"""노출 급감 품질 3차 지적 3-1 · 3-2 회귀 검사 (2026-10-30).

3-1 '바로 앞 회차'는 기록이 아니라 실행 순서로 확인한다.
    앞 멈춤 기록의 실행 번호 · 시도 번호 == 워크플로가 찾은 바로 앞 실행일 때만 급감 재확인.
    조회 실패 · 값 없음 · 번호 다름 · 기록 저장 실패 · 캐시에 더 옛 기록만 · 기록 전에 죽은 회차 끼임 → 멈춤 · 쓰기 0.
3-2 '같은 기준'은 정확히 같음 — 기준 노출 줄 수와 맞댄 줄 수가 둘 다 같을 때만.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from src import exposure_drop_guard as G
from src import exposure_prev_run as P
from tests.unit.test_exposure_drop_guard import _run, _sample, _written_rows


def _st(tmp_path) -> pathlib.Path:
    return tmp_path / "state" / "state.json"


def _cyc(monkeypatch, tmp_path, name, n, still, st, run_id, prev_run=None):
    d = tmp_path / name
    d.mkdir()
    s, c, _ = _run(monkeypatch, d, n, still, state_path=st, run_id=run_id, prev_run=prev_run)
    return s, c


# ── 바로 앞 실행 찾기(GitHub API 응답 흉내 — 네트워크 0) ─────────────────────────
def _api(runs, me_no=1382, me_id="40852211707", fail=None):
    def get(url):
        if fail and fail in url:
            raise OSError("조회 실패 흉내")
        if url.endswith(f"/actions/runs/{me_id}"):
            return {"id": int(me_id), "workflow_id": 777, "run_number": me_no}
        if "/actions/workflows/777/runs" in url:
            return {"workflow_runs": runs}
        raise AssertionError(url)
    return get


R = "yoohojong/naver-rank-checker"


class Test바로_앞_실행_찾기:
    def test_번호가_하나_작은_끝난_실행(self):
        runs = [{"id": 40852211707, "run_number": 1382, "status": "in_progress", "run_attempt": 1},
                {"id": 40846265314, "run_number": 1381, "status": "completed", "conclusion": "success", "run_attempt": 1},
                {"id": 40809657614, "run_number": 1380, "status": "completed", "run_attempt": 1}]
        v, why = P.find_previous_run(R, "40852211707", _api(runs))
        assert v == "40846265314:1" and "1381" in why

    def test_다시_돌린_실행은_마지막_시도_번호(self):
        runs = [{"id": 5, "run_number": 1381, "status": "completed", "run_attempt": 2}]
        assert P.find_previous_run(R, "40852211707", _api(runs))[0] == "5:2"

    @pytest.mark.parametrize("fail", ["/actions/runs/40852211707", "/actions/workflows/777/runs"])
    def test_조회_실패는_빈_값(self, fail):
        v, why = P.find_previous_run(R, "40852211707", _api([], fail=fail))
        assert v == "" and "조회 실패" in why

    def test_바로_앞_번호가_목록에_없으면_빈_값(self):
        runs = [{"id": 1, "run_number": 1380, "status": "completed", "run_attempt": 1}]
        v, why = P.find_previous_run(R, "40852211707", _api(runs))
        assert v == "" and "0개" in why

    def test_바로_앞_실행이_안_끝났으면_빈_값(self):
        runs = [{"id": 1, "run_number": 1381, "status": "in_progress", "run_attempt": 1}]
        assert P.find_previous_run(R, "40852211707", _api(runs))[0] == ""

    @pytest.mark.parametrize("repo,rid", [("", "1"), ("a/b", ""), ("a/b", "local"), ("../x", "1")])
    def test_입력이_이상하면_빈_값(self, repo, rid):
        assert P.find_previous_run(repo, rid, _api([]))[0] == ""

    @pytest.mark.parametrize("v", ["", "abc", "1:0", "1:x", "1:2:3", ":1", None])
    def test_값_모양이_다르면_확인_못_함(self, v):
        assert P.parse_prev(v) is None

    def test_find_는_열쇠_없으면_빈_값을_남긴다(self, monkeypatch, tmp_path):
        env = tmp_path / "env"
        for k in ("GH_TOKEN", "GITHUB_TOKEN"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("GITHUB_ENV", str(env))
        assert P.main(["find"]) == 0
        text = env.read_text(encoding="utf-8")
        assert f"{P.ENV_PREV_RUN}=\n" in text and "열쇠 없음" in text

    def test_own_은_이번_실행_이번_시도_기록만_true(self, monkeypatch, tmp_path):
        st = _st(tmp_path)
        G.save_state(str(st), {"status": G.STATUS_HOLD}, "77", run_attempt=2)
        out = tmp_path / "out"
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        for rid, att, want in (("77", "2", "true"), ("77", "1", "false"), ("78", "2", "false")):
            monkeypatch.setenv("GITHUB_RUN_ID", rid)
            monkeypatch.setenv("GITHUB_RUN_ATTEMPT", att)
            out.write_text("", encoding="utf-8")
            P.main(["own", str(st)])
            assert out.read_text(encoding="utf-8").strip() == f"own={want}"
        monkeypatch.setenv("GITHUB_RUN_ID", "77")
        assert P.is_own_record(str(tmp_path / "없음.json"), "77", "2") is False


# ── 지적 3-1: 판정(순수 함수) ────────────────────────────────────────────────────
class Test실행_순서_판정:
    def _hold(self, tmp_path, run_id="100", attempt=1):
        st = _st(tmp_path)
        tu, rc = _sample(100, 50)
        G.save_state(str(st), G.evaluate(tu, rc), run_id, run_attempt=attempt)
        return st

    def test_바로_앞_실행과_같으면_재확인(self, tmp_path):
        st = self._hold(tmp_path)
        prev = G.load_prev_state(str(st), run_id="101", prev_run="100:1")
        tu, rc = _sample(100, 50)
        assert prev["state"] == G.PREV_HOLD and G.evaluate(tu, rc, prev=prev)["status"] == G.STATUS_RECONFIRMED

    @pytest.mark.parametrize("prev_run,why", [
        ("", "확인 못 함"), (None, "확인 못 함"), ("99:1", "것이 아님"), ("100:2", "것이 아님"),
    ])
    def test_확인_못_하거나_다르면_멈춤(self, tmp_path, prev_run, why):
        st = self._hold(tmp_path)
        prev = G.load_prev_state(str(st), run_id="102", prev_run=prev_run, prev_run_why="앞 실행 조회 실패(OSError)")
        tu, rc = _sample(100, 50)
        r = G.evaluate(tu, rc, prev=prev)
        assert prev["state"] == G.PREV_NOT_ADJACENT and r["status"] == G.STATUS_HOLD and why in r["reason"]

    def test_1판_기록은_못_읽음(self, tmp_path):
        st = _st(tmp_path)
        st.parent.mkdir(parents=True)
        st.write_text(json.dumps({"version": 1, "run_id": "100", "saved_at": "2026-10-30T00:00:00+00:00",
                                  "status": G.STATUS_HOLD, "drop_ratio": 0.5, "baseline_exposed": 100,
                                  "current_exposed": 50, "rows_compared": 100, "rows_unreadable": 0}),
                      encoding="utf-8")
        assert G.load_prev_state(str(st), run_id="101", prev_run="100:1")["state"] == G.PREV_UNREADABLE

    def test_저장_실패면_남은_옛_기록을_지운다(self, tmp_path):
        st = self._hold(tmp_path)
        (pathlib.Path(str(st) + ".tmp")).mkdir()          # 품질3차와 같은 장애: .tmp 자리에 폴더
        tu, rc = _sample(100, 100)
        with pytest.raises(OSError):
            G.save_state(str(st), G.evaluate(tu, rc), "101")
        assert not st.exists()


# ── 지적 3-2: 같은 기준 = 정확히 같음 ────────────────────────────────────────────
class Test같은_기준_정확히:
    def _prev(self, tmp_path, base, cur, compared):
        st = _st(tmp_path)
        st.parent.mkdir(parents=True, exist_ok=True)
        st.write_text(json.dumps({"version": G.STATE_VERSION, "run_id": "100", "run_attempt": 1,
                                  "saved_at": G._now_utc().isoformat(), "status": G.STATUS_HOLD,
                                  "drop_ratio": 0.5, "baseline_exposed": base, "current_exposed": cur,
                                  "rows_compared": compared, "rows_unreadable": 0}), encoding="utf-8")
        return G.load_prev_state(str(st), run_id="101", prev_run="100:1")

    def test_기준_노출이_하나라도_다르면_멈춤(self, tmp_path):
        prev = self._prev(tmp_path, 100, 50, 100)
        tu, rc = _sample(99, 40)
        r = G.evaluate(tu, rc, prev=prev)
        assert r["rows_compared"] == 99 and r["status"] == G.STATUS_HOLD and "기준이 다름" in r["reason"]

    def test_맞댄_줄_수만_달라도_멈춤(self, tmp_path):
        prev = self._prev(tmp_path, 100, 50, 120)          # 키워드가 20줄 줄었거나 늘었음
        tu, rc = _sample(100, 50)
        r = G.evaluate(tu, rc, prev=prev)
        assert r["baseline_exposed"] == 100 and r["status"] == G.STATUS_HOLD

    def test_품질3차_50에서_100으로_바뀐_기준은_멈춤(self, tmp_path):
        prev = self._prev(tmp_path, 50, 0, 50)
        tu, rc = _sample(100, 50)
        r = G.evaluate(tu, rc, prev=prev)
        assert r["status"] == G.STATUS_HOLD and "50→100" in r["reason"]

    def test_정말_같은_기준이면_재확인(self, tmp_path):
        prev = self._prev(tmp_path, 100, 50, 100)
        tu, rc = _sample(100, 30)
        assert G.evaluate(tu, rc, prev=prev)["status"] == G.STATUS_RECONFIRMED


# ── run_cycle 여러 회차(가짜 시트 · 가짜 검색) ──────────────────────────────────
class Test회차_잇기:
    def test_멈춤_회복_저장실패_새급감은_멈춤(self, monkeypatch, tmp_path):
        """품질3차 fs-A/B/C — B 저장 실패로 A 기록이 남아도 C 는 재확인하지 않는다."""
        st = _st(tmp_path)
        sa, ca = _cyc(monkeypatch, tmp_path, "A", 100, 50, st, "11")
        assert sa["exposure_drop_status"] == G.STATUS_HOLD and _written_rows(ca) == 0
        blocker = pathlib.Path(str(st) + ".tmp")
        blocker.mkdir()
        sb, cb = _cyc(monkeypatch, tmp_path, "B", 100, 100, st, "12", prev_run="11:1")
        assert sb["exposure_drop_status"] == G.STATUS_PASS and _written_rows(cb) == 100
        assert sb["exposure_drop_state_saved"] is False and not st.exists()
        blocker.rmdir()
        sc, cc = _cyc(monkeypatch, tmp_path, "C", 100, 50, st, "13", prev_run="12:1")
        assert sc["exposure_drop_status"] == G.STATUS_HOLD and _written_rows(cc) == 0

    def test_옛_기록이_남아도_실행_순서가_막는다(self, monkeypatch, tmp_path):
        """기록 전에 죽은 회차 · 캐시 저장 실패로 더 옛 멈춤 기록만 복원된 경우."""
        st = _st(tmp_path)
        _cyc(monkeypatch, tmp_path, "A", 100, 50, st, "21")
        # 22 는 기록 전에 죽음(기록 없음) — 23 은 21 기록을 받지만 바로 앞 실행은 22
        sc, cc = _cyc(monkeypatch, tmp_path, "C", 100, 50, st, "23", prev_run="22:1")
        assert sc["exposure_drop_status"] == G.STATUS_HOLD and _written_rows(cc) == 0
        assert "것이 아님" in sc["exposure_drop"]["reason"]

    def test_앞_실행_조회_실패면_멈춤(self, monkeypatch, tmp_path):
        st = _st(tmp_path)
        _cyc(monkeypatch, tmp_path, "A", 100, 50, st, "31")
        s, c = _cyc(monkeypatch, tmp_path, "B", 100, 50, st, "32", prev_run="")
        assert s["exposure_drop_status"] == G.STATUS_HOLD and _written_rows(c) == 0

    def test_기준_50에서_0_멈춤_뒤_100에서_50은_멈춤(self, monkeypatch, tmp_path):
        st = _st(tmp_path)
        sa, _ = _cyc(monkeypatch, tmp_path, "A", 50, 0, st, "41")
        assert sa["exposure_drop_status"] == G.STATUS_HOLD
        sb, cb = _cyc(monkeypatch, tmp_path, "B", 100, 50, st, "42", prev_run="41:1")
        assert sb["exposure_drop_status"] == G.STATUS_HOLD and _written_rows(cb) == 0

    def test_정말_같은_기준_두_번_급감은_재확인으로_전부_쓴다(self, monkeypatch, tmp_path):
        st = _st(tmp_path)
        _cyc(monkeypatch, tmp_path, "A", 100, 50, st, "51")
        sb, cb = _cyc(monkeypatch, tmp_path, "B", 100, 50, st, "52", prev_run="51:1")
        assert sb["exposure_drop_status"] == G.STATUS_RECONFIRMED and _written_rows(cb) == 100


class Test워크플로_앞실행_단계:
    def _steps(self):
        import yaml
        p = pathlib.Path(__file__).resolve().parents[2] / ".github/workflows/rank-check.yml"
        wf = yaml.load(p.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        return wf, wf["jobs"]["run-cron"]["steps"]

    def test_앞실행_찾기는_실행_전_기록_보관은_이번_실행_것만(self):
        wf, steps = self._steps()
        names = [s.get("name") for s in steps]
        i_find = names.index("Find previous run (노출 급감 바로 앞 실행)")
        i_run = names.index("Run cron cycle")
        i_own = names.index("Check own exposure-drop state (이번 실행 기록인가)")
        i_save = names.index("Save exposure-drop state (다음 회차용)")
        assert i_find < i_run < i_own < i_save
        assert "src.exposure_prev_run find" in steps[i_find]["run"]
        assert steps[i_find]["env"]["GH_TOKEN"] == "${{ github.token }}"
        assert "src.exposure_prev_run own" in steps[i_own]["run"]
        assert "steps.exposure_state_own.outputs.own == 'true'" in steps[i_save]["if"]
        assert "hashFiles" not in steps[i_save]["if"]
        assert wf["permissions"]["actions"] == "read"
