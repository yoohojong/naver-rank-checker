"""Audit helpers for sheet output invariants and row-level trace artifacts."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable, Optional

from src.sheets import RowUpdate, HEADER_AREA, HEADER_LINK, HEADER_L, HEADER_M, HEADER_JISIKIN
from src.transitions import parse_K_with_stamp


PLAIN_EXPOSED_BASES = frozenset({"AB", "스마트블록", "인기글"})
DUPLICATE_BASE_PREFIX = "중복노출"


def _clean(value: object) -> str:
    return str(value or "").strip()


def _row_meta(tab_name: str, row: dict, columns: dict, code: str) -> dict:
    k_full = _clean(columns.get(HEADER_AREA, row.get(HEADER_AREA, "")))
    k_base, _ = parse_K_with_stamp(k_full)
    return {
        "code": code,
        "tab": tab_name,
        "row": row.get("_row"),
        "keyword": row.get("키워드", ""),
        "original_link": _clean(row.get(HEADER_LINK, "")),
        "output_link": _clean(columns.get(HEADER_LINK, "")),
        "k_full": k_full,
        "k_base": k_base,
        "L": _clean(columns.get(HEADER_L, row.get(HEADER_L, ""))),
        "M": _clean(columns.get(HEADER_M, row.get(HEADER_M, ""))),
    }


def validate_row_output(tab_name: str, row: dict, columns: dict) -> Optional[dict]:
    """Validate one pending RowUpdate against source-row invariants.

    A row whose original sheet link is blank must not be written as a plain
    exposure (`AB`, `스마트블록`, `인기글`). Blank-link discoveries are only valid
    when they are duplicate-exposure outputs and include the matched link.
    """
    original_link = _clean(row.get(HEADER_LINK, ""))
    if original_link:
        return None

    k_full = _clean(columns.get(HEADER_AREA, ""))
    k_base, _ = parse_K_with_stamp(k_full)

    if k_base in PLAIN_EXPOSED_BASES:
        return _row_meta(tab_name, row, columns, "EMPTY_LINK_PLAIN_EXPOSED")

    if (columns.get(HEADER_L) or columns.get(HEADER_M)) and not k_base.startswith(DUPLICATE_BASE_PREFIX):
        return _row_meta(tab_name, row, columns, "EMPTY_LINK_RANK_WITHOUT_DUPLICATE")

    if k_base.startswith(DUPLICATE_BASE_PREFIX) and not _clean(columns.get(HEADER_LINK, "")):
        return _row_meta(tab_name, row, columns, "EMPTY_LINK_DUPLICATE_WITHOUT_LINK")

    return None


def filter_invalid_updates(
    tab_updates: dict[str, list[RowUpdate]],
    row_context: dict[tuple[str, int], dict],
) -> tuple[dict[str, list[RowUpdate]], list[dict]]:
    """Drop impossible RowUpdates before batch write.

    Returning a filtered copy keeps callers from mutating the in-memory update
    list before trace artifacts are generated.
    """
    filtered: dict[str, list[RowUpdate]] = {}
    issues: list[dict] = []
    for tab_name, updates in tab_updates.items():
        kept: list[RowUpdate] = []
        for upd in updates:
            row = row_context.get((tab_name, upd.row), {"_tab": tab_name, "_row": upd.row})
            issue = validate_row_output(tab_name, row, upd.columns)
            if issue:
                issues.append(issue)
                continue
            kept.append(upd)
        filtered[tab_name] = kept
    return filtered, issues


def audit_sheet_rows(data: dict[str, list[dict]]) -> list[dict]:
    """Audit current sheet rows for impossible persisted states."""
    issues: list[dict] = []
    for tab_name, rows in data.items():
        for row in rows:
            link = _clean(row.get(HEADER_LINK, ""))
            if link:
                continue
            columns = {
                HEADER_AREA: row.get(HEADER_AREA, ""),
                HEADER_L: row.get(HEADER_L, ""),
                HEADER_M: row.get(HEADER_M, ""),
            }
            issue = validate_row_output(tab_name, row, columns)
            if not issue:
                continue
            issue["code"] = issue["code"].replace("EMPTY_LINK", "SHEET_EMPTY_LINK", 1)
            issues.append(issue)
    return issues


def build_update_trace(
    tab_updates: dict[str, list[RowUpdate]],
    row_context: dict[tuple[str, int], dict],
    invalid_issues: Iterable[dict],
) -> list[dict]:
    """Build final per-row trace rows for updates and pre-write skips."""
    issue_by_key = {(i.get("tab"), i.get("row")): i for i in invalid_issues}
    traces: list[dict] = []
    for tab_name, updates in tab_updates.items():
        for upd in updates:
            row = row_context.get((tab_name, upd.row), {"_tab": tab_name, "_row": upd.row})
            k_full = _clean(upd.columns.get(HEADER_AREA, ""))
            k_base, _ = parse_K_with_stamp(k_full)
            issue = issue_by_key.get((tab_name, upd.row))
            status = "invalid_skipped" if issue else "write_ready"
            trace = {
                "status": status,
                "tab": tab_name,
                "row": upd.row,
                "keyword": row.get("키워드", ""),
                "original_link_empty": not _clean(row.get(HEADER_LINK, "")),
                "original_link": _clean(row.get(HEADER_LINK, "")),
                "output_link": _clean(upd.columns.get(HEADER_LINK, "")),
                "prev_K": _clean(row.get(HEADER_AREA, "")),
                "new_K": k_full,
                "new_K_base": k_base,
                "L": _clean(upd.columns.get(HEADER_L, "")),
                "M": _clean(upd.columns.get(HEADER_M, "")),
                "jisikin": _clean(upd.columns.get(HEADER_JISIKIN, "")),
                "matched_area": _clean(upd.columns.get("_matched_area", "")),
                "row_link_meta": _clean(upd.columns.get("_row_link", "")),
            }
            if issue:
                trace["issue_code"] = issue.get("code", "")
            traces.append(trace)
    traces.sort(key=lambda x: (x.get("tab", ""), int(x.get("row") or 0), x.get("status", "")))
    return traces


def write_jsonl(path: str | os.PathLike, rows: Iterable[dict]) -> None:
    """Write rows as UTF-8 JSONL, creating parent directories."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            f.write("\n")
