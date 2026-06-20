"""telegram Q&A 봇 단위 테스트 (M11). 순수 함수 + 안전추출. 네트워크 0."""
import importlib.util
import os
from collections import Counter

from src import qa_formatter as qa
from src.snapshot_diff import RowDiff, TabReport


def _load_bot():
    p = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "telegram_qa_bot.py")
    spec = importlib.util.spec_from_file_location("telegram_qa_bot", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _tab():
    return TabReport(
        tab="샴푸 카외",
        distribution=Counter({"인기글": 1, "AB": 1, "삭제": 1}),
        prev_distribution=Counter({"미노출": 1, "AB": 2}),
        diffs=[
            RowDiff("샴푸 카외", "비듬샴푸", "미노출", "인기글", None, None, "신규노출", ""),
            RowDiff("샴푸 카외", "탈모샴푸 추천", "AB", "삭제", 2, None, "삭제", ""),
            RowDiff("샴푸 카외", "단백질샴푸", "AB", "AB", 8, 5, "오름", ""),
        ],
        jisikin_now=2,
        type_dist=Counter({"AB": 2, "인기글": 1}),
        type_changes=1,
        type_change_dirs=Counter({"AB→인기글": 1}),
    )


def test_classify_intent():
    assert qa.classify_intent("도움")[0] == "help"
    assert qa.classify_intent("누락된 거?")[0] == "missing"
    assert qa.classify_intent("삭제")[0] == "deleted"
    assert qa.classify_intent("순위 알려줘")[0] == "rank"
    assert qa.classify_intent("유형")[0] == "type"
    assert qa.classify_intent("지식인")[0] == "jisikin"
    assert qa.classify_intent("요약")[0] == "summary"
    assert qa.classify_intent("샴푸", ["샴푸 카외"]) == ("product", "샴푸 카외")
    assert qa.classify_intent("비듬샴푸")[0] == "keyword"
    assert qa.classify_intent("")[0] == "unknown"
    # 회귀: "키워드 X"는 제품명 부분일치보다 우선 (드라이런 버그)
    assert qa.classify_intent("키워드 비듬샴푸", ["샴푸 카외"]) == ("keyword", "비듬샴푸")
    assert qa.classify_intent("비듬샴푸", ["샴푸 카외"])[0] == "keyword"  # 제품 아님


def test_formatters():
    r = [_tab()]
    assert "없음" in qa.fmt_missing(r)  # 누락 0
    assert "탈모샴푸 추천" in qa.fmt_deleted(r) and "점검" in qa.fmt_deleted(r)
    assert "순위 상승 1개" in qa.fmt_rank(r)
    assert "샴푸 카외" in qa.fmt_product(r)
    assert "AB→인기글" in qa.fmt_type(r)
    assert "지식인" in qa.fmt_jisikin(r) and "2개" in qa.fmt_jisikin(r)
    assert "전체 3개" in qa.fmt_summary(r)
    assert "최근 점검" in qa.fmt_header("6/20 12:27", True)
    assert "비교 기준 없음" in qa.fmt_header("6/20 12:27", False)


def test_fmt_keyword():
    backup = {"tabs": {"샴푸 카외": [
        {"키워드": "비듬샴푸", "노출영역": "인기글 (6/20 01:00~)", "유형": "인기글",
         "지식인탭": "", "작업일": "6/19", "_tab": "샴푸 카외", "_row": 2},
    ]}}
    out = qa.fmt_keyword(backup, "비듬샴푸")
    assert "비듬샴푸" in out and "인기글" in out
    assert "못 찾" in qa.fmt_keyword(backup, "없는키워드")


def test_safe_extract_poison():
    b = _load_bot()
    assert b.safe_extract({}) is None  # update_id 없음
    assert b.safe_extract({"update_id": 5}) == (5, None, "")  # message 없음
    assert b.safe_extract({"update_id": 7, "message": {"from": {"id": 123}, "text": "hi"}}) == (7, "123", "hi")
    assert b.safe_extract({"update_id": 8, "message": {"text": "x"}}) == (8, None, "x")  # from 없음


def _curr_one():
    return {"tabs": {"샴푸 카외": [
        {"키워드": "비듬샴푸", "노출영역": "인기글", "유형": "인기글",
         "지식인탭": "", "작업일": "6/19", "_tab": "샴푸 카외", "_row": 2},
    ]}}


def test_answer_smart_compose_used_first(monkeypatch):
    """1순위: AI 답작성(compose) 성공 시 그 답을 그대로 사용."""
    b = _load_bot()
    monkeypatch.setattr(b, "load_data_once", lambda: ([_tab()], _curr_one(), "6/20 12:00", True))
    monkeypatch.setattr(b.llm_answer, "compose", lambda q, ctx: "샴푸 비듬샴푸가 1위예요.")
    out = b.answer("샴푸 1등 키워드 뭐야")
    assert "샴푸 비듬샴푸가 1위예요." in out and "최근 점검" in out  # header + AI 답


def test_answer_freetext_uses_llm(monkeypatch):
    """compose 실패(폴백) 시 키워드로 확신 못한 자유 질문 → LLM 분류 결과 사용."""
    b = _load_bot()
    monkeypatch.setattr(b, "load_data_once", lambda: ([_tab()], _curr_one(), "6/20 12:00", True))
    monkeypatch.setattr(b.llm_answer, "compose", lambda q, ctx: None)  # 스마트 실패 → 폴백
    monkeypatch.setattr(b.llm_intent, "classify", lambda text, tabs: ("missing", None))
    out = b.answer("요새 빠진 거 있으려나")
    assert "누락" in out and "없음" in out  # fmt_missing 경로 = LLM 의도 적용됨


def test_answer_llm_none_falls_back_to_keyword(monkeypatch):
    """LLM 실패(None) → 기존 키워드 결과 유지(비차단)."""
    b = _load_bot()
    monkeypatch.setattr(b, "load_data_once", lambda: ([_tab()], _curr_one(), "6/20 12:00", True))
    monkeypatch.setattr(b.llm_answer, "compose", lambda q, ctx: None)  # 스마트 실패 → 폴백
    monkeypatch.setattr(b.llm_intent, "classify", lambda text, tabs: None)
    out = b.answer("존재하지않는키워드xyz")
    assert "못 찾" in out  # keyword 폴백 검색 → graceful


def test_answer_explicit_command_skips_llm(monkeypatch):
    """확신 매칭(명령)은 LLM 호출 안 함 = 무료한도 절약."""
    b = _load_bot()
    monkeypatch.setattr(b, "load_data_once", lambda: ([_tab()], _curr_one(), "6/20 12:00", True))
    monkeypatch.setattr(b.llm_answer, "compose", lambda q, ctx: None)  # 스마트 실패 → 폴백

    def _boom(*a, **k):
        raise AssertionError("확신 매칭에서 LLM 호출되면 안 됨")

    monkeypatch.setattr(b.llm_intent, "classify", _boom)
    out = b.answer("누락")
    assert "누락" in out


# ── long-poll 루프 (M12 즉시 응답) ───────────────────────────────
def _msg(uid, sender, text):
    return {"update_id": uid, "message": {"from": {"id": sender}, "text": text}}


def test_handle_batch_owner_others_poison(monkeypatch):
    b = _load_bot()
    sent = []
    monkeypatch.setattr(b, "answer", lambda t: f"답:{t}")
    monkeypatch.setattr(b, "send_report", lambda m: sent.append(m))
    updates = [_msg(10, 999, "샴푸 어때"), _msg(11, 123, "남의것"), {"update_id": 12}]
    answered, max_uid = b._handle_batch(updates, "999")
    assert answered == 1 and max_uid == 12  # owner만 답, 비owner·poison은 ack만
    assert sent == ["답:샴푸 어때"]


def test_handle_batch_flood_cap(monkeypatch):
    b = _load_bot()
    sent = []
    monkeypatch.setattr(b, "answer", lambda t: "x")
    monkeypatch.setattr(b, "send_report", lambda m: sent.append(m))
    updates = [_msg(i, 999, "q") for i in range(10)]
    answered, max_uid = b._handle_batch(updates, "999")
    assert answered == b.MAX_ANSWERS_PER_BATCH and max_uid == 9


def test_load_data_ttl_refresh(monkeypatch):
    """4h 루프 중 데이터 캐시가 TTL 후 새로고침되는지(staleness 회귀 방지)."""
    b = _load_bot()
    calls = {"n": 0}

    def _runs():
        calls["n"] += 1
        return []  # curr=None 경로(가벼움), 캐시는 그래도 잡힘

    monkeypatch.setattr(b, "list_success_runs", _runs)
    monkeypatch.setenv("QA_DATA_TTL", "100")
    ticks = iter([0, 50, 200])  # load@0, hit@50(<100), reload@200(>100)
    monkeypatch.setattr(b.time, "monotonic", lambda: next(ticks))
    b.load_data_once()
    assert calls["n"] == 1
    b.load_data_once()
    assert calls["n"] == 1  # TTL 내 = 캐시 재사용
    b.load_data_once()
    assert calls["n"] == 2  # TTL 만료 = 재로드


def test_main_loop_no_hang_on_zero_budget(monkeypatch):
    b = _load_bot()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    monkeypatch.setenv("QA_LOOP_SECONDS", "0")
    monkeypatch.setattr(b, "_tg", lambda *a, **k: {})
    calls = {"n": 0}

    def _gu(**k):
        calls["n"] += 1
        return []

    monkeypatch.setattr(b, "get_updates", _gu)
    assert b.main() == 0
    assert calls["n"] == 0  # budget 0 → 루프 진입 0회(무한루프 아님)


def test_main_loop_processes_message_then_exits(monkeypatch):
    b = _load_bot()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    monkeypatch.setenv("QA_LOOP_SECONDS", "100")
    monkeypatch.setenv("QA_POLL_TIMEOUT", "0")
    monkeypatch.setattr(b, "_tg", lambda *a, **k: {})
    monkeypatch.setattr(b.time, "sleep", lambda s: None)
    ticks = iter([0, 1, 200, 200, 200])           # start=0, cond1=1(<100 진입), cond2=200(종료)
    monkeypatch.setattr(b.time, "monotonic", lambda: next(ticks))
    batches = iter([[_msg(5, 999, "샴푸")]])
    seen = []

    def _gu(offset=None, timeout=0):
        seen.append(offset)
        try:
            return next(batches)
        except StopIteration:
            return []

    monkeypatch.setattr(b, "get_updates", _gu)
    monkeypatch.setattr(b, "answer", lambda t: f"답:{t}")
    sent = []
    monkeypatch.setattr(b, "send_report", lambda m: sent.append(m))
    assert b.main() == 0
    assert sent == ["답:샴푸"]      # 즉시 답
    assert 6 in seen               # offset=uid+1 로 서버측 ack(재수신 방지)
