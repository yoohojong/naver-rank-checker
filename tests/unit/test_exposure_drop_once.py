"""노출 급감 '멈춤은 한 회차만'(2026-10-30 정책 A) + 품질 2차 지적 2-1(쓰기 여부 문구) 회귀 검사.

정책 A (마에스트로 · 사장님 확인 '실제 급감에도 시트를 멈춰 세움이 되지 않게')
  - 바로 앞 회차 멈춤 + 이번도 같은 기준에서 20% 넘게 감소 → '급감 재확인' · 쓰기 전부 · 알림 한 줄
  - 바로 앞 회차 멈춤 + 이번은 20% 이하                  → 통과(한 번 튄 것)
  - 기록 못 읽음 · 없음 · 24시간 지남 · 같은 실행 것        → 지금처럼 멈춤(안전 쪽)
  - 기록에는 키워드 · 링크 · 카페 · 탭 이름 없음(숫자만)
지적 2-1: 일부 미확인 + (멈춤 / 급감 없음 / 사람 해제 / 급감 재확인) 네 갈래의 이슈 · 텔레그램 문구가
          실제 쓰기 여부와 맞는다. 멈춘 회차엔 '쓰기는 막지 않음'이 없다.
"""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from src import exposure_drop_guard as G
from tests.unit.test_exposure_drop_guard import TAB, _fake_sheet, _run, _sample, _written_rows

NOW = datetime(2026, 10, 30, 9, 46, tzinfo=timezone.utc)


def _state(tmp_path) -> pathlib.Path:
    return tmp_path / "state" / "state.json"


def _hold_record(path: pathlib.Path, *, baseline=552, current=173, run_id="r1800", saved=None, status=G.STATUS_HOLD):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "version": G.STATE_VERSION, "run_id": run_id,
        "saved_at": (saved or (NOW - timedelta(minutes=46))).isoformat(),
        "status": status, "drop_ratio": round((baseline - current) / baseline, 4) if baseline else None,
        "baseline_exposed": baseline, "current_exposed": current,
        "rows_compared": baseline, "rows_unreadable": 0,
    }), encoding="utf-8")


# ── 판정(순수 함수) ──────────────────────────────────────────────────────────────
class Test앞회차_기록_판정:
    def _eval(self, tmp_path, total, still, **rec):
        p = _state(tmp_path)
        if rec.pop("write", True):
            _hold_record(p, **rec)
        prev = G.load_prev_state(str(p), run_id="r1846", now=NOW)
        tu, rc = _sample(total, still)
        return G.evaluate(tu, rc, prev=prev), prev

    def test_앞_멈춤_뒤_같은_급감이면_급감_재확인(self, tmp_path):
        r, prev = self._eval(tmp_path, 552, 173)
        assert prev["state"] == G.PREV_HOLD
        assert r["status"] == G.STATUS_RECONFIRMED and not G.is_hold(r)
        assert G.RECONFIRM_NOTE in r["reason"]

    def test_앞_멈춤_뒤_회복이면_통과(self, tmp_path):
        r, _ = self._eval(tmp_path, 552, 540)
        assert r["status"] == G.STATUS_PASS

    def test_기록_없으면_멈춤(self, tmp_path):
        r, prev = self._eval(tmp_path, 552, 173, write=False)
        assert prev["state"] == G.PREV_NONE and r["status"] == G.STATUS_HOLD

    @pytest.mark.parametrize("body", ["{깨짐", "[]", '{"version": 1}', '{"version": 99}', ""])
    def test_기록을_못_읽으면_멈춤(self, tmp_path, body):
        p = _state(tmp_path)
        p.parent.mkdir(parents=True)
        p.write_text(body, encoding="utf-8")
        prev = G.load_prev_state(str(p), run_id="r1846", now=NOW)
        tu, rc = _sample(552, 173)
        r = G.evaluate(tu, rc, prev=prev)
        assert prev["state"] == G.PREV_UNREADABLE and r["status"] == G.STATUS_HOLD
        assert "못 읽음" in r["reason"]

    def test_기록이_폴더라_열_수_없어도_멈춤(self, tmp_path):
        p = _state(tmp_path)
        p.mkdir(parents=True)          # 파일 자리에 폴더 → open 실패
        prev = G.load_prev_state(str(p), now=NOW)
        tu, rc = _sample(552, 173)
        assert prev["state"] == G.PREV_UNREADABLE and G.evaluate(tu, rc, prev=prev)["status"] == G.STATUS_HOLD

    def test_24시간_지난_기록은_무효라_멈춤(self, tmp_path):
        r, prev = self._eval(tmp_path, 552, 173, saved=NOW - timedelta(hours=24, minutes=1))
        assert prev["state"] == G.PREV_EXPIRED and r["status"] == G.STATUS_HOLD

    def test_24시간_안이면_유효(self, tmp_path):
        r, prev = self._eval(tmp_path, 552, 173, saved=NOW - timedelta(hours=23, minutes=59))
        assert prev["state"] == G.PREV_HOLD and r["status"] == G.STATUS_RECONFIRMED

    def test_시각이_미래인_기록은_못_읽음(self, tmp_path):
        r, prev = self._eval(tmp_path, 552, 173, saved=NOW + timedelta(hours=1))
        assert prev["state"] == G.PREV_UNREADABLE and r["status"] == G.STATUS_HOLD

    def test_이번_실행이_남긴_기록은_앞_회차가_아니다(self, tmp_path):
        """같은 실행을 다시 돌림(rerun) — 자기 기록으로 스스로 풀지 않는다."""
        r, prev = self._eval(tmp_path, 552, 173, run_id="r1846")
        assert prev["state"] == G.PREV_UNREADABLE and r["status"] == G.STATUS_HOLD

    def test_앞_회차가_멈춤이_아니면_첫_멈춤(self, tmp_path):
        r, prev = self._eval(tmp_path, 552, 173, status=G.STATUS_PASS)
        assert prev["state"] == G.PREV_NOT_HOLD and r["status"] == G.STATUS_HOLD

    def test_그새_기준이_바뀌었으면_새_급감으로_멈춤(self, tmp_path):
        """앞 회차 멈춤(552→173) 뒤 누가 시트를 173 쪽으로 써 놨고, 이번에 거기서 또 급감 → 다른 급감."""
        r, _ = self._eval(tmp_path, 180, 20)
        assert r["status"] == G.STATUS_HOLD and "그새 기준이" in r["reason"]

    def test_기록_꺼짐이면_예전처럼_멈춤(self):
        tu, rc = _sample(552, 173)
        assert G.evaluate(tu, rc)["status"] == G.STATUS_HOLD
        assert G.evaluate(tu, rc, prev=G.load_prev_state(None))["status"] == G.STATUS_HOLD

    def test_사람_스위치가_먼저(self, tmp_path):
        p = _state(tmp_path)
        _hold_record(p)
        tu, rc = _sample(552, 173)
        r = G.evaluate(tu, rc, allow=True, prev=G.load_prev_state(str(p), now=NOW))
        assert r["status"] == G.STATUS_RELEASED

    def test_장치_고장은_여전히_비교_못_함(self, tmp_path):
        p = _state(tmp_path)
        _hold_record(p)
        r = G.evaluate({TAB: [object()]}, {}, prev=G.load_prev_state(str(p), now=NOW))
        assert r["status"] == G.STATUS_NO_COMPARE and "계산 오류" in r["reason"]


class Test기록에_숫자만:
    def test_저장_내용은_숫자_칸만(self, tmp_path):
        tu, rc = _sample(552, 173)
        r = G.evaluate(tu, rc)
        assert r["lost_examples"] and r["lost_examples"][0]["keyword"]   # 판정 dict 엔 키워드가 있다
        p = _state(tmp_path)
        assert G.save_state(str(p), r, "40846265314", now=NOW) is True
        rec = json.loads(p.read_text(encoding="utf-8"))
        assert set(rec) == {"version", "run_id", "saved_at", "status", "drop_ratio",
                            "baseline_exposed", "current_exposed", "rows_compared", "rows_unreadable"}
        text = p.read_text(encoding="utf-8")
        for bad in ("kw", "cafe", "http", TAB, "키워드", "링크"):
            assert bad not in text
        # 다음 회차가 그대로 읽는다
        prev = G.load_prev_state(str(p), run_id="40852211707", now=NOW + timedelta(minutes=46))
        assert prev["state"] == G.PREV_HOLD and prev["record"]["baseline_exposed"] == 552

    def test_실행_번호_모양이_이상하면_unknown(self, tmp_path):
        p = _state(tmp_path)
        G.save_state(str(p), {"status": G.STATUS_HOLD}, "../../etc/x", now=NOW)
        assert json.loads(p.read_text(encoding="utf-8"))["run_id"] == "unknown"

    def test_경로_없으면_안_씀(self):
        assert G.save_state(None, {"status": G.STATUS_HOLD}, "1") is False


# ── run_cycle 두 회차 (가짜 시트 · 가짜 검색) ────────────────────────────────────
class Test두_회차_배선:
    def test_멈춤_다음_회차_같은_급감이면_급감_재확인으로_전부_쓴다(self, monkeypatch, tmp_path):
        st = _state(tmp_path)
        d1, d2 = tmp_path / "c1", tmp_path / "c2"
        d1.mkdir(), d2.mkdir()
        s1, c1, _ = _run(monkeypatch, d1, 552, 173, state_path=st, run_id="1001")
        assert s1["exposure_drop_status"] == G.STATUS_HOLD and _written_rows(c1) == 0
        c1.write_type_results.assert_not_called()
        assert s1["exposure_drop_state_saved"] is True
        # 멈춘 회차는 시트를 안 바꿨다 → 다음 회차도 같은 시트를 읽는다
        s2, c2, _ = _run(monkeypatch, d2, 552, 173, state_path=st, run_id="1002")
        assert s2["exposure_drop_status"] == G.STATUS_RECONFIRMED
        assert s2["exposure_drop_hold"] is False
        assert _written_rows(c2) == 552          # 가짜 시트가 셀 수 0 을 돌려줘 total_cells 는 못 씀 — 쓴 줄 수로 본다
        assert not s2.get("code_change_suspected")
        assert G.RECONFIRM_NOTE in s2["exposure_drop"]["reason"]
        # 세 번째 회차는 앞 회차가 '급감 재확인'(멈춤 아님) → 또 급감이면 새 급감으로 한 번 멈춘다
        d3 = tmp_path / "c3"
        d3.mkdir()
        s3, c3, _ = _run(monkeypatch, d3, 173, 20, state_path=st, run_id="1003")
        assert s3["exposure_drop_status"] == G.STATUS_HOLD and _written_rows(c3) == 0

    def test_멈춤_다음_회차_회복이면_통과(self, monkeypatch, tmp_path):
        st = _state(tmp_path)
        d1, d2 = tmp_path / "c1", tmp_path / "c2"
        d1.mkdir(), d2.mkdir()
        s1, _, _ = _run(monkeypatch, d1, 552, 173, state_path=st, run_id="2001")
        assert s1["exposure_drop_status"] == G.STATUS_HOLD
        s2, c2, _ = _run(monkeypatch, d2, 552, 540, state_path=st, run_id="2002")
        assert s2["exposure_drop_status"] == G.STATUS_PASS and _written_rows(c2) == 552

    def test_기록을_못_읽으면_다음_회차도_멈춤(self, monkeypatch, tmp_path):
        st = _state(tmp_path)
        d1, d2 = tmp_path / "c1", tmp_path / "c2"
        d1.mkdir(), d2.mkdir()
        _run(monkeypatch, d1, 552, 173, state_path=st, run_id="3001")
        st.write_text("{깨진 기록", encoding="utf-8")
        s2, c2, _ = _run(monkeypatch, d2, 552, 173, state_path=st, run_id="3002")
        assert s2["exposure_drop_status"] == G.STATUS_HOLD and _written_rows(c2) == 0
        assert "못 읽음" in s2["exposure_drop"]["reason"]

    def test_기록_경로가_없으면_예전처럼_두_번_다_멈춤(self, monkeypatch, tmp_path):
        d1, d2 = tmp_path / "c1", tmp_path / "c2"
        d1.mkdir(), d2.mkdir()
        s1, _, _ = _run(monkeypatch, d1, 552, 173, run_id="4001")
        s2, c2, _ = _run(monkeypatch, d2, 552, 173, run_id="4002")
        assert s1["exposure_drop_status"] == s2["exposure_drop_status"] == G.STATUS_HOLD
        assert s2["exposure_drop_state_saved"] is None and _written_rows(c2) == 0

    def test_기록_저장_실패는_알림에_드러난다(self, monkeypatch, tmp_path):
        st = tmp_path / "state_is_file"
        st.write_text("x", encoding="utf-8")
        bad = st / "state.json"           # 부모가 파일 → 저장 실패
        s, c, _ = _run(monkeypatch, tmp_path, 552, 540, state_path=bad, run_id="5001")
        assert s["exposure_drop_state_saved"] is False and _written_rows(c) == 552
        from scripts.send_telegram_summary import build_brief
        from scripts.post_summary_to_issue import build_success_comment
        assert "기록 저장 실패" in build_brief(s, ts="10/30 06:00", run_status="success")
        assert "기록 저장 실패" in build_success_comment(s)


# ── 지적 2-1: 일부 미확인 네 갈래 문구 = 실제 쓰기 여부 ─────────────────────────
def _partial_two_cycles(monkeypatch, tmp_path, *, allow=False, reconfirm=False, still=0):
    """100줄 중 50줄만 기준(AB) · 나머지 50줄 기준 못 읽음. 읽은 50줄 중 still 줄만 이번에도 노출."""
    st = _state(tmp_path)
    if reconfirm:
        d0 = tmp_path / "c0"
        d0.mkdir()
        s0, _, _ = _run(monkeypatch, d0, 100, still, missing=50, state_path=st, run_id="9000")
        assert s0["exposure_drop_status"] == G.STATUS_HOLD
    d = tmp_path / "c1"
    d.mkdir()
    return _run(monkeypatch, d, 100, still, missing=50, allow=allow, state_path=st, run_id="9001")


class Test일부_미확인_네_갈래:
    def _texts(self, s):
        from scripts.send_telegram_summary import build_brief
        from scripts.post_summary_to_issue import build_success_comment
        return build_brief(s, ts="10/30 06:00", run_status="success"), build_success_comment(s)

    def test_일부_미확인_더하기_멈춤(self, monkeypatch, tmp_path):
        s, c, _ = _partial_two_cycles(monkeypatch, tmp_path, still=0)
        assert s["exposure_drop_status"] == G.STATUS_HOLD and _written_rows(c) == 0
        tg, issue = self._texts(s)
        assert "쓰기는 막지 않음" not in issue and "쓰기는 막지 않음" not in tg
        assert "그대로 씀" not in issue.split("**K 분포 비교**")[0]
        assert "이번 회차 시트 쓰기 멈춤" in issue and "위 급감으로 멈춤" in issue
        assert tg.startswith("⏸") and "다음 회차에도 같으면" in tg

    def test_일부_미확인_더하기_급감_없음(self, monkeypatch, tmp_path):
        s, c, _ = _partial_two_cycles(monkeypatch, tmp_path, still=50)
        assert s["exposure_drop_status"] == G.STATUS_PARTIAL and _written_rows(c) == 100
        tg, issue = self._texts(s)
        assert "쓰기 멈춤" not in issue and "막지는 않음 — 이번 회차 그대로 씀" in issue
        assert not tg.startswith("⏸")

    def test_일부_미확인_더하기_사람_해제(self, monkeypatch, tmp_path):
        s, c, _ = _partial_two_cycles(monkeypatch, tmp_path, still=0, allow=True)
        assert s["exposure_drop_status"] == G.STATUS_RELEASED and _written_rows(c) == 100
        tg, issue = self._texts(s)
        assert "쓰기 멈춤" not in issue and "사람 스위치로 이번 회차 그대로 씀" in issue
        assert not tg.startswith("⏸")

    def test_일부_미확인_더하기_급감_재확인(self, monkeypatch, tmp_path):
        s, c, _ = _partial_two_cycles(monkeypatch, tmp_path, still=0, reconfirm=True)
        assert s["exposure_drop_status"] == G.STATUS_RECONFIRMED and _written_rows(c) == 100
        tg, issue = self._texts(s)
        assert "쓰기 멈춤" not in issue and G.RECONFIRM_NOTE in issue
        assert G.RECONFIRM_NOTE in tg and not tg.startswith("⏸")

    def test_기준_전부_못_읽음은_쓰기_막지_않음_그대로(self, monkeypatch, tmp_path):
        s, c, _ = _run(monkeypatch, tmp_path, 100, 0, with_k=False)
        assert s["exposure_drop_status"] == G.STATUS_NO_COMPARE and _written_rows(c) == 100
        tg, _ = self._texts(s)
        assert "(쓰기는 막지 않음)" in tg

    def test_문구_어디에도_멈춤과_안막음이_같이_나오지_않는다(self):
        """상태별로 쓰기 여부 한 문장이 하나만 정해진다."""
        held = G.write_decision_text({"status": G.STATUS_HOLD})
        assert "멈춤" in held and "막지" not in held and "씀" not in held
        for st in (G.STATUS_PARTIAL, G.STATUS_RELEASED, G.STATUS_RECONFIRMED, G.STATUS_PASS):
            assert "멈춤" not in G.write_decision_text({"status": st})


class Test텔레그램_급감_재확인:
    def test_급감_재확인은_같은_회차_문자_생략을_타지_않는다(self, monkeypatch, tmp_path):
        import scripts.send_telegram_summary as S
        monkeypatch.chdir(tmp_path)
        tu, rc = _sample(552, 173)
        p = _state(tmp_path)
        _hold_record(p)
        d = G.evaluate(tu, rc, prev=G.load_prev_state(str(p), now=NOW))
        s = {"success_rate": 1.0, "total_rows_processed": 552, "code_change_suspected": False,
             "exposure_drop": d, "exposure_drop_status": d["status"], "exposure_drop_hold": False}
        (tmp_path / "cycle_summary.json").write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
        보낸것 = []
        monkeypatch.setattr(S, "send_report", lambda t: 보낸것.append(t) or 0)
        monkeypatch.setattr(S, "이_회차에_이미_보고했나", lambda: True)
        assert S.main() == 0
        assert len(보낸것) == 1 and G.RECONFIRM_NOTE in 보낸것[0] and 보낸것[0].startswith("✅")


class Test워크플로_캐시:
    def _wf(self):
        import yaml
        p = pathlib.Path(__file__).resolve().parents[2] / ".github/workflows/rank-check.yml"
        return yaml.load(p.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    def test_복원_실행_저장_순서와_같은_경로(self):
        steps = self._wf()["jobs"]["run-cron"]["steps"]
        names = [s.get("name") for s in steps]
        i_restore = names.index("Restore exposure-drop state (앞 회차 기록)")
        i_run = names.index("Run cron cycle")
        i_save = names.index("Save exposure-drop state (다음 회차용)")
        assert i_restore < i_run < i_save
        restore, run, save = steps[i_restore], steps[i_run], steps[i_save]
        path = run["env"]["EXPOSURE_DROP_STATE_PATH"]
        assert restore["with"]["path"] == save["with"]["path"] == path
        assert restore["uses"].startswith("actions/cache/restore@") and save["uses"].startswith("actions/cache/save@")
        assert restore["continue-on-error"] == "true" and save["continue-on-error"] == "true"
        assert "always()" in save["if"]
        assert restore["with"]["restore-keys"].strip() == "exposure-drop-state-"

    def test_기록_폴더는_git_에_안_담는다(self):
        gi = (pathlib.Path(__file__).resolve().parents[2] / ".gitignore").read_text(encoding="utf-8")
        assert ".harness/exposure-drop-state/" in gi
