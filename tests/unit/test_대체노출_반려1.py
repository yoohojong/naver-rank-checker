"""대체 노출 품질 1차 반려(2026-10-30) 고침 시험.

지적 2 — 옛 글 출처(글장부 · 이력)를 못 읽으면 '대체 없음'과 가른다:
  글장부만 / 이력만 / 둘 다 못 읽음 3조건 모두 줄 기록 error · 시트 칸 '확인 못 함' · trace · 집계 맞대기실패까지.
  부분 자료로 찾은 대체는 '완전 확인'(대체 · 애프터)으로 세지 않는다.
지적 3 — 카페+글번호를 함께 쓴다:
  다른 카페의 같은 글번호는 대체 매치 · 제 글 제외 · 중복 제거 세 곳 모두 부딪치지 않는다.
  카페 이름 ↔ 카페 번호는 확인된 매핑(aliases)이 있을 때만 같은 글.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src import substitute
from src.audit import build_update_trace
from src.crawler import CafeStatus
from src.health import HealthMonitor
from src.main import _process_row
from src.parser import OurPostHit
from src.sheets import HEADER_AREA, HEADER_SUBSTITUTE, RowUpdate

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "naver"
STAMP = "10/30 09:00"
TAB = "샴푸 카외"
KW = "비듬샴푸"
TWO_CARDS = "popular_same_cafe_two_cards.html"
# popular_same_cafe_two_cards.html 인기글 박스: 1칸 ccrs5500/777989 · 2칸 cantsb/3406915 …
ON_PAGE = "https://cafe.naver.com/ccrs5500/777989"
OTHER_SHEET = "https://cafe.naver.com/cantsb/3406915"
MISSING = "https://cafe.naver.com/ccrs5500/999999"
NOWHERE = "https://cafe.naver.com/nowhere/1"

FAIL_CASES = [
    # (이름, 글장부 오류, 이력 오류)
    ("글장부만", "APIError: 429", ""),
    ("이력만", "", "TimeoutError"),
    ("둘다", "APIError: 429", "TimeoutError"),
]


def _html(name: str = TWO_CARDS) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _crawler(html: str) -> MagicMock:
    c = MagicMock()
    c.fetch_search.return_value = html
    c.fetch_cafe_url_status.return_value = CafeStatus.ALIVE
    return c


def _row(link: str, keyword: str = KW, k: str = "", r: int = 2) -> dict:
    return {"키워드": keyword, "링크": link, HEADER_AREA: k, "_row": r, "_tab": TAB}


def _counter():
    spec = importlib.util.spec_from_file_location(
        "count_substitute_before_after",
        Path(__file__).resolve().parents[2] / "scripts" / "count_substitute_before_after.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _one_row_pipeline(idx, row: dict):
    """_process_row → 기록 줄 → 시트 칸 값 → trace → 집계 (회차 끝 순서 그대로, 시트·네이버 없음)."""
    cols = _process_row(dict(row), _crawler(_html()), HealthMonitor(), today_stamp=STAMP, our_index=idx)
    updates = {TAB: [RowUpdate(row=row["_row"], columns=cols)]}
    ctx = {(TAB, row["_row"]): row}
    recs = substitute.collect_rows(updates, ctx, "t", "fixed")
    substitute.apply_cells(updates, recs, HEADER_SUBSTITUTE, enabled=True, index_error="")
    trace = build_update_trace(updates, ctx, [], substitute_by_row={(TAB, r["row"]): r for r in recs})
    return cols, recs, trace, _counter().count(trace, recs)


# ── 지적 2: 출처 못 읽음 ≠ 대체 없음 ─────────────────────────────────────

@pytest.mark.parametrize("name,ledger_err,archive_err", FAIL_CASES, ids=[c[0] for c in FAIL_CASES])
def test_출처_못읽음_대체없음은_확인못함으로_끝까지(name, ledger_err, archive_err):
    # 화면에 우리 글이 하나도 없는 줄 — 출처를 다 읽었다면 빈칸(없음)이지만, 못 읽었으니 '확인 못 함'
    idx = substitute.build_index({TAB: [_row(NOWHERE, keyword="x", r=10)]}, [], [],
                                 ledger_error=ledger_err, archive_error=archive_err)
    cols, recs, trace, cnt = _one_row_pipeline(idx, _row(MISSING))
    assert cols[HEADER_AREA].startswith("미노출")  # K 그대로
    rec = recs[0]
    assert rec["substitute_count"] == 0 and rec["complete"] is False
    assert rec["error"].startswith("옛 글 출처 못 읽음:")
    for src, err in (("글장부", ledger_err), ("이력", archive_err)):
        assert (f"{src}({err})" in rec["error"]) is bool(err)
    cell = cols[HEADER_SUBSTITUTE]
    assert cell.startswith("확인 못 함 (옛 글 출처 못 읽음") and "찾은 것" not in cell
    assert trace[0]["substitute_error"] == rec["error"] and trace[0]["substitute_complete"] is False
    assert cnt["전체"]["맞대기실패"] == 1 and cnt["전체"]["대체"] == 0 and cnt["전체"]["대체_확인못함"] == 0


@pytest.mark.parametrize("name,ledger_err,archive_err", FAIL_CASES, ids=[c[0] for c in FAIL_CASES])
def test_출처_못읽음_부분자료로_찾은_대체는_완전확인으로_안셈(name, ledger_err, archive_err):
    # 시트 링크(시트 출처는 읽힘)로 대체를 찾았지만 옛 글 출처 하나 이상을 못 읽음 = 부분 자료
    idx = substitute.build_index({TAB: [_row(OTHER_SHEET, keyword="x", r=10)]}, [], [],
                                 ledger_error=ledger_err, archive_error=archive_err)
    cols, recs, trace, cnt = _one_row_pipeline(idx, _row(MISSING))
    rec = recs[0]
    assert rec["substitute_count"] == 1 and rec["complete"] is False and rec["error"]
    cell = cols[HEADER_SUBSTITUTE]
    assert cell.startswith("확인 못 함 (") and f"— 찾은 것: 인기글 2위 {OTHER_SHEET}" in cell
    assert trace[0]["substitute_complete"] is False and trace[0]["substitute_count"] == 1
    t = cnt["전체"]
    assert (t["대체"], t["애프터"], t["맞대기실패"], t["대체_확인못함"]) == (0, 0, 1, 1)
    assert cnt["대체 줄 표"] == []  # '대신 뜬 글' 확정 표에 안 올라감


def test_출처_다_읽으면_종전대로_빈칸과_대체():
    idx = substitute.build_index({TAB: [_row(OTHER_SHEET, keyword="x", r=10)]}, [], [])
    cols, recs, trace, cnt = _one_row_pipeline(idx, _row(MISSING))
    assert recs[0]["error"] == "" and recs[0]["complete"] is True
    assert cols[HEADER_SUBSTITUTE].startswith(f"인기글 2위 {OTHER_SHEET}")
    assert (cnt["전체"]["대체"], cnt["전체"]["애프터"], cnt["전체"]["맞대기실패"]) == (1, 1, 0)
    idx0 = substitute.build_index({TAB: [_row(NOWHERE, keyword="x", r=10)]}, [], [])
    cols0, recs0, _, cnt0 = _one_row_pipeline(idx0, _row(MISSING))
    assert cols0[HEADER_SUBSTITUTE] == "" and recs0[0]["complete"] is True
    assert cnt0["전체"]["맞대기실패"] == 0


def test_빈_탭은_0건이_아니라_못읽음():
    client = MagicMock()
    ws = MagicMock()
    ws.get_all_values.return_value = []
    client.spreadsheet.worksheet.return_value = ws
    l_rows, l_err, a_rows, a_err = substitute.read_private_sources(client)
    assert l_err and a_err and l_rows == [] and a_rows == []
    idx = substitute.build_index({}, l_rows, a_rows, ledger_error=l_err, archive_error=a_err)
    assert sorted(idx.source_errors) == ["글장부", "이력"]


# 회차 전체(run_cycle): 실제 read_private_sources 실패 → 기록 파일 · 시트 쓰기 값 · trace · 요약 · 집계

def _run_cycle_with_failures(tmp_path, monkeypatch, ledger_fail: bool, archive_fail: bool):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUBSTITUTE_SCAN", "1")
    monkeypatch.setenv("GOYU_NOTIFY_OFF", "1")
    for name in ("ARCHIVE_ENABLED", "STALE_OUTPUT_FORMULA_MODE", "RECHECK_STALE_ONLY",
                 "TYPE_PREVIEW_WRITE_CONFIRMED", "GITHUB_ACTIONS"):
        monkeypatch.delenv(name, raising=False)
    rows = {TAB: [_row(MISSING, r=2), _row(OTHER_SHEET, keyword="다른키워드", r=3)]}
    client = MagicMock()
    client.load_all_data_tabs.return_value = rows
    client.write_results.return_value = 0

    def worksheet(name):
        ws = MagicMock()
        if name == substitute.LEDGER_TAB_NAME:
            if ledger_fail:
                raise Exception("APIError: 429")
            ws.get_all_values.return_value = [substitute.LEDGER_TAB_HEADER, [TAB, KW, ON_PAGE, "2026-09-01", "k"]]
        elif name == substitute.ARCHIVE_TAB_NAME:
            if archive_fail:
                raise TimeoutError("read timed out")
            ws.get_all_values.return_value = [["날짜", "탭", "키워드", "노출영역", "통합순위", "카페구좌순위", "링크"]]
        else:
            raise Exception("WorksheetNotFound")
        return ws
    client.spreadsheet.worksheet.side_effect = worksheet
    crawler = _crawler(_html())
    with patch("src.main.SheetsClient", return_value=client), \
         patch("src.main.Crawler", return_value=crawler), \
         patch("src.main.SPREADSHEET_ID", "fake"), \
         patch("src.main.SERVICE_ACCOUNT_JSON", "{}"), \
         patch("src.main.random.shuffle", lambda x: None):
        from src.main import run_cycle
        summary = run_cycle()
    writes = {(call.args[0], u.row): dict(u.columns)
              for call in client.write_results.call_args_list for u in call.args[1]}
    sub_file = list((tmp_path / ".harness" / "substitutes").glob("*.jsonl"))[0]
    recs = [json.loads(x) for x in sub_file.read_text(encoding="utf-8").splitlines()]
    trace_file = list((tmp_path / ".harness" / "traces").glob("*.jsonl"))[0]
    trace = [json.loads(x) for x in trace_file.read_text(encoding="utf-8").splitlines()]
    return summary, writes, recs, trace, crawler.fetch_search.call_count


@pytest.mark.parametrize("name,ledger_fail,archive_fail",
                         [("글장부만", True, False), ("이력만", False, True), ("둘다", True, True)],
                         ids=["글장부만", "이력만", "둘다"])
def test_회차_출처_실패가_기록_시트칸_trace_집계까지(tmp_path, monkeypatch, name, ledger_fail, archive_fail):
    summary, writes, recs, trace, n_search = _run_cycle_with_failures(tmp_path, monkeypatch, ledger_fail, archive_fail)
    assert n_search == 2  # 새 검색 0 (링크 줄 2개만)
    expect_src = sorted(s for s, f in (("글장부", ledger_fail), ("이력", archive_fail)) if f)
    assert sorted(summary["substitute_source_errors"]) == expect_src
    rec = {r["row"]: r for r in recs}[2]
    assert rec["error"].startswith("옛 글 출처 못 읽음:") and rec["complete"] is False
    for s in expect_src:
        assert s in rec["error"]
    # 글장부를 읽었으면 옛 글(1위)도 찾고, 못 읽었으면 시트 다른 글(2위)만 — 어느 쪽이든 부분 자료
    urls = [h["url"].split("?")[0] for h in rec["hits"]]
    assert urls == ([OTHER_SHEET] if ledger_fail else [ON_PAGE, OTHER_SHEET])
    cell = writes[(TAB, 2)][HEADER_SUBSTITUTE]
    assert cell.startswith("확인 못 함 (옛 글 출처 못 읽음") and "— 찾은 것: 인기글" in cell
    assert writes[(TAB, 3)][HEADER_SUBSTITUTE] == ""  # 제 글 찾은 줄 = 맞대지 않음
    assert writes[(TAB, 2)][HEADER_AREA].startswith("미노출")  # K 그대로
    assert summary["substitute_scan_errors"] == 1 and summary["substitute_rows_with_hits_partial"] == 1
    tr = {r["row"]: r for r in trace}
    assert tr[2]["substitute_error"] == rec["error"] and tr[2]["substitute_complete"] is False
    cnt = _counter().count(trace, recs)["전체"]
    assert (cnt["비포"], cnt["대체"], cnt["애프터"], cnt["맞대기실패"], cnt["대체_확인못함"]) == (1, 0, 1, 1, 1)


# ── 지적 3: 카페 + 글번호 ────────────────────────────────────────────────

def test_열쇠는_카페와_글번호를_함께_쓴다():
    k = substitute.link_key
    assert k("https://cafe.naver.com/ccrs5500/777989") != k("https://cafe.naver.com/not-ccrs5500/777989")
    # 같은 글의 주소 꼴(확인됨): m. · http · 물음표 뒤 · 끝 /
    same = ["https://cafe.naver.com/ccrs5500/777989", "https://m.cafe.naver.com/ccrs5500/777989?art=abc",
            "http://cafe.naver.com/ccrs5500/777989/"]
    assert len({k(u) for u in same}) == 1
    # 카페 이름 ↔ 카페 번호: 매핑 없으면 다른 글, 확인된 매핑이 있을 때만 같은 글
    new = "https://cafe.naver.com/ca-fe/cafes/12345/articles/777989"
    assert k(new) != k(same[0])
    assert k(new, {"slug:ccrs5500": "id:12345"}) == k(same[0], {"slug:ccrs5500": "id:12345"})
    # 다른 카페 번호 같은 글번호 = 다른 글
    assert k("https://cafe.naver.com/ca-fe/cafes/111/articles/5") != k("https://cafe.naver.com/ca-fe/cafes/222/articles/5")
    # 대소문자 다른 카페 이름도 매핑 없으면 같다고 하지 않음
    assert k("https://cafe.naver.com/Abc/1") != k("https://cafe.naver.com/abc/1")
    # 글을 가리키지 못하는 카페 주소 = 열쇠 없음(어느 글과도 같지 않음)
    assert k("https://cafe.naver.com/ccrs5500") is None
    assert k("https://cafe.naver.com/ca-fe/home/feed") is None
    assert k("https://cafe.naver.com/ArticleRead.nhn?clubid=1&articleid=2") == ("cafe", "clubid:1", "2")


def test_대체_매치_다른_카페_같은_번호는_우리_글_아님():
    # 품질 재현: 목록에는 not-ccrs5500/777989 하나 → 화면의 ccrs5500/777989 를 우리 글로 내면 안 됨
    idx = substitute.build_index({TAB: [_row("https://cafe.naver.com/not-ccrs5500/777989", keyword="x", r=10)]})
    assert substitute.scan(_html(), idx, TAB, KW) == []
    # 옛 글(키워드별) 쪽도 같음
    idx2 = substitute.build_index({}, [{"탭": TAB, "키워드": KW, "링크": "https://cafe.naver.com/zzz/777989"}], [])
    assert substitute.scan(_html(), idx2, TAB, KW) == []
    # 진짜 같은 카페 같은 번호는 그대로 찾는다
    idx3 = substitute.build_index({TAB: [_row(ON_PAGE, keyword="x", r=10)]})
    assert [h["url"].split("?")[0] for h in substitute.scan(_html(), idx3, TAB, KW)] == [ON_PAGE]


def test_대체_매치_확인된_매핑이면_신형_주소도_같은_글():
    new = "https://cafe.naver.com/ca-fe/cafes/12345/articles/777989"
    no_map = substitute.build_index({TAB: [_row(new, keyword="x", r=10)]})
    assert substitute.scan(_html(), no_map, TAB, KW) == []
    mapped = substitute.build_index({TAB: [_row(new, keyword="x", r=10)]}, aliases={"slug:ccrs5500": "id:12345"})
    assert [h["url"].split("?")[0] for h in substitute.scan(_html(), mapped, TAB, KW)] == [ON_PAGE]


def test_제_글_제외_다른_카페_같은_번호는_빼지_않는다():
    idx = substitute.build_index({TAB: [_row("https://cafe.naver.com/not-ccrs5500/777989", keyword="x", r=10)]})
    m = idx.matcher_for(TAB, KW, own_link="https://cafe.naver.com/another-cafe/777989")
    assert m("https://cafe.naver.com/not-ccrs5500/777989") == "시트"  # 품질 재현에서는 None 이었음
    # 제 글(같은 카페 · 주소 꼴만 다름)은 뺀다
    m2 = idx.matcher_for(TAB, KW, own_link="https://m.cafe.naver.com/not-ccrs5500/777989?art=q")
    assert m2("https://cafe.naver.com/not-ccrs5500/777989") is None
    # 화면 전체로: 제 링크가 다른 카페 같은 번호여도 화면의 우리 글은 대체로 잡힌다.
    # (_process_row 를 거치면 기존 K 판정(parser._urls_match)이 other-cafe/777989 를 화면의 ccrs5500/777989 와
    #  같은 글로 보고 '노출'로 판정해 맞대기까지 가지 않는다 — 기존 K 쪽 같은 원인, 이 카드 범위 밖 · report 에 적음.)
    idx3 = substitute.build_index({TAB: [_row(ON_PAGE, keyword="x", r=10)]})
    hits = substitute.scan(_html(), idx3, TAB, KW, own_link="https://cafe.naver.com/other-cafe/777989")
    assert [h["url"].split("?")[0] for h in hits] == [ON_PAGE]


def test_중복_제거_다른_카페_같은_번호는_둘_다_남는다(monkeypatch):
    a = "https://cafe.naver.com/ccrs5500/777989"
    b = "https://cafe.naver.com/zzop/777989"
    a_again = "https://m.cafe.naver.com/ccrs5500/777989?art=x"  # a 와 같은 글(다른 구좌에 또 뜸)
    fake = [OurPostHit(area="인기글", integrated_rank=1, cafe_slot_rank=1, url=a),
            OurPostHit(area="인기글", integrated_rank=2, cafe_slot_rank=2, url=b),
            OurPostHit(area="스마트블록", integrated_rank=1, cafe_slot_rank=1, url=a_again)]
    monkeypatch.setattr(substitute, "find_all_our_posts", lambda html, is_ours: [h for h in fake if is_ours(h.url)])
    idx = substitute.build_index({TAB: [_row(a, keyword="x", r=10), _row(b, keyword="y", r=11)]})
    out = substitute.scan("<html/>", idx, TAB, KW)
    assert [(h["url"], h["area"]) for h in out] == [(a, "인기글"), (b, "인기글")]
