"""report_metrics 단위 테스트 (2026-07-13).

검증: 일·주·월 context 계산 정합(합계/노출/발행/퍼널/변화 정합식/카테고리/Best·Worst/대량하락).
합성 백업만 사용(외부 의존 0 — snapshot_diff = re 기반). 로컬 백업/gh 불필요.
"""
from src.report_metrics import daily_context, monthly_context, weekly_context


def _row(rownum, kw, area, l="", link=None, workdate="", kwclass="", ktype="", jisikin=""):
    r = {
        "_tab": "샴푸 카외",
        "_row": rownum,
        "키워드": kw,
        "노출영역": area,
        "노출여부(통합탭 순위)": l,
        "링크": link if link is not None else f"http://cafe.naver.com/a/{rownum}",
    }
    if workdate:
        r["작업일"] = workdate
    if kwclass:
        r["키워드 분류"] = kwclass
    if ktype:
        r["유형"] = ktype
    if jisikin:
        r["지식인탭"] = jisikin
    return r


def _bk(rows):
    return {"timestamp": "t", "run_id": "x", "tabs": {"샴푸 카외": rows}}


def _dataset():
    """3일치(07-08~07-10). 결정적 값으로 구성 — 어느 셀이 뭔지 주석 참고."""
    d0708 = _bk([
        _row(2, "비듬", "미노출", workdate="7/10", kwclass="3 증상", ktype="AB"),
        _row(3, "각질", "인기글", workdate="7/8", kwclass="4 대안", ktype="인기글", jisikin="O"),
        _row(4, "탈모", "미노출", workdate="7/10", kwclass="5 브랜드제품", ktype="스마트블록"),
        _row(5, "비듬샴푸", "AB", l="1", workdate="7/1", kwclass="3 증상", ktype="AB"),
    ])
    d0709 = _bk([
        _row(2, "비듬", "미노출", workdate="7/10", kwclass="3 증상", ktype="AB"),
        _row(3, "각질", "인기글", workdate="7/8", kwclass="4 대안", ktype="인기글", jisikin="O"),
        _row(4, "탈모", "미노출", workdate="7/10", kwclass="5 브랜드제품", ktype="스마트블록"),
        _row(5, "비듬샴푸", "AB", l="1", workdate="7/1", kwclass="3 증상", ktype="AB"),
    ])
    d0710 = _bk([
        _row(2, "비듬", "AB", workdate="7/10", kwclass="3 증상", ktype="AB"),          # 신규노출 + 당일
        _row(3, "각질", "인기글", workdate="7/8", kwclass="4 대안", ktype="인기글", jisikin="O"),
        _row(4, "탈모", "미노출", workdate="7/10", kwclass="5 브랜드제품", ktype="스마트블록"),
        _row(5, "비듬샴푸", "누락", workdate="7/1", kwclass="3 증상", ktype="AB"),        # 1위→누락(이탈)
    ])
    return {"2026-07-08": d0708, "2026-07-09": d0709, "2026-07-10": d0710}


# ── 일간 ─────────────────────────────────────────────────────────────────────
def test_daily_counts_and_publish():
    ctx = daily_context(_dataset())
    assert ctx["scope"] == "daily"
    assert ctx["date_label"] == "7/10"
    assert ctx["total"] == 4
    assert ctx["exposed"] == 2          # AB(비듬) + 인기글(각질)
    assert ctx["exposed_prev"] == 2     # 07-09: 인기글 + AB(비듬샴푸)
    assert ctx["exposed_delta"] == 0
    assert ctx["published_today"] == 2  # 비듬, 탈모 (작업일 7/10 & 링크)
    assert ctx["published_today_exposed"] == 1  # 비듬만 노출


def test_daily_changes_and_reconcile():
    ctx = daily_context(_dataset())
    assert ctx["changes"]["신규노출"] == 1
    assert ctx["changes"]["누락"] == 1
    rc = ctx["reconcile"]
    assert rc["prev"] == 2 and rc["gained"] == 1 and rc["lost"] == 1 and rc["curr"] == 2
    assert rc["residual"] == 0  # 정합식 어제+들어옴-나감 = 오늘


def test_daily_days_to_expose_and_types():
    ctx = daily_context(_dataset())
    d2e = ctx["days_to_expose"]
    assert d2e["당일"] == 1   # 비듬 wd 7/10
    assert d2e["2일"] == 1    # 각질 wd 7/8
    assert ctx["type_dist"]["AB"] == 2
    assert ctx["jisikin"] == 1
    assert len(ctx["trend"]) == 3
    assert ctx["avg_dwell_source"] == "default"  # 표본 부족 → 기본 3.0
    assert ctx["avg_dwell"] == 3.0


def test_daily_no_baseline_single_day():
    ctx = daily_context({"2026-07-10": _dataset()["2026-07-10"]})
    assert ctx["has_base"] is False
    assert ctx["exposed_delta"] is None
    assert ctx["exposed"] == 2


# ── 주간 ─────────────────────────────────────────────────────────────────────
def test_weekly_aggregate_and_churn():
    ctx = weekly_context(_dataset())
    assert ctx["scope"] == "weekly"
    assert ctx["date_range"] == "7/8~7/10"
    assert ctx["total"] == 4
    assert ctx["exposed"] == 2
    assert ctx["achieve_pct"] == 50
    # 비듬샴푸: 1위 → 누락 (이탈 Top)
    assert any(c["keyword"] == "비듬샴푸" for c in ctx["churn_top"])


def test_weekly_categories():
    ctx = weekly_context(_dataset())
    cats = {c["cat"]: c for c in ctx["categories"]}
    assert cats["3 증상"]["total"] == 2 and cats["3 증상"]["exposed"] == 1
    assert cats["4 대안"]["exposed"] == 1
    assert cats["5 브랜드제품"]["exposed"] == 0


# ── 월간 ─────────────────────────────────────────────────────────────────────
def test_monthly_weeks_best_worst():
    ctx = monthly_context(_dataset())
    assert ctx["scope"] == "monthly"
    assert len(ctx["weeks"]) == 1
    assert ctx["weeks"][0]["total"] == 4 and ctx["weeks"][0]["exposed"] == 2
    # 각질: 3일 내내 노출 → Best
    assert any(b["keyword"] == "각질" for b in ctx["best_keywords"])
    assert ctx["mass_drops"] == []  # 소규모 데이터 → 대량하락 없음
    assert ctx["need_publish_daily"] == 1  # round(4*0.75/3.0)
    assert ctx["need_publish_month"] == 30
    assert ctx["diagnosis"]  # 진단 문단 비어있지 않음


def test_empty_inputs():
    assert daily_context({}).get("empty") is True
    assert weekly_context({}).get("empty") is True
    assert monthly_context({}).get("empty") is True
