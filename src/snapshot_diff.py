"""snapshot_diff: 백업 json.gz 2개(어제·오늘)를 비교해 제품(탭)별 노출영역 분포 + 전날 변화 산출.

M10 (2026-06-19, 텔레그램 보고). grounding + critic 정합:
- 데이터는 `.harness/backups/{run_id}_{ts}.json.gz` 단독으로 산출 (시트 read 불필요 = 서비스계정 키 불필요).
- ⚠️ critic 치명 1 — 백업 K = "직전 cron 이 시트에 쓴 값"(run_cycle 시작 snapshot, main.py L529).
  따라서 "어제 vs 오늘" 비교는 **백업 ↔ 백업** (동일 출처)로만 한다.
  cycle_summary 의 tab_updates 기반 K 분포(이번 사이클 크롤 결과)와는 모집단이 달라 직접 비교 금지.
- ⚠️ critic 치명 2 — "어제" = 절대 24h 아님. 호출측이 "직전 성공 백업"을 prev 로 넘긴다.
  prev=None(첫 운영/retention 경계)이면 분포만 내고 변화(diffs)는 비운다 → 보고측이 "비교 기준 없음" 표기.
- K base/시점 분리는 transitions.parse_K_with_stamp 재활용 (표기 정합).
"""
from __future__ import annotations

import gzip
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from src.transitions import EXPOSED_VALUES, parse_K_with_stamp

# 시트 헤더명 = 백업 행 dict 키 (sheets.py 와 동일, 정확 매칭 필수)
_H_KEYWORD = "키워드"
_H_AREA = "노출영역"  # K
_H_L = "노출여부(통합탭 순위)"  # L 통합탭 순위 (작을수록 좋음)
_H_M = "노출여부(카페구좌순위)"  # M 카페구좌 순위
_H_JISIKIN = "지식인탭"  # O
_H_LINK = "링크"
_H_WORKDATE = "작업일"  # 마케터 작업일 (M/D 형식, 실측 78% 채워짐)
_H_TYPE = "유형"  # C — 대표 구좌 타입 (AB/스마트블록/인기글), 실측 99% 채워짐

# D-040 공식 모드: 보이는 K/L/M/O 는 '공식'(input 키 불일치 시 빈칸/재검사필요 표시)이고
# 진짜 값은 raw_* 숨김칸에 있다(sheets.py 와 동일). 집계는 raw_* 우선, 없으면(구 백업/비공식) 보이는 값.
# (D-056 디버그: 봇 '지식인 0개' 원인 = 보이는 지식인탭 칸 부재/빈칸인데 raw_지식인탭 에 값 존재.)
_H_RAW_AREA = "raw_노출영역"
_H_RAW_L = "raw_통합순위"
_H_RAW_M = "raw_카페순위"
_H_RAW_JISIKIN = "raw_지식인탭"
_RAW_OF = {_H_AREA: _H_RAW_AREA, _H_L: _H_RAW_L, _H_M: _H_RAW_M, _H_JISIKIN: _H_RAW_JISIKIN}

_DROP_DELETED = "삭제"  # 진짜 글 사라짐
_DROP_MISSING = "누락"  # 노출됐다 빠짐 (회복 가능)


def field_value(row: dict, visible_header: str) -> str:
    """공식 모드 대응 값 읽기: raw_* 키가 있으면 그 값(빈값이어도 진실), 없으면 보이는 값."""
    raw = _RAW_OF.get(visible_header)
    if raw is not None and raw in row:
        return str(row.get(raw, "") or "")
    return str(row.get(visible_header, "") or "")


@dataclass
class RowDiff:
    """한 키워드(행)의 어제→오늘 변화."""

    tab: str
    keyword: str
    prev_k: str  # 어제 K base (시점 제거)
    curr_k: str  # 오늘 K base
    prev_rank: Optional[int]  # 어제 통합탭 순위 (없으면 None)
    curr_rank: Optional[int]  # 오늘 통합탭 순위
    kind: str  # 신규노출 / 누락 / 삭제 / 오름 / 내림 / 변화
    work_date: str = ""  # K 시점스탬프의 '상태 시작일' (메모리: 마지막 측정일 아님)


@dataclass
class TabReport:
    """한 제품(탭)의 분포 + 변화."""

    tab: str
    distribution: Counter  # 오늘 {K base: count}
    prev_distribution: Counter  # 어제 {K base: count}
    diffs: list[RowDiff] = field(default_factory=list)
    baseline_available: bool = True  # 어제 백업 있었나 (False면 diffs 비움)
    jisikin_now: int = 0  # 오늘 지식인(O열) 뜬 키워드 수
    jisikin_prev: int = 0  # 어제 지식인 뜬 키워드 수
    worked: int = 0  # 작업일=대상일(어제) 인 키워드 수
    worked_exposed: int = 0  # 그중 현재 상위노출 중인 수
    unworked: int = 0  # 작업일 빈 칸 = 아직 작업 안 한 키워드 수
    type_dist: Counter = field(default_factory=Counter)  # 오늘 유형(C) 분포
    type_dist_prev: Counter = field(default_factory=Counter)  # 어제 유형(C) 분포
    type_changes: int = 0  # 유형(C) 바뀐 키워드 수
    type_change_dirs: Counter = field(default_factory=Counter)  # {'AB→인기글': n}
    # 정합용(2026-07-07): '지금 노출 개수' 변화를 완전히 설명하는 버킷.
    #   exposed_now = exposed_prev + (신규노출 + new_exposed) − (누락 + 삭제 + other_exit + vanished_exposed)
    new_exposed: int = 0       # 어제 없던 새 키워드가 오늘 상위노출(신규노출 kind엔 안 잡히던 것)
    vanished_exposed: int = 0  # 어제 노출됐는데 오늘 행 자체가 사라짐(줄 삭제 = 누락과 다름)
    other_exit: int = 0        # 노출→비노출인데 누락/삭제 아님(미노출/실패/재검사 등, 기존엔 '변화'로 묻힘)

    @property
    def total(self) -> int:
        return sum(self.distribution.values())

    @property
    def exposed_now(self) -> int:
        return sum(c for k, c in self.distribution.items() if k in EXPOSED_VALUES)

    @property
    def exposed_prev(self) -> int:
        return sum(c for k, c in self.prev_distribution.items() if k in EXPOSED_VALUES)


def load_backup(path: str) -> dict:
    """*.json.gz (또는 .json) 백업 로드 → 'tabs' 키 보유 dict."""
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def k_base_of(row: dict) -> str:
    """행의 노출영역(K)에서 시점 제거한 base. 빈값 → '미노출'. (raw 우선)"""
    base, _ = parse_K_with_stamp(field_value(row, _H_AREA))
    return base or "미노출"


def rank_of(row: dict, header: str = _H_L) -> Optional[int]:
    """순위 컬럼에서 정수 추출 (없거나 숫자 아니면 None). (raw 우선)"""
    m = re.search(r"\d+", field_value(row, header))
    return int(m.group()) if m else None


def work_date_of(row: dict) -> str:
    """K 시점스탬프의 상태 시작일 (예: 'AB (6/18 03:00~)' → '6/18').

    ⚠️ 메모리 정합: 시점 = 상태 시작일(설계의도), 마지막 측정일 아님.
    """
    _, stamp = parse_K_with_stamp(field_value(row, _H_AREA))
    return stamp.split()[0] if stamp else ""


def _norm_kw(v: object) -> str:
    return re.sub(r"\s+", " ", str(v or "").strip()).casefold()


def _norm_link(v: object) -> str:
    """sheets._normalize_input_link 와 동일 규칙 (끝 슬래시만 제거)."""
    text = str(v or "").strip().casefold()
    if not text:
        return ""
    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"^m\.", "", text)
    text = re.sub(r"[?#].*$", "", text)
    return re.sub(r"/+$", "", text)


def row_identity(row: dict) -> tuple:
    """행 매칭 키. 1순위 (_tab,_row), 폴백 (키워드, 정규화 링크)."""
    tab = row.get("_tab")
    rownum = row.get("_row")
    if tab is not None and rownum is not None:
        return ("rc", str(tab), str(rownum))
    return ("kl", _norm_kw(row.get(_H_KEYWORD)), _norm_link(row.get(_H_LINK)))


def compute_distribution(backup: dict) -> dict:
    """탭별 {K base: count}."""
    out: dict[str, Counter] = {}
    for tab, rows in (backup.get("tabs") or {}).items():
        c: Counter = Counter()
        for row in rows:
            c[k_base_of(row)] += 1
        out[tab] = c
    return out


def classify(prev_k: str, curr_k: str, prev_rank: Optional[int], curr_rank: Optional[int]) -> str:
    """어제→오늘 K/순위 → 변화 종류. 누락(회복 가능) ≠ 삭제(사라짐) 구분."""
    exposed_prev = prev_k in EXPOSED_VALUES
    exposed_curr = curr_k in EXPOSED_VALUES
    if curr_k == _DROP_DELETED and prev_k != _DROP_DELETED:
        return "삭제"
    if exposed_prev and curr_k == _DROP_MISSING:
        return "누락"
    if not exposed_prev and exposed_curr:
        return "신규노출"
    if exposed_prev and exposed_curr and prev_rank and curr_rank:
        if curr_rank < prev_rank:
            return "오름"
        if curr_rank > prev_rank:
            return "내림"
    return "변화"


def _type_dist(rows: list) -> Counter:
    """유형(C) 값 분포 (빈칸 제외)."""
    c: Counter = Counter()
    for r in rows:
        t = str(r.get(_H_TYPE, "") or "").strip()
        if t:
            c[t] += 1
    return c


def _work_stats(rows: list, work_date: Optional[str]) -> tuple:
    """(worked, worked_exposed, unworked).
    worked = 작업일==work_date 행 수 / worked_exposed = 그중 상위노출 / unworked = 작업일 빈 행 수.
    """
    worked = worked_exposed = unworked = 0
    for r in rows:
        wd = str(r.get(_H_WORKDATE, "") or "").strip()
        if not wd:
            unworked += 1
        if work_date and wd == work_date:
            worked += 1
            if k_base_of(r) in EXPOSED_VALUES:
                worked_exposed += 1
    return worked, worked_exposed, unworked


def _index_rows(backup: dict) -> dict:
    idx: dict[tuple, dict] = {}
    for rows in (backup.get("tabs") or {}).values():
        for row in rows:
            idx[row_identity(row)] = row
    return idx


def _count_jisikin(backup: dict, tab: str) -> int:
    """탭에서 지식인탭(O열)이 채워진(= 지식iN 박스 뜬) 키워드 수. (raw_지식인탭 우선)"""
    rows = (backup.get("tabs") or {}).get(tab, [])
    return sum(1 for r in rows if field_value(r, _H_JISIKIN).strip())


def diff_backups(prev: Optional[dict], curr: dict, work_date: Optional[str] = None) -> list:
    """어제(prev)·오늘(curr) 백업 → 탭별 TabReport.

    ⚠️ prev/curr 모두 백업 출처여야 함(critic 치명 1). prev=None → baseline 없음(diffs 비움).
    신규 행(어제 없던 키워드)은 분포에는 잡히되 변화 목록엔 넣지 않는다(‘전부 신규’ 오보 방지).
    work_date(M/D) 주면 탭별 '그날 작업/적중/미작업' 집계도 채운다.
    """
    curr_dist = compute_distribution(curr)
    prev_dist = compute_distribution(prev) if prev else {}
    prev_index = _index_rows(prev) if prev else {}

    reports: list[TabReport] = []
    for tab in curr_dist:
        curr_rows = (curr.get("tabs") or {}).get(tab, [])
        worked, worked_exposed, unworked = _work_stats(curr_rows, work_date)
        tr = TabReport(
            tab=tab,
            distribution=curr_dist.get(tab, Counter()),
            prev_distribution=prev_dist.get(tab, Counter()),
            baseline_available=prev is not None,
            jisikin_now=_count_jisikin(curr, tab),
            jisikin_prev=_count_jisikin(prev, tab) if prev else 0,
            worked=worked,
            worked_exposed=worked_exposed,
            unworked=unworked,
            type_dist=_type_dist(curr_rows),
            type_dist_prev=_type_dist((prev.get("tabs") or {}).get(tab, [])) if prev else Counter(),
        )
        if prev is not None:
            curr_ids = set()
            for row in curr_rows:
                rid = row_identity(row)
                curr_ids.add(rid)
                prev_row = prev_index.get(rid)
                if prev_row is None:
                    # 어제 없던 행 = 변화 목록엔 안 넣음('전부 신규' 오보 방지). 단 정합용으로
                    # 새 키워드가 오늘 노출이면 new_exposed 로 센다(노출 개수 증가분 설명).
                    if k_base_of(row) in EXPOSED_VALUES:
                        tr.new_exposed += 1
                    continue
                # 유형(C) 변경 (노출 변화와 별개 — K 동일해도 유형 바뀔 수 있음)
                pt = str(prev_row.get(_H_TYPE, "") or "").strip()
                ct = str(row.get(_H_TYPE, "") or "").strip()
                if pt and ct and pt != ct:
                    tr.type_changes += 1
                    tr.type_change_dirs[f"{pt}→{ct}"] += 1
                # 노출/순위 변경
                pk, ck = k_base_of(prev_row), k_base_of(row)
                pr, cr = rank_of(prev_row), rank_of(row)
                if pk == ck and pr == cr:
                    continue  # 변화 없음
                kind = classify(pk, ck, pr, cr)
                # 정합용: 노출→비노출인데 누락/삭제로 안 잡힌 이탈(미노출/실패/재검사) = other_exit
                if pk in EXPOSED_VALUES and ck not in EXPOSED_VALUES and kind not in ("누락", "삭제"):
                    tr.other_exit += 1
                tr.diffs.append(
                    RowDiff(
                        tab=tab,
                        keyword=str(row.get(_H_KEYWORD, "") or ""),
                        prev_k=pk,
                        curr_k=ck,
                        prev_rank=pr,
                        curr_rank=cr,
                        kind=kind,
                        work_date=work_date_of(row),
                    )
                )
            # 어제 있다 오늘 사라진 행(줄 삭제) 중 어제 노출이던 것 = vanished_exposed(정합용)
            for prow in (prev.get("tabs") or {}).get(tab, []):
                if row_identity(prow) not in curr_ids and k_base_of(prow) in EXPOSED_VALUES:
                    tr.vanished_exposed += 1
        reports.append(tr)
    return reports


# 노출 소요일(발행→노출) 버킷 표시 순서.
LAG_BUCKETS = ["당일", "+1일", "+2일", "+3~6일", "+7일+", "음수(재노출)", "미상"]


def _md_to_date(s: str, year: int):
    try:
        m, d = str(s).strip().split("/")[:2]
        return date(year, int(m), int(d))
    except Exception:
        return None


def exposure_lag_distribution(curr: dict, today: date) -> Counter:
    """지금 상위노출된 키워드의 '발행(작업일) → 노출(K스탬프 상태시작일)' 소요일 분포.

    ⚠️ K스탬프 = '현재 노출 상태 시작일'(재노출이면 최초노출보다 늦음) → 근사치.
    정확판은 아카이브(상위노출_이력) 축적 후. 반환 Counter 키 = LAG_BUCKETS.
    """
    out: Counter = Counter()
    for rows in (curr.get("tabs") or {}).values():
        for r in rows:
            if k_base_of(r) not in EXPOSED_VALUES:
                continue
            dw = _md_to_date(str(r.get(_H_WORKDATE, "") or "").strip(), today.year)
            de = _md_to_date(work_date_of(r), today.year)
            if not dw or not de:
                out["미상"] += 1
                continue
            lag = (de - dw).days
            if lag < 0:
                out["음수(재노출)"] += 1
            elif lag == 0:
                out["당일"] += 1
            elif lag == 1:
                out["+1일"] += 1
            elif lag == 2:
                out["+2일"] += 1
            elif lag <= 6:
                out["+3~6일"] += 1
            else:
                out["+7일+"] += 1
    return out
