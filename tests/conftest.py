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


@pytest.fixture(autouse=True)
def _no_actions_run_context(monkeypatch):
    """GitHub Actions 안에서 검사를 돌려도 그 실행의 종류 · 시도 번호가 검사에 새지 않게 치운다.

    텔레그램 '같은 회차 문자 생략'이 손으로 돌린 실행(workflow_dispatch) · 다시 돌린 시도(2회차)를
    보고 판단한다(2026-10-31). 검사 실행 환경 값이 끼면 생략 검사가 저절로 갈린다. 필요한 검사는 스스로 넣는다.
    """
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.delenv("GITHUB_RUN_ATTEMPT", raising=False)


@pytest.fixture
def fixtures_dir():
    return FIXTURES_DIR


@pytest.fixture
def load_fixture(fixtures_dir):
    def _load(name: str) -> str:
        path = fixtures_dir / name
        return path.read_text(encoding="utf-8")
    return _load
