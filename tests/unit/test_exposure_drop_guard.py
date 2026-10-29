"""노출 급감 멈춤 (2026-10-29) — 18:00 회차 노출 552→173 을 그대로 쓴 사고의 재발 막기.

검사하는 것
  1. 판정: 552→173 = 멈춤 · 552→540 = 통과 · 기준 못 읽음/첫 회차 = 비교 못 함 · 스위치 = 풀림 · 장치 고장 = 비교 못 함
  2. run_cycle 배선: 멈춤이면 K/L/M/O · C열 쓰기 0, 산출물엔 그대로, 종료 코드 0(실패 아님)
                    통과 · 비교 못 함이면 예전처럼 씀
  3. K 값 규칙 · 검색 횟수는 장치가 있든 없든 같다(세기만 한다)
  4. 알림: 텔레그램 한 줄 · 같은 회차 문자 생략을 타지 않음 · 이슈 댓글 줄 · 워크플로 스위치
"""
from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src import exposure_drop_guard as G
from src.parser import ExposureArea, RankResult
from src.transitions import parse_K_with_stamp

STAMP = "10/22 12:00"


def _upd(row: int, k: str):
    return SimpleNamespace(row=row, columns={"노출영역": k})


def _sample(total_exposed: int, still_exposed: int, tab: str = "샴푸 카외", raw: bool = True):
    """노출 total_exposed 줄 중 still_exposed 줄만 이번에도 노출(나머지는 누락)."""
    tab_updates = {tab: []}
    row_context = {}
    for i in range(total_exposed):
        row_no = i + 2
        prev = f"AB ({STAMP}~)"
        row = {"키워드": f"kw{i}", "_row": row_no, "_tab": tab}
        if raw:
            row["raw_노출영역"] = prev
            row["노출영역"] = "재검사필요" if i % 7 == 0 else prev   # 보이는 칸은 공식 표시일 수 있다
        else:
            row["노출영역"] = prev
        row_context[(tab, row_no)] = row
        new = prev if i < still_exposed else "누락 (10/29 18:00~)"
        tab_updates[tab].append(_upd(row_no, new))
    return tab_updates, row_context


class Test판정:
    def test_552에서_173이면_멈춤(self):
        tu, rc = _sample(552, 173)
        r = G.evaluate(tu, rc)
        assert r["status"] == G.STATUS_HOLD
        assert (r["baseline_exposed"], r["current_exposed"], r["drop_rows"]) == (552, 173, 379)
        assert r["drop_ratio"] == pytest.approx(379 / 552, abs=1e-4)
        assert r["lost_examples"] and r["lost_examples"][0]["new_K"].startswith("누락")

    def test_552에서_540이면_통과(self):
        tu, rc = _sample(552, 540)
        r = G.evaluate(tu, rc)
        assert r["status"] == G.STATUS_PASS
        assert (r["baseline_exposed"], r["current_exposed"]) == (552, 540)

    def test_딱_20퍼센트는_멈추지_않는다(self):
        tu, rc = _sample(100, 80)
        assert G.evaluate(tu, rc)["status"] == G.STATUS_PASS
        tu, rc = _sample(100, 79)
        assert G.evaluate(tu, rc)["status"] == G.STATUS_HOLD

    def test_기준은_raw_칸을_먼저_본다(self):
        """보이는 칸이 '재검사필요'여도 raw_노출영역이 AB 면 노출로 센다(공식 모드)."""
        tu, rc = _sample(552, 552)
        r = G.evaluate(tu, rc)
        assert r["baseline_exposed"] == 552
        assert r["prev_k_distribution"] == {"AB": 552}

    def test_raw_칸이_없으면_보이는_칸(self):
        tu, rc = _sample(552, 173, raw=False)
        assert G.evaluate(tu, rc)["status"] == G.STATUS_HOLD

    def test_기준_칸을_못_읽으면_비교_못_함(self):
        tu, rc = _sample(552, 173)
        rc = {k: {"키워드": v["키워드"], "_row": v["_row"]} for k, v in rc.items()}   # K 칸 없음
        r = G.evaluate(tu, rc)
        assert r["status"] == G.STATUS_NO_COMPARE
        assert "못 읽음" in r["reason"] and r["rows_unreadable"] == 552

    def test_첫_회차는_비교_못_함(self):
        """기준 노출이 거의 없으면(새 시트 · 첫 회차) 비율이 흔들려 막지 않는다."""
        tu, rc = _sample(5, 0)
        r = G.evaluate(tu, rc)
        assert r["status"] == G.STATUS_NO_COMPARE
        assert "첫 회차" in r["reason"]

    def test_쓸_줄이_없으면_비교_못_함(self):
        r = G.evaluate({}, {})
        assert r["status"] == G.STATUS_NO_COMPARE and r["reason"]

    def test_사람_스위치면_풀림(self):
        tu, rc = _sample(552, 173)
        r = G.evaluate(tu, rc, allow=True)
        assert r["status"] == G.STATUS_RELEASED and r["allow_switch"] is True

    def test_스위치는_급감_아닐_때_아무것도_안_바꾼다(self):
        tu, rc = _sample(552, 540)
        assert G.evaluate(tu, rc, allow=True)["status"] == G.STATUS_PASS

    def test_장치가_고장나면_통과가_아니라_비교_못_함(self):
        """장치 고장 시험 — 결과를 '통과'로 바꾸지 않는다."""
        tu = {"샴푸 카외": [object()]}   # .row 가 없는 깨진 입력
        r = G.evaluate(tu, {})
        assert r["status"] == G.STATUS_NO_COMPARE
        assert "오류" in r["reason"]

    def test_중복노출도_노출로_센다(self):
        tu = {"t": [_upd(2, "중복노출(AB) (10/29 18:00~)")]}
        rc = {("t", 2): {"raw_노출영역": f"AB ({STAMP}~)"}}
        r = G.evaluate(tu, rc, min_baseline=1)
        assert r["status"] == G.STATUS_PASS and r["current_exposed"] == 1


# ── run_cycle 배선 ─────────────────────────────────────────────────────────────
TAB = "샴푸 카외"


def _fake_sheet(n: int, with_k: bool = True) -> dict:
    rows = []
    for i in range(n):
        r = {
            "키워드": f"샴푸키워드{i}",
            "링크": f"https://cafe.naver.com/cosmania/{100000 + i}",
            "_row": i + 2,
            "_tab": TAB,
        }
        if with_k:
            r["노출영역"] = f"AB ({STAMP}~)"
            r["raw_노출영역"] = f"AB ({STAMP}~)"
        rows.append(r)
    return {TAB: rows}


def _run(monkeypatch, tmp_path, n_rows: int, still_exposed: int, *, allow=False, with_k=True):
    """가짜 시트 · 가짜 검색으로 run_cycle 을 돌린다. 시트 · 네이버 요청 0."""
    monkeypatch.chdir(tmp_path)
    for name in ("GITHUB_ACTIONS", "ARCHIVE_ENABLED", "STALE_OUTPUT_FORMULA_MODE",
                 "RECHECK_STALE_ONLY", "TYPE_PREVIEW_WRITE_ALLOW_BULK", "GITHUB_RUN_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TYPE_PREVIEW_WRITE_CONFIRMED", "true")
    if allow:
        monkeypatch.setenv(G.ENV_ALLOW, "true")
    else:
        monkeypatch.delenv(G.ENV_ALLOW, raising=False)

    sheet = _fake_sheet(n_rows, with_k=with_k)
    exposed_links = {r["링크"] for r in sheet[TAB][:still_exposed]}

    client = MagicMock()
    client.load_all_data_tabs.return_value = sheet
    client.write_results.return_value = 0
    client.write_type_results.return_value = 0
    client_cls = MagicMock(return_value=client)

    crawler = MagicMock()
    crawler.warmup.return_value = None
    crawler.fetch_search.side_effect = lambda kw: "<html></html>"
    crawler.fetch_cafe_url_status.return_value = None
    crawler_cls = MagicMock(return_value=crawler)

    def fake_parse(html, target_url=None, link_set=None, **kw):
        if target_url in exposed_links:
            return RankResult(exposure_area=ExposureArea.AB, integrated_rank=1, cafe_slot_rank=1,
                              parser_confidence=1.0, matched_url=target_url, block_order=["AB"])
        return RankResult(parser_confidence=1.0)

    with patch("src.main.SheetsClient", client_cls), \
         patch("src.main.Crawler", crawler_cls), \
         patch("src.main.parse_search_result", side_effect=fake_parse), \
         patch("src.main.SPREADSHEET_ID", "fake_id"), \
         patch("src.main.SERVICE_ACCOUNT_JSON", "{}"):
        from src.main import run_cycle
        summary = run_cycle()
    return summary, client, crawler


def _trace(tmp_path) -> list[dict]:
    files = list(pathlib.Path(tmp_path, ".harness/traces").glob("*row-trace.jsonl"))
    assert len(files) == 1
    return [json.loads(x) for x in files[0].read_text(encoding="utf-8").splitlines()]


def _written_rows(client) -> int:
    return sum(len(c.args[1]) for c in client.write_results.call_args_list) + \
        sum(len(c.args[1]) for c in client.write_stale_formula_results.call_args_list)


class Test회차_배선:
    def test_552에서_173이면_쓰기를_멈추고_실패가_아니다(self, monkeypatch, tmp_path):
        s, client, crawler = _run(monkeypatch, tmp_path, 552, 173)
        assert s["exposure_drop_status"] == G.STATUS_HOLD
        assert s["exposure_drop_hold"] is True
        assert (s["exposure_drop"]["baseline_exposed"], s["exposure_drop"]["current_exposed"]) == (552, 173)
        # K/L/M/O · C열 쓰기 0
        client.write_results.assert_not_called()
        client.write_stale_formula_results.assert_not_called()
        client.write_type_results.assert_not_called()
        assert s["total_cells_written"] == 0
        # 실패(rc=2)로 올리지 않는다 — '멈춤'
        assert not s.get("code_change_suspected")
        # 결과는 산출물에 그대로 남아 사람이 본다
        tr = _trace(tmp_path)
        assert len(tr) == 552 and {t["status"] for t in tr} == {"held_exposure_drop"}
        assert sum(1 for t in tr if t["new_K_base"] == "누락") == 379
        drop_file = pathlib.Path(s["exposure_drop_path"])
        assert drop_file.exists()
        assert json.loads(drop_file.read_text(encoding="utf-8"))["status"] == G.STATUS_HOLD
        # K 분포 비교도 이제 실제로 돈다(예전엔 늘 FileNotFoundError → pass).
        # ※ 이 가짜 시트는 기준에 '누락'이 0줄이라 detect_k_anomaly 가 '누락'을 자연 신규값으로
        #   흡수해 False 를 낸다 — 그래서 노출 줄 수 검사가 따로 있어야 한다(실제 18:00 은 True).
        assert s["k_anomaly_compare"] == "비교함" and s["k_anomaly_detected"] is not None

    def test_552에서_540이면_그대로_쓴다(self, monkeypatch, tmp_path):
        s, client, crawler = _run(monkeypatch, tmp_path, 552, 540)
        assert s["exposure_drop_status"] == G.STATUS_PASS
        assert s["exposure_drop_hold"] is False
        assert _written_rows(client) == 552
        assert {t["status"] for t in _trace(tmp_path)} == {"write_ready"}
        assert s["k_anomaly_compare"] == "비교함" and s["k_anomaly_detected"] is False

    def test_기준을_못_읽으면_막지_않고_비교_못_함을_남긴다(self, monkeypatch, tmp_path):
        s, client, crawler = _run(monkeypatch, tmp_path, 552, 173, with_k=False)
        assert s["exposure_drop_status"] == G.STATUS_NO_COMPARE
        assert s["exposure_drop"]["reason"]
        assert _written_rows(client) == 552
        assert s["k_anomaly_compare"] == "비교 못 함"

    def test_사람_스위치를_켜면_그대로_쓴다(self, monkeypatch, tmp_path):
        s, client, crawler = _run(monkeypatch, tmp_path, 552, 173, allow=True)
        assert s["exposure_drop_status"] == G.STATUS_RELEASED
        assert _written_rows(client) == 552
        # 사람이 확인하고 푼 회차는 빨강으로 올리지 않는다
        assert not s.get("code_change_suspected")

    def test_K_값과_검색_횟수는_장치와_상관없이_같다(self, monkeypatch, tmp_path):
        """장치는 세기만 한다 — 멈춘 회차와 푼 회차의 K 값 · 검색 수가 같아야 한다."""
        held_dir = tmp_path / "held"
        held_dir.mkdir()
        s1, _, c1 = _run(monkeypatch, held_dir, 552, 173)
        k_held = {(t["tab"], t["row"]): t["new_K_base"] for t in _trace(held_dir)}
        free_dir = tmp_path / "free"
        free_dir.mkdir()
        s2, _, c2 = _run(monkeypatch, free_dir, 552, 173, allow=True)
        k_free = {(t["tab"], t["row"]): t["new_K_base"] for t in _trace(free_dir)}
        assert k_held == k_free
        assert c1.fetch_search.call_count == c2.fetch_search.call_count == 552


# ── 알림 ──────────────────────────────────────────────────────────────────────
class Test알림:
    def _hold_summary(self):
        tu, rc = _sample(552, 173)
        return {"success_rate": 1.0, "total_rows_processed": 922, "code_change_suspected": False,
                "exposure_drop": G.evaluate(tu, rc), "exposure_drop_hold": True,
                "exposure_drop_path": ".harness/audits/x_exposure-drop.jsonl",
                "k_anomaly_compare": "비교함"}

    def test_텔레그램_한_줄은_멈춤을_말한다(self):
        from scripts.send_telegram_summary import build_brief
        t = build_brief(self._hold_summary(), ts="10/29 18:00", run_status="success")
        assert t.startswith("⏸") and "552→173" in t and "69%" in t and "멈췄" in t
        assert "✅" not in t

    def test_멈춘_회차는_같은_회차_문자_생략을_타지_않는다(self, monkeypatch, tmp_path):
        import scripts.send_telegram_summary as S
        monkeypatch.chdir(tmp_path)
        (tmp_path / "cycle_summary.json").write_text(
            json.dumps(self._hold_summary(), ensure_ascii=False), encoding="utf-8")
        보낸것 = []
        monkeypatch.setattr(S, "send_report", lambda t: 보낸것.append(t) or 0)
        monkeypatch.setattr(S, "이_회차에_이미_보고했나", lambda: True)
        assert S.main() == 0
        assert len(보낸것) == 1 and 보낸것[0].startswith("⏸")

    def test_멈추지_않은_회차는_예전처럼_생략(self, monkeypatch, tmp_path):
        import scripts.send_telegram_summary as S
        monkeypatch.chdir(tmp_path)
        s = self._hold_summary()
        s["exposure_drop_hold"] = False
        (tmp_path / "cycle_summary.json").write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
        보낸것 = []
        monkeypatch.setattr(S, "send_report", lambda t: 보낸것.append(t) or 0)
        monkeypatch.setattr(S, "이_회차에_이미_보고했나", lambda: True)
        assert S.main() == 0
        assert 보낸것 == []

    def test_이슈_댓글에_멈춤과_비교_결과가_남는다(self):
        from scripts.post_summary_to_issue import build_success_comment
        body = build_success_comment(self._hold_summary())
        assert "노출 급감 검사**: 멈춤" in body and "allow_exposure_drop=true" in body
        assert "K 분포 비교**: 비교함" in body

    def test_비교_못_함도_이슈_댓글에_남는다(self):
        from scripts.post_summary_to_issue import build_success_comment
        s = self._hold_summary()
        s["exposure_drop"] = G.evaluate({}, {})
        s["exposure_drop_hold"] = False
        s["k_anomaly_compare"] = "비교 못 함"
        body = build_success_comment(s)
        assert "노출 급감 검사**: 비교 못 함" in body and "K 분포 비교**: 비교 못 함" in body

    def test_워크플로_스위치는_수동_실행에만_있고_기본은_끔(self):
        import yaml
        wf = yaml.load(pathlib.Path(".github/workflows/rank-check.yml").read_text(encoding="utf-8"),
                       Loader=yaml.BaseLoader) if pathlib.Path(".github/workflows/rank-check.yml").exists() else \
            yaml.load((pathlib.Path(__file__).resolve().parents[2] / ".github/workflows/rank-check.yml")
                      .read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        inp = wf["on"]["workflow_dispatch"]["inputs"]["allow_exposure_drop"]
        assert inp["default"] == "false" and inp["options"] == ["false", "true"]
        step = next(s for s in wf["jobs"]["run-cron"]["steps"] if s.get("name") == "Run cron cycle")
        assert step["env"]["EXPOSURE_DROP_ALLOW"] == (
            "${{ github.event_name == 'workflow_dispatch' && inputs.allow_exposure_drop == 'true' }}"
        )


def test_예전_조용한_pass_가_남아있지_않다():
    """앞 회차 cycle_summary.json 을 읽고 FileNotFoundError 를 삼키던 자리가 돌아오면 안 된다."""
    body = (pathlib.Path(__file__).resolve().parents[2] / "src/main.py").read_text(encoding="utf-8")
    assert 'open("cycle_summary.json", "r"' not in body
    assert "pass  # 첫 cron 또는 파일 없음" not in body


def test_K_base_헬퍼는_transitions_와_같다():
    for k in ("AB (10/22 12:00~)", "누락 (10/29 18:00~)", "중복노출(AB)", ""):
        assert G._base(k) == (parse_K_with_stamp(k)[0] or "미노출")
