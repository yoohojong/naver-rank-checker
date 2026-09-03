# -*- coding: utf-8 -*-
"""'점검이 실제로 돌았나' 판정 검사 (2026-08-07 신설).

## 이 검사가 지키는 것
헛경보와 놓친 경보 둘 다 막는다. 둘 중 하나만 막으면 결국 둘 다 못 막는다 —
헛경보가 잦으면 사장님이 진짜 경보를 무시하게 되고, 그게 이 저장소가 이미 겪은 병이다.

## 특히 위험한 자리
① **회차 경계**: 점검은 KST 00/06/12/18 시 회차마다 두 갈래로 시도한다(외부크론 :00 + GitHub 크론).
   경계를 잘못 그으면 성공한 실행이 옆 회차로 새서, 멀쩡한데 '안 돌았다'가 된다.
② **아직 도는 중**: 큐에 갇힌 실행이 실재한다(08-07 06:00 실행이 9시간 넘게 queued).
   그걸 '안 돎'으로 읽으면 헛경보고, 그 실행은 나중에 성공한다.
③ **조회 실패 ≠ 안 돌았음**: gh 가 흔들린 걸 '점검이 멈췄다'로 읽으면 안 된다.
④ **배선**: 판정이 아무리 정확해도 문구까지·워크플로까지 이어지지 않으면 소용없다.
   ★1차 검증에서 배선 돌연변이 9종 중 8종이 통과했다 — 파이썬 배선 검사가 통째로 없었다.
"""
import os
import pathlib
import re
import subprocess
from datetime import datetime, timedelta, timezone

import pytest
import yaml

import scripts.가동확인 as G
from scripts.가동확인 import (
    KST,
    build_alert,
    build_report,
    build_생존신고,
    보고통로_상태,
    실행이력,
    안돎,
    보류,
    정상,
    최근_끝난_회차,
    최대_연속_결측,
    판정,
    회차_라벨,
    회차_시작,
)

저장소루트 = pathlib.Path(__file__).resolve().parents[2]
WF = 저장소루트 / ".github/workflows/가동확인.yml"


def _kst(월, 일, 시, 분=0) -> datetime:
    return datetime(2026, 월, 일, 시, 분, tzinfo=KST)


def _실행(때: datetime, 결론="success", 상태="completed") -> dict:
    return {"createdAt": 때.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "conclusion": 결론, "status": 상태}


def _판정시각들(날=None) -> list:
    """라이브 워크플로의 cron 을 그날의 **KST 판정 시각**으로 편다.

    ★검사가 시각을 따로 적어 두면 라이브와 갈라진다 — 실제로 갈라져 있었다.
      검사는 '지금'을 07:00·08:00 으로 넣어 통과했는데 라이브 판정은 09:00 하나뿐이라,
      **검사가 통과하는 상태를 라이브가 한 번도 안 만들었다.** 그래서 파일에서 읽는다.
    """
    날 = 날 or datetime(2026, 8, 7, tzinfo=timezone.utc)
    d = yaml.safe_load(WF.read_text(encoding="utf-8"))
    트리거 = d.get("on") or d.get(True)
    시각 = []
    for c in 트리거["schedule"]:
        분, 시들 = c["cron"].split()[0], c["cron"].split()[1]
        for h in 시들.split(","):
            시각.append(날.replace(hour=int(h), minute=int(분)).astimezone(KST))
    return sorted(시각)


# ── ① 회차 경계 ──────────────────────────────────────────────────────────────

class Test회차_경계:
    @pytest.mark.parametrize("시,기대", [
        (0, 0), (5, 0), (6, 6), (11, 6), (12, 12), (17, 12), (18, 18), (23, 18),
    ])
    def test_어느_회차에_속하나(self, 시, 기대):
        assert 회차_시작(_kst(8, 6, 시)).hour == 기대

    def test_경계_직전은_앞_회차(self):
        assert 회차_시작(_kst(8, 6, 5, 59)).hour == 0
        assert 회차_시작(_kst(8, 6, 6, 0)).hour == 6

    def test_라벨이_구간임을_스스로_말한다(self):
        """'12시' 는 정오로 읽힌다 — 6시간 덩어리라는 걸 라벨이 밝혀야 한다."""
        assert 회차_라벨(_kst(8, 6, 12)) == "12~18시"
        assert 회차_라벨(_kst(8, 6, 18)) == "18~00시"

    def test_UTC로_줘도_KST로_읽는다(self):
        """실행 이력은 UTC 로 온다. 시간대를 놓치면 회차가 통째로 밀린다."""
        시작 = 회차_시작(datetime(2026, 8, 6, 15, 30, tzinfo=timezone.utc))  # KST 8/7 00:30
        assert 시작.hour == 0 and 시작.astimezone(KST).day == 7

    def test_회차_길이는_6시간(self):
        """★상수를 바꾸면 경계가 통째로 어긋난다 — 상수와 실제 경계가 한 몸인지 본다."""
        assert G.회차_길이 == timedelta(hours=6)
        하루 = {회차_시작(_kst(8, 6, h)).hour for h in range(24)}
        assert 하루 == {0, 6, 12, 18}, f"회차 경계가 어긋났다: {sorted(하루)}"


class Test끝난_회차만_판정한다:
    def test_진행중인_회차는_안_센다(self):
        회차들 = 최근_끝난_회차(_kst(8, 7, 9), 개수=4)
        assert _kst(8, 7, 6) not in 회차들, "진행 중인 회차를 판정했다"
        assert 회차들 == [_kst(8, 6, 6), _kst(8, 6, 12), _kst(8, 6, 18), _kst(8, 7, 0)]

    def test_기본값으로_불러도_네_회차(self):
        """★main() 은 기본값을 쓴다. 검사가 매번 명시로 넘기면 기본값은 안 지켜진다."""
        assert len(최근_끝난_회차(_kst(8, 7, 9))) == 4

    def test_오래된_것부터_최근_순(self):
        회차들 = 최근_끝난_회차(_kst(8, 7, 9), 개수=4)
        assert 회차들 == sorted(회차들)


# ── ② 정상 / 보류 / 안돎 ─────────────────────────────────────────────────────

class Test세_가지_상태:
    def _회차4(self):
        return [_kst(8, 6, 6), _kst(8, 6, 12), _kst(8, 6, 18), _kst(8, 7, 0)]

    # 마지막 회차가 끝난 직후. 시계를 안 주면 '지금'이 실제 현재라서
    # 보류_한계(12시간)를 넘겨 전부 안돎이 된다 — 상태 구분 검사가 헛돈다.
    지금 = _kst(8, 7, 7)

    def test_성공이_하나면_정상(self):
        실행 = [_실행(_kst(8, 6, 6, 7), "failure"), _실행(_kst(8, 6, 6, 27), "success")]
        assert 판정(실행, self._회차4(), self.지금)[0]["상태"] == 정상

    def test_아직_도는_중이면_보류지_안돎이_아니다(self):
        """★실측: 08-07 06:00 실행이 9시간 넘게 queued 였다.

        그걸 '안 돎'으로 읽으면 헛경보가 나가고, 정작 그 실행은 나중에 성공한다.
        """
        실행 = [_실행(_kst(8, 7, 0, 5), "", "queued")]   # 방금 끝난 회차
        r = 판정(실행, self._회차4(), self.지금)[3]
        assert r["상태"] == 보류, "큐에 갇힌 실행을 '안 돎'으로 읽었다 — 헛경보 난다"
        assert r["진행중"] == 1

    def test_실패했는데_다른_하나가_도는_중이면_보류(self):
        실행 = [_실행(_kst(8, 7, 0, 7), "failure"), _실행(_kst(8, 7, 0, 27), "", "in_progress")]
        assert 판정(실행, self._회차4(), self.지금)[3]["상태"] == 보류

    def test_다_끝났는데_성공이_없으면_안돎(self):
        실행 = [_실행(_kst(8, 6, 6, 7), "failure"), _실행(_kst(8, 6, 6, 27), "cancelled")]
        assert 판정(실행, self._회차4(), self.지금)[0]["상태"] == 안돎

    def test_기록이_아예_없으면_안돎(self):
        """★07-23·07-28 처럼 조용히 사라진 경우."""
        결과 = 판정([], self._회차4(), self.지금)
        assert all(r["상태"] == 안돎 for r in 결과)

    def test_성공이_있으면_도는_게_있어도_정상(self):
        실행 = [_실행(_kst(8, 6, 6, 0)), _실행(_kst(8, 6, 6, 27), "", "queued")]
        assert 판정(실행, self._회차4(), self.지금)[0]["상태"] == 정상

    def test_실행_건수로_세지_않는다(self):
        """★회차마다 1번씩만 돌아도 정상이다. 건수로 세면 헛경보가 난다."""
        실행 = [_실행(s + timedelta(minutes=7)) for s in self._회차4()]
        assert all(r["상태"] == 정상 for r in 판정(실행, self._회차4(), self.지금))

    def test_success_만_성공으로_친다(self):
        for 결론 in ("failure", "cancelled", "timed_out", "startup_failure", "skipped"):
            실행 = [_실행(_kst(8, 6, 6, 7), 결론)]
            assert 판정(실행, self._회차4(), self.지금)[0]["상태"] == 안돎, f"{결론} 을 성공으로 읽었다"

    def test_옆_회차_성공을_끌어오지_않는다(self):
        실행 = [_실행(_kst(8, 6, 6, 7))]
        assert [r["상태"] for r in 판정(실행, self._회차4(), self.지금)] == [정상, 안돎, 안돎, 안돎]

    def test_시간대_없는_기록도_안_터진다(self):
        결과 = 판정([{"createdAt": "", "conclusion": "success"}, {"conclusion": "success"}],
                   self._회차4(), self.지금)
        assert all(r["상태"] == 안돎 for r in 결과)

    def test_created_at_스네이크도_읽는다(self):
        실행 = [{"created_at": _kst(8, 6, 6, 7).astimezone(timezone.utc)
                 .isoformat().replace("+00:00", "Z"),
                 "conclusion": "success", "status": "completed"}]
        assert 판정(실행, self._회차4(), self.지금)[0]["상태"] == 정상

    def test_연속_결측을_센다(self):
        def 결과(상태들):
            return [{"상태": s} for s in 상태들]
        assert 최대_연속_결측(결과([정상, 안돎, 안돎, 정상])) == 2
        assert 최대_연속_결측(결과([안돎, 정상, 안돎, 정상])) == 1
        assert 최대_연속_결측(결과([정상] * 4)) == 0


# ── ③ 조회 실패는 '안 돌았음'이 아니다 ────────────────────────────────────────

class Test못_읽은_것과_안_돈_것은_다르다:
    def test_gh가_실패하면_예외를_던진다(self, monkeypatch):
        class 실패:
            returncode, stdout, stderr = 1, "", "gh: not logged in"
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: 실패())
        with pytest.raises(RuntimeError):
            실행이력("o/r", "rank-check.yml")

    def test_gh가_물리면_시간초과로_끝낸다(self, monkeypatch):
        """★timeout 이 없으면 예약작업 제한에 걸려 로그도 문자도 없이 죽는다."""
        def 물림(*a, **k):
            raise subprocess.TimeoutExpired(cmd="gh", timeout=k.get("timeout", 60))
        monkeypatch.setattr(subprocess, "run", 물림)
        with pytest.raises(RuntimeError):
            실행이력("o/r", "rank-check.yml")

    def test_조회_한도가_판정_구간을_덮는다(self):
        """★한도가 모자라면 오래된 회차의 실행이 목록에서 잘려 '안 돌았다'가 된다.

        조용히 헛경보가 되는 자리다 — 잘린 건지 안 돈 건지 구분할 방법이 없다.
        실측 하루 8~12건이고 4회차(24시간)를 판정하니, 하루치의 2배는 있어야 안전하다.
        """
        import inspect
        기본한도 = inspect.signature(실행이력).parameters["개수"].default
        하루_최대_실행 = 12
        판정_일수 = (4 * G.회차_길이).total_seconds() / 86400
        필요 = 하루_최대_실행 * 판정_일수 * 2
        assert 기본한도 >= 필요, (
            f"조회 한도 {기본한도} 가 판정 구간을 못 덮는다(최소 {필요:.0f} 필요) — "
            "오래된 회차가 잘려서 '안 돌았다'로 읽힌다")

    def test_조회에_시간제한을_건다(self, monkeypatch):
        받은 = {}
        class OK:
            returncode, stdout, stderr = 0, "[]", ""
        monkeypatch.setattr(subprocess, "run",
                            lambda *a, **k: (받은.update(k), OK())[1])
        실행이력("o/r", "rank-check.yml")
        assert 받은.get("timeout"), "시간제한 없이 gh 를 부른다 — 물리면 감시가 통째로 멈춘다"

    def test_조회_실패는_안_돌았다고_말하지_않는다(self, monkeypatch):
        보낸것 = []
        monkeypatch.setattr(G, "실행이력",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        monkeypatch.setattr(G, "send_telegram", lambda t, **k: 보낸것.append(t) or True)
        assert G.main(["--모드", "보고"]) == 1, "조회를 못 했는데 성공으로 끝냈다"
        assert len(보낸것) == 1, "조회 실패를 조용히 넘겼다"
        assert "확인하지 못했습니다" in 보낸것[0]
        assert "안 돌았습니다" not in 보낸것[0]

    def test_사장님께_영어_예외이름을_안_보낸다(self, monkeypatch):
        보낸것 = []
        monkeypatch.setattr(G, "실행이력",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        monkeypatch.setattr(G, "send_telegram", lambda t, **k: 보낸것.append(t) or True)
        G.main(["--모드", "보고"])
        assert not re.search(r"[A-Za-z]{4,}Error", 보낸것[0]), f"영어 예외명이 샜다: {보낸것[0]}"


# ── ④ 보고 통로 상태 (1차 검증에서 검사가 0건이던 자리) ──────────────────────

class Test보고통로_상태:
    """★여기가 통째로 검사 없이 나갔고, 그래서 fail-open 이 살아 있었다.

    실제로 재현됐다 — 보고 워크플로가 GitHub 에 존재하지도 않는데(404)
    경보 통로가 '이상 없음'이라고 말했다.
    """

    def test_최근에_돌았으면_정상(self, monkeypatch):
        지금 = datetime(2026, 8, 7, 3, tzinfo=timezone.utc)
        monkeypatch.setattr(G, "실행이력", lambda *a, **k: [
            {"createdAt": (지금 - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
             "conclusion": "success", "status": "completed"}])
        assert 보고통로_상태("o/r", 지금) == 정상

    def test_하루_넘게_안_돌았으면_안돎(self, monkeypatch):
        지금 = datetime(2026, 8, 7, 3, tzinfo=timezone.utc)
        monkeypatch.setattr(G, "실행이력", lambda *a, **k: [
            {"createdAt": (지금 - timedelta(hours=40)).isoformat().replace("+00:00", "Z")}])
        assert 보고통로_상태("o/r", 지금) == 안돎

    def test_기록이_아예_없으면_안돎(self, monkeypatch):
        monkeypatch.setattr(G, "실행이력", lambda *a, **k: [])
        assert 보고통로_상태("o/r", datetime.now(timezone.utc)) == 안돎

    def test_조회_실패는_못읽음이지_정상이_아니다(self, monkeypatch):
        """★fail-open 금지. 워크플로가 지워지면 조회가 404 로 실패한다 —
        그게 바로 '보고 통로가 죽었다'는 신호다. 정상으로 뭉개면 아무도 모른다."""
        monkeypatch.setattr(G, "실행이력",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("404")))
        assert 보고통로_상태("o/r", datetime.now(timezone.utc)) == "못읽음", \
            "못 읽은 것을 '정상'으로 삼켰다 — 감시가 사라져도 조용하다"

    def test_보고_워크플로_이름이_실제_파일과_맞는다(self):
        """★상수가 실제 파일과 어긋나면 조회가 영원히 404 = 영원히 '못읽음'."""
        assert (저장소루트 / ".github/workflows" / G.보고_워크플로).exists(), \
            f"보고_워크플로={G.보고_워크플로} 인데 그런 파일이 없다"

    def test_점검_워크플로_이름이_실제_파일과_맞는다(self):
        assert (저장소루트 / ".github/workflows" / G.점검_워크플로).exists(), \
            f"점검_워크플로={G.점검_워크플로} 인데 그런 파일이 없다"


# ── ⑤ 문구 ──────────────────────────────────────────────────────────────────

def _결과(상태들):
    return [{"회차": f"{h:02d}~{(h+6) % 24:02d}시", "시작": _kst(8, 6, h), "상태": s,
             "성공": int(s == 정상), "시도": 1, "진행중": int(s == 보류), "산것": s == 정상}
            for h, s in zip((6, 12, 18, 0), 상태들)]


class Test보고_문구:
    """★2026-09-03 계약이 바뀌었다 (사장님 확정).

    원문: "몇번 정상이 아니라 비정상 뜨는 즉시 알려달라고."
    · 세는 문구('4번 중 3번 정상')를 없앤다.
    · 정상이면 **한 통도 안 보낸다** — 빈 문자열이 정답이다.
    · 매일 오는 살아있음 한 줄은 팀프로젝트 쪽이 맡는다. 여기서 만들지 않는다.
    """

    def test_다_돌면_아무_말도_안_한다(self):
        assert build_report(_결과([정상] * 4)) == "", \
            "정상인데 문자를 보냈다 — 사장님이 없애라고 하신 그 문구다"

    def test_세는_문구가_어디에도_없다(self):
        """'4번 중 3번 정상' 류가 살아 있으면 사장님 지시를 어긴 것이다."""
        for 상태들 in ([정상] * 4, [정상, 안돎, 정상, 정상], [안돎] * 4, [보류] * 4):
            문구 = build_report(_결과(상태들))
            assert "번 정상" not in 문구, f"세는 문구가 남았다: {문구}"

    def test_아직_도는_중이면_조용하다(self):
        """사장님 원문: '실행중이라면 문제가 없음.' — 지연은 실패가 아니다."""
        assert build_report(_결과([정상, 보류, 정상, 정상])) == ""

    def test_안_돈_회차가_있으면_빨강으로_바로_말한다(self):
        문구 = build_report(_결과([정상, 안돎, 정상, 정상]))
        assert "🔴" in 문구 and "12~18시" in 문구

    def test_둘_이상_빠지면_빨강(self):
        assert "🔴" in build_report(_결과([정상, 안돎, 안돎, 정상]))

    def test_이미_알린_회차는_다시_안_알린다(self):
        """★6시간마다 판정하니 같은 회차를 네 번 본다. 그대로면 문자가 서너 통 간다."""
        결과 = _결과([정상, 안돎, 정상, 정상])
        assert build_report(결과, 새것=set()) == ""
        assert "🔴" in build_report(결과, 새것={"12~18시"})

    def test_전부_보류면_그건_조용히_넘기지_않는다(self):
        """정상이 하나도 없는데 침묵하면 러너 기근 날 무음이 된다(2026-08-07 실측)."""
        문구 = build_report(_결과([보류] * 4))
        assert "🔴" in 문구 and "안 끝나고" in 문구

    def test_일부_결측은_기록이_남아있다고_말한다(self):
        """★정정: 영구 기록은 하루 1벌이라(src/archive.py 날짜별 멱등)
        회차 하나 빠져도 그날 기록은 안 사라진다. '다시 못 잽니다'는 거짓말이었다."""
        문구 = build_report(_결과([정상, 안돎, 정상, 정상]))
        assert "남아 있을 가능성이 높습니다" in 문구
        assert "안 남았을 수 있습니다" not in 문구
        assert "12시간 전 것" in 문구

    def test_연속으로_빠지면_더_옛것이라고_말한다(self):
        문구 = build_report(_결과([정상, 안돎, 안돎, 정상]))
        assert "18시간 전 것" in 문구

    def test_하루가_통째로_빠져야_기록이_없다고_말한다(self):
        문구 = build_report(_결과([안돎] * 4))
        assert "안 남았을 수 있습니다" in 문구
        assert "확인이 필요해요" in 문구

    def test_정상이면_군더더기가_없다(self):
        문구 = build_report(_결과([정상] * 4))
        assert "걸른" not in 문구 and "옛것" not in 문구

    def test_판정_값은_문자와_따로_남는다(self):
        """★살아있음 한 줄은 팀프로젝트가 만든다 — 여기서는 값만 넘긴다."""
        from scripts.가동확인 import 결과_한줄
        한줄 = 결과_한줄(_결과([정상, 안돎, 보류, 정상]))
        assert "12~18시" in 한줄 and 안돎 in 한줄


class Test경보_문구:
    def test_다_정상이면_조용하다(self):
        assert build_alert(_결과([정상] * 4), 보고통로=정상) == ""

    def test_보류만_있으면_조용하다(self):
        """아직 판정이 안 된 것으로 사장님을 깨우지 않는다."""
        assert build_alert(_결과([정상, 보류, 정상, 정상]), 보고통로=정상) == ""

    def test_회차가_비면_운다(self):
        문구 = build_alert(_결과([정상, 안돎, 정상, 정상]), 보고통로=정상)
        assert "🔴" in 문구 and "12~18시" in 문구

    def test_보고가_안_돌면_회차가_멀쩡해도_운다(self):
        """★GitHub 이 통째로 멈춘 날 — 이 다리만 살아 있다."""
        문구 = build_alert(_결과([정상] * 4), 보고통로=안돎)
        assert 문구 and "일일 보고 자체가" in 문구 and "PC" in 문구

    def test_보고_상태를_못_읽어도_운다(self):
        """★fail-open 이 살아 있던 자리. 조용하면 감시가 사라진 걸 아무도 모른다."""
        문구 = build_alert(_결과([정상] * 4), 보고통로="못읽음")
        assert 문구, "보고 통로 상태를 못 읽었는데 조용했다"
        assert "확인하지 못했습니다" in 문구

    def test_둘_다_문제면_둘_다_말한다(self):
        문구 = build_alert(_결과([안돎] * 4), 보고통로=안돎)
        assert "안 돌았습니다" in 문구 and "일일 보고 자체가" in 문구

    def test_생존신고는_조치가_필요없다고_말한다(self):
        문구 = build_생존신고()
        assert "살아있습니다" in 문구 and "조치는 필요 없습니다" in 문구


class Test경보_배선:
    """★판정이 맞아도 main() 이 안 부르면 소용없다. 1차 검증에서 이 배선이 통째로 안 지켜졌다."""

    def _돌린다(self, monkeypatch, 실행, 보고상태):
        보낸것 = []
        monkeypatch.setattr(G, "실행이력", lambda *a, **k: 실행)
        monkeypatch.setattr(G, "보고통로_상태", lambda *a, **k: 보고상태)
        monkeypatch.setattr(G, "send_telegram", lambda t, **k: 보낸것.append(t) or True)
        rc = G.main(["--모드", "경보"])
        return rc, 보낸것

    def test_경보모드가_보고통로_상태를_실제로_본다(self, monkeypatch):
        """★이 호출을 통째로 지워도 1차 검사는 전부 통과했다."""
        지금 = datetime.now(timezone.utc)
        실행 = [_실행(회차_시작(지금) - timedelta(hours=6 * i) + timedelta(hours=1))
                for i in range(1, 5)]
        rc, 보낸것 = self._돌린다(monkeypatch, 실행, "못읽음")
        assert 보낸것, "보고 통로 상태를 안 보고 조용히 끝냈다"
        assert "확인하지 못했습니다" in 보낸것[0]

    def test_다_정상이면_경보모드는_조용하고_0으로_끝난다(self, monkeypatch):
        지금 = datetime.now(timezone.utc)
        실행 = [_실행(회차_시작(지금) - timedelta(hours=6 * i) + timedelta(hours=1))
                for i in range(1, 5)]
        rc, 보낸것 = self._돌린다(monkeypatch, 실행, 정상)
        assert rc == 0 and 보낸것 == []

    def test_보고모드는_정상이면_한_통도_안_보낸다(self, monkeypatch):
        """★2026-09-03 사장님 확정으로 뒤집힌 계약.

        원문: "몇번 정상이 아니라 비정상 뜨는 즉시 알려달라고."
        판정은 6시간마다 하지만 정상일 땐 조용하다 — 그래서 문자가 늘지 않는다.
        살아있음 한 줄은 팀프로젝트 쪽이 맡는다.
        """
        지금 = datetime.now(timezone.utc)
        실행 = [_실행(회차_시작(지금) - timedelta(hours=6 * i) + timedelta(hours=1))
                for i in range(1, 5)]
        보낸것 = []
        monkeypatch.setattr(G, "실행이력", lambda *a, **k: 실행)
        monkeypatch.setattr(G, "send_telegram", lambda t, **k: 보낸것.append(t) or True)
        assert G.main(["--모드", "보고"]) == 0
        assert 보낸것 == [], f"정상인데 문자가 나갔다: {보낸것}"

    def test_보고모드도_판정_값은_남긴다(self, monkeypatch, tmp_path):
        """조용해도 **아무것도 안 남기면** 팀프로젝트가 읽을 게 없다."""
        지금 = datetime.now(timezone.utc)
        실행 = [_실행(회차_시작(지금) - timedelta(hours=6 * i) + timedelta(hours=1))
                for i in range(1, 5)]
        요약 = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(요약))
        monkeypatch.setattr(G, "실행이력", lambda *a, **k: 실행)
        monkeypatch.setattr(G, "send_telegram", lambda t, **k: True)
        assert G.main(["--모드", "보고"]) == 0
        assert "[가동확인-결과]" in 요약.read_text(encoding="utf-8")

    def test_발송_실패하면_1로_끝낸다(self, monkeypatch):
        monkeypatch.setattr(G, "실행이력", lambda *a, **k: [])
        monkeypatch.setattr(G, "send_telegram", lambda t, **k: False)
        assert G.main(["--모드", "보고"]) == 1

    def test_생존신고_모드가_있다(self, monkeypatch):
        보낸것 = []
        monkeypatch.setattr(G, "send_telegram", lambda t, **k: 보낸것.append(t) or True)
        assert G.main(["--모드", "생존신고"]) == 0
        assert len(보낸것) == 1 and "살아있습니다" in 보낸것[0]


# ── ⑥ 워크플로 배선 ─────────────────────────────────────────────────────────

class Test워크플로_배선:
    """★배선은 파이썬 검사로 안 지켜진다 — 워치독에서 이미 겪었다."""

    @pytest.fixture(scope="class")
    def wf(self):
        return yaml.safe_load(WF.read_text(encoding="utf-8"))

    def test_job_과_input_이름이_ASCII다(self, wf):
        """★한글 job id 는 GitHub 스키마(^[_a-zA-Z][a-zA-Z0-9_-]*$) 위반이라
        워크플로가 아예 안 뜬다 — '감시를 걸었다'고 보고한 뒤 아무 일도 안 일어난다."""
        규칙 = re.compile(r"^[_a-zA-Z][a-zA-Z0-9_-]*$")
        for jid in wf["jobs"]:
            assert 규칙.match(jid), f"job id 가 규칙 위반: {jid!r}"
        트리거 = wf.get("on") or wf.get(True)
        for iid in (트리거.get("workflow_dispatch") or {}).get("inputs", {}):
            assert 규칙.match(iid), f"input id 가 규칙 위반: {iid!r}"

    def test_여섯시간마다_돈다(self, wf):
        """★하루 한 번이면 '안 돈 것'을 최대 21시간 뒤에 안다(2026-09-03 사장님 지적).

        회차가 6시간이므로 판정도 6시간마다여야 회차 하나에 판정 한 번이 맞물린다.
        """
        assert len(_판정시각들()) == 4, \
            f"하루 판정 횟수가 4번이 아니다: {[str(t) for t in _판정시각들()]}"

    def test_수동_실행도_된다(self, wf):
        트리거 = wf.get("on") or wf.get(True)
        assert "workflow_dispatch" in 트리거

    def test_실행이력을_읽을_권한이_있다(self, wf):
        assert wf["permissions"].get("actions") == "read"

    def test_설치_단계가_없다(self, wf):
        """pip install 이 있으면 그게 깨질 때 보고가 통째로 안 나간다."""
        본문 = "\n".join(str(s.get("run", "")) for s in self._스텝(wf))
        assert "pip install" not in 본문

    def test_보고_모드로_부른다(self, wf):
        """--모드 경보 로 잘못 부르면 자기가 살아있는지를 자기한테 묻게 된다.

        경보 모드는 '이 워크플로가 오늘 돌았나'(보고통로_상태)를 같이 보는데,
        그건 사장님 PC 쪽 다리가 할 일이다 — 여기서 부르면 늘 '나는 지금 돌고 있다'다.
        (정상일 때 조용한 것은 이제 두 모드가 같다 — 2026-09-03 사장님 확정.)
        """
        스텝 = [s for s in self._스텝(wf) if s.get("id") == "report"][0]
        assert "--모드 보고" in 스텝["run"]

    def test_보고가_실패하면_최후수단이_받는다(self, wf):
        후보 = [s for s in self._스텝(wf) if "steps.report.outcome" in str(s.get("if", ""))]
        assert 후보, "보고가 못 나갔을 때 대신 알릴 통로가 없다"
        run = "\n".join(L for L in 후보[0]["run"].splitlines()
                        if not L.strip().startswith("#"))
        assert "curl" in run and "--fail" in run

    def test_보고_스텝이_잡을_죽이지_않는다(self, wf):
        스텝 = [s for s in self._스텝(wf) if s.get("id") == "report"][0]
        assert 스텝["continue-on-error"] is True

    @staticmethod
    def _스텝(wf):
        (잡,) = wf["jobs"].values()
        return 잡["steps"]


# ── ⑦ 2차 검증에서 새로 드러난 것 ────────────────────────────────────────────

class Test보류가_면죄부가_되면_안된다:
    """★2차 검증 CRITICAL. 이 장치가 존재하는 이유인 '러너 기근' 날에 무음이었다.

    실측 재현: 네 회차가 전부 큐에 갇히면 → 상태 전부 보류 →
      보고 '🟢 4번 중 0번 정상', 경보 '' (침묵).
    판정 창은 24시간을 겹침 없이 자르므로 그 회차는 두 번 다시 안 본다 =
    영원히 보류가 아니라 **영원히 사면**이다.
    """

    def _큐(self, 회차들):
        return [{"createdAt": (c + timedelta(minutes=5)).astimezone(timezone.utc)
                 .isoformat().replace("+00:00", "Z"),
                 "conclusion": "", "status": "queued"} for c in 회차들]

    def test_너무_오래_큐에_있으면_안돎으로_본다(self):
        """실측: run 31128005421 이 12시간 넘게 queued 였다."""
        회차들 = [_kst(8, 6, 6), _kst(8, 6, 12), _kst(8, 6, 18), _kst(8, 7, 0)]
        지금 = _kst(8, 7, 23)   # 마지막 회차가 끝난 지 17시간
        결과 = 판정(self._큐(회차들), 회차들, 지금)
        assert 결과[0]["상태"] == 안돎, "무한 대기를 허용하면 침묵과 같다"

    def test_아직_한계_안이면_보류_그대로(self):
        회차들 = [_kst(8, 7, 0)]
        지금 = _kst(8, 7, 8)   # 회차 끝난 지 2시간
        assert 판정(self._큐(회차들), 회차들, 지금)[0]["상태"] == 보류

    def test_전부_보류면_초록이_아니다(self):
        문구 = build_report(_결과([보류] * 4))
        assert "🟢" not in 문구, "0번 정상인데 초록불이 나갔다"
        assert "🔴" in 문구

    def test_전부_보류면_경보가_운다(self):
        """★조용히 넘기면 러너 기근 날 보고도 경보도 무음이 된다."""
        문구 = build_alert(_결과([보류] * 4), 보고통로=정상)
        assert 문구, "정상이 하나도 없는데 침묵했다"
        assert "안 끝났습니다" in 문구

    def test_하나라도_정상이면_보류는_조용하다(self):
        """과잉 경보 금지 — 하나라도 살아 있으면 시트는 갱신된다."""
        assert build_alert(_결과([정상, 보류, 보류, 보류]), 보고통로=정상) == ""

    def test_신선도는_보류도_갱신_안됨으로_센다(self):
        문구 = build_report(_결과([정상, 안돎, 보류, 안돎]))
        assert "24시간 전" in 문구, "보류를 건너뛰고 세면 실제보다 신선해 보인다"


class Test보고통로는_성공만_정상이다:
    """★2차 검증 CRITICAL. '실행이 있었나'만 봐서 큐에 갇히거나 실패한 보고를
    정상으로 읽었다. 그러면 문자가 0통인데 PC 도 조용해진다 = 전면 무음."""

    def _상태(self, monkeypatch, conclusion, status="completed", 시간전=1):
        지금 = datetime(2026, 8, 7, 3, tzinfo=timezone.utc)
        monkeypatch.setattr(G, "실행이력", lambda *a, **k: [{
            "createdAt": (지금 - timedelta(hours=시간전)).isoformat().replace("+00:00", "Z"),
            "conclusion": conclusion, "status": status}])
        return 보고통로_상태("o/r", 지금)

    def test_성공이면_정상(self, monkeypatch):
        assert self._상태(monkeypatch, "success") == 정상

    def test_큐에_갇혔으면_안돎(self, monkeypatch):
        assert self._상태(monkeypatch, "", "queued") == 안돎, \
            "보고가 시작만 하고 안 끝났는데 정상으로 읽었다 — 문자는 0통이다"

    def test_실패했으면_안돎(self, monkeypatch):
        assert self._상태(monkeypatch, "failure") == 안돎

    def test_성공했어도_너무_오래됐으면_안돎(self, monkeypatch):
        assert self._상태(monkeypatch, "success", 시간전=40) == 안돎


class Testgh를_어떻게_부르는가:
    """★2차 검증: gh argv 를 아무도 안 봐서, 감시 대상이 바뀌어도 전부 초록이었다.

    파이썬 로직만 검사하면 '바깥과 맞닿는 줄'이 무방비다 — 1차 사고와 같은 모양.
    """

    def _argv(self, monkeypatch):
        받은 = {}
        class OK:
            returncode, stdout, stderr = 0, "[]", ""
        def 가로채기(cmd, **k):
            받은["cmd"] = cmd
            받은.update(k)
            return OK()
        monkeypatch.setattr(subprocess, "run", 가로채기)
        return 받은

    def test_점검_워크플로를_본다(self, monkeypatch):
        받은 = self._argv(monkeypatch)
        monkeypatch.setattr(G, "send_telegram", lambda t, **k: True)
        G.main(["--모드", "보고", "--발송안함"])
        assert G.점검_워크플로 in 받은["cmd"], \
            f"감시 대상이 바뀌었다: {받은['cmd']}"

    def test_필요한_필드를_다_요청한다(self, monkeypatch):
        받은 = self._argv(monkeypatch)
        실행이력("o/r", "rank-check.yml")
        json인자 = 받은["cmd"][받은["cmd"].index("--json") + 1]
        for 필드 in ("createdAt", "conclusion", "status"):
            assert 필드 in json인자, f"{필드} 를 안 받아오면 판정이 무너진다"

    def test_저장소와_한도를_넘긴다(self, monkeypatch):
        받은 = self._argv(monkeypatch)
        실행이력("o/r", "rank-check.yml", 개수=40)
        assert "--repo" in 받은["cmd"] and "o/r" in 받은["cmd"]
        assert "--limit" in 받은["cmd"] and "40" in 받은["cmd"]

    def test_시간제한이_충분히_길다(self, monkeypatch):
        받은 = self._argv(monkeypatch)
        실행이력("o/r", "rank-check.yml")
        assert 받은.get("timeout", 0) >= 30, "너무 짧으면 정상인데 조회 실패가 된다"


class Test화면_인코딩이_경보를_죽이지_않는다:
    """★cp949 화면에서 print("🔴...") 가 터지면 그 아래 발송까지 못 간다 = 문자 0통.

    예약작업 인자의 `-X utf8` 에 기대면, 누가 예약작업을 다시 만드는 순간
    조용히 모든 경보가 사라진다. 그래서 코드 안에서 스스로 막는다.
    """

    def test_cp949_화면에서도_이모지를_찍는다(self):
        import subprocess as sp
        import sys as _sys
        코드 = ("import sys; sys.path.insert(0, r'%s'); "
                "import scripts.가동확인; print('🔴 경보 문구')" % 저장소루트)
        환경 = {**os.environ, "PYTHONIOENCODING": "cp949"}
        환경.pop("PYTHONUTF8", None)
        r = sp.run([_sys.executable, "-c", 코드], capture_output=True,
                   cwd=str(저장소루트), env=환경)
        assert r.returncode == 0, (
            "cp949 화면에서 경보 문구를 찍다가 죽었다 — 그 아래 발송까지 못 간다:\n"
            + r.stderr.decode("utf-8", "replace")[-400:])


class Test보류_한계가_라이브_판정시각과_맞는가:
    """★검사와 라이브가 갈라져 있던 자리다 (2026-09-03).

    예전 검사는 '지금'을 07:00·08:00 으로 넣어 보류를 만들어 냈는데, **라이브 판정은
    09:00 하나뿐**이었다. 그 시각에서 네 회차의 '끝난 뒤 경과'는 21h/15h/9h/3h 라
    가장 짧은 3h 도 옛 한계(2h)를 넘겼다 — 즉 라이브에서는 '보류'가 **한 번도**
    만들어질 수 없었고, 8/7 에 9시간 기다렸다 성공한 회차가 '안 돌았음'으로 찍혔다.
    검사는 초록인데 라이브는 늘 틀린 상태였다.

    그래서 이제 시각을 검사에 적어 두지 않는다 — **워크플로 cron 에서 직접 계산한다.**
    한쪽만 바꾸면 여기가 빨개진다.
    """

    def _경과시간들(self):
        """판정 시각마다, 그때 판정하는 네 회차의 '끝난 뒤 경과'(시간)."""
        값 = set()
        for t in _판정시각들():
            for c in 최근_끝난_회차(t):
                값.add(round((t - (c + G.회차_길이)).total_seconds() / 3600, 2))
        return sorted(값)

    def test_첫_판정은_봐주고_다음_판정이_잡는다(self):
        경과 = self._경과시간들()
        한계 = G.보류_한계.total_seconds() / 3600
        assert 경과[0] < 한계 < 경과[1], (
            f"보류_한계({한계}h)가 판정 시각과 안 맞는다. 경과={경과}\n"
            f"· {한계} <= {경과[0]} 이면 큐에 갇힌 실행이 첫 판정부터 '안 돎'이 된다 "
            "= 멀쩡한데 경보(8/7 사고 재발)\n"
            f"· {한계} >= {경과[1]} 이면 다음 판정에서도 안 잡혀 늦게 안다")

    def test_아직_도는_중이면_첫_판정에서_봐준다(self):
        """8/7 사고 재현: 회차 직후에 만들어져 아직 큐에 있는 실행."""
        첫판정 = _판정시각들()[0]
        회차들 = 최근_끝난_회차(첫판정)
        표적 = 회차들[-1]                       # 가장 최근에 끝난 회차
        큐 = [_실행(표적 + timedelta(minutes=5), "", "queued")]
        assert 판정(큐, [표적], 첫판정)[0]["상태"] == 보류, \
            "아직 도는 중인데 '안 돌았다'로 읽었다 — 헛경보가 나간다"

    def test_계속_안_끝나면_다음_판정에서_잡는다(self):
        표적 = _kst(8, 7, 0)
        큐 = [_실행(표적 + timedelta(minutes=5), "", "queued")]
        다음 = 표적 + G.회차_길이 + G.보류_한계 + timedelta(minutes=1)
        assert 판정(큐, [표적], 다음)[0]["상태"] == 안돎, \
            "무한 대기를 허용하면 침묵과 같다"


class Test안_돈_회차는_딱_한_번_문자로_나간다:
    """★6시간마다 판정하면서 문자가 늘지 않는지를 **라이브 cron 으로** 확인한다.

    사장님 지시 두 개가 여기서 만난다:
      · "비정상 뜨는 즉시 알려달라고" → 한 번도 안 나가면 안 된다.
      · 문자를 하루 4통으로 늘리지 말 것 → 같은 회차로 두 번 나가도 안 된다.
    """

    def _하루치_판정시각(self, 표적):
        """표적 회차가 끝난 뒤 24시간 안에 오는 판정 시각들."""
        끝 = 표적 + G.회차_길이
        시각 = []
        for 날 in (0, 1, 2):
            기준 = datetime(2026, 8, 6, tzinfo=timezone.utc) + timedelta(days=날)
            시각 += [t for t in _판정시각들(기준) if 끝 < t <= 끝 + timedelta(hours=24)]
        return sorted(시각)

    def _문자들(self, 실행만들기, 표적=None):
        표적 = 표적 or _kst(8, 7, 0)
        나온것 = []
        for t in self._하루치_판정시각(표적):
            회차들 = 최근_끝난_회차(t)
            실행 = 실행만들기(회차들, 표적, t)
            문구 = build_report(판정(실행, 회차들, t), G.새로_안돎(실행, 회차들, t))
            if 문구:
                나온것.append((t, 문구))
        return 나온것

    def test_아예_안_돈_회차는_한_통만_나간다(self):
        def 실행(회차들, 표적, t):
            return [_실행(c + timedelta(minutes=7)) for c in 회차들 if c != 표적]
        문자 = self._문자들(실행)
        assert len(문자) == 1, \
            f"문자가 {len(문자)}통 나갔다: {[str(t) for t, _ in 문자]}"
        assert 회차_라벨(_kst(8, 7, 0)) in 문자[0][1]

    def test_실패로_끝난_회차도_한_통만_나간다(self):
        def 실행(회차들, 표적, t):
            return [_실행(c + timedelta(minutes=7),
                          "failure" if c == 표적 else "success") for c in 회차들]
        assert len(self._문자들(실행)) == 1

    def test_늦게라도_성공하면_한_통도_안_나간다(self):
        """★8/7 사고. 9시간 기다렸다 성공한 회차에 경보가 나가면 안 된다."""
        표적 = _kst(8, 7, 0)
        성공시각 = 표적 + timedelta(hours=9)

        def 실행(회차들, _표적, t):
            목록 = [_실행(c + timedelta(minutes=7)) for c in 회차들 if c != 표적]
            # 판정하는 그 시점에 GitHub 이 돌려줄 모습 그대로
            목록.append(_실행(표적 + timedelta(minutes=5), "success", "completed")
                       if t >= 성공시각
                       else _실행(표적 + timedelta(minutes=5), "", "queued"))
            return 목록
        문자 = self._문자들(실행, 표적)
        assert 문자 == [], f"멀쩡한데 경보가 나갔다: {[m for _, m in 문자]}"

    def test_하루가_통째로_비면_판정할_때마다_알린다(self):
        """가장 나쁜 경우다 — 이건 한 번 알리고 마는 게 아니다."""
        문자 = self._문자들(lambda 회차들, 표적, t: [])
        assert len(문자) >= 2, "하루치가 통째로 비었는데 한 번만 말하고 말았다"
        assert all("통째로" in m for _, m in 문자)
