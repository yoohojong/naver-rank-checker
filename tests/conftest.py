"""pytest 공통 fixtures."""
from pathlib import Path
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir():
    return FIXTURES_DIR


@pytest.fixture
def load_fixture(fixtures_dir):
    def _load(name: str) -> str:
        path = fixtures_dir / name
        return path.read_text(encoding="utf-8")
    return _load
