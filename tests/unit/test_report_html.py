"""report_html 단위 테스트 (2026-07-13).

검증: 일·주·월 HTML 생성기가 완결 문서(doctype~/html) + 필수 섹션 + 실제 숫자 포함.
context 는 report_metrics 로 합성 데이터에서 계산(생성기-계산 정합). 외부 의존 0.
"""
from src.report_html import daily_html, monthly_html, weekly_html
from src.report_metrics import daily_context, monthly_context, weekly_context
from tests.unit.test_report_metrics import _dataset


def _is_full_doc(html: str) -> bool:
    return html.lstrip().startswith("<!doctype html>") and html.rstrip().endswith("</html>")


# ── 일간 ─────────────────────────────────────────────────────────────────────
def test_daily_html_full_document_and_sections():
    html = daily_html(daily_context(_dataset()))
    assert _is_full_doc(html)
    assert "<style>" in html  # 인라인 CSS 자체완결
    assert "prefers-color-scheme" in html  # 다크 대응
    for section in ["오늘 한눈에", "제품별 상위노출", "목표 달성률",
                    "어제 → 오늘 변화", "상위노출 추세", "날짜별 발행 → 상위노출",
                    "발행 후 며칠에 뜨나", "노출 유형 분포"]:
        assert section in html, f"섹션 누락: {section}"


def test_daily_html_shows_numbers():
    ctx = daily_context(_dataset())
    html = daily_html(ctx)
    assert "7/10" in html
    assert f"전체 {ctx['total']}개 중" in html
    assert f"{ctx['need_publish']}개" in html  # 필요 발행량 노출
    # 정합식(어제 + 신규 − 이탈 = 오늘)
    assert "어제" in html and "= 오늘" in html


def test_daily_html_empty():
    html = daily_html(daily_context({}))
    assert _is_full_doc(html)
    assert "데이터" in html


# ── 주간 ─────────────────────────────────────────────────────────────────────
def test_weekly_html_sections():
    html = weekly_html(weekly_context(_dataset()))
    assert _is_full_doc(html)
    for section in ["이번 주 한눈에", "목표 대비", "상위노출 추세",
                    "카테고리별 달성률", "이탈 Top"]:
        assert section in html, f"섹션 누락: {section}"
    assert "7/8~7/10" in html
    assert "비듬샴푸" in html  # 이탈 Top 키워드


# ── 월간 ─────────────────────────────────────────────────────────────────────
def test_monthly_html_sections():
    html = monthly_html(monthly_context(_dataset()))
    assert _is_full_doc(html)
    for section in ["이번 달 한눈에", "주별 추세", "카테고리별 성과",
                    "다음달 필요 발행", "진단", "신규 유입·매출 동행"]:
        assert section in html, f"섹션 누락: {section}"
    assert "각질" in html  # Best 키워드
    assert "GA4" in html   # 자리표시


def test_monthly_html_hypothesis_marking():
    """진단에 가설이 있으면 'hyp' 클래스로 표기(데이터 확정 vs 가설 구분)."""
    ctx = monthly_context(_dataset())
    if any(str(line).startswith("가설:") for line in ctx["diagnosis"]):
        html = monthly_html(ctx)
        assert "class=\"hyp\"" in html
