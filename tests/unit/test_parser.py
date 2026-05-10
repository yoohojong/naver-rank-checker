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
        """mixed_blocks.html: 사장님 컨벤션 = AB + 인기글 (구 SMART_BLOCK 박스도 인기글로 합쳐짐)."""
        html = load_fixture("naver/mixed_blocks.html")
        result = parse_search_result(html, "")
        assert result.block_order == ["AB", "인기글"]

    def test_popular_first_fixture(self, load_fixture):
        """popular_cafe.html: 인기글 먼저 등장, 그 후 AB."""
        html = load_fixture("naver/popular_cafe.html")
        result = parse_search_result(html, "")
        assert result.block_order == ["인기글", "AB"]

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
        """popular_cafe.html '패션·미용 인기글' 안 cosmania 카페 글이 3등."""
        html = load_fixture("naver/popular_cafe.html")
        target = "https://cafe.naver.com/cosmania/38373348"
        result = parse_search_result(html, target)
        assert result.exposure_area == ExposureArea.POPULAR
        assert result.cafe_slot_rank == 3
        assert result.parser_confidence > 0.7

    def test_popular_dedup_same_source(self, load_fixture):
        """같은 출처 (cosmania) 의 다른 글도 같은 출처 idx 매칭 — 첫 본문만 카운트되므로 3등 동일."""
        html = load_fixture("naver/popular_cafe.html")
        # cosmania/38349398 은 cosmania 출처 의 두번째 글 — 출처 dedup 으로 idx 3 = 첫 글 (38373348) 만 매칭
        # 따라서 38349398 은 매칭 X (이미 첫 본문 38373348 으로 idx 3 사용)
        target = "https://cafe.naver.com/cosmania/38349398"
        result = parse_search_result(html, target)
        # 두번째 글은 인기글로 카운트 안 됨 → UNEXPOSED 또는 별도 처리
        # 사장님 컨벤션: 첫 글만 인기글, 다른 글은 UNEXPOSED
        assert result.cafe_slot_rank != 3 or result.exposure_area != ExposureArea.POPULAR

    def test_popular_no_match_returns_unexposed(self, load_fixture):
        """인기글 박스 있어도 본인 URL 없으면 UNEXPOSED."""
        html = load_fixture("naver/popular_cafe.html")
        result = parse_search_result(html, "https://cafe.naver.com/never/9999")
        assert result.exposure_area == ExposureArea.UNEXPOSED
        assert result.cafe_slot_rank is None

    def test_popular_blog_target_at_rank_1(self, load_fixture):
        """첫 번째 인기글 = juhee960123 blog 글. 사장님 컨벤션: 인기글에서 L=M (같은 idx)."""
        html = load_fixture("naver/popular_cafe.html")
        target = "https://blog.naver.com/juhee960123/224253557960"
        result = parse_search_result(html, target)
        assert result.exposure_area == ExposureArea.POPULAR
        assert result.integrated_rank == 1
        assert result.cafe_slot_rank == 1


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
