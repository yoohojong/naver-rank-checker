"""send_telegram_summary.build_brief 단위 테스트.

핵심 검증(2026-07-20): code_change_suspected 시 알림이 원인을 구분한다 —
  · 일시 차단(circuit_breaker)  → '자동 재시도'(사람 점검 불필요)
  · 구조 신호(대량변경/무결성/성공률급락/K분포) → '파서 점검 필요'
네트워크 0 — build_brief 에 summary dict 를 직접 주입한다.
"""

from scripts.send_telegram_summary import build_brief

TS = "7/20 15:07"


def _brief(summary: dict) -> str:
    return build_brief(summary=summary, ts=TS)


# ---------------------------------------------------------------------------
# 정상
# ---------------------------------------------------------------------------
class TestSuccess:
    def test_clean_success(self):
        msg = _brief({"success_rate": 1.0, "total_rows_processed": 400})
        assert msg.startswith("✅")
        assert "성공률 100%" in msg
        assert "점검 필요" not in msg

    def test_success_with_transient_block_note(self):
        msg = _brief(
            {"success_rate": 0.95, "total_rows_processed": 400, "circuit_breaker_blocks": 3}
        )
        assert msg.startswith("✅")
        assert "차단 3회" in msg


# ---------------------------------------------------------------------------
# 일시 차단(회로차단) — '자동 재시도', '점검 필요' 아님  ← 이번 수정의 핵심
# ---------------------------------------------------------------------------
class TestTransientBlock:
    def test_circuit_breaker_is_transient_not_inspection(self):
        msg = _brief(
            {
                "success_rate": 0.0,
                "code_change_suspected": True,
                "circuit_breaker_tripped": True,
                "circuit_breaker_blocks": 5,
            }
        )
        assert "자동 재시도" in msg
        assert "점검 필요" not in msg  # 헛알람 방지 = 이번 수정의 목적
        assert "파서" not in msg

    def test_circuit_breaker_shows_block_count(self):
        msg = _brief(
            {
                "success_rate": 0.1,
                "code_change_suspected": True,
                "circuit_breaker_tripped": True,
                "circuit_breaker_blocks": 5,
            }
        )
        assert "5회" in msg


# ---------------------------------------------------------------------------
# 구조변경 — '파서 점검 필요'
# ---------------------------------------------------------------------------
class TestStructuralChange:
    def test_bulk_guard_is_structural(self):
        msg = _brief(
            {
                "success_rate": 0.8,
                "code_change_suspected": True,
                "circuit_breaker_tripped": False,
                "type_preview_write_blocked_by_bulk_guard": True,
            }
        )
        assert msg.startswith("🔴")
        assert "파서 점검 필요" in msg
        assert "대량변경 가드" in msg

    def test_low_success_without_block_is_structural(self):
        msg = _brief(
            {
                "success_rate": 0.1,
                "code_change_suspected": True,
                "circuit_breaker_tripped": False,
            }
        )
        assert "파서 점검 필요" in msg
        assert "성공률 급락" in msg

    def test_invariant_violation_is_structural(self):
        msg = _brief(
            {
                "success_rate": 0.85,
                "code_change_suspected": True,
                "circuit_breaker_tripped": False,
                "post_write_audit_violations": 2,
            }
        )
        assert "파서 점검 필요" in msg
        assert "데이터 무결성" in msg

    def test_k_anomaly_only_is_structural(self):
        """성공률 정상이어도 K분포 급변만으로 code_change → 구조 점검."""
        msg = _brief(
            {
                "success_rate": 0.95,
                "code_change_suspected": True,
                "circuit_breaker_tripped": False,
            }
        )
        assert "파서 점검 필요" in msg


# ---------------------------------------------------------------------------
# 부분 실패(코드변경 아님) + 파일 폴백
# ---------------------------------------------------------------------------
class TestPartialAndFallback:
    def test_partial_fail_no_code_change(self):
        msg = _brief({"success_rate": 0.7, "code_change_suspected": False})
        assert "일부 실패" in msg
        assert "점검 필요" not in msg

    def test_missing_file_fallback(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)  # cycle_summary.json 없음
        monkeypatch.delenv("RUN_STATUS", raising=False)
        msg = build_brief(ts=TS)
        assert "시작조차 못 했습니다" in msg


class Test결과기록이_없을_때_무슨_일이었나:
    """★2026-09-03. 여기가 그 구멍이었다.

    cycle_summary.json 은 사이클 **맨 끝**에서야 쓰인다(src/main.py). 그래서
    70분을 돌며 시트까지 다 고치고 마지막에 죽어도 사장님은 "시작 전 중단" 을 받았다
    — 무슨 일이 있었는지 정반대로 알려준 셈이다.
    워크플로는 답을 이미 넘겨주고 있었다(rank-check.yml 의 RUN_STATUS). 안 읽었을 뿐이다.

    사장님 지시(2026-09-03): "실행 자체를 안한거면 그게 진짜 실패."
    """

    def _없음(self, monkeypatch, tmp_path, run_status):
        monkeypatch.chdir(tmp_path)
        return build_brief(ts=TS, run_status=run_status)

    def test_돌다가_죽으면_그렇게_말한다(self, monkeypatch, tmp_path):
        msg = self._없음(monkeypatch, tmp_path, "failure")
        assert "돌다가 중간에 멈췄습니다" in msg
        assert "시작조차" not in msg, "돌다가 죽은 것을 '시작 못 함'으로 말했다"

    def test_시작을_못_하면_그렇게_말한다(self, monkeypatch, tmp_path):
        """스텝이 아예 안 돌면 outcome 이 빈 문자열로 온다(준비 단계에서 멈춤)."""
        assert "시작조차 못 했습니다" in self._없음(monkeypatch, tmp_path, "")

    def test_성공인데_기록이_없으면_조용히_넘기지_않는다(self, monkeypatch, tmp_path):
        assert "확인이 필요해요" in self._없음(monkeypatch, tmp_path, "success")

    def test_환경변수를_직접_읽는다(self, monkeypatch, tmp_path):
        """★배선 검사. 인자로만 되고 env 를 안 읽으면 라이브에선 그대로 옛 문구가 나간다."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("RUN_STATUS", "failure")
        assert "돌다가 중간에 멈췄습니다" in build_brief(ts=TS)

    def test_워크플로가_RUN_STATUS_를_넘긴다(self):
        """★배선이 끊기면 스크립트가 아무리 잘 읽어도 소용없다."""
        import pathlib

        import yaml
        WF = (pathlib.Path(__file__).resolve().parents[2]
              / ".github/workflows/rank-check.yml")
        d = yaml.safe_load(WF.read_text(encoding="utf-8"))
        (잡,) = d["jobs"].values()
        스텝 = [s for s in 잡["steps"]
               if "send_telegram_summary.py" in str(s.get("run", ""))]
        assert 스텝, "즉시 보고 스텝이 사라졌다"
        env = 스텝[0]["env"]
        assert "steps.run_cycle.outcome" in str(env.get("RUN_STATUS", "")), \
            "RUN_STATUS 배선이 끊겼다 — '돌다가 죽음'과 '시작 못 함'을 못 가른다"


class Test같은_회차에_문자를_두_번_보내지_않는다:
    """★하루 8통의 정체(2026-09-03).

    예약이 :07·:27 두 번 걸려 있고 concurrency 가 뒤엣것을 지우지 않아서
    (cancel-in-progress: false), 앞 실행이 성공해도 뒤 실행이 똑같은 사이클을
    한 번 더 돌고 자기 문자를 또 보냈다.
    **실행은 그대로 둔다** — 예약을 두 번 거는 건 GitHub 이 예약을 통째로 흘린
    사고가 있어 남겨 둔 보험이다. 줄이는 건 문자뿐이다.
    """

    def _기록(self, monkeypatch, 실행들, 이번run="999"):
        import scripts.send_telegram_summary as S
        import scripts.가동확인 as G
        monkeypatch.setenv("GITHUB_RUN_ID", 이번run)
        monkeypatch.setenv("GH_REPO", "o/r")
        monkeypatch.setattr(G, "실행이력", lambda *a, **k: 실행들)
        # 2026-10-31: '이미 보고함'은 앞 실행이 멈춤이 아니었다는 기록이 있을 때만이다(run 1 = 노출 급감 통과).
        monkeypatch.setattr(S, "_앞_실행_기록", lambda: {"run_id": "1", "status": "통과"})
        return S.이_회차에_이미_보고했나()

    def _run(self, 때, conclusion="success", rid=1):
        from datetime import timezone
        return {"createdAt": 때.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "conclusion": conclusion, "status": "completed", "databaseId": rid}

    def test_같은_회차에_성공이_있으면_건너뛴다(self, monkeypatch):
        from scripts.가동확인 import KST
        from datetime import datetime
        나 = datetime(2026, 8, 7, 0, 30, tzinfo=KST)
        앞 = datetime(2026, 8, 7, 0, 10, tzinfo=KST)
        assert self._기록(monkeypatch, [self._run(나, "", 999), self._run(앞, "success", 1)])

    def test_앞_회차_성공은_건너뛸_이유가_안_된다(self, monkeypatch):
        from scripts.가동확인 import KST
        from datetime import datetime
        나 = datetime(2026, 8, 7, 6, 10, tzinfo=KST)
        앞 = datetime(2026, 8, 7, 5, 50, tzinfo=KST)   # 00~06시 회차
        assert not self._기록(monkeypatch, [self._run(나, "", 999), self._run(앞, "success", 1)])

    def test_같은_회차라도_실패였으면_보낸다(self, monkeypatch):
        from scripts.가동확인 import KST
        from datetime import datetime
        나 = datetime(2026, 8, 7, 0, 30, tzinfo=KST)
        앞 = datetime(2026, 8, 7, 0, 10, tzinfo=KST)
        assert not self._기록(monkeypatch, [self._run(나, "", 999), self._run(앞, "failure", 1)])

    def test_자기_자신을_보고_건너뛰지_않는다(self, monkeypatch):
        """이번 run 이 성공으로 찍혀 있어도 그건 '이미 보냈다'가 아니다."""
        from scripts.가동확인 import KST
        from datetime import datetime
        나 = datetime(2026, 8, 7, 0, 30, tzinfo=KST)
        assert not self._기록(monkeypatch, [self._run(나, "success", 999)])

    def test_못_읽으면_보낸다(self, monkeypatch):
        """★못 읽은 것을 '이미 보냈다'로 읽으면 침묵이 기본값이 된다."""
        import scripts.send_telegram_summary as S
        import scripts.가동확인 as G
        monkeypatch.setattr(G, "실행이력",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("gh 죽음")))
        assert not S.이_회차에_이미_보고했나()

    def test_회차_경계를_스스로_다시_계산하지_않는다(self):
        """★경계가 두 곳에 있으면 조용히 갈라진다 — 가동확인.py 것을 쓴다."""
        import pathlib
        본문 = (pathlib.Path(__file__).resolve().parents[2]
                / "scripts/send_telegram_summary.py").read_text(encoding="utf-8")
        assert "회차_시작" in 본문 and "// 6" not in 본문

    def test_main_이_실제로_그_문을_지난다(self, monkeypatch, tmp_path):
        """★배선 검사. 판정이 아무리 맞아도 main() 이 안 부르면 문자는 그대로 두 통이다.

        (돌연변이 확인에서 실제로 뚫렸던 자리 — 판정 함수만 검사하고 있었다.)
        """
        import json

        import scripts.send_telegram_summary as S
        monkeypatch.chdir(tmp_path)
        # 2026-10-31: 생략은 평범한 정상(✅) 결과에만 건다 — 실패 · 경보 문자는 같은 회차라도 간다.
        (tmp_path / "cycle_summary.json").write_text(
            json.dumps({"success_rate": 1.0, "total_rows_processed": 400}), encoding="utf-8")
        보낸것 = []
        monkeypatch.setattr(S, "send_report", lambda t: 보낸것.append(t) or 0)
        monkeypatch.setattr(S, "이_회차에_이미_보고했나", lambda: True)
        assert S.main() == 0
        assert 보낸것 == [], "이미 성공 보고가 나간 회차인데 문자를 또 보냈다"

    def test_안_보낸_회차면_그대로_보낸다(self, monkeypatch, tmp_path):
        """막는 쪽만 검사하면 '늘 막는' 코드도 통과한다 = 전면 침묵."""
        import scripts.send_telegram_summary as S
        monkeypatch.chdir(tmp_path)
        보낸것 = []
        monkeypatch.setattr(S, "send_report", lambda t: 보낸것.append(t) or 0)
        monkeypatch.setattr(S, "이_회차에_이미_보고했나", lambda: False)
        assert S.main() == 0
        assert len(보낸것) == 1

    def test_워크플로가_gh_인증을_넘긴다(self):
        """지난 실행을 물어보려면 GH_TOKEN 이 있어야 한다 — 없으면 늘 '못 읽음'."""
        import pathlib

        import yaml
        WF = (pathlib.Path(__file__).resolve().parents[2]
              / ".github/workflows/rank-check.yml")
        d = yaml.safe_load(WF.read_text(encoding="utf-8"))
        (잡,) = d["jobs"].values()
        스텝 = [s for s in 잡["steps"]
               if "send_telegram_summary.py" in str(s.get("run", ""))][0]
        assert "GH_TOKEN" in 스텝["env"], "gh 인증이 없으면 중복 문자가 그대로 나간다"


class Test멈춘_뒤_다시_잰_결과는_보낸다:
    """★2026-10-31 사장님 "왜 보고를 안해줘 근데 상노" · "텔레그램에".

    같은 회차(6시간)에 success 로 끝난 실행이 있으면 무조건 '이미 보고함'으로 읽었다.
    그런데 노출 급감으로 시트 쓰기를 멈춘 실행도 종료 0(success)이다. 그래서
      · 12:00 실행(41162456392)이 멈춤으로 12~18 칸을 차지하자
      · 15:19 손으로 다시 잰 실행(41176100244, 2회차 922/922 성공)의 문자가 생략됐다.
    사장님은 '멈춤 → 다시 재서 성공'의 끝 소식을 못 받으셨다.
    문자 폭주를 막는 장치(정상 보고가 이미 나간 회차의 예약 실행은 생략)는 그대로 둔다.
    """

    @staticmethod
    def _run(시각, conclusion, rid):
        from datetime import timezone
        return {"createdAt": 시각.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                "conclusion": conclusion, "status": "completed", "databaseId": rid}

    @staticmethod
    def _정상_요약(앞기록):
        return {"success_rate": 1.0, "total_rows_processed": 922, "code_change_suspected": False,
                "exposure_drop": {"status": "통과", "rows_compared": 922, "rows_unreadable": 0,
                                  "prev_run": {"state": "앞 회차 멈춤 아님", "why": "",
                                               "record": 앞기록}},
                "exposure_drop_status": "통과", "exposure_drop_hold": False}

    def _main(self, monkeypatch, tmp_path, 실행들, 이번run, 요약,
              이벤트="schedule", 시도="1", run_status="success"):
        import json

        import scripts.send_telegram_summary as S
        import scripts.가동확인 as G
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("GITHUB_RUN_ID", str(이번run))
        monkeypatch.setenv("GH_REPO", "o/r")
        monkeypatch.setenv("GITHUB_EVENT_NAME", 이벤트)
        monkeypatch.setenv("GITHUB_RUN_ATTEMPT", 시도)
        monkeypatch.setenv("RUN_STATUS", run_status)
        monkeypatch.setattr(G, "실행이력", lambda *a, **k: 실행들)
        if 요약 is not None:
            (tmp_path / "cycle_summary.json").write_text(
                json.dumps(요약, ensure_ascii=False), encoding="utf-8")
        보낸것 = []
        monkeypatch.setattr(S, "send_report", lambda t: 보낸것.append(t) or 0)
        assert S.main() == 0
        return 보낸것

    # ── 장면 ㉠ 같은 회차 앞 실행이 '멈춤으로 끝난 success' · 이번은 정상 성공(예약) → 보낸다
    def test_ㄱ_앞_실행이_멈춤이면_이번_정상_결과를_보낸다(self, monkeypatch, tmp_path):
        from datetime import datetime

        from scripts.가동확인 import KST
        멈춘것 = self._run(datetime(2026, 10, 31, 12, 0, 30, tzinfo=KST), "success", 41162456392)
        나 = self._run(datetime(2026, 10, 31, 12, 27, tzinfo=KST), "", 5001)
        보낸것 = self._main(monkeypatch, tmp_path, [나, 멈춘것], 5001,
                          self._정상_요약({"run_id": "41162456392", "run_attempt": 1,
                                         "status": "멈춤"}))
        assert len(보낸것) == 1 and 보낸것[0].startswith("✅"), \
            "멈춤 문자 뒤에 정상으로 다시 잰 결과가 안 갔다 — 사장님은 '멈춤'에서 소식이 끊긴다"

    # ── 장면 ㉡ 이번 실행이 workflow_dispatch(손으로 다시 잼) → 보낸다
    def test_ㄴ_손으로_다시_잰_실행은_보낸다(self, monkeypatch, tmp_path):
        """15:00 실행(사람 스위치)이 정상 기록으로 칸을 차지해도, 15:19 손으로 다시 잰 결과는 간다."""
        from datetime import datetime

        from scripts.가동확인 import KST
        멈춘것 = self._run(datetime(2026, 10, 31, 12, 0, 30, tzinfo=KST), "success", 41162456392)
        스위치 = self._run(datetime(2026, 10, 31, 15, 0, 7, tzinfo=KST), "success", 41174777839)
        나 = self._run(datetime(2026, 10, 31, 15, 19, 8, tzinfo=KST), "", 41176100244)
        보낸것 = self._main(monkeypatch, tmp_path, [나, 스위치, 멈춘것], 41176100244,
                          self._정상_요약({"run_id": "41174777839", "run_attempt": 1,
                                         "status": "풀림(사람 스위치)"}),
                          이벤트="workflow_dispatch")
        assert len(보낸것) == 1 and 보낸것[0].startswith("✅")

    def test_ㄴ_워치독이_다시_돌린_2회차도_보낸다(self, monkeypatch, tmp_path):
        """실패 알림 뒤 다시 돌린 시도(run_attempt 2 이상)의 성공이 곧 '끝 소식'이다."""
        from datetime import datetime

        from scripts.가동확인 import KST
        앞 = self._run(datetime(2026, 10, 31, 18, 0, 27, tzinfo=KST), "success", 41186870225)
        나 = self._run(datetime(2026, 10, 31, 18, 7, tzinfo=KST), "", 5002)
        보낸것 = self._main(monkeypatch, tmp_path, [나, 앞], 5002,
                          self._정상_요약({"run_id": "41186870225", "run_attempt": 1,
                                         "status": "통과"}),
                          시도="2")
        assert len(보낸것) == 1

    # ── 장면 ㉢ 같은 회차에 정상 보고가 이미 나갔고 이번은 예약 실행 → 지금처럼 생략
    def test_ㄷ_정상_보고가_나간_회차의_예약_실행은_생략한다(self, monkeypatch, tmp_path, capsys):
        from datetime import datetime

        from scripts.가동확인 import KST
        앞 = self._run(datetime(2026, 10, 31, 18, 0, 27, tzinfo=KST), "success", 41186870225)
        나 = self._run(datetime(2026, 10, 31, 18, 29, 41, tzinfo=KST), "", 41188906501)
        보낸것 = self._main(monkeypatch, tmp_path, [나, 앞], 41188906501,
                          self._정상_요약({"run_id": "41186870225", "run_attempt": 1,
                                         "status": "통과"}))
        assert 보낸것 == [], "문자 폭주를 막는 장치가 풀렸다"
        assert "41186870225" in capsys.readouterr().out, "어느 실행이 칸을 차지했는지 로그에 없다"

    # ── 같은 뿌리의 다른 자리
    def test_앞_실행이_무엇을_보고했는지_모르면_보낸다(self, monkeypatch, tmp_path):
        """기록(캐시)이 없거나 다른 실행 것이면 '이미 보냈다'로 읽지 않는다 — 침묵이 기본값이 되면 안 된다."""
        from datetime import datetime

        from scripts.가동확인 import KST
        앞 = self._run(datetime(2026, 10, 31, 18, 0, 27, tzinfo=KST), "success", 41186870225)
        나 = self._run(datetime(2026, 10, 31, 18, 29, 41, tzinfo=KST), "", 41188906501)
        보낸것 = self._main(monkeypatch, tmp_path, [나, 앞], 41188906501, self._정상_요약(None))
        assert len(보낸것) == 1

    def test_앞_실행의_다른_시도_기록이면_보낸다(self, monkeypatch, tmp_path):
        """GPT 검토 1번: A 1차 '통과' 기록 저장 뒤 실패 → 다시 돌린 A 2차가 '멈춤' · 저장 실패 → B 가 1차 기록을 받음."""
        from datetime import datetime

        from scripts.가동확인 import KST
        앞 = self._run(datetime(2026, 10, 31, 18, 0, 27, tzinfo=KST), "success", 41186870225)
        앞["attempt"] = 2
        나 = self._run(datetime(2026, 10, 31, 18, 29, 41, tzinfo=KST), "", 41188906501)
        보낸것 = self._main(monkeypatch, tmp_path, [나, 앞], 41188906501,
                          self._정상_요약({"run_id": "41186870225", "run_attempt": 1,
                                         "status": "통과"}))
        assert len(보낸것) == 1

    def test_같은_시도_기록이면_예전처럼_생략(self, monkeypatch, tmp_path):
        from datetime import datetime

        from scripts.가동확인 import KST
        앞 = self._run(datetime(2026, 10, 31, 18, 0, 27, tzinfo=KST), "success", 41186870225)
        앞["attempt"] = 1
        나 = self._run(datetime(2026, 10, 31, 18, 29, 41, tzinfo=KST), "", 41188906501)
        보낸것 = self._main(monkeypatch, tmp_path, [나, 앞], 41188906501,
                          self._정상_요약({"run_id": "41186870225", "run_attempt": 1,
                                         "status": "통과"}))
        assert 보낸것 == []

    def test_이번_실행_안에서_다시_돌아_기록이_덮였으면_보낸다(self, monkeypatch, tmp_path, capsys):
        """GPT 검토 2번: 1차 사이클이 죽고 90초 뒤 다시 돌면 앞 기록 자리에 이번 실행 기록이 들어온다."""
        from datetime import datetime

        from scripts.가동확인 import KST
        앞 = self._run(datetime(2026, 10, 31, 18, 0, 27, tzinfo=KST), "success", 41186870225)
        나 = self._run(datetime(2026, 10, 31, 18, 29, 41, tzinfo=KST), "", 41188906501)
        보낸것 = self._main(monkeypatch, tmp_path, [나, 앞], 41188906501,
                          self._정상_요약({"run_id": "41188906501", "run_attempt": 1,
                                         "status": "통과"}))
        assert len(보낸것) == 1 and "덮였다" in capsys.readouterr().out

    def test_실행이력이_시도_번호를_묻는다(self):
        import pathlib
        본문 = (pathlib.Path(__file__).resolve().parents[2] / "scripts/가동확인.py").read_text(encoding="utf-8")
        assert "databaseId,attempt" in 본문, "시도 번호가 없으면 1차 기록으로 2차 결과를 판정한다"

    def test_같은_회차_바로_앞_실행이_실패였으면_보낸다(self, monkeypatch, tmp_path):
        """앞 성공 → 실패(❌ 문자) → 이번 성공: 마지막 소식이 ❌ 이므로 이번 성공은 새 소식이다."""
        from datetime import datetime

        from scripts.가동확인 import KST
        성공 = self._run(datetime(2026, 10, 31, 18, 0, 27, tzinfo=KST), "success", 41186870225)
        실패 = self._run(datetime(2026, 10, 31, 18, 7, tzinfo=KST), "failure", 5003)
        나 = self._run(datetime(2026, 10, 31, 18, 27, tzinfo=KST), "", 5004)
        보낸것 = self._main(monkeypatch, tmp_path, [나, 실패, 성공], 5004,
                          self._정상_요약({"run_id": "41186870225", "run_attempt": 1,
                                         "status": "통과"}))
        assert len(보낸것) == 1

    def test_이번_실행이_실패면_같은_회차_성공이_있어도_보낸다(self, monkeypatch, tmp_path):
        from datetime import datetime

        from scripts.가동확인 import KST
        앞 = self._run(datetime(2026, 10, 31, 18, 0, 27, tzinfo=KST), "success", 41186870225)
        나 = self._run(datetime(2026, 10, 31, 18, 29, tzinfo=KST), "", 5005)
        보낸것 = self._main(monkeypatch, tmp_path, [나, 앞], 5005, None, run_status="failure")
        assert len(보낸것) == 1 and 보낸것[0].startswith("❌")

    def test_이번_실행에_K분포_경보가_있으면_보낸다(self, monkeypatch, tmp_path):
        """사람 스위치로 푼 실행은 K 분포 경보가 빨강으로 안 올라가 ✅ 줄이 된다 — 그래도 생략하지 않는다."""
        from datetime import datetime

        from scripts.가동확인 import KST
        앞 = self._run(datetime(2026, 10, 31, 12, 0, 30, tzinfo=KST), "success", 41162456392)
        나 = self._run(datetime(2026, 10, 31, 12, 27, tzinfo=KST), "", 5006)
        요약 = self._정상_요약({"run_id": "41162456392", "run_attempt": 1, "status": "통과"})
        요약["k_anomaly_detected"] = True
        보낸것 = self._main(monkeypatch, tmp_path, [나, 앞], 5006, 요약)
        assert len(보낸것) == 1
