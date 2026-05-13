"""parser: AB / 스마트블록 / 인기글 / 지식인 파싱 분기."""
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup


class ExposureArea(str, Enum):
    """spec 4.2 K 컬럼 8개 enum. parser 가 직접 채우는 건 AB/SMART_BLOCK/POPULAR/UNEXPOSED.

    UNEXPOSURE_STOPPED 는 transitions.py (M7.1) 가 이전 K 비교로 채움.
    DELETED/PRIVATE 는 main.py (M7.2) 가 crawler.fetch_cafe_url_status 결과로 매핑.
    FAILED 는 main.py 가 CrawlerError 캐치 시 채움.
    """
    AB = "AB"
    SMART_BLOCK = "스마트블록"
    POPULAR = "인기글"
    UNEXPOSED = "미노출"
    # 사장님 컨벤션 (2026-05-08 확인): 노출 안 됨 케이스 모두 "삭제" 단일 단어.
    # UNEXPOSURE_STOPPED / DELETED / PRIVATE 셋 다 "삭제" — Python enum alias.
    UNEXPOSURE_STOPPED = "삭제"
    DELETED = "삭제"
    PRIVATE = "삭제"
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


def parse_search_result(html: str, target_url: Optional[str], link_set: Optional[set[str]] = None) -> RankResult:
    """검색 결과 페이지 + target_url 또는 link_set → RankResult.

    target_url 박힘: 기존 동작 — target_url 매치 박은 link 의 순위 표시.
    target_url=None + link_set 박힘 (T-M14, 2026-05-12): 사장님 시트의 다른 row link set
    중 검색 결과에 박힌 link 의 순위 표시. 마케터 시점 = "내가 박은 카페글이
    다른 키워드에도 노출 박혔으면" 즉시 인식.

    실측 셀렉터는 fixture 분석 후 _parse_* 함수에서 채워짐.
    """
    if not html or len(html) < 500:
        return RankResult()

    result = RankResult()
    result.block_order = _detect_block_order(html)

    if _parse_ab_list(html, target_url, result, link_set):
        result.exposure_area = ExposureArea.AB
    elif _parse_smart_blocks(html, target_url, result):
        result.exposure_area = ExposureArea.SMART_BLOCK
    elif _parse_popular(html, target_url, result, link_set):
        result.exposure_area = ExposureArea.POPULAR

    _parse_jisikin(html, target_url or "", result)
    return result


def _detect_block_order(html: str) -> list[str]:
    """페이지 위→아래로 등장하는 블록 종류 unique list (C 컬럼 용).

    분류 규칙 (T-M33 2026-05-12 D-022 갱신):
    - h2 자손 없음 + 박스 안 cafe link ≥ 1 → 'AB'
    - h2 자손 없음 + cafe link 0 (blog/web 만) → skip (AB 아님)
    - h2 자손 있음 + h2 텍스트 POPULAR_SKIP (광고/이미지/AI 브리핑/쇼핑/네이버 클립/브랜드) → skip
    - h2 자손 있음 + 그 외 → '인기글'
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
            # T-M33: 박스 안 cafe link 없으면 AB 분류 X (blog/web 만 박힌 박스 = skip)
            has_cafe = any("cafe.naver.com" in a.get("href", "") for a in box.find_all("a", href=True))
            if has_cafe and _extract_main_link(box):
                kind = ExposureArea.AB.value
        else:
            h2_text = h2.get_text(strip=True)
            if any(p in h2_text for p in _POPULAR_SKIP_PATTERNS):
                continue
            # h2 자손 있고 광고/이미지/AI/쇼핑 외 = 사장님 컨벤션 = '인기글'
            kind = ExposureArea.POPULAR.value
        if kind and kind not in seen:
            seen.append(kind)
    return seen


def _parse_ab_list(html: str, target_url: Optional[str], result: RankResult, link_set: Optional[set[str]] = None) -> bool:
    """AB 통합 리스트 안에서 target_url 또는 link_set 매치 link 찾고 순위 계산.

    AB 항목 정의:
    - 외곽: div.api_subject_bx + .desktop_mode
    - h2 자손이 없음 (있으면 AI 브리핑 / 광고 / 스마트블록 / 인기글 / 이미지 등)
    - 메인 a[href] 가 있음

    매칭 시: integrated_rank, cafe_slot_rank/blog_slot_rank, parser_confidence 채움.
    target_url 박힘: 기존 동작.
    target_url=None + link_set 박힘 (T-M14): 사장님 시트의 다른 row link 와 매치된 link 의 순위.
    매칭 실패 시 False (다음 분기로).
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
        # blog/web 만 박힌 박스는 AB로 카운트하지 않음 (Case B 11건 fix)
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
        # T-M14 (T-M10 revert): target_url=None + link_set 박힘 = 사장님 시트 link 매치
        # T-M16 (2026-05-12): 사장님 의도 = "내 카페 글이 노출되었나" — 카페 link 만 매치.
        # 사장님 시트의 어떤 row 에 blog link 박혀있어도 매치 시도 X (마케터 = 카페만 작업).
        if target_url is None and link_set:
            if kind != "cafe":
                continue  # T-M16: blog/web 매치 시도 X
            if _urls_match_any(url, link_set):
                result.integrated_rank = idx
                result.cafe_slot_rank = cafe_count
                result.parser_confidence = 0.9
                result.matched_url = url  # T-M14.2: 매치된 URL 기록
                print(f"    [AB_MATCH] idx={idx} kind={kind} matched_url={url[:90]}")
                return True
            continue
        if target_url is None:
            # link_set 없으면 매치하지 않음 (T-M13 정신)
            continue
        if _urls_match(url, target_url):
            result.integrated_rank = idx
            if kind == "cafe":
                result.cafe_slot_rank = cafe_count
            elif kind == "blog":
                result.blog_slot_rank = blog_count
            result.parser_confidence = 0.9
            result.matched_url = target_url  # T-M14.2: target_url 매치 시 = target_url 기록
            return True
    return False


def _extract_main_link(box) -> str:
    """박스 내부 메인 결과 URL.

    1순위: total_area / title_area / api_txt_lines 클래스 안의 a 태그 (CSS 정밀 선택)
    2순위: 가장 텍스트 긴 외부 a[href] (fallback)

    광고 / 관련 검색 등 부수 링크가 더 길어도 오작동하지 않도록 CSS 정밀 선택 우선.
    검색 fragment(?nso=...) 나 javascript: 등은 제외.

    critic 발견 (2026-05-12): 기존 텍스트 길이 기준 fallback 만 사용 = 광고/관련검색이
    더 길면 오작동. CSS 정밀 selector 1순위 추가로 fix.
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
                return href
    # 2순위 — fallback (텍스트 가장 긴 a)
    main_link = ""
    main_text_len = 0
    for a in box.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("http"):
            continue
        if href.startswith(("javascript:", "#")):
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


def _urls_match(a: str, b: str) -> bool:
    """URL 매칭: 쿼리/fragment 무시, netloc (m. prefix 정규화) + path (trailing slash 무시) 일치."""
    if not a or not b:
        return False
    pa, pb = urlparse(a), urlparse(b)
    return (
        _normalize_netloc(pa.netloc) == _normalize_netloc(pb.netloc)
        and pa.path.rstrip("/") == pb.path.rstrip("/")
    )


def _urls_match_any(url: str, link_set: set[str]) -> bool:
    """T-M14: url 박힌 거가 link_set 안 어떤 link 와 매치 박혀있나.

    naver.me 단축 URL 박힌 link 박을 때 = 매치 X. main.py 에서 link_set 박을 때
    resolve_short_url 박은 후 박는 것 정합. 여기는 raw _urls_match 박음.
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


def _parse_smart_blocks(html: str, target_url: str, result: RankResult) -> bool:
    """DEPRECATED — 사장님 컨벤션 (2026-05-08 확인): 이런 형태도 모두 '인기글'.
    _parse_popular 가 흡수. 호환성 위해 함수는 남기되 항상 False 리턴."""
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


def _parse_popular(html: str, target_url: Optional[str], result: RankResult, link_set: Optional[set[str]] = None) -> bool:
    """인기글 (사장님 컨벤션) — h2 자손 있는 박스 모두 (광고/이미지/AI/쇼핑 제외).

    사장님 컨벤션 (2026-05-08 확인): 검색 결과 박스에 h2 헤더 (키워드 변형 또는 '...인기글') 있고
    안에 본문 묶음 → 모두 '인기글'. 제가 spec 에 박은 'SMART_BLOCK' 은 사장님 컨벤션 X.

    매칭 시:
    - integrated_rank (L) = 인기글 박스 안 본문 글 idx (URL 단위 dedup, T-M14.3)
    - cafe_slot_rank (M) = 같은 박스 안 카페 항목들 중 idx (cafe.naver.com 만 카운트, URL 단위 dedup)
    - smart_block_name = 박스 h2 텍스트 (메타용, 시트 write X)
    - parser_confidence = 0.85
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

        items = _extract_popular_items(box)
        # 2026-05-11 critic Major 2 fix: L = 박스 안 모든 항목 순위, M = 카페만 카운트.
        cafe_count = 0
        for idx, url in enumerate(items, start=1):
            is_cafe = "cafe.naver.com" in url
            if is_cafe:
                cafe_count += 1
            # T-M14: target_url=None + link_set 박힘 = 사장님 시트 link 매치
            # T-M16 (2026-05-12): 카페 link 만 매치 (사장님 의도 = 카페만 작업)
            if target_url is None and link_set:
                if not is_cafe:
                    continue  # T-M16: blog/web 매치 시도 X
                if _urls_match_any(url, link_set):
                    result.integrated_rank = idx
                    result.cafe_slot_rank = cafe_count
                    result.smart_block_name = h2_text
                    result.parser_confidence = 0.85
                    result.matched_url = url  # T-M14.2: 매치된 URL 기록
                    print(f"    [POPULAR_MATCH] idx={idx} h2={h2_text!r} matched_url={url[:90]}")
                    return True
                continue
            if target_url is None:
                continue
            if _urls_match(url, target_url):
                result.integrated_rank = idx
                if is_cafe:
                    result.cafe_slot_rank = cafe_count
                result.smart_block_name = h2_text
                result.parser_confidence = 0.85
                result.matched_url = target_url  # T-M14.2: target_url 매치 시 = target_url 기록
                return True
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
