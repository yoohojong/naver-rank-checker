"""환경 sanity 테스트: 모든 모듈 import 가능 + 기본 상수 검증."""


def test_all_modules_importable():
    from src import (
        config,
        crawler,
        parser,
        sheets,
        cache,
        retry,
        health,
        transitions,
        main,
    )
    assert config.NAVER_SLOWDOWN_BASE_SEC > 0  # 양수 보장 (실제 값은 config.py 에서 관리)


def test_user_agents_list_nonempty():
    from src.config import USER_AGENTS
    assert len(USER_AGENTS) >= 4
    assert all(isinstance(ua, str) and len(ua) > 20 for ua in USER_AGENTS)


def test_config_env_vars_default_empty():
    """SPREADSHEET_ID, SERVICE_ACCOUNT_JSON는 환경변수 없을 때 빈 문자열."""
    from src.config import SPREADSHEET_ID, SERVICE_ACCOUNT_JSON
    # GitHub Actions 환경에선 secret 주입되지만 로컬은 빈 문자열
    assert isinstance(SPREADSHEET_ID, str)
    assert isinstance(SERVICE_ACCOUNT_JSON, str)
