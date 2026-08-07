# -*- coding: utf-8 -*-
"""상노 점검이 **실제로 돌았는지** 회차 단위로 확인한다 (2026-08-07 신설).

## 왜 이게 필요한가
지금까지의 감시는 전부 '실패했을 때' 울린다. 그런데 실측된 사고는 실패가 아니었다:
  · 08-06 16:54 — 러너 미배정으로 job 이 시작조차 못 함
  · 07-23 / 07-28 — 큐에 갇혀 cancelled 로 끝남 → 워치독 job 이 통째로 skipped, **알림 0건**
  · 워치독 자신도 같은 러너를 쓰므로 러너가 없으면 고치는 장치까지 같이 죽는다
'실패'가 아니라 '안 돌았다' 는 아무도 안 알려줬다. 그래서 **부재**를 본다.

## 세는 단위 = 회차(6시간 창), 실행 횟수가 아니다
한 회차에 두 갈래로 시도한다 — 외부 크론(:00) + GitHub 크론(cron '7,27 ...').
실측(07-14~08-07, 200건): 회차당 GitHub 스케줄 실행은 1건, 외부 크론 성공 94/96·스케줄 95/96.
둘 중 하나만 돌면 그 회차는 산 것이므로, 실행 건수를 세면 정상인데도 모자라 보인다.
KST 00·06·12·18시 네 회차 각각에 **성공이 하나라도 있었나**만 본다.

## 세 가지 상태 — '안 돎'과 '아직 도는 중'을 섞지 않는다
큐에 갇힌 실행이 실재한다(08-07 06:00 실행이 9시간 넘게 queued). 그걸 '안 돎'으로 읽으면
멀쩡한데 경보가 나가고, 실제로 그 실행은 나중에 성공한다. 그래서 **보류**를 따로 둔다.
  정상 = 성공이 하나라도 있음 / 보류 = 아직 안 끝난 실행이 있음 / 안돎 = 끝났는데 성공 0

## 이 장치가 재는 것과 안 재는 것
잰다: 점검 워크플로가 그 회차에 돌아서 성공으로 끝났나.
못 잰다: 그래서 시트에 숫자가 실제로 들어갔나. 아카이빙 실패는 비차단이라 워크플로는
        초록으로 끝난다(src/main.py). 문구도 딱 잰 만큼만 말한다 — 넘겨짚지 않는다.

## 두 다리로 선다
① GitHub Actions(하루 한 번) = **보고 통로**. 잘 돌았어도 한 줄 보낸다.
② 사장님 PC 예약작업 = **경보 통로**. 평소엔 조용하고, 회차가 비었거나
   ①이 안 돌았거나 ①의 상태를 못 읽었을 때만 운다. GitHub 이 멈춘 날은 ②만 살아 있다.
(경보 통로와 보고 통로를 나눈다 — 보고가 섞이면 경보가 묻힌다.)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.notify import send_telegram  # noqa: E402

# ★화면 인코딩 때문에 경보가 죽지 않게. cp949 화면에서 print("🔴...") 가 터지면
#   그 아래 send_telegram 까지 못 가서 **문자가 0통** 나간다(실측 재현).
#   예약작업 인자의 -X utf8 에 기대면, 누가 예약작업을 다시 만드는 순간 조용히 사라진다.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

KST = timezone(timedelta(hours=9))
회차_길이 = timedelta(hours=6)   # rank-check.yml cron '7,27 15,21,3,9 * * *' 과 한 몸
기본_저장소 = "yoohojong/naver-rank-checker"
점검_워크플로 = "rank-check.yml"
보고_워크플로 = "가동확인.yml"
조회_제한초 = 60   # gh 가 물려도 감시가 통째로 멈추지 않게
# ★회차가 끝난 지 이만큼 지났는데 아직도 안 끝난 실행은 '안 돎'으로 본다.
#   실측: run 31128005421 이 12시간 넘게 queued 였다. 보류로만 두면 판정 창이
#   겹침 없이 지나가며 **영원히 사면**된다 — 하루 한 번만 판정하기 때문이다.
보류_한계 = timedelta(hours=12)

정상, 보류, 안돎 = "정상", "보류", "안돎"


# ── 회차 계산 (순수 함수) ─────────────────────────────────────────────────────

def 회차_시작(때: datetime) -> datetime:
    """그 시각이 속한 회차의 시작(KST). 경계는 여기 한 곳에만 있다."""
    k = 때.astimezone(KST)
    시작시 = (k.hour // int(회차_길이.total_seconds() // 3600)) * int(
        회차_길이.total_seconds() // 3600)
    return k.replace(hour=시작시, minute=0, second=0, microsecond=0)


def 회차_라벨(시작: datetime) -> str:
    """'12시' 는 정오로 읽힌다 — 6시간 덩어리라는 걸 라벨이 스스로 말하게 한다."""
    s = 시작.astimezone(KST)
    e = (s + 회차_길이).hour
    return f"{s.hour:02d}~{e:02d}시"


def 최근_끝난_회차(지금: datetime, 개수: int = 4) -> list:
    """이미 **끝난** 회차만 오래된 순으로. 진행 중인 회차는 판정하지 않는다.

    예전엔 여기에 '유예 40분'을 뒀는데 근거가 틀렸다 — 실측 200건에서 회차 시작 기준
    생성 지연이 40분을 넘는 실행이 절반(103건)이었고, 최대 완료가 회차시작+6.82시간이었다.
    시간으로 넉넉히 기다리는 대신, **끝나지 않은 실행이 있으면 '보류'** 로 두는 쪽이 맞다
    (아래 판정()). 그래야 늦게 끝나는 실행을 시간 가정 없이 정확히 다룬다.
    """
    현재 = 회차_시작(지금)
    return [현재 - 회차_길이 * (i + 1) for i in range(개수)][::-1]


def 판정(실행들: list, 회차들: list, 지금: datetime = None) -> list:
    """회차마다 정상/보류/안돎. 실행들 = [{createdAt, conclusion, status}, ...]"""
    지금 = 지금 or datetime.now(timezone.utc)
    결과 = []
    for 시작 in 회차들:
        끝 = 시작 + 회차_길이
        속한것 = []
        for r in 실행들:
            때 = _파싱(r.get("createdAt") or r.get("created_at") or "")
            if 때 is None:
                continue
            if 시작 <= 때.astimezone(KST) < 끝:
                속한것.append(r)
        성공 = [r for r in 속한것 if r.get("conclusion") == "success"]
        # status 가 'completed' 가 아니면 아직 도는 중(queued/in_progress). 실재한다 —
        # 08-07 06:00 실행이 9시간 넘게 queued 였다. 그걸 '안 돎'으로 읽으면 헛경보다.
        진행중 = [r for r in 속한것
                  if r.get("status") and r.get("status") != "completed"]
        # 아직 도는 중이어도 너무 오래됐으면 '안 돎'이다 — 무한 대기는 침묵과 같다.
        너무_오래 = 지금.astimezone(KST) - 끝 > 보류_한계
        상태 = 정상 if 성공 else (보류 if (진행중 and not 너무_오래) else 안돎)
        결과.append({
            "회차": 회차_라벨(시작), "시작": 시작,
            "성공": len(성공), "시도": len(속한것), "진행중": len(진행중),
            "상태": 상태, "산것": bool(성공),
        })
    return 결과


def _파싱(s: str):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def 최대_연속_결측(결과: list) -> int:
    """연속으로 몇 번 걸렀나 — 시트가 얼마나 옛것인지가 여기서 나온다."""
    최대 = 현재 = 0
    for r in 결과:
        # 보류도 '갱신 안 됨'이다 — 안돎만 세면 [안돎,보류,안돎] 을 12시간으로 낮잡는다.
        현재 = 현재 + 1 if r["상태"] != 정상 else 0
        최대 = max(최대, 현재)
    return 최대


# ── 문구 (순수 함수) ─────────────────────────────────────────────────────────

def _결측_설명(결과: list) -> str:
    """빠진 회차가 실제로 무엇을 뜻하는지. **넘겨짚지 않는다.**

    ★2026-08-07 정정: 처음엔 '그 시각 순위는 다시 못 잽니다' 라고 썼는데 사실이 아니다.
      영구 기록(상위노출_이력)은 **하루 1벌**이고 회차마다 그날 블록을 덮어쓴다
      (src/archive.py '날짜별 멱등'). 그래서 하루 네 회차 중 한둘이 빠져도 그날 기록은
      안 비고, 실제로 잃는 건 시트 숫자의 신선도다.
      하루가 통째로 빠졌을 때만 '그날 기록이 없다'가 맞다.
    """
    빠짐 = [r for r in 결과 if r["상태"] == 안돎]
    if not 빠짐:
        return ""
    if len(빠짐) == len(결과):
        return ("하루치를 통째로 걸렀습니다 — 그날 순위 기록이 안 남았을 수 있습니다.\n"
                "→ 확인이 필요해요.")
    옛것 = (최대_연속_결측(결과) + 1) * 6
    return (f"시트 숫자가 {옛것}시간 전 것일 수 있습니다"
            f"(원래는 6시간마다 갱신).\n"
            "→ 그날 순위 기록은 남아 있을 가능성이 높습니다"
            "(다른 회차가 그날 몫을 덮어씁니다). 다음 회차가 돌면 시트도 최신으로 돌아옵니다.")


def build_report(결과: list) -> str:
    """하루 한 줄 보고. **잘 돌았어도 보낸다** — 이게 '감시가 살아있다'는 유일한 신호다."""
    산것 = [r for r in 결과 if r["상태"] == 정상]
    빠짐 = [r for r in 결과 if r["상태"] == 안돎]
    보류중 = [r for r in 결과 if r["상태"] == 보류]
    # ★초록은 '네 번 다 정상'일 때만. 예전엔 빠짐만 봐서, 네 회차가 전부 큐에 갇히면
    #   '0번 정상'인데도 🟢 가 나갔다(실측 재현). 아직 도는 중도 정상은 아니다.
    if len(산것) == len(결과):
        머리 = "🟢"
    elif len(빠짐) >= 2 or not 산것:
        머리 = "🔴"
    else:
        머리 = "🟠"
    줄 = f"{머리} 상노 점검 지난 하루: {len(결과)}번 중 {len(산것)}번 정상"
    if 보류중:
        줄 += f" (아직 도는 중 {len(보류중)}번)"
    if 빠짐:
        줄 += "\n안 돈 점검: " + ", ".join(r["회차"] for r in 빠짐)
        줄 += "\n" + _결측_설명(결과)
    return 줄


def build_alert(결과: list, 보고통로: str = 정상) -> str:
    """PC 쪽 경보. 문제 없으면 **빈 문자열**(조용).

    여기서만 침묵이 허용된다. '이상 없음'을 확인한 침묵이고,
    보고 통로(①)가 매일 한 줄을 보내 살아있음을 따로 증명하기 때문이다.
    """
    빠짐 = [r for r in 결과 if r["상태"] == 안돎]
    산것 = [r for r in 결과 if r["상태"] == 정상]
    조각 = []
    if not 산것 and not 빠짐:
        # 전부 '아직 도는 중' — 정상이 하나도 없다. 조용히 넘기면 러너 기근 날 무음이 된다.
        조각.append(
            f"🔴 상노 점검이 {len(결과)}번 모두 시작만 하고 안 끝났습니다"
            "(GitHub 이 실행할 기계를 못 붙이는 중일 수 있습니다).\n"
            "→ 시트 숫자가 갱신되지 않고 있습니다. 확인이 필요해요.")
    if 빠짐:
        조각.append(
            f"🔴 상노 점검이 {len(빠짐)}번 안 돌았습니다 "
            f"({', '.join(r['회차'] for r in 빠짐)}).\n" + _결측_설명(결과))
    if 보고통로 == 안돎:
        조각.append(
            "🔴 상노 점검 일일 보고 자체가 하루 넘게 안 돌았습니다 "
            "(GitHub 쪽이 통째로 멈췄을 수 있습니다).\n"
            "→ 확인이 필요해요. 이 문자는 사장님 PC 에서 보냈습니다.")
    elif 보고통로 == "못읽음":
        # ★못 읽은 것을 '이상 없음'으로 넘기면, 보고 워크플로가 사라져도 아무도 모른다.
        #   실제로 그 상태를 재현했다(워크플로 404 인데 경보는 '이상 없음'이라 말했다).
        조각.append(
            "⚠️ 상노 점검 일일 보고가 살아있는지 확인하지 못했습니다"
            "(GitHub 에 물어보는 데 실패).\n"
            "→ 감시가 걸려 있는지 한 번 봐 주세요. 이 문자는 사장님 PC 에서 보냈습니다.")
    return "\n\n".join(조각)


def build_생존신고() -> str:
    """PC 다리가 주 1회 '나 살아있다'를 알린다.

    이 다리는 평소 조용하다 — 그래서 조용한 게 '이상 없음'인지 '죽었음'인지 구분이 안 된다.
    (열쇠파일 경로가 바뀌거나 예약작업이 지워지면 아무 소리 없이 사라진다.)
    주 1회 한 줄을 보내면, **그 한 줄이 안 오는 것 자체가 신호**가 된다.
    """
    return ("🟢 상노 감시(사장님 PC 쪽)가 살아있습니다. 주 1회 알려드립니다.\n"
            "→ 조치는 필요 없습니다. 이 줄이 한 주 넘게 안 오면 PC 감시가 멈춘 겁니다.")


# ── GitHub 조회 ──────────────────────────────────────────────────────────────

def 실행이력(저장소: str, 워크플로: str, 개수: int = 40) -> list:
    """gh CLI 로 실행 이력. gh 는 러너에도 사장님 PC 에도 이미 깔려 있다.

    실패하면 예외를 던진다 — 조용히 빈 목록을 돌려주면 '안 돌았다'로 오판해
    멀쩡한데 경보가 나간다. 못 읽은 것과 안 돈 것은 다르다.
    개수 40 = 약 5일치(실측 하루 8건). 24시간을 덮고도 남는다.
    """
    try:
        r = subprocess.run(
            ["gh", "run", "list", "--workflow", 워크플로, "--repo", 저장소,
             "--limit", str(개수), "--json", "createdAt,conclusion,status,databaseId"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=조회_제한초,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("gh 조회 시간 초과")
    if r.returncode != 0:
        raise RuntimeError(f"gh 조회 실패(rc={r.returncode})")
    return json.loads(r.stdout or "[]")


def 보고통로_상태(저장소: str, 지금: datetime) -> str:
    """①(GitHub 일일 보고)이 최근 26시간 안에 돌았나 → 정상 / 안돎 / 못읽음.

    ★못 읽은 것을 '정상'으로 뭉개지 않는다. 보고 워크플로가 지워지거나 이름이 바뀌거나
      기본 브랜치에서 빠지면 조회가 404 로 실패하는데, 그게 바로 '보고 통로가 죽었다'는
      신호다. 그걸 조용히 넘기면 감시가 사라진 걸 아무도 모른다(실제로 재현됨).
    """
    try:
        기록 = 실행이력(저장소, 보고_워크플로, 개수=5)
    except Exception:
        return "못읽음"
    # ★'실행이 있었나'가 아니라 '성공했나'를 본다. 큐에 갇혔거나 실패한 보고는
    #   문자를 한 통도 못 보낸다 — 그걸 '정상'이라 읽으면 보고·경보가 동시에 침묵한다.
    한계 = 지금 - timedelta(hours=26)
    for r in 기록:
        때 = _파싱(r.get("createdAt", ""))
        if 때 and 때 >= 한계 and r.get("conclusion") == "success":
            return 정상
    return 안돎


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="상노 점검이 실제로 돌았는지 회차 단위 확인")
    p.add_argument("--모드", choices=["보고", "경보", "생존신고"], default="보고",
                   help="보고=매일 한 줄 무조건 발송(GitHub) / 경보=문제 있을 때만(PC) / "
                        "생존신고=PC 감시가 살아있다는 주 1회 한 줄")
    p.add_argument("--저장소", default=os.environ.get("GH_REPO", 기본_저장소))
    p.add_argument("--회차수", type=int, default=4)
    p.add_argument("--발송안함", action="store_true", help="문구만 출력(연습용)")
    a = p.parse_args(argv)

    if a.모드 == "생존신고":
        문구 = build_생존신고()
        print(문구)
        if a.발송안함:
            return 0
        return 0 if send_telegram(문구) else 1

    지금 = datetime.now(timezone.utc)
    회차들 = 최근_끝난_회차(지금, 개수=a.회차수)
    try:
        실행 = 실행이력(a.저장소, 점검_워크플로)
    except Exception:
        # 못 읽었으면 '안 돌았다'고 단정하지 않는다. 다만 조용히 넘기지도 않는다.
        # 영어 예외 이름은 사장님께 안 보낸다 — 로그에만 남긴다.
        문구 = ("⚠️ 상노 점검이 돌고 있는지 확인하지 못했습니다(GitHub 에 물어보는 데 실패).\n"
                "점검이 멈춘 건지 조회만 막힌 건지 아직 모릅니다.\n"
                "→ 이어지면 확인이 필요해요.")
        print(문구)
        if not a.발송안함:
            send_telegram(문구)
        return 1

    결과 = 판정(실행, 회차들, 지금)
    for r in 결과:
        print(f"[가동확인] {r['회차']} 시도={r['시도']} 성공={r['성공']} "
              f"진행중={r['진행중']} → {r['상태']}")

    if a.모드 == "보고":
        문구 = build_report(결과)
    else:
        상태 = 보고통로_상태(a.저장소, 지금)
        print(f"[가동확인] 보고 통로 = {상태}")
        문구 = build_alert(결과, 보고통로=상태)
        if not 문구:
            print("[가동확인] 이상 없음 — 경보 없음(보고 통로가 매일 살아있음을 증명한다)")
            return 0

    print(문구)
    if a.발송안함:
        return 0
    return 0 if send_telegram(문구) else 1


if __name__ == "__main__":
    sys.exit(main())
