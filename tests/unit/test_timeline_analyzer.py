"""H1 시계열 분석 스크립트 회귀 test (2026-05-18).

사장님 단호 시그널 정합 = scripts/timeline_analyzer.py 검증:
- 백업 파일 (.json + .json.gz) union read
- 시점 순 정렬
- 키워드 + link 별 K 변화 추적
- CSV 출력 정합 (= 컬럼 의무)
- 이상 변경 (loss / recovery) 자동 검출
"""
import csv
import gzip
import json
import os
import sys
import tempfile

import pytest

# scripts/ 모듈 path 추가
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "scripts",
    ),
)


def _write_backup(tmp_path, filename: str, payload: dict, gzipped: bool = False) -> str:
    """test 용 백업 파일 작성. gzipped True 시 .json.gz."""
    full_path = str(tmp_path / filename)
    if gzipped:
        with gzip.open(full_path, "wt", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    else:
        with open(full_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    return full_path


@pytest.fixture
def sample_backups_dir(tmp_path):
    """3 시점 백업 fixture — 키워드 K 변화 시뮬."""
    # T1: AB → T2: 누락 → T3: AB (= recovery)
    payload_t1 = {
        "timestamp": "2026-05-15T06:00:00+09:00",
        "run_id": "run1",
        "spreadsheet_id": "sheet1",
        "tabs": {
            "샴푸 카외": [
                {"_row": 2, "키워드": "탈모샴푸", "링크": "https://cafe.naver.com/cosmania/111",
                 "노출영역": "AB", "노출여부(통합탭 순위)": "3", "노출여부(카페구좌순위)": "2"},
            ]
        },
    }
    payload_t2 = {
        "timestamp": "2026-05-16T06:00:00+09:00",
        "run_id": "run2",
        "spreadsheet_id": "sheet1",
        "tabs": {
            "샴푸 카외": [
                {"_row": 2, "키워드": "탈모샴푸", "링크": "https://cafe.naver.com/cosmania/111",
                 "노출영역": "누락", "노출여부(통합탭 순위)": "", "노출여부(카페구좌순위)": ""},
            ]
        },
    }
    payload_t3 = {
        "timestamp": "2026-05-17T06:00:00+09:00",
        "run_id": "run3",
        "spreadsheet_id": "sheet1",
        "tabs": {
            "샴푸 카외": [
                {"_row": 2, "키워드": "탈모샴푸", "링크": "https://cafe.naver.com/cosmania/111",
                 "노출영역": "AB", "노출여부(통합탭 순위)": "5", "노출여부(카페구좌순위)": "3"},
            ]
        },
    }
    _write_backup(tmp_path, "backup_t1.json", payload_t1)
    _write_backup(tmp_path, "backup_t2.json.gz", payload_t2, gzipped=True)  # gzip 인식 검증
    _write_backup(tmp_path, "backup_t3.json", payload_t3)
    return str(tmp_path)


class TestH1TimelineBuild:
    """H1: build_timeline_rows 검증 — 백업 union read + 시점 정렬."""

    def test_build_rows_from_mixed_json_and_gzip(self, sample_backups_dir):
        """H1: .json + .json.gz 둘 다 read = union 정합."""
        from timeline_analyzer import build_timeline_rows
        rows = build_timeline_rows(sample_backups_dir)
        # 3 시점 × 1 행 = 3 row
        assert len(rows) == 3
        # 시점 정렬 검증 (= 오름차순)
        timestamps = [r["시점"] for r in rows]
        assert timestamps == sorted(timestamps)

    def test_row_fields_complete(self, sample_backups_dir):
        """H1: 컬럼 = 탭, 행, 키워드, link, 시점, K, L, M 의무 존재."""
        from timeline_analyzer import build_timeline_rows
        rows = build_timeline_rows(sample_backups_dir)
        assert len(rows) > 0
        first = rows[0]
        for col in ["탭", "행", "키워드", "link", "시점", "K", "L", "M"]:
            assert col in first, f"컬럼 {col} 누락"
        assert first["키워드"] == "탈모샴푸"
        assert first["link"] == "https://cafe.naver.com/cosmania/111"

    def test_empty_keyword_rows_skipped(self, tmp_path):
        """H1: 키워드 빈 행 = 분석 대상 X (T-M13 학습 정합)."""
        from timeline_analyzer import build_timeline_rows
        payload = {
            "timestamp": "2026-05-18T06:00:00+09:00",
            "run_id": "run_empty",
            "spreadsheet_id": "sheet1",
            "tabs": {
                "샴푸 카외": [
                    {"_row": 2, "키워드": "", "링크": "", "노출영역": ""},  # skip
                    {"_row": 3, "키워드": "탈모", "링크": "", "노출영역": "미노출"},
                ]
            },
        }
        _write_backup(tmp_path, "b.json", payload)
        rows = build_timeline_rows(str(tmp_path))
        # 키워드 빈 행 1개 제외 = 1 row
        assert len(rows) == 1
        assert rows[0]["키워드"] == "탈모"


class TestH1AnomalyDetection:
    """H1: detect_anomaly_transitions 검증 — loss / recovery 자동 검출."""

    def test_loss_transition_detected(self, sample_backups_dir):
        """H1: AB → 누락 = transition_type='loss' 검출."""
        from timeline_analyzer import build_timeline_rows, detect_anomaly_transitions
        rows = build_timeline_rows(sample_backups_dir)
        anomaly_map = detect_anomaly_transitions(rows)
        key = ("샴푸 카외", "탈모샴푸", "https://cafe.naver.com/cosmania/111")
        assert key in anomaly_map
        transitions = anomaly_map[key]
        # T1 → T2 = AB → 누락 (loss) / T2 → T3 = 누락 → AB (recovery)
        loss_transitions = [t for t in transitions if t["transition_type"] == "loss"]
        assert len(loss_transitions) == 1
        assert loss_transitions[0]["prev_K"] == "AB"
        assert loss_transitions[0]["new_K"] == "누락"

    def test_recovery_transition_detected(self, sample_backups_dir):
        """H1: 누락 → AB = transition_type='recovery' 검출."""
        from timeline_analyzer import build_timeline_rows, detect_anomaly_transitions
        rows = build_timeline_rows(sample_backups_dir)
        anomaly_map = detect_anomaly_transitions(rows)
        key = ("샴푸 카외", "탈모샴푸", "https://cafe.naver.com/cosmania/111")
        transitions = anomaly_map[key]
        recovery = [t for t in transitions if t["transition_type"] == "recovery"]
        assert len(recovery) == 1
        assert recovery[0]["prev_K"] == "누락"
        assert recovery[0]["new_K"] == "AB"

    def test_stable_no_transitions(self, tmp_path):
        """H1: K 변화 X = transition 0건 (= 안정 상태)."""
        from timeline_analyzer import build_timeline_rows, detect_anomaly_transitions
        payload_t1 = {
            "timestamp": "2026-05-15T06:00:00+09:00",
            "spreadsheet_id": "sheet1",
            "tabs": {"샴푸 카외": [
                {"_row": 2, "키워드": "kw", "링크": "https://cafe.naver.com/iroid/1",
                 "노출영역": "AB", "노출여부(통합탭 순위)": "1", "노출여부(카페구좌순위)": "1"},
            ]},
        }
        payload_t2 = {
            "timestamp": "2026-05-16T06:00:00+09:00",
            "spreadsheet_id": "sheet1",
            "tabs": {"샴푸 카외": [
                {"_row": 2, "키워드": "kw", "링크": "https://cafe.naver.com/iroid/1",
                 "노출영역": "AB", "노출여부(통합탭 순위)": "1", "노출여부(카페구좌순위)": "1"},
            ]},
        }
        _write_backup(tmp_path, "b1.json", payload_t1)
        _write_backup(tmp_path, "b2.json", payload_t2)
        rows = build_timeline_rows(str(tmp_path))
        anomaly_map = detect_anomaly_transitions(rows)
        # 변화 X = anomaly_map 비어있거나 transition 0건
        assert all(len(v) == 0 for v in anomaly_map.values()) or len(anomaly_map) == 0

    def test_deletion_transition_detected_as_loss(self, tmp_path):
        """H1: AB → 삭제 = loss transition (= 사장님 매출 ↓ 시점 매핑 의무)."""
        from timeline_analyzer import build_timeline_rows, detect_anomaly_transitions
        payload_t1 = {
            "timestamp": "2026-05-15T06:00:00+09:00",
            "spreadsheet_id": "sheet1",
            "tabs": {"샴푸 카외": [
                {"_row": 2, "키워드": "kw", "링크": "https://cafe.naver.com/iroid/1",
                 "노출영역": "AB"},
            ]},
        }
        payload_t2 = {
            "timestamp": "2026-05-16T06:00:00+09:00",
            "spreadsheet_id": "sheet1",
            "tabs": {"샴푸 카외": [
                {"_row": 2, "키워드": "kw", "링크": "https://cafe.naver.com/iroid/1",
                 "노출영역": "삭제"},
            ]},
        }
        _write_backup(tmp_path, "b1.json", payload_t1)
        _write_backup(tmp_path, "b2.json", payload_t2)
        rows = build_timeline_rows(str(tmp_path))
        anomaly_map = detect_anomaly_transitions(rows)
        key = ("샴푸 카외", "kw", "https://cafe.naver.com/iroid/1")
        assert key in anomaly_map
        loss = [t for t in anomaly_map[key] if t["transition_type"] == "loss"]
        assert len(loss) == 1
        assert loss[0]["new_K"] == "삭제"


class TestH1CSVOutput:
    """H1: write_csv + write_anomaly_report 검증 — 출력 컬럼 정합."""

    def test_csv_columns_complete(self, sample_backups_dir, tmp_path):
        """H1: CSV 컬럼 = 탭, 행, 키워드, link, 시점, K, L, M (의무)."""
        from timeline_analyzer import build_timeline_rows, write_csv
        rows = build_timeline_rows(sample_backups_dir)
        output = str(tmp_path / "timeline.csv")
        write_csv(rows, output)
        assert os.path.exists(output)
        with open(output, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == ["탭", "행", "키워드", "link", "시점", "K", "L", "M"]
            written = list(reader)
        assert len(written) == 3

    def test_anomaly_csv_columns(self, sample_backups_dir, tmp_path):
        """H1: anomaly CSV 컬럼 = 탭, 키워드, link, 시점, prev_K, new_K, transition_type."""
        from timeline_analyzer import (
            build_timeline_rows, detect_anomaly_transitions, write_anomaly_report,
        )
        rows = build_timeline_rows(sample_backups_dir)
        anomaly_map = detect_anomaly_transitions(rows)
        output = str(tmp_path / "anomalies.csv")
        total = write_anomaly_report(anomaly_map, output)
        assert total >= 2  # loss + recovery 최소 2
        with open(output, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == [
                "탭", "키워드", "link", "시점", "prev_K", "new_K", "transition_type",
            ]

    def test_csv_output_dir_auto_created(self, sample_backups_dir, tmp_path):
        """H1: 출력 디렉토리 자동 생성 (= 사장님 운영 편의)."""
        from timeline_analyzer import build_timeline_rows, write_csv
        rows = build_timeline_rows(sample_backups_dir)
        # 존재하지 않는 sub-dir 안 output 경로
        output = str(tmp_path / "subdir" / "timeline.csv")
        write_csv(rows, output)
        assert os.path.exists(output)


class TestH1NoBackups:
    """H1: 백업 파일 없음 / 손상 시 안전 동작 검증."""

    def test_empty_dir_returns_empty_rows(self, tmp_path):
        """H1: 백업 디렉토리 빈 = rows 0건 (= 예외 X)."""
        from timeline_analyzer import build_timeline_rows
        rows = build_timeline_rows(str(tmp_path))
        assert rows == []

    def test_corrupted_json_skipped(self, tmp_path):
        """H1: 손상된 JSON 파일 = skip + 다음 파일 처리 (= 예외 X)."""
        from timeline_analyzer import build_timeline_rows
        # 손상 파일
        with open(str(tmp_path / "broken.json"), "w", encoding="utf-8") as f:
            f.write("{ not valid json ")
        # 정상 파일
        payload = {
            "timestamp": "2026-05-18T06:00:00+09:00",
            "spreadsheet_id": "sheet1",
            "tabs": {"샴푸 카외": [{"_row": 2, "키워드": "kw", "링크": "", "노출영역": "미노출"}]},
        }
        _write_backup(tmp_path, "good.json", payload)
        rows = build_timeline_rows(str(tmp_path))
        # 손상 파일 skip + 정상 파일 1 row 반영
        assert len(rows) == 1
