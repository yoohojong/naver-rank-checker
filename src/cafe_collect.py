"""cafe_collect: 네이버 카페글 검색 Open API로 제품 후기/불만 카페글을 수집.

카페외부 원고 '재료'(4 대안 / 5 브랜드 단계) — 타사 브랜드 샴푸를 쓰는 사람들의
불만·불안 표현을 카페글에서 자동 수집한다. 지식인 수집(jisikin_collect)과 동일한
네이버 Open API 키(NAVER_OPENAPI_CLIENT_ID/SECRET)·동일 인증 헤더를 쓴다.
공식 Open API(합법·무료)라 스크래핑 anti-bot/법 리스크가 없다.

이 모듈은 '수집 코어'만 담당한다 — 결과를 어디에 저장할지는 호출부가 결정한다.
"""
from __future__ import annotations

import html as _html
import re

from curl_cffi import requests

CAFE_API_URL = "https://openapi.naver.com/v1/search/cafearticle.json"

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    """응답 title/description의 <b> 태그 제거 + HTML 엔티티 복원."""
    return _html.unescape(_TAG_RE.sub("", text or "")).strip()


def fetch_cafe(
    keyword: str,
    *,
    client_id: str,
    client_secret: str,
    display: int = 20,
    start: int = 1,
    sort: str = "sim",
    timeout: int = 10,
) -> list[dict]:
    """키워드로 카페글을 검색해 [{title, link, description, cafename, cafeurl}] 반환.

    Args:
        keyword: 검색어. 공백이면 빈 리스트.
        client_id / client_secret: 네이버 개발자센터 앱 키(지식인과 동일).
        display: 1~100 (API 상한 100).
        start: 1~1000.
        sort: 'sim'(정확도순) | 'date'(최신순).

    Raises:
        RuntimeError: 키 미설정 또는 API 응답이 200이 아닐 때.
    """
    kw = (keyword or "").strip()
    if not kw:
        return []
    if not client_id or not client_secret:
        raise RuntimeError(
            "NAVER_OPENAPI_CLIENT_ID/SECRET 미설정 — 네이버 개발자센터 무료 앱 키가 필요합니다."
        )

    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }
    params = {
        "query": kw,
        "display": max(1, min(int(display), 100)),
        "start": max(1, min(int(start), 1000)),
        "sort": sort if sort in ("sim", "date") else "sim",
    }

    r = requests.get(CAFE_API_URL, headers=headers, params=params, timeout=timeout)
    if r.status_code != 200:
        body = (r.text or "")[:200]
        for _secret in (client_secret, client_id):
            if _secret:
                body = body.replace(_secret, "[가림]")
        raise RuntimeError(f"카페글 Open API 오류 {r.status_code}: {body}")

    data = r.json() or {}
    items = data.get("items", []) or []
    results: list[dict] = []
    for it in items:
        results.append(
            {
                "title": _clean(it.get("title", "")),
                "link": it.get("link", ""),
                "description": _clean(it.get("description", "")),
                "cafename": _clean(it.get("cafename", "")),
                "cafeurl": it.get("cafeurl", ""),
            }
        )
    return results, data
