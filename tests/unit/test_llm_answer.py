"""llm_answer + qa_context 단위 테스트 (M12 D-059). 네트워크 0(groq_chat mock)."""
import json
from collections import Counter
from unittest import mock

from src import llm_answer, qa_context
from src.snapshot_diff import RowDiff, TabReport


def _tab():
    return TabReport(
        tab="샴푸 카외",
        distribution=Counter({"AB": 2, "인기글": 1, "삭제": 1, "미노출": 1}),
        prev_distribution=Counter({"AB": 1}),
        diffs=[
            RowDiff("샴푸 카외", "비듬샴푸", "미노출", "AB", None, 3, "신규노출", ""),
            RowDiff("샴푸 카외", "탈모샴푸", "AB", "삭제", 2, None, "삭제", ""),
            RowDiff("샴푸 카외", "단백질샴푸", "AB", "AB", 8, 5, "오름", ""),
        ],
        jisikin_now=2,
        type_dist=Counter({"AB": 2, "인기글": 1}),
    )


def _curr():
    return {"tabs": {"샴푸 카외": [
        {"키워드": "비듬샴푸", "raw_노출영역": "AB (6/1 00:00~)", "raw_통합순위": "3", "raw_지식인탭": "O"},
        {"키워드": "탈모샴푸", "raw_노출영역": "삭제 (6/1 00:00~)", "raw_지식인탭": ""},
        {"키워드": "단백질샴푸", "raw_노출영역": "AB (6/1 00:00~)", "raw_통합순위": "5", "raw_지식인탭": ""},
    ]}}


# ── qa_context ───────────────────────────────────────────────────
def test_build_context_structure_and_counts():
    ctx = qa_context.build_context([_tab()], _curr())
    assert ctx["어제비교가능"] is True
    p = ctx["제품"][0]
    assert p["제품"] == "샴푸 카외"
    assert p["지식인구좌"] == 2
    assert p["변화건수"]["삭제"] == 1 and p["변화건수"]["오름"] == 1
    assert "탈모샴푸" in p["삭제키워드"]
    # 상위노출 키워드는 순위 오름차순(1위부터)
    ranks = [k["통합순위"] for k in p["상위노출키워드"] if k["통합순위"]]
    assert ranks == sorted(ranks)


def test_build_context_caps_keyword_lists():
    rows = [{"키워드": f"kw{i}", "raw_노출영역": "삭제 (6/1 00:00~)"} for i in range(50)]
    tr = TabReport(tab="샴푸 카외", distribution=Counter({"삭제": 50}), prev_distribution=Counter())
    ctx = qa_context.build_context([tr], {"tabs": {"샴푸 카외": rows}}, cap=10)
    assert len(ctx["제품"][0]["삭제키워드"]) == 10  # 상한 적용(토큰·노출 제한)


def test_build_context_no_raw_full_rows_leaked():
    # 컨텍스트에 링크/숨김컬럼 등 원본 행 통째가 들어가지 않음(요약만)
    ctx = qa_context.build_context([_tab()], _curr())
    s = json.dumps(ctx, ensure_ascii=False)
    assert "raw_노출영역" not in s and "링크" not in s


# ── llm_answer ───────────────────────────────────────────────────
def test_compose_returns_ai_text():
    with mock.patch("src.llm_intent.groq_chat", return_value="샴푸는 비듬샴푸가 3위로 가장 좋아요."):
        out = llm_answer.compose("샴푸 1등 뭐야", {"제품": []})
    assert out == "샴푸는 비듬샴푸가 3위로 가장 좋아요."


def test_compose_none_on_failure():
    with mock.patch("src.llm_intent.groq_chat", return_value=None):
        assert llm_answer.compose("아무거나", {"제품": []}) is None


def test_compose_messages_include_question_and_data():
    cap = {}

    def _fake(messages, **kw):
        cap["m"] = messages
        return "ok"

    with mock.patch("src.llm_intent.groq_chat", side_effect=_fake):
        llm_answer.compose("샴푸 어때", {"제품": [{"제품": "샴푸 카외", "상위노출": 2}]})
    blob = json.dumps(cap["m"], ensure_ascii=False)
    assert "샴푸 어때" in blob and "상위노출" in blob


def test_compose_includes_history():
    cap = {}

    def _fake(messages, **kw):
        cap["m"] = messages
        return "ok"

    with mock.patch("src.llm_intent.groq_chat", side_effect=_fake):
        llm_answer.compose("그럼 샴푸는?", {"제품": []}, history=[("지식인 몇개?", "352개")])
    blob = json.dumps(cap["m"], ensure_ascii=False)
    assert "지식인 몇개?" in blob and "352개" in blob and "그럼 샴푸는?" in blob
