"""scripts/archive_dryrun.py — 상위노출 일별 아카이빙 드라이런 (시트 쓰기 X).

목적:
    라이브(ARCHIVE_ENABLED) 켜기 전, "무엇이 저장될지" 사장님이 눈으로 확인.
    로컬 .harness/backups/ 의 가장 최근 백업(*.json.gz)을 로드해 build_archive_rows 로
    변환한 뒤 처음 15행 + 총 행수 + 탭별 카운트를 출력한다. 시트 R/W 는 하지 않는다.

사용 예:
    python scripts/archive_dryrun.py
    python scripts/archive_dryrun.py .harness/backups/12345_20260702T030000.json.gz

백업 파일이 없으면 작은 샘플 tabs 로 출력 형식을 시연한다.
"""
import glob
import gzip
import json
import os
import sys

# 부모 디렉토리 = src 안 모듈 import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.archive import ARCHIVE_HEADER, build_archive_rows

BACKUP_DIR = ".harness/backups"
PREVIEW_ROWS = 15


def _latest_backup() -> str | None:
    """가장 최근 백업 경로(.json.gz 우선, 없으면 .json). 없으면 None."""
    candidates = glob.glob(os.path.join(BACKUP_DIR, "*.json.gz")) + glob.glob(
        os.path.join(BACKUP_DIR, "*.json")
    )
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def _load_tabs(backup_path: str) -> dict:
    """백업 파일 → tabs dict (gzip 자동 인식)."""
    if backup_path.endswith(".gz"):
        with gzip.open(backup_path, "rt", encoding="utf-8") as f:
            payload = json.load(f)
    else:
        with open(backup_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    return payload.get("tabs", {}) or {}


_SAMPLE_TABS = {
    "샴푸 카외": [
        {"키워드": "비듬샴푸", "노출영역": "AB (6/19 13:00~)", "노출여부(통합탭 순위)": "5"},
        {"키워드": "탈모샴푸", "노출영역": "누락 (6/18 03:00~)", "노출여부(통합탭 순위)": ""},
        {"키워드": "", "노출영역": "AB", "노출여부(통합탭 순위)": "1"},  # 빈 키워드 = 스킵
    ],
    "토닉 카외": [
        {"키워드": "두피토닉", "노출영역": "삭제 (6/17 03:00)", "노출여부(통합탭 순위)": ""},
        {"키워드": "모발토닉", "노출영역": "미노출 (6/18 03:00~)", "노출여부(통합탭 순위)": ""},
    ],
}


def main() -> int:
    backup_path = sys.argv[1] if len(sys.argv) > 1 else _latest_backup()

    if backup_path and os.path.exists(backup_path):
        print(f"=== archive_dryrun (백업: {backup_path}) ===")
        tabs = _load_tabs(backup_path)
    else:
        print("=== archive_dryrun (백업 없음 → 샘플 tabs 시연) ===")
        tabs = _SAMPLE_TABS

    # 날짜는 데모용 고정값(드라이런은 형식 확인이 목적).
    date_str = "YYYY-MM-DD"
    rows = build_archive_rows(tabs, date_str)

    print(f"\n헤더: {ARCHIVE_HEADER}")
    print(f"총 행수: {len(rows)}\n")

    print(f"[처음 {min(PREVIEW_ROWS, len(rows))}행]")
    for r in rows[:PREVIEW_ROWS]:
        print("  " + " | ".join(str(c) for c in r))

    # 탭별 카운트(원본 탭 순서 유지).
    counts: dict[str, int] = {}
    for r in rows:
        counts[r[1]] = counts.get(r[1], 0) + 1
    print("\n[탭별 카운트]")
    for tab_name, n in counts.items():
        print(f"  {tab_name}: {n}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
