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


class TestSmartBlockSameFix:
    """스마트블록 파서도 같은 칸 단위로 바뀌었다 — 인기글만 검사하면 반쪽이다.

    실측 인기글 박스의 h2 만 스마트블록 이름으로 바꿔, 같은 DOM 구조가 스마트블록
    경로로 흘렀을 때도 묶음 칸이 1칸으로 세어지는지 본다.
    """

    def _as_smart_block(self, html: str) -> str:
        return html.replace("패션·미용 인기글", "이용자 두피케어").replace(
            "<h2>인기글</h2>", "<h2>이용자 두피케어</h2>"
        )

    def test_bundle_counts_as_one_slot_in_smart_block(self, load_fixture):
        html = self._as_smart_block(load_fixture(FIXTURE))
        result = parse_search_result(html, None, link_set={OURS})
        assert result.exposure_area == ExposureArea.SMART_BLOCK
        assert result.cafe_slot_rank == 2

    def test_bundled_second_post_matches_in_smart_block(self, load_fixture):
        html = self._as_smart_block(load_fixture(FIXTURE))
        result = parse_search_result(html, None, link_set={BUNDLED_SECOND})
        assert result.matched_url is not None
        assert result.cafe_slot_rank == 1


class TestOtherMatchPaths:
    """target_url 경로와 slug 화이트리스트 경로도 구조가 바뀌었다 — 같이 지킨다."""

    def test_target_url_path_uses_card_unit(self, load_fixture):
        result = parse_search_result(load_fixture(FIXTURE), OURS)
        assert result.cafe_slot_rank == 2
        assert result.integrated_rank == 2

    def test_slug_whitelist_path_uses_card_unit(self, load_fixture):
        result = parse_search_result(load_fixture(FIXTURE), None, cafe_slug_whitelist={"zzop"})
        assert result.cafe_slot_rank == 2


class TestStructureGuards:
    """칸을 '읽었다고 착각' 하는 두 갈래를 막는다 (2026-08-05 독립검증 지적).

    두 안전장치가 없으면:
      · 덮개 안 됨 → 노출된 글이 조용히 '미노출' 로 기록된다(시트 빨강·재작업).
      · 한 칸 = 여러 주인 → 칸을 잘못 읽은 채 순위를 매긴다.
    """

    def test_partial_container_rename_falls_back_not_unexposed(self, load_fixture):
        """바깥 목록의 fds-ugc 이름만 바뀌어도 글을 놓치지 않는다.

        네이버가 클래스 이름을 부분만 바꾸는 일은 이미 있었다
        (fds-ugc-single-intention-item-list 대 …-rra). 그때 안쪽 묶음만 칸으로
        잡히면 범위가 좁아져 우리 글이 사라진다 — 되돌려서라도 찾아내야 한다.
        """
        html = load_fixture(FIXTURE).replace("fds-ugc-single-intention-item-list", "xx-item-list")
        result = parse_search_result(html, None, link_set={OURS})
        assert result.exposure_area == ExposureArea.POPULAR, "노출된 글이 미노출로 기록됐다"
        assert result.cafe_slot_rank is not None

    def test_single_card_bundle_keeps_card_unit(self):
        """칸이 하나여도 같은 카페 묶음이면 1칸으로 센다 (개수 휴리스틱이면 여기서 되살아난다)."""
        from bs4 import BeautifulSoup

        from src.parser import _extract_popular_cards

        html = """
        <div class="desktop_mode api_subject_bx"><h2>인기글</h2>
          <div class="fds-ugc-single-intention-item-list">
            <div class="fds-ugc-item">
              <div class="fds-ugc-after-article-list">
                <a href="https://cafe.naver.com/mycafe/111">글1</a>
                <a href="https://cafe.naver.com/mycafe/222">글2</a>
              </div>
            </div>
          </div>
        </div>"""
        box = BeautifulSoup(html, "lxml").select_one(".api_subject_bx")
        cards = _extract_popular_cards(box)
        assert len(cards) == 1, "같은 카페 묶음이 여러 칸으로 쪼개졌다"
        assert len(cards[0]) == 2, "칸 안 두 글이 다 담겨야 매치가 유지된다"

    def test_two_owners_in_one_card_falls_back(self):
        """한 칸에 서로 다른 카페가 섞였다 = 칸을 잘못 읽은 것 → 되돌린다."""
        from bs4 import BeautifulSoup

        from src.parser import _extract_popular_cards

        html = """
        <div class="desktop_mode api_subject_bx"><h2>인기글</h2>
          <div class="fds-ugc-single-intention-item-list">
            <div class="fds-ugc-item">
              <a href="https://cafe.naver.com/aaa/111">글1</a>
              <a href="https://cafe.naver.com/bbb/222">글2</a>
            </div>
          </div>
        </div>"""
        box = BeautifulSoup(html, "lxml").select_one(".api_subject_bx")
        assert _extract_popular_cards(box) == []


class TestFallbackIsAlsoCorrect:
    """되돌리기가 '오답 생산기' 가 아님을 증명한다 (2026-08-05 사장님 지적).

    사장님: "알리면 다야? 문제를 해결해야지."
    화면 구조를 못 읽었을 때 옛 방식(링크 개수)으로 돌아가면, 되돌리기 자체가
    사장님이 겪은 그 오류를 그대로 만들어낸다. 그래서 되돌림 계산을
    '연속 같은 출처 = 한 칸' 으로 바꿨다 — 네이버 클래스 이름과 무관한 규칙이라
    화면 구조가 바뀌어도 답이 유지된다.
    """

    def _break_dom(self, html: str) -> str:
        """네이버가 클래스 이름을 전부 갈아엎은 상황을 만든다."""
        return html.replace("fds-ugc", "zzz-renamed")

    def test_answer_survives_dom_rename(self, load_fixture):
        """화면 구조를 못 읽어도 답은 2등 그대로여야 한다 (예전엔 3등이 나왔다)."""
        from bs4 import BeautifulSoup

        from src.parser import _extract_popular_cards

        html = self._break_dom(load_fixture(FIXTURE))
        box = BeautifulSoup(html, "lxml").select_one(
            ".desktop_mode.api_subject_bx, .fds-default-mode.api_subject_bx"
        )
        assert _extract_popular_cards(box) == [], "이 검사는 DOM 을 못 읽는 상황을 전제한다"

        result = parse_search_result(html, None, link_set={OURS})
        assert result.cafe_slot_rank == 2, "되돌림이 옛 오류(3등)를 되살렸다"

    def test_bundled_second_post_still_same_slot_after_rename(self, load_fixture):
        html = self._break_dom(load_fixture(FIXTURE))
        result = parse_search_result(html, None, link_set={BUNDLED_SECOND})
        assert result.cafe_slot_rank == 1

    def test_owner_runs_matches_dom_cards_on_real_page(self, load_fixture):
        """두 계산법이 실제 응답에서 같은 답을 낸다 — 서로를 검증할 수 있는 근거."""
        from bs4 import BeautifulSoup

        from src.parser import _extract_popular_cards, _owner_runs

        box = BeautifulSoup(load_fixture(FIXTURE), "lxml").select_one(
            ".desktop_mode.api_subject_bx, .fds-default-mode.api_subject_bx"
        )
        dom = _extract_popular_cards(box)
        runs = _owner_runs(_extract_popular_items(box))
        assert [sorted(c) for c in dom] == [sorted(c) for c in runs]


class TestOwnerJudgementIsConservative:
    """뭉치는 판단은 '확실할 때만' — 틀리면 없던 상위노출이 생긴다 (독립검증 H-2·M-2).

    뭉치면 순위가 당겨져 4위가 3위로 기록되고(상위노출 문턱 통과) 재작업 대상에서 빠진다.
    특히 전부 한 주인으로 뭉치면 모두 1등이 되어, 1등일 때 리셋되는 '실패 횟수' 가
    통째로 꺼진다. 그래서 못 뽑으면 안 뭉치는 쪽(순위가 밀리는 쪽)으로 기운다.
    """

    def test_unknown_cafe_url_shape_does_not_merge(self):
        """네이버가 카페 주소 형식을 또 바꿔도 전부 한 칸으로 뭉치지 않는다."""
        from src.parser import _owner_runs

        urls = [f"https://cafe.naver.com/f-e/cafes/{i}/articles/{i}" for i in (111, 222, 333)]
        assert len(_owner_runs(urls)) == 3, "주소 형식이 바뀌자 전 카페가 가짜 1등이 됐다"

    def test_non_cafe_sites_do_not_merge(self):
        """카페·블로그가 아닌 곳은 첫 경로 조각이 주인이 아니다."""
        from src.parser import _owner_runs

        urls = [
            "https://www.glowpick.com/products/181751",
            "https://www.glowpick.com/products/160715",
            "https://kin.naver.com/qna/detail/111",
            "https://kin.naver.com/qna/detail/222",
        ]
        assert len(_owner_runs(urls)) == 4

    def test_known_cafe_shapes_still_merge(self):
        """반대로, 확실히 아는 두 형식은 제대로 묶여야 한다(과잉 방어 금지)."""
        from src.parser import _owner_runs

        old = [
            "https://cafe.naver.com/gloseems1/1284324",
            "https://cafe.naver.com/gloseems1/1284056",
            "https://cafe.naver.com/zzop/4142803",
        ]
        new = [
            "https://cafe.naver.com/ca-fe/cafes/111/articles/1",
            "https://cafe.naver.com/ca-fe/cafes/111/articles/2",
            "https://cafe.naver.com/ca-fe/cafes/222/articles/3",
        ]
        assert len(_owner_runs(old)) == 2
        assert len(_owner_runs(new)) == 2

    def test_audit_and_parser_agree_on_owner(self):
        """감사와 파서가 같은 주인 판별을 쓴다 — 달라지면 헛된 어긋남이 쏟아진다."""
        import importlib.util
        from pathlib import Path

        from src.parser import slot_owner_key

        path = Path(__file__).resolve().parents[2] / "scripts" / "audit" / "구좌순위_화면대조.py"
        spec = importlib.util.spec_from_file_location("audit_slot", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for url in [
            "https://cafe.naver.com/zzop/4142803",
            "https://cafe.naver.com/ca-fe/cafes/111/articles/1",
            "https://cafe.naver.com/f-e/cafes/222/articles/2",
            "https://m.cafe.naver.com/zzop/4142803",
            "https://blog.naver.com/abc/224353549382",
        ]:
            assert mod._owner(url) == slot_owner_key(url), url


class TestSameCafeTwoSeparateCards:
    """같은 카페가 **이웃한 별도 칸 2개**를 차지하는 실물 (2026-08-05 '닭살피부바디워시').

    '연속 같은 출처 = 한 칸' 규칙이 틀리는 유일한 조건이고, 라이브에 실재한다.
    이때는 DOM 칸(파서)이 맞고 되돌림이 한 칸 적게 센다 — 알고 감수하는 위험이라
    그 사실 자체를 검사로 못박는다. 이 검사가 깨지면 되돌림의 위험 범위가 달라진 것이다.

    별도 칸이라는 독립 근거: 칸5·칸6 이 **각각 자기 카페 대문 링크**를 하나씩 갖는다
    (묶인 칸이면 대문이 하나여야 한다 — 실측 칸 50개에서 대문 2개인 칸은 0이었다).
    """

    FIXTURE2 = "naver/popular_same_cafe_two_cards.html"
    SECOND_OF_PAIR = "https://cafe.naver.com/com2usbaseball2015/1996063"

    def _box(self, load_fixture):
        from bs4 import BeautifulSoup

        return BeautifulSoup(load_fixture(self.FIXTURE2), "lxml").select_one(
            ".desktop_mode.api_subject_bx, .fds-default-mode.api_subject_bx"
        )

    def test_dom_sees_two_cards_owner_runs_merges_them(self, load_fixture):
        from src.parser import _extract_popular_cards, _owner_runs

        box = self._box(load_fixture)
        cards = _extract_popular_cards(box)
        runs = _owner_runs(_extract_popular_items(box))
        assert len(cards) == 7
        assert len(runs) == 6, "이 픽스처는 두 계산이 갈리는 실물이어야 의미가 있다"

    def test_parser_uses_dom_answer(self, load_fixture):
        """파서는 DOM 을 우선하므로 5(맞는 값)를 내야 한다."""
        result = parse_search_result(
            load_fixture(self.FIXTURE2), None, link_set={self.SECOND_OF_PAIR}
        )
        assert result.cafe_slot_rank == 5
        assert result.rank_from_dom_cards is True

    def test_each_card_has_its_own_source_home_link(self, load_fixture):
        """별도 칸이라는 독립 근거 — 두 칸이 각각 대문 링크를 갖는다."""
        import re

        box = self._box(load_fixture)
        root = box.select("div[class*='fds-ugc']")[0]
        kids = [
            ch
            for ch in root.find_all(recursive=False)
            if "sds-comps-divider" not in " ".join(ch.get("class", []))
        ]
        homes = [
            {
                a["href"].split("?")[0]
                for a in ch.find_all("a", href=True)
                if re.match(r"^https://(cafe|blog)\.naver\.com/[^/]+/?$", a["href"].split("?")[0])
            }
            for ch in kids
        ]
        assert all(len(h) <= 1 for h in homes), "한 칸에 대문이 둘이면 칸 경계를 잘못 읽은 것"
        pair = [h for h in homes if "https://cafe.naver.com/com2usbaseball2015" in h]
        assert len(pair) == 2, "같은 카페가 대문을 각각 가진 별도 두 칸이어야 한다"


class TestUnknownOwnerIsNotDisagreement:
    """'주인을 모른다' 와 '주인이 다르다' 는 다르다 (독립검증 H-2).

    모르는 형식 하나 때문에 박스 전체가 되돌림으로 떨어지면, 거기에 위 '이웃 별도 칸'
    이 겹쳤을 때 화면 4등이 3등으로 기록된다 — 상위노출 문턱을 넘는 방향이다.
    """

    def test_clip_and_in_naver_shapes_are_recognised(self):
        from src.parser import slot_owner_key

        assert slot_owner_key("https://m.blog.naver.com/l971031/clip/1") == slot_owner_key(
            "https://m.blog.naver.com/l971031/clip/2"
        )
        assert slot_owner_key("https://in.naver.com/abc/contents/internal/1") == slot_owner_key(
            "https://in.naver.com/abc/contents/internal/2"
        )

    def test_unknown_shapes_do_not_trip_the_guard(self):
        """주인을 모르는 링크 둘이 한 칸에 있어도 되돌림을 부르지 않는다."""
        from bs4 import BeautifulSoup

        from src.parser import _extract_popular_cards

        html = """
        <div class="desktop_mode api_subject_bx"><h2>인기글</h2>
          <div class="fds-ugc-single-intention-item-list">
            <div class="fds-ugc-item">
              <a href="https://www.glowpick.com/products/111">가</a>
              <a href="https://www.glowpick.com/products/222">나</a>
            </div>
            <div class="fds-ugc-item"><a href="https://cafe.naver.com/aaa/333">다</a></div>
          </div>
        </div>"""
        box = BeautifulSoup(html, "lxml").select_one(".api_subject_bx")
        cards = _extract_popular_cards(box)
        assert cards != [], "주인을 '모른다' 는 것을 '다르다' 로 읽어 되돌림이 발동했다"
        assert len(cards) == 2

    def test_two_known_owners_in_one_card_still_trips_the_guard(self):
        """반대로 확실히 아는 주인이 둘이면 여전히 되돌린다(안전장치가 죽으면 안 된다)."""
        from bs4 import BeautifulSoup

        from src.parser import _extract_popular_cards

        html = """
        <div class="desktop_mode api_subject_bx"><h2>인기글</h2>
          <div class="fds-ugc-single-intention-item-list">
            <div class="fds-ugc-item">
              <a href="https://cafe.naver.com/aaa/111">가</a>
              <a href="https://cafe.naver.com/bbb/222">나</a>
            </div>
          </div>
        </div>"""
        box = BeautifulSoup(html, "lxml").select_one(".api_subject_bx")
        assert _extract_popular_cards(box) == []


class TestJsonFallbackIsMarked:
    """JSON 대체 경로는 화면 칸으로 센 값이 아니다 — 감사가 건너뛰면 안 된다 (독립검증 H-1).

    이 경로는 아직 링크 개수로 세므로 사장님이 겪은 그 오류가 남아 있다.
    표시가 없으면 감사의 'AB 는 대상 아님' 규칙에 걸려 조용히 빠진다.
    """

    def test_json_fallback_marks_rank_as_not_from_dom(self):
        import json

        from src.parser import parse_search_result

        payload = {
            "items": [
                {"url": "https://cafe.naver.com/aaa/1"},
                {"url": "https://cafe.naver.com/aaa/2"},
                {"url": "https://cafe.naver.com/bbb/3"},
            ]
        }
        # 실제 형식: entry.bootstrap(document.getElementById("fdr-…"), {…JSON…});
        html = (
            "<html><body><div>" + "x" * 600 + "</div>"
            '<script>entry.bootstrap(document.getElementById("fdr-1"), '
            + json.dumps(payload)
            + ");</script></body></html>"
        )
        result = parse_search_result(html, None, link_set={"https://cafe.naver.com/bbb/3"})
        assert result.cafe_slot_rank is not None, "JSON 경로가 안 탔다 — 이 검사가 무의미해진다"
        assert result.rank_from_dom_cards is False, "JSON 경로 값이 DOM 칸으로 센 것처럼 표시됐다"

    def test_json_fallback_still_counts_by_link(self):
        """아직 링크 개수로 센다는 사실 자체를 기록해 둔다 — 고쳐지면 이 검사가 알려준다.

        같은 카페 글 2건 + 다른 카페 1건에서 화면 정답은 M=2 인데 JSON 경로는 3을 낸다.
        지금은 표시(rank_from_dom_cards=False)로 감사가 잡게 하고, 근본 수정은 별도 과제.
        """
        import json

        from src.parser import parse_search_result

        payload = {
            "items": [
                {"url": "https://cafe.naver.com/aaa/1"},
                {"url": "https://cafe.naver.com/aaa/2"},
                {"url": "https://cafe.naver.com/bbb/3"},
            ]
        }
        html = (
            "<html><body><div>" + "x" * 600 + "</div>"
            '<script>entry.bootstrap(document.getElementById("fdr-1"), '
            + json.dumps(payload)
            + ");</script></body></html>"
        )
        result = parse_search_result(html, None, link_set={"https://cafe.naver.com/bbb/3"})
        assert result.cafe_slot_rank == 3  # 화면 칸 기준 정답은 2 — 알려진 미해결 경로
        assert result.rank_from_dom_cards is False


class TestRankSignalsAreVisible:
    """순위가 '평소와 다르게' 돈 횟수를 사이클 요약이 실어 나른다 (독립검증 M-2).

    이 사고의 원인 진단이 "3개월간 틀렸다는 신호가 없었다" 였다. 신호를 만들어 놓고
    보이는 곳에 안 달면 같은 일이 되풀이된다.
    """

    def test_fallback_and_mismatch_are_counted(self, load_fixture):
        from src.parser import rank_signals, reset_rank_signals

        reset_rank_signals()
        assert rank_signals == {"fallback_boxes": 0, "mismatch_boxes": 0}

        # DOM 을 못 읽게 만든 페이지 → fallback 카운트
        broken = load_fixture(FIXTURE).replace("fds-ugc", "zzz-renamed")
        parse_search_result(broken, None, link_set={OURS})
        assert rank_signals["fallback_boxes"] >= 1

        # 두 계산이 갈리는 실측 페이지 → mismatch 카운트
        reset_rank_signals()
        parse_search_result(
            load_fixture("naver/popular_same_cafe_two_cards.html"),
            None,
            link_set={"https://cafe.naver.com/com2usbaseball2015/1996063"},
        )
        assert rank_signals["mismatch_boxes"] >= 1

    def test_reset_clears_counts(self):
        from src.parser import rank_signals, reset_rank_signals

        rank_signals["fallback_boxes"] = 7
        reset_rank_signals()
        assert rank_signals["fallback_boxes"] == 0

    def test_cycle_summary_carries_the_signals(self):
        """main.py 가 요약에 실제로 싣는지 — 배선이 끊기면 신호가 다시 안 보이게 된다."""
        import inspect

        from src import main as main_module

        src = inspect.getsource(main_module)
        assert 'summary["rank_fallback_boxes"]' in src
        assert 'summary["rank_mismatch_boxes"]' in src
        assert "reset_rank_signals()" in src


class TestSplitBundleIsDetectable:
    """묶음이 쪼개진 것(원래 사고와 같은 모양)과 이웃 별도 칸을 구분한다 (독립검증 M-1).

    두 경우 모두 두 계산의 차이가 1이라, 차이만 보면 원래 사고의 재발이 조용히 통과한다.
    '대문 링크 없는 칸' 이 그 둘을 가르는 지문이다 — 화면 한 칸은 자기 출처 대문을 갖는데,
    묶여 있던 글이 쪼개져 나오면 대문 없이 글만 남는다.
    """

    def _audit_module(self):
        import importlib.util
        from pathlib import Path

        path = Path(__file__).resolve().parents[2] / "scripts" / "audit" / "구좌순위_화면대조.py"
        spec = importlib.util.spec_from_file_location("audit_slot_orphan", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _box(self, cards):
        from bs4 import BeautifulSoup

        inner = "".join(f'<div class="fds-ugc-item">{c}</div>' for c in cards)
        html = (
            '<div class="desktop_mode api_subject_bx"><h2>인기글</h2>'
            f'<div class="fds-ugc-single-intention-item-list">{inner}</div></div>'
        )
        return BeautifulSoup(html, "html.parser").select_one(".api_subject_bx")

    HOME = '<a href="https://cafe.naver.com/{s}">대문</a>'
    POST = '<a href="https://cafe.naver.com/{s}/{n}">글</a>'

    def _card(self, slug, nums, with_home=True):
        parts = [self.HOME.format(s=slug)] if with_home else []
        parts += [self.POST.format(s=slug, n=n) for n in nums]
        return "".join(parts)

    def test_intact_bundle_has_no_orphan(self):
        mod = self._audit_module()
        box = self._box([self._card("aaa", [1, 2]), self._card("bbb", [3])])
        assert mod._has_orphan_card(box) is False

    def test_split_bundle_is_flagged(self):
        """원래 사고와 같은 모양 — 반드시 잡혀야 한다."""
        mod = self._audit_module()
        box = self._box(
            [self._card("aaa", [1]), self._card("aaa", [2], with_home=False), self._card("bbb", [3])]
        )
        assert mod._has_orphan_card(box) is True

    def test_neighbouring_separate_cards_are_not_flagged(self):
        """같은 카페 이웃 별도 칸 — 정상이므로 잡히면 안 된다(헛경보)."""
        mod = self._audit_module()
        box = self._box([self._card("aaa", [1]), self._card("aaa", [2]), self._card("bbb", [3])])
        assert mod._has_orphan_card(box) is False

    def test_real_fixture_has_no_orphan(self, load_fixture):
        """실측 반례(닭살피부바디워시)는 정상이므로 지문이 안 나와야 한다."""
        from bs4 import BeautifulSoup

        mod = self._audit_module()
        box = BeautifulSoup(
            load_fixture("naver/popular_same_cafe_two_cards.html"), "html.parser"
        ).select_one(".desktop_mode.api_subject_bx, .fds-default-mode.api_subject_bx")
        assert mod._has_orphan_card(box) is False


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
