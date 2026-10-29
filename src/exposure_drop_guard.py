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
    급감 재확인 : 바로 앞 회차가 '멈춤'이었고 이번 회차도 같은 기준 대비 20% 넘게 감소 → 실제 변화로 보고
                  그대로 씀(알림 · 이슈에 '두 회차 연속 같은 급감 — 실제 변화로 보고 썼음' 한 줄)

멈춤은 한 회차만 (2026-10-30 정책 A · 사장님 확인 '실제 급감에도 시트를 멈춰 세움이 되지 않게')
    예전엔 멈추면 시트가 안 바뀌어 다음 회차도 같은 기준으로 또 멈추고, 사람이 풀 때까지 실제
    급감을 끝없이 막았다. 이제 회차마다 판정 숫자를 '앞 회차 기록' 파일 하나에 남기고
    (EXPOSURE_DROP_STATE_PATH — 워크플로가 GitHub Actions 캐시로 다음 회차에 넘긴다), 다음 회차가 읽는다.
      앞 회차 멈춤 + 이번도 같은 기준에서 20% 넘게 감소 → 급감 재확인(씀)
      앞 회차 멈춤 + 이번은 20% 이하                    → 통과 / 일부 미확인(한 번 튄 것)
      기록 없음 · 못 읽음 · 24시간 지남 · 같은 실행의 기록 · 기준이 달라짐(시트가 그새 바뀜) → 지금처럼 멈춤(안전 쪽)
    '같은 기준' = 이번 기준 노출 줄 수가 앞 회차 멈춤 때의 기준 쪽에 더 가깝다(멈춘 뒤 시트가 안 바뀌었다).
    기록에는 실행 번호 · 시각 · 줄 수 · 비율만 넣는다 — 저장소가 공개라 키워드 · 링크 · 카페 · 탭 이름은 넣지 않는다.
    EXPOSURE_DROP_STATE_PATH 가 없으면(로컬 실행 · 시험) 기록을 읽지도 쓰지도 않는다 → 예전과 같다(멈춤).

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

import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
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
STATUS_RECONFIRMED = "급감 재확인"

ENV_ALLOW = "EXPOSURE_DROP_ALLOW"
ENV_STATE_PATH = "EXPOSURE_DROP_STATE_PATH"

RECONFIRM_NOTE = "두 회차 연속 같은 급감 — 실제 변화로 보고 썼음"

# 앞 회차 기록(회차 사이 상태) — 숫자만
STATE_VERSION = 1
STATE_MAX_AGE = timedelta(hours=24)        # 이보다 오래된 기록은 무효
STATE_FUTURE_SLACK = timedelta(minutes=10)  # 시계가 앞선 기록은 못 읽은 것으로 본다
PREV_OFF = "꺼짐"            # 기록 경로가 없음(로컬 · 시험) — 읽지도 쓰지도 않음
PREV_NONE = "없음"           # 기록 파일이 없음(첫 회차 · 캐시 없음)
PREV_HOLD = "멈춤"           # 바로 앞 회차가 멈춤
PREV_NOT_HOLD = "멈춤 아님"
PREV_UNREADABLE = "못 읽음"
PREV_EXPIRED = "지남"
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_STATE_INT_FIELDS = ("baseline_exposed", "current_exposed", "rows_compared", "rows_unreadable")


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
    cleanup_keys: Optional[set] = None,
    prev: Optional[dict] = None,
) -> dict:
    """이번 회차가 쓰려는 줄의 노출 수를 쓰기 전 시트와 맞대 판정한다.

    tab_updates: {탭: [RowUpdate(row, columns)]}  — 시트에 쓰려는 값
    row_context: {(탭, 행): 시작 때 읽은 행 dict}  — 앞 회차가 써 놓은 값
    cleanup_keys: {(탭, 행)} — 사람이 입력(키워드 · 링크)을 비운 줄의 K/L/M/O 비우기(D-034).
                  이번 회차가 잰 노출이 아니라 정리라서 맞대기에서 빼고 줄 수만 남긴다.
    prev: load_prev_state() 의 반환 — 앞 회차 기록. None 이면 기록 꺼짐(멈춤 한 회차 규칙이 안 걸림 → 예전처럼 멈춤).
    반환 dict 는 cycle_summary · 산출물에 그대로 남긴다.
    """
    prev = prev if isinstance(prev, dict) else {"state": PREV_OFF, "why": "앞 회차 기록 꺼짐", "record": None}
    result = {
        "status": STATUS_NO_COMPARE,
        "reason": "",
        "baseline_exposed": 0,
        "current_exposed": 0,
        "drop_rows": 0,
        "drop_ratio": None,
        "rows_compared": 0,
        "rows_unreadable": 0,
        "rows_cleanup_excluded": 0,
        "threshold": threshold,
        "partial": False,
        "allow_switch": bool(allow),
        "baseline_source": "이번 회차 시작 때 읽은 시트(raw_노출영역 우선) = 앞 회차가 써 놓은 값",
        # 둘 다 '기준을 읽은 같은 줄'만 센다 — K 분포 비교는 이 둘을 맞댄다(같은 줄 묶음끼리)
        "prev_k_distribution": {},
        "cur_k_distribution": {},
        "lost_examples": [],
        # 앞 회차 기록(숫자만) — 무엇을 읽었고 왜 그렇게 판정했나
        "prev_run": {k: prev.get(k) for k in ("state", "why", "record")},
    }
    try:
        prev_dist: Counter = Counter()
        cur_dist: Counter = Counter()
        baseline_exposed = 0
        current_exposed = 0
        compared = 0
        unreadable = 0
        cleanup_excluded = 0
        cleanup_keys = cleanup_keys or set()
        lost: list[dict] = []
        for tab_name, updates in (tab_updates or {}).items():
            for upd in updates:
                if (tab_name, upd.row) in cleanup_keys:
                    cleanup_excluded += 1
                    continue
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
            rows_cleanup_excluded=cleanup_excluded,
            prev_k_distribution=dict(prev_dist),
            cur_k_distribution=dict(cur_dist),
            lost_examples=lost,
            partial=bool(compared and unreadable),
        )
        # 못 읽은 줄이 있으면 어느 판정이든 꼬리에 붙인다 — 전체를 본 것처럼 말하지 않는다
        tail = f" · 일부 미확인 {unreadable}줄(기준 K 칸 못 읽음 — 읽은 {compared}줄끼리만 셈)" if unreadable else ""
        if compared == 0:
            if unreadable:
                result["reason"] = f"기준 K 칸을 못 읽음(맞댈 줄 0 · 못 읽은 줄 {unreadable})"
            elif cleanup_excluded:
                result["reason"] = f"이번 회차에 잰 줄이 없음(입력 비운 줄 정리 {cleanup_excluded}줄만 — 맞대기에서 뺌)"
            else:
                result["reason"] = "이번 회차에 쓸 줄이 없음"
            return result
        if baseline_exposed == 0:
            result["reason"] = (
                f"기준 노출 0줄(첫 회차 · 새 시트 — 줄어들 노출이 없음, 이번 노출 {current_exposed}줄){tail}"
            )
            return result
        ratio = (baseline_exposed - current_exposed) / baseline_exposed
        result["drop_ratio"] = round(ratio, 4)
        if ratio > threshold:
            prev_ok, prev_why = _prev_hold_same_baseline(prev, baseline_exposed)
            if allow:
                result["status"] = STATUS_RELEASED
                result["reason"] = (
                    f"노출 {baseline_exposed}→{current_exposed}줄({ratio:.0%} 감소)이지만 "
                    f"사람이 스위치를 켠 실행 → 그대로 씀{tail}"
                )
            elif prev_ok:
                result["status"] = STATUS_RECONFIRMED
                result["reason"] = (
                    f"노출 {baseline_exposed}→{current_exposed}줄({ratio:.0%} 감소) > {threshold:.0%} · "
                    f"{prev_why} → {RECONFIRM_NOTE}{tail}"
                )
            else:
                result["status"] = STATUS_HOLD
                result["reason"] = (
                    f"노출 {baseline_exposed}→{current_exposed}줄({ratio:.0%} 감소) > {threshold:.0%}"
                    f" · {prev_why}{tail}"
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


def is_hold(result: dict) -> bool:
    """이번 회차 시트 쓰기를 멈췄나 — 쓰기 여부를 말하는 모든 문구는 이 한 곳을 본다."""
    return (result or {}).get("status") == STATUS_HOLD


# ── 앞 회차 기록 (멈춤은 한 회차만 · 2026-10-30 정책 A) ───────────────────────────
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def state_path_from_env() -> Optional[str]:
    p = os.environ.get(ENV_STATE_PATH, "").strip()
    return p or None


def load_prev_state(path: Optional[str], run_id: str = "", now: Optional[datetime] = None) -> dict:
    """앞 회차 기록을 읽는다. 반환 {state, why, record}. 못 읽는 경우는 전부 '멈춤 쪽'(PREV_HOLD 아님)으로 남긴다."""
    if not path:
        return {"state": PREV_OFF, "why": "앞 회차 기록 꺼짐", "record": None}
    now = now or _now_utc()
    try:
        if not os.path.exists(path):
            return {"state": PREV_NONE, "why": "앞 회차 기록 없음", "record": None}
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict) or raw.get("version") != STATE_VERSION:
            raise ValueError("판 번호가 맞지 않음")
        rec = {
            "run_id": str(raw["run_id"]),
            "saved_at": str(raw["saved_at"]),
            "status": str(raw["status"]),
            "drop_ratio": raw.get("drop_ratio"),
        }
        if not _RUN_ID_RE.match(rec["run_id"]):
            raise ValueError("실행 번호 모양이 다름")
        for k in _STATE_INT_FIELDS:
            v = raw[k]
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise ValueError(f"{k} 가 0 이상 정수가 아님")
            rec[k] = v
        if rec["drop_ratio"] is not None and not isinstance(rec["drop_ratio"], (int, float)):
            raise ValueError("drop_ratio 가 숫자가 아님")
        saved = datetime.fromisoformat(rec["saved_at"])
        if saved.tzinfo is None:
            raise ValueError("시각에 시간대가 없음")
    except Exception as e:  # noqa: BLE001 — 못 읽으면 멈춤 쪽
        return {"state": PREV_UNREADABLE, "why": f"앞 회차 기록 못 읽음({type(e).__name__})", "record": None}
    age = now - saved
    if age < -STATE_FUTURE_SLACK:
        return {"state": PREV_UNREADABLE, "why": "앞 회차 기록 시각이 지금보다 뒤", "record": rec}
    if age > STATE_MAX_AGE:
        hours = age.total_seconds() / 3600
        return {"state": PREV_EXPIRED, "why": f"앞 회차 기록이 {hours:.0f}시간 지나 무효", "record": rec}
    if run_id and rec["run_id"] == str(run_id):
        return {"state": PREV_UNREADABLE, "why": "앞 회차 기록이 이번 실행 것", "record": rec}
    if rec["status"] == STATUS_HOLD:
        return {"state": PREV_HOLD, "why": f"앞 회차(실행 {rec['run_id']}) 멈춤", "record": rec}
    return {"state": PREV_NOT_HOLD, "why": f"앞 회차(실행 {rec['run_id']}) {rec['status']}", "record": rec}


def _prev_hold_same_baseline(prev: dict, baseline_exposed: int) -> tuple[bool, str]:
    """앞 회차가 멈춤이었고, 멈춘 뒤 시트가 그대로(같은 기준)인가.

    같은 기준 = 이번 기준 노출 줄 수가 앞 회차의 '기준'에 '이번 값'보다 더 가깝다.
    (멈춘 회차는 시트를 안 바꿨으니 다음 회차 기준은 그 회차 기준과 같다. 그새 누가 썼으면 '이번 값' 쪽에 가깝다.)
    """
    state = prev.get("state")
    why = str(prev.get("why") or "")
    if state != PREV_HOLD:
        if state in (PREV_NOT_HOLD,):
            return False, f"{why} — 첫 멈춤"
        return False, f"{why} — 멈춤(안전 쪽)"
    rec = prev.get("record") or {}
    pb, pc = int(rec.get("baseline_exposed", -1)), int(rec.get("current_exposed", -1))
    if abs(baseline_exposed - pb) <= abs(baseline_exposed - pc):
        return True, f"{why}(기준 {pb}줄 · 이번 기준 {baseline_exposed}줄 같은 기준)"
    return False, f"{why}이지만 그새 기준이 {pb}→{baseline_exposed}줄로 바뀜 — 새 급감으로 보고 멈춤"


def save_state(path: Optional[str], result: dict, run_id: str, now: Optional[datetime] = None) -> bool:
    """이번 회차 판정을 숫자만 남긴다(키워드 · 링크 · 카페 · 탭 이름 없음). 경로가 없으면 안 씀 → False."""
    if not path:
        return False
    now = now or _now_utc()
    rid = str(run_id or "")
    if not _RUN_ID_RE.match(rid):
        rid = "unknown"
    rec = {
        "version": STATE_VERSION,
        "run_id": rid,
        "saved_at": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "status": str(result.get("status") or ""),
        "drop_ratio": result.get("drop_ratio") if isinstance(result.get("drop_ratio"), (int, float)) else None,
    }
    for k in _STATE_INT_FIELDS:
        rec[k] = int(result.get(k) or 0)
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False)
    os.replace(tmp, path)
    return True


def write_decision_text(result: dict) -> str:
    """이번 회차 시트 쓰기 여부 한 문장 — 상태와 꼭 맞게(품질 2차 지적 2-1)."""
    status = (result or {}).get("status")
    if status == STATUS_HOLD:
        return "이번 회차 시트 쓰기는 위 급감으로 멈춤(못 읽은 줄도 쓰지 않음)"
    if status == STATUS_RECONFIRMED:
        return f"이번 회차는 {RECONFIRM_NOTE}"
    if status == STATUS_RELEASED:
        return "사람 스위치로 이번 회차 그대로 씀"
    return "못 읽은 줄 때문에 쓰기를 막지는 않음 — 이번 회차 그대로 씀"
