"""apply_keyword_classify 단위 테스트 — 실 네트워크 0 (시트 mock/주입).

매칭·값생성 로직, 미매칭/CSV전용, 데이터확인 request, dry-run 경로 검증.
"""
from pathlib import Path

import pytest

from src.apply_keyword_classify import (
    HEADER_CLASSIFY,
    HEADER_KEYWORD,
    apply,
    build_classify_value,
    build_data_validation_request,
    classify_value_set,
    compute_updates,
    load_classify_map,
)


# ---------- 값 형식 ('{단계} {유형}') 생성 ----------

def test_build_classify_value_format():
    assert build_classify_value("3", "증상") == "3 증상"
    assert build_classify_value("5", "브랜드제품") == "5 브랜드제품"
    assert build_classify_value("5", "카테고리") == "5 카테고리"
    assert build_classify_value("4", "대안") == "4 대안"


def test_build_classify_value_trims_whitespace():
    # 단계/유형에 공백이 섞여도 단일 공백으로 결합.
    assert build_classify_value(" 3 ", " 증상 ") == "3 증상"
    assert build_classify_value(3, "증상") == "3 증상"  # 숫자형도 허용


def test_classify_value_set_dedup_sorted():
    m = {
        "a": "5 브랜드제품",
        "b": "3 증상",
        "c": "5 브랜드제품",  # 중복
        "d": "4 대안",
    }
    assert classify_value_set(m) == ["3 증상", "4 대안", "5 브랜드제품"]


# ---------- CSV 로드 (BOM 안전) ----------

def test_load_classify_map_from_real_csv():
    # worktree 에 복사된 실제 CSV 로 BOM/형식 검증.
    csv_path = Path(__file__).resolve().parents[2] / "data" / "keyword_classify_shampoo.csv"
    if not csv_path.exists():
        pytest.skip("data/keyword_classify_shampoo.csv 없음")
    m = load_classify_map(str(csv_path))
    assert len(m) == 343  # 343행 모두 유니크 키워드
    # 모든 값이 '{숫자} {유형}' 형식 — 맨 앞이 단계 숫자.
    for v in m.values():
        head = v.split(" ", 1)[0]
        assert head in {"3", "4", "5"}, f"단계 숫자 아님: {v!r}"
    # 분류값 집합 = 4종.
    assert set(m.values()) == {"3 증상", "4 대안", "5 브랜드제품", "5 카테고리"}


def test_load_classify_map_handles_bom_and_blank(tmp_path):
    p = tmp_path / "c.csv"
    # BOM + 빈 키워드 행 포함.
    p.write_text(
        "﻿키워드,접촉지점,단계,유형,근거\n"
        "머리에여드름,3-증상,3,증상,근거1\n"
        "약국니조랄가격,5-브랜드제품,5,브랜드제품,근거2\n"
        ",,4,대안,빈키워드행\n",
        encoding="utf-8",
    )
    m = load_classify_map(str(p))
    assert m == {"머리에여드름": "3 증상", "약국니조랄가격": "5 브랜드제품"}


def test_load_classify_map_trims_keyword(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text(
        "키워드,접촉지점,단계,유형,근거\n"
        "  머리에여드름  ,3-증상,3,증상,근거\n",
        encoding="utf-8",
    )
    m = load_classify_map(str(p))
    assert m == {"머리에여드름": "3 증상"}


# ---------- compute_updates: 매칭/미매칭/CSV전용 ----------

CLASSIFY_MAP = {
    "머리에여드름": "3 증상",
    "약국니조랄가격": "5 브랜드제품",
    "샴푸추천": "5 카테고리",
    "탈모대안": "4 대안",  # CSV 에만 있고 시트에 없음 → csv_only
}


def _rows(*pairs):
    """(_row, 키워드, [기존 분류값]) → 시트 행 dict 리스트."""
    out = []
    for p in pairs:
        row_num, keyword = p[0], p[1]
        classify = p[2] if len(p) > 2 else ""
        out.append({"_row": row_num, HEADER_KEYWORD: keyword, HEADER_CLASSIFY: classify})
    return out


def test_compute_updates_basic_match():
    headers = ["작업일", HEADER_KEYWORD, "링크", HEADER_CLASSIFY]
    rows = _rows(
        (2, "머리에여드름"),
        (3, "약국니조랄가격"),
        (4, "샴푸추천"),
    )
    plan = compute_updates(headers=headers, sheet_rows=rows, classify_map=CLASSIFY_MAP)

    # 키워드 칸 = 2번째(B), 분류 칸 = 4번째(D).
    coords = {(u.a1, u.value) for u in plan.updates}
    assert coords == {
        ("D2", "3 증상"),
        ("D3", "5 브랜드제품"),
        ("D4", "5 카테고리"),
    }
    assert plan.overwrites == []  # 기존값 모두 빈칸
    assert plan.sheet_only == []
    assert plan.csv_only == ["탈모대안"]  # 시트에 없는 CSV 키워드


def test_compute_updates_sheet_only_unclassified():
    headers = [HEADER_KEYWORD, HEADER_CLASSIFY]
    rows = _rows(
        (2, "머리에여드름"),
        (3, "정체불명키워드"),  # CSV 에 없음 → sheet_only(미분류)
    )
    plan = compute_updates(headers=headers, sheet_rows=rows, classify_map=CLASSIFY_MAP)
    assert [u.a1 for u in plan.updates] == ["B2"]
    assert plan.sheet_only == ["정체불명키워드"]


def test_compute_updates_overwrite_logged_and_skip_same():
    headers = [HEADER_KEYWORD, HEADER_CLASSIFY]
    rows = _rows(
        (2, "머리에여드름", "3 증상"),     # 이미 같은 값 → 스킵(쓰지 않음)
        (3, "약국니조랄가격", "4 대안"),   # 기존값 다름 → 덮어쓰기
    )
    plan = compute_updates(headers=headers, sheet_rows=rows, classify_map=CLASSIFY_MAP)
    # 같은 값은 update 에서 제외.
    assert [u.a1 for u in plan.updates] == ["B3"]
    assert len(plan.overwrites) == 1
    ow = plan.overwrites[0]
    assert ow.a1 == "B3"
    assert ow.old_value == "4 대안"
    assert ow.value == "5 브랜드제품"


def test_compute_updates_trims_sheet_keyword():
    headers = [HEADER_KEYWORD, HEADER_CLASSIFY]
    rows = _rows((2, "  머리에여드름  "))  # 앞뒤 공백 → 정규화 후 매칭
    plan = compute_updates(headers=headers, sheet_rows=rows, classify_map=CLASSIFY_MAP)
    assert [(u.a1, u.value) for u in plan.updates] == [("B2", "3 증상")]


def test_compute_updates_skips_header_and_blank_rows():
    headers = [HEADER_KEYWORD, HEADER_CLASSIFY]
    rows = [
        {"_row": 1, HEADER_KEYWORD: HEADER_KEYWORD, HEADER_CLASSIFY: ""},  # 헤더행 방어
        {"_row": 2, HEADER_KEYWORD: "", HEADER_CLASSIFY: ""},  # 빈 키워드
        {"_row": 3, HEADER_KEYWORD: "머리에여드름", HEADER_CLASSIFY: ""},
    ]
    plan = compute_updates(headers=headers, sheet_rows=rows, classify_map=CLASSIFY_MAP)
    assert [u.a1 for u in plan.updates] == ["B3"]


# ---------- 헤더 누락 에러 ----------

def test_compute_updates_missing_keyword_header():
    headers = ["작업일", HEADER_CLASSIFY]
    with pytest.raises(ValueError, match=HEADER_KEYWORD):
        compute_updates(headers=headers, sheet_rows=[], classify_map=CLASSIFY_MAP)


def test_compute_updates_missing_classify_header():
    headers = ["작업일", HEADER_KEYWORD]
    with pytest.raises(ValueError, match=HEADER_CLASSIFY):
        compute_updates(headers=headers, sheet_rows=[], classify_map=CLASSIFY_MAP)


# ---------- 데이터확인 request 형식 ----------

def test_build_data_validation_request_shape():
    req = build_data_validation_request(
        sheet_id=12345,
        classify_col=5,  # 0-indexed → F열
        start_row=2,
        end_row=100,
        values=["3 증상", "4 대안", "5 브랜드제품", "5 카테고리"],
    )
    dv = req["setDataValidation"]
    rng = dv["range"]
    assert rng["sheetId"] == 12345
    assert rng["startRowIndex"] == 1  # 0-indexed inclusive (행2)
    assert rng["endRowIndex"] == 100  # exclusive
    assert rng["startColumnIndex"] == 5
    assert rng["endColumnIndex"] == 6
    rule = dv["rule"]
    assert rule["condition"]["type"] == "ONE_OF_LIST"
    assert [v["userEnteredValue"] for v in rule["condition"]["values"]] == [
        "3 증상",
        "4 대안",
        "5 브랜드제품",
        "5 카테고리",
    ]
    assert rule["showCustomUi"] is True
    assert rule["strict"] is False  # 목록 외 값도 경고 없이 허용


# ---------- apply(): 주입 클라이언트로 end-to-end (네트워크 0) ----------

class _FakeWorksheet:
    """get_all_values / batch_update 만 흉내내는 mock 워크시트."""

    def __init__(self, values, sheet_id=999, title="샴푸 카외"):
        self._values = values
        self.id = sheet_id
        self.title = title
        self.batch_update_calls = []  # (cells, value_input_option)

    def get_all_values(self):
        return self._values

    def batch_update(self, cells, value_input_option="RAW"):
        self.batch_update_calls.append((cells, value_input_option))
        return {"ok": True}


class _FakeSpreadsheet:
    def __init__(self, ws):
        self._ws = ws
        self.batch_update_requests = []  # setDataValidation 등 raw requests

    def worksheet(self, name):
        assert name == self._ws.title
        return self._ws

    def batch_update(self, body):
        self.batch_update_requests.append(body)
        return {"ok": True}


class _FakeClient:
    def __init__(self, ws):
        self.spreadsheet = _FakeSpreadsheet(ws)


def test_apply_dry_run_does_not_write(tmp_path):
    csv = tmp_path / "c.csv"
    csv.write_text(
        "키워드,접촉지점,단계,유형,근거\n"
        "머리에여드름,3-증상,3,증상,근거\n"
        "약국니조랄가격,5-브랜드제품,5,브랜드제품,근거\n",
        encoding="utf-8",
    )
    ws = _FakeWorksheet(
        [
            [HEADER_KEYWORD, HEADER_CLASSIFY],
            ["머리에여드름", ""],
            ["약국니조랄가격", ""],
        ]
    )
    client = _FakeClient(ws)
    plan = apply(
        spreadsheet_id="x",
        service_account_json="{}",
        target_tab="샴푸 카외",
        csv_path=str(csv),
        dry_run=True,
        client=client,
    )
    assert len(plan.updates) == 2
    # dry-run = 어떤 쓰기도 없어야 함.
    assert ws.batch_update_calls == []
    assert client.spreadsheet.batch_update_requests == []


def test_apply_real_writes_cells_and_validation(tmp_path):
    csv = tmp_path / "c.csv"
    csv.write_text(
        "키워드,접촉지점,단계,유형,근거\n"
        "머리에여드름,3-증상,3,증상,근거\n"
        "약국니조랄가격,5-브랜드제품,5,브랜드제품,근거\n",
        encoding="utf-8",
    )
    ws = _FakeWorksheet(
        [
            ["작업일", HEADER_KEYWORD, "링크", HEADER_CLASSIFY],
            ["6/1", "머리에여드름", "http://x", ""],
            ["6/1", "약국니조랄가격", "http://y", ""],
        ]
    )
    client = _FakeClient(ws)
    apply(
        spreadsheet_id="x",
        service_account_json="{}",
        target_tab="샴푸 카외",
        csv_path=str(csv),
        dry_run=False,
        client=client,
    )
    # 1) 셀 batch_update 정확히 1회.
    assert len(ws.batch_update_calls) == 1
    cells, opt = ws.batch_update_calls[0]
    assert opt == "RAW"
    # 분류 칸 = D열, 행 2/3.
    sent = {(c["range"], c["values"][0][0]) for c in cells}
    assert sent == {("D2", "3 증상"), ("D3", "5 브랜드제품")}
    # 2) 데이터확인 setDataValidation 정확히 1회.
    assert len(client.spreadsheet.batch_update_requests) == 1
    req = client.spreadsheet.batch_update_requests[0]["requests"][0]
    dv = req["setDataValidation"]
    assert dv["range"]["sheetId"] == ws.id
    assert dv["range"]["startColumnIndex"] == 3  # D열 (0-indexed)
    vals = [v["userEnteredValue"] for v in dv["rule"]["condition"]["values"]]
    assert vals == ["3 증상", "5 브랜드제품"]
