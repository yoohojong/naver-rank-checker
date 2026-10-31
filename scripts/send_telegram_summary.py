"""cron 직후 즉시 알림 — 텔레그램에 '한 줄 건강 체크'. M10 (D-054 가독성 수정).

⚠️ 사장님 피드백(2026-06-20): 기존엔 개발자용 운영 로그(type-preview/stale/D-026 등)를
그대로 보내 외계어 + 가독성 최악이었음 → **딱 한 줄(돌았나/성공률)**로 간소화.
상세 운영 로그는 GitHub 이슈(post_summary_to_issue)에만 남김. 텔레그램 = 사람용.
인자 0(로그 노출 차단). 실패 비차단.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.notify import send_report  # noqa: E402
from src.exposure_drop_guard import (  # noqa: E402
    RECONFIRM_NOTE as G_RECONFIRM_NOTE,
    STATUS_HOLD as G_HOLD,
    STATUS_RECONFIRMED as G_RECONFIRMED,
)


def _kst_now() -> str:
    dt = datetime.now(timezone(timedelta(hours=9)))
    return f"{dt.month}/{dt.day} {dt.hour:02d}:{dt.minute:02d}"


def _결과없음(ts: str, run_status: str) -> str:
    """cycle_summary.json 이 없다 — 그런데 **왜** 없는지는 갈린다.

    ★2026-09-03. 예전엔 무조건 "점검 실패(시작 전 중단)" 였다. 그런데 그 파일은
      사이클 **맨 끝**에서야 쓰인다(src/main.py). 70분을 돌며 시트까지 다 고치고
      마지막에 죽어도 사장님은 "시작 전 중단" 을 받았다 — 무슨 일이 있었는지
      정반대로 알려준 셈이다.
      워크플로는 답을 이미 넘겨주고 있었다(rank-check.yml 의 RUN_STATUS =
      점검 스텝의 outcome). 이 스크립트가 그걸 한 번도 안 읽었을 뿐이다.

    사장님 지시(2026-09-03): "실행 자체를 안한거면 그게 진짜 실패" —
    '돌다가 죽음' 과 '시작을 못 함' 을 갈라 쓴다.
    """
    if run_status == "failure":
        return (f"❌ 상노체크 {ts} · 점검이 돌다가 중간에 멈췄습니다"
                " — 시트가 일부만 갱신됐을 수 있습니다. 다음 점검에 자동 재시도")
    if run_status == "success":
        # 스텝은 성공인데 결과 기록이 없다 = 우리가 모르는 일이 났다. 조용히 안 넘긴다.
        return (f"⚠️ 상노체크 {ts} · 점검은 끝났는데 결과 기록이 안 남았습니다"
                " — 확인이 필요해요")
    # '' (스텝이 시작도 못 함) / 'skipped' / 그 밖
    return (f"❌ 상노체크 {ts} · 점검이 시작조차 못 했습니다(준비 단계에서 멈춤)"
            " — 다음 점검에 자동 재시도")


def build_brief(summary: dict | None = None, ts: str | None = None,
                run_status: str | None = None) -> str:
    """cycle_summary.json → 사람용 한 줄 알림 (개발자 용어 0).

    2026-07-20: '네이버 변경 의심'을 두 갈래로 분리 —
      · 일시 차단(circuit_breaker) = 명시적 차단 신호(429/차단문구) 연속 → 자동 재시도로 풀림.
        '사람 점검 필요'로 띄우지 않는다(헛알람·알림 피로 방지).
      · 구조 신호(대량변경 가드·데이터 무결성·성공률 급락·K분포 급변) = 파서를 사람이 손봐야 함
        → '파서 점검 필요'로 격상.
    근거(메모리 naver-rank-success-rate-dip): '네이버변경 의심'은 대개 일시차단이라
    기존 단일 문구가 헛알람을 냈다. 부분실패=차단(재시도), 구조신호=진짜 변경(점검).

    Args:
        summary: cycle_summary dict. None 이면 cycle_summary.json 파일에서 읽음(운영 기본).
        ts:      표시용 KST 시각. None 이면 현재 KST.
        run_status: 점검 스텝의 결말(success/failure/''). None 이면 env RUN_STATUS.
                 결과 파일이 없을 때 '돌다가 죽음'과 '시작 못 함'을 가르는 근거다.
    """
    if ts is None:
        ts = _kst_now()
    if run_status is None:
        run_status = os.environ.get("RUN_STATUS", "").strip().lower()
    if summary is None:
        if not os.path.exists("cycle_summary.json"):
            return _결과없음(ts, run_status)
        try:
            summary = json.load(open("cycle_summary.json", encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return f"❌ 상노체크 {ts} · 결과 읽기 오류"
    line = _build_brief_core(summary, ts)
    # 노출 급감 검사가 기준을 일부 못 읽었으면(2026-10-30 품질 반려 고침) 어느 줄이든 끝에 붙인다 —
    # '점검 완료'만 보고 전체를 확인한 것으로 읽히지 않게.
    d = summary.get("exposure_drop") or {}
    held = bool(summary.get("exposure_drop_hold"))
    # 두 회차 연속 같은 급감(2026-10-30 정책 A) — 실제 변화로 보고 썼다는 한 줄
    if d.get("status") == G_RECONFIRMED and not held:
        line += (
            f"\n🔁 노출 {d.get('baseline_exposed', '?')}→{d.get('current_exposed', '?')}줄 · "
            f"{G_RECONFIRM_NOTE}"
        )
    unreadable = int(d.get("rows_unreadable") or 0)
    if unreadable and int(d.get("rows_compared") or 0) > 0:
        line += (
            f"\n⚠️ 노출 급감 검사: {unreadable}줄은 앞 회차 값을 못 읽어 확인 못 함"
            f"(읽은 {d.get('rows_compared')}줄만 맞댐)"
        )
    elif unreadable:
        # 쓰기 여부는 실제로 멈췄나(held)로만 말한다 — 품질 2차 지적 2-1
        tail = "" if held else "(쓰기는 막지 않음)"
        line += f"\n⚠️ 노출 급감 검사: 앞 회차 값을 못 읽어 {unreadable}줄 모두 비교 못 함{tail}"
    if summary.get("exposure_drop_state_saved") is False:
        line += "\n⚠️ 노출 급감 앞 회차 기록 저장 실패 — 다음 회차에 급감이면 다시 멈춥니다"
    return line


def _build_brief_core(s: dict, ts: str) -> str:
    rate = s.get("success_rate", 0) * 100
    rows = s.get("total_rows_processed", 0)
    blocked = s.get("circuit_breaker_blocks", 0)
    code_change = s.get("code_change_suspected", False)
    cb_tripped = s.get("circuit_breaker_tripped", False)
    bulk_guard = s.get("type_preview_write_blocked_by_bulk_guard", False)
    invariant = (s.get("prewrite_invariant_violations", 0) or 0) + (
        s.get("post_write_audit_violations", 0) or 0
    )

    # 노출 급감 멈춤(2026-10-29) — 실패가 아니라 '멈춤'. 다른 어떤 줄보다 먼저 알린다.
    if s.get("exposure_drop_hold"):
        d = s.get("exposure_drop") or {}
        ratio = d.get("drop_ratio")
        pct = f"{ratio * 100:.0f}%" if isinstance(ratio, (int, float)) else "?"
        return (
            f"⏸ 상노체크 {ts} · 노출 {d.get('baseline_exposed', '?')}→{d.get('current_exposed', '?')}줄"
            f"({pct} 감소) — 이번 회차 시트 쓰기를 멈췄습니다(시트는 앞 회차 값 그대로)."
            f"\n멈춤은 한 회차만 — 다음 회차에도 같으면 실제 변화로 보고 저절로 씁니다."
            f" 바로 쓰려면 수동 실행에서 '노출 급감 그대로 쓰기'를 켜고 한 번 돌리면 됩니다."
        )

    # 정상 (성공률 ≥90% + 코드변경 의심 없음)
    if s.get("success_rate", 0) >= 0.9 and not code_change:
        line = f"✅ 상노체크 {ts} 점검 완료 · {rows}개 키워드 · 성공률 {rate:.0f}%"
        if blocked:
            line += f"\n⚠️ 네이버 차단 {blocked}회 감지(다음 점검 자동 재시도)"
        return line

    if code_change:
        # 회로차단 = 일시적 차단 → 자동 재시도로 풀림(사람 점검 불필요).
        if cb_tripped:
            hint = f" {blocked}회" if blocked else ""
            return (
                f"⚠️ 상노체크 {ts} · 네이버 일시 차단{hint} 감지 "
                f"— 자동 재시도로 해결됩니다(사람 점검 불필요)"
            )
        # 구조 신호 → 사람(Claude)이 파서를 손봐야 함.
        reasons = []
        if bulk_guard:
            reasons.append("대량변경 가드")
        if invariant:
            reasons.append("데이터 무결성")
        if s.get("success_rate", 1.0) < 0.5:
            reasons.append("성공률 급락")
        tag = ", ".join(reasons) if reasons else "K분포/구조 급변"
        return (
            f"🔴 상노체크 {ts} · 성공률 {rate:.0f}% · 네이버 구조변경 의심({tag}) "
            f"— 파서 점검 필요(자동 재시도로 안 풀림)"
        )

    # code_change 아님 + 성공률 <90% = 부분 실패 → 다음 점검 재시도
    return f"⚠️ 상노체크 {ts} · 성공률 {rate:.0f}% · 일부 실패(다음 점검 재시도)"


def 이_회차에_이미_보고했나() -> bool:
    """같은 회차(6시간)에 이미 '정상' 보고가 나갔으면 True = 이번엔 문자 안 보낸다.

    ★2026-10-31 사장님 "왜 보고를 안해줘". 예전엔 같은 회차에 success 실행이 하나라도 있으면
      True 였다. 그런데 노출 급감으로 시트 쓰기를 멈춘 실행도 종료 0(success)이다 — 12:00 멈춤 실행
      (41162456392)이 12~18 칸을 차지해, 15:19 다시 잰 실행(41176100244, 2회차 922/922 성공)의 문자가
      생략됐다. 이제 같은 회차에서 이번 실행보다 **먼저 만들어진 실행 중 가장 늦은 것**
      (success · failure 만 — 취소된 실행은 문자를 안 보낸다)을 '바로 앞 실행'으로 보고:
        · 실패였으면 마지막 소식은 ❌ → 이번 결과를 보낸다
        · 성공이었으면 그 실행의 노출 급감 기록(이번 실행이 캐시로 받은 앞 회차 기록 —
          cycle_summary.exposure_drop.prev_run.record)으로 멈춤이었나를 본다:
          멈춤 → 보낸다 / 멈춤 아님 → 생략 / 그 실행 기록이 아님·없음 → 보낸다(모르는 것을 '보냈다'로 읽지 않는다)

    ★하루 8통의 정체(2026-09-03). 예약을 :07·:27 두 번 거는 것은 GitHub 이 예약을
      통째로 흘린 적이 있어 남겨 둔 보험이다. 그런데 concurrency 가 뒤엣것을
      지우지 않고(cancel-in-progress: false) **줄을 세워서**, 앞 실행이 성공해도
      뒤 실행이 똑같은 사이클을 한 번 더 돌고 자기 문자를 또 보냈다.
      실행은 그대로 둔다(보험이니까). 줄일 것은 **문자**다 — 한 회차에 한 통.

    회차 경계는 가동확인.py 한 곳에만 있다(회차_시작). 여기서 다시 계산하지 않는다.
    저장소를 못 읽으면 False — 못 읽은 것을 '이미 보냈다'로 읽으면 침묵이 기본값이 된다.
    """
    # ★'scripts.가동확인' 으로 못 박는다. 'import 가동확인' 은 같은 파일을 **다른 모듈**로
    #   한 번 더 읽어들여, 검사에서 갈아끼운 것과 라이브가 보는 것이 서로 달라진다.
    try:
        from scripts import 가동확인 as G
    except Exception:  # noqa: BLE001
        return False
    이번run = os.environ.get("GITHUB_RUN_ID", "").strip()
    저장소 = os.environ.get("GH_REPO") or os.environ.get("GITHUB_REPOSITORY") or G.기본_저장소
    try:
        기록 = G.실행이력(저장소, G.점검_워크플로)
    except Exception:  # noqa: BLE001
        print("[TG-SUMMARY] 지난 실행을 못 읽음 — 그냥 보낸다(침묵보다 낫다)")
        return False

    def _때(r):
        return G._파싱(r.get("createdAt") or r.get("created_at") or "")

    # 이번 실행이 속한 회차. 이번 실행의 생성 시각을 쓴다 — '지금'으로 재면
    # 사이클이 회차 경계를 넘겨 끝났을 때 엉뚱한 회차를 본다.
    나 = [r for r in 기록 if str(r.get("databaseId", "")) == 이번run]
    기준 = (_때(나[0]) if (나 and _때(나[0])) else datetime.now(timezone.utc))
    시작 = G.회차_시작(기준)
    끝 = 시작 + G.회차_길이
    라벨 = G.회차_라벨(시작)
    앞것들 = []
    for r in 기록:
        if str(r.get("databaseId", "")) == 이번run:
            continue
        if r.get("conclusion") not in ("success", "failure"):
            continue   # 취소 · 건너뜀 · 진행 중 = 문자를 보낸 실행이 아니다
        때 = _때(r)
        if not 때 or not (시작 <= 때.astimezone(G.KST) < 끝) or 때 > 기준:
            continue
        앞것들.append((때, r))
    if not 앞것들:
        return False
    _, 앞 = max(앞것들, key=lambda x: x[0])
    앞id = str(앞.get("databaseId", ""))
    if 앞.get("conclusion") != "success":
        print(f"[TG-SUMMARY] {라벨} 회차 바로 앞 실행 {앞id} 이 실패로 끝났다 — 이번 결과를 보낸다")
        return False
    rec = _앞_실행_기록()
    받은id = str(rec.get("run_id", "")) if rec else ""
    if 받은id and 받은id == 이번run:
        # 이번 실행 안의 자동 재시도(1차 사이클이 죽고 90초 뒤 다시 돎)가 앞 기록을 자기 기록으로 덮었다 —
        # 앞 실행이 무엇이었는지 모른다. 1차가 죽은 일 자체가 소식이라 보낸다(GPT 검토 2번 · 일부러 고른 선택).
        print(f"[TG-SUMMARY] {라벨} 회차 바로 앞 실행 {앞id} — 이번 실행이 중간에 다시 돌아 앞 기록이 덮였다"
              " · 그냥 보낸다")
        return False
    if not 받은id or 받은id != 앞id:
        print(f"[TG-SUMMARY] {라벨} 회차 바로 앞 실행 {앞id} 이 무엇을 보고했는지 기록이 없다"
              f"(받은 기록: 실행 {받은id or '없음'}) — 그냥 보낸다(침묵보다 낫다)")
        return False
    앞시도 = 앞.get("attempt")
    if 앞시도 is not None and str(rec.get("run_attempt", "")) != str(앞시도):
        # 실행 번호는 같아도 시도가 다르면 다른 결과다 — 1차 '통과' 기록으로 2차 '멈춤'을 덮지 않는다(GPT 검토 1번).
        print(f"[TG-SUMMARY] {라벨} 회차 바로 앞 실행 {앞id} 의 {앞시도}차 시도 기록이 없다"
              f"(받은 기록: {rec.get('run_attempt')}차) — 그냥 보낸다")
        return False
    if rec.get("status") == G_HOLD:
        print(f"[TG-SUMMARY] {라벨} 회차 바로 앞 실행 {앞id} 은 노출 급감 멈춤이었다 — 이번 결과를 보낸다")
        return False
    print(f"[TG-SUMMARY] {라벨} 회차는 이미 성공 보고가 나갔다(실행 {앞id} · 노출 급감 {rec.get('status')})"
          " — 문자 생략")
    return True


def _요약() -> dict:
    try:
        with open("cycle_summary.json", encoding="utf-8") as f:
            s = json.load(f)
        return s if isinstance(s, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _앞_실행_기록() -> dict | None:
    """이번 실행이 읽은 '앞 회차 노출 급감 기록'(실행 번호 · 판정). 없으면 None.

    새 상태 파일을 만들지 않는다 — 노출 급감 장치가 이미 캐시로 넘겨받아 cycle_summary 에 싣는 것을 쓴다.
    """
    rec = ((_요약().get("exposure_drop") or {}).get("prev_run") or {}).get("record")
    return rec if isinstance(rec, dict) else None


def _이번에_멈췄나() -> bool:
    """이번 실행이 노출 급감으로 쓰기를 멈췄거나 '급감 재확인'으로 썼거나 K 분포 경보가 났나 — 모두 생략을 타지 않는다.

    급감 재확인(2026-10-30 정책 A)은 바로 앞 멈춤 실행이 같은 회차(:07 → :27 줄 선 실행)일 때가 많다.
    멈춘 실행도 종료 0(success)이라 생략 규칙이 '이미 보고함'으로 읽어 '실제 변화로 보고 썼음' 줄이 안 갈 뻔했다.
    K 분포 경보(2026-10-31): 사람 스위치로 푼 실행은 경보가 빨강으로 안 올라가 ✅ 줄이 된다 — 그래도 새 소식이다.
    """
    s = _요약()
    return (bool(s.get("exposure_drop_hold")) or s.get("exposure_drop_status") == G_RECONFIRMED
            or s.get("k_anomaly_detected") is True)


def _다시_잰_실행인가() -> bool:
    """손으로 돌린 실행(workflow_dispatch)이나 다시 돌린 시도(run_attempt 2 이상)인가.

    다시 잰 결과는 앞 소식(멈춤 · 실패 알림)의 끝 소식이다 — 같은 회차라도 보낸다(2026-10-31).
    ⚠️ 외부 cron-job.org 정각 호출도 workflow_dispatch 다. 그 호출은 회차 첫 실행이라 원래도 보내던 것이라 달라지지 않는다.
    """
    if os.environ.get("GITHUB_EVENT_NAME", "").strip() == "workflow_dispatch":
        return True
    try:
        return int(os.environ.get("GITHUB_RUN_ATTEMPT", "1").strip() or "1") >= 2
    except ValueError:
        return False


def 생략할까(brief: str) -> bool:
    """문자를 생략하는 것은 '같은 회차에 정상 보고가 이미 나갔는데 이번도 평범한 정상 결과'일 때뿐이다.

    문자 폭주를 막는 장치(2026-09-03 하루 8통 → 회차당 1통)는 정상(✅) 중복에만 건다.
    실패 · 경보 · 멈춤 문자는 같은 회차라도 늘 보낸다 — 앞 성공이 있다고 ❌ 가 묻히면 안 된다.
    """
    if not brief.startswith("✅"):
        return False
    if _이번에_멈췄나():
        return False
    if _다시_잰_실행인가():
        print("[TG-SUMMARY] 손으로 · 다시 돌린 실행 — 같은 회차라도 보낸다")
        return False
    return 이_회차에_이미_보고했나()


def main() -> int:
    try:
        brief = build_brief()
        if 생략할까(brief):
            return 0
        return send_report(brief)
    except Exception:  # noqa: BLE001
        print("[TG-SUMMARY] 예외 — 비차단 반환(0)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
