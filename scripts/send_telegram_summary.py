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


def build_brief() -> str:
    """cycle_summary.json → 사람용 한 줄 알림 (개발자 용어 0)."""
    ts = _kst_now()
    if not os.path.exists("cycle_summary.json"):
        return f"❌ 상노체크 {ts} · 점검 실패(시작 전 중단) — 다음 점검에 자동 재시도"
    try:
        s = json.load(open("cycle_summary.json", encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return f"❌ 상노체크 {ts} · 결과 읽기 오류"
    rate = s.get("success_rate", 0) * 100
    rows = s.get("total_rows_processed", 0)
    blocked = s.get("circuit_breaker_blocks", 0)
    code_change = s.get("code_change_suspected", False)
    if s.get("success_rate", 0) >= 0.9 and not code_change:
        line = f"✅ 상노체크 {ts} 점검 완료 · {rows}개 키워드 · 성공률 {rate:.0f}%"
        if blocked:
            line += f"\n⚠️ 네이버 차단 {blocked}회 감지(다음 점검 자동 재시도)"
        return line
    if code_change:
        return f"⚠️ 상노체크 {ts} · 성공률 {rate:.0f}% · 네이버 변경 의심 — 점검 필요"
    return f"⚠️ 상노체크 {ts} · 성공률 {rate:.0f}% · 일부 실패(다음 점검 재시도)"


def main() -> int:
    try:
        return send_report(build_brief())
    except Exception:  # noqa: BLE001
        print("[TG-SUMMARY] 예외 — 비차단 반환(0)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
