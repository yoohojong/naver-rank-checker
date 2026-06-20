"""jisikin_filter 단위 테스트 — 보수적 쓰레기 판정 검증.

버려야 하는 것: 빈값 / 너무 짧음 / 전화+URL 동시 / URL 2개 이상.
남겨야 하는 것(보수성 검증): 정상 고객글 / 업체명만 있는 글 / 전화만 있는 글.
"""
import pytest

from src.jisikin_filter import is_junk


# ── 버려야 하는 케이스 ──────────────────────────────────────────────────

class TestShouldDiscard:

    def test_both_empty(self):
        """제목·설명 모두 빈값 → 버림."""
        junk, reason = is_junk("", "")
        assert junk is True
        assert reason

    def test_both_whitespace_only(self):
        """공백만 있는 경우도 빈값과 동일 → 버림."""
        junk, reason = is_junk("   ", "\t\n")
        assert junk is True

    def test_too_short_combined(self):
        """제목+설명 합산 정제 길이 < 15자 → 버림."""
        junk, reason = is_junk("짧다", "네")  # 총 3자
        assert junk is True
        assert "짧" in reason

    def test_exactly_14_chars_discarded(self):
        """경계값: 14자 → 버림."""
        # 14자짜리 순수 텍스트 (공백 없이)
        junk, reason = is_junk("가나다라마바사", "아자차카")  # 7+4=11? 재계산 필요
        # "가나다라마바사" = 7자, "아자차카" = 4자 → 11자 → 버림
        assert junk is True

    def test_phone_and_url_both_present(self):
        """전화번호 + URL 동시 포함 → 순수 광고 → 버림."""
        title = "두피 탈모 고민"
        desc = "저희 클리닉 010-1234-5678 바로 상담 https://example.com"
        junk, reason = is_junk(title, desc)
        assert junk is True
        assert "광고" in reason

    def test_representative_phone_and_url(self):
        """1588 대표번호 + URL → 버림."""
        junk, reason = is_junk("치료 문의", "1588-1234 http://clinic.co.kr 바로 예약")
        assert junk is True

    def test_two_urls_no_phone(self):
        """URL 2개 이상(전화 없이도) → 링크 도배 → 버림."""
        desc = "https://site1.com 추천 https://site2.com 여기도 추천"
        junk, reason = is_junk("추천합니다", desc)
        assert junk is True
        assert "URL" in reason

    def test_three_urls(self):
        """URL 3개 → 버림."""
        desc = "http://a.com http://b.com https://c.com"
        junk, reason = is_junk("정보 공유", desc)
        assert junk is True


# ── 남겨야 하는 케이스 (보수성 검증) ───────────────────────────────────

class TestShouldKeep:

    def test_normal_customer_question(self):
        """정상 고객 질문 → 남김."""
        title = "두피가 너무 가려운데 원인이 뭔가요"
        desc = "샴푸 바꾸고 나서부터 두피가 자꾸 간지럽고 각질이 생겨요. 어떻게 하면 좋을까요?"
        junk, reason = is_junk(title, desc)
        assert junk is False
        assert reason == ""

    def test_business_name_only_kept(self):
        """업체명·홍보수식어만 있어도 버리지 않음(찐 고객 섞임 가능성)."""
        title = "두피 전문 클리닉 ○○헤어 강남점"
        desc = "10년 경력 전문가가 직접 상담해 드립니다. 탈모 고민 있으신 분 환영합니다."
        junk, reason = is_junk(title, desc)
        assert junk is False

    def test_phone_only_no_url_kept(self):
        """전화번호만 있고 URL 없으면 → 남김(규칙 3 미충족)."""
        title = "두피 관련 문의"
        desc = "상담 원하시면 010-9876-5432 로 연락 주세요."
        junk, reason = is_junk(title, desc)
        assert junk is False

    def test_url_only_one_kept(self):
        """URL 1개만 있고 전화 없으면 → 남김(규칙 3·4 모두 미충족)."""
        title = "이 글 참고해보세요"
        desc = "https://naver.com/help 여기 보면 자세히 나와있어요. 저도 이걸로 해결했어요."
        junk, reason = is_junk(title, desc)
        assert junk is False

    def test_exactly_15_chars_kept(self):
        """경계값: 정제 길이 15자 → 남김."""
        # "가나다라마바사아자차카타파하a" = 15자
        title = "가나다라마바사"   # 7자
        desc = "아자차카타파하a"   # 8자 → 합 15자
        junk, reason = is_junk(title, desc)
        assert junk is False

    def test_real_worry_with_product_mention(self):
        """제품 언급이 있어도 고객 고민 내용이면 → 남김."""
        title = "○○ 샴푸 쓰고 나서 두피 트러블이 생겼어요"
        desc = "한 달째 쓰고 있는데 갑자기 두피가 빨개지고 가렵기 시작했어요. 알러지인가요?"
        junk, reason = is_junk(title, desc)
        assert junk is False

    def test_price_with_url_kept(self):
        """가격(1500원)+URL 이 있어도 찐 고객글이면 남김 — 4자리 숫자 전화 오인 방지 회귀."""
        title = "두피 가려움 샴푸 추천해주세요"
        desc = ("이 샴푸 1500원인데 https://smartstore.naver.com/x/products/1 "
                "에서 샀어요 두피에 좋을까요?")
        junk, reason = is_junk(title, desc)
        assert junk is False, f"가격+URL 찐고객글이 버려짐: {reason}"

    def test_year_number_kept(self):
        """연도(1999년) 같은 4자리 숫자를 전화로 오인하지 않음."""
        title = "2년째 두피 가려움 고민이에요"
        desc = "1999년생인데 작년부터 두피가 너무 가렵고 각질도 심해요. 병원 가야 할까요?"
        junk, reason = is_junk(title, desc)
        assert junk is False

    def test_real_ad_repnum_with_url_still_discarded(self):
        """진짜 광고(대표번호 1588-1234 형식 + URL)는 여전히 버림 — 필터가 무력화되지 않음."""
        junk, reason = is_junk(
            "탈모 상담", "상담전화 1588-1234 http://clinic.example.com 예약하세요")
        assert junk is True
