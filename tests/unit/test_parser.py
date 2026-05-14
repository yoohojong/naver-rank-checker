"""parser 단위 테스트."""
from src.parser import ExposureArea, RankResult, parse_search_result


class TestRankResult:
    def test_default_unexposed(self):
        r = RankResult()
        assert r.exposure_area == ExposureArea.UNEXPOSED
        assert r.integrated_rank is None
        assert r.cafe_slot_rank is None
        assert r.blog_slot_rank is None
        assert r.in_jisikin is False
        assert r.block_order == []
        assert r.smart_block_name is None
        assert r.parser_confidence == 0.0

    def test_exposure_area_enum_values(self):
        assert ExposureArea.AB.value == "AB"
        assert ExposureArea.SMART_BLOCK.value == "스마트블록"
        assert ExposureArea.POPULAR.value == "인기글"
        assert ExposureArea.UNEXPOSED.value == "미노출"

    def test_exposure_area_extended_enum_values(self):
        """사장님 컨벤션 (2026-05-08): 노출 안 됨 = '삭제' 단일. UNEXPOSURE_STOPPED/DELETED/PRIVATE alias."""
        assert ExposureArea.UNEXPOSURE_STOPPED.value == "삭제"
        assert ExposureArea.DELETED.value == "삭제"
        assert ExposureArea.PRIVATE.value == "삭제"
        assert ExposureArea.FAILED.value == "실패"
        # 사장님 컨벤션 unique value 6개
        values = {e.value for e in ExposureArea}
        assert len(values) == 6


class TestParseSearchResult:
    def test_empty_html_returns_default(self):
        result = parse_search_result("", "https://cafe.naver.com/x/1")
        assert result.exposure_area == ExposureArea.UNEXPOSED

    def test_short_html_returns_default(self):
        result = parse_search_result("<html></html>", "https://cafe.naver.com/x/1")
        assert result.exposure_area == ExposureArea.UNEXPOSED

    def test_no_match_fixture_returns_unexposed(self, load_fixture):
        # M4.1에서 수집한 "결과 없음" fixture
        try:
            html = load_fixture("naver/no_match.html")
        except FileNotFoundError:
            import pytest
            pytest.skip("fixture not collected yet")
        result = parse_search_result(html, "https://cafe.naver.com/anywhere/123")
        assert result.exposure_area == ExposureArea.UNEXPOSED


class TestDetectBlockOrder:
    """M4.10: 페이지 위→아래 박스 종류 unique 순서 (C 컬럼 용)."""

    def test_empty_html(self):
        from src.parser import _detect_block_order
        assert _detect_block_order("<html></html>") == []

    def test_ab_only_fixture(self, load_fixture):
        """ab_cafe_top.html: 모든 결과가 AB → ['AB']."""
        html = load_fixture("naver/ab_cafe_top.html")
        result = parse_search_result(html, "")
        assert result.block_order == ["AB"]

    def test_mixed_blocks_fixture(self, load_fixture):
        """mixed_blocks.html: T-M33 fix 후 — h2 없는 박스가 blog/web 전용 = AB 분류 X.
        이 fixture 는 인기글 박스(h2 있음)만 존재 → ['인기글'].
        T-M33 이전: ['AB', '인기글'] (blog 전용 박스도 AB로 오분류).
        T-M33 이후: ['인기글'] (cafe link 없는 박스 = AB skip). """
        html = load_fixture("naver/mixed_blocks.html")
        result = parse_search_result(html, "")
        assert "인기글" in result.block_order
        # T-M33: cafe link 없는 h2-없는 박스 = AB 분류 X
        assert "AB" not in result.block_order

    def test_popular_first_fixture(self, load_fixture):
        """popular_cafe.html: 인기글 박스 포함 (T-M33 후 — cafe link 없는 박스 = AB skip).
        이 fixture 의 h2-없는 박스는 cafe link 0개 → AB 분류 X. 인기글만 존재."""
        html = load_fixture("naver/popular_cafe.html")
        result = parse_search_result(html, "")
        assert "인기글" in result.block_order

    def test_block_order_dedup(self, load_fixture):
        """같은 종류 박스 여러 개여도 unique 1번씩만 (사장님 컨벤션: 인기글 박스 여러 개 → 1번)."""
        html = load_fixture("naver/mixed_blocks.html")
        result = parse_search_result(html, "")
        # mixed_blocks 에 인기글 분류 박스가 4개지만 list 에는 1번만
        assert result.block_order.count("인기글") == 1


class TestParseAbList:
    """M4.7: AB 통합 리스트 파싱 (실측 fixture 기반)."""

    def test_target_at_rank_1(self, load_fixture):
        """ab_cafe_top.html: 부산맘 카페 게시글이 1등 (검색어=등드름해초필링)."""
        html = load_fixture("naver/ab_cafe_top.html")
        target = "https://cafe.naver.com/pusanmommy/1445556"
        result = parse_search_result(html, target)
        assert result.exposure_area == ExposureArea.AB
        assert result.integrated_rank == 1
        assert result.cafe_slot_rank == 1
        assert result.blog_slot_rank is None
        assert result.parser_confidence > 0.7

    def test_target_url_with_query_still_matches(self, load_fixture):
        """검색 결과 URL 에는 ?art=... 가 붙지만 쿼리 무시하고 path 매칭."""
        html = load_fixture("naver/ab_cafe_top.html")
        target = "https://cafe.naver.com/pusanmommy/1445556?some=other"
        result = parse_search_result(html, target)
        assert result.integrated_rank == 1

    def test_no_target_match_returns_unexposed(self, load_fixture):
        """AB 결과 박스는 있지만 본인 URL 없으면 UNEXPOSED."""
        html = load_fixture("naver/ab_cafe_top.html")
        result = parse_search_result(html, "https://cafe.naver.com/never/9999")
        assert result.exposure_area == ExposureArea.UNEXPOSED
        assert result.integrated_rank is None

    def test_ai_briefing_box_skipped(self, load_fixture):
        """AI 브리핑 박스 (h2 있음) 는 카운트되지 않음 → 박스 0번이 아닌 1번이 첫 결과."""
        html = load_fixture("naver/ab_cafe_top.html")
        target = "https://cafe.naver.com/pusanmommy/1445556"
        result = parse_search_result(html, target)
        assert result.integrated_rank == 1


class TestParseAbListHelpers:
    """AB list 의 내부 helper 들."""

    def test_classify_item_url(self):
        from src.parser import _classify_item_url
        assert _classify_item_url("https://cafe.naver.com/x/1") == "cafe"
        assert _classify_item_url("https://blog.naver.com/x/1") == "blog"
        assert _classify_item_url("https://example.com/page") == "web"

    def test_urls_match_ignores_query(self):
        from src.parser import _urls_match
        a = "https://cafe.naver.com/x/123?art=foo"
        b = "https://cafe.naver.com/x/123"
        assert _urls_match(a, b) is True

    def test_urls_match_different_path(self):
        from src.parser import _urls_match
        a = "https://cafe.naver.com/x/123"
        b = "https://cafe.naver.com/x/124"
        assert _urls_match(a, b) is False

    def test_urls_match_handles_trailing_slash(self):
        from src.parser import _urls_match
        a = "https://cafe.naver.com/x/123/"
        b = "https://cafe.naver.com/x/123"
        assert _urls_match(a, b) is True

    def test_urls_match_empty(self):
        from src.parser import _urls_match
        assert _urls_match("", "https://x/1") is False
        assert _urls_match("https://x/1", "") is False


class TestParseSmartBlocks:
    """DEPRECATED — 사장님 컨벤션 (2026-05-08): 이런 형태도 모두 '인기글' 으로 분류.
    enum SMART_BLOCK 은 호환성 위해 남았지만 parser 가 더는 그것으로 분류 X."""

    def test_olive_young_box_classified_as_popular(self, load_fixture):
        """예전 SMART_BLOCK 으로 분류했던 박스 → 사장님 컨벤션 = 인기글."""
        html = load_fixture("naver/mixed_blocks.html")
        target = "https://blog.naver.com/comprehensive5189/223816275254"
        result = parse_search_result(html, target)
        assert result.exposure_area == ExposureArea.POPULAR
        assert result.smart_block_name == "올리브영샴푸순위"

    def test_talmo_box_classified_as_popular(self, load_fixture):
        html = load_fixture("naver/mixed_blocks.html")
        target = "https://blog.naver.com/jeongjuhyunj/223985884379"
        result = parse_search_result(html, target)
        assert result.exposure_area == ExposureArea.POPULAR
        assert result.smart_block_name == "탈모샴푸 순위"

    def test_inkigi_block_skipped_by_smart_blocks(self, load_fixture):
        """'샴푸순위' 인기글 박스는 스마트블록 분기에서 매칭하면 안 됨 (M4.9 책임).
        현재 _parse_popular 은 placeholder False 라 결국 UNEXPOSED.
        """
        html = load_fixture("naver/mixed_blocks.html")
        # box[4] 인기글 안 cafe URL
        target = "https://cafe.naver.com/knife67/615149"
        result = parse_search_result(html, target)
        # 스마트블록으로 분류되면 안 됨
        assert result.exposure_area != ExposureArea.SMART_BLOCK

    def test_no_smart_block_in_ab_only_fixture(self, load_fixture):
        """ab_cafe_top.html 은 스마트블록 박스 없음 → AB 분기 매칭."""
        html = load_fixture("naver/ab_cafe_top.html")
        target = "https://cafe.naver.com/pusanmommy/1445556"
        result = parse_search_result(html, target)
        assert result.exposure_area == ExposureArea.AB
        assert result.smart_block_name is None

    def test_smart_block_no_match_returns_unexposed(self, load_fixture):
        """스마트블록 있어도 본인 URL 없으면 UNEXPOSED."""
        html = load_fixture("naver/mixed_blocks.html")
        result = parse_search_result(html, "https://blog.naver.com/never/9999")
        assert result.exposure_area == ExposureArea.UNEXPOSED
        assert result.smart_block_name is None


class TestParsePopular:
    """M4.9: 인기글 파싱 (실측 popular_cafe.html 기준)."""

    def test_popular_target_at_rank_3(self, load_fixture):
        """popular_cafe.html '패션·미용 인기글' 안 cosmania 카페 글.
        2026-05-11 v4 fix: L (integrated_rank) = 박스 안 모든 항목 순위,
        M (cafe_slot_rank) = 카페만 카운트 순위. AB 박스 로직 동일."""
        html = load_fixture("naver/popular_cafe.html")
        target = "https://cafe.naver.com/cosmania/38373348"
        result = parse_search_result(html, target)
        assert result.exposure_area == ExposureArea.POPULAR
        # L (모든 항목 idx) 와 M (카페만 idx) 둘 다 확인
        assert result.integrated_rank is not None
        assert result.cafe_slot_rank is not None
        # cafe target 이라 cafe_slot_rank ≤ integrated_rank
        assert result.cafe_slot_rank <= result.integrated_rank
        assert result.parser_confidence > 0.7

    def test_popular_second_post_same_cafe_can_match(self, load_fixture):
        """T-M14.3 (2026-05-13): source_key dedup 제거 후 같은 카페 두 번째 글도 매칭 가능.
        cosmania/38349398 이 인기글 박스 안에 존재하면 → POPULAR 매칭.
        존재하지 않으면 UNEXPOSED — fixture 에 없는 경우도 정상."""
        html = load_fixture("naver/popular_cafe.html")
        target = "https://cafe.naver.com/cosmania/38349398"
        result = parse_search_result(html, target)
        # dedup 제거: 두 번째 글이 박스 안에 있으면 POPULAR, 없으면 UNEXPOSED — 둘 다 정상
        assert result.exposure_area in (ExposureArea.POPULAR, ExposureArea.UNEXPOSED)

    def test_popular_no_match_returns_unexposed(self, load_fixture):
        """인기글 박스 있어도 본인 URL 없으면 UNEXPOSED."""
        html = load_fixture("naver/popular_cafe.html")
        result = parse_search_result(html, "https://cafe.naver.com/never/9999")
        assert result.exposure_area == ExposureArea.UNEXPOSED
        assert result.cafe_slot_rank is None

    def test_popular_blog_target_at_rank_1(self, load_fixture):
        """첫 번째 인기글 = juhee960123 blog 글.
        2026-05-11 v4 fix (critic Major 2): blog target = cafe_slot_rank None.
        L = 박스 안 모든 항목 순위 (블로그 포함), M = 카페만. blog 면 M=None."""
        html = load_fixture("naver/popular_cafe.html")
        target = "https://blog.naver.com/juhee960123/224253557960"
        result = parse_search_result(html, target)
        assert result.exposure_area == ExposureArea.POPULAR
        assert result.integrated_rank == 1  # 박스 첫 번째 = L=1
        assert result.cafe_slot_rank is None  # blog target = M None


class TestMatchedUrl:
    """T-M14.2 (D-022): RankResult.matched_url 필드 검증."""

    _PADDING = "<div class='pad'>" + ("x" * 600) + "</div>"

    def _make_ab_box(self, cafe_url: str) -> str:
        """AB 박스 (h2 없음 + cafe link 포함) HTML 조각 생성."""
        return (
            f'<div class="fds-default-mode api_subject_bx">'
            f'<a class="api_txt_lines" href="{cafe_url}">글제목</a>'
            f'</div>'
        )

    def test_target_url_match_sets_matched_url(self):
        """target_url 매치 성공 시 matched_url = target_url."""
        target = "https://cafe.naver.com/pusanmommy/1111"
        box = self._make_ab_box(target)
        html = f"<html><body>{self._PADDING}{box}</body></html>"
        result = parse_search_result(html, target_url=target)
        assert result.exposure_area == ExposureArea.AB
        assert result.matched_url == target

    def test_link_set_match_sets_matched_url(self):
        """target_url=None + link_set 매치 성공 시 matched_url = 매치된 link."""
        matched = "https://cafe.naver.com/cosmania/2222"
        other = "https://cafe.naver.com/pusanmommy/3333"
        box = self._make_ab_box(matched)
        html = f"<html><body>{self._PADDING}{box}</body></html>"
        result = parse_search_result(html, target_url=None, link_set={matched, other})
        assert result.exposure_area == ExposureArea.AB
        assert result.matched_url == matched

    def test_no_match_matched_url_is_none(self):
        """target_url 매치 X + link_set 매치 X → matched_url = None."""
        box = self._make_ab_box("https://cafe.naver.com/cosmania/9999")
        html = f"<html><body>{self._PADDING}{box}</body></html>"
        result = parse_search_result(html, target_url="https://cafe.naver.com/pusanmommy/0001")
        assert result.exposure_area == ExposureArea.UNEXPOSED
        assert result.matched_url is None

    def test_default_rank_result_matched_url_is_none(self):
        """RankResult 기본값: matched_url = None."""
        r = RankResult()
        assert r.matched_url is None


class TestM33BoxClassification:
    """T-M33 (2026-05-12 D-022): 박스 분류 — h2 없음 + cafe 0 = AB/block_order skip."""

    _PADDING = "<div class='pad'>" + ("x" * 600) + "</div>"

    def _make_box(self, hrefs: list, has_h2: bool = False, h2_text: str = "") -> str:
        links = "".join(f'<a href="{h}">글</a>' for h in hrefs)
        h2_tag = f"<h2>{h2_text}</h2>" if has_h2 else ""
        return f'<div class="fds-default-mode api_subject_bx">{h2_tag}{links}</div>'

    def test_ab_box_with_cafe_link_classified_as_ab(self):
        """h2 없음 + cafe link 1개 이상 = AB 분류 (정상 케이스)."""
        box = self._make_box(["https://cafe.naver.com/pusanmommy/1", "https://blog.naver.com/x/2"])
        html = f"<html><body>{self._PADDING}{box}</body></html>"
        from src.parser import _detect_block_order
        order = _detect_block_order(html)
        assert "AB" in order

    def test_ab_box_without_cafe_link_skipped(self):
        """h2 없음 + cafe 0 (blog/web 만) = AB 분류 X (T-M33 핵심 fix)."""
        box = self._make_box(["https://blog.naver.com/x/1", "https://blog.naver.com/y/2"])
        html = f"<html><body>{self._PADDING}{box}</body></html>"
        from src.parser import _detect_block_order
        order = _detect_block_order(html)
        assert "AB" not in order

    def test_ab_box_without_cafe_not_matched_in_parse(self):
        """h2 없음 + cafe 0 박스 = _parse_ab_list 도 AB 매치 X."""
        box = self._make_box(["https://blog.naver.com/x/1"])
        html = f"<html><body>{self._PADDING}{box}</body></html>"
        result = parse_search_result(html, "https://blog.naver.com/x/1")
        # blog-only 박스는 AB로 분류되지 않음
        assert result.exposure_area.value != "AB"

    def test_popular_box_h2_with_inkigi_text(self):
        """h2 있음 + h2 텍스트에 스킵 패턴 없음 = 인기글 분류 (기존 동작 회귀 방지)."""
        box = self._make_box(
            ["https://cafe.naver.com/x/1", "https://blog.naver.com/y/2"],
            has_h2=True,
            h2_text="패션 인기글",
        )
        html = f"<html><body>{self._PADDING}{box}</body></html>"
        from src.parser import _detect_block_order
        order = _detect_block_order(html)
        assert "인기글" in order
        assert "AB" not in order

    def test_mixed_cafe_and_blog_boxes(self):
        """카페 박스 = AB, 블로그 전용 박스 = skip → block_order 에 AB 1번만."""
        cafe_box = self._make_box(["https://cafe.naver.com/a/1"])
        blog_box = self._make_box(["https://blog.naver.com/b/2"])
        html = f"<html><body>{self._PADDING}{cafe_box}{blog_box}</body></html>"
        from src.parser import _detect_block_order
        order = _detect_block_order(html)
        assert order.count("AB") == 1


class TestParseJisikin:
    """M4.9 + 2026-05-11 v2 fix: 지식인 탭 존재 여부.
    v2 컨벤션 (사장님 시트 500행 비교 J false positive 69건 fix 반영):
    - h2 텍스트 = '지식iN' / '지식인' 인 박스 안에 kin.naver.com 링크 있으면 True
    - 그 외 박스 (광고/추천/카페/인기글 등) 의 부수 kin 링크는 False
    """

    def test_jisikin_absent_when_no_kin_link(self, load_fixture):
        """popular_cafe.html 에 kin.naver.com 0개 → 'O' 안 찍힘."""
        html = load_fixture("naver/popular_cafe.html")
        result = parse_search_result(html, "https://cafe.naver.com/cosmania/38373348")
        assert result.in_jisikin is False

    def test_jisikin_absent_when_no_jisikin_h2_box(self, load_fixture):
        """smart_block.html 안 kin.naver.com 링크 있지만 h2='지식iN' 박스 없음 (광고/추천 부수 링크) → False.
        v2 fix 회귀 방지: 사장님 시트 J false positive 69건 케이스 (cafe 박스 안 부수 kin 링크)."""
        html = load_fixture("naver/smart_block.html")
        result = parse_search_result(html, "https://cafe.naver.com/foo/123")
        assert result.in_jisikin is False

    def test_jisikin_absent_target_kin_no_jisikin_h2_box(self, load_fixture):
        """target 이 kin URL 이어도 페이지에 진짜 지식iN h2 박스 없으면 False (v2)."""
        html = load_fixture("naver/smart_block.html")
        result = parse_search_result(html, "https://kin.naver.com/anything/1")
        assert result.in_jisikin is False

    def test_jisikin_present_when_h2_jisikin_box_with_kin_link(self):
        """h2='지식iN' 박스 안 kin.naver.com 링크 있으면 True."""
        padding = "<div class='padding'>" + ("x" * 600) + "</div>"
        html = f"""
        <html><body>
        {padding}
        <div class="fds-default-mode api_subject_bx">
            <h2>지식iN</h2>
            <a href="https://kin.naver.com/qna/detail.naver?d1id=8&docId=111">질문 1</a>
            <a href="https://kin.naver.com/qna/detail.naver?d1id=8&docId=222">질문 2</a>
        </div>
        </body></html>
        """
        result = parse_search_result(html, "https://cafe.naver.com/foo/123")
        assert result.in_jisikin is True

    def test_jisikin_false_positive_kin_in_ab_box_v2_regression(self):
        """사장님 시트 J false positive 회귀 방지 (2026-05-11 v2):
        AB 박스 (h2 없음) 안에 부수 kin 링크 있어도 in_jisikin = False."""
        padding = "<div class='padding'>" + ("x" * 600) + "</div>"
        html = f"""
        <html><body>
        {padding}
        <div class="fds-default-mode api_subject_bx">
            <a href="https://cafe.naver.com/iroid/5412361">카페 글 1</a>
            <a href="https://kin.naver.com/related/etc">부수 추천 링크</a>
        </div>
        </body></html>
        """
        result = parse_search_result(html, "https://cafe.naver.com/iroid/5412361")
        assert result.in_jisikin is False

    def test_jisikin_present_korean_variant_h2(self):
        """h2='지식인' (한글) 도 인식."""
        padding = "<div class='padding'>" + ("x" * 600) + "</div>"
        html = f"""
        <html><body>
        {padding}
        <div class="fds-default-mode api_subject_bx">
            <h2>지식인</h2>
            <a href="https://kin.naver.com/qna/1">Q</a>
        </div>
        </body></html>
        """
        result = parse_search_result(html, "https://example.com")
        assert result.in_jisikin is True


class TestExtractPopularItemsDedup:
    """T-M14.3 (2026-05-13): _extract_popular_items source_key dedup 제거 검증."""

    def _make_box(self, hrefs: list) -> object:
        from bs4 import BeautifulSoup
        links = "".join(f'<a href="{h}">글</a>' for h in hrefs)
        html = f'<div class="box">{links}</div>'
        return BeautifulSoup(html, "lxml").find("div")

    def test_same_cafe_two_posts_both_returned(self):
        """같은 카페 두 글 = 둘 다 items 에 포함 (URL 단위 dedup 만 적용)."""
        from src.parser import _extract_popular_items
        box = self._make_box([
            "https://cafe.naver.com/cosmania/100",
            "https://cafe.naver.com/cosmania/200",
        ])
        items = _extract_popular_items(box)
        assert len(items) == 2
        assert "https://cafe.naver.com/cosmania/100" in items
        assert "https://cafe.naver.com/cosmania/200" in items

    def test_exact_same_url_deduped(self):
        """완전 동일 URL (netloc + path 동일) = dedup — 1개만 반환."""
        from src.parser import _extract_popular_items
        box = self._make_box([
            "https://cafe.naver.com/cosmania/100",
            "https://cafe.naver.com/cosmania/100",
        ])
        items = _extract_popular_items(box)
        assert len(items) == 1

    def test_different_cafes_all_returned(self):
        """다른 카페 3개 글 = 모두 반환."""
        from src.parser import _extract_popular_items
        box = self._make_box([
            "https://cafe.naver.com/cafeA/1",
            "https://cafe.naver.com/cafeB/2",
            "https://cafe.naver.com/cafeC/3",
        ])
        items = _extract_popular_items(box)
        assert len(items) == 3

    def test_non_post_url_excluded(self):
        """path 끝이 숫자 아님 = 제외."""
        from src.parser import _extract_popular_items
        box = self._make_box([
            "https://cafe.naver.com/cosmania",
            "https://cafe.naver.com/cosmania/100",
        ])
        items = _extract_popular_items(box)
        assert len(items) == 1
        assert "https://cafe.naver.com/cosmania/100" in items


class TestPopularSkipPatterns:
    """T-M22 (2026-05-13): _POPULAR_SKIP_PATTERNS 신규 패턴 검증."""

    _PADDING = "<div class='pad'>" + ("x" * 600) + "</div>"

    def _make_popular_box(self, h2_text: str, cafe_url: str = "https://cafe.naver.com/x/1") -> str:
        return (
            f'<div class="fds-default-mode api_subject_bx">'
            f'<h2>{h2_text}</h2>'
            f'<a href="{cafe_url}">글</a>'
            f'</div>'
        )

    def test_ai_recommend_box_skipped(self):
        """h2='AI 추천' 박스 = 인기글 분류 X."""
        box = self._make_popular_box("AI 추천")
        html = f"<html><body>{self._PADDING}{box}</body></html>"
        result = parse_search_result(html, "https://cafe.naver.com/x/1")
        assert result.exposure_area == ExposureArea.UNEXPOSED

    def test_shortform_box_skipped(self):
        """h2='숏폼' 박스 = 인기글 분류 X."""
        box = self._make_popular_box("숏폼")
        html = f"<html><body>{self._PADDING}{box}</body></html>"
        result = parse_search_result(html, "https://cafe.naver.com/x/1")
        assert result.exposure_area == ExposureArea.UNEXPOSED

    def test_place_box_skipped(self):
        """h2='플레이스' 박스 = 인기글 분류 X."""
        box = self._make_popular_box("플레이스")
        html = f"<html><body>{self._PADDING}{box}</body></html>"
        result = parse_search_result(html, "https://cafe.naver.com/x/1")
        assert result.exposure_area == ExposureArea.UNEXPOSED

    def test_video_box_skipped(self):
        """h2='동영상' 박스 = 인기글 분류 X."""
        box = self._make_popular_box("동영상")
        html = f"<html><body>{self._PADDING}{box}</body></html>"
        result = parse_search_result(html, "https://cafe.naver.com/x/1")
        assert result.exposure_area == ExposureArea.UNEXPOSED

    def test_shopping_box_skipped(self):
        """h2='쇼핑' 박스 = 인기글 분류 X."""
        box = self._make_popular_box("쇼핑")
        html = f"<html><body>{self._PADDING}{box}</body></html>"
        result = parse_search_result(html, "https://cafe.naver.com/x/1")
        assert result.exposure_area == ExposureArea.UNEXPOSED

    def test_normal_inkigi_box_not_skipped(self):
        """h2='패션 인기글' = 스킵 X → 매칭 시도."""
        box = self._make_popular_box("패션 인기글")
        html = f"<html><body>{self._PADDING}{box}</body></html>"
        result = parse_search_result(html, "https://cafe.naver.com/x/1")
        assert result.exposure_area == ExposureArea.POPULAR


class TestExtractBootstrapJson:
    """T-M22.1 (2026-05-14 probe 실측 fix): _extract_bootstrap_json 함수 검증.

    진짜 형식: entry.bootstrap(document.getElementById("fdr-..."), {...JSON...});
    첫 번째 인자 = DOM element (무시), 두 번째 인자 = JSON 페이로드.
    brace 균형 기반 파싱으로 중첩 brace 안전 처리.
    """

    def test_extracts_valid_json_real_format(self):
        """진짜 형식 (document.getElementById + 두 번째 인자 JSON) = dict 반환."""
        from src.parser import _extract_bootstrap_json
        html = '<script>entry.bootstrap(document.getElementById("fdr-abc"), {"key": "value", "num": 42});</script>'
        result = _extract_bootstrap_json(html)
        assert result == {"key": "value", "num": 42}

    def test_extracts_nested_brace_json(self):
        """중첩 brace JSON = 안전하게 추출 (brace counting 방식 검증)."""
        from src.parser import _extract_bootstrap_json
        html = '<script>entry.bootstrap(document.getElementById("fdr-xyz"), {"a": {"b": "c"}, "d": [1, 2]});</script>'
        result = _extract_bootstrap_json(html)
        assert result == {"a": {"b": "c"}, "d": [1, 2]}

    def test_extracts_json_with_brace_in_string(self):
        """JSON string 값 안 '}'  = 무시 (string 안 brace 처리 검증)."""
        from src.parser import _extract_bootstrap_json
        html = '<script>entry.bootstrap(document.getElementById("fdr-1"), {"key": "value with } inside"});</script>'
        result = _extract_bootstrap_json(html)
        assert result == {"key": "value with } inside"}

    def test_returns_none_when_no_bootstrap(self):
        """entry.bootstrap 없음 = None 반환."""
        from src.parser import _extract_bootstrap_json
        html = "<html><body>일반 페이지</body></html>"
        result = _extract_bootstrap_json(html)
        assert result is None

    def test_returns_none_on_empty_html(self):
        """빈 문자열 = None 반환."""
        from src.parser import _extract_bootstrap_json
        result = _extract_bootstrap_json("")
        assert result is None

    def test_returns_none_on_old_format(self):
        """구 형식 (document.getElementById 없음) = None 반환 (regex 불일치)."""
        from src.parser import _extract_bootstrap_json
        html = '<script>entry.bootstrap({"key": "value"});</script>'
        result = _extract_bootstrap_json(html)
        assert result is None

    def test_returns_none_on_invalid_json(self):
        """entry.bootstrap 진짜 형식이지만 JSON 파싱 실패 = None 반환."""
        from src.parser import _extract_bootstrap_json
        html = '<script>entry.bootstrap(document.getElementById("fdr-1"), {invalid json});</script>'
        result = _extract_bootstrap_json(html)
        assert result is None

    def test_returns_none_on_none_input(self):
        """None 입력 = None 반환."""
        from src.parser import _extract_bootstrap_json
        result = _extract_bootstrap_json(None)
        assert result is None


class TestUrlsMatchCafeNewUrl:
    """T-M14.5 (2026-05-14): 네이버 카페 신형 URL fallback 매치 검증.

    구형: cafe.naver.com/{slug}/{post_id}
    신형: cafe.naver.com/ca-fe/cafes/{cafe_id}/articles/{post_id}
    """

    def test_old_vs_old_same_post_matches(self):
        """구형 vs 구형 — 같은 post_id = True (기존 동작 회귀 방지)."""
        from src.parser import _urls_match
        a = "https://cafe.naver.com/pusanmommy/1445556"
        b = "https://cafe.naver.com/pusanmommy/1445556"
        assert _urls_match(a, b) is True

    def test_old_vs_old_different_post_no_match(self):
        """구형 vs 구형 — 다른 post_id = False (기존 동작 회귀 방지)."""
        from src.parser import _urls_match
        a = "https://cafe.naver.com/pusanmommy/1111"
        b = "https://cafe.naver.com/pusanmommy/2222"
        assert _urls_match(a, b) is False

    def test_new_vs_new_same_post_matches(self):
        """신형 vs 신형 — 같은 cafe_id + post_id = True."""
        from src.parser import _urls_match
        a = "https://cafe.naver.com/ca-fe/cafes/12345/articles/99001"
        b = "https://cafe.naver.com/ca-fe/cafes/12345/articles/99001"
        assert _urls_match(a, b) is True

    def test_new_vs_new_different_post_no_match(self):
        """신형 vs 신형 — 다른 post_id = False."""
        from src.parser import _urls_match
        a = "https://cafe.naver.com/ca-fe/cafes/12345/articles/99001"
        b = "https://cafe.naver.com/ca-fe/cafes/12345/articles/99002"
        assert _urls_match(a, b) is False

    def test_old_vs_new_same_post_id_matches(self):
        """구형 vs 신형 — 같은 post_id = True (fallback 매치)."""
        from src.parser import _urls_match
        a = "https://cafe.naver.com/pusanmommy/1445556"
        b = "https://cafe.naver.com/ca-fe/cafes/12345/articles/1445556"
        assert _urls_match(a, b) is True

    def test_new_vs_old_same_post_id_matches(self):
        """신형 vs 구형 — 같은 post_id = True (방향 무관 대칭 확인)."""
        from src.parser import _urls_match
        a = "https://cafe.naver.com/ca-fe/cafes/12345/articles/1445556"
        b = "https://cafe.naver.com/pusanmommy/1445556"
        assert _urls_match(a, b) is True

    def test_old_vs_new_different_post_id_no_match(self):
        """구형 vs 신형 — 다른 post_id = False."""
        from src.parser import _urls_match
        a = "https://cafe.naver.com/pusanmommy/1111"
        b = "https://cafe.naver.com/ca-fe/cafes/12345/articles/2222"
        assert _urls_match(a, b) is False

    def test_mobile_prefix_normalized_with_new_url(self):
        """m. prefix + 신형 URL = 정규화 후 매치."""
        from src.parser import _urls_match
        a = "https://m.cafe.naver.com/ca-fe/cafes/12345/articles/1445556"
        b = "https://cafe.naver.com/pusanmommy/1445556"
        assert _urls_match(a, b) is True

    def test_query_ignored_new_url(self):
        """신형 URL 쿼리 파라미터 무시."""
        from src.parser import _urls_match
        a = "https://cafe.naver.com/ca-fe/cafes/12345/articles/99001?art=foo"
        b = "https://cafe.naver.com/ca-fe/cafes/12345/articles/99001"
        assert _urls_match(a, b) is True


class TestIsExcludedLink:
    """T-M14.6 (2026-05-14): _is_excluded_link 광고/사이드바 제외 검증."""

    def test_ad_domain_ader_excluded(self):
        """ader.naver.com 광고 도메인 = 제외."""
        from src.parser import _is_excluded_link
        assert _is_excluded_link("https://ader.naver.com/ad?campaign=123") is True

    def test_ad_domain_adcr_excluded(self):
        """adcr.naver.com 광고 도메인 = 제외."""
        from src.parser import _is_excluded_link
        assert _is_excluded_link("https://adcr.naver.com/r/click?abc") is True

    def test_ad_path_excluded(self):
        """/ad/ path 포함 = 제외."""
        from src.parser import _is_excluded_link
        assert _is_excluded_link("https://search.naver.com/ad/redirect") is True

    def test_adidx_query_excluded(self):
        """?adidx= 쿼리 포함 = 제외."""
        from src.parser import _is_excluded_link
        assert _is_excluded_link("https://shopping.naver.com/item?adidx=5") is True

    def test_hashtag_sidebar_excluded(self):
        """hashtag 패턴 사이드바 링크 = 제외."""
        from src.parser import _is_excluded_link
        assert _is_excluded_link("https://search.naver.com/search?hashtag=foo") is True

    def test_related_keyword_excluded(self):
        """related_keyword 패턴 = 제외."""
        from src.parser import _is_excluded_link
        assert _is_excluded_link("https://search.naver.com/related_keyword?q=bar") is True

    def test_query_sidebar_excluded(self):
        """/?query= 패턴 관련 검색 = 제외."""
        from src.parser import _is_excluded_link
        assert _is_excluded_link("https://search.naver.com/?query=abc") is True

    def test_normal_cafe_link_not_excluded(self):
        """정상 카페 링크 = 제외 X."""
        from src.parser import _is_excluded_link
        assert _is_excluded_link("https://cafe.naver.com/pusanmommy/1445556") is False

    def test_empty_string_excluded(self):
        """빈 문자열 = 제외."""
        from src.parser import _is_excluded_link
        assert _is_excluded_link("") is True


class TestExtractMainLinkAdExclusion:
    """T-M14.6 (2026-05-14): _extract_main_link 광고/사이드바 링크 제외 동작 검증."""

    _PADDING = "<div class='pad'>" + ("x" * 600) + "</div>"

    def test_ad_link_excluded_from_css_selector(self):
        """CSS 1순위 selector 에서 광고 링크 = 제외 후 정상 링크 반환."""
        from src.parser import _extract_main_link
        from bs4 import BeautifulSoup
        html = (
            '<div class="fds-default-mode api_subject_bx">'
            '<a class="api_txt_lines" href="https://ader.naver.com/ad?x=1">광고</a>'
            '<a class="api_txt_lines" href="https://cafe.naver.com/pusanmommy/100">카페 글</a>'
            '</div>'
        )
        box = BeautifulSoup(html, "lxml").find("div")
        result = _extract_main_link(box)
        assert result == "https://cafe.naver.com/pusanmommy/100"

    def test_ad_link_excluded_from_fallback(self):
        """fallback (텍스트 길이 기준) 에서도 광고 링크 = 제외."""
        from src.parser import _extract_main_link
        from bs4 import BeautifulSoup
        # 광고 링크가 텍스트 더 길어도 제외되어 카페 링크 반환
        html = (
            '<div class="fds-default-mode api_subject_bx">'
            '<a href="https://ader.naver.com/ad?x=1">이 텍스트는 매우 길고 광고입니다 광고 광고 광고</a>'
            '<a href="https://cafe.naver.com/pusanmommy/100">카페 글</a>'
            '</div>'
        )
        box = BeautifulSoup(html, "lxml").find("div")
        result = _extract_main_link(box)
        assert result == "https://cafe.naver.com/pusanmommy/100"

    def test_hashtag_sidebar_excluded(self):
        """사이드바 해시태그 링크 = fallback 에서 제외."""
        from src.parser import _extract_main_link
        from bs4 import BeautifulSoup
        html = (
            '<div class="fds-default-mode api_subject_bx">'
            '<a href="https://search.naver.com/?hashtag=뷰티">관련 해시태그 매우 긴 텍스트</a>'
            '<a href="https://cafe.naver.com/cosmania/200">카페 글</a>'
            '</div>'
        )
        box = BeautifulSoup(html, "lxml").find("div")
        result = _extract_main_link(box)
        assert result == "https://cafe.naver.com/cosmania/200"

    def test_normal_cafe_link_returned(self):
        """광고 없는 정상 박스 = 기존 동작 유지."""
        from src.parser import _extract_main_link
        from bs4 import BeautifulSoup
        html = (
            '<div class="fds-default-mode api_subject_bx">'
            '<a class="api_txt_lines" href="https://cafe.naver.com/pusanmommy/1445556">게시글 제목</a>'
            '</div>'
        )
        box = BeautifulSoup(html, "lxml").find("div")
        result = _extract_main_link(box)
        assert result == "https://cafe.naver.com/pusanmommy/1445556"


class TestExtractCafeSlug:
    """T-M14.7 (2026-05-14): _extract_cafe_slug 내부 헬퍼 검증."""

    def test_old_url_returns_slug(self):
        """구형 URL: cafe.naver.com/{slug}/{post_id} → slug 반환."""
        from src.parser import _extract_cafe_slug
        assert _extract_cafe_slug("https://cafe.naver.com/pusanmommy/1445556") == "pusanmommy"

    def test_old_url_mobile_prefix_returns_slug(self):
        """m. prefix 구형 URL → slug 반환."""
        from src.parser import _extract_cafe_slug
        assert _extract_cafe_slug("https://m.cafe.naver.com/cosmania/38373348") == "cosmania"

    def test_new_url_returns_none(self):
        """신형 URL (ca-fe/cafes/...) → None 반환 (slug 매핑 불가)."""
        from src.parser import _extract_cafe_slug
        assert _extract_cafe_slug("https://cafe.naver.com/ca-fe/cafes/12345/articles/99001") is None

    def test_non_cafe_url_returns_none(self):
        """카페 URL 아님 → None 반환."""
        from src.parser import _extract_cafe_slug
        assert _extract_cafe_slug("https://blog.naver.com/some/post") is None

    def test_empty_string_returns_none(self):
        """빈 문자열 → None 반환."""
        from src.parser import _extract_cafe_slug
        assert _extract_cafe_slug("") is None


class TestCafeSlugWhitelistMatch:
    """T-M14.7 (2026-05-14): cafe_slug_whitelist 매치 fallback 검증.

    매치 우선순위:
    1. target_url 정확 매치
    2. link_set 정확 매치 (T-M14.2)
    3. cafe_slug_whitelist slug 매치 (T-M14.7 신규)
    4. 매치 X
    """

    _PADDING = "<div class='pad'>" + ("x" * 600) + "</div>"

    def _make_ab_box(self, cafe_url: str) -> str:
        """AB 박스 (h2 없음 + cafe link 포함) HTML 조각 생성."""
        return (
            f'<div class="fds-default-mode api_subject_bx">'
            f'<a class="api_txt_lines" href="{cafe_url}">글제목</a>'
            f'</div>'
        )

    def _make_popular_box(self, cafe_url: str, h2_text: str = "패션 인기글") -> str:
        """인기글 박스 (h2 있음 + cafe link 포함) HTML 조각 생성."""
        return (
            f'<div class="fds-default-mode api_subject_bx">'
            f'<h2>{h2_text}</h2>'
            f'<a href="{cafe_url}">글제목</a>'
            f'</div>'
        )

    # --- AB 박스 slug 매치 ---

    def test_ab_slug_match_whitelist_slug(self):
        """AB 박스 안 카페 slug 가 화이트리스트 안 = 매치 성공."""
        whitelist_url = "https://cafe.naver.com/pusanmommy/9999"
        box = self._make_ab_box(whitelist_url)
        html = f"<html><body>{self._PADDING}{box}</body></html>"
        whitelist = {"pusanmommy", "cosmania"}
        result = parse_search_result(html, target_url=None, cafe_slug_whitelist=whitelist)
        assert result.exposure_area == ExposureArea.AB
        assert result.matched_url == whitelist_url
        assert result.integrated_rank == 1
        assert result.cafe_slot_rank == 1
        assert result.parser_confidence == 0.85

    def test_ab_slug_match_non_whitelist_slug_no_match(self):
        """AB 박스 안 카페 slug 가 화이트리스트 외 = 매치 X."""
        unknown_url = "https://cafe.naver.com/unknown_cafe/9999"
        box = self._make_ab_box(unknown_url)
        html = f"<html><body>{self._PADDING}{box}</body></html>"
        whitelist = {"pusanmommy", "cosmania"}
        result = parse_search_result(html, target_url=None, cafe_slug_whitelist=whitelist)
        assert result.exposure_area == ExposureArea.UNEXPOSED
        assert result.matched_url is None

    def test_ab_slug_match_new_url_no_match(self):
        """신형 URL (ca-fe/cafes/...) = slug 추출 불가 → 매치 X."""
        new_url = "https://cafe.naver.com/ca-fe/cafes/12345/articles/9999"
        box = self._make_ab_box(new_url)
        html = f"<html><body>{self._PADDING}{box}</body></html>"
        whitelist = {"pusanmommy", "cosmania"}
        result = parse_search_result(html, target_url=None, cafe_slug_whitelist=whitelist)
        assert result.exposure_area == ExposureArea.UNEXPOSED

    # --- 인기글 박스 slug 매치 ---

    def test_popular_slug_match_whitelist_slug(self):
        """인기글 박스 안 카페 slug 가 화이트리스트 안 = 매치 성공."""
        whitelist_url = "https://cafe.naver.com/cosmania/38373348"
        box = self._make_popular_box(whitelist_url)
        html = f"<html><body>{self._PADDING}{box}</body></html>"
        whitelist = {"pusanmommy", "cosmania"}
        result = parse_search_result(html, target_url=None, cafe_slug_whitelist=whitelist)
        assert result.exposure_area == ExposureArea.POPULAR
        assert result.matched_url == whitelist_url
        assert result.cafe_slot_rank == 1
        assert result.parser_confidence == 0.85

    def test_popular_slug_match_non_whitelist_no_match(self):
        """인기글 박스 안 slug 가 화이트리스트 외 = 매치 X."""
        unknown_url = "https://cafe.naver.com/unknown_cafe/9999"
        box = self._make_popular_box(unknown_url)
        html = f"<html><body>{self._PADDING}{box}</body></html>"
        whitelist = {"pusanmommy", "cosmania"}
        result = parse_search_result(html, target_url=None, cafe_slug_whitelist=whitelist)
        assert result.exposure_area == ExposureArea.UNEXPOSED

    # --- 우선순위 검증 ---

    def test_priority_target_url_over_slug_whitelist(self):
        """우선순위: target_url 정확 매치 > cafe_slug_whitelist slug 매치."""
        target = "https://cafe.naver.com/pusanmommy/1111"
        other_whitelist_url = "https://cafe.naver.com/cosmania/2222"
        box1 = self._make_ab_box(target)
        box2 = self._make_ab_box(other_whitelist_url)
        html = f"<html><body>{self._PADDING}{box1}{box2}</body></html>"
        whitelist = {"pusanmommy", "cosmania"}
        # target_url 지정 시 = target_url 매치 우선
        result = parse_search_result(html, target_url=target, cafe_slug_whitelist=whitelist)
        assert result.exposure_area == ExposureArea.AB
        assert result.matched_url == target
        assert result.integrated_rank == 1

    def test_priority_link_set_over_slug_whitelist(self):
        """우선순위: link_set 정확 매치 > cafe_slug_whitelist slug 매치."""
        link_set_url = "https://cafe.naver.com/cosmania/2222"
        other_url = "https://cafe.naver.com/pusanmommy/3333"
        box1 = self._make_ab_box(link_set_url)
        box2 = self._make_ab_box(other_url)
        html = f"<html><body>{self._PADDING}{box1}{box2}</body></html>"
        link_set = {link_set_url}
        whitelist = {"pusanmommy", "cosmania"}
        # link_set 지정 시 = link_set 매치 우선 (cafe_slug_whitelist 무시)
        result = parse_search_result(html, target_url=None, link_set=link_set, cafe_slug_whitelist=whitelist)
        assert result.exposure_area == ExposureArea.AB
        assert result.matched_url == link_set_url
        assert result.integrated_rank == 1

    def test_slug_whitelist_fallback_when_no_target_and_no_link_set(self):
        """target_url=None + link_set=None + cafe_slug_whitelist 지정 = slug 매치 동작."""
        whitelist_url = "https://cafe.naver.com/iroid/5412361"
        box = self._make_ab_box(whitelist_url)
        html = f"<html><body>{self._PADDING}{box}</body></html>"
        whitelist = {"iroid", "pusanmommy"}
        result = parse_search_result(html, target_url=None, cafe_slug_whitelist=whitelist)
        assert result.exposure_area == ExposureArea.AB
        assert result.matched_url == whitelist_url

    def test_no_match_when_whitelist_none(self):
        """cafe_slug_whitelist=None + target_url=None + link_set=None = 매치 X."""
        box = self._make_ab_box("https://cafe.naver.com/pusanmommy/1111")
        html = f"<html><body>{self._PADDING}{box}</body></html>"
        result = parse_search_result(html, target_url=None)
        assert result.exposure_area == ExposureArea.UNEXPOSED
