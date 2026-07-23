"""pytest 공통 fixtures."""
from pathlib import Path
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _no_paid_llm_in_tests(monkeypatch):
    """검사 도중 유료 판정기를 실제로 부르지 않게 열쇠를 치운다.

    판정기가 유료(Anthropic) 먼저 → 무료(Groq) 순으로 가므로, 열쇠가 환경에 남아
    있으면 가짜 응답 대신 진짜 호출이 나가 돈이 든다. 유료 경로를 보는 검사는
    이 fixture 뒤에 스스로 열쇠를 넣는다.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


@pytest.fixture
def fixtures_dir():
    return FIXTURES_DIR


@pytest.fixture
def load_fixture(fixtures_dir):
    def _load(name: str) -> str:
        path = fixtures_dir / name
        return path.read_text(encoding="utf-8")
    return _load
