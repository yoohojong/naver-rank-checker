"""report_html: 대시보드 context dict → 자체완결 HTML 문자열(일·주·월). 2026-07-13.

⚠️ 순수 함수(I/O 없음, 테스트 대상). 인라인 CSS 자체완결 = 외부 의존 0(표준 라이브러리만).
- daily_html(ctx) / weekly_html(ctx) / monthly_html(ctx) → 완결 HTML 문서 문자열.
- 라이트/다크 모두 대응(@media prefers-color-scheme + CSS 변수). max-width 560px 카드형.
- 숫자는 렌더 단계에서 반올림(정수/％). 데이터 없으면 '데이터 없음'/생략(추측 표기 안 함).

기존 텍스트 보고(report_builder/weekly_digest)는 그대로 두고, 이미지 대시보드용으로 순수 추가.
"""
from __future__ import annotations

_CSS = """
:root{
  --bg:#f4f5f8; --surf:#ffffff; --ink:#181b22; --mut:#6b7280; --line:#e6e8ee;
  --acc:#2563eb; --warn:#d97706; --crit:#dc2626; --rec:#0f9d58;
  --barbg:#eceef3; --bar:#2563eb; --track:#e6e8ee;
}
@media (prefers-color-scheme:dark){
  :root{
    --bg:#0f1116; --surf:#191c24; --ink:#e8eaf0; --mut:#98a1b2; --line:#2a2f3a;
    --acc:#4f8cff; --warn:#f0a020; --crit:#f05252; --rec:#22c98a;
    --barbg:#242833; --bar:#4f8cff; --track:#242833;
  }
}
*{box-sizing:border-box;}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Malgun Gothic","Apple SD Gothic Neo",Roboto,sans-serif;
  -webkit-font-smoothing:antialiased;line-height:1.5;font-size:15px;}
.wrap{max-width:560px;margin:0 auto;padding:16px 14px 40px;}
.head{margin:2px 0 14px;}
.head .eyebrow{font-size:12px;color:var(--mut);letter-spacing:.04em;}
.head h1{font-size:21px;margin:2px 0 4px;font-weight:750;}
.head .sub{font-size:13px;color:var(--mut);}
.head .ok{color:var(--rec);font-weight:650;}
.card{background:var(--surf);border:1px solid var(--line);border-radius:14px;
  padding:14px 15px;margin:0 0 12px;}
.card h2{font-size:14px;margin:0 0 11px;font-weight:700;letter-spacing:.01em;}
.card h2 .hint{font-weight:400;color:var(--mut);font-size:12px;margin-left:6px;}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;}
.kpi{background:var(--barbg);border-radius:11px;padding:11px 10px;text-align:center;}
.kpi .l{font-size:11px;color:var(--mut);margin-bottom:3px;}
.kpi .v{font-size:23px;font-weight:750;font-variant-numeric:tabular-nums;letter-spacing:-.01em;}
.kpi .s{font-size:11px;color:var(--mut);margin-top:2px;}
.kpi .up{color:var(--rec);} .kpi .down{color:var(--crit);}
.gauge{margin:2px 0 4px;}
.gauge .track{height:16px;background:var(--track);border-radius:9px;overflow:hidden;position:relative;}
.gauge .fill{height:100%;background:var(--acc);border-radius:9px;}
.gauge .goal{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--warn);}
.gauge .cap{display:flex;justify-content:space-between;font-size:12px;color:var(--mut);margin-top:6px;}
.gauge .cap b{color:var(--ink);font-variant-numeric:tabular-nums;}
.rows{display:flex;flex-direction:column;gap:8px;}
.brow{display:grid;grid-template-columns:88px 1fr 44px;align-items:center;gap:9px;font-size:13px;}
.brow .lab{color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.brow .num{text-align:right;font-variant-numeric:tabular-nums;font-weight:650;}
.bar{height:10px;background:var(--barbg);border-radius:6px;overflow:hidden;}
.bar > span{display:block;height:100%;background:var(--bar);border-radius:6px;}
.bar > span.warn{background:var(--warn);} .bar > span.crit{background:var(--crit);}
.bar > span.rec{background:var(--rec);}
.chips{display:flex;flex-wrap:wrap;gap:7px;}
.chip{background:var(--barbg);border-radius:9px;padding:7px 10px;font-size:12px;color:var(--mut);}
.chip b{color:var(--ink);font-size:15px;font-variant-numeric:tabular-nums;}
.chip.up b{color:var(--rec);} .chip.down b{color:var(--crit);} .chip.warn b{color:var(--warn);}
.reco{font-size:13px;color:var(--mut);text-align:center;padding:8px 4px 2px;font-variant-numeric:tabular-nums;}
.reco b{color:var(--ink);}
.tbl-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;}
table{border-collapse:collapse;width:100%;font-size:12.5px;min-width:320px;}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;
  font-variant-numeric:tabular-nums;white-space:nowrap;}
th:first-child,td:first-child{text-align:left;}
th{color:var(--mut);font-weight:600;font-size:11.5px;}
td.kw{max-width:150px;overflow:hidden;text-overflow:ellipsis;}
.note{font-size:12.5px;color:var(--mut);margin:4px 0 0;}
.diag{font-size:13.5px;line-height:1.6;}
.diag p{margin:0 0 7px;}
.diag .hyp{color:var(--warn);}
.empty{color:var(--mut);font-size:13px;padding:6px 0;}
.warncard{border:1px solid var(--warn);border-left:4px solid var(--warn);}
.warncard h2{color:var(--warn);}
.warncard ul{margin:2px 0 0;padding-left:20px;}
.warncard li{font-size:13px;line-height:1.55;margin:5px 0;color:var(--ink);}
.foot{text-align:center;font-size:11px;color:var(--mut);margin-top:6px;}
"""


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _bar(pct, cls: str = "") -> str:
    p = max(0, min(100, round(pct)))
    span_cls = f' class="{cls}"' if cls else ""
    return f'<div class="bar"><span{span_cls} style="width:{p}%"></span></div>'


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{_esc(title)}</title><style>{_CSS}</style></head>"
        f"<body><div class=\"wrap\">{body}"
        "<div class=\"foot\">카페외부 상위노출 대시보드 · 자동 생성</div>"
        "</div></body></html>"
    )


def _head(eyebrow: str, title: str, sub: str, status: str) -> str:
    return (
        "<div class=\"head\">"
        f"<div class=\"eyebrow\">{_esc(eyebrow)}</div>"
        f"<h1>{_esc(title)}</h1>"
        f"<div class=\"sub\">{_esc(sub)} · 프로그램 <span class=\"ok\">{_esc(status)}</span></div>"
        "</div>"
    )


def _card(title: str, inner: str, hint: str = "") -> str:
    h = f"<h2>{_esc(title)}<span class=\"hint\">{_esc(hint)}</span></h2>" if hint else f"<h2>{_esc(title)}</h2>"
    return f"<div class=\"card\">{h}{inner}</div>"


def _warn_card(ctx: dict) -> str:
    """자동 검증 경고(metric_guards) 카드. 경고 없으면 빈 문자열(미표시)."""
    warnings = ctx.get("warnings") or []
    if not warnings:
        return ""
    items = "".join(f"<li>{_esc(w)}</li>" for w in warnings)
    return (
        "<div class=\"card warncard\">"
        "<h2>⚠️ 자동 검증 경고<span class=\"hint\">숫자 신뢰성 점검</span></h2>"
        f"<ul>{items}</ul></div>"
    )


def _kpi(label: str, value, sub: str = "", cls: str = "") -> str:
    s = f"<div class=\"s {cls}\">{_esc(sub)}</div>" if sub else ""
    return f"<div class=\"kpi\"><div class=\"l\">{_esc(label)}</div><div class=\"v\">{_esc(value)}</div>{s}</div>"


def _barrows(items: list) -> str:
    """items = [(label, value_display, fill_pct, cls)]. fill_pct 정규화는 호출측 계산."""
    out = ["<div class=\"rows\">"]
    for lab, disp, pct, cls in items:
        out.append(
            f"<div class=\"brow\"><div class=\"lab\">{_esc(lab)}</div>"
            f"{_bar(pct, cls)}<div class=\"num\">{_esc(disp)}</div></div>"
        )
    out.append("</div>")
    return "".join(out)


def _delta_str(d) -> tuple:
    if d is None:
        return ("", "")
    if d > 0:
        return (f"▲{d}", "up")
    if d < 0:
        return (f"▼{-d}", "down")
    return ("―", "")


# ── 일간 ─────────────────────────────────────────────────────────────────────
def daily_html(ctx: dict) -> str:
    if ctx.get("empty"):
        return _page("카페외부 일간", _head("카페외부 · 일간", "데이터 없음", "", "확인 필요") +
                     "<div class=\"card\"><div class=\"empty\">백업 데이터가 없습니다.</div></div>")

    date_label = ctx["date_label"]
    body = [_head("카페외부 · 일간 대시보드", f"{date_label} 상위노출 리포트",
                  ctx["date_full"], ctx["status_line"])]
    body.append(_warn_card(ctx))  # 경고 있으면 맨 위 카드(없으면 빈 문자열)

    # KPI
    dstr, dcls = _delta_str(ctx.get("exposed_delta"))
    kpis = [
        _kpi("지금 상위노출", f"{ctx['exposed']}", f"전체 {ctx['total']}개 중"),
        _kpi("오늘 발행", f"{ctx['published_today']}",
             f"그중 {ctx['published_today_exposed']}개 노출" if ctx['published_today'] else "발행 없음"),
        _kpi("어제比 순변화", dstr or "―", "어제 대비" if ctx["has_base"] else "비교 기준 없음", dcls),
    ]
    body.append(_card("오늘 한눈에", f"<div class=\"kpis\">{''.join(kpis)}</div>"))

    # 탭별 KPI
    tab_rows = []
    tmax = max([t["total"] for t in ctx["tabs"]] + [1])
    for t in ctx["tabs"]:
        pct = t["exposed"] / t["total"] * 100 if t["total"] else 0
        d = (t["exposed"] - t["exposed_prev"]) if t["baseline"] else None
        ds, _ = _delta_str(d)
        disp = f"{t['exposed']}/{t['total']}" + (f" {ds}" if ds else "")
        tab_rows.append((t["name"], disp, pct, "rec" if pct >= ctx["goal_pct"] else ""))
    body.append(_card("제품별 상위노출", _barrows(tab_rows)))

    # 목표 게이지
    ach = ctx["achieve_pct"]
    goal = ctx["goal_pct"]
    w_note = ("코호트 기준(발행 배치 생존곡선)" if ctx["avg_dwell_source"] == "cohort"
              else "표본 부족 → 기본 3.0")
    gauge = (
        "<div class=\"gauge\"><div class=\"track\">"
        f"<div class=\"fill\" style=\"width:{min(100, ach)}%\"></div>"
        f"<div class=\"goal\" style=\"left:{min(100, goal)}%\"></div></div>"
        f"<div class=\"cap\"><span>현재 <b>{ach}%</b></span><span>목표 <b>{goal}%</b></span></div></div>"
        f"<div class=\"reco\">모델 기준 하루 필요 발행 <b>{ctx['need_publish']}개</b> "
        f"= 전체 {ctx['total']} × {goal}% ÷ 체류 {ctx['avg_dwell']}일</div>"
        f"<div class=\"note\">평균체류일(W) {ctx['avg_dwell']}일 · {w_note}</div>"
    )
    body.append(_card("목표 달성률", gauge, f"목표 {goal}%"))

    # 어제 대비 변화 + 정합식
    if ctx["has_base"]:
        ch = ctx["changes"]
        chips = [
            ("신규노출", ch["신규노출"], "up"),
            ("순위상승", ch["오름"], "up"),
            ("순위하락", ch["내림"], "down"),
            ("누락", ch["누락"], "warn"),
            ("삭제", ch["삭제"], "down"),
        ]
        chip_html = "".join(
            f"<div class=\"chip {c}\"><b>{v}</b> {_esc(lab)}</div>" for lab, v, c in chips
        )
        rc = ctx["reconcile"]
        eq = (f"어제 <b>{rc['prev']}</b> + 신규 <b>{rc['gained']}</b> − 이탈 <b>{rc['lost']}</b>"
              + (f" + 기타 <b>{rc['residual']:+d}</b>" if rc["residual"] else "")
              + f" = 오늘 <b>{rc['curr']}</b>")
        inner = f"<div class=\"chips\">{chip_html}</div><div class=\"reco\">{eq}</div>"
        body.append(_card("어제 → 오늘 변화", inner))
    else:
        body.append(_card("어제 → 오늘 변화",
                          "<div class=\"empty\">비교 기준(어제 백업) 없음 — 변화 생략</div>"))

    # 상위노출 추세 (최근 6일)
    tr = ctx["trend"]
    tmax2 = max([x["exposed"] for x in tr] + [1])
    tr_rows = [(x["date"], str(x["exposed"]), x["exposed"] / tmax2 * 100, "") for x in tr]
    body.append(_card("상위노출 추세", _barrows(tr_rows), "최근 6일"))

    # 날짜별 발행 → 상위노출
    fb = ctx["funnel_by_date"]
    rows = ["<div class=\"tbl-wrap\"><table><thead><tr><th>날짜</th><th>발행</th><th>노출</th><th>전환</th></tr></thead><tbody>"]
    for x in fb:
        rows.append(f"<tr><td>{_esc(x['date'])}</td><td>{x['published']}</td>"
                    f"<td>{x['exposed']}</td><td>{x['pct']}%</td></tr>")
    ftot = ctx["funnel_total"]
    rows.append(f"<tr><td><b>합계</b></td><td><b>{ftot['published']}</b></td>"
                f"<td><b>{ftot['exposed']}</b></td><td><b>{ftot['pct']}%</b></td></tr>")
    rows.append("</tbody></table></div>")
    body.append(_card("날짜별 발행 → 상위노출", "".join(rows), "최근 7일"))

    # 발행 후 며칠에 뜨나
    d2e = ctx["days_to_expose"]
    dmax = max(list(d2e.values()) + [1])
    d2e_rows = [(k, str(v), v / dmax * 100, "acc") for k, v in d2e.items()]
    body.append(_card("발행 후 며칠에 뜨나", _barrows(d2e_rows), "현재 노출 키워드 기준"))

    # 유형 분포 + 지식인
    td = ctx["type_dist"]
    type_chips = "".join(f"<div class=\"chip\"><b>{td[k]}</b> {k}</div>"
                         for k in ["AB", "스마트블록", "인기글"])
    extra = f"<div class=\"chip warn\"><b>{ctx['type_changes']}</b> 유형변경</div>" if ctx["type_changes"] else ""
    jis = f"<div class=\"chip\"><b>{ctx['jisikin']}</b> 지식인</div>"
    body.append(_card("노출 유형 분포", f"<div class=\"chips\">{type_chips}{extra}{jis}</div>"))

    return _page(f"카페외부 일간 {date_label}", "".join(body))


# ── 주간 ─────────────────────────────────────────────────────────────────────
def weekly_html(ctx: dict) -> str:
    if ctx.get("empty"):
        return _page("카페외부 주간", _head("카페외부 · 주간", "데이터 없음", "", "확인 필요") +
                     "<div class=\"card\"><div class=\"empty\">백업 데이터가 없습니다.</div></div>")

    body = [_head("카페외부 · 주간 총괄", f"{ctx['date_range']} 주간 리포트",
                  ctx["date_full"], ctx["status_line"])]
    body.append(_warn_card(ctx))  # 경고 있으면 맨 위 카드(없으면 빈 문자열)

    # KPI
    gain = ctx["week_gain"]
    gstr, gcls = _delta_str(gain)
    eff = ctx["efficiency_pct"]
    kpis = [
        _kpi("지금 상위노출", f"{ctx['exposed']}", f"전체 {ctx['total']}개 중"),
        _kpi("주 순증", gstr or ("―" if ctx["has_base"] else "―"),
             "주 시작 대비" if ctx["has_base"] else "비교 기준 없음", gcls),
        _kpi("발행 효율", f"{eff}%" if eff is not None else "데이터 없음",
             "순증 ÷ 발행"),
    ]
    body.append(_card("이번 주 한눈에", f"<div class=\"kpis\">{''.join(kpis)}</div>"))

    # 목표 게이지
    ach = ctx["achieve_pct"]
    goal = ctx["goal_pct"]
    gauge = (
        "<div class=\"gauge\"><div class=\"track\">"
        f"<div class=\"fill\" style=\"width:{min(100, ach)}%\"></div>"
        f"<div class=\"goal\" style=\"left:{min(100, goal)}%\"></div></div>"
        f"<div class=\"cap\"><span>현재 <b>{ach}%</b></span><span>목표 <b>{goal}%</b></span></div></div>"
        f"<div class=\"reco\">주 발행 <b>{ctx['week_published']}</b>개 · "
        f"평균체류일 <b>{ctx['avg_dwell']}</b>일</div>"
        f"<div class=\"note\">평균체류일(W) {ctx['avg_dwell']}일 · "
        + ("코호트 기준(발행 배치 생존곡선)" if ctx["avg_dwell_source"] == "cohort"
           else "표본 부족 → 기본 3.0")
        + "</div>"
    )
    body.append(_card("목표 대비", gauge, f"목표 {goal}%"))

    # 상위노출 추세
    tr = ctx["trend"]
    tmax = max([x["exposed"] for x in tr] + [1])
    tr_rows = [(x["date"], str(x["exposed"]), x["exposed"] / tmax * 100, "") for x in tr]
    body.append(_card("상위노출 추세(글 수명)", _barrows(tr_rows), "일별 노출 수"))

    # 카테고리별 달성률
    cats = ctx["categories"]
    cat_rows = [(c["cat"], f"{c['exposed']}/{c['total']} · {c['pct']}%", c["pct"],
                 "rec" if c["pct"] >= goal else "") for c in cats]
    body.append(_card("카테고리별 달성률", _barrows(cat_rows), "키워드 분류 기준"))

    # 이탈 Top (1위서 빠진 것)
    churn = ctx["churn_top"]
    if churn:
        rows = ["<div class=\"tbl-wrap\"><table><thead><tr><th>키워드</th><th>제품</th><th>상태</th></tr></thead><tbody>"]
        for c in churn:
            rows.append(f"<tr><td class=\"kw\">{_esc(c['keyword'])}</td>"
                        f"<td>{_esc(c['tab'])}</td><td>{_esc(c['kind'])}</td></tr>")
        rows.append("</tbody></table></div>")
        body.append(_card("이탈 Top", "".join(rows), "1위서 빠진 것"))
    else:
        body.append(_card("이탈 Top", "<div class=\"empty\">1위에서 빠진 키워드 없음</div>", "1위서 빠진 것"))

    return _page(f"카페외부 주간 {ctx['date_range']}", "".join(body))


# ── 월간 ─────────────────────────────────────────────────────────────────────
def monthly_html(ctx: dict) -> str:
    if ctx.get("empty"):
        return _page("카페외부 월간", _head("카페외부 · 월간", "데이터 없음", "", "확인 필요") +
                     "<div class=\"card\"><div class=\"empty\">백업 데이터가 없습니다.</div></div>")

    goal = ctx["goal_pct"]
    body = [_head("카페외부 · 월간 심층", f"{ctx['date_range']} 월간 리포트",
                  ctx["date_full"], ctx["status_line"])]
    body.append(_warn_card(ctx))  # 경고 있으면 맨 위 카드(없으면 빈 문자열)

    # KPI
    kpis = [
        _kpi("현재 상위노출", f"{ctx['exposed']}", f"전체 {ctx['total']}개 중"),
        _kpi("달성률", f"{ctx['achieve_pct']}%", f"목표 {goal}%"),
        _kpi("평균체류", f"{ctx['avg_dwell']}일",
             "코호트 기준" if ctx["avg_dwell_source"] == "cohort" else "기본값"),
    ]
    body.append(_card("이번 달 한눈에", f"<div class=\"kpis\">{''.join(kpis)}</div>"))

    # 주별 달성률 추세 + 발행효율
    weeks = ctx["weeks"]
    rows = ["<div class=\"tbl-wrap\"><table><thead><tr><th>주</th><th>노출</th><th>달성</th><th>발행</th><th>효율</th></tr></thead><tbody>"]
    for w in weeks:
        eff = f"{w['efficiency_pct']}%" if w["efficiency_pct"] is not None else "―"
        rows.append(f"<tr><td>{_esc(w['label'])}</td><td>{w['exposed']}/{w['total']}</td>"
                    f"<td>{w['pct']}%</td><td>{w['published']}</td><td>{eff}</td></tr>")
    rows.append("</tbody></table></div>")
    body.append(_card("주별 추세", "".join(rows), "달성률 · 발행효율"))

    # 카테고리별 성과
    cats = ctx["categories"]
    cat_rows = [(c["cat"], f"{c['exposed']}/{c['total']} · {c['pct']}%", c["pct"],
                 "rec" if c["pct"] >= goal else "") for c in cats]
    body.append(_card("카테고리별 성과", _barrows(cat_rows), "키워드 분류 기준"))

    # Best / Worst
    best = ctx["best_keywords"]
    worst = ctx["worst_keywords"]
    if best:
        rows = ["<div class=\"tbl-wrap\"><table><thead><tr><th>Best(유지)</th><th>유지일</th></tr></thead><tbody>"]
        for b in best:
            rows.append(f"<tr><td class=\"kw\">{_esc(b['keyword'])}</td>"
                        f"<td>{b['days']}/{b['window']}일</td></tr>")
        rows.append("</tbody></table></div>")
        body.append(_card("Best 키워드", "".join(rows), "기간 대부분 유지"))
    if worst:
        rows = ["<div class=\"tbl-wrap\"><table><thead><tr><th>Worst(반복이탈)</th><th>이탈횟수</th></tr></thead><tbody>"]
        for w in worst:
            rows.append(f"<tr><td class=\"kw\">{_esc(w['keyword'])}</td>"
                        f"<td>{w['drops']}회</td></tr>")
        rows.append("</tbody></table></div>")
        body.append(_card("Worst 키워드", "".join(rows), "노출→이탈 반복"))

    # 대량하락 이벤트
    events = ctx["mass_drops"]
    if events:
        chips = "".join(
            f"<div class=\"chip down\"><b>{e['date']}</b> {e['from']}→{e['to']} (-{e['drop']})</div>"
            for e in events
        )
        body.append(_card("대량하락 이벤트", f"<div class=\"chips\">{chips}</div>", "하루 노출 급감일"))
    else:
        body.append(_card("대량하락 이벤트", "<div class=\"empty\">기간 중 대량하락 없음</div>", "하루 노출 급감일"))

    # 다음달 필요발행 권고
    reco = (
        f"<div class=\"reco\">모델 기준 하루 <b>{ctx['need_publish_daily']}개</b> · "
        f"다음달(30일) <b>{ctx['need_publish_month']}개</b> 권고<br>"
        f"= 전체 {ctx['total']} × {goal}% ÷ 체류 {ctx['avg_dwell']}일</div>"
    )
    body.append(_card("다음달 필요 발행", reco))

    # 진단
    diag_html = ["<div class=\"diag\">"]
    for line in ctx["diagnosis"]:
        cls = " class=\"hyp\"" if str(line).startswith("가설:") else ""
        diag_html.append(f"<p{cls}>{_esc(line)}</p>")
    diag_html.append("</div>")
    body.append(_card("진단", "".join(diag_html)))

    # GA4 자리표시
    body.append(_card("신규 유입·매출 동행",
                      f"<div class=\"note\">{_esc(ctx['ga4_placeholder'])}</div>", "다음 과제"))

    return _page(f"카페외부 월간 {ctx['date_range']}", "".join(body))
