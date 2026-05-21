"""Type preview artifact helpers.

The type preview is a read-only proposal for the sheet C column ("유형").
It must never be passed to SheetsClient.write_results as a writable column.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

from src.parser import RankResult
from src.sheets import HEADER_AREA, HEADER_LINK, HEADER_TYPE
from src.transitions import parse_K_with_stamp


TYPE_PREVIEW_FIELDS = [
    "tab",
    "row",
    "keyword",
    "current_type",
    "suggested_type",
    "block_order",
    "k_area",
    "link_empty",
    "parser_confidence",
    "html_status",
    "reason",
    "would_update",
]

SAFE_HTML_STATUS = "ok"
TYPE_PREVIEW_BULK_MAX_UPDATE_COUNT = 100
TYPE_PREVIEW_BULK_MAX_UPDATE_RATIO = 0.50
TYPE_PREVIEW_BULK_MIN_ROWS_FOR_RATIO = 50


def _clean(value: object) -> str:
    return str(value or "").strip()


def html_status_from_html(html: str) -> str:
    """Classify fetched HTML for preview safety.

    Crawler normally raises on very short or blocked responses, but tests and
    defensive paths can still pass empty HTML directly into the parser.
    """
    if not html or len(html) < 500:
        return "empty_html"
    return SAFE_HTML_STATUS


def suggested_type_from_block_order(block_order: Iterable[str]) -> str:
    """Return the top representative slot type for the keyword result page."""
    for item in block_order or []:
        item = _clean(item)
        if item:
            return item
    return ""


def _reason_for_preview(
    *,
    html_status: str,
    suggested_type: str,
    current_type: str,
    reason: str,
    would_update: bool,
) -> str:
    if reason:
        return reason
    if html_status == "empty_html":
        return "empty_html_or_too_short"
    if html_status == "blocked":
        return "blocked_or_crawler_error"
    if html_status == "parse_failed":
        return "parse_failed"
    if html_status == "not_fetched":
        return "not_fetched"
    if not suggested_type:
        return "no_type_detected"
    if would_update:
        return "suggested_type_differs"
    if suggested_type == current_type:
        return "already_current"
    return "no_update"


def build_type_preview_row(
    *,
    row: dict,
    result: Optional[RankResult] = None,
    columns: Optional[dict] = None,
    html_status: str = SAFE_HTML_STATUS,
    reason: str = "",
) -> dict:
    """Build one preview row with the exact external artifact schema."""
    block_order = list(result.block_order) if result is not None else []
    suggested_type = suggested_type_from_block_order(block_order)
    current_type = _clean(row.get(HEADER_TYPE, ""))
    k_full = _clean((columns or {}).get(HEADER_AREA, row.get(HEADER_AREA, "")))
    k_area, _ = parse_K_with_stamp(k_full)
    parser_confidence = float(result.parser_confidence) if result is not None else 0.0

    would_update = (
        html_status == SAFE_HTML_STATUS
        and bool(suggested_type)
        and suggested_type != current_type
    )
    final_reason = _reason_for_preview(
        html_status=html_status,
        suggested_type=suggested_type,
        current_type=current_type,
        reason=reason,
        would_update=would_update,
    )

    return {
        "tab": _clean(row.get("_tab", "")),
        "row": row.get("_row"),
        "keyword": _clean(row.get("키워드", "")),
        "current_type": current_type,
        "suggested_type": suggested_type,
        "block_order": block_order,
        "k_area": k_area,
        "link_empty": not bool(_clean(row.get(HEADER_LINK, ""))),
        "parser_confidence": parser_confidence,
        "html_status": html_status,
        "reason": final_reason,
        "would_update": would_update,
    }


def build_type_preview_error_row(*, row: dict, html_status: str, reason: str) -> dict:
    """Build a safe no-update preview row for blocked/parser-failed paths."""
    return build_type_preview_row(
        row=row,
        result=None,
        columns=None,
        html_status=html_status,
        reason=reason,
    )


class TypePreviewCollector:
    """Keep one latest preview row per sheet row.

    Retries can process the same row more than once. Last write wins so the
    artifact stays one row per keyword row instead of one row per attempt.
    """

    def __init__(self) -> None:
        self._rows: dict[tuple[str, int], dict] = {}

    def add(self, preview_row: dict) -> None:
        key = (_clean(preview_row.get("tab", "")), int(preview_row.get("row") or 0))
        self._rows[key] = preview_row

    def rows(self) -> list[dict]:
        return [
            self._rows[key]
            for key in sorted(self._rows, key=lambda item: (item[0], item[1]))
        ]


def apply_final_k_area_to_preview_rows(
    preview_rows: list[dict],
    tab_updates: dict,
) -> list[dict]:
    """Reflect final K-area values after pass-2 duplicate updates."""
    final_k_by_row: dict[tuple[str, int], str] = {}
    for tab_name, updates in tab_updates.items():
        for upd in updates:
            k_full = _clean(upd.columns.get(HEADER_AREA, ""))
            if not k_full:
                continue
            k_area, _ = parse_K_with_stamp(k_full)
            final_k_by_row[(tab_name, upd.row)] = k_area

    for preview in preview_rows:
        key = (_clean(preview.get("tab", "")), int(preview.get("row") or 0))
        if key in final_k_by_row:
            preview["k_area"] = final_k_by_row[key]
    return preview_rows


def summarize_type_preview(
    rows: Iterable[dict],
    *,
    max_update_count: int = TYPE_PREVIEW_BULK_MAX_UPDATE_COUNT,
    max_update_ratio: float = TYPE_PREVIEW_BULK_MAX_UPDATE_RATIO,
    min_rows_for_ratio_guard: int = TYPE_PREVIEW_BULK_MIN_ROWS_FOR_RATIO,
) -> dict:
    rows = list(rows)
    total = len(rows)
    would_update = sum(1 for row in rows if row.get("would_update") is True)
    ratio = (would_update / total) if total else 0.0
    bulk_guard = would_update > max_update_count or (
        total >= min_rows_for_ratio_guard and ratio > max_update_ratio
    )
    return {
        "type_preview_rows": total,
        "type_preview_would_update_rows": would_update,
        "type_preview_update_ratio": ratio,
        "type_preview_bulk_guard_triggered": bulk_guard,
    }


def audit_type_preview_writes(type_preview_rows: Iterable[dict], post_write_data: dict[str, list[dict]]) -> list[dict]:
    """Verify confirmed C-column writes against freshly loaded sheet rows."""
    row_by_key: dict[tuple[str, int], dict] = {}
    for tab_name, rows in post_write_data.items():
        for row in rows:
            try:
                row_num = int(row.get("_row") or 0)
            except (TypeError, ValueError):
                continue
            if row_num:
                row_by_key[(_clean(tab_name), row_num)] = row

    issues: list[dict] = []
    for preview in type_preview_rows:
        if preview.get("would_update") is not True:
            continue
        if _clean(preview.get("html_status", "")) != SAFE_HTML_STATUS:
            continue
        suggested_type = _clean(preview.get("suggested_type", ""))
        tab_name = _clean(preview.get("tab", ""))
        try:
            row_num = int(preview.get("row") or 0)
        except (TypeError, ValueError):
            row_num = 0
        if not suggested_type or not tab_name or not row_num:
            continue

        row = row_by_key.get((tab_name, row_num))
        if row is None:
            issues.append({
                "code": "TYPE_WRITE_ROW_MISSING",
                "tab": tab_name,
                "row": row_num,
                "keyword": _clean(preview.get("keyword", "")),
                "suggested_type": suggested_type,
                "actual_type": "",
            })
            continue

        actual_type = _clean(row.get(HEADER_TYPE, ""))
        if actual_type != suggested_type:
            issues.append({
                "code": "TYPE_WRITE_MISMATCH",
                "tab": tab_name,
                "row": row_num,
                "keyword": _clean(preview.get("keyword", row.get("키워드", ""))),
                "suggested_type": suggested_type,
                "actual_type": actual_type,
            })
    return issues


def _markdown_cell(value: object) -> str:
    if isinstance(value, list):
        value = ", ".join(_clean(item) for item in value)
    text = _clean(value)
    return text.replace("\n", " ").replace("|", "\\|")


def _markdown_table(rows: list[dict], *, limit: int = 100) -> str:
    if not rows:
        return "_No rows._"

    lines = [
        "| tab | row | keyword | current_type | suggested_type | k_area | html_status | reason |",
        "| --- | ---: | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows[:limit]:
        lines.append(
            "| {tab} | {row} | {keyword} | {current_type} | {suggested_type} | "
            "{k_area} | {html_status} | {reason} |".format(
                tab=_markdown_cell(row.get("tab", "")),
                row=_markdown_cell(row.get("row", "")),
                keyword=_markdown_cell(row.get("keyword", "")),
                current_type=_markdown_cell(row.get("current_type", "")),
                suggested_type=_markdown_cell(row.get("suggested_type", "")),
                k_area=_markdown_cell(row.get("k_area", "")),
                html_status=_markdown_cell(row.get("html_status", "")),
                reason=_markdown_cell(row.get("reason", "")),
            )
        )
    if len(rows) > limit:
        lines.append(f"\n_Showing first {limit} of {len(rows)} rows._")
    return "\n".join(lines)


def write_type_preview_summary_artifact(
    path: str | Path,
    rows: Iterable[dict],
    summary: dict,
    *,
    write_confirmed: bool = False,
    bulk_write_allowed: bool = False,
) -> None:
    """Write a human-readable approval checklist next to the JSONL artifact."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    rows = list(rows)
    candidates = [row for row in rows if row.get("would_update") is True]
    attention_rows = [
        row
        for row in rows
        if _clean(row.get("html_status", "")) != SAFE_HTML_STATUS
        or _clean(row.get("reason", "")) not in ("already_current", "suggested_type_differs")
    ]
    guard = bool(summary.get("type_preview_bulk_guard_triggered", False))
    bulk_blocked = write_confirmed and guard and not bulk_write_allowed
    if bulk_blocked:
        status = "HOLD - bulk-change guard blocked C-column write"
    elif write_confirmed:
        status = "C-column write enabled"
    elif guard:
        status = "HOLD - bulk-change guard triggered"
    else:
        status = "Review ready"

    confirm_line = (
        "- Confirm phrase: `preview 확인했어. C열 write 허용 단계 진행해.`"
        if not write_confirmed
        else "- Confirm phrase: not needed; C-column write mode was already enabled for this run."
    )
    if bulk_blocked:
        write_line = "- C column write is blocked by the bulk-change guard in this run."
    elif write_confirmed:
        write_line = "- C column write is enabled for safe would_update rows in this run."
    else:
        write_line = "- C column is not written in this preview stage."

    text = "\n".join(
        [
            "# Type Preview Review",
            "",
            f"- Status: {status}",
            f"- Preview rows: {summary.get('type_preview_rows', len(rows))}",
            f"- C column candidates: {summary.get('type_preview_would_update_rows', len(candidates))}",
            f"- Update ratio: {summary.get('type_preview_update_ratio', 0):.1%}",
            f"- Bulk-change guard: {'TRIGGERED' if guard else 'ok'}",
            confirm_line,
            "",
            "## C Column Candidates",
            "",
            _markdown_table(candidates),
            "",
            "## Rows Needing Attention",
            "",
            _markdown_table(attention_rows),
            "",
            "## Meaning Check",
            "",
            "- suggested_type = top representative slot from keyword search result.",
            "- k_area = actual exposure/status for your link in column K.",
            write_line,
            "",
        ]
    )
    path.write_text(text, encoding="utf-8", newline="\n")


def write_type_preview_artifact(path: str | Path, rows: Iterable[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False))
            f.write("\n")
