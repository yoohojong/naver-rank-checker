"""report_render: 대시보드 HTML 문자열 → PNG 바이트(Playwright chromium headless). 2026-07-13.

⚠️ 순수 렌더(외부 네트워크 없음 — set_content 로 인메모리 렌더). 기존 라이브 흐름과 무관한 순수 추가.
- html_to_png(html, width=600) → 전체(full_page) PNG 바이트. viewport width=600, device_scale_factor=2(선명).
- Playwright 미설치 / chromium 미설치 등 렌더 불가 = RenderError(명확한 안내 메시지)로 즉시 실패.
"""
from __future__ import annotations


class RenderError(RuntimeError):
    """Playwright 미설치·chromium 미설치·렌더 실패 등 이미지 생성 불가 상태."""


def html_to_png(html: str, width: int = 600) -> bytes:
    """자체완결 HTML 문서 → 전체 PNG 바이트.

    viewport 폭 width(기본 600), full_page 스크린샷, device_scale_factor=2(2배 해상도).
    Playwright/chromium 미설치 시 RenderError 로 명확히 실패(조용한 빈 이미지 금지).
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise RenderError(
            "playwright 미설치 — 'pip install -r requirements.txt' 후 "
            "'python -m playwright install chromium' 를 실행하세요."
        ) from e

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as e:  # noqa: BLE001 — 브라우저 바이너리 미설치 등
                raise RenderError(
                    "chromium 실행 실패 — 'python -m playwright install chromium' 로 "
                    f"브라우저를 설치하세요 ({type(e).__name__})."
                ) from e
            try:
                ctx = browser.new_context(
                    viewport={"width": width, "height": 900},
                    device_scale_factor=2,
                )
                pg = ctx.new_page()
                pg.set_content(html, wait_until="networkidle")
                return pg.screenshot(full_page=True, type="png")
            finally:
                browser.close()
    except RenderError:
        raise
    except Exception as e:  # noqa: BLE001 — 그 외 렌더 실패도 명확한 예외로 승격
        raise RenderError(f"HTML→PNG 렌더 실패: {type(e).__name__}") from e
