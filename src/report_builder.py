"""report_builder: snapshot_diff 결과 → 텔레그램 보고 텍스트 (저녁/아침). M10 T-M10.4.

⚠️ 비공개 채널(텔레그램 DM) 전용 — 키워드/제품(탭)명/분포 포함. 공개 issue 와 절대 공유 X (D-048).
즉시 보고(메타 전용)는 send_telegram_summary 가 post_summary.build_comment_from_cycle 로 별도 생성.
plain text (parse_mode 없음) — 마크다운 escape 불필요. 길이 초과는 notify.send_report 가 분할.
"""
from __future__ import annotations

from collections import Counter

from src.snapshot_diff import TabReport

# 분포 표기 순서 (노출 → 비노출/문제)
_DIST_ORDER = [
    "AB", "스마트블록", "인기글",
    "중복노출", "중복노출(AB)", "중복노출(스마트블록)", "중복노출(인기글)",
    "미노출", "누락", "삭제", "실패", "재검사필요",
]
_KIND_ICON = {"신규노출": "🟦", "오름": "🔺", "내림": "🔻", "누락": "⚠️", "삭제": "❌", "변화": "·"}


def _fmt_delta(prev: int, curr: int) -> str:
    d = curr - prev
    return f"{prev}→{curr} (0)" if d == 0 else f"{prev}→{curr} ({'+' if d > 0 else ''}{d})"


def _exposed_line(tr: TabReport) -> str:
    """상위노출 요약 줄. baseline 없으면 delta(0→N) 대신 현재값만 — 오독 방지(Codex #4)."""
    if tr.baseline_available:
        return f"상위노출 {_fmt_delta(tr.exposed_prev, tr.exposed_now)}"
    return f"상위노출 {tr.exposed_now}/{tr.total}"


def _dist_segment(tr: TabReport) -> str:
    parts: list[str] = []
    extras = [k for k in tr.distribution if k not in _DIST_ORDER]
    for k in _DIST_ORDER + extras:
        c, p = tr.distribution.get(k, 0), tr.prev_distribution.get(k, 0)
        if c or p:
            parts.append(f"{k} {p}→{c}" if tr.baseline_available else f"{k} {c}")
    return " · ".join(parts)


def _diff_detail(d) -> str:
    if d.kind in ("오름", "내림"):
        return f"{d.prev_rank}→{d.curr_rank}위"
    if d.kind == "신규노출":
        return d.curr_k
    if d.kind == "누락":
        return "노출 빠짐(회복 가능)"
    if d.kind == "삭제":
        return "글 사라짐"
    return f"{d.prev_k}→{d.curr_k}"


def _format_tab_block(tr: TabReport, *, show_diffs: bool = True) -> str:
    lines = [f"📦 {tr.tab} (키워드 {tr.total})"]
    lines.append(f"  {_exposed_line(tr)}")
    seg = _dist_segment(tr)
    if seg:
        lines.append("  " + seg)
    if tr.jisikin_now or tr.jisikin_prev:
        jis = _fmt_delta(tr.jisikin_prev, tr.jisikin_now) if tr.baseline_available else str(tr.jisikin_now)
        lines.append(f"  지식인 뜸 {jis}")
    if show_diffs and tr.baseline_available:
        for d in tr.diffs:
            lines.append(f"  {_KIND_ICON.get(d.kind, '·')} {d.keyword} {_diff_detail(d)}")
    return "\n".join(lines)


def _aggregate_kinds(reports: list[TabReport]) -> Counter:
    kinds: Counter = Counter()
    for tr in reports:
        for d in tr.diffs:
            kinds[d.kind] += 1
    return kinds


def _totals(reports: list[TabReport]) -> tuple[int, int, int]:
    """(총 키워드, 오늘 상위노출, 어제 상위노출)."""
    return (
        sum(tr.total for tr in reports),
        sum(tr.exposed_now for tr in reports),
        sum(tr.exposed_prev for tr in reports),
    )


def _change_line(kinds: Counter) -> str:
    return (
        f"변화: 🟦{kinds.get('신규노출', 0)} 🔺{kinds.get('오름', 0)} "
        f"🔻{kinds.get('내림', 0)} ⚠️{kinds.get('누락', 0)} ❌{kinds.get('삭제', 0)}"
    )


def _has_baseline(reports: list[TabReport]) -> bool:
    return any(tr.baseline_available for tr in reports)


def build_evening_report(reports: list[TabReport], kst: str, status_line: str = "✅정상") -> str:
    """저녁 최종본: 전체 + 제품별 분포 + 어제 대비 변화."""
    total, now, prev = _totals(reports)
    head = [f"📊 상노체크 · {kst} 저녁 마감 · {status_line}"]
    if _has_baseline(reports):
        head.append(f"전체 상위노출 {_fmt_delta(prev, now)}")
        head.append(_change_line(_aggregate_kinds(reports)))
    else:
        head.append(f"전체 상위노출 {now}/{total}")
        head.append("어제 비교 기준 없음(첫 운영/보관 경계) — 오늘 현황만")
    blocks = [_format_tab_block(tr) for tr in reports]
    return "\n".join(head) + "\n\n" + "\n\n".join(blocks) if blocks else "\n".join(head)


def build_morning_report(reports: list[TabReport], kst: str, status_line: str = "✅정상") -> str:
    """아침 요약: 조치 필요(누락·삭제) 상단 + 밤사이 변화 + 제품별 노출 카운트."""
    lines = [f"☀️ 상노체크 아침요약 · {kst} · {status_line}"]

    # 조치 필요(누락·삭제) 키워드 먼저
    urgent = [
        (tr.tab, d) for tr in reports for d in tr.diffs if d.kind in ("누락", "삭제")
    ]
    if urgent:
        lines.append("🚨 챙길 것")
        for tab, d in urgent:
            lines.append(f"  {_KIND_ICON[d.kind]} {d.keyword} ({tab}) {_diff_detail(d)}")
    else:
        lines.append("🚨 챙길 것: 없음")

    if _has_baseline(reports):
        lines.append(_change_line(_aggregate_kinds(reports)))
    else:
        lines.append("어제 비교 기준 없음 — 오늘 현황만")

    # 제품별 노출 카운트 (분포 상세는 저녁 최종본에)
    for tr in reports:
        lines.append(f"  📦 {tr.tab}: {_exposed_line(tr)}")
    return "\n".join(lines)
