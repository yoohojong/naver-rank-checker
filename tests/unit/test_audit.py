"""Audit/invariant tests for sheet output safety.

These tests protect the D-023/D-024 rule: never let impossible output states
silently reach the sheet.
"""
import json

from src.sheets import RowUpdate, HEADER_AREA, HEADER_LINK, HEADER_L, HEADER_M


def test_empty_link_exposed_rank_output_is_invalid():
    """A blank-link row cannot end as plain exposed K with ranks."""
    from src.audit import validate_row_output

    row = {"_tab": "바디워시 카외", "_row": 205, "키워드": "퍼퓸바디워시", HEADER_LINK: ""}
    columns = {
        HEADER_AREA: "인기글 (5/19 00:00~)",
        HEADER_L: "2",
        HEADER_M: "1",
    }

    issue = validate_row_output("바디워시 카외", row, columns)

    assert issue is not None
    assert issue["code"] == "EMPTY_LINK_PLAIN_EXPOSED"
    assert issue["row"] == 205
    assert issue["k_base"] == "인기글"


def test_empty_link_duplicate_autofill_output_is_valid():
    """A blank-link row may be auto-filled only as duplicate exposure."""
    from src.audit import validate_row_output

    row = {"_tab": "바디워시 카외", "_row": 205, "키워드": "퍼퓸바디워시", HEADER_LINK: ""}
    columns = {
        HEADER_AREA: "중복노출(인기글) (5/19 12:00~)",
        HEADER_LINK: "https://cafe.naver.com/cosmania/12345",
        HEADER_L: "2",
        HEADER_M: "1",
    }

    assert validate_row_output("바디워시 카외", row, columns) is None


def test_filter_invalid_updates_skips_bad_update_and_keeps_good():
    """Pre-write gate removes impossible rows instead of writing them."""
    from src.audit import filter_invalid_updates

    bad_row = {"_tab": "바디워시 카외", "_row": 205, "키워드": "퍼퓸바디워시", HEADER_LINK: ""}
    good_row = {
        "_tab": "바디워시 카외",
        "_row": 206,
        "키워드": "정상",
        HEADER_LINK: "https://cafe.naver.com/cosmania/999",
    }
    tab_updates = {
        "바디워시 카외": [
            RowUpdate(row=205, columns={HEADER_AREA: "인기글", HEADER_L: "2", HEADER_M: "1"}),
            RowUpdate(row=206, columns={HEADER_AREA: "인기글", HEADER_L: "2", HEADER_M: "1"}),
        ]
    }
    row_context = {
        ("바디워시 카외", 205): bad_row,
        ("바디워시 카외", 206): good_row,
    }

    filtered, issues = filter_invalid_updates(tab_updates, row_context)

    assert [u.row for u in filtered["바디워시 카외"]] == [206]
    assert len(issues) == 1
    assert issues[0]["row"] == 205


def test_audit_sheet_rows_flags_stale_invalid_sheet_state():
    """Post-write audit catches impossible states already present in sheet."""
    from src.audit import audit_sheet_rows

    data = {
        "바디워시 카외": [
            {"_row": 205, "키워드": "퍼퓸바디워시", HEADER_LINK: "", HEADER_AREA: "인기글", HEADER_L: "2", HEADER_M: "1"},
            {"_row": 206, "키워드": "정상", HEADER_LINK: "", HEADER_AREA: "미노출", HEADER_L: "", HEADER_M: ""},
        ]
    }

    issues = audit_sheet_rows(data)

    assert len(issues) == 1
    assert issues[0]["code"] == "SHEET_EMPTY_LINK_PLAIN_EXPOSED"
    assert issues[0]["row"] == 205


def test_write_jsonl_trace_writes_one_json_object_per_line(tmp_path):
    """Trace artifact must be grep-friendly JSONL."""
    from src.audit import write_jsonl

    path = tmp_path / "row-trace.jsonl"
    rows = [{"row": 205, "status": "invalid"}, {"row": 206, "status": "written"}]

    write_jsonl(path, rows)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["row"] for line in lines] == [205, 206]
