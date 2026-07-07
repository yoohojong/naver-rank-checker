"""exposure_history: 아카이브(상위노출_이력) 기반 일별 개수 추세 + 발행분 코호트 변화 (텔레그램 보고용).

사장님 2026-07-07: 매일 개수만 찍혀 '흐름'이 안 보여 답답 →
  (1) 지난 며칠 상위노출 개수 추세(daily_trend)
  (2) 발행한 날 글이 며칠 뒤 몇 개 떠 있나(cohort_evolution)
데이터 = 상위노출_이력 탭(archive.py 가 매 cron 적재). SheetsClient.spreadsheet 로 읽는다.
발행일(작업일)은 아카이브에 없어 curr 백업(행 dict의 '작업일')에서 가져와 조인한다.
⚠️ 비차단: 탭/키 없거나 실패 시 빈 결과 → 해당 섹션만 생략(핵심 보고 유지).
"""
from __future__ import annotations

from collections import OrderedDict, defaultdict

from src.transitions import EXPOSED_VALUES

ARCHIVE_TAB = "상위노출_이력"


def read_archive_rows(client) -> list:
    """상위노출_이력 → [(날짜ISO, 탭, 키워드, 노출영역), ...]. 탭 없음/실패 시 []. (비차단)"""
    try:
        ws = client.spreadsheet.worksheet(ARCHIVE_TAB)
        vals = ws.get_all_values()
    except Exception:
        return []
    if len(vals) < 2:
        return []
    h = vals[0]
    try:
        di, ti, ki, ai = h.index("날짜"), h.index("탭"), h.index("키워드"), h.index("노출영역")
    except ValueError:
        return []
    out = []
    for r in vals[1:]:
        if di < len(r) and str(r[di]).strip():
            out.append((
                r[di],
                r[ti] if ti < len(r) else "",
                r[ki] if ki < len(r) else "",
                r[ai] if ai < len(r) else "",
            ))
    return out


def daily_trend(rows: list, days: int = 6) -> "OrderedDict":
    """행 → 최근 days개 날짜별 {탭: 상위노출수} + 합계. 날짜 오름차순(왼쪽 과거 → 오른쪽 오늘)."""
    by: dict = defaultdict(lambda: defaultdict(int))
    for d, t, kw, a in rows:
        if a in EXPOSED_VALUES:
            by[d][t] += 1
    dates = sorted(by)[-days:]
    out: "OrderedDict" = OrderedDict()
    for d in dates:
        per = dict(by[d])
        out[d] = {"합계": sum(per.values()), **per}
    return out


def _md_to_iso(md: str, year: int):
    try:
        m, d = str(md).strip().split("/")[:2]
        return f"{year}-{int(m):02d}-{int(d):02d}"
    except Exception:
        return None


def cohort_evolution(rows: list, curr_backup: dict, n_cohorts: int = 3, max_steps: int = 4) -> list:
    """발행일(작업일)별 코호트가 며칠 뒤 몇 개 상위노출인지.

    rows = read_archive_rows 결과(키워드 포함). curr_backup = 오늘 백업(행 dict에 '작업일').
    반환: [(발행일'M/D', 발행수, [('당일', n), ('1일뒤', n), ...]), ...] 최신 발행일 먼저.
    아카이브에 없는 발행일/데이터 없으면 [].
    """
    exp_by_date: dict = defaultdict(set)
    all_dates: set = set()
    for d, t, kw, a in rows:
        all_dates.add(d)
        if a in EXPOSED_VALUES and kw:
            exp_by_date[d].add(kw)
    if not all_dates:
        return []
    year = int(sorted(all_dates)[-1].split("-")[0])
    archive_dates = sorted(all_dates)

    # 발행일(작업일) → 키워드 집합 (curr 백업에서)
    pub: dict = defaultdict(set)
    for tab_rows in (curr_backup.get("tabs") or {}).values():
        for r in tab_rows or []:
            wd = str(r.get("작업일", "") or "").strip()
            kw = str(r.get("키워드", "") or "").strip()
            if wd and kw:
                pub[wd].add(kw)

    # 아카이브에 실제 존재하는 발행일만, 최신 n개
    cand = []
    for md, kws in pub.items():
        iso = _md_to_iso(md, year)
        if iso and iso in all_dates:
            cand.append((iso, md, kws))
    cand.sort(reverse=True)

    result = []
    for iso, md, kws in cand[:n_cohorts]:
        after = [d for d in archive_dates if d >= iso][:max_steps]
        steps = []
        for i, d in enumerate(after):
            label = "당일" if i == 0 else f"{i}일뒤"
            steps.append((label, len(kws & exp_by_date.get(d, set()))))
        result.append((md, len(kws), steps))
    return result
