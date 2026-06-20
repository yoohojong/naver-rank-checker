"""jisikin_collect: 네이버 지식iN 검색 Open API로 '증상' 키워드의 지식인 Q&A를 수집.

카페외부 원고 '재료'(3 증상 단계) — 고객의 고민·표현·언어를 지식인에서 자동 수집한다.
공식 Open API(합법·무료)라 스크래핑 anti-bot/법 리스크가 없다.

키: NAVER_OPENAPI_CLIENT_ID / NAVER_OPENAPI_CLIENT_SECRET (네이버 개발자센터 무료 앱 등록).
이 모듈은 '수집 코어'만 담당한다 — 결과를 어디에 저장할지(시트/보관함)는 호출부가 결정한다.
"""
from __future__ import annotations

import html as _html
import re

from curl_cffi import requests

KIN_API_URL = "https://openapi.naver.com/v1/search/kin.json"

# 네이버 Open API 응답의 <b>강조</b> 태그 제거용.
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    """응답 title/description의 <b> 태그 제거 + HTML 엔티티(&amp; 등) 복원."""
    return _html.unescape(_TAG_RE.sub("", text or "")).strip()


def fetch_jisikin(
    keyword: str,
    *,
    client_id: str,
    client_secret: str,
    display: int = 20,
    start: int = 1,
    sort: str = "sim",
    timeout: int = 10,
) -> list[dict]:
    """키워드로 지식iN Q&A를 검색해 [{title, link, description}] 리스트를 반환.

    Args:
        keyword: 검색어(증상 키워드). 공백이면 빈 리스트.
        client_id / client_secret: 네이버 개발자센터 앱 키(무료).
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

    r = requests.get(KIN_API_URL, headers=headers, params=params, timeout=timeout)
    if r.status_code != 200:
        # 응답 본문에 혹시라도 키 값이 섞여 로그로 새지 않도록 실제 키 값을 가린다(방어).
        body = (r.text or "")[:200]
        for _secret in (client_secret, client_id):
            if _secret:
                body = body.replace(_secret, "[가림]")
        raise RuntimeError(f"지식iN Open API 오류 {r.status_code}: {body}")

    items = (r.json() or {}).get("items", []) or []
    results: list[dict] = []
    for it in items:
        results.append(
            {
                "title": _clean(it.get("title", "")),
                "link": it.get("link", ""),
                "description": _clean(it.get("description", "")),
            }
        )
    return results
