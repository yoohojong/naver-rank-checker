# -*- coding: utf-8 -*-
"""자가치유 회귀 (2026-07-24).

사장님 지시: "재시도여부도 텔레그램으로 보내줘야하고 성공 여부까지 보내줘야지"
→ 실패·반복실패·**복구** 세 시점이 전부 가는지, 그리고 평소 성공에 스팸이 안 나는지 검사.

    python -m pytest cafe-external/test_자가치유.py -q
"""
import importlib.util
import os
import pathlib
import sys

import pytest

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts")
저장소루트 = pathlib.Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "자가치유_mod", os.path.join(HERE, "자가치유.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["자가치유_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def H(monkeypatch):
    mod = _load()
    monkeypatch.setenv("GITHUB_REPOSITORY", "yoohojong/naver-rank-checker")
    monkeypatch.setenv("GITHUB_RUN_ID", "999")
    monkeypatch.setenv("WORKFLOW_FILE", "rank-check.yml")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    # CI 안에서 돌면 이 값들이 진짜로 들어 있다 — 검사가 그 값에 따라 갈리지 않게 비운다.
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
    return mod


def _runs(*결론들):
    return {"workflow_runs": [{"id": 100 + i, "conclusion": c}
                              for i, c in enumerate(결론들)]}


class Test연속실패_세기:
    def test_성공을_만나면_거기서_끊는다(self, H, monkeypatch):
        monkeypatch.setattr(H, "_api", lambda *a, **k: _runs("failure", "failure", "success", "failure"))
        assert H.연속실패_횟수("r", "w", "999", "failure") == 3   # 이번 것 + 앞의 2

    def test_성공이면_0(self, H):
        assert H.연속실패_횟수("r", "w", "999", "success") == 0

    def test_못_세면_1로_본다(self, H, monkeypatch):
        """과소보고가 과대보고보다 안전 — 없는 '5회 연속'으로 사장님을 놀래지 않는다."""
        monkeypatch.setattr(H, "_api", lambda *a, **k: None)
        assert H.연속실패_횟수("r", "w", "999", "failure") == 1

    def test_이번_run_은_두_번_안_센다(self, H, monkeypatch):
        monkeypatch.setattr(H, "_api", lambda *a, **k: {
            "workflow_runs": [{"id": 999, "conclusion": "failure"},
                              {"id": 998, "conclusion": "success"}]})
        assert H.연속실패_횟수("r", "w", "999", "failure") == 1


class Test원인_분류:
    def _로그(self, H, monkeypatch, 본문):
        def api(경로, 방법="GET", 본문2=None, raw=False):
            if "/jobs?" in 경로:
                return {"jobs": [{"id": 7, "conclusion": "failure",
                                  "steps": [{"name": "Deposit + 수집상태 실물검증 반영 (핵심)",
                                             "conclusion": "failure"}]}]}
            if "/logs" in 경로:
                return 본문
            return None
        monkeypatch.setattr(H, "_api", api)
        return H.실패로그_원인("r", "999")

    def test_연결끊김을_사람말로_부른다(self, H, monkeypatch):
        원인, 안내, 증거 = self._로그(
            H, monkeypatch,
            "collect\tstep\t2026-07-23T14:54:10Z requests.exceptions.ConnectionError: "
            "('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))\n")
        assert "연결을 끊음" in 원인
        assert "다리" in 안내 or "앱스스크립트" in 안내
        assert "ConnectionResetError" in 증거
        assert "2026-07-23T14:54" not in 증거, "앞 타임스탬프는 지워야 읽힌다"

    def test_어느_step_에서_죽었는지_붙인다(self, H, monkeypatch):
        원인, _, _ = self._로그(H, monkeypatch, "ConnectionResetError(104)")
        assert "Deposit" in 원인, "사장님이 위치를 바로 알 수 있어야 한다"

    def test_토큰만료가_연결끊김보다_정확히_잡힌다(self, H, monkeypatch):
        원인, 안내, _ = self._로그(H, monkeypatch, "urllib.error.HTTPError: HTTP Error 401")
        assert "열쇠" in 원인 and "Secrets" in 안내

    def test_코드문제는_저절로_안_풀린다고_말한다(self, H, monkeypatch):
        원인, 안내, _ = self._로그(H, monkeypatch, "AttributeError: 'NoneType' object")
        assert "코드" in 원인 and "저절로 안" in 안내

    def test_모르면_모른다고_한다(self, H, monkeypatch):
        원인, _, _ = self._로그(H, monkeypatch, "무슨 일인지 알 수 없는 출력")
        assert 원인 == "알 수 없음", "억지로 아는 척하면 오진을 부른다"


class Test알림_문장:
    def test_첫_실패는_자동재시도를_안내한다(self, H):
        s = H.문장_만들기("상위노출 순위검사", "failure", 1, "상대 서버가 연결을 끊음",
                      "다음 회차에 풉니다", "ConnectionReset", "http://log", "6시간 뒤쯤")
        assert "🚨" in s and "6시간 뒤쯤 다시 시도" in s
        assert "연속" not in s

    def test_반복_실패는_사람_확인을_요청한다(self, H):
        s = H.문장_만들기("상위노출 순위검사", "failure", 3, "우리 코드 문제",
                      "고쳐야 합니다", "AttributeError", "http://issue", "")
        assert "3회 연속" in s and "저절로 풀리는 문제가 아닙니다" in s

    def test_복구도_반드시_알린다(self, H):
        """사장님 지시의 '성공 여부까지'. 이게 없으면 계속 고장난 줄 안다."""
        s = H.문장_만들기("상위노출 순위검사", "success", 0, "", "", "", "", "")
        assert "✅" in s and "복구" in s


class Test전체_흐름:
    def _스파이(self, H, monkeypatch):
        보낸것 = []
        monkeypatch.setattr(H, "텔레그램", lambda s: 보낸것.append(s) or True)
        return 보낸것

    def test_평소_성공엔_알림이_안_간다(self, H, monkeypatch):
        보낸것 = self._스파이(H, monkeypatch)
        monkeypatch.setattr(H, "_api", lambda *a, **k: _runs("success", "success"))
        H.main(["--이름", "상위노출 순위검사", "--결과", "success"])
        assert 보낸것 == [], "하루 수십 통이면 아무도 안 본다"

    def test_실패_뒤_성공이면_문자_대신_아침보고로_넘기고_이슈를_닫는다(self, H, monkeypatch, capsys):
        """★2026-10-21 사장님 "이상한 보고가 너무 많아 진짜" — '복구됐습니다' 문자는 보내지 않고
        팀 저장소의 아침 건강 보고(system_health)가 한 줄로 싣는다."""
        보낸것 = self._스파이(H, monkeypatch)
        닫힌것 = []
        monkeypatch.setattr(H, "_api", lambda *a, **k: _runs("failure", "failure"))
        monkeypatch.setattr(H, "이슈_닫기", lambda *a: 닫힌것.append(a))
        H.main(["--이름", "상위노출 순위검사", "--결과", "success"])
        assert 보낸것 == [], "복구 문자는 아침 건강 보고로 옮겼다"
        assert "아침 건강 보고" in capsys.readouterr().out
        assert 닫힌것, "나은 이슈를 계속 띄워두면 아무도 안 본다"

    def test_한계를_아예_못_알아내면_알리지_않는다(self, H, monkeypatch):
        # 한계를 모르면 고장인지 사람이 누른 취소인지 가릴 근거가 없다 — 그때만 조용하다.
        # (2026-09-03 개정: 예전엔 TIMEOUT_MIN 만 봤다. 이제 워크플로 파일도 보므로
        #  '못 알아내는' 상황을 만들려면 그런 워크플로가 없어야 한다.)
        보낸것 = self._스파이(H, monkeypatch)
        monkeypatch.delenv("TIMEOUT_MIN", raising=False)
        monkeypatch.setenv("WORKFLOW_FILE", "있지도-않은-워크플로.yml")
        H.main(["--이름", "상위노출 순위검사", "--결과", "cancelled"])
        assert 보낸것 == []

    def test_TIMEOUT_MIN_이_없어도_워크플로_파일에서_한계를_읽는다(self, H, monkeypatch):
        """★2026-09-03. 이게 그 구멍이었다.

        발행검수(balhaeng-geomsu.yml)는 timeout-minutes: 120 을 적어 놓고도
        env TIMEOUT_MIN 이 없어서, 120분을 다 채우고 잘려도 **문자가 0통**이었다.
        값을 두 벌 적게 하는 구조 자체를 없앤다 — 선언한 자리에서 읽는다.
        """
        보낸것 = self._스파이(H, monkeypatch)
        monkeypatch.delenv("TIMEOUT_MIN", raising=False)
        monkeypatch.setenv("WORKFLOW_FILE", "balhaeng-geomsu.yml")
        monkeypatch.setenv("GITHUB_WORKSPACE", str(저장소루트))
        monkeypatch.setattr(H, "_경과분", lambda *a: 119.5)
        H.main(["--이름", "발행본 검수", "--결과", "cancelled"])
        assert len(보낸것) == 1 and "시간 초과" in 보낸것[0]
        assert "120분" in 보낸것[0], f"한계를 잘못 읽었다: {보낸것[0]}"

    def test_주석에_적힌_숫자가_실제_한계를_이기지_않는다(self, H, tmp_path, monkeypatch):
        """설명글이 검사를 대신 통과시켜 주는 일은 없어야 한다."""
        폴더 = tmp_path / ".github" / "workflows"
        폴더.mkdir(parents=True)
        (폴더 / "x.yml").write_text(
            "jobs:\n  a:\n    # timeout-minutes: 999\n    timeout-minutes: 30\n",
            encoding="utf-8")
        monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
        assert H._워크플로가_밝힌_한계분("x.yml") == 30

    def test_job_이_여럿이면_가장_짧은_한계를_쓴다(self, H, tmp_path, monkeypatch):
        """크게 잡으면 짧은 job 이 잘렸을 때 '아직 멀었다'로 읽어 침묵한다."""
        폴더 = tmp_path / ".github" / "workflows"
        폴더.mkdir(parents=True)
        (폴더 / "y.yml").write_text(
            "jobs:\n  a:\n    timeout-minutes: 300\n  b:\n    timeout-minutes: '45'\n",
            encoding="utf-8")
        monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
        assert H._워크플로가_밝힌_한계분("y.yml") == 45

    def test_시간한계를_다_채운_취소는_시간초과로_알린다(self, H, monkeypatch):
        # ★2026-08-20 교훈: 경쟁사-댓글이 7/29~8/16 매일 밤 180분을 채우고 잘렸는데
        #   '취소'라는 이름 때문에 알림 0통 — 침묵이 기본값이 되면 고장이 숨는다.
        보낸것 = self._스파이(H, monkeypatch)
        monkeypatch.setenv("TIMEOUT_MIN", "180")
        monkeypatch.setattr(H, "_경과분", lambda *a: 179.7)
        H.main(["--이름", "댓글 경쟁제품 수집", "--결과", "cancelled"])
        assert len(보낸것) == 1 and "시간 초과" in 보낸것[0]

    def test_일찍_잘린_취소는_사람취소로_보고_조용히_둔다(self, H, monkeypatch):
        보낸것 = self._스파이(H, monkeypatch)
        monkeypatch.setenv("TIMEOUT_MIN", "180")
        monkeypatch.setattr(H, "_경과분", lambda *a: 12.0)
        H.main(["--이름", "댓글 경쟁제품 수집", "--결과", "cancelled"])
        assert 보낸것 == []

    def test_경과를_못_재면_한계가_밝혀진_워크플로는_알린다(self, H, monkeypatch):
        # 조회 실패까지 침묵으로 접으면 '경보를 조건부로 삼키는' 병이 재발한다 — 알리는 쪽으로.
        보낸것 = self._스파이(H, monkeypatch)
        monkeypatch.setenv("TIMEOUT_MIN", "180")
        monkeypatch.setattr(H, "_경과분", lambda *a: None)
        H.main(["--이름", "댓글 경쟁제품 수집", "--결과", "cancelled"])
        assert len(보낸것) == 1 and "시간 초과" in 보낸것[0]

    def test_임계_넘으면_이슈를_연다(self, H, monkeypatch):
        보낸것 = self._스파이(H, monkeypatch)
        연것 = []
        monkeypatch.setattr(H, "연속실패_재기", lambda *a, **k: {"연속": 3, "이상": False, "직전실패시각": ""})
        monkeypatch.setattr(H, "실패로그_원인",
                            lambda *a: ("우리 코드 문제", "고쳐야 합니다", "AttributeError"))
        monkeypatch.setattr(H, "이슈_열기",
                            lambda *a: 연것.append(a) or "http://issue/1")
        H.main(["--이름", "상위노출 순위검사", "--결과", "failure"])
        assert 연것, "3회 연속이면 Claude 가 집을 자리를 만들어야 한다"
        assert "http://issue/1" in 보낸것[0]

    def test_임계_전이면_이슈를_안_연다(self, H, monkeypatch):
        self._스파이(H, monkeypatch)
        연것 = []
        monkeypatch.setattr(H, "연속실패_재기", lambda *a, **k: {"연속": 1, "이상": False, "직전실패시각": ""})
        monkeypatch.setattr(H, "실패로그_원인", lambda *a: ("상대 서버", "곧 풉니다", ""))
        monkeypatch.setattr(H, "이슈_열기", lambda *a: 연것.append(a) or "")
        H.main(["--이름", "상위노출 순위검사", "--결과", "failure"])
        assert not 연것, "한 번 삐끗한 걸로 이슈를 열면 이슈가 쓰레기통이 된다"

    def test_어떤_실패에도_비0으로_안_죽는다(self, H, monkeypatch):
        """자가치유가 크론을 죽이면 본말전도."""
        def 터짐(*a, **k):
            raise RuntimeError("GitHub 다운")
        monkeypatch.setattr(H, "_api", 터짐)
        monkeypatch.setattr(H, "텔레그램", 터짐)
        try:
            rc = H.main(["--이름", "x", "--결과", "failure"])
        except Exception as e:
            pytest.fail(f"자가치유가 예외를 올렸다: {e!r}")
        assert rc == 0


class Test다음_재시도_안내:
    @pytest.mark.parametrize("크론,기대", [
        ("17 */6 * * *", "6시간 뒤쯤"),
        ("0 22 * * *", "다음 예정 시각에"),
        ("7,27 15,21,3,9 * * *", "다음 예정 시각에"),
        ("", ""),
    ])
    def test_사람말로_바꾼다(self, H, 크론, 기대):
        assert H.다음_재시도(크론) == 기대


class Test증거줄_다듬기:
    """실제 API 로그와 gh CLI 로그의 앞머리 형식이 달라 둘 다 벗겨야 한다."""

    @pytest.mark.parametrize("원본", [
        "2026-07-23T14:54:10.1306926Z ConnectionResetError: [Errno 104] Connection reset by peer",
        "collect\t핵심\t2026-07-23T14:54:10Z ConnectionResetError: [Errno 104] Connection reset by peer",
    ])
    def test_앞_타임스탬프를_벗긴다(self, H, 원본):
        결과 = H._증거줄(원본, 원본.index("ConnectionResetError"))
        assert 결과.startswith("ConnectionResetError"), f"앞머리가 남았다: {결과!r}"
        assert "2026-07-23" not in 결과


class Test라이브_실제상태:
    """★독립검토 CRITICAL 회귀 — 라이브에서 실제로 오는 payload 로만 검사한다.

    옛 테스트는 `conclusion: "failure"` 인 job 을 모킹했다. 그런데 자가치유는
    **같은 job 의 마지막 step** 이라, 라이브에서 자기 job 은 언제나
    status=in_progress · conclusion=None 이다. 그래서 진단이 100% '알 수 없음' 으로
    나왔는데도 24건이 전부 통과했다 — 테스트가 작성자의 틀린 모델을 되풀이한 탓.
    """

    def _진단(self, H, monkeypatch, job, 로그):
        def api(경로, 방법="GET", 본문=None, raw=False):
            if "/jobs?" in 경로:
                return {"jobs": [job]}
            if "/logs" in 경로:
                return 로그
            return None
        monkeypatch.setattr(H, "_api", api)
        return H.실패로그_원인("r", "999")

    def test_진행중인_자기_job_도_진단한다(self, H, monkeypatch):
        원인, _, _ = self._진단(H, monkeypatch,
            {"id": 7, "status": "in_progress", "conclusion": None,
             "steps": [{"name": "핵심", "conclusion": "failure"},
                       {"name": "자가치유 보고", "conclusion": None}]},
            "ConnectionResetError: [Errno 104] Connection reset by peer")
        assert 원인 != "알 수 없음", "라이브에서 항상 이 상태다 — 여기서 못 읽으면 2층이 죽는다"
        assert "핵심" in 원인

    def test_성공한_job_은_건드리지_않는다(self, H, monkeypatch):
        원인, _, _ = self._진단(H, monkeypatch,
            {"id": 7, "status": "completed", "conclusion": "success", "steps": []},
            "ConnectionResetError")
        assert 원인 == "알 수 없음"


class Test오탐_방지:
    """★독립검토 H-1 — 오진은 사장님께 틀린 조치를 시킨다(토큰 재발급 등)."""

    def _진단(self, H, monkeypatch, 로그):
        def api(경로, 방법="GET", 본문=None, raw=False):
            if "/jobs?" in 경로:
                return {"jobs": [{"id": 7, "conclusion": None,
                                  "steps": [{"name": "핵심", "conclusion": "failure"}]}]}
            if "/logs" in 경로:
                return 로그
            return None
        monkeypatch.setattr(H, "_api", api)
        return H.실패로그_원인("r", "999")[0]

    def test_pip_의_401kB_를_토큰만료로_읽지_않는다(self, H, monkeypatch):
        원인 = self._진단(H, monkeypatch,
            "Downloading pandas-2.4.1.tar.gz (401 kB)\n"
            "Traceback (most recent call last):\n"
            "AttributeError: 'NoneType' object has no attribute 'get'\n")
        assert "코드" in 원인, f"pip 출력에 낚였다: {원인}"

    def test_수집_401건_도_토큰만료가_아니다(self, H, monkeypatch):
        원인 = self._진단(H, monkeypatch,
            "수집 401건 완료\nTraceback (most recent call last):\nTimeoutError: timed out\n")
        assert "시간" in 원인, f"본문 숫자에 낚였다: {원인}"

    def test_이미_복구된_재시도가_진짜_원인을_덮지_않는다(self, H, monkeypatch):
        원인 = self._진단(H, monkeypatch,
            "[retry 1/3] ConnectionResetError → [retry 2/3] 성공\n"
            "Traceback (most recent call last):\n"
            "AttributeError: 'NoneType' object\n")
        assert "코드" in 원인, f"앞쪽 잡음이 이겼다: {원인}"

    def test_진짜_401은_잡는다(self, H, monkeypatch):
        원인 = self._진단(H, monkeypatch, "urllib.error.HTTPError: HTTP Error 401: Unauthorized")
        assert "열쇠" in 원인


class Test연속_카운트_보정:
    def test_타임아웃도_실패로_센다(self, H, monkeypatch):
        """★M-1: 5회 연속 타임아웃이 '연속 1회'로 보고되면 3층이 안 열린다."""
        monkeypatch.setattr(H, "_api", lambda *a, **k: _runs("timed_out", "timed_out", "success"))
        assert H.연속실패_횟수("r", "w", "999", "failure") == 3

    def test_취소는_연속을_끊지_않는다(self, H, monkeypatch):
        """★M-3: 취소가 잦은 워크플로에서 연속이 늘 1 이 되던 문제."""
        monkeypatch.setattr(H, "_api", lambda *a, **k: _runs("cancelled", "failure", "cancelled", "failure"))
        assert H.연속실패_횟수("r", "w", "999", "failure") == 3


class Test알림_폭주_방지:
    """★H-3: 5분 크론이 고장나면 하루 288통 — 사장님이 알림을 꺼버린다."""

    def test_처음_세_번은_매번_알린다(self, H):
        assert all(H.알릴차례인가(n) for n in (1, 2, 3))

    def test_그_뒤로는_하루_한_통(self, H):
        """★2026-10-21: '12의 배수'만 보내면 연속 수가 31에서 멈췄을 때 영영 안 보냈다.
        네 번째부터는 횟수가 아니라 날짜로 — 그날(한국 시각) 첫 실패에서만 보낸다."""
        from datetime import datetime, timezone
        지금 = datetime(2026, 10, 21, 1, 0, tzinfo=timezone.utc)        # KST 10/21 10:00
        어제 = "2026-10-20T13:00:00Z"                                   # KST 10/20 22:00
        오늘아침 = "2026-10-20T22:30:00Z"                               # KST 10/21 07:30
        assert H.알릴차례인가(31, 어제, 지금) is True, "31회째도 하루 한 번은 알려야 한다"
        assert H.알릴차례인가(145, 어제, 지금) is True
        assert H.알릴차례인가(32, 오늘아침, 지금) is False, "같은 날 두 번째는 안 보낸다"
        assert H.알릴차례인가(5, 오늘아침, 지금) is False


class Test시간한계를_모든_워크플로에서_알아내는가:
    """★자가치유를 붙여 놓고 시간 한계를 못 알아내면, 그 워크플로는 시간을 다 채우고
    잘리는 날 **문자가 0통**이다. 발행검수가 정확히 그 상태였다(2026-09-03).

    워크플로마다 손으로 적게 하는 규칙은 이미 실패했다 — 여덟 곳 중 한 곳만 적혀 있었다.
    그래서 '적었나'가 아니라 **'알아낼 수 있나'** 를 센다.
    """

    def _자가치유_쓰는_워크플로(self):
        폴더 = 저장소루트 / ".github" / "workflows"
        return sorted(p for p in 폴더.glob("*.yml")
                      if "자가치유.py" in p.read_text(encoding="utf-8"))

    def test_자가치유를_쓰는_워크플로가_실제로_있다(self):
        """목록이 비면 아래 검사가 아무것도 안 세고 초록이 된다."""
        assert len(self._자가치유_쓰는_워크플로()) >= 3

    def test_한_곳도_빠짐없이_한계를_알아낼_수_있다(self, H, monkeypatch):
        monkeypatch.delenv("TIMEOUT_MIN", raising=False)
        monkeypatch.setenv("GITHUB_WORKSPACE", str(저장소루트))
        빠진것 = []
        for p in self._자가치유_쓰는_워크플로():
            monkeypatch.setenv("WORKFLOW_FILE", p.name)
            if H._시간한계분() <= 0:
                빠진것.append(p.name)
        assert not 빠진것, (
            f"시간 한계를 못 알아내는 워크플로: {빠진것} — 시간을 다 채우고 잘리면 "
            "'취소'로 끝나고 문자가 한 통도 안 나간다")


def test_두_저장소_사본이_안_갈라졌다():
    """★L-4: 한쪽만 고치면 조용히 갈라진다 — 버전으로 대조."""
    import re
    한쪽 = pathlib.Path(HERE, "자가치유.py").read_text(encoding="utf-8")
    m = re.search(r'버전 = "([^"]+)"', 한쪽)
    assert m, "버전 표시가 사라졌다"
    저쪽 = pathlib.Path(HERE, "..", "..", "team project", "cafe-external", "자가치유.py")
    if 저쪽.exists():
        저쪽글 = 저쪽.read_text(encoding="utf-8")
        assert m.group(1) in 저쪽글, \
            "두 저장소의 자가치유.py 버전이 다르다 — 한쪽만 고쳤다"
        # ★2026-10-21: 버전 글자만 대조하던 구멍. 두 사본이 같은 '2026-10-21.1' 을 달고도
        #   직전 실패 시각(시작 vs 끝)·복구 알림 길·시간 한계 읽는 순서가 달랐다.
        #   **내용 전체**를 견준다(read_text 가 줄 끝 글자는 맞춰 준다).
        assert 한쪽 == 저쪽글, \
            "두 저장소의 자가치유.py 내용이 다르다 — 같은 버전 표시를 달고 갈라졌다"


# ── 연속 실패 셈의 두 구멍 (2026-10-21 · 진단 `4_실패3곳_진단.md`) ───────────────
#
# 실측(margin-guard 로그 원문): 9/9 첫 실패가 '11회 연속', 12를 건너뛰고 13, 9/15 21,
#   10/20 '31회 연속 — 알림은 띄엄띄엄'. 정기 144회가 실패하는 동안 알림이 한 통도 안 갔다.
#   ① 최근 실행을 30개 한 장만 물어서 31(이번 것 + 30)에서 멈췄다.
#   ② 알림은 '1·2·3회째와 12의 배수'에만 — 31은 둘 다 아니라 영영 차례가 안 왔다.
#   ③ 알림 단계는 정기 실행에서만 도는데, 셈에는 코드 올림(push) 실행까지 섞였다.

def _쪽(결론들, 시작id=100, 시각="2026-10-20T13:00:00Z"):
    return [{"id": 시작id + i, "conclusion": c, "run_started_at": 시각}
            for i, c in enumerate(결론들)]


def _쪽나눠주는_api(전부, 본경로=None, 쪽크기=100):
    """GitHub 처럼 page·per_page 로 잘라 준다. 물은 경로는 본경로에 쌓는다."""
    import re as _re

    def api(경로, 방법="GET", 본문=None, raw=False):
        if 본경로 is not None:
            본경로.append(경로)
        m = _re.search(r"[?&]page=(\d+)", 경로)
        쪽 = int(m.group(1)) if m else 1
        m2 = _re.search(r"[?&]per_page=(\d+)", 경로)
        크기 = int(m2.group(1)) if m2 else 쪽크기
        return {"workflow_runs": 전부[(쪽 - 1) * 크기: 쪽 * 크기]}
    return api


class Test긴_연속실패:
    def test_30개가_넘어도_실제_연속_수를_센다(self, H, monkeypatch):
        """45회 실패 뒤 성공 — 옛 코드는 31 에서 멈췄다."""
        monkeypatch.setattr(H, "_api", _쪽나눠주는_api(_쪽(["failure"] * 45 + ["success"])))
        assert H.연속실패_횟수("r", "w", "999", "failure") == 46

    def test_한_쪽을_넘기는_연속도_센다(self, H, monkeypatch):
        monkeypatch.setattr(H, "_api", _쪽나눠주는_api(_쪽(["failure"] * 150 + ["success"])))
        assert H.연속실패_횟수("r", "w", "999", "failure") == 151

    def test_다_못_세면_이상이라고_표시한다(self, H, monkeypatch):
        """끝까지 성공을 못 만나면 센 만큼이 '하한'이다 — 정확한 수인 척하지 않는다."""
        monkeypatch.setattr(H, "_api", _쪽나눠주는_api(_쪽(["failure"] * 900)))
        r = H.연속실패_재기("r", "w", "999", "failure")
        assert r["이상"] is True and r["연속"] > 30
        s = H.문장_만들기("구좌순위 화면대조", "failure", r["연속"], "우리 코드 문제", "",
                      "", "", "", 이상=r["이상"])
        assert f"{r['연속']}회 이상" in s

    def test_30개_딱_맞게_끝나면_정확한_수다(self, H, monkeypatch):
        monkeypatch.setattr(H, "_api", _쪽나눠주는_api(_쪽(["failure"] * 30)))
        r = H.연속실패_재기("r", "w", "999", "failure")
        assert r == {**r, "연속": 31, "이상": False}

    def test_정기_실행이면_정기_실행만_센다(self, H, monkeypatch):
        """★③: push 실행 실패가 섞여 9/9 첫 정기 실패가 '11회 연속'으로 보고됐다."""
        본경로 = []
        monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
        monkeypatch.setattr(H, "_api", _쪽나눠주는_api(_쪽(["success"]), 본경로))
        H.연속실패_횟수("r", "w", "999", "failure")
        assert 본경로 and all("event=schedule" in p for p in 본경로), 본경로
        본경로.clear()
        H.직전이_실패였나("r", "w", "999")
        assert 본경로 and all("event=schedule" in p for p in 본경로), 본경로

    def test_직전_실패_시각을_돌려준다(self, H, monkeypatch):
        monkeypatch.setattr(H, "_api", _쪽나눠주는_api(
            _쪽(["failure"] * 3 + ["success"], 시각="2026-10-19T01:00:00Z")))
        assert H.연속실패_재기("r", "w", "999", "failure")["직전실패시각"] == "2026-10-19T01:00:00Z"


class Test긴_연속실패_전체흐름:
    def _스파이(self, H, monkeypatch):
        보낸것 = []
        monkeypatch.setattr(H, "텔레그램", lambda s: 보낸것.append(s) or True)
        monkeypatch.setattr(H, "이슈_열기", lambda *a: "http://issue")
        monkeypatch.setattr(H, "실패로그_원인", lambda *a: ("우리 코드 문제", "고쳐야 합니다", ""))
        return 보낸것

    def test_31회째_정기_실패도_그날_첫_실패면_알린다(self, H, monkeypatch, capsys):
        보낸것 = self._스파이(H, monkeypatch)
        monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
        monkeypatch.setattr(H, "_api", _쪽나눠주는_api(
            _쪽(["failure"] * 30, 시각="2020-01-01T00:00:00Z")))
        H.main(["--이름", "상위노출 순위검사", "--결과", "failure"])
        assert len(보낸것) == 1 and "31회 연속" in 보낸것[0], 보낸것
        assert "31회" in capsys.readouterr().out, "로그에 연속 수 줄이 있어야 다음 회차에 확인한다"

    def test_검사만_실패하는_작업은_문자를_안_보낸다(self, H, monkeypatch, capsys):
        """★2026-10-21 사장님 "이상한 보고가 너무 많아 진짜" — 검사만 실패하고 수집·보고는
        그대로 도는 곳은 Claude 가 고칠 일이라, 문자 대신 아침 건강 보고에 한 줄."""
        보낸것 = self._스파이(H, monkeypatch)
        monkeypatch.setenv("WORKFLOW_FILE", "slot-rank-audit.yml")
        monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
        monkeypatch.setattr(H, "_api", _쪽나눠주는_api(_쪽(["success"])))
        H.main(["--이름", "구좌순위 화면대조", "--결과", "failure"])
        assert 보낸것 == []
        assert "아침 건강 보고" in capsys.readouterr().out

    def test_검사만_실패하는_작업은_시간초과도_문자를_안_보낸다(self, H, monkeypatch):
        보낸것 = self._스파이(H, monkeypatch)
        monkeypatch.setenv("WORKFLOW_FILE", "slot-rank-audit.yml")
        monkeypatch.setenv("TIMEOUT_MIN", "10")
        monkeypatch.setattr(H, "_경과분", lambda *a: 99.0)
        H.main(["--이름", "구좌순위 화면대조", "--결과", "cancelled"])
        assert 보낸것 == []

    def test_수집_실패는_그대로_바로_보낸다(self, H, monkeypatch):
        보낸것 = self._스파이(H, monkeypatch)
        monkeypatch.setenv("WORKFLOW_FILE", "rank-check.yml")
        monkeypatch.setattr(H, "_api", _쪽나눠주는_api(_쪽(["success"])))
        H.main(["--이름", "상위노출 순위검사", "--결과", "failure"])
        assert len(보낸것) == 1


def test_아침보고로_옮긴_작업_목록():
    """판정표(2_판정표.md) '옮김' 칸 그대로. 수집·자료가 안 쌓이는 곳은 여기 넣지 않는다."""
    H = _load()
    assert set(H.아침보고로_옮김) == {
        "utm-guard.yml", "ext-guard.yml", "margin-guard.yml", "slot-rank-audit.yml",
        "cafe-folder-guard.yml", "cafe-weekly-audit.yml", "sheet-slim-guard.yml"}
    for 바로 in ("rank-check.yml", "clarity-daily.yml", "competitor-comments.yml",
                "obsidian-autolink.yml"):
        assert 바로 not in H.아침보고로_옮김


def test_옮긴_작업의_이름이_워크플로에_적힌_이름과_같다():
    """아침 보고가 이 이름으로 줄을 쓴다 — 워크플로 쪽 이름과 갈라지면 사장님은 두 이름을 보신다."""
    import re
    H = _load()
    p = 저장소루트 / ".github" / "workflows" / "slot-rank-audit.yml"
    m = re.search(r'자가치유\.py --이름 "([^"]+)"', p.read_text(encoding="utf-8"))
    assert m and m.group(1) == H.아침보고로_옮김["slot-rank-audit.yml"]


# ── GPT 교차 검토(10-21) 가 잡은 구멍 ─────────────────────────────────────────
def test_자정_직전에_정하고_자정_뒤에_끝난_회차_뒤로도_그날_첫_실패는_알린다(H, monkeypatch):
    """★GPT 2차 검토(10-21): 끝난 시각으로 보면 23:59:50 에 '어제 이미 알림 → 안 보냄'으로
    정하고 00:00:10 에 끝난 회차 뒤로, 그날 모든 회차가 '오늘 이미 실패가 있었다'로 보고
    하루가 통째로 조용했다. 시작 시각으로 본다 — 자정을 걸친 날 한 통 더 가는 것은 받아들인다."""
    from datetime import datetime, timezone
    monkeypatch.setattr(H, "_api", _쪽나눠주는_api([
        {"id": 1, "conclusion": "failure", "run_started_at": "2026-10-20T14:59:00Z",
         "updated_at": "2026-10-20T15:00:10Z"}] + _쪽(["failure"] * 5, 시작id=10)))
    셈 = H.연속실패_재기("r", "w", "999", "failure")
    assert 셈["직전실패시각"] == "2026-10-20T14:59:00Z"
    지금 = datetime(2026, 10, 20, 15, 5, tzinfo=timezone.utc)          # KST 10/21 00:05
    assert H.알릴차례인가(셈["연속"], 셈["직전실패시각"], 지금) is True



def test_오늘_시작한_실패가_앞에_있으면_같은_날_두_번째는_안_보낸다(H, monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr(H, "_api", _쪽나눠주는_api([
        {"id": 1, "conclusion": "failure", "run_started_at": "2026-10-20T15:01:00Z",
         "updated_at": "2026-10-20T15:02:00Z"}] + _쪽(["failure"] * 5, 시작id=10)))
    셈 = H.연속실패_재기("r", "w", "999", "failure")
    지금 = datetime(2026, 10, 20, 15, 6, tzinfo=timezone.utc)          # KST 10/21 00:06
    assert H.알릴차례인가(셈["연속"], 셈["직전실패시각"], 지금) is False


def test_첫_쪽을_못_읽으면_못_셌다고_말한다(H, monkeypatch):
    monkeypatch.setattr(H, "_api", lambda *a, **k: None)
    셈 = H.연속실패_재기("r", "w", "999", "failure")
    assert 셈["연속"] == 1 and 셈["못셈"] is True
    s = H.문장_만들기("상위노출 순위검사", "failure", 1, "알 수 없음", "", "", "", "", 못셈=True)
    assert "못 셌습니다" in s


def test_직전_실패_시각을_모르면_보낸다(H):
    """횟수 규칙으로 떨어지면 셈이 상한에 걸릴 때 또 영영 조용해진다."""
    assert H.알릴차례인가(301, "") is True
    assert H.알릴차례인가(300, "알수없는값") is True


def test_GOYU_NOTIFY_OFF_면_안_보낸다(H, monkeypatch):
    """이 사본에만 차단 스위치가 없었다(2026-10-21) — 손으로 돌려 보면 진짜 문자가 나갔다."""
    monkeypatch.setenv("GOYU_NOTIFY_OFF", "1")
    assert H.텔레그램("시험") is False


def test_조회_실패는_실패아님이_아니라_모름이다(H, monkeypatch):
    """팀 사본(2026-08-24)과 같게 — 못 본 것을 '평소 성공'으로 바꿔 말하지 않는다."""
    monkeypatch.setattr(H, "_api", lambda 경로, 방법="GET", **kw: None)
    assert H.직전이_실패였나("o/r", "w.yml", "1") is None
