"""Preview helpers for input-fingerprint stale-output protection.

This module is intentionally read-only. It does not write formulas or hidden
columns; it only shows what formula mode would display if the sheet had already
been migrated to raw-output + input-key columns.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from src.sheets import (
    HEADER_AREA,
    HEADER_CURRENT_INPUT_KEY,
    HEADER_JISIKIN,
    HEADER_KEYWORD,
    HEADER_L,
    HEADER_LAST_CHECKED_AT,
    HEADER_LAST_CHECKED_INPUT_KEY,
    HEADER_LINK,
    HEADER_M,
    HEADER_RAW_AREA,
    HEADER_RAW_JISIKIN,
    HEADER_RAW_L,
    HEADER_RAW_M,
    INPUT_KEY_VERSION,
    STALE_DISPLAY_K,
)
from src.transitions import SYSTEM_K_VALUES, parse_K_with_stamp


FORMULA_MODE_REQUIRED_HEADERS = (
    HEADER_CURRENT_INPUT_KEY,
    HEADER_LAST_CHECKED_INPUT_KEY,
    HEADER_RAW_AREA,
    HEADER_RAW_L,
    HEADER_RAW_M,
    HEADER_RAW_JISIKIN,
)


def _clean(value: object) -> str:
    return str(value or "").strip()


def _normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", _clean(value)).casefold()


def _normalize_link(value: object) -> str:
    text = _clean(value).casefold()
    if not text:
        return ""
    parsed = urlparse(text)
    if not parsed.netloc:
        return text.rstrip("/")
    netloc = parsed.netloc
    if netloc.startswith("m."):
        netloc = netloc[2:]
    path = re.sub(r"/+", "/", parsed.path).rstrip("/")
    return f"{netloc}{path}"


def _hash_value(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _redact_text(value: object, *, keep: int = 2) -> str:
    text = _clean(value)
    if not text:
        return ""
    if len(text) <= keep * 2:
        return "*" * len(text)
    return f"{text[:keep]}...{text[-keep:]}"


def build_input_key(row: dict) -> str:
    """Build the search-input fingerprint from keyword + link only.

    Type(C), current K/L/M/O, worker, date, volume, and other user columns must
    not affect this key. Only changing the keyword or target link should make a
    previous rank result stale.
    """
    keyword = _normalize_text(row.get(HEADER_KEYWORD, ""))
    link = _normalize_link(row.get(HEADER_LINK, ""))
    if not keyword and not link:
        return ""
    return f"{INPUT_KEY_VERSION}|{keyword}|{link}"


def _formula_mode_ready(row: dict) -> bool:
    return all(header in row for header in FORMULA_MODE_REQUIRED_HEADERS)


def _has_any_relevant_value(row: dict) -> bool:
    relevant_headers = (
        HEADER_KEYWORD,
        HEADER_LINK,
        HEADER_AREA,
        HEADER_L,
        HEADER_M,
        HEADER_JISIKIN,
        *FORMULA_MODE_REQUIRED_HEADERS,
    )
    return any(_clean(row.get(header, "")) for header in relevant_headers)


def _blank_outputs() -> dict[str, str]:
    return {
        "would_show_k": "",
        "would_show_l": "",
        "would_show_m": "",
        "would_show_jisikin": "",
    }


def _stale_outputs() -> dict[str, str]:
    return {
        "would_show_k": STALE_DISPLAY_K,
        "would_show_l": "",
        "would_show_m": "",
        "would_show_jisikin": "",
    }


def _raw_outputs(row: dict) -> dict[str, str]:
    return {
        "would_show_k": _clean(row.get(HEADER_RAW_AREA, "")),
        "would_show_l": _clean(row.get(HEADER_RAW_L, "")),
        "would_show_m": _clean(row.get(HEADER_RAW_M, "")),
        "would_show_jisikin": _clean(row.get(HEADER_RAW_JISIKIN, "")),
    }


def build_stale_preview_row(row: dict) -> dict:
    current_key = build_input_key(row)
    last_key = _clean(row.get(HEADER_LAST_CHECKED_INPUT_KEY, ""))
    sheet_current_key = _clean(row.get(HEADER_CURRENT_INPUT_KEY, ""))
    ready = _formula_mode_ready(row)
    visible_k = _clean(row.get(HEADER_AREA, ""))
    visible_k_base, _ = parse_K_with_stamp(visible_k)
    manual_visible_k = bool(visible_k_base and visible_k_base not in SYSTEM_K_VALUES)

    if not ready:
        status = "no_baseline"
        reason = "hidden_columns_missing"
        would_mask = False
        would_outputs = {
            "would_show_k": visible_k,
            "would_show_l": _clean(row.get(HEADER_L, "")),
            "would_show_m": _clean(row.get(HEADER_M, "")),
            "would_show_jisikin": _clean(row.get(HEADER_JISIKIN, "")),
        }
    elif sheet_current_key and sheet_current_key != current_key:
        status = "baseline_conflict"
        reason = "sheet_current_input_key_differs_from_computed_key"
        would_mask = False
        would_outputs = _stale_outputs()
    elif not current_key:
        status = "blank_input"
        reason = "current_keyword_and_link_blank"
        would_mask = any(
            _clean(row.get(header, ""))
            for header in (HEADER_AREA, HEADER_L, HEADER_M, HEADER_JISIKIN)
        )
        would_outputs = _blank_outputs()
    elif not last_key:
        status = "never_checked"
        reason = "last_checked_input_key_empty"
        would_mask = True
        would_outputs = _stale_outputs()
    elif current_key != last_key:
        if manual_visible_k:
            status = "manual_visible_k"
            reason = "visible_k_not_system_owned"
            would_mask = False
            would_outputs = {
                "would_show_k": visible_k,
                "would_show_l": _clean(row.get(HEADER_L, "")),
                "would_show_m": _clean(row.get(HEADER_M, "")),
                "would_show_jisikin": _clean(row.get(HEADER_JISIKIN, "")),
            }
        else:
            status = "stale_input"
            reason = "current_input_differs_from_last_check"
            would_mask = True
            would_outputs = _stale_outputs()
    else:
        status = "current"
        reason = "input_key_matches_last_check"
        would_mask = False
        would_outputs = _raw_outputs(row)

    preview = {
        "tab": _clean(row.get("_tab", "")),
        "row": row.get("_row"),
        "keyword_display": _redact_text(row.get(HEADER_KEYWORD, "")),
        "keyword_hash": _hash_value(_normalize_text(row.get(HEADER_KEYWORD, ""))),
        "link_empty": not bool(_clean(row.get(HEADER_LINK, ""))),
        "visible_k": visible_k,
        "visible_l": _clean(row.get(HEADER_L, "")),
        "visible_m": _clean(row.get(HEADER_M, "")),
        "visible_o": _clean(row.get(HEADER_JISIKIN, "")),
        "input_key_current_hash": _hash_value(current_key),
        "input_key_sheet_current_hash": _hash_value(sheet_current_key),
        "input_key_baseline_hash": _hash_value(last_key),
        "last_checked_at": _clean(row.get(HEADER_LAST_CHECKED_AT, "")),
        "raw_k": _clean(row.get(HEADER_RAW_AREA, "")),
        "raw_l": _clean(row.get(HEADER_RAW_L, "")),
        "raw_m": _clean(row.get(HEADER_RAW_M, "")),
        "raw_o": _clean(row.get(HEADER_RAW_JISIKIN, "")),
        "baseline_available": ready,
        "formula_mode_ready": ready,
        "freshness_status": status,
        "would_mask_stale_output": would_mask,
        "reason": reason,
    }
    preview.update(would_outputs)
    return preview


def build_stale_preview_rows(data: dict[str, list[dict]]) -> list[dict]:
    rows: list[dict] = []
    for tab_name, tab_rows in data.items():
        for row in tab_rows:
            if not _has_any_relevant_value(row):
                continue
            row_with_tab = dict(row)
            row_with_tab.setdefault("_tab", tab_name)
            rows.append(build_stale_preview_row(row_with_tab))
    rows.sort(key=lambda item: (_clean(item.get("tab", "")), int(item.get("row") or 0)))
    return rows


def summarize_stale_preview(rows: Iterable[dict]) -> dict:
    rows = list(rows)
    total = len(rows)
    initialized = sum(1 for row in rows if row.get("formula_mode_ready") is True)
    stale = sum(1 for row in rows if row.get("freshness_status") == "stale_input")
    never_checked = sum(1 for row in rows if row.get("freshness_status") == "never_checked")
    no_baseline = sum(1 for row in rows if row.get("freshness_status") == "no_baseline")
    baseline_conflict = sum(1 for row in rows if row.get("freshness_status") == "baseline_conflict")
    manual_visible_k = sum(1 for row in rows if row.get("freshness_status") == "manual_visible_k")
    blank_input = sum(1 for row in rows if row.get("freshness_status") == "blank_input")
    would_mask = sum(1 for row in rows if row.get("would_mask_stale_output") is True)
    return {
        "stale_preview_rows": total,
        "stale_preview_initialized_rows": initialized,
        "stale_preview_stale_rows": stale,
        "stale_preview_never_checked_rows": never_checked,
        "stale_preview_no_baseline_rows": no_baseline,
        "stale_preview_baseline_conflict_rows": baseline_conflict,
        "stale_preview_manual_visible_k_rows": manual_visible_k,
        "stale_preview_blank_input_rows": blank_input,
        "stale_preview_would_mask_rows": would_mask,
    }


def write_stale_preview_artifact(path: str | Path, rows: Iterable[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            f.write("\n")


def _markdown_cell(value: object) -> str:
    text = _clean(value)
    return text.replace("\n", " ").replace("|", "\\|")


def _markdown_table(rows: list[dict], *, limit: int = 100) -> str:
    if not rows:
        return "_No rows._"
    lines = [
        "| tab | row | keyword | status | visible_k | would_show_k | reason |",
        "| --- | ---: | --- | --- | --- | --- | --- |",
    ]
    for row in rows[:limit]:
        lines.append(
            "| {tab} | {row} | {keyword} | {status} | {visible_k} | {would_show_k} | {reason} |".format(
                tab=_markdown_cell(row.get("tab", "")),
                row=_markdown_cell(row.get("row", "")),
                keyword=_markdown_cell(row.get("keyword_display", "")),
                status=_markdown_cell(row.get("freshness_status", "")),
                visible_k=_markdown_cell(row.get("visible_k", "")),
                would_show_k=_markdown_cell(row.get("would_show_k", "")),
                reason=_markdown_cell(row.get("reason", "")),
            )
        )
    if len(rows) > limit:
        lines.append(f"\n_Showing first {limit} of {len(rows)} rows._")
    return "\n".join(lines)


def write_stale_preview_summary_artifact(
    path: str | Path,
    rows: Iterable[dict],
    summary: dict,
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    masked_rows = [row for row in rows if row.get("would_mask_stale_output") is True]
    no_baseline_rows = [row for row in rows if row.get("freshness_status") == "no_baseline"]

    text = "\n".join(
        [
            "# Stale Output Preview",
            "",
            f"- Preview rows: {summary.get('stale_preview_rows', len(rows))}",
            f"- Formula-mode initialized rows: {summary.get('stale_preview_initialized_rows', 0)}",
            f"- Stale input rows: {summary.get('stale_preview_stale_rows', 0)}",
            f"- Never-checked rows: {summary.get('stale_preview_never_checked_rows', 0)}",
            f"- No-baseline rows: {summary.get('stale_preview_no_baseline_rows', 0)}",
            f"- Baseline-conflict rows: {summary.get('stale_preview_baseline_conflict_rows', 0)}",
            f"- Manual visible-K rows: {summary.get('stale_preview_manual_visible_k_rows', 0)}",
            f"- Would mask rows: {summary.get('stale_preview_would_mask_rows', 0)}",
            "",
            "## Rows That Would Be Masked",
            "",
            _markdown_table(masked_rows),
            "",
            "## Rows Without Baseline Columns",
            "",
            _markdown_table(no_baseline_rows),
            "",
            "## Meaning Check",
            "",
            "- input_key = normalized keyword + normalized link only; artifacts store hashes and redacted keywords.",
            "- When current input_key differs from last_checked_input_key, K would show 재검사필요 and L/M/O would be blank.",
            "- This preview does not write formulas, hidden columns, raw outputs, or visible K/L/M/O cells.",
            "",
        ]
    )
    path.write_text(text, encoding="utf-8", newline="\n")
