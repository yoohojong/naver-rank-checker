"""qa_context: 봇 '똑똑한 답'용 압축 데이터 요약 생성 (M12, D-059).

봇이 AI(Groq)에게 답을 직접 쓰게 하려면 데이터를 줘야 한다. 전체 시트(800행)를 보내지 않고
제품(탭)별 집계 + 카테고리별 키워드 예시(상한 cap개)만 보낸다 — 토큰·노출 최소화.
raw_* 우선 읽기(snapshot_diff.field_value)로 공식 모드에서도 진짜 값을 담는다.
"""
from __future__ import annotations

from src.snapshot_diff import field_value, k_base_of, rank_of
from src.transitions import EXPOSED_VALUES

_CAP = 12  # 카테고리별 키워드 예시 상한(토큰·노출·TPM 한도 여유)


def _kw(row: dict) -> str:
    return str(row.get("키워드", "") or "").strip()


def _is_exposed(kbase: str) -> bool:
    return kbase in EXPOSED_VALUES or kbase.startswith("중복노출")


def build_context(reports, curr_backup, *, cap: int = _CAP) -> dict:
    """reports(TabReport) + 현재 백업 → AI 에게 줄 압축 요약 dict."""
    tabs = (curr_backup.get("tabs") or {}) if curr_backup else {}
    products = []
    for tr in reports:
        rows = tabs.get(tr.tab, [])
        exposed = []
        for r in rows:
            kb = k_base_of(r)
            if _is_exposed(kb):
                exposed.append({
                    "키워드": _kw(r),
                    "노출영역": kb,
                    "통합순위": rank_of(r),
                    "지식인": bool(field_value(r, "지식인탭").strip()),
                })
        exposed.sort(key=lambda x: (x["통합순위"] is None, x["통합순위"] or 99999))
        deleted = [_kw(r) for r in rows if k_base_of(r) == "삭제"]
        missing = [_kw(r) for r in rows if k_base_of(r) == "누락"]
        ups = [{"키워드": d.keyword, "전→후": f"{d.prev_rank}→{d.curr_rank}"}
               for d in tr.diffs if d.kind == "오름"]
        downs = [{"키워드": d.keyword, "전→후": f"{d.prev_rank}→{d.curr_rank}"}
                 for d in tr.diffs if d.kind == "내림"]
        newly = [d.keyword for d in tr.diffs if d.kind == "신규노출"]
        products.append({
            "제품": tr.tab,
            "전체": tr.total,
            "상위노출": tr.exposed_now,
            "어제상위노출": tr.exposed_prev if tr.baseline_available else None,
            "분포": dict(tr.distribution),
            "지식인구좌": tr.jisikin_now,
            "유형분포": dict(tr.type_dist),
            "변화건수": {"신규": len(newly), "오름": len(ups), "내림": len(downs),
                      "누락": len(missing), "삭제": len(deleted)},
            "삭제키워드": deleted[:cap],
            "누락키워드": missing[:cap],
            "오른키워드": ups[:cap],
            "내린키워드": downs[:cap],
            "상위노출키워드": exposed[:cap],
            "예시상한": cap,
        })
    return {"어제비교가능": any(t.baseline_available for t in reports), "제품": products}
