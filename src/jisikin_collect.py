"""jisikin_collect: 네이버 지식iN 검색 Open API로 '증상' 키워드의 지식인 Q&A를 수집.

카페외부 원고 '재료'(3 증상 단계) — 고객의 고민·표현·언어를 지식인에서 자동 수집한다.
공식 Open API(합법·무료)라 스크래핑 anti-bot/법 리스크가 없다.

키: NAVER_OPENAPI_CLIENT_ID / NAVER_OPENAPI_CLIENT_SECRET (네이버 개발자센터 무료 앱 등록).
이 모듈은 '수집 코어'만 담당한다 — 결과를 어디에 저장할지(시트/보관함)는 호출부가 결정한다.
"""
from __future__ import annotations

import html as _html
import re
import time as _time

from curl_cffi import requests

KIN_API_URL = "https://openapi.naver.com/v1/search/kin.json"

# 키워드 1건당 detail fetch 기본 상한 — 초과분은 description 폴백(GHA 60분 timeout 안전장치).
MAX_DETAIL_PER_KEYWORD = 30


class RateLimitError(RuntimeError):
    """네이버 API 429(rate-limit) 응답 시 raise — 일반 RuntimeError 와 구분해 채널 circuit-break용."""

# detail 페이지 GET 시 쓰는 브라우저 UA 위장(_proto_kin_material.py 와 동일 — anti-bot 완화).
_DETAIL_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# 네이버 Open API 응답의 <b>강조</b> 태그 제거용.
_TAG_RE = re.compile(r"<[^>]+>")

# detail 본문 정제용 — 보일러플레이트(UI/안내/약관 등) 줄 제거(_proto_kin_material.py JUNK 기반).
_DETAIL_JUNK = (
    "지식iN 서비스", "답변자 정보", "나도 궁금해요", "활동이 보류", "네이버는 사용자",
    "인터넷 익스플로러", "브라우저", "Whale", "로그인", "바로가기", "권장",
    "병원 위치", "진료 예약", "문의 전화", "프로필", "채택", "신고", "목록", "이용약관",
    "저작권", "고객센터", "애드포스트", "광고", "AI 답변이 도움",
)

# <script>/<style> 통째 제거(본문 텍스트 추출 전 노이즈 제거).
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S)
_WS_RE = re.compile(r"\s+")
_HANGUL_RE = re.compile(r"[가-힣]")


def _clean(text: str) -> str:
    """응답 title/description의 <b> 태그 제거 + HTML 엔티티(&amp; 등) 복원."""
    return _html.unescape(_TAG_RE.sub("", text or "")).strip()


def _strip_tags(h: str) -> str:
    """HTML 문자열에서 script/style 제거 후 모든 태그를 공백으로 치환 + 엔티티 복원."""
    h = _SCRIPT_STYLE_RE.sub(" ", h or "")
    h = _TAG_RE.sub(" ", h)
    return _html.unescape(h)


def _clean_lines(text: str) -> list[str]:
    """본문 텍스트를 줄 단위로 정제 — 짧은 줄/보일러플레이트/중복 제거(proto 동일).

    - 한글 8자 미만 줄 제거(메뉴/버튼 등 노이즈 차단).
    - _DETAIL_JUNK 포함 줄 제거.
    - 동일 줄 중복 제거(순서 보존).
    """
    out: list[str] = []
    seen: set[str] = set()
    for line in re.split(r"[\n\r]|\s{2,}", text or ""):
        line = _WS_RE.sub(" ", line).strip()
        if len(_HANGUL_RE.findall(line)) < 8:
            continue
        if any(j in line for j in _DETAIL_JUNK):
            continue
        if line in seen:
            continue
        seen.add(line)
        out.append(line)
    return out


def _extract_se_blocks(page: str) -> list[str]:
    """se-main-container 블록(질문/답변 본문)들의 정제 텍스트를 순서대로 추출.

    각 se-main-container 시작 위치부터 다음 시작(또는 +9000자)까지 슬라이스해 정제.
    proto(_proto_kin_material.py)와 동일한 휴리스틱 — 실측 검증됨.
    """
    blocks: list[str] = []
    starts = [m.start() for m in re.finditer(r"se-main-container", page or "")]
    for i, s in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else s + 9000
        lines = _clean_lines(_strip_tags(page[s:end]))
        if lines:
            blocks.append(" ".join(lines))
    return blocks


def fetch_kin_detail(link: str, *, timeout: int = 10) -> dict:
    """지식인 detail URL을 GET → 질문 본문 + 답변들을 정제해 반환.

    se-main-container 블록을 추출해 첫 블록=질문 본문, 나머지=답변들로 분리한다.
    보일러플레이트는 _clean_lines 가 제거한다.

    Args:
        link: 지식인 detail URL(qna/detail.naver?...).
        timeout: HTTP 타임아웃(초).

    Returns:
        {"question_body": str, "answers": [str, ...]}.
        실패/차단/빈 link 시 빈 dict {} 반환 — 예외를 던지지 않는다(한 건 실패가
        전체 수집을 막으면 안 됨).
    """
    url = (link or "").strip()
    if not url:
        return {}
    try:
        r = requests.get(
            url,
            headers={"User-Agent": _DETAIL_UA},
            timeout=timeout,
            allow_redirects=True,
        )
        if r.status_code != 200:
            return {}
        page = r.text or ""
    except Exception:  # noqa: BLE001 — 네트워크/차단 실패는 빈 dict(수집 전체 비차단).
        return {}

    blocks = _extract_se_blocks(page)
    if not blocks:
        return {}
    return {"question_body": blocks[0], "answers": blocks[1:]}


def enrich_jisikin(
    items: list[dict],
    *,
    timeout: int = 10,
    max_items=None,
    max_detail: int = MAX_DETAIL_PER_KEYWORD,
    deadline: float | None = None,
) -> list[dict]:
    """fetch_jisikin 결과 각 item 에 detail(질문+답변) 본문을 붙여 'body_full' 을 만든다.

    각 item 의 link 로 fetch_kin_detail 을 순차 호출(서버 부담↓ — 과한 동시성 X)해
    item["body_full"] = '질문 본문\\n\\n[답변 1] ...\\n\\n[답변 2] ...' 를 채운다.
    detail 추출 실패/빈 값이면 body_full = item.get("description", "") 로 폴백(회귀 안전).

    Args:
        items: fetch_jisikin 이 돌려준 [{title, link, description}, ...].
        timeout: 각 detail GET 타임아웃(초).
        max_items: detail 을 실제로 긁을 최대 건수(None=전부). 초과분은 폴백만 적용.
            (하위호환용 — 새 코드는 max_detail 을 쓴다.)
        max_detail: 키워드당 detail fetch 상한(기본 MAX_DETAIL_PER_KEYWORD=30).
            max_items 와 동시 지정 시 더 작은 값이 우선.
        deadline: time.monotonic() 기준 절대 시각(초). 이 시각을 넘으면 남은 link 는
            description 폴백으로 조기 종료(누적 시간 예산 초과 시 호출부가 주입).
            None 이면 시간 체크 비활성.

    Returns:
        같은 item 들(in-place 로 body_full 추가)의 리스트.
    """
    # max_items(하위호환)와 max_detail 중 더 제한적인 값을 실효 상한으로.
    effective_max = max_detail
    if max_items is not None:
        effective_max = min(effective_max, max_items)

    for idx, item in enumerate(items or []):
        fallback = item.get("description", "") or ""
        # 상한 초과 — description 폴백만 적용하고 detail fetch 생략.
        if idx >= effective_max:
            item["body_full"] = fallback
            continue
        # 시간 예산 초과 — 남은 link 를 description 폴백으로 조기 종료.
        if deadline is not None and _time.monotonic() >= deadline:
            item["body_full"] = fallback
            continue
        detail = fetch_kin_detail(item.get("link", ""), timeout=timeout)
        parts: list[str] = []
        question = (detail.get("question_body") or "").strip()
        answers = [a.strip() for a in (detail.get("answers") or []) if a and a.strip()]
        if question:
            parts.append(question)
        for ai, ans in enumerate(answers, 1):
            parts.append(f"[답변 {ai}] {ans}")
        body_full = "\n\n".join(parts).strip()
        item["body_full"] = body_full if body_full else fallback
    return items


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
        # 429(rate-limit) — 채널 circuit-break 용 별도 예외(integration_runner 에서 잡아 처리).
        if r.status_code == 429:
            raise RateLimitError(f"지식iN Open API 429 한도초과: {body}")
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
