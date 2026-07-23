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


def _kst_now() -> str:
    dt = datetime.now(timezone(timedelta(hours=9)))
    return f"{dt.month}/{dt.day} {dt.hour:02d}:{dt.minute:02d}"


def build_brief(summary: dict | None = None, ts: str | None = None) -> str:
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
    """
    if ts is None:
        ts = _kst_now()
    if summary is None:
        if not os.path.exists("cycle_summary.json"):
            return f"❌ 상노체크 {ts} · 점검 실패(시작 전 중단) — 다음 점검에 자동 재시도"
        try:
            summary = json.load(open("cycle_summary.json", encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return f"❌ 상노체크 {ts} · 결과 읽기 오류"
    s = summary

    rate = s.get("success_rate", 0) * 100
    rows = s.get("total_rows_processed", 0)
    blocked = s.get("circuit_breaker_blocks", 0)
    code_change = s.get("code_change_suspected", False)
    cb_tripped = s.get("circuit_breaker_tripped", False)
    bulk_guard = s.get("type_preview_write_blocked_by_bulk_guard", False)
    invariant = (s.get("prewrite_invariant_violations", 0) or 0) + (
        s.get("post_write_audit_violations", 0) or 0
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


def main() -> int:
    try:
        return send_report(build_brief())
    except Exception:  # noqa: BLE001
        print("[TG-SUMMARY] 예외 — 비차단 반환(0)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
