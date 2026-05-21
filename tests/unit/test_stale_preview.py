from src.sheets import HEADER_AREA, HEADER_JISIKIN, HEADER_L, HEADER_LINK, HEADER_M, HEADER_TYPE


def test_input_key_uses_only_keyword_and_link():
    from src.stale_preview import HEADER_KEYWORD, build_input_key

    base = {
        HEADER_KEYWORD: "  지루성두피염원인  ",
        HEADER_LINK: " HTTPS://cafe.naver.com/workee/1325909 ",
        HEADER_TYPE: "AB",
        HEADER_AREA: "AB",
        HEADER_L: "2",
        HEADER_M: "2",
    }
    edited_non_search_columns = {
        **base,
        HEADER_TYPE: "인기글",
        HEADER_AREA: "누락",
        HEADER_L: "",
        HEADER_M: "",
    }

    assert build_input_key(base) == build_input_key(edited_non_search_columns)


def test_input_key_normalizes_link_noise_but_keeps_post_id_distinct():
    from src.stale_preview import HEADER_KEYWORD, build_input_key

    base = {
        HEADER_KEYWORD: "지루성두피염원인",
        HEADER_LINK: "https://cafe.naver.com/workee/1325909?from=list#comment",
    }
    mobile = {
        HEADER_KEYWORD: "지루성두피염원인",
        HEADER_LINK: "https://m.cafe.naver.com/workee/1325909/",
    }
    different_post = {
        HEADER_KEYWORD: "지루성두피염원인",
        HEADER_LINK: "https://cafe.naver.com/workee/1325910",
    }

    assert build_input_key(base) == build_input_key(mobile)
    assert build_input_key(base) != build_input_key(different_post)


def test_missing_hidden_columns_are_not_flagged_as_stale():
    from src.stale_preview import HEADER_KEYWORD, build_stale_preview_rows

    rows = {
        "샴푸 카외": [
            {
                "_tab": "샴푸 카외",
                "_row": 177,
                HEADER_KEYWORD: "지루성두피염원인",
                HEADER_LINK: "https://cafe.naver.com/workee/1325909",
                HEADER_AREA: "AB (5/20 15:54~)",
                HEADER_L: "2",
                HEADER_M: "2",
                HEADER_JISIKIN: "",
            }
        ]
    }

    preview = build_stale_preview_rows(rows)

    assert preview[0]["freshness_status"] == "no_baseline"
    assert preview[0]["baseline_available"] is False
    assert preview[0]["formula_mode_ready"] is False
    assert preview[0]["would_mask_stale_output"] is False
    assert preview[0]["reason"] == "hidden_columns_missing"


def test_matching_input_key_would_show_raw_outputs():
    from src.stale_preview import (
        HEADER_KEYWORD,
        HEADER_LAST_CHECKED_INPUT_KEY,
        HEADER_CURRENT_INPUT_KEY,
        HEADER_RAW_AREA,
        HEADER_RAW_JISIKIN,
        HEADER_RAW_L,
        HEADER_RAW_M,
        build_input_key,
        build_stale_preview_rows,
    )

    row = {
        "_tab": "샴푸 카외",
        "_row": 177,
        HEADER_KEYWORD: "지루성두피염원인",
        HEADER_LINK: "https://cafe.naver.com/workee/1325909",
        HEADER_AREA: "재검사필요",
        HEADER_L: "",
        HEADER_M: "",
        HEADER_JISIKIN: "",
        HEADER_RAW_AREA: "누락 (5/21 18:00~)",
        HEADER_RAW_L: "",
        HEADER_RAW_M: "",
        HEADER_RAW_JISIKIN: "",
    }
    row[HEADER_CURRENT_INPUT_KEY] = build_input_key(row)
    row[HEADER_LAST_CHECKED_INPUT_KEY] = build_input_key(row)

    preview = build_stale_preview_rows({"샴푸 카외": [row]})

    assert preview[0]["freshness_status"] == "current"
    assert preview[0]["would_show_k"] == "누락 (5/21 18:00~)"
    assert preview[0]["would_show_l"] == ""
    assert preview[0]["would_show_m"] == ""
    assert preview[0]["would_show_jisikin"] == ""
    assert preview[0]["would_mask_stale_output"] is False


def test_changed_input_key_would_mask_stale_visible_outputs():
    from src.stale_preview import (
        HEADER_KEYWORD,
        HEADER_LAST_CHECKED_INPUT_KEY,
        HEADER_CURRENT_INPUT_KEY,
        HEADER_RAW_AREA,
        HEADER_RAW_JISIKIN,
        HEADER_RAW_L,
        HEADER_RAW_M,
        build_input_key,
        build_stale_preview_rows,
    )

    old_row = {
        HEADER_KEYWORD: "기존키워드",
        HEADER_LINK: "https://cafe.naver.com/workee/1325909",
    }
    row = {
        "_tab": "샴푸 카외",
        "_row": 177,
        HEADER_KEYWORD: "지루성두피염원인",
        HEADER_LINK: "https://cafe.naver.com/workee/1325909",
        HEADER_AREA: "AB (5/20 15:54~)",
        HEADER_L: "2",
        HEADER_M: "2",
        HEADER_JISIKIN: "",
        HEADER_LAST_CHECKED_INPUT_KEY: build_input_key(old_row),
        HEADER_RAW_AREA: "AB (5/20 15:54~)",
        HEADER_RAW_L: "2",
        HEADER_RAW_M: "2",
        HEADER_RAW_JISIKIN: "",
    }
    row[HEADER_CURRENT_INPUT_KEY] = build_input_key(row)

    preview = build_stale_preview_rows({"샴푸 카외": [row]})

    assert preview[0]["freshness_status"] == "stale_input"
    assert preview[0]["would_show_k"] == "재검사필요"
    assert preview[0]["would_show_l"] == ""
    assert preview[0]["would_show_m"] == ""
    assert preview[0]["would_show_jisikin"] == ""
    assert preview[0]["would_mask_stale_output"] is True
    assert preview[0]["reason"] == "current_input_differs_from_last_check"


def test_manual_visible_k_is_not_masked_by_preview():
    from src.stale_preview import (
        HEADER_CURRENT_INPUT_KEY,
        HEADER_KEYWORD,
        HEADER_LAST_CHECKED_INPUT_KEY,
        HEADER_RAW_AREA,
        HEADER_RAW_JISIKIN,
        HEADER_RAW_L,
        HEADER_RAW_M,
        build_input_key,
        build_stale_preview_rows,
    )

    old_row = {
        HEADER_KEYWORD: "기존키워드",
        HEADER_LINK: "https://cafe.naver.com/workee/1325909",
    }
    row = {
        "_tab": "샴푸 카외",
        "_row": 177,
        HEADER_KEYWORD: "지루성두피염원인",
        HEADER_LINK: "https://cafe.naver.com/workee/1325909",
        HEADER_AREA: "수동확인",
        HEADER_L: "",
        HEADER_M: "",
        HEADER_JISIKIN: "",
        HEADER_LAST_CHECKED_INPUT_KEY: build_input_key(old_row),
        HEADER_RAW_AREA: "AB",
        HEADER_RAW_L: "2",
        HEADER_RAW_M: "2",
        HEADER_RAW_JISIKIN: "",
    }
    row[HEADER_CURRENT_INPUT_KEY] = build_input_key(row)

    preview = build_stale_preview_rows({"샴푸 카외": [row]})

    assert preview[0]["freshness_status"] == "manual_visible_k"
    assert preview[0]["would_show_k"] == "수동확인"
    assert preview[0]["would_mask_stale_output"] is False


def test_sheet_current_key_conflict_is_attention_not_stale():
    from src.stale_preview import (
        HEADER_CURRENT_INPUT_KEY,
        HEADER_KEYWORD,
        HEADER_LAST_CHECKED_INPUT_KEY,
        HEADER_RAW_AREA,
        HEADER_RAW_JISIKIN,
        HEADER_RAW_L,
        HEADER_RAW_M,
        build_input_key,
        build_stale_preview_rows,
    )

    row = {
        "_tab": "샴푸 카외",
        "_row": 177,
        HEADER_KEYWORD: "지루성두피염원인",
        HEADER_LINK: "https://cafe.naver.com/workee/1325909",
        HEADER_AREA: "AB",
        HEADER_L: "2",
        HEADER_M: "2",
        HEADER_JISIKIN: "",
        HEADER_CURRENT_INPUT_KEY: "v1|wrong|wrong",
        HEADER_RAW_AREA: "AB",
        HEADER_RAW_L: "2",
        HEADER_RAW_M: "2",
        HEADER_RAW_JISIKIN: "",
    }
    row[HEADER_LAST_CHECKED_INPUT_KEY] = build_input_key(row)

    preview = build_stale_preview_rows({"샴푸 카외": [row]})

    assert preview[0]["freshness_status"] == "baseline_conflict"
    assert preview[0]["would_mask_stale_output"] is False


def test_stale_preview_artifact_does_not_expose_raw_keyword_or_link(tmp_path):
    from src.stale_preview import HEADER_KEYWORD, build_stale_preview_rows, write_stale_preview_artifact

    rows = {
        "샴푸 카외": [
            {
                "_tab": "샴푸 카외",
                "_row": 177,
                HEADER_KEYWORD: "지루성두피염원인",
                HEADER_LINK: "https://cafe.naver.com/workee/1325909",
                HEADER_AREA: "AB (5/20 15:54~)",
            }
        ]
    }
    path = tmp_path / "stale-preview.jsonl"

    write_stale_preview_artifact(path, build_stale_preview_rows(rows))

    text = path.read_text(encoding="utf-8")
    assert "https://cafe.naver.com" not in text
    assert "지루성두피염원인" not in text
    assert "keyword_hash" in text
    assert "keyword_display" in text
