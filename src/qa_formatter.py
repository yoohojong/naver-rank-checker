"""qa_formatter: 텔레그램 Q&A 봇 응답 포매터 + 의도 분류 (순수 함수). M11.

snapshot_diff 결과(TabReport/RowDiff)에서 질문별로 골라 한글 답 생성 — 집계 신규 0.
모든 데이터 답 앞에 fmt_header(백업 시점 고지) 프리픽스: '라이브 아님, 최근 점검 기준'(critic C-3/5).
"""
from __future__ import annotations

from collections import Counter

from src.snapshot_diff import _norm_kw, k_base_of, rank_of

_HELP = (
    "🤖 상노 봇 — 이렇게 물어보세요:\n"
    "• 누락 — 검색에서 빠진 키워드\n"
    "• 삭제 — 글이 사라진 키워드(점검 필요)\n"
    "• 순위 — 순위 오른/내린 것\n"
    "• 제품 (또는 샴푸/바디워시/두드러기) — 제품별 현황\n"
    "• 유형 — AB·인기글·스마트블록 분포·변경\n"
    "• 지식인 — 지식iN 노출 수\n"
    "• 요약 — 전체 한눈에\n"
    "• 키워드 <단어> — 그 키워드 상태\n\n"
    "※ 답은 '실시간'이 아니라 최근 자동점검(6시간마다) 기준이에요."
)


def classify_intent(text, tab_names=None):
    """질문 텍스트 → (intent, arg). 결정적 키워드 매칭(자연어 후순위)."""
    t = (text or "").strip().lower()
    if not t:
        return ("unknown", None)
    if t in ("?", "/start", "/help") or any(k in t for k in ("도움", "help", "명령", "물어")):
        return ("help", None)
    if "누락" in t:
        return ("missing", None)
    if "삭제" in t or "사라" in t:
        return ("deleted", None)
    if "지식인" in t or "지식in" in t:
        return ("jisikin", None)
    if "유형" in t or "구좌" in t:
        return ("type", None)
    if any(k in t for k in ("순위", "랭킹", "몇위", "몇 위", "통합", "카페구좌")):
        return ("rank", None)
    if any(k in t for k in ("요약", "전체", "오늘", "상태", "현황")):
        return ("summary", None)
    # 명시 "키워드 X" → 키워드 조회 (제품명 부분일치보다 우선)
    q = text.strip()
    if q.lower().startswith("키워드"):
        kw = q[3:].strip()
        return ("keyword", kw) if kw else ("help", None)
    # 탭명 토큰 일치 → 제품 (부분일치 금지: '비듬샴푸'가 '샴푸'로 새지 않게)
    toks = t.split()
    for tab in tab_names or []:
        base = tab.replace("카외", "").strip().lower()
        if base and (t == base or base in toks):
            return ("product", tab)
    if any(k in t for k in ("제품", "탭", "분포")):
        return ("product", None)
    return ("keyword", q) if q else ("unknown", None)


def fmt_help():
    return _HELP


def fmt_header(curr_ts, baseline_available):
    h = f"📊 최근 점검({curr_ts}) 기준 · 실시간 아님"
    if not baseline_available:
        h += "\n(어제 비교 기준 없음)"
    return h


def _sum(reports, attr):
    return sum(getattr(t, attr) for t in reports)


def _collect(reports, kind):
    return [(t.tab, d) for t in reports for d in t.diffs if d.kind == kind]


def _list_block(title, rows, empty, limit=30):
    if not rows:
        return empty
    lines = [title.format(n=len(rows))]
    for tab, d in rows[:limit]:
        lines.append(f"  · {d.keyword} ({tab})")
    if len(rows) > limit:
        lines.append(f"  …외 {len(rows) - limit}개")
    return "\n".join(lines)


def fmt_missing(reports):
    return _list_block("누락(잠깐 빠짐, 보통 회복) {n}개:", _collect(reports, "누락"), "누락: 없음 ✅")


def fmt_deleted(reports):
    return _list_block("🚨 삭제(글 사라짐) {n}개 — 점검 필요:", _collect(reports, "삭제"), "삭제: 없음 ✅")


def fmt_rank(reports, arg=None):
    ups = _collect(reports, "오름")
    downs = _collect(reports, "내림")
    lines = [f"순위 상승 {len(ups)}개 · 하락 {len(downs)}개"]
    for tab, d in ups[:15]:
        lines.append(f"  🔺 {d.keyword} {d.prev_rank}→{d.curr_rank}위")
    for tab, d in downs[:15]:
        lines.append(f"  🔻 {d.keyword} {d.prev_rank}→{d.curr_rank}위")
    return "\n".join(lines)


def fmt_product(reports, tab_name=None):
    sel = [t for t in reports if (tab_name is None or t.tab == tab_name)]
    if not sel:
        return "해당 제품 없음"
    lines = []
    for t in sel:
        tail = ""
        if t.baseline_available:
            d = t.exposed_now - t.exposed_prev
            tail = f" (어제보다 {'+' if d > 0 else ''}{d})" if d else " (그대로)"
        lines.append(f"📦 {t.tab}: 전체 {t.total} · 상위노출 {t.exposed_now}{tail}")
    return "\n".join(lines)


def fmt_type(reports):
    td, dirs, chg = Counter(), Counter(), 0
    for t in reports:
        td.update(t.type_dist)
        dirs.update(t.type_change_dirs)
        chg += t.type_changes
    seg = " · ".join(f"{k} {td[k]}" for k in ["AB", "스마트블록", "인기글"] if td.get(k))
    lines = [f"유형(대표구좌): {seg}", f"유형 바뀐 키워드: {chg}개"]
    for d, n in dirs.most_common(5):
        lines.append(f"  · {d} {n}개")
    return "\n".join(lines)


def fmt_jisikin(reports):
    return f"지식인(지식iN)에 뜬 키워드: {_sum(reports, 'jisikin_now')}개"


def fmt_summary(reports):
    tot, now = _sum(reports, "total"), _sum(reports, "exposed_now")
    kc = Counter(d.kind for t in reports for d in t.diffs)
    return (
        f"전체 {tot}개 · 상위노출 {now}개\n"
        f"신규 {kc.get('신규노출', 0)} · 오름 {kc.get('오름', 0)} · 내림 {kc.get('내림', 0)} · "
        f"누락 {kc.get('누락', 0)} · 삭제 {kc.get('삭제', 0)}"
    )


def fmt_keyword(curr_backup, query):
    nq = _norm_kw(query)
    if not nq:
        return "키워드를 같이 적어주세요. 예: 키워드 비듬샴푸"
    hits = []
    for rows in (curr_backup.get("tabs") or {}).values():
        for r in rows:
            if nq in _norm_kw(r.get("키워드")):
                hits.append(r)
    if not hits:
        return f"'{query}' 키워드를 못 찾았어요. (도움 이라고 보내면 사용법)"
    if len(hits) > 1:
        names = ", ".join(str(r.get("키워드", "")) for r in hits[:8])
        return f"'{query}' 비슷한 키워드 {len(hits)}개: {names}\n정확한 이름으로 다시 물어봐 주세요."
    r = hits[0]
    return (
        f"[{r.get('키워드', '')}]\n"
        f"  노출영역: {r.get('노출영역', '') or '미노출'}\n"
        f"  통합순위: {rank_of(r) if rank_of(r) else '-'}\n"
        f"  유형: {r.get('유형', '') or '-'}\n"
        f"  지식인: {'O' if str(r.get('지식인탭', '') or '').strip() else '-'}\n"
        f"  작업일: {r.get('작업일', '') or '-'}\n"
        f"  (노출영역 = {k_base_of(r)})"
    )
