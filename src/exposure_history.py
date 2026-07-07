"""exposure_history: 아카이브(상위노출_이력) 기반 일별 상위노출 개수 추세 (텔레그램 보고용).

사장님 2026-07-07: 매일 개수만 찍혀 '흐름'이 안 보여 답답 → 지난 며칠 개수 추세를 보고에 표시.
데이터 = 상위노출_이력 탭(archive.py 가 매 cron 적재). SheetsClient.spreadsheet 로 읽는다.
⚠️ 비차단: 탭/키 없거나 읽기 실패 시 빈 결과 → 보고는 추세 섹션만 생략(핵심 보고는 유지).
"""
from __future__ import annotations

from collections import OrderedDict, defaultdict

from src.transitions import EXPOSED_VALUES

ARCHIVE_TAB = "상위노출_이력"


def read_archive_rows(client) -> list:
    """상위노출_이력 → [(날짜, 탭, 노출영역), ...]. 탭 없음/실패 시 []. (비차단)"""
    try:
        ws = client.spreadsheet.worksheet(ARCHIVE_TAB)
        vals = ws.get_all_values()
    except Exception:
        return []
    if len(vals) < 2:
        return []
    h = vals[0]
    try:
        di, ti, ai = h.index("날짜"), h.index("탭"), h.index("노출영역")
    except ValueError:
        return []
    out = []
    for r in vals[1:]:
        if di < len(r) and str(r[di]).strip():
            out.append((r[di], r[ti] if ti < len(r) else "", r[ai] if ai < len(r) else ""))
    return out


def daily_trend(rows: list, days: int = 6) -> "OrderedDict":
    """행 → 최근 days개 날짜별 {탭: 상위노출수} + 합계. 날짜 오름차순(왼쪽 과거 → 오른쪽 오늘).

    반환: OrderedDict(날짜 → {"합계": n, 탭명: n, ...}). 데이터 없으면 빈 OrderedDict.
    """
    by: dict = defaultdict(lambda: defaultdict(int))
    for d, t, a in rows:
        if a in EXPOSED_VALUES:
            by[d][t] += 1
    dates = sorted(by)[-days:]
    out: "OrderedDict" = OrderedDict()
    for d in dates:
        per = dict(by[d])
        out[d] = {"합계": sum(per.values()), **per}
    return out
