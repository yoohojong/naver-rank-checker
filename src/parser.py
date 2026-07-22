"""parser: AB / 스마트블록 / 인기글 / 지식인 파싱 분기."""
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup


class ExposureArea(str, Enum):
    """spec 4.2 K 컬럼 enum (D-029 2026-05-18 — D-026 정정 = 중복노출 구좌 명시).

    parser 가 직접 채우는 값:
    - AB / SMART_BLOCK / POPULAR (= 검색 노출, 본인 link 매치)
    - UNEXPOSED (= 검색 미노출)

    main.py 가 D-029 빈 link 자동 채움 + Pass 2 양방향 갱신 logic 에서 채우는 값:
    - DUPLICATE_AB / DUPLICATE_SMART_BLOCK / DUPLICATE_POPULAR
      (= 빈 link 행 + 키워드 검색 결과에 다른 행 link 매치 = "추가 노출 발견" + 구좌 명시)
    - DUPLICATE (D-026 단일 값, 호환성 유지 — Pass 2 갱신 전 또는 구좌 미상)

    transitions.py 가 prev_K 비교로 채우는 값:
    - DROPPED (= 이전 노출 → 현재 미노출, "박스 빠짐")

    main.py 가 텍스트 판정 결과로 채울 값 (Phase E+F 2026-05-16):
    - DELETED (= "게시글이 삭제되었습니다" exact substring 검출 시)
    - FAILED (= 예외 발생 시, 다만 D-024 정합 = 시트 보존 우선)

    D-022 ① 폐기 (2026-05-16): 사장님 진짜 컨벤션 = AB / 스마트블록 / 인기글 별도 표기.
    이전 (2026-05-08): "노출 안 됨 = 모두 '삭제' 단일" = 잘못 misread.
    D-029 사장님 컨벤션 (2026-05-18 명확 의도):
    - 미노출 = search 결과 0건
    - 누락 = 이전 노출 → 지금 검색 결과 X (박스 안에서 빠짐)
    - 중복노출(AB) / 중복노출(스마트블록) / 중복노출(인기글) = 같은 link 가 여러 키워드 매치 (= 구좌 명시)
    - 삭제 = "게시글이 삭제되었습니다" exact substring 텍스트 검출 (= 진짜 글 사라짐)
    UNEXPOSURE_STOPPED / PRIVATE alias = 폐기 (T-M10.5 학습 정합).
    """
    AB = "AB"
    SMART_BLOCK = "스마트블록"
    POPULAR = "인기글"
    DUPLICATE = "중복노출"  # D-026 Phase C+D (2026-05-16) 호환 유지 — Pass 1 단계 또는 구좌 미상
    DUPLICATE_AB = "중복노출(AB)"  # D-029 (2026-05-18): 같은 link 가 여러 키워드 매치 (AB 구좌)
    DUPLICATE_SMART_BLOCK = "중복노출(스마트블록)"  # D-029 (2026-05-18): 스마트블록 구좌
    DUPLICATE_POPULAR = "중복노출(인기글)"  # D-029 (2026-05-18): 인기글 구좌
    UNEXPOSED = "미노출"
    DROPPED = "누락"  # D-026 Phase B: 이전 노출 → 현재 미노출 (transitions.py 가 채움)
    DELETED = "삭제"  # D-026 Phase E+F (2026-05-16): "게시글이 삭제되었습니다" 텍스트 검출 시
    FAILED = "실패"


@dataclass
class RankResult:
    exposure_area: ExposureArea = ExposureArea.UNEXPOSED
    integrated_rank: Optional[int] = None
    cafe_slot_rank: Optional[int] = None
    blog_slot_rank: Optional[int] = None
    in_jisikin: bool = False
    block_order: list[str] = field(default_factory=list)
    smart_block_name: Optional[str] = None
    parser_confidence: float = 0.0
    matched_url: Optional[str] = None  # T-M14.2: 매치된 URL. link_set 매치 시 = 매치된 link, target_url 매치 시 = target_url


def parse_search_result(
    html: str,
    target_url: Optional[str],
    link_set: Optional[set[str]] = None,
    cafe_slug_whitelist: Optional[set[str]] = None,
) -> RankResult:
    """검색 결과 페이지 + target_url 또는 link_set → RankResult.

    target_url 지정: 기존 동작 — target_url 매치한 link 의 순위 표시.
    target_url=None + link_set 지정 (T-M14, 2026-05-12): 사장님 시트의 다른 row link set
    중 검색 결과에 있는 link 의 순위 표시. 마케터 시점 = "내가 작업한 카페글이
    다른 키워드에도 노출되었으면" 즉시 인식.

    T-M14.7 (2026-05-14 D-022 B 옵션): cafe_slug_whitelist 매치 fallback.
    target_url 매치 X + link_set 매치 X 시 = 박스 안 카페 link 의 slug 가
    화이트리스트 안이면 매치 = 사장님 새 글 자동 검출.
    matched_url = 새 검출 link = 시트 link 자동 갱신.

    실측 셀렉터는 fixture 분석 후 _parse_* 함수에서 채워짐.
    """
    if not html or len(html) < 500:
        return RankResult()

    result = RankResult()
    result.block_order = _detect_block_order(html)

    if _parse_ab_list(html, target_url, result, link_set, cafe_slug_whitelist):
        result.exposure_area = ExposureArea.AB
    elif _parse_smart_blocks(html, target_url, result, link_set, cafe_slug_whitelist):
        result.exposure_area = ExposureArea.SMART_BLOCK
    elif _parse_popular(html, target_url, result, link_set, cafe_slug_whitelist):
        result.exposure_area = ExposureArea.POPULAR

    # T-M22.1 통합 (D-025, 2026-05-14): HTML 정적 파싱 = UNEXPOSED 시 = JSON fallback 시도.
    # 옵션 A 채택 (HTML 우선 + UNEXPOSED 시 JSON fallback):
    # - HTML 파싱 100% 정확도 검증 (5-14 자동 정확도 측정) = 회귀 X 보장
    # - 네이버 동적 박스 (entry.bootstrap() JSON payload) 누락 case = +5~10%p 정확도
    # - HTML 매치 성공 시 = JSON skip = 성능 영향 X
    # - JSON 추출/파싱 실패 시 = HTML 결과 그대로 보존 (예외 X)
    if result.exposure_area == ExposureArea.UNEXPOSED:
        _parse_bootstrap_json_fallback(html, target_url, result, link_set, cafe_slug_whitelist)

    _parse_jisikin(html, target_url or "", result)
    return result


def _detect_block_order(html: str) -> list[str]:
    """페이지 위→아래로 등장하는 블록 종류 unique list (C 컬럼 용).

    분류 규칙 (D-026 Phase A 2026-05-16 갱신 — 스마트블록 부활):
    - h2 자손 없음 + 박스 안 cafe link ≥ 1 → 'AB'
    - h2 자손 없음 + cafe link 0 (blog/web 만) → skip (AB 아님)
    - h2 자손 있음 + h2 텍스트 POPULAR_SKIP (광고/이미지/AI 브리핑/쇼핑/네이버 클립/브랜드) → skip
    - h2 자손 있음 + h2 텍스트 = '인기글' 키워드 → '인기글'
    - h2 자손 있음 + 그 외 (= 스마트블록) → '스마트블록' (D-022 ① 폐기 정합)
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    boxes = soup.select(".desktop_mode.api_subject_bx, .fds-default-mode.api_subject_bx")

    seen: list[str] = []
    for box in boxes:
        h2 = box.find("h2")
        kind: Optional[str] = None
        if h2 is None:
            # T-M33: 박스 안 cafe link 없으면 AB 분류 X (blog/web 만 있는 박스 = skip)
            has_cafe = any("cafe.naver.com" in a.get("href", "") for a in box.find_all("a", href=True))
            if has_cafe and _extract_main_link(box):
                kind = ExposureArea.AB.value
        else:
            h2_text = h2.get_text(strip=True)
            # _POPULAR_SKIP_PATTERNS = 광고/이미지/AI/쇼핑 등 = "인기글" 키워드 X 항목들.
            # = "인기글" 박스 와 충돌 X (= 사장님 fixture 정합)
            if any(p in h2_text for p in _POPULAR_SKIP_PATTERNS):
                continue
            # D-026 Phase A (2026-05-16): "인기글" 키워드 = 인기글, 그 외 h2 = 스마트블록
            if "인기글" in h2_text:
                kind = ExposureArea.POPULAR.value
            else:
                kind = ExposureArea.SMART_BLOCK.value
        if kind and kind not in seen:
            seen.append(kind)
    return seen


def _extract_cafe_slug(url: str) -> Optional[str]:
    """카페 URL 에서 slug 추출. 구형 URL (cafe.naver.com/{slug}/{post_id}) 만 지원.
    신형 URL (ca-fe/cafes/...) 은 cafe_id 기반으로 slug 매핑 불가 → None 반환.
    T-M14.7 (2026-05-14): cafe_slug_whitelist 매치용 내부 헬퍼.
    """
    if not url or "cafe.naver.com" not in url:
        return None
    from urllib.parse import urlparse
    p = urlparse(url)
    path_parts = [s for s in p.path.split("/") if s]
    if not path_parts:
        return None
    # 신형 URL: ca-fe/cafes/{cafe_id}/articles/{post_id} — slug 추출 불가
    if path_parts[0] == "ca-fe":
        return None
    # 구형 URL: {slug}/{post_id} — 첫 번째 segment = slug
    return path_parts[0]


def _parse_ab_list(
    html: str,
    target_url: Optional[str],
    result: RankResult,
    link_set: Optional[set[str]] = None,
    cafe_slug_whitelist: Optional[set[str]] = None,
) -> bool:
    """AB 통합 리스트 안에서 target_url 또는 link_set 매치 link 찾고 순위 계산.

    AB 항목 정의:
    - 외곽: div.api_subject_bx + .desktop_mode
    - h2 자손이 없음 (있으면 AI 브리핑 / 광고 / 스마트블록 / 인기글 / 이미지 등)
    - 메인 a[href] 가 있음

    매칭 시: integrated_rank, cafe_slot_rank/blog_slot_rank, parser_confidence 채움.
    target_url 지정: 기존 동작.
    target_url=None + link_set 지정 (T-M14): 사장님 시트의 다른 row link 와 매치된 link 의 순위.
    target_url=None + link_set 없음 + cafe_slug_whitelist 지정 (T-M14.7):
        박스 안 카페 link slug 가 화이트리스트 안이면 매치 = 새 글 자동 검출.
    매칭 실패 시 False (다음 분기로).

    매치 우선순위:
    1. target_url 정확 매치
    2. link_set 정확 매치 (T-M14.2)
    3. cafe_slug_whitelist slug 매치 (T-M14.7 신규)
    4. 매치 X
    """
    if not html:
        return False

    soup = BeautifulSoup(html, "lxml")
    boxes = soup.select(".desktop_mode.api_subject_bx, .fds-default-mode.api_subject_bx")

    ab_items: list[tuple[str, str]] = []
    for box in boxes:
        if box.find("h2") is not None:
            continue
        # T-M33 (2026-05-12 D-022): 박스 안 cafe link 0건 = AB 분류 X
        # blog/web 만 있는 박스는 AB로 카운트하지 않음 (Case B 11건 fix)
        has_cafe = any("cafe.naver.com" in a.get("href", "") for a in box.find_all("a", href=True))
        if not has_cafe:
            continue
        main_url = _extract_main_link(box)
        if not main_url:
            continue
        ab_items.append((main_url, _classify_item_url(main_url)))

    cafe_count = 0
    blog_count = 0
    for idx, (url, kind) in enumerate(ab_items, start=1):
        if kind == "cafe":
            cafe_count += 1
        elif kind == "blog":
            blog_count += 1

        # 1. target_url 정확 매치 (기존 동작)
        if target_url is not None:
            if _urls_match(url, target_url):
                result.integrated_rank = idx
                if kind == "cafe":
                    result.cafe_slot_rank = cafe_count
                elif kind == "blog":
                    result.blog_slot_rank = blog_count
                result.parser_confidence = 0.9
                result.matched_url = target_url  # T-M14.2: target_url 매치 시 = target_url 기록
                return True
            continue

        # target_url=None 이하: link_set / cafe_slug_whitelist 분기

        # T-M14 (T-M10 revert): target_url=None + link_set 지정 = 사장님 시트 link 매치
        # T-M16 (2026-05-12): 사장님 의도 = "내 카페 글이 노출되었나" — 카페 link 만 매치.
        # 사장님 시트의 어떤 row 에 blog link 있어도 매치 시도 X (마케터 = 카페만 작업).
        if link_set:
            if kind != "cafe":
                continue  # T-M16: blog/web 매치 시도 X
            # 2. link_set 정확 매치 (T-M14.2)
            if _urls_match_any(url, link_set):
                result.integrated_rank = idx
                result.cafe_slot_rank = cafe_count
                result.parser_confidence = 0.9
                result.matched_url = url  # T-M14.2: 매치된 URL 기록
                print(f"    [AB_MATCH] idx={idx} kind={kind} matched_url={url[:90]}")
                return True
            continue

        # 3. cafe_slug_whitelist slug 매치 (T-M14.7 신규)
        # target_url=None + link_set 없음 + cafe_slug_whitelist 지정 = 새 글 자동 검출
        if cafe_slug_whitelist and kind == "cafe":
            slug = _extract_cafe_slug(url)
            if slug and slug in cafe_slug_whitelist:
                result.integrated_rank = idx
                result.cafe_slot_rank = cafe_count
                result.parser_confidence = 0.85
                result.matched_url = url
                print(f"    [AB_SLUG_MATCH] idx={idx} slug={slug} matched_url={url[:90]}")
                return True

        # link_set 도 cafe_slug_whitelist 도 없으면 매치하지 않음 (T-M13 정신)

    return False


# T-M14.6 (2026-05-14): 광고 및 사이드바 링크 제외 패턴
_AD_LINK_PATTERNS = ("ader.naver.com", "adcr.naver.com", "/ad/", "?adidx=")
_SIDEBAR_LINK_PATTERNS = ("hashtag", "related_keyword", "/?query=")


def _is_excluded_link(url: str) -> bool:
    """T-M14.6 (2026-05-14): 광고 / 사이드바 / 관련 검색 링크 제외 판별."""
    if not url:
        return True
    return any(p in url for p in _AD_LINK_PATTERNS) or any(p in url for p in _SIDEBAR_LINK_PATTERNS)


def _extract_main_link(box) -> str:
    """박스 내부 메인 결과 URL.

    1순위: total_area / title_area / api_txt_lines 클래스 안의 a 태그 (CSS 정밀 선택)
    2순위: 가장 텍스트 긴 외부 a[href] (fallback)

    광고 / 관련 검색 등 부수 링크가 더 길어도 오작동하지 않도록 CSS 정밀 선택 우선.
    검색 fragment(?nso=...) 나 javascript: 등은 제외.

    critic 발견 (2026-05-12): 기존 텍스트 길이 기준 fallback 만 사용 = 광고/관련검색이
    더 길면 오작동. CSS 정밀 selector 1순위 추가로 fix.

    T-M14.6 (2026-05-14): 광고 / 사이드바 / 관련 검색 링크 명시 제외 — CSS 1순위 및
    fallback 양쪽 모두 _is_excluded_link 필터 적용.
    """
    # 1순위 — CSS 정밀 selector (네이버 검색 결과 실제 title 영역)
    for sel in [
        ".total_tit a[href]",
        ".title_link a[href]",
        "a.api_txt_lines[href]",
        ".title_area a[href]",
        ".user_thumb a[href]",
    ]:
        a = box.select_one(sel)
        if a:
            href = a.get("href", "")
            if href.startswith("http") and not href.startswith(("javascript:", "#")):
                if _is_excluded_link(href):
                    continue
                return href
    # 2순위 — fallback (텍스트 가장 긴 a, 광고/사이드바 제외)
    main_link = ""
    main_text_len = 0
    for a in box.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("http"):
            continue
        if href.startswith(("javascript:", "#")):
            continue
        if _is_excluded_link(href):
            continue
        text_len = len(a.get_text(strip=True))
        if text_len > main_text_len:
            main_text_len = text_len
            main_link = href
    return main_link


def _classify_item_url(url: str) -> str:
    """URL 도메인으로 'cafe' / 'blog' / 'web' 분류."""
    if "cafe.naver.com" in url:
        return "cafe"
    if "blog.naver.com" in url:
        return "blog"
    return "web"


def _normalize_netloc(netloc: str) -> str:
    """모바일 prefix `m.` 정규화 — m.cafe.naver.com 과 cafe.naver.com 동일 처리.

    네이버 검색 결과의 cafe URL 은 m.cafe.naver.com 으로 등장 (2026-05-08 확인).
    사장님 시트 URL 은 cafe.naver.com — 정규화 없으면 매칭 X.
    """
    if netloc.startswith("m."):
        return netloc[2:]
    return netloc


# T-M14.5 (2026-05-14): 네이버 카페 신형 URL 패턴 — ca-fe/cafes/{cafe_id}/articles/{post_id}
_CAFE_NEW_URL_RE = re.compile(r"/ca-fe/cafes/(\d+)/articles/(\d+)")


def _normalize_cafe_url(parsed_url) -> tuple:
    """T-M14.5 (2026-05-14): 카페 URL 정규화 — 구형 / 신형 통합 비교용 키 반환.

    구형: cafe.naver.com/{slug}/{post_id}
    신형: cafe.naver.com/ca-fe/cafes/{cafe_id}/articles/{post_id}

    netloc 정규화 (m. prefix 제거) 후 path → (netloc, key) 튜플 반환.
    - 신형 = ("정규화된_netloc", "NEW:{post_id}")
    - 구형 (끝이 숫자) = ("정규화된_netloc", "OLD:{post_id}")
    - 그 외 = ("정규화된_netloc", path)

    구형 slug ≠ 신형 cafe_id (네이버 내부 매핑 필요) → 직접 비교 불가.
    fallback = post_id 단독 비교 (같은 post_id = 같은 글 가정).
    """
    netloc = _normalize_netloc(parsed_url.netloc)
    path = parsed_url.path.rstrip("/")

    # 신형 URL 검출
    m = _CAFE_NEW_URL_RE.match(path)
    if m:
        post_id = m.group(2)
        return (netloc, f"NEW:{post_id}")

    # 구형 URL — path 끝 segment 가 숫자이면 post_id
    path_parts = [s for s in path.split("/") if s]
    if len(path_parts) >= 2 and path_parts[-1].isdigit():
        post_id = path_parts[-1]
        return (netloc, f"OLD:{post_id}")

    return (netloc, path)


def _urls_match(a: str, b: str) -> bool:
    """URL 매칭: 쿼리/fragment 무시, netloc (m. prefix 정규화) + path 비교.

    T-M14.5 (2026-05-14): 네이버 카페 구형/신형 URL 동시 지원.
    - 둘 다 구형 또는 둘 다 신형 = 정확 비교
    - 구형 vs 신형 (혼합) = post_id 단독 fallback 비교
    - 카페 URL 아닌 경우 = 기존 netloc + path 비교 유지
    """
    if not a or not b:
        return False
    pa, pb = urlparse(a), urlparse(b)
    na, ka = _normalize_cafe_url(pa)
    nb, kb = _normalize_cafe_url(pb)

    # 같은 netloc + 같은 키 (구형+구형, 신형+신형, 일반 URL)
    if na == nb and ka == kb:
        return True

    # 같은 netloc + 구형 vs 신형 혼합 = post_id 단독 fallback
    if na == nb:
        if ka.startswith("OLD:") and kb.startswith("NEW:"):
            return ka[4:] == kb[4:]
        if ka.startswith("NEW:") and kb.startswith("OLD:"):
            return ka[4:] == kb[4:]

    return False


def _urls_match_any(url: str, link_set: set[str]) -> bool:
    """T-M14: url 이 link_set 안 어떤 link 와 매치되는지 확인.

    naver.me 단축 URL 있는 link 사용 시 = 매치 X. main.py 에서 link_set 사용 시
    resolve_short_url 처리 후 사용하는 것과 정합. 여기는 raw _urls_match 사용.
    """
    if not url or not link_set:
        return False
    return any(_urls_match(url, link) for link in link_set)


_SMART_BLOCK_SKIP_PATTERNS = (
    "인기글",
    "관련 브랜드 콘텐츠",
    "이미지",
    "AI 브리핑",
    "네이버 클립",
    "네이버 가격비교",
    "네이버플러스 스토어",
)


def _parse_smart_blocks(
    html: str,
    target_url: Optional[str],
    result: RankResult,
    link_set: Optional[set[str]] = None,
    cafe_slug_whitelist: Optional[set[str]] = None,
) -> bool:
    """스마트블록 박스 매치 (D-026 Phase A 2026-05-16 부활 — D-022 ① 폐기 정합).

    사장님 진짜 컨벤션 = AB / 스마트블록 / 인기글 별도 표기.
    이전 (2026-05-08 D-022 ①): "이런 형태도 모두 인기글" = 잘못 misread = 폐기.

    스마트블록 박스 정의:
    - h2 자손 있음
    - h2 텍스트 POPULAR_SKIP (광고/이미지/AI/쇼핑 등) X
    - h2 텍스트 "인기글" 키워드 X (= 인기글 박스 = _parse_popular 책임)
    - h2 자손 = h2 텍스트 (예: "이용자 두피케어" / "탈모샴푸 순위" 등)

    매칭 시:
    - integrated_rank (L) = 박스 안 모든 항목 idx (URL 단위 dedup)
    - cafe_slot_rank (M) = 박스 안 카페 항목만 idx
    - smart_block_name = 박스 h2 텍스트
    - parser_confidence = 0.85

    매치 우선순위:
    1. target_url 정확 매치
    2. link_set 정확 매치 (T-M14.2 정합)
    3. cafe_slug_whitelist slug 매치 (T-M14.7 정합)
    4. 매치 X
    """
    if not html:
        return False

    soup = BeautifulSoup(html, "lxml")
    boxes = soup.select(".desktop_mode.api_subject_bx, .fds-default-mode.api_subject_bx")

    for box in boxes:
        h2 = box.find("h2")
        if h2 is None:
            continue
        h2_text = h2.get_text(strip=True)
        # 스킵 패턴 (광고/이미지/AI/쇼핑 등) = skip — 두 set 통합 적용 (D-026 Phase A 정합).
        # _SMART_BLOCK_SKIP_PATTERNS = 기본 + _POPULAR_SKIP_PATTERNS = T-M22 확장 (AI 추천/숏폼/쇼핑 등).
        if any(p in h2_text for p in _SMART_BLOCK_SKIP_PATTERNS):
            continue
        if any(p in h2_text for p in _POPULAR_SKIP_PATTERNS):
            continue
        # "인기글" 키워드 = 인기글 박스 = _parse_popular 책임 (= skip)
        if "인기글" in h2_text:
            continue

        # 박스 안 모든 항목 추출 (= _extract_popular_items 동일 logic)
        items = _extract_popular_items(box)
        cafe_count = 0
        for idx, url in enumerate(items, start=1):
            is_cafe = "cafe.naver.com" in url
            if is_cafe:
                cafe_count += 1

            # 1. target_url 정확 매치
            if target_url is not None:
                if _urls_match(url, target_url):
                    result.integrated_rank = idx
                    if is_cafe:
                        result.cafe_slot_rank = cafe_count
                    result.smart_block_name = h2_text
                    result.parser_confidence = 0.85
                    result.matched_url = target_url
                    return True
                continue

            # target_url=None 이하: link_set / cafe_slug_whitelist 분기

            # 2. link_set 정확 매치 (T-M16 정합: 카페만)
            if link_set:
                if not is_cafe:
                    continue
                if _urls_match_any(url, link_set):
                    result.integrated_rank = idx
                    result.cafe_slot_rank = cafe_count
                    result.smart_block_name = h2_text
                    result.parser_confidence = 0.85
                    result.matched_url = url
                    print(f"    [SMART_BLOCK_MATCH] idx={idx} h2={h2_text!r} matched_url={url[:90]}")
                    return True
                continue

            # 3. cafe_slug_whitelist slug 매치 (T-M14.7 정합)
            if cafe_slug_whitelist and is_cafe:
                slug = _extract_cafe_slug(url)
                if slug and slug in cafe_slug_whitelist:
                    result.integrated_rank = idx
                    result.cafe_slot_rank = cafe_count
                    result.smart_block_name = h2_text
                    result.parser_confidence = 0.85
                    result.matched_url = url
                    print(f"    [SMART_BLOCK_SLUG_MATCH] idx={idx} slug={slug} h2={h2_text!r} matched_url={url[:90]}")
                    return True

    return False


def _extract_smart_block_items(box) -> list[str]:
    """스마트블록 박스 안의 메인 결과 URL 리스트 (위→아래, dedup).

    제외: keep.naver.com, javascript:, root path 출처 링크.
    """
    seen: set[tuple[str, str]] = set()
    items: list[str] = []
    for a in box.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("http"):
            continue
        if "keep.naver.com" in href:
            continue
        p = urlparse(href)
        if p.path in ("", "/"):
            continue
        key = (p.netloc, p.path.rstrip("/"))
        if key in seen:
            continue
        seen.add(key)
        items.append(href)
    return items


_POPULAR_SKIP_PATTERNS = (
    "관련 브랜드 콘텐츠",
    "이미지",
    "AI 브리핑",
    "네이버 클립",
    "네이버 가격비교",
    "네이버플러스 스토어",
    # T-M22 (2026-05-13 architect 발견): 신규 박스 사전 대응
    "AI 추천",
    "숏폼",
    "플레이스",
    "동영상",
    "쇼핑",
)


def _parse_popular(
    html: str,
    target_url: Optional[str],
    result: RankResult,
    link_set: Optional[set[str]] = None,
    cafe_slug_whitelist: Optional[set[str]] = None,
) -> bool:
    """인기글 (사장님 컨벤션) — h2 자손 있는 박스 모두 (광고/이미지/AI/쇼핑 제외).

    사장님 컨벤션 (2026-05-08 확인): 검색 결과 박스에 h2 헤더 (키워드 변형 또는 '...인기글') 있고
    안에 본문 묶음 → 모두 '인기글'. 제가 spec 에 사용한 'SMART_BLOCK' 은 사장님 컨벤션 X.

    매칭 시:
    - integrated_rank (L) = 인기글 박스 안 본문 글 idx (URL 단위 dedup, T-M14.3)
    - cafe_slot_rank (M) = 같은 박스 안 카페 항목들 중 idx (cafe.naver.com 만 카운트, URL 단위 dedup)
    - smart_block_name = 박스 h2 텍스트 (메타용, 시트 write X)
    - parser_confidence = 0.85

    매치 우선순위:
    1. target_url 정확 매치
    2. link_set 정확 매치 (T-M14.2)
    3. cafe_slug_whitelist slug 매치 (T-M14.7 신규)
    4. 매치 X
    """
    if not html:
        return False

    soup = BeautifulSoup(html, "lxml")
    boxes = soup.select(".desktop_mode.api_subject_bx, .fds-default-mode.api_subject_bx")

    for box in boxes:
        h2 = box.find("h2")
        if h2 is None:
            continue
        h2_text = h2.get_text(strip=True)
        if any(p in h2_text for p in _POPULAR_SKIP_PATTERNS):
            continue
        # D-026 Phase A (2026-05-16): 인기글 박스 = h2 텍스트 "인기글" 키워드 명시 포함.
        # 그 외 h2 박스 = 스마트블록 박스 = _parse_smart_blocks 책임 (= skip).
        if "인기글" not in h2_text:
            continue

        items = _extract_popular_items(box)
        # 2026-05-11 critic Major 2 fix: L = 박스 안 모든 항목 순위, M = 카페만 카운트.
        cafe_count = 0
        for idx, url in enumerate(items, start=1):
            is_cafe = "cafe.naver.com" in url
            if is_cafe:
                cafe_count += 1

            # 1. target_url 정확 매치 (기존 동작)
            if target_url is not None:
                if _urls_match(url, target_url):
                    result.integrated_rank = idx
                    if is_cafe:
                        result.cafe_slot_rank = cafe_count
                    result.smart_block_name = h2_text
                    result.parser_confidence = 0.85
                    result.matched_url = target_url  # T-M14.2: target_url 매치 시 = target_url 기록
                    return True
                continue

            # target_url=None 이하: link_set / cafe_slug_whitelist 분기

            # T-M14: target_url=None + link_set 지정 = 사장님 시트 link 매치
            # T-M16 (2026-05-12): 카페 link 만 매치 (사장님 의도 = 카페만 작업)
            if link_set:
                if not is_cafe:
                    continue  # T-M16: blog/web 매치 시도 X
                # 2. link_set 정확 매치 (T-M14.2)
                if _urls_match_any(url, link_set):
                    result.integrated_rank = idx
                    result.cafe_slot_rank = cafe_count
                    result.smart_block_name = h2_text
                    result.parser_confidence = 0.85
                    result.matched_url = url  # T-M14.2: 매치된 URL 기록
                    print(f"    [POPULAR_MATCH] idx={idx} h2={h2_text!r} matched_url={url[:90]}")
                    return True
                continue

            # 3. cafe_slug_whitelist slug 매치 (T-M14.7 신규)
            # target_url=None + link_set 없음 + cafe_slug_whitelist 지정 = 새 글 자동 검출
            if cafe_slug_whitelist and is_cafe:
                slug = _extract_cafe_slug(url)
                if slug and slug in cafe_slug_whitelist:
                    result.integrated_rank = idx
                    result.cafe_slot_rank = cafe_count
                    result.smart_block_name = h2_text
                    result.parser_confidence = 0.85
                    result.matched_url = url
                    print(f"    [POPULAR_SLUG_MATCH] idx={idx} slug={slug} h2={h2_text!r} matched_url={url[:90]}")
                    return True

            # link_set 도 cafe_slug_whitelist 도 없으면 매치하지 않음

    return False


def _extract_popular_items(box) -> list[str]:
    """인기글 박스 안의 본문 글 URL 리스트 (위→아래).

    본문 글 = path 끝이 숫자 (post_id) 인 URL. 출처 root URL 제외.

    T-M14.3 (2026-05-13 architect 발견): source_key dedup 제거.
    같은 카페 복수 글 = 모두 idx 카운트 (사장님 시트 link 가 두 번째 글이어도 매치 가능).
    다만 완전히 동일한 URL (netloc + path 동일) = dedup (HTML 안 중복 링크 방지).
    """
    # T-M14.3: URL 단위 dedup (동일 링크 중복 방지), source 단위 dedup 제거
    seen_urls: set[tuple[str, str]] = set()
    items: list[str] = []
    for a in box.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("http"):
            continue
        if "keep.naver.com" in href:
            continue
        p = urlparse(href)
        path_parts = [s for s in p.path.split("/") if s]
        if len(path_parts) < 2:
            continue
        last_seg = path_parts[-1].split("?")[0]
        if not last_seg.isdigit():
            continue
        url_key = (p.netloc, p.path.rstrip("/"))
        if url_key in seen_urls:
            continue
        seen_urls.add(url_key)
        items.append(href)
    return items


_JISIKIN_H2_PATTERNS = ("지식iN", "지식인", "지식 iN")


def _parse_jisikin(html: str, target_url: str, result: RankResult) -> None:
    """지식인 탭 존재 여부 (사장님 컨벤션, 2026-05-08 확인): target_url 무관,
    검색 페이지에 지식iN 결과/탭이 보이면 'O'.

    2026-05-11 v2 fix: 사장님 시트 500행 비교 결과 J false positive 69건 발견.
    원인 = 기존 로직이 "AB 박스 안 임의 kin.naver.com 링크" 잡음. 진짜 지식iN 탭 박스
    (h2 텍스트='지식iN') 가 아닌 부수 링크 (관련검색, 추천 등) 까지 false 매칭.
    fix = M4.9 인기글 패턴 동일하게 h2 텍스트로 박스 narrow.

    target_url 인자는 인터페이스 호환성 위해 유지.
    """
    if not html:
        return
    soup = BeautifulSoup(html, "lxml")
    # D-050 (2026-06-20): 네이버 sds-comps 신 디자인 DOM drift 정탐 복구.
    # 지식iN 라벨이 <h2> → 출처 프로필 제목(sds-comps-profile-info-title="네이버 지식iN")으로 이동.
    # 이 출처 라벨만 검출 = 정탐 (클립/카페 등 다른 출처 라벨은 미스매치라 오탐 X).
    for el in soup.select('[class*="sds-comps-profile-info-title"]'):
        if any(p in el.get_text(strip=True) for p in _JISIKIN_H2_PATTERNS):
            result.in_jisikin = True
            return
    # 구 구조 호환 (h2='지식iN' 박스 + kin.naver.com 링크, 2026-05-11 v2)
    boxes = soup.select(".desktop_mode.api_subject_bx, .fds-default-mode.api_subject_bx")
    for box in boxes:
        h2 = box.find("h2")
        if not h2:
            continue
        h2_text = h2.get_text(strip=True)
        # h2 텍스트가 '지식iN' / '지식인' 패턴이어야 진짜 지식iN 박스
        if not any(p in h2_text for p in _JISIKIN_H2_PATTERNS):
            continue
        # 박스 안에 kin.naver.com 링크 존재하면 노출 = 'O'
        for a in box.find_all("a", href=True):
            if "kin.naver.com" in a["href"]:
                result.in_jisikin = True
                return


# T-M22.1 (2026-05-14 probe 실측 fix): entry.bootstrap() 두 번째 인자 위치 탐색용 정규식.
# 진짜 형식: entry.bootstrap(document.getElementById("fdr-..."), {...JSON...});
# 첫 번째 인자 = DOM element (무시), 두 번째 인자 = JSON 페이로드.
# JSON 끝은 regex non-greedy 로 중첩 brace 처리 불가 → brace counting 방식 사용.
_BOOTSTRAP_PREFIX_RE = re.compile(
    r'entry\.bootstrap\(\s*document\.getElementById\([^)]+\)\s*,\s*'
)


def _extract_bootstrap_json(html: str) -> Optional[dict]:
    """T-M22.1 (2026-05-14 probe 실측 fix): 네이버 entry.bootstrap() 두 번째 인자 JSON 추출.

    진짜 형식: entry.bootstrap(document.getElementById("fdr-..."), {...JSON...});

    regex non-greedy = JSON 안 중첩 brace 처리 불가.
    brace 균형 기반 수동 파싱으로 JSON 객체 끝을 정확히 탐색.

    반환: 추출 성공 시 dict, 실패 시 None (정적 HTML 파싱 fallback 사용).
    """
    if not html or "entry.bootstrap" not in html:
        return None

    # entry.bootstrap(document.getElementById(...), 위치 탐색
    match = _BOOTSTRAP_PREFIX_RE.search(html)
    if not match:
        return None

    # 두 번째 인자 시작 위치 = JSON 객체 시작 '{' 여야 함
    start = match.end()
    if start >= len(html) or html[start] != '{':
        return None

    # brace 균형 기반 JSON 끝 탐색
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(html)):
        c = html[i]
        if escape:
            escape = False
            continue
        if c == '\\':
            escape = True
            continue
        if c == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                # JSON 객체 끝 발견 → 파싱 시도
                try:
                    return json.loads(html[start:i + 1])
                except (json.JSONDecodeError, ValueError):
                    return None
    return None


# T-M22.1 통합 (D-025, 2026-05-14): JSON payload 안 URL 탐색용 키 후보.
# 네이버 동적 박스 JSON payload = 중첩 dict/list 혼합. URL 은 보통 'link' / 'url' / 'href'
# 키 또는 string 값 형태로 등장. 깊이 우선 재귀 탐색 으로 모든 string URL 수집.
_URL_LIKE_PREFIXES = ("http://", "https://")


def _collect_urls_from_json(node, urls: list) -> None:
    """T-M22.1 통합 (D-025, 2026-05-14): JSON payload 깊이 우선 재귀 탐색,
    http(s) prefix string 값 = URL 후보로 수집.

    네이버 동적 박스 JSON payload = 키 구조 다양 (link/url/href/contentUrl/...).
    구조 의존 없이 모든 string 값 중 http(s) prefix 만 수집 = robust.

    중복 dedup = caller (등장 순서 보존).
    """
    if isinstance(node, dict):
        for v in node.values():
            _collect_urls_from_json(v, urls)
    elif isinstance(node, list):
        for v in node:
            _collect_urls_from_json(v, urls)
    elif isinstance(node, str):
        if node.startswith(_URL_LIKE_PREFIXES):
            urls.append(node)


def _parse_bootstrap_json_fallback(
    html: str,
    target_url: Optional[str],
    result: RankResult,
    link_set: Optional[set[str]] = None,
    cafe_slug_whitelist: Optional[set[str]] = None,
) -> bool:
    """T-M22.1 통합 (D-025, 2026-05-14): HTML 파싱 = UNEXPOSED 시 = JSON fallback.

    옵션 A (HTML 우선 + JSON fallback) 의 fallback 단계 구현.
    네이버 동적 박스 (entry.bootstrap() JSON payload) 안 URL 후보 추출 후
    target_url / link_set / cafe_slug_whitelist 매치 시도.

    매치 성공 시:
    - result.exposure_area = AB (JSON fallback 매치 = 동적 박스 = AB 가정)
    - result.integrated_rank = JSON 안 URL 등장 순서 idx
    - result.cafe_slot_rank = 카페 URL 만 카운트한 idx
    - result.parser_confidence = 0.75 (JSON fallback = HTML 직접 파싱보다 약간 낮음)
    - result.matched_url = 매치된 URL

    매치 실패 시 = result 변경 X (HTML 결과 그대로 보존, 예외 X).

    매치 우선순위 (HTML 파싱 분기와 동일):
    1. target_url 정확 매치
    2. link_set 정확 매치
    3. cafe_slug_whitelist slug 매치
    4. 매치 X
    """
    if not html:
        return False

    payload = _extract_bootstrap_json(html)
    if payload is None:
        return False

    # JSON payload 안 모든 URL 수집 (등장 순서 보존, dedup)
    raw_urls: list[str] = []
    _collect_urls_from_json(payload, raw_urls)
    if not raw_urls:
        return False

    # 등장 순서 보존 dedup (광고/사이드바 제외 = HTML 파싱과 정합)
    seen: set[str] = set()
    urls: list[str] = []
    for u in raw_urls:
        if u in seen:
            continue
        if _is_excluded_link(u):
            continue
        seen.add(u)
        urls.append(u)

    if not urls:
        return False

    cafe_count = 0
    for idx, url in enumerate(urls, start=1):
        kind = _classify_item_url(url)
        if kind == "cafe":
            cafe_count += 1

        # 1. target_url 정확 매치
        if target_url is not None:
            if _urls_match(url, target_url):
                result.integrated_rank = idx
                if kind == "cafe":
                    result.cafe_slot_rank = cafe_count
                result.exposure_area = ExposureArea.AB
                result.parser_confidence = 0.75
                result.matched_url = target_url
                return True
            continue

        # target_url=None 이하: link_set / cafe_slug_whitelist 분기

        # 2. link_set 정확 매치 (T-M16 정합: 카페 link 만 매치)
        if link_set:
            if kind != "cafe":
                continue
            if _urls_match_any(url, link_set):
                result.integrated_rank = idx
                result.cafe_slot_rank = cafe_count
                result.exposure_area = ExposureArea.AB
                result.parser_confidence = 0.75
                result.matched_url = url
                print(f"    [JSON_FALLBACK_MATCH] idx={idx} kind={kind} matched_url={url[:90]}")
                return True
            continue

        # 3. cafe_slug_whitelist slug 매치 (T-M14.7 정합)
        if cafe_slug_whitelist and kind == "cafe":
            slug = _extract_cafe_slug(url)
            if slug and slug in cafe_slug_whitelist:
                result.integrated_rank = idx
                result.cafe_slot_rank = cafe_count
                result.exposure_area = ExposureArea.AB
                result.parser_confidence = 0.70
                result.matched_url = url
                print(f"    [JSON_FALLBACK_SLUG_MATCH] idx={idx} slug={slug} matched_url={url[:90]}")
                return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# 경쟁사 수집 (2026-07-23 사장님 요청): "누락시킨거 보고 상위노출된 경쟁사 리스트업"
#
# 기존 파싱 분기(_parse_ab_list / _parse_smart_blocks / _parse_popular)는 **우리 link**
# 를 찾으면 즉시 return 하고 나머지 항목은 버린다. 경쟁사 집계는 그 "나머지"가 필요하다.
# 기존 함수를 건드리면 순위 판정 회귀 위험이 있으므로, 같은 박스 분류 규칙을 그대로 쓰되
# **읽기 전용으로 따로 도는 함수**를 새로 둔다(= 순위 로직 회귀 0).
# 추가 크롤링 없음 — main.py 가 이미 받아둔 같은 html 을 그대로 넘긴다.
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class SlotItem:
    """검색 결과 한 구좌에 실제로 올라와 있는 글 1건 (우리 글/남의 글 구분 전)."""

    area: str  # "AB" / "스마트블록" / "인기글"
    rank: int  # 그 구좌 안 순위 (위→아래, 1부터)
    url: str
    kind: str  # "cafe" / "blog" / "web"
    title: str = ""
    block_name: str = ""  # 박스 h2 텍스트 (AB 는 h2 없음 = "")


def _title_for_url(box, url: str) -> str:
    """박스 안에서 해당 URL 을 가진 a 태그의 표시 텍스트 (없으면 "")."""
    if not url:
        return ""
    for a in box.find_all("a", href=True):
        if a["href"] == url:
            text = a.get_text(strip=True)
            if text:
                return text[:120]
    return ""


def collect_slot_items(html: str, *, max_per_area: int = 20) -> list[SlotItem]:
    """검색 결과 페이지 → 구좌별 상위 글 목록 (읽기 전용, 매칭 판단 없음).

    박스 분류 규칙은 _detect_block_order 와 동일:
    - h2 없음 + 박스 안 cafe link ≥ 1 → AB (박스 1개 = 항목 1개, 박스 순서 = 순위)
    - h2 있음 + "인기글" 포함 → 인기글 (박스 안 본문 글 목록)
    - h2 있음 + 그 외 (광고/이미지/AI/쇼핑 제외) → 스마트블록

    Args:
        html: 이미 받아둔 검색 결과 HTML (추가 요청 X).
        max_per_area: 구좌별 상위 몇 개까지 담을지 (시트 적재량 방어).

    Returns:
        SlotItem 리스트 (구좌·순위 순). html 이 비었거나 짧으면 빈 리스트.
    """
    if not html or len(html) < 500:
        return []

    soup = BeautifulSoup(html, "lxml")
    boxes = soup.select(".desktop_mode.api_subject_bx, .fds-default-mode.api_subject_bx")

    items: list[SlotItem] = []
    ab_rank = 0
    for box in boxes:
        h2 = box.find("h2")
        if h2 is None:
            has_cafe = any("cafe.naver.com" in a.get("href", "") for a in box.find_all("a", href=True))
            if not has_cafe:
                continue
            url = _extract_main_link(box)
            if not url:
                continue
            ab_rank += 1
            if ab_rank > max_per_area:
                continue
            items.append(
                SlotItem(
                    area=ExposureArea.AB.value,
                    rank=ab_rank,
                    url=url,
                    kind=_classify_item_url(url),
                    title=_title_for_url(box, url),
                )
            )
            continue

        h2_text = h2.get_text(strip=True)
        if any(p in h2_text for p in _POPULAR_SKIP_PATTERNS):
            continue
        if "인기글" in h2_text:
            area = ExposureArea.POPULAR.value
            urls = _extract_popular_items(box)
        else:
            area = ExposureArea.SMART_BLOCK.value
            urls = _extract_smart_block_items(box)

        # 스마트블록은 글 링크와 함께 작성자 홈(blog.naver.com/{id}, in.naver.com/{id}) 링크도
        # 같이 잡힌다. 경쟁사 목록에는 '글'만 남긴다(홈 링크는 순위 자리를 차지한 글이 아님).
        urls = [u for u in urls if _is_post_like_url(u)]

        for idx, url in enumerate(urls[:max_per_area], start=1):
            items.append(
                SlotItem(
                    area=area,
                    rank=idx,
                    url=url,
                    kind=_classify_item_url(url),
                    title=_title_for_url(box, url),
                    block_name=h2_text,
                )
            )
    return items


def _is_post_like_url(url: str) -> bool:
    """글 상세 URL 로 보이는지 — path segment 2개 이상 (홈/프로필 링크 배제)."""
    if not url:
        return False
    parts = [seg for seg in urlparse(url).path.split("/") if seg]
    return len(parts) >= 2


def is_known_url(url: str, link_set: Optional[set[str]]) -> bool:
    """url 이 link_set(우리 시트 link) 중 하나와 같은 글인지 (정규화 매치). 공개 wrapper."""
    if not url or not link_set:
        return False
    return _urls_match_any(url, link_set)


def cafe_slug_of(url: str) -> Optional[str]:
    """카페 URL → slug (구형 URL 만). 공개 wrapper."""
    return _extract_cafe_slug(url)
