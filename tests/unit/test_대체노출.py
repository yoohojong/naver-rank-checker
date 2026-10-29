"""대체 노출 재기 (2026-10-29) — 미노출·누락 줄에 우리 다른 글이 떠 있나.

카드 완료 증거:
  ① 링크 줄 미노출 + 다른 우리 글 노출 → 대체 칸에 그 글 · 구좌 · 순위
  ② 우리 글 2개 → 둘 다
  ③ 아무것도 없음 → 빈칸
  ④ 고침 전후 fetch_search 부르는 수 같음
  ⑤ 노출영역(K)·L·M·O 값이 바뀐 줄 0개 (표본 전부 비교)
"""
from __future__ import annotations

import glob
import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src import parser as parser_module
from src import substitute
from src.crawler import CafeStatus
from src.health import HealthMonitor
from src.main import _process_row
from src.sheets import HEADER_AREA, HEADER_JISIKIN, HEADER_L, HEADER_M

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "naver"
STAMP = "10/29 09:00"
TAB = "샴푸 카외"
KW = "비듬샴푸"

# popular_same_cafe_two_cards.html 의 인기글 박스 (화면 칸 순서)
#   1칸 ccrs5500/777989 · 774361 · 773882 / 2칸 cantsb/3406915 · 3340742 / 3칸 블로그 / 4칸 gangmok/2073966 …
TWO_CARDS = "popular_same_cafe_two_cards.html"
MISSING = "https://cafe.naver.com/ccrs5500/999999"  # 이 줄 제 글 — 화면에 없음
OTHER_SHEET = "https://cafe.naver.com/cantsb/3406915"  # 시트 다른 줄 링크
OLD_LEDGER = "https://cafe.naver.com/ccrs5500/777989"  # 글 장부의 같은 키워드 옛 글


def _html(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def _crawler(html: str, status=CafeStatus.ALIVE) -> MagicMock:
    c = MagicMock()
    c.fetch_search.return_value = html
    c.fetch_cafe_url_status.return_value = status
    return c


def _row(link: str, keyword: str = KW, k: str = "", tab: str = TAB, r: int = 2) -> dict:
    return {"키워드": keyword, "링크": link, HEADER_AREA: k, "_row": r, "_tab": tab}


def _index(sheet_links=(), ledger=(), archive=(), **kw):
    data = {TAB: [_row(u, keyword="다른키워드", r=10 + i) for i, u in enumerate(sheet_links)]}
    return substitute.build_index(data, list(ledger), list(archive), **kw)


def _visible(cols: dict) -> dict:
    return {h: cols.get(h) for h in (HEADER_AREA, HEADER_L, HEADER_M, HEADER_JISIKIN, "링크")}


# ── ① ② ③ ───────────────────────────────────────────────────────────────

def test_링크줄_미노출에_시트_다른_글이_뜨면_그_글_구좌_순위():
    idx = _index(sheet_links=[OTHER_SHEET])
    cols = _process_row(_row(MISSING), _crawler(_html(TWO_CARDS)), HealthMonitor(),
                        today_stamp=STAMP, our_index=idx)
    assert cols[HEADER_AREA].startswith("미노출")
    hits = cols["_substitute"]["hits"]
    assert [(h["url"].split("?")[0], h["area"], h["rank"], h["cafe_rank"], h["source"]) for h in hits] == [
        (OTHER_SHEET, "인기글", 2, 2, "시트"),
    ]
    assert substitute.format_cell(hits) == f"인기글 2위 {hits[0]['url']}"


def test_우리_글_2개면_둘_다_순위대로():
    idx = _index(sheet_links=[OTHER_SHEET],
                 ledger=[{"탭": TAB, "키워드": KW, "링크": OLD_LEDGER}])
    cols = _process_row(_row(MISSING, k="인기글 (10/28 09:00~)"), _crawler(_html(TWO_CARDS)),
                        HealthMonitor(), today_stamp=STAMP, our_index=idx)
    assert cols[HEADER_AREA].startswith("누락")
    got = [(h["url"].split("?")[0], h["area"], h["rank"], h["cafe_rank"], h["source"])
           for h in cols["_substitute"]["hits"]]
    assert got == [
        (OLD_LEDGER, "인기글", 1, 1, "글장부"),
        (OTHER_SHEET, "인기글", 2, 2, "시트"),
    ]
    cell = substitute.format_cell(cols["_substitute"]["hits"])
    assert cell.startswith("인기글 1위 ") and " / 인기글 2위 " in cell


def test_아무것도_없으면_빈칸():
    idx = _index(sheet_links=["https://cafe.naver.com/nowhere/1"])
    cols = _process_row(_row(MISSING), _crawler(_html(TWO_CARDS)), HealthMonitor(),
                        today_stamp=STAMP, our_index=idx)
    assert cols["_substitute"] == {"hits": []}
    assert substitute.format_cell(cols["_substitute"]["hits"]) == ""


def test_옛_글은_같은_탭_같은_키워드에만_맞댄다():
    idx = _index(ledger=[{"탭": TAB, "키워드": "다른 키워드", "링크": OLD_LEDGER},
                         {"탭": "바디워시 카외", "키워드": KW, "링크": OLD_LEDGER}])
    cols = _process_row(_row(MISSING), _crawler(_html(TWO_CARDS)), HealthMonitor(),
                        today_stamp=STAMP, our_index=idx)
    assert cols["_substitute"]["hits"] == []
    # 키워드 띄어쓰기 차이는 같은 키워드로 본다
    idx2 = _index(ledger=[{"탭": TAB, "키워드": " 비듬샴푸 ", "링크": OLD_LEDGER}])
    cols2 = _process_row(_row(MISSING), _crawler(_html(TWO_CARDS)), HealthMonitor(),
                         today_stamp=STAMP, our_index=idx2)
    assert len(cols2["_substitute"]["hits"]) == 1


def test_이력_탭_링크도_옛_글로_쓴다():
    idx = _index(archive=[{"탭": TAB, "키워드": KW, "링크": OLD_LEDGER}])
    cols = _process_row(_row(MISSING), _crawler(_html(TWO_CARDS)), HealthMonitor(),
                        today_stamp=STAMP, our_index=idx)
    assert [h["source"] for h in cols["_substitute"]["hits"]] == ["이력"]


def test_제_링크는_대체로_안_센다_그리고_찾으면_스캔_안함():
    # 제 글이 떠 있으면 판정이 노출 → 대체 재기 자체를 안 한다
    idx = _index(sheet_links=[OLD_LEDGER, OTHER_SHEET])
    cols = _process_row(_row(OLD_LEDGER), _crawler(_html(TWO_CARDS)), HealthMonitor(),
                        today_stamp=STAMP, our_index=idx)
    assert "_substitute" not in cols
    # matcher 단위: 제 링크(신형·구형·?art 꼬리 달라도)는 None
    m = idx.matcher_for(TAB, KW, own_link=OLD_LEDGER + "?art=abc")
    assert m("https://m.cafe.naver.com/ccrs5500/777989") is None
    assert m(OTHER_SHEET + "?art=zz") == "시트"


def test_빈_링크_줄_미노출도_옛_글을_맞대고_K는_그대로():
    # all_known_links(시트 지금 링크)에 없으니 K=미노출 그대로, 옛 글은 기록에만
    idx = _index(ledger=[{"탭": TAB, "키워드": KW, "링크": OLD_LEDGER}])
    known = {"https://cafe.naver.com/nowhere/1"}
    cols = _process_row(_row(""), _crawler(_html(TWO_CARDS)), HealthMonitor(),
                        all_known_links=known, today_stamp=STAMP, our_index=idx)
    assert cols[HEADER_AREA].startswith("미노출")
    assert "링크" not in cols
    assert [h["url"].split("?")[0] for h in cols["_substitute"]["hits"]] == [OLD_LEDGER]


def test_스캔이_터져도_판정은_그대로이고_사유를_남긴다(monkeypatch):
    idx = _index(sheet_links=[OTHER_SHEET])
    before = _process_row(_row(MISSING), _crawler(_html(TWO_CARDS)), HealthMonitor(), today_stamp=STAMP)

    def boom(*a, **k):
        raise RuntimeError("일부러")
    monkeypatch.setattr(substitute, "scan", boom)
    cols = _process_row(_row(MISSING), _crawler(_html(TWO_CARDS)), HealthMonitor(),
                        today_stamp=STAMP, our_index=idx)
    assert _visible(cols) == _visible(before)
    assert cols["_substitute"]["hits"] == [] and "일부러" in cols["_substitute"]["error"]


def test_못_읽은_출처는_0이_아니라_사유():
    client = MagicMock()
    client.spreadsheet.worksheet.side_effect = Exception("WorksheetNotFound")
    l_rows, l_err, a_rows, a_err = substitute.read_private_sources(client)
    idx = substitute.build_index({}, l_rows, a_rows, ledger_error=l_err, archive_error=a_err)
    assert idx.counts["글장부"].startswith("못 읽음") and idx.counts["이력"].startswith("못 읽음")


def test_스캔은_순위_신호를_두번_세지_않는다():
    parser_module.reset_rank_signals()
    parser_module.rank_signals["fallback_boxes"] = 3
    parser_module.find_all_our_posts(_html(TWO_CARDS), lambda u: True)
    assert parser_module.rank_signals == {"fallback_boxes": 3, "mismatch_boxes": 0}


def test_찾은_순위는_판정과_같은_셈이다():
    """표본 전부: 찾은 글마다 parse_search_result(그 글) 의 구좌·L·M 과 같아야 한다."""
    n = 0
    for f in sorted(glob.glob(str(FIX / "*.html"))):
        html = Path(f).read_text(encoding="utf-8")
        for h in parser_module.find_all_our_posts(html, lambda u: "cafe.naver.com" in u):
            r = parser_module.parse_search_result(html, h.url)
            if r.matched_url is None:
                continue
            # 같은 글이 위 구좌에서 먼저 잡힌 경우는 판정이 그 구좌를 돌려준다 — 같은 구좌만 비교
            if r.exposure_area.value != h.area:
                continue
            assert (r.integrated_rank, r.cafe_slot_rank) == (h.integrated_rank, h.cafe_slot_rank), (f, h)
            n += 1
    assert n >= 20


# ── ④ ⑤ 표본 전부: 부르는 수 같음 · K/L/M/O 바뀐 줄 0 ─────────────────────

def _all_sample_rows():
    """표본 html 마다: 화면에 있는 카페 글 링크 줄 · 없는 링크 줄 · 빈 링크 줄 · 누락 이력 줄."""
    cases = []
    for f in sorted(glob.glob(str(FIX / "*.html"))):
        html = Path(f).read_text(encoding="utf-8")
        on_page = [h.url for h in parser_module.find_all_our_posts(html, lambda u: "cafe.naver.com" in u)]
        links = on_page[:3] + [MISSING, ""]
        for i, link in enumerate(links):
            for prev_k in ("", "인기글 (10/28 09:00~)", "미노출 (10/20 09:00~)"):
                cases.append((Path(f).name, html, _row(link, k=prev_k, r=2 + i)))
    return cases, [h for h in (OTHER_SHEET, OLD_LEDGER)]


def test_표본_전부_K_L_M_O_바뀐_줄_0_그리고_부르는_수_같음(capsys):
    cases, _ = _all_sample_rows()
    # 우리 글 목록 = 표본 화면의 카페 글 전부 + 위 두 글 (대체가 많이 생기게 일부러 넓게)
    every = set()
    for _, html, _r in cases:
        every.update(h.url for h in parser_module.find_all_our_posts(html, lambda u: "cafe.naver.com" in u))
    idx = substitute.build_index(
        {TAB: [_row(u, keyword="x", r=100 + i) for i, u in enumerate(sorted(every))]},
        [{"탭": TAB, "키워드": KW, "링크": OLD_LEDGER}], [],
    )
    known = {OTHER_SHEET}
    changed = 0
    calls_before = calls_after = 0
    status_before = status_after = 0
    with_hits = 0
    for name, html, row in cases:
        c0, c1 = _crawler(html), _crawler(html)
        b = _process_row(dict(row), c0, HealthMonitor(), all_known_links=known, today_stamp=STAMP)
        a = _process_row(dict(row), c1, HealthMonitor(), all_known_links=known, today_stamp=STAMP,
                         our_index=idx)
        if b is None:
            assert a is None
            continue
        if _visible(a) != _visible(b):
            changed += 1
        assert {k: v for k, v in a.items() if k != "_substitute"} == b, name
        calls_before += c0.fetch_search.call_count
        calls_after += c1.fetch_search.call_count
        status_before += c0.fetch_cafe_url_status.call_count
        status_after += c1.fetch_cafe_url_status.call_count
        with_hits += bool((a.get("_substitute") or {}).get("hits"))
    capsys.readouterr()
    print(f"[증거] 표본 줄 {len(cases)} · K/L/M/O 바뀐 줄 {changed} · fetch_search {calls_before}→{calls_after}"
          f" · 카페 글 열기 {status_before}→{status_after} · 대체 뜬 줄 {with_hits}")
    assert changed == 0
    assert calls_before == calls_after == len(cases)
    assert status_before == status_after
    assert with_hits > 0  # 시험이 헛돌지 않았다


# ── 회차 전체(run_cycle): 끄고 켜도 시트 쓰기 같음 · 기록 파일 생김 ───────────

def _run_cycle(tmp_path, monkeypatch, enabled: bool):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUBSTITUTE_SCAN", "1" if enabled else "0")
    monkeypatch.setenv("GOYU_NOTIFY_OFF", "1")
    for name in ("ARCHIVE_ENABLED", "STALE_OUTPUT_FORMULA_MODE", "RECHECK_STALE_ONLY",
                 "TYPE_PREVIEW_WRITE_CONFIRMED", "GITHUB_ACTIONS"):
        monkeypatch.delenv(name, raising=False)
    rows = {TAB: [_row(MISSING, r=2), _row(OTHER_SHEET, keyword="다른키워드", r=3), _row("", r=4)]}
    client = MagicMock()
    client.load_all_data_tabs.return_value = rows
    client.write_results.return_value = 0

    def worksheet(name):
        ws = MagicMock()
        if name == substitute.LEDGER_TAB_NAME:
            ws.get_all_values.return_value = [substitute.LEDGER_TAB_HEADER, [TAB, KW, OLD_LEDGER, "2026-09-01", "k"]]
        elif name == substitute.ARCHIVE_TAB_NAME:
            ws.get_all_values.return_value = [["날짜", "탭", "키워드", "노출영역", "통합순위", "카페구좌순위", "링크"]]
        else:
            raise Exception("WorksheetNotFound")
        return ws
    client.spreadsheet.worksheet.side_effect = worksheet
    crawler = _crawler(_html(TWO_CARDS))
    with patch("src.main.SheetsClient", return_value=client), \
         patch("src.main.Crawler", return_value=crawler), \
         patch("src.main.SPREADSHEET_ID", "fake"), \
         patch("src.main.SERVICE_ACCOUNT_JSON", "{}"), \
         patch("src.main.random.shuffle", lambda x: None):
        from src.main import run_cycle
        summary = run_cycle()
    writes = sorted(
        (call.args[0], u.row, tuple(sorted(u.columns.items())))
        for call in client.write_results.call_args_list for u in call.args[1]
    )
    return summary, writes, crawler.fetch_search.call_count


def test_회차_끄고_켜도_시트_쓰기와_검색_수가_같고_기록만_생긴다(tmp_path, monkeypatch):
    (tmp_path / "off").mkdir()
    (tmp_path / "on").mkdir()
    s0, w0, n0 = _run_cycle(tmp_path / "off", monkeypatch, enabled=False)
    s1, w1, n1 = _run_cycle(tmp_path / "on", monkeypatch, enabled=True)
    # 시트에 가는 값: 켬 = 끔 + '대체 노출' 칸 하나만 더해짐(D-062 사장님 승인 10-29 17:5x). K/L/M/O·그 밖 칸은 같다.
    assert w0 and len(w0) == len(w1)
    from src.sheets import HEADER_SUBSTITUTE
    assert all(HEADER_SUBSTITUTE not in dict(cols) for _, _, cols in w0)  # 끔 = 칸 쓰기 없음
    sub_cells = {}
    for (t0, r0, c0), (t1, r1, c1) in zip(w0, w1):
        c1 = dict(c1)
        assert (t0, r0) == (t1, r1)
        sub_cells[r1] = c1.pop(HEADER_SUBSTITUTE)  # 켬 = 줄마다 그 칸이 꼭 있다
        assert c1 == dict(c0), r1  # 더해진 것은 그 칸 하나뿐
    assert all("_substitute" not in dict(cols) for _, _, cols in w1)
    # 2행 = 옛 글 1위 + 시트 다른 글 2위(출처 다 읽음 = 완전 확인) · 3행 = 제 글 찾음 = 맞대지 않아 빈칸
    assert sub_cells[2].startswith("인기글 1위 https://cafe.naver.com/ccrs5500/777989")
    assert " / 인기글 2위 https://cafe.naver.com/cantsb/3406915" in sub_cells[2]
    assert sub_cells[3] == ""
    # 빈 링크 줄은 시트 지금 링크(all_known_links)가 비면 원래도 검색하지 않는다(고침 전과 같음).
    # 이 시험은 카페 허용 목록이 비어 있어 2번(링크 줄 2개)만 검색한다.
    assert n0 == n1 == 2
    assert s0["substitute_enabled"] is False and s1["substitute_enabled"] is True
    assert s1["substitute_index_counts"]["글장부"] == 1
    out = list((tmp_path / "on" / ".harness" / "substitutes").glob("*.jsonl"))
    assert len(out) == 1
    recs = [json.loads(x) for x in out[0].read_text(encoding="utf-8").splitlines()]
    by_row = {r["row"]: r for r in recs}
    # 2행(제 글 없음): 옛 글 1위 + 시트 다른 글 2위. 3행(제 글 2위로 노출) = 기록 대상 아님.
    assert sorted(by_row) == [2]
    assert [h["url"].split("?")[0] for h in by_row[2]["hits"]] == [OLD_LEDGER, OTHER_SHEET]
    assert by_row[2]["substitute_cell"].startswith("인기글 1위")
    assert s1["substitute_rows_with_hits"] >= 1
    assert not list((tmp_path / "off" / ".harness").glob("substitutes/*.jsonl"))
    # 회차 요약: 맞대기 시간 · 맞댄 줄 · 맞댄 글 수
    assert s1["substitute_scan_calls"] == 1 and s1["substitute_scan_seconds"] >= 0
    assert s1["substitute_index_size"]["키워드별"] == 1 and s0["substitute_scan_calls"] == 0
    # 비포·애프터: 같은 회차 trace 줄마다 K 와 대체 값이 같이 남는다
    trace = list((tmp_path / "on" / ".harness" / "traces").glob("*.jsonl"))[0]
    tr = {r["row"]: r for r in map(json.loads, trace.read_text(encoding="utf-8").splitlines())}
    assert tr[2]["new_K_base"] == "미노출" and tr[2]["substitute_count"] == 2
    assert tr[2]["substitute_cell"].startswith("인기글 1위")
    assert tr[3]["substitute_scanned"] is False and tr[3]["new_K_base"] == "인기글"
    trace_off = list((tmp_path / "off" / ".harness" / "traces").glob("*.jsonl"))[0]
    assert all("substitute_scanned" not in json.loads(x) for x in trace_off.read_text(encoding="utf-8").splitlines())
    # 셈 스크립트
    cnt = _load_script("count_substitute_before_after")
    res = cnt.count(cnt._read_jsonl(str(trace)), cnt._read_jsonl(str(out[0])))
    assert res["전체"]["줄"] == 3 and res["전체"]["비포"] == 1 and res["전체"]["애프터"] == 2
    assert res["전체"]["맞대기실패"] == 0 and res["전체"]["대체_확인못함"] == 0
    assert tr[2]["substitute_complete"] is True
    assert [(t["행"], t["대신 뜬 글"].split("?")[0], t["구좌"], t["순위"]) for t in res["대체 줄 표"]] == [
        (2, OLD_LEDGER, "인기글", 1), (2, OTHER_SHEET, "인기글", 2)]
    assert "error" in cnt.count(cnt._read_jsonl(str(trace_off)))  # 고침 전 회차 = 0 이 아니라 '셀 수 없음'


def _load_script(name: str):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parents[2] / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 글 장부 → 비공개 숨긴 탭 스크립트 ───────────────────────────────────

def _tiny_ledger(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE posts (key TEXT PRIMARY KEY, ref TEXT);"
        "CREATE TABLE assignments (key TEXT, tab TEXT, keyword TEXT, workdate_raw TEXT, workdate TEXT);"
    )
    con.executemany("INSERT INTO posts VALUES (?,?)", [
        ("a/1", "https://cafe.naver.com/a/1?art=LONGTOKEN"), ("b/2", None)])
    con.executemany("INSERT INTO assignments VALUES (?,?,?,?,?)", [
        ("a/1", "샴푸 카외", "비듬 샴푸", "9/1", "2026-09-01"),
        ("a/1", "샴푸 카외", "비듬  샴푸", "9/2", "2026-09-02"),  # 같은 글·같은 키워드(띄어쓰기) = 한 줄
        ("b/2", "샴푸 카외", "비듬샴푸", "9/3", "2026-09-03"),
        ("a/1", "발행 검수", "비듬샴푸", "9/4", "2026-09-04"),  # 순위체커 탭 아님 = 뺌
    ])
    con.commit()
    con.close()


def test_장부_스크립트_보기만은_시트를_안_건드린다(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ledger_to_sheet_tab", Path(__file__).resolve().parents[2] / "scripts" / "ledger_to_sheet_tab.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    db = tmp_path / "ledger.db"
    _tiny_ledger(db)
    rows = mod.read_ledger_rows(str(db))
    assert rows == [
        ["샴푸 카외", "비듬 샴푸", "https://cafe.naver.com/a/1", "2026-09-01", "a/1"],
        ["샴푸 카외", "비듬샴푸", "https://cafe.naver.com/b/2", "2026-09-03", "b/2"],
    ]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ledger.db"]  # 곁파일(-wal·-shm) 안 생김
    assert mod.main(["--db", str(db), "--out", str(tmp_path / "out")]) == 0
    assert mod.main(["--db", str(db), "--write"]) == 2  # 승인 표시 없이 쓰기 = 거절
    # 쓰기 함수는 이 탭 하나만 지우고 쓰고 숨긴다
    ss = MagicMock()
    ws = MagicMock(row_count=1000, id=7)
    ss.worksheet.return_value = ws
    res = mod.write_tab(ss, rows)
    ss.worksheet.assert_called_once_with("우리글_장부")
    ws.clear.assert_called_once()
    req = ss.batch_update.call_args.args[0]["requests"][0]["updateSheetProperties"]
    assert req["properties"] == {"sheetId": 7, "hidden": True}
    assert res["rows_written"] == 2
