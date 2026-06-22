# -*- coding: utf-8 -*-
"""review_glowpick: 글로우픽(glowpick.com) 제품의 저점 후기를 실브라우저로 수집.

카페외부 원고 '재료'(경쟁사 제품의 불만·사용감 디테일)를 모으는 3소스(네이버/화해/글로우픽) 중 하나.
글로우픽은 로그인월·봇차단이 없어 가장 쉽다(2026-06-23 실증). 후기는 `/products/{id}/reviews`
페이지를 스크롤하면 화면에 렌더된다.

추출 방식(정찰 확정): 후기 API(`/api/proxy/reviewApiK/api/reviews`)는 protobuf 라 복제가 어렵고,
별점 별(<li class*=starRed>)은 후기 본문과 형제 구조라 DOM 선택자도 까다롭다. → **렌더된 후기영역의
'텍스트'를 정규식으로 파싱**한다. 글로우픽 후기 텍스트 한 건 = `{작성자}{나이/타입} {별점} {YYYY.MM.DD}
{본문}`. 별점 = 날짜 바로 앞 숫자(0.5~5), 본문 = 날짜 뒤 텍스트(다음 후기 시작 전까지).

수집 기준(사장님 확정): 별점 낮은(<=max_score, 기본 2) 후기 + **원문 그대로**(요약/자르기 X).
출력(3소스 공통): [{score, content, product_name, source_url, source}]
"""
from __future__ import annotations

import re
import time

from playwright.sync_api import sync_playwright

SOURCE = "글로우픽"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_PRODUCT_RE = re.compile(r"glowpick\.com/products/(\d+)")

# 후기 한 건 = (별점)(날짜)(본문). 본문은 다음 후기의 '별점+날짜' 시작 전까지(비탐욕, 개행 포함).
_REVIEW_RE = re.compile(
    r"([0-5](?:\.5)?)\s+(\d{4}\.\d{2}\.\d{2})\s+(.+?)(?=\s+[0-5](?:\.5)?\s+\d{4}\.\d{2}\.\d{2}|\Z)",
    re.S,
)
# 본문 끝에 붙는 다음 후기 '작성자 나이/타입' 토막을 떼기 위한 꼬리 패턴(휴리스틱, 과하지 않게).
_TAIL_RE = re.compile(r"\s+\S{1,12}\s+\d{0,2}[가-힣/]*$")


def _search_product_id(pg, keyword: str) -> str | None:
    """글로우픽 검색에서 첫 제품 id 확보. 이미 숫자 id/URL 이면 그대로 사용."""
    kw = (keyword or "").strip()
    if kw.isdigit():
        return kw
    m = _PRODUCT_RE.search(kw)
    if m:
        return m.group(1)
    pg.goto("https://www.glowpick.com/search?query=" + kw.replace(" ", "%20"),
            wait_until="domcontentloaded", timeout=45000)
    time.sleep(3)
    for _ in range(3):
        pg.mouse.wheel(0, 2000)
        time.sleep(0.8)
    blob = "\n".join(pg.eval_on_selector_all("a", "els => els.map(e => e.href).filter(Boolean)"))
    m = _PRODUCT_RE.search(blob + "\n" + pg.content())
    return m.group(1) if m else None


def _review_text(pg) -> str:
    """후기 리스트 영역의 렌더된 텍스트(없으면 body 전체)."""
    for sel in ("[class*=productReviewL]", "[class*=reviewsPage]"):
        try:
            t = pg.inner_text(sel)
            if t and len(t) > 50:
                return t
        except Exception:
            continue
    try:
        return pg.inner_text("body")
    except Exception:
        return ""


def parse_reviews(text: str) -> list[dict]:
    """후기 영역 텍스트 → [{score, content}] (별점=날짜 앞 숫자, 본문=날짜 뒤)."""
    out: list[dict] = []
    for m in _REVIEW_RE.finditer(text or ""):
        try:
            score = float(m.group(1))
        except ValueError:
            continue
        body = re.sub(r"\s+", " ", m.group(3)).strip()
        body = _TAIL_RE.sub("", body).strip()  # 다음 작성자 토막 제거(휴리스틱)
        if len(body) < 10:
            continue
        out.append({"score": score, "content": body})
    return out


def fetch_glowpick_lowstar(
    keyword_or_id: str,
    max_reviews: int = 100,
    max_score: float = 2.0,
    *,
    headless: bool = True,
    max_scrolls: int = 40,
) -> list[dict]:
    """글로우픽 제품의 저점(별점<=max_score) 후기를 수집. 원문 보존."""
    target = (keyword_or_id or "").strip()
    if not target:
        return []
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless, args=["--disable-blink-features=AutomationControlled"]
        )
        ctx = browser.new_context(
            user_agent=_UA, locale="ko-KR", viewport={"width": 1366, "height": 3000}
        )
        pg = ctx.new_page()
        try:
            pid = _search_product_id(pg, target)
            if not pid:
                return []
            url = f"https://www.glowpick.com/products/{pid}/reviews"
            pg.goto(url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(5)
            try:
                product_name = (pg.title() or "").split("|")[0].split("리뷰")[0].strip()[:80]
            except Exception:
                product_name = ""

            collected: dict[str, dict] = {}  # body[:50] → review
            stale = 0
            for _ in range(max_scrolls):
                for rv in parse_reviews(_review_text(pg)):
                    key = rv["content"][:50]
                    if key not in collected:
                        collected[key] = rv
                low = [r for r in collected.values() if r["score"] <= max_score]
                if len(low) >= max_reviews:
                    break
                before = len(collected)
                pg.mouse.wheel(0, 5000)
                time.sleep(1.5)
                if len(collected) == before:
                    stale += 1
                    if stale >= 4:
                        break
                else:
                    stale = 0

            results = [
                {
                    "score": r["score"], "content": r["content"],
                    "product_name": product_name, "source_url": url, "source": SOURCE,
                }
                for r in collected.values() if r["score"] <= max_score
            ]
            return results[:max_reviews]
        finally:
            browser.close()


if __name__ == "__main__":
    import json
    import sys

    arg = sys.argv[1] if len(sys.argv) > 1 else "161538"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    print(json.dumps(fetch_glowpick_lowstar(arg, max_reviews=n), ensure_ascii=False, indent=2))
