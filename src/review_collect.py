"""review_collect: Apify로 네이버 스마트스토어 리뷰를 무인 자동 수집 + 저점(1~3점) 필터.

카페외부 원고 '재료'(4 대안 / 5 브랜드 단계) — 경쟁/제품의 불만·불안(저점 리뷰)을 모은다.
네이버 anti-bot·프록시·캡차는 Apify 벤더가 떠안고, 우리는 REST API만 호출(직원 수작업 0).

⚠️ 법 회색지대: 경쟁사 리뷰 대량 수집·재사용은 네이버 ToS 위반 + 민사(DB권·부정경쟁) 리스크.
   → 소량 선별 / 원문 재게시 금지·사실만 추출+표현 변형 / 본격 운영 전 변호사 검토 전제.
키: APIFY_TOKEN (유료 Apify 계정). 미설정 시 RuntimeError.
이 모듈은 '수집 코어'만 — 저장(시트/보관함)·사용은 호출부가 결정한다.
"""
from __future__ import annotations

import html as _html
import re

from curl_cffi import requests

APIFY_BASE = "https://api.apify.com/v2"

_TAG_RE = re.compile(r"<[^>]+>")
# 액터마다 키 이름이 달라 흔한 후보들을 순서대로 탐색(스키마 변동에 견고).
_STAR_KEYS = ("score", "rating", "star", "stars", "reviewScore", "grade", "별점")
_TEXT_KEYS = ("content", "review", "reviewContent", "text", "body", "comment", "내용")
_DATE_KEYS = ("date", "createdAt", "reviewDate", "writeDate", "작성일")


def _clean(text: str) -> str:
    return _html.unescape(_TAG_RE.sub("", text or "")).strip()


def _first(d: dict, keys: tuple) -> object:
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return None


def _to_star(v: object):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def fetch_low_star_reviews(
    product_urls,
    *,
    apify_token: str,
    actor_id: str,
    max_star: int = 3,
    input_field: str = "startUrls",
    extra_input: dict | None = None,
    timeout: int = 300,
) -> list[dict]:
    """스마트스토어 리뷰 중 별점 <= max_star 만 [{star, content, date, source}] 반환.

    액터마다 '대상 입력 필드'가 다르므로 input_field 로 맞춘다(리뷰 수집 안정성 핵심):
      - 상품 URL 직접 입력 액터(예: styleindexamerica~kr-naver-stores-scraper):
          input_field='productUrls'(또는 'startUrls'), product_urls=상품 URL 리스트.
      - 브랜드 단위 액터(추천: accurate_dancer~naver-smart-store-monitor, 성공률 95%대):
          input_field='brandUrls', product_urls=브랜드 슬러그 리스트('brand.naver.com/<슬러그>'),
          extra_input={'includeReviews': True, 'maxReviewPages': 3} 권장.

    Args:
        product_urls: 대상 리스트(액터에 따라 상품 URL 또는 브랜드 슬러그).
        apify_token: 유료 Apify 계정 토큰(Authorization 헤더로 전송 — URL/로그 노출 회피).
        actor_id: Apify 액터 id (예: 'accurate_dancer~naver-smart-store-monitor').
        max_star: 이 별점 이하만 수집(기본 3 = 저점 1~3점).
        input_field: 액터 input 의 대상 필드명. startUrls/productUrls=[{url}] 형태,
            그 외(brandUrls 등)=문자열 리스트. 기본 'startUrls'.
        extra_input: 액터별 추가 input(예: includeReviews/maxReviewPages/maxReviews).

    Raises:
        RuntimeError: 토큰 미설정 또는 Apify 응답 비정상.
    """
    urls = [u for u in (product_urls or []) if u]
    if not urls:
        return []
    if not apify_token:
        raise RuntimeError("APIFY_TOKEN 미설정 — 유료 Apify 계정 토큰이 필요합니다.")

    payload: dict = dict(extra_input or {})
    if input_field not in payload:
        if input_field in ("startUrls", "productUrls"):
            payload[input_field] = [{"url": u} for u in urls]
        else:  # brandUrls 등 = 문자열 슬러그 리스트
            payload[input_field] = list(urls)
    # 토큰은 ?token= 쿼리 대신 Authorization 헤더로 (URL/로그 노출 회피).
    headers = {"Authorization": f"Bearer {apify_token}"}
    api = f"{APIFY_BASE}/acts/{actor_id}/run-sync-get-dataset-items"

    r = requests.post(api, headers=headers, json=payload, timeout=timeout)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Apify 오류 {r.status_code}: {r.text[:200]}")

    items = r.json() or []
    out: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        star = _to_star(_first(it, _STAR_KEYS))
        if star is None or star > max_star:
            continue
        out.append(
            {
                "star": star,
                "content": _clean(str(_first(it, _TEXT_KEYS) or "")),
                "date": _first(it, _DATE_KEYS) or "",
                "source": it.get("url") or it.get("productUrl") or "",
            }
        )
    return out
