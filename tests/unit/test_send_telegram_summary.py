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
        import scripts.send_telegram_summary as S
        monkeypatch.chdir(tmp_path)
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
