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

    def test_실패_뒤_성공이면_복구를_알리고_이슈를_닫는다(self, H, monkeypatch):
        보낸것 = self._스파이(H, monkeypatch)
        닫힌것 = []
        monkeypatch.setattr(H, "_api", lambda *a, **k: _runs("failure", "failure"))
        monkeypatch.setattr(H, "이슈_닫기", lambda *a: 닫힌것.append(a))
        H.main(["--이름", "상위노출 순위검사", "--결과", "success"])
        assert len(보낸것) == 1 and "복구" in 보낸것[0]
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
        monkeypatch.setattr(H, "연속실패_횟수", lambda *a: 3)
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
        monkeypatch.setattr(H, "연속실패_횟수", lambda *a: 1)
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

    def test_그_뒤로는_띄엄띄엄(self, H):
        보냄 = [n for n in range(4, 40) if H.알릴차례인가(n)]
        assert 보냄 == [12, 24, 36], f"너무 자주 보낸다: {보냄}"


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
        assert m.group(1) in 저쪽.read_text(encoding="utf-8"), \
            "두 저장소의 자가치유.py 버전이 다르다 — 한쪽만 고쳤다"
