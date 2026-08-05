# -*- coding: utf-8 -*-
"""인기글 순위 = 화면 칸 단위 (2026-08-05 사장님 지적 fix 회귀 방지).

사고 경위:
    사장님이 '약산성샴푸' 를 직접 검색해 우리 글이 2등인 것을 보셨는데 시트엔 3등으로
    적혀 있었다. 원인 = 네이버가 같은 카페 글 여러 개를 화면 한 칸에 묶어 보여주는데
    (fds-ugc-after-article-list) 파서가 그 칸의 링크를 개수대로 세어 아래 글 순위를
    한 칸씩 밀어냈다. 2026-05-13 T-M14.3 에서 '같은 카페는 한 칸' 규칙을 없앤 것이 발단 —
    그때는 '시트 링크가 두 번째 글이면 못 찾는다' 를 고치려던 것이었고, 같은 목록이
    찾기와 세기를 겸하고 있어 세기까지 같이 부풀었다.

이 검사가 지키는 것:
    찾기 범위(칸 안 모든 글)는 넓게 두되, 순위 숫자는 사람이 화면에서 세는 칸과 같아야 한다.

픽스처 = 2026-08-05 실제 통합검색 응답에서 잘라낸 인기글 박스.
    화면 칸: 광고2 / 루이클럽(같은 카페 글 2개 한 칸) / 나트랑도깨비(우리 글) / 블로그 / 카페2
"""
from src.parser import (
    ExposureArea,
    _extract_popular_cards,
    _extract_popular_items,
    parse_search_result,
)

FIXTURE = "naver/popular_same_cafe_bundle.html"
OURS = "https://cafe.naver.com/zzop/4142803"
BUNDLED_FIRST = "https://cafe.naver.com/gloseems1/1284324"
BUNDLED_SECOND = "https://cafe.naver.com/gloseems1/1284056"


class TestPopularCardRank:
    def test_our_post_is_cafe_slot_2_not_3(self, load_fixture):
        """사장님이 화면에서 보신 2등이 그대로 나와야 한다 (결함 시 3)."""
        result = parse_search_result(load_fixture(FIXTURE), None, link_set={OURS})
        assert result.exposure_area == ExposureArea.POPULAR
        assert result.cafe_slot_rank == 2
        assert result.integrated_rank == 2

    def test_same_cafe_bundle_counts_as_one_slot(self, load_fixture):
        """같은 카페 글 2개 = 화면 한 칸 = 구좌 1칸."""
        result = parse_search_result(load_fixture(FIXTURE), None, link_set={BUNDLED_FIRST})
        assert result.cafe_slot_rank == 1

    def test_second_post_in_bundle_still_matches_same_slot(self, load_fixture):
        """칸에 딸려 붙은 두 번째 글도 찾을 수 있어야 한다(T-M14.3 취지 유지).

        찾기는 되면서, 순위는 그 칸의 번호(1)로 같아야 한다 — 별도 칸으로 세지 않는다.
        """
        result = parse_search_result(load_fixture(FIXTURE), None, link_set={BUNDLED_SECOND})
        assert result.matched_url is not None
        assert result.cafe_slot_rank == 1

    def test_cards_hold_bundle_together(self, load_fixture):
        """칸 나누기 자체 검증: 묶인 두 글이 같은 칸 안에 있어야 한다."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(load_fixture(FIXTURE), "lxml")
        box = soup.select_one(".desktop_mode.api_subject_bx, .fds-default-mode.api_subject_bx")
        cards = _extract_popular_cards(box)
        assert len(cards) >= 4
        bundle = [c for c in cards if any("gloseems1" in u for u in c)]
        assert len(bundle) == 1, "같은 카페 두 글이 두 칸으로 쪼개졌다"
        assert len(bundle[0]) == 2, "칸 안에 두 글이 다 들어 있어야 매치가 유지된다"

    def test_link_count_still_exceeds_card_count(self, load_fixture):
        """이 픽스처가 결함을 실제로 재현하는지 확인 — 링크 수 > 칸 수 여야 의미가 있다."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(load_fixture(FIXTURE), "lxml")
        box = soup.select_one(".desktop_mode.api_subject_bx, .fds-default-mode.api_subject_bx")
        assert len(_extract_popular_items(box)) > len(_extract_popular_cards(box))


class TestCardFallback:
    def test_unknown_structure_falls_back_to_link_units(self):
        """칸 구조를 못 읽는 HTML 이면 기존 링크 단위 방식으로 되돌아간다(정지 금지).

        네이버가 DOM 을 또 바꿔 칸을 못 읽게 돼도 순위가 빈칸이 되면 안 된다 —
        예전 방식으로라도 숫자가 나와야 한다.
        """
        from bs4 import BeautifulSoup

        from src.parser import RankResult, _parse_popular

        html = """
        <div class="desktop_mode api_subject_bx"><h2>패션·미용 인기글</h2>
          <ul>
            <li><a href="https://cafe.naver.com/aaa/111">글1</a></li>
            <li><a href="https://cafe.naver.com/bbb/222">글2</a></li>
          </ul>
        </div>"""
        soup = BeautifulSoup(html, "lxml")
        box = soup.select_one(".desktop_mode.api_subject_bx")
        assert _extract_popular_cards(box) == []  # fds-ugc 구조 없음 = 칸 못 읽음
        assert len(_extract_popular_items(box)) == 2  # 링크 단위로는 읽힘

        result = RankResult()
        assert _parse_popular(html, None, result, link_set={"https://cafe.naver.com/bbb/222"})
        assert result.cafe_slot_rank == 2  # 기존 방식 그대로 동작
