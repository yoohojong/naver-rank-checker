"""T-M82 (D-027 2026-05-17) restore_backup.py 회귀 test.

사장님 명시 컨벤션:
- 백업 JSON read → 시트 직접 write (HEADER_AREA/L/M/JISIKIN/LINK 컬럼)
- D-023/D-026 가드 = restore-mode = HEADER_LINK 도 허용 (= 유일 예외)
- 매 탭 = 1회 batch_update API 호출
- dry-run flag = 실제 write 안 함 = 시뮬레이션
- spreadsheet_id 불일치 = 복원 거부
"""
import json
import os
import sys
import tempfile
from unittest.mock import patch, MagicMock

import pytest

# scripts/ 모듈 path 추가
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts"))


@pytest.fixture
def backup_payload(tmp_path):
    """fixture: 백업 JSON 파일 생성."""
    payload = {
        "timestamp": "2026-05-17T18:00:00+09:00",
        "run_id": "test12345",
        "spreadsheet_id": "test_sheet_id",
        "tabs": {
            "샴푸 카외": [
                {
                    "_row": 2, "_tab": "샴푸 카외",
                    "키워드": "kw1",
                    "링크": "https://cafe.naver.com/cosmania/111",
                    "노출영역": "AB",
                    "노출여부(통합탭 순위)": "3",
                    "노출여부(카페구좌순위)": "2",
                    "지식인탭": "",
                },
                {
                    "_row": 3, "_tab": "샴푸 카외",
                    "키워드": "kw2",
                    "링크": "",
                    "노출영역": "미노출",
                    "노출여부(통합탭 순위)": "",
                    "노출여부(카페구좌순위)": "",
                    "지식인탭": "",
                },
            ]
        }
    }
    backup_file = tmp_path / "test12345_20260517T180000.json"
    with open(backup_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return str(backup_file)


class TestRestoreBackup:
    """scripts/restore_backup.py 회귀 test."""

    def test_dry_run_no_write(self, backup_payload, monkeypatch):
        """dry-run = 실제 write X = SheetsClient 호출 X."""
        monkeypatch.setattr("src.config.SPREADSHEET_ID", "test_sheet_id")
        monkeypatch.setattr("src.config.SERVICE_ACCOUNT_JSON", '{"fake": "creds"}')
        # restore_backup module 안 SPREADSHEET_ID/SERVICE_ACCOUNT_JSON = src.config 에서 import 시점
        # → restore_backup module-level reload 필요
        if "restore_backup" in sys.modules:
            del sys.modules["restore_backup"]
        monkeypatch.setattr("src.config.SPREADSHEET_ID", "test_sheet_id")
        monkeypatch.setattr("src.config.SERVICE_ACCOUNT_JSON", '{"fake": "creds"}')

        from importlib import import_module
        rb = import_module("restore_backup")
        rb.SPREADSHEET_ID = "test_sheet_id"
        rb.SERVICE_ACCOUNT_JSON = '{"fake": "creds"}'

        # dry-run = SheetsClient 호출 X
        summary = rb.restore_backup(backup_payload, dry_run=True)
        assert summary["total_rows"] == 2
        assert "샴푸 카외" in summary["tabs"]
        # dry-run 시 cells 추정 ≥ 1 (sanity)
        assert summary["tabs"]["샴푸 카외"]["cells_estimate"] >= 1

    def test_real_restore_calls_batch_update(self, backup_payload, monkeypatch):
        """실제 복원 = SheetsClient 인증 + batch_update 호출."""
        if "restore_backup" in sys.modules:
            del sys.modules["restore_backup"]
        from importlib import import_module
        rb = import_module("restore_backup")
        rb.SPREADSHEET_ID = "test_sheet_id"
        rb.SERVICE_ACCOUNT_JSON = '{"type": "service_account", "client_email": "x@x.iam.gserviceaccount.com", "private_key": "-----BEGIN PRIVATE KEY-----\\nFAKE\\n-----END PRIVATE KEY-----\\n", "token_uri": "https://oauth2.googleapis.com/token"}'

        mock_client = MagicMock()
        mock_ws = MagicMock()
        # 사장님 시트 헤더 (HEADER_AREA / L / M / 링크 / 지식인탭 포함)
        mock_ws.row_values.return_value = [
            "키워드", "링크", "노출영역", "노출여부(통합탭 순위)",
            "노출여부(카페구좌순위)", "지식인탭",
        ]
        mock_client.spreadsheet.worksheet.return_value = mock_ws

        with patch("restore_backup.SheetsClient", return_value=mock_client):
            summary = rb.restore_backup(backup_payload, dry_run=False)

        # batch_update 1회 호출 검증 (탭별 1회)
        mock_ws.batch_update.assert_called_once()
        # 정상 복원 = total_cells ≥ 1
        assert summary["total_cells"] >= 1

    def test_spreadsheet_id_mismatch_refuses(self, backup_payload, monkeypatch, capsys):
        """T-M82 안전 가드: 백업 spreadsheet_id ≠ 현재 SPREADSHEET_ID = 복원 거부."""
        if "restore_backup" in sys.modules:
            del sys.modules["restore_backup"]
        from importlib import import_module
        rb = import_module("restore_backup")
        # 현재 SPREADSHEET_ID = 다른 값 = 백업 안 fake_id 불일치
        rb.SPREADSHEET_ID = "DIFFERENT_SHEET_ID"
        rb.SERVICE_ACCOUNT_JSON = '{"fake": "creds"}'

        summary = rb.restore_backup(backup_payload, dry_run=False)
        # mismatch = error 반환 (write X)
        assert summary.get("error") == "spreadsheet_id_mismatch"

    def test_missing_backup_file_raises(self, monkeypatch):
        """T-M82: 백업 파일 없으면 FileNotFoundError raise."""
        if "restore_backup" in sys.modules:
            del sys.modules["restore_backup"]
        from importlib import import_module
        rb = import_module("restore_backup")
        rb.SPREADSHEET_ID = "test_sheet_id"
        rb.SERVICE_ACCOUNT_JSON = '{"fake": "creds"}'

        with pytest.raises(FileNotFoundError):
            rb.restore_backup("/nonexistent/path.json", dry_run=True)

    def test_restore_columns_includes_header_link(self):
        """T-M82: D-023 가드 우회 = HEADER_LINK 도 RESTORE_COLUMNS 안 포함 (= 사고 복원 시 의무)."""
        if "restore_backup" in sys.modules:
            del sys.modules["restore_backup"]
        from importlib import import_module
        rb = import_module("restore_backup")
        from src.sheets import HEADER_AREA, HEADER_L, HEADER_M, HEADER_JISIKIN, HEADER_LINK

        # 5 컬럼 모두 포함 (= 진짜 사고 복원 시 link 복원 의무)
        assert HEADER_AREA in rb.RESTORE_COLUMNS
        assert HEADER_L in rb.RESTORE_COLUMNS
        assert HEADER_M in rb.RESTORE_COLUMNS
        assert HEADER_JISIKIN in rb.RESTORE_COLUMNS
        assert HEADER_LINK in rb.RESTORE_COLUMNS
        assert len(rb.RESTORE_COLUMNS) == 5
