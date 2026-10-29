"""노출 급감 멈춤 — 이번 회차가 시트에 쓰려는 값이 '노출' 줄을 한꺼번에 크게 줄이면 쓰기를 멈춘다.

왜 만들었나 (2026-10-29)
    18:00 회차가 노출 줄을 552 → 173 으로(383줄이 노출 → 누락) 한 번에 바꿔 썼는데
    회차는 success 였고 알림도 없었다. 사장님 원문: "이거 제대로 한거 맞아 ?"
    원래 있던 K 분포 급변 감지(health.detect_k_anomaly)는 앞 회차 cycle_summary.json 을
    읽으려 했는데, GitHub 실행은 매번 새 폴더라 그 파일이 한 번도 없었다
    (FileNotFoundError → 조용히 pass). 게다가 감지돼도 시트 쓰기가 이미 끝난 뒤였다.

기준(앞 회차 값)을 어디서 읽나
    이번 회차가 시작할 때 읽은 시트(load_all_data_tabs) = 앞 회차가 써 놓은 결과다.
    값은 raw_노출영역(공식 모드의 진짜 값)을 먼저, 없으면 보이는 노출영역을 쓴다
    (snapshot_diff.field_value 와 같은 규칙). 새 요청 0 · 파일 0 · GitHub 권한 0.
    버린 길: 앞 회차 sheet-backup 산출물 — 그 백업은 앞 회차가 '쓰기 전에' 뜬 것이라
    두 회차 전 값이고, 실행 중에 gh 인증 · 내려받기가 더 든다.

무엇을 세나
    이번 회차가 쓰려는 줄(tab_updates)만, 같은 줄끼리 '쓰기 전 K'와 '쓰려는 K'를 맞댄다.
    노출 = K 의 시점 뗀 이름이 transitions.EXPOSED_VALUES 안(AB · 스마트블록 · 인기글 · 중복노출…).
    K 값을 정하는 규칙은 건드리지 않는다 — 이미 정해진 값을 세기만 한다.

판정
    통과        : 기준 대비 노출 감소가 20% 이하 (쓸 줄 전부 기준을 읽음)
    일부 미확인 : 기준을 읽은 줄끼리는 20% 이하인데, 기준 K 칸을 못 읽은 줄이 있다
                  → 막지 않고 쓰되 '통과'로 단정하지 않고 못 읽은 줄 수를 판정 · 알림에 드러낸다
    멈춤        : 20% 넘게 감소 → 이번 회차 시트 쓰기(K/L/M/O · C) 전부 멈춤, 실패 아님.
                  기준 노출 줄 수가 적어도(예 19→0) 같다 — 원 요청의 예외는 '첫 회차 · 기준 못 읽음' 둘뿐
    비교 못 함  : 기준 K 칸을 하나도 못 읽음 · 기준 노출 0줄(첫 회차 · 새 시트 — 줄어들 노출이 없음)
                  · 계산 오류 → 막지 않고 기록
    풀림        : 20% 넘게 감소했지만 사람이 스위치(EXPOSURE_DROP_ALLOW)를 켠 수동 실행 → 그대로 씀

    2026-10-30 품질 1차 반려 고침: ① 예전엔 기준 노출 20줄 미만을 '비교 못 함'으로 넘겨 정상 기준 19→0 을
    그대로 썼다(하한 MIN_BASELINE_EXPOSED 삭제). ② 기준을 반만 읽어도 '통과'라 했고, K 분포는 읽은 줄(기준)과
    쓰는 줄 전부(이번)를 맞대 서로 다른 줄 묶음을 비교했다 → 이제 '일부 미확인' + 같은 줄끼리의 분포
    (prev_k_distribution · cur_k_distribution)를 함께 낸다.

스위치 · 되돌리기 (한 곳)
    끄기·켜기: rank-check.yml 수동 실행 입력 allow_exposure_drop (기본 false, 정기 실행은 늘 false)
    주인: 순위체커 운영 담당
    되돌리는 법: 이 파일과 main.py 의 '노출 급감 멈춤' 블록을 되돌리면 예전 동작(그대로 씀)
"""
from __future__ import annotations

from collections import Counter
from typing import Optional

from src.transitions import EXPOSED_VALUES, parse_K_with_stamp

HEADER_AREA = "노출영역"
HEADER_RAW_AREA = "raw_노출영역"

DROP_RATIO_LIMIT = 0.20       # 이보다 '넘게' 줄면 멈춤 (카드: 20% 넘게)
# 기준 노출 줄 수 하한은 두지 않는다(2026-10-30) — 원 요청의 예외는 첫 회차 · 기준 못 읽음 둘뿐.

STATUS_PASS = "통과"
STATUS_PARTIAL = "일부 미확인"
STATUS_HOLD = "멈춤"
STATUS_NO_COMPARE = "비교 못 함"
STATUS_RELEASED = "풀림(사람 스위치)"

ENV_ALLOW = "EXPOSURE_DROP_ALLOW"


def _base(k_full: object) -> str:
    base, _ = parse_K_with_stamp(str(k_full or "").strip())
    return base or "미노출"


def baseline_k_full(row: dict) -> Optional[str]:
    """쓰기 전 시트의 K. raw_노출영역 우선(빈값이어도 그것이 진실), 둘 다 칸이 없으면 None."""
    if HEADER_RAW_AREA in row:
        return str(row.get(HEADER_RAW_AREA) or "")
    if HEADER_AREA in row:
        return str(row.get(HEADER_AREA) or "")
    return None


def is_exposed_k(k_full: object) -> bool:
    return _base(k_full) in EXPOSED_VALUES


def evaluate(
    tab_updates: dict,
    row_context: dict,
    allow: bool = False,
    threshold: float = DROP_RATIO_LIMIT,
) -> dict:
    """이번 회차가 쓰려는 줄의 노출 수를 쓰기 전 시트와 맞대 판정한다.

    tab_updates: {탭: [RowUpdate(row, columns)]}  — 시트에 쓰려는 값
    row_context: {(탭, 행): 시작 때 읽은 행 dict}  — 앞 회차가 써 놓은 값
    반환 dict 는 cycle_summary · 산출물에 그대로 남긴다.
    """
    result = {
        "status": STATUS_NO_COMPARE,
        "reason": "",
        "baseline_exposed": 0,
        "current_exposed": 0,
        "drop_rows": 0,
        "drop_ratio": None,
        "rows_compared": 0,
        "rows_unreadable": 0,
        "threshold": threshold,
        "partial": False,
        "allow_switch": bool(allow),
        "baseline_source": "이번 회차 시작 때 읽은 시트(raw_노출영역 우선) = 앞 회차가 써 놓은 값",
        # 둘 다 '기준을 읽은 같은 줄'만 센다 — K 분포 비교는 이 둘을 맞댄다(같은 줄 묶음끼리)
        "prev_k_distribution": {},
        "cur_k_distribution": {},
        "lost_examples": [],
    }
    try:
        prev_dist: Counter = Counter()
        cur_dist: Counter = Counter()
        baseline_exposed = 0
        current_exposed = 0
        compared = 0
        unreadable = 0
        lost: list[dict] = []
        for tab_name, updates in (tab_updates or {}).items():
            for upd in updates:
                row = row_context.get((tab_name, upd.row))
                prev_full = baseline_k_full(row) if row is not None else None
                if prev_full is None:
                    unreadable += 1
                    continue
                compared += 1
                new_full = upd.columns.get(HEADER_AREA, "")
                prev_dist[_base(prev_full)] += 1
                cur_dist[_base(new_full)] += 1
                prev_exp = is_exposed_k(prev_full)
                new_exp = is_exposed_k(new_full)
                baseline_exposed += int(prev_exp)
                current_exposed += int(new_exp)
                if prev_exp and not new_exp and len(lost) < 20:
                    lost.append({
                        "tab": tab_name,
                        "row": upd.row,
                        "keyword": (row or {}).get("키워드", ""),
                        "prev_K": prev_full,
                        "new_K": new_full,
                    })
        result.update(
            baseline_exposed=baseline_exposed,
            current_exposed=current_exposed,
            drop_rows=baseline_exposed - current_exposed,
            rows_compared=compared,
            rows_unreadable=unreadable,
            prev_k_distribution=dict(prev_dist),
            cur_k_distribution=dict(cur_dist),
            lost_examples=lost,
            partial=bool(compared and unreadable),
        )
        # 못 읽은 줄이 있으면 어느 판정이든 꼬리에 붙인다 — 전체를 본 것처럼 말하지 않는다
        tail = f" · 일부 미확인 {unreadable}줄(기준 K 칸 못 읽음 — 읽은 {compared}줄끼리만 셈)" if unreadable else ""
        if compared == 0:
            result["reason"] = (
                f"기준 K 칸을 못 읽음(맞댈 줄 0 · 못 읽은 줄 {unreadable})"
                if unreadable else "이번 회차에 쓸 줄이 없음"
            )
            return result
        if baseline_exposed == 0:
            result["reason"] = (
                f"기준 노출 0줄(첫 회차 · 새 시트 — 줄어들 노출이 없음, 이번 노출 {current_exposed}줄){tail}"
            )
            return result
        ratio = (baseline_exposed - current_exposed) / baseline_exposed
        result["drop_ratio"] = round(ratio, 4)
        if ratio > threshold:
            if allow:
                result["status"] = STATUS_RELEASED
                result["reason"] = (
                    f"노출 {baseline_exposed}→{current_exposed}줄({ratio:.0%} 감소)이지만 "
                    f"사람이 스위치를 켠 실행 → 그대로 씀{tail}"
                )
            else:
                result["status"] = STATUS_HOLD
                result["reason"] = (
                    f"노출 {baseline_exposed}→{current_exposed}줄({ratio:.0%} 감소) > {threshold:.0%}{tail}"
                )
        else:
            change = f"{ratio:.0%} 감소" if ratio >= 0 else f"{-ratio:.0%} 증가"
            if unreadable:
                result["status"] = STATUS_PARTIAL
                result["reason"] = (
                    f"읽은 {compared}줄: 노출 {baseline_exposed}→{current_exposed}줄({change}){tail} — 막지 않고 씀"
                )
            else:
                result["status"] = STATUS_PASS
                result["reason"] = f"노출 {baseline_exposed}→{current_exposed}줄({change})"
        return result
    except Exception as e:  # 장치 고장은 '비교 못 함'으로 남긴다 — 통과로 바꾸지 않는다
        result["status"] = STATUS_NO_COMPARE
        result["reason"] = f"판정 계산 오류: {type(e).__name__}: {e}"
        return result


def summary_line(result: dict) -> str:
    """로그 한 줄."""
    return f"[노출급감] {result.get('status')} — {result.get('reason')}"
