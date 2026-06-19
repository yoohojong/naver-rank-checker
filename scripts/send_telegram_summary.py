"""cron 직후 즉시 보고 — cycle_summary.json → 텔레그램 (메타 전용). M10 T-M10.5.

⚠️ 인자 0 (메시지 text 를 CLI 인자로 받지 않음) = Actions log 노출 차단(D-048 가드).
실패 비차단(return 0). build_comment_from_cycle = issue 와 동일 메타 본문(키워드/분포 없음).
"""
import os
import sys

# repo 루트를 path 에 → src.* import 가능 (scripts/ 직접 실행 시 자동 포함 안 됨)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# scripts/ 도 명시 추가 (다른 cwd 에서 호출 대비)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from post_summary_to_issue import build_comment_from_cycle  # noqa: E402
from src.notify import send_report  # noqa: E402


def main() -> int:
    # 최상위 예외 방어(code-review HIGH): 어떤 경우에도 cron 비차단(return 0).
    try:
        return send_report(build_comment_from_cycle())
    except Exception:  # noqa: BLE001
        print("[TG-SUMMARY] 예외 발생 — 비차단 반환(0)")
        return 0


if __name__ == "__main__":
    sys.exit(main())
