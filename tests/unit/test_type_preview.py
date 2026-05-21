from src.parser import ExposureArea, RankResult
from src.sheets import HEADER_AREA, HEADER_TYPE


def test_type_preview_fields_and_k_area_are_separate():
    from src.type_preview import TYPE_PREVIEW_FIELDS, build_type_preview_row

    result = RankResult(
        exposure_area=ExposureArea.POPULAR,
        integrated_rank=2,
        cafe_slot_rank=1,
        block_order=["AB", "인기글"],
        parser_confidence=0.85,
    )
    row = {
        "_tab": "샴푸 카외",
        "_row": 12,
        "키워드": "탈모샴푸",
        "링크": "https://cafe.naver.com/cosmania/123",
        HEADER_TYPE: "인기글",
    }
    columns = {HEADER_AREA: "인기글 (5/21 03:00~)"}

    preview = build_type_preview_row(row=row, result=result, columns=columns)

    assert list(preview.keys()) == TYPE_PREVIEW_FIELDS
    assert preview["suggested_type"] == "AB"
    assert preview["k_area"] == "인기글"
    assert preview["would_update"] is True


def test_type_preview_empty_html_never_would_update():
    from src.type_preview import build_type_preview_row

    result = RankResult(
        exposure_area=ExposureArea.AB,
        block_order=["AB"],
        parser_confidence=0.9,
    )
    row = {"_tab": "샴푸 카외", "_row": 4, "키워드": "탈모샴푸", "링크": "", HEADER_TYPE: ""}

    preview = build_type_preview_row(
        row=row,
        result=result,
        columns={HEADER_AREA: "AB"},
        html_status="empty_html",
    )

    assert preview["suggested_type"] == "AB"
    assert preview["html_status"] == "empty_html"
    assert preview["would_update"] is False
    assert preview["reason"] == "empty_html_or_too_short"


def test_type_preview_bulk_guard_detects_mass_change_risk():
    from src.type_preview import summarize_type_preview

    rows = [
        {"would_update": True},
        {"would_update": True},
        {"would_update": True},
        {"would_update": False},
    ]

    summary = summarize_type_preview(rows, max_update_ratio=0.5, min_rows_for_ratio_guard=3)

    assert summary["type_preview_rows"] == 4
    assert summary["type_preview_would_update_rows"] == 3
    assert summary["type_preview_bulk_guard_triggered"] is True


def test_type_preview_summary_artifact_is_human_readable(tmp_path):
    from src.type_preview import (
        summarize_type_preview,
        write_type_preview_summary_artifact,
    )

    rows = [
        {
            "tab": "Tab A",
            "row": 2,
            "keyword": "sample keyword",
            "current_type": "",
            "suggested_type": "AB",
            "block_order": ["AB", "popular"],
            "k_area": "popular",
            "link_empty": False,
            "parser_confidence": 0.9,
            "html_status": "ok",
            "reason": "suggested_type_differs",
            "would_update": True,
        },
        {
            "tab": "Tab A",
            "row": 3,
            "keyword": "blocked keyword",
            "current_type": "",
            "suggested_type": "",
            "block_order": [],
            "k_area": "",
            "link_empty": False,
            "parser_confidence": 0.0,
            "html_status": "blocked",
            "reason": "blocked_or_crawler_error",
            "would_update": False,
        },
    ]
    path = tmp_path / "type-preview-summary.md"

    write_type_preview_summary_artifact(path, rows, summarize_type_preview(rows))

    text = path.read_text(encoding="utf-8")
    assert "Type Preview Review" in text
    assert "C column candidates: 1" in text
    assert "preview 확인했어. C열 write 허용 단계 진행해." in text
    assert "| Tab A | 2 | sample keyword |  | AB | popular | ok | suggested_type_differs |" in text
    assert "blocked keyword" in text
