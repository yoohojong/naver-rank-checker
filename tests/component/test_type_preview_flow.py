import json
from unittest.mock import MagicMock, patch

from src.crawler import CrawlerError
from src.parser import ExposureArea, RankResult
from src.sheets import (
    HEADER_AREA,
    HEADER_CURRENT_INPUT_KEY,
    HEADER_LAST_CHECKED_INPUT_KEY,
    HEADER_LINK,
    HEADER_RAW_AREA,
    HEADER_RAW_JISIKIN,
    HEADER_RAW_L,
    HEADER_RAW_M,
    HEADER_TYPE,
)
from src.stale_preview import build_input_key


def _service_account_json() -> str:
    return '{"type":"service_account","client_email":"x@x.iam.gserviceaccount.com","private_key":"-----BEGIN PRIVATE KEY-----\\nFAKE\\n-----END PRIVATE KEY-----\\n","token_uri":"https://oauth2.googleapis.com/token"}'


def _base_rows() -> dict:
    return {
        "샴푸 카외": [
            {
                "_row": 2,
                "_tab": "샴푸 카외",
                "키워드": "탈모샴푸",
                HEADER_LINK: "https://cafe.naver.com/cosmania/123",
                HEADER_TYPE: "",
                HEADER_AREA: "",
            }
        ]
    }


def _rows_with_type(type_value: str) -> dict:
    rows = _base_rows()
    rows["샴푸 카외"][0][HEADER_TYPE] = type_value
    return rows


def _many_base_rows(count: int) -> dict:
    return {
        "샴푸 카외": [
            {
                "_row": row_num,
                "_tab": "샴푸 카외",
                "키워드": f"탈모샴푸{row_num}",
                HEADER_LINK: f"https://cafe.naver.com/cosmania/{1000 + row_num}",
                HEADER_TYPE: "",
                HEADER_AREA: "",
            }
            for row_num in range(2, 2 + count)
        ]
    }


def _formula_ready_rows_with_one_stale() -> dict:
    stale_row = {
        "_row": 2,
        "_tab": "샴푸 카외",
        "키워드": "탈모샴푸",
        HEADER_LINK: "https://cafe.naver.com/cosmania/123",
        HEADER_TYPE: "",
        HEADER_AREA: "재검사필요",
        HEADER_RAW_AREA: "AB",
        HEADER_RAW_L: "1",
        HEADER_RAW_M: "1",
        HEADER_RAW_JISIKIN: "",
    }
    current_row = {
        "_row": 3,
        "_tab": "샴푸 카외",
        "키워드": "비듬샴푸",
        HEADER_LINK: "https://cafe.naver.com/cosmania/456",
        HEADER_TYPE: "",
        HEADER_AREA: "AB",
        HEADER_RAW_AREA: "AB",
        HEADER_RAW_L: "1",
        HEADER_RAW_M: "1",
        HEADER_RAW_JISIKIN: "",
    }
    stale_row[HEADER_CURRENT_INPUT_KEY] = build_input_key(stale_row)
    stale_row[HEADER_LAST_CHECKED_INPUT_KEY] = "v1|이전키워드|cafe.naver.com/cosmania/123"
    current_row[HEADER_CURRENT_INPUT_KEY] = build_input_key(current_row)
    current_row[HEADER_LAST_CHECKED_INPUT_KEY] = build_input_key(current_row)
    return {"샴푸 카외": [stale_row, current_row]}


def _matched_result(area: ExposureArea = ExposureArea.AB, block_order=None) -> RankResult:
    result = RankResult()
    result.exposure_area = area
    result.integrated_rank = 1
    result.cafe_slot_rank = 1
    result.block_order = block_order if block_order is not None else [area.value]
    result.parser_confidence = 0.9
    result.matched_url = "https://cafe.naver.com/cosmania/123"
    return result


def _run_cycle_with_mocks(
    tmp_path,
    monkeypatch,
    rows,
    crawler,
    parse_result=None,
    parse_error=None,
    type_write_confirmed=False,
    type_write_allow_bulk=False,
    stale_formula_mode=False,
    recheck_stale_only=False,
    post_write_rows=None,
    type_write_cells=0,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_RUN_ID", "preview123")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    if type_write_confirmed:
        monkeypatch.setenv("TYPE_PREVIEW_WRITE_CONFIRMED", "true")
    else:
        monkeypatch.delenv("TYPE_PREVIEW_WRITE_CONFIRMED", raising=False)
    if type_write_allow_bulk:
        monkeypatch.setenv("TYPE_PREVIEW_WRITE_ALLOW_BULK", "true")
    else:
        monkeypatch.delenv("TYPE_PREVIEW_WRITE_ALLOW_BULK", raising=False)
    if stale_formula_mode:
        monkeypatch.setenv("STALE_OUTPUT_FORMULA_MODE", "true")
    else:
        monkeypatch.delenv("STALE_OUTPUT_FORMULA_MODE", raising=False)
    if recheck_stale_only:
        monkeypatch.setenv("RECHECK_STALE_ONLY", "true")
    else:
        monkeypatch.delenv("RECHECK_STALE_ONLY", raising=False)
    monkeypatch.setattr("src.main.SPREADSHEET_ID", "fake_id")
    monkeypatch.setattr("src.main.SERVICE_ACCOUNT_JSON", _service_account_json())

    mock_client = MagicMock()
    if stale_formula_mode:
        mock_client.load_all_data_tabs.side_effect = [rows, rows, post_write_rows or rows]
    else:
        mock_client.load_all_data_tabs.side_effect = [rows, post_write_rows or rows]
    mock_client.write_results.return_value = 0
    mock_client.ensure_stale_formula_mode.return_value = {"headers_added": 0, "rows_backfilled": 0, "formula_rows": len(next(iter(rows.values()), []))}
    mock_client.write_stale_formula_results.return_value = 6
    mock_client.write_type_results.return_value = type_write_cells
    mock_client.write_timestamp.return_value = None

    patches = [
        patch("src.main.SheetsClient", return_value=mock_client),
        patch("src.main.Crawler", return_value=crawler),
        patch("src.main.random.shuffle", side_effect=lambda values: None),
    ]
    if parse_error is not None:
        patches.append(patch("src.main.parse_search_result", side_effect=parse_error))
    elif parse_result is not None:
        patches.append(patch("src.main.parse_search_result", return_value=parse_result))

    with patches[0], patches[1], patches[2]:
        if len(patches) == 4:
            with patches[3]:
                from src.main import run_cycle
                summary = run_cycle()
        else:
            from src.main import run_cycle
            summary = run_cycle()

    return summary, mock_client


def _read_preview_rows(tmp_path):
    files = list((tmp_path / ".harness" / "type-previews").glob("preview123_*_type-preview.jsonl"))
    assert len(files) == 1
    return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]


def _read_preview_summary(tmp_path):
    files = list((tmp_path / ".harness" / "type-previews").glob("preview123_*_type-preview-summary.md"))
    assert len(files) == 1
    return files[0].read_text(encoding="utf-8")


def _read_stale_preview_rows(tmp_path):
    files = list((tmp_path / ".harness" / "stale-previews").glob("preview123_*_stale-preview.jsonl"))
    assert len(files) == 1
    return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]


def _read_stale_preview_summary(tmp_path):
    files = list((tmp_path / ".harness" / "stale-previews").glob("preview123_*_stale-preview-summary.md"))
    assert len(files) == 1
    return files[0].read_text(encoding="utf-8")


def test_run_cycle_writes_stale_preview_artifact_without_hidden_column_write(tmp_path, monkeypatch):
    crawler = MagicMock()
    crawler.warmup.return_value = None
    crawler.fetch_search.return_value = "<html>" + ("정상" * 300) + "</html>"
    crawler.fetch_cafe_url_status.return_value = None

    summary, mock_client = _run_cycle_with_mocks(
        tmp_path,
        monkeypatch,
        _base_rows(),
        crawler,
        parse_result=_matched_result(ExposureArea.AB, block_order=["AB", "인기글"]),
    )

    rows = _read_stale_preview_rows(tmp_path)
    assert rows[0]["tab"] == next(iter(_base_rows()))
    assert rows[0]["row"] == 2
    assert rows[0]["freshness_status"] == "no_baseline"
    assert rows[0]["formula_mode_ready"] is False
    assert rows[0]["would_mask_stale_output"] is False
    assert summary["stale_preview_rows"] == 1
    assert summary["stale_preview_no_baseline_rows"] == 1
    assert summary["stale_preview_path"].endswith("_stale-preview.jsonl")
    assert "Stale Output Preview" in _read_stale_preview_summary(tmp_path)
    assert "https://cafe.naver.com" not in json.dumps(rows, ensure_ascii=False)

    written_updates = mock_client.write_results.call_args_list[0].args[1]
    for update in written_updates:
        assert all(not name.startswith("raw_") for name in update.columns)
        assert "마지막검사입력키" not in update.columns


def test_run_cycle_writes_type_preview_artifact_without_c_column_write(tmp_path, monkeypatch):
    crawler = MagicMock()
    crawler.warmup.return_value = None
    crawler.fetch_search.return_value = "<html>" + ("정상" * 300) + "</html>"
    crawler.fetch_cafe_url_status.return_value = None

    summary, mock_client = _run_cycle_with_mocks(
        tmp_path,
        monkeypatch,
        _base_rows(),
        crawler,
        parse_result=_matched_result(ExposureArea.AB, block_order=["AB", "인기글"]),
    )

    rows = _read_preview_rows(tmp_path)
    assert rows[0]["tab"] == "샴푸 카외"
    assert rows[0]["row"] == 2
    assert rows[0]["keyword"] == "탈모샴푸"
    assert rows[0]["current_type"] == ""
    assert rows[0]["suggested_type"] == "AB"
    assert rows[0]["block_order"] == ["AB", "인기글"]
    assert rows[0]["k_area"] == "AB"
    assert rows[0]["link_empty"] is False
    assert rows[0]["parser_confidence"] == 0.9
    assert rows[0]["html_status"] == "ok"
    assert rows[0]["would_update"] is True
    assert summary["type_preview_rows"] == 1
    assert summary["type_preview_would_update_rows"] == 1
    assert summary["type_preview_summary_path"].endswith("_type-preview-summary.md")
    summary_text = _read_preview_summary(tmp_path)
    assert "Type Preview Review" in summary_text
    assert "C column candidates: 1" in summary_text
    assert "preview 확인했어. C열 write 허용 단계 진행해." in summary_text

    written_updates = mock_client.write_results.call_args_list[0].args[1]
    assert HEADER_TYPE not in written_updates[0].columns
    mock_client.write_type_results.assert_not_called()


def test_run_cycle_stale_formula_mode_writes_raw_outputs_instead_of_visible_columns(tmp_path, monkeypatch):
    crawler = MagicMock()
    crawler.warmup.return_value = None
    crawler.fetch_search.return_value = "<html>" + ("정상" * 300) + "</html>"
    crawler.fetch_cafe_url_status.return_value = None

    summary, mock_client = _run_cycle_with_mocks(
        tmp_path,
        monkeypatch,
        _base_rows(),
        crawler,
        parse_result=_matched_result(ExposureArea.AB, block_order=["AB", "인기글"]),
        stale_formula_mode=True,
    )

    mock_client.ensure_stale_formula_mode.assert_called_once()
    mock_client.write_stale_formula_results.assert_called_once()
    mock_client.write_results.assert_not_called()
    assert summary["stale_formula_mode_enabled"] is True
    assert summary["stale_formula_mode_cells_written"] == 6


def test_run_cycle_recheck_stale_only_processes_only_stale_input_rows(tmp_path, monkeypatch):
    crawler = MagicMock()
    crawler.warmup.return_value = None
    crawler.fetch_search.return_value = "<html>" + ("정상" * 300) + "</html>"
    crawler.fetch_cafe_url_status.return_value = None

    summary, mock_client = _run_cycle_with_mocks(
        tmp_path,
        monkeypatch,
        _formula_ready_rows_with_one_stale(),
        crawler,
        parse_result=_matched_result(ExposureArea.AB, block_order=["AB"]),
        stale_formula_mode=True,
        recheck_stale_only=True,
    )

    tab_name, updates = mock_client.write_stale_formula_results.call_args.args[:2]
    assert tab_name == "샴푸 카외"
    assert [update.row for update in updates] == [2]
    assert crawler.fetch_search.call_count == 1
    assert summary["recheck_stale_only_enabled"] is True
    assert summary["recheck_stale_only_target_rows"] == 1
    assert summary["total_rows_processed"] == 1


def test_run_cycle_confirmed_type_preview_writes_c_column_candidates(tmp_path, monkeypatch):
    crawler = MagicMock()
    crawler.warmup.return_value = None
    crawler.fetch_search.return_value = "<html>" + ("?뺤긽" * 300) + "</html>"
    crawler.fetch_cafe_url_status.return_value = None

    summary, mock_client = _run_cycle_with_mocks(
        tmp_path,
        monkeypatch,
        _base_rows(),
        crawler,
        parse_result=_matched_result(ExposureArea.AB, block_order=["AB", "?멸린湲"]),
        type_write_confirmed=True,
        post_write_rows=_rows_with_type("AB"),
        type_write_cells=1,
    )

    mock_client.write_type_results.assert_called_once()
    tab_name, updates = mock_client.write_type_results.call_args.args
    assert tab_name == next(iter(_base_rows()))
    assert len(updates) == 1
    assert updates[0].row == 2
    assert updates[0].columns == {HEADER_TYPE: "AB"}
    assert summary["type_preview_write_confirmed"] is True
    assert summary["type_preview_write_requested_rows"] == 1
    assert summary["type_preview_write_rows"] == 1
    assert summary["type_preview_write_audit_violations"] == 0
    summary_text = _read_preview_summary(tmp_path)
    assert "C-column write enabled" in summary_text
    assert "preview 확인했어. C열 write 허용 단계 진행해." not in summary_text


def test_run_cycle_confirmed_type_preview_audits_c_column_after_write(tmp_path, monkeypatch):
    crawler = MagicMock()
    crawler.warmup.return_value = None
    crawler.fetch_search.return_value = "<html>" + ("정상" * 300) + "</html>"
    crawler.fetch_cafe_url_status.return_value = None

    summary, mock_client = _run_cycle_with_mocks(
        tmp_path,
        monkeypatch,
        _base_rows(),
        crawler,
        parse_result=_matched_result(ExposureArea.AB, block_order=["AB"]),
        type_write_confirmed=True,
        post_write_rows=_rows_with_type(""),
        type_write_cells=1,
    )

    mock_client.write_type_results.assert_called_once()
    assert summary["type_preview_write_audit_violations"] == 1
    assert summary["code_change_suspected"] is True
    audit_files = list((tmp_path / ".harness" / "audits").glob("preview123_*_type-write-audit.jsonl"))
    assert len(audit_files) == 1
    assert "TYPE_WRITE_MISMATCH" in audit_files[0].read_text(encoding="utf-8")


def test_run_cycle_confirmed_type_preview_bulk_guard_blocks_automatic_c_write(tmp_path, monkeypatch):
    crawler = MagicMock()
    crawler.warmup.return_value = None
    crawler.fetch_search.return_value = "<html>" + ("정상" * 300) + "</html>"
    crawler.fetch_cafe_url_status.return_value = None

    summary, mock_client = _run_cycle_with_mocks(
        tmp_path,
        monkeypatch,
        _many_base_rows(51),
        crawler,
        parse_result=_matched_result(ExposureArea.AB, block_order=["AB"]),
        type_write_confirmed=True,
    )

    mock_client.write_type_results.assert_not_called()
    assert summary["type_preview_bulk_guard_triggered"] is True
    assert summary["type_preview_write_blocked_by_bulk_guard"] is True
    assert summary["type_preview_write_rows"] == 0
    assert summary["code_change_suspected"] is True
    summary_text = _read_preview_summary(tmp_path)
    assert "bulk-change guard blocked C-column write" in summary_text


def test_run_cycle_confirmed_type_preview_bulk_guard_allows_manual_override(tmp_path, monkeypatch):
    crawler = MagicMock()
    crawler.warmup.return_value = None
    crawler.fetch_search.return_value = "<html>" + ("정상" * 300) + "</html>"
    crawler.fetch_cafe_url_status.return_value = None
    rows = _many_base_rows(51)
    post_rows = {
        "샴푸 카외": [
            {**row, HEADER_TYPE: "AB"}
            for row in rows["샴푸 카외"]
        ]
    }

    summary, mock_client = _run_cycle_with_mocks(
        tmp_path,
        monkeypatch,
        rows,
        crawler,
        parse_result=_matched_result(ExposureArea.AB, block_order=["AB"]),
        type_write_confirmed=True,
        type_write_allow_bulk=True,
        post_write_rows=post_rows,
        type_write_cells=51,
    )

    mock_client.write_type_results.assert_called_once()
    assert summary["type_preview_bulk_guard_triggered"] is True
    assert summary["type_preview_bulk_guard_overridden"] is True
    assert summary["type_preview_write_blocked_by_bulk_guard"] is False
    assert summary["type_preview_write_requested_rows"] == 51
    assert summary["type_preview_write_rows"] == 51


def test_run_cycle_type_preview_records_blocked_rows(tmp_path, monkeypatch):
    crawler = MagicMock()
    crawler.warmup.return_value = None
    crawler.fetch_search.side_effect = CrawlerError("rate limited")

    summary, mock_client = _run_cycle_with_mocks(tmp_path, monkeypatch, _base_rows(), crawler)

    rows = _read_preview_rows(tmp_path)
    assert rows[0]["html_status"] == "blocked"
    assert rows[0]["suggested_type"] == ""
    assert rows[0]["would_update"] is False
    assert "blocked" in rows[0]["reason"]
    assert summary["type_preview_rows"] == 1
    mock_client.write_results.assert_not_called()


def test_run_cycle_type_preview_records_parser_failure(tmp_path, monkeypatch):
    crawler = MagicMock()
    crawler.warmup.return_value = None
    crawler.fetch_search.return_value = "<html>" + ("정상" * 300) + "</html>"

    summary, _mock_client = _run_cycle_with_mocks(
        tmp_path,
        monkeypatch,
        _base_rows(),
        crawler,
        parse_error=ValueError("parser boom"),
    )

    rows = _read_preview_rows(tmp_path)
    assert rows[0]["html_status"] == "parse_failed"
    assert rows[0]["suggested_type"] == ""
    assert rows[0]["parser_confidence"] == 0.0
    assert rows[0]["would_update"] is False
    assert "parser boom" in rows[0]["reason"]
    assert summary["type_preview_rows"] == 1
