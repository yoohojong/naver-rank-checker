"""scripts/timeline_analyzer.py — H1 시계열 분석 스크립트 (2026-05-18).

사장님 단호 시그널 정합 = 백업 파일 활용 키워드별 K 변화 시계열 추적 + 매출 분석 매핑.

사용 예:
    python scripts/timeline_analyzer.py
    python scripts/timeline_analyzer.py --output .harness/timeline_report_20260518.csv
    python scripts/timeline_analyzer.py --backups-dir .harness/backups --output custom.csv

동작:
    1. `.harness/backups/*.json` + `.harness/backups/*.json.gz` 모두 read (= 시점 union)
    2. 시점별 정렬 (= 타임스탬프 기준 오름차순)
    3. 키워드 + link 별 K 변화 시퀀스 추출
    4. CSV 출력 (= 사장님 매출 분석 매핑 가이드)
       컬럼: 탭, 행, 키워드, link, 시점, K, L, M

진짜 분석 활용:
    - 키워드 + link 별 K 시계열 = 누락 / 삭제 시점 자동 검출
    - 사장님 매출 분석 = 매출 변동 시점 = K 변화 시점 (= 노출 떨어진 시점) 매핑
    - GitHub Actions artifact 다운로드 후 로컬 실행 의무
"""
import argparse
import csv
import glob
import gzip
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from typing import Iterator, Optional


# 시트 컬럼 헤더 (= sheets.py 정합)
HEADER_AREA = "노출영역"
HEADER_L = "노출여부(통합탭 순위)"
HEADER_M = "노출여부(카페구좌순위)"
HEADER_LINK = "링크"
HEADER_KEYWORD = "키워드"


def _load_backup_file(path: str) -> dict:
    """백업 파일 1개 read — .json.gz 자동 인식."""
    if path.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def iter_backup_files(backups_dir: str) -> Iterator[tuple[str, dict]]:
    """백업 디렉토리 내 모든 백업 파일 = (path, payload) 순회.

    파일명 .json + .json.gz 둘 다 인식. 타임스탬프 정렬 (오름차순).
    """
    patterns = [
        os.path.join(backups_dir, "*.json"),
        os.path.join(backups_dir, "*.json.gz"),
    ]
    paths: set = set()
    for p in patterns:
        paths.update(glob.glob(p))

    items: list[tuple[str, dict]] = []
    for path in sorted(paths):
        try:
            payload = _load_backup_file(path)
            items.append((path, payload))
        except (json.JSONDecodeError, OSError) as e:
            print(f"[SKIP] {path} 읽기 실패: {e}", file=sys.stderr)
            continue

    # 타임스탬프 정렬 (= 시계열 분석 = 시점 순)
    def _ts_key(item: tuple[str, dict]) -> str:
        _path, payload = item
        return payload.get("timestamp") or os.path.basename(_path)

    items.sort(key=_ts_key)
    for path, payload in items:
        yield path, payload


def build_timeline_rows(backups_dir: str) -> list[dict]:
    """모든 백업 파일 → 시계열 row list 구성.

    Returns:
        시계열 row list. 각 row = {탭, 행, 키워드, link, 시점, K, L, M}.
        시점 = ISO 8601 형식 (= 백업 timestamp 그대로).
    """
    rows: list[dict] = []
    file_count = 0
    for backup_path, payload in iter_backup_files(backups_dir):
        file_count += 1
        timestamp = payload.get("timestamp") or os.path.basename(backup_path)
        tabs = payload.get("tabs", {})

        for tab_name, tab_rows in tabs.items():
            for row in tab_rows:
                keyword = (row.get(HEADER_KEYWORD) or "").strip()
                link = (row.get(HEADER_LINK) or "").strip()
                # 키워드 빈 행 = 분석 대상 X (= 마케팅 예정 = T-M13 학습 정합)
                if not keyword:
                    continue

                rows.append({
                    "탭": tab_name,
                    "행": row.get("_row", ""),
                    "키워드": keyword,
                    "link": link,
                    "시점": timestamp,
                    "K": (row.get(HEADER_AREA) or "").strip(),
                    "L": (row.get(HEADER_L) or "").strip(),
                    "M": (row.get(HEADER_M) or "").strip(),
                })

    print(f"[H1] 백업 파일 {file_count} 개 → 시계열 row {len(rows)} 건 추출")
    return rows


def detect_anomaly_transitions(rows: list[dict]) -> dict:
    """누락 / 삭제 / 회복 시점 자동 검출 (= 키워드+link 별 K 변화 추적).

    Returns:
        {(키워드, link): [{시점, prev_K, new_K, transition_type}, ...]} 의 dict.
        transition_type = "loss" (= 노출 → 누락/미노출/삭제) / "recovery" (= 누락 → 노출) / "stable" (= 변화 X).
    """
    # key = (탭, 키워드, link), value = 시계열 [(timestamp, K), ...]
    timeline_per_key: dict[tuple[str, str, str], list[tuple[str, str]]] = defaultdict(list)
    for row in rows:
        key = (row["탭"], row["키워드"], row["link"])
        timeline_per_key[key].append((row["시점"], row["K"]))

    # 키별 시점 정렬 + 변화 시점 추출
    EXPOSED_K = {"AB", "스마트블록", "인기글", "중복노출", "중복노출(AB)", "중복노출(스마트블록)", "중복노출(인기글)"}
    UNEXPOSED_K = {"미노출", "누락", "삭제", ""}

    anomaly_map: dict[tuple[str, str, str], list[dict]] = {}
    for key, points in timeline_per_key.items():
        points.sort(key=lambda p: p[0])  # 시점 오름차순
        transitions: list[dict] = []
        for i in range(1, len(points)):
            prev_ts, prev_K = points[i - 1]
            new_ts, new_K = points[i]
            if prev_K == new_K:
                continue
            # 변화 유형 분류
            if prev_K in EXPOSED_K and new_K in UNEXPOSED_K:
                t_type = "loss"  # 노출 → 누락/삭제/미노출
            elif prev_K in UNEXPOSED_K and new_K in EXPOSED_K:
                t_type = "recovery"  # 누락 → 노출 회복
            else:
                t_type = "transition"  # 그 외 (= 노출 종류 간 변경)
            transitions.append({
                "시점": new_ts,
                "prev_K": prev_K,
                "new_K": new_K,
                "transition_type": t_type,
            })
        if transitions:
            anomaly_map[key] = transitions

    return anomaly_map


def write_csv(rows: list[dict], output_path: str) -> int:
    """시계열 row list → CSV 출력.

    Args:
        rows: build_timeline_rows 결과
        output_path: 출력 경로 (예: .harness/timeline_report_20260518.csv)

    Returns:
        write 된 row 수.
    """
    # 출력 디렉토리 자동 생성
    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    columns = ["탭", "행", "키워드", "link", "시점", "K", "L", "M"]
    # utf-8-sig = Excel 한국어 정상 표시 (BOM 포함)
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in columns})

    print(f"[H1] CSV 출력: {output_path} ({len(rows)} 행)")
    return len(rows)


def write_anomaly_report(anomaly_map: dict, output_path: str) -> int:
    """누락/삭제/회복 시점 별도 CSV 출력 (= 사장님 매출 분석 매핑 가이드).

    Returns:
        write 된 transition 수.
    """
    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    columns = ["탭", "키워드", "link", "시점", "prev_K", "new_K", "transition_type"]
    total = 0
    with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for (tab, keyword, link), transitions in anomaly_map.items():
            for t in transitions:
                writer.writerow({
                    "탭": tab,
                    "키워드": keyword,
                    "link": link,
                    "시점": t["시점"],
                    "prev_K": t["prev_K"],
                    "new_K": t["new_K"],
                    "transition_type": t["transition_type"],
                })
                total += 1

    print(f"[H1] 이상 변경 report: {output_path} ({total} transition)")
    return total


def _default_output_path() -> str:
    today = datetime.now().strftime("%Y%m%d")
    return f".harness/timeline_report_{today}.csv"


def _default_anomaly_path(output_path: str) -> str:
    base, ext = os.path.splitext(output_path)
    return f"{base}_anomalies{ext}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="H1 시계열 분석 — 키워드별 K 변화 추적 + 매출 매핑 가이드 (2026-05-18)"
    )
    parser.add_argument(
        "--backups-dir",
        default=".harness/backups",
        help="백업 디렉토리 (기본=.harness/backups)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=f"CSV 출력 경로 (기본=.harness/timeline_report_{{date}}.csv)",
    )
    parser.add_argument(
        "--no-anomaly",
        action="store_true",
        help="이상 변경 report 출력 skip (= 시계열 CSV 만)",
    )
    args = parser.parse_args()

    if not os.path.isdir(args.backups_dir):
        print(f"[H1] 백업 디렉토리 없음: {args.backups_dir}", file=sys.stderr)
        return 2

    output = args.output or _default_output_path()

    rows = build_timeline_rows(args.backups_dir)
    if not rows:
        print("[H1] 시계열 row 0건 = CSV 출력 skip (= 백업 파일 비어있거나 분석 대상 키워드 없음)")
        return 1

    write_csv(rows, output)

    if not args.no_anomaly:
        anomaly_map = detect_anomaly_transitions(rows)
        anomaly_path = _default_anomaly_path(output)
        write_anomaly_report(anomaly_map, anomaly_path)
        print(
            f"[H1] 사장님 매출 매핑 가이드:\n"
            f"  1. {output} = 키워드별 K 시계열 전체 (= Excel pivot 분석 활용)\n"
            f"  2. {anomaly_path} = 노출 누락/회복 시점만 (= 매출 변동 시점 매칭)\n"
            f"  3. transition_type='loss' 행 시점 = 매출 ↓ 시점 검증 의무\n"
            f"  4. transition_type='recovery' 행 시점 = 매출 ↑ 시점 검증 의무"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
