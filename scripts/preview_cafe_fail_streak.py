"""미리보기(라이브 write 없음): 카페 구좌 1등 실패 재발행 횟수 카운터 → 키워드 색칠 대상 산출.

변경 이력:
- v1: run당 카운터
- v2: 하루당 카운터 (YYYY-MM-DD 게이트)
- v3: 재발행 횟수 (작업일 M/D 게이트) — 사장님 확정 의미
- v4: 역대 최대(raw_카페실패최대) 추가 → 전적 있으나 현재 1등 = 옅은 회색

의미: 재발행(작업일 값이 바뀜)마다 1일 지나도 1등 실패면 +1. 같은 발행분은 run 수에 무관 1회만.
색 임계: 1회=연노랑, 2회=주황, 3회+=빨강. 전적 있으나 현재 1등=옅은 회색. 무전적 1등=흰색.

⚠️ 이 스크립트는 읽기/계산만. 구글시트 write·git push 없음.
실행: .venv/Scripts/python.exe scripts/preview_cafe_fail_streak.py
"""
from __future__ import annotations

import glob
import os
import sys
from collections import Counter
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.sheets import (  # noqa: E402
    _next_cafe_fail_streak,
    _next_cafe_fail_history,
    _fail_streak_color,
    _parse_fail_streak,
    COLOR_FAIL_STREAK_1,
    COLOR_FAIL_STREAK_2,
    COLOR_FAIL_STREAK_3,
    COLOR_FAIL_HISTORY,
)
from src.snapshot_diff import load_backup  # noqa: E402
from src.report_metrics import _md_to_date  # noqa: E402

_H_WORKDATE = "작업일"
_H_KEYWORD  = "키워드"
_H_LINK     = "링크"
_H_M        = "노출여부(카페구좌순위)"
_H_RAW_M    = "raw_카페순위"
_H_COUNT    = "raw_카페1등실패횟수"
_H_LAST_WD  = "raw_카페실패마지막작업일"
_H_MAX      = "raw_카페실패최대"
_H_SINCE    = "raw_카페1등연속시작"
_H_EVER     = "raw_카페1등달성"

_COLOR_NAME = {
    id(COLOR_FAIL_STREAK_1): "연노랑(1회)",
    id(COLOR_FAIL_STREAK_2): "주황(2회)",
    id(COLOR_FAIL_STREAK_3): "빨강(3회+)",
    id(COLOR_FAIL_HISTORY):  "옅은회색(전적)",
}


def _cafe_rank(row: dict) -> str:
    v = row.get(_H_RAW_M)
    if v is None or str(v).strip() == "":
        v = row.get(_H_M)
    return str(v or "").strip()


def _row_usable(row: dict) -> bool:
    return bool(str(row.get(_H_KEYWORD, "") or "").strip())


def _pick_local_backup() -> str | None:
    fs = sorted(glob.glob(".harness/backups/*.json.gz") + glob.glob(".harness/backups/*.json"))
    for f in reversed(fs):
        try:
            d = load_backup(f)
        except Exception:
            continue
        for rows in (d.get("tabs") or {}).values():
            for r in rows:
                if str(r.get(_H_WORKDATE, "") or "").strip() and str(r.get(_H_LINK, "") or "").strip():
                    return f
    return None


def _synthetic_backup(ref: date) -> dict:
    """합성 스냅샷 — 사장님 예시 + 전적회색 케이스 포함.

    last_wd: 마지막으로 +1 한 발행의 작업일(M/D).
    max_cnt: 역대 최대 실패 횟수 (단조 비감소).
    """
    prev_day = ref - timedelta(days=1)
    today_wd = f"{ref.month}/{ref.day}"
    p = f"{prev_day.month}/{prev_day.day}"

    def r(kw, wd, rawm, count, last_wd="", max_cnt=None):
        if max_cnt is None:
            max_cnt = count  # 기본값: 최대 == 현재 횟수
        return {
            _H_KEYWORD: kw, _H_WORKDATE: wd,
            _H_LINK: f"https://cafe.naver.com/x/{kw}",
            _H_RAW_M: rawm, _H_COUNT: count, _H_LAST_WD: last_wd,
            _H_MAX: max_cnt, "_row": 0,
        }

    shampoo = [
        # 새 발행분 실패 (작업일 != 마지막작업일, 1일↑)
        r("지루성두피염샴푸", "7/5",  "", "2", "7/3"),   # 3차 실패 → 3 빨강
        r("비듬샴푸추천",    "7/9",  "4","1", "7/6"),   # 2차 실패 → 2 주황
        r("모낭염샴푸",     "7/14", "",  "0", ""),      # 첫 실패  → 1 연노랑
        # 같은 발행분 재run (작업일 == 마지막작업일 → 유지)
        r("두피각질샴푸",   "7/10", "",  "2", "7/10"),  # 같은 발행 → 2 유지(주황)
        # 1등 리셋: 전적 있음 → 회색
        r("탈모샴푸",      "7/10", "1", "3", "7/10", max_cnt="3"),  # 1등→0, 최대3 → 회색
        # 1등 리셋: 전적 없음 → 흰색
        r("두피쿨링샴푸",  "7/8",  "1", "0", "", max_cnt="0"),      # 1등, 무전적 → 흰색
        # 유지(건드리지 않음)
        r("지성두피샴푸",  "",     "",  "4", "7/10"),  # 작업일없음 → 4 유지(빨강)
        r("두피토닉샴푸",  today_wd,"", "1", p),       # 오늘작업=1일미경과 → 1 유지(연노랑)
    ]
    bodywash = [
        r("등드름바디워시",   "7/3",  "7","4", "7/1"),   # 5차 실패 → 5 빨강
        r("가슴여드름바디워시","7/12", "",  "1", "7/9"),   # 2차 실패 → 2 주황
        r("바디워시트러블",   "7/15", "2", "0", ""),      # 첫 실패  → 1 연노랑
        r("모공바디워시",    today_wd,"",  "3", p),       # 오늘작업 → 3 유지(빨강)
        # 1등이지만 전적 있음 → 회색
        r("두피여드름바디워시","7/14","1", "0", "", max_cnt="2"),   # 1등, 전적2 → 회색
    ]
    return {"timestamp": ref.isoformat(),
            "tabs": {"샴푸 카외": shampoo, "바디워시 카외": bodywash}}


def _cause(rank: str, wd: str, last_wd: str, ref: date, ever: bool = False) -> str:
    if rank == "1":
        return "1등리셋"
    if ever:
        return "과거1위동결"
    if not wd:
        return "작업일없음"
    wd_date = _md_to_date(wd, ref)
    if wd_date is None or (ref - wd_date).days < 2:
        return "2일미경과"
    if wd == last_wd:
        return "같은발행재run"
    return "증가"


def main() -> None:
    ref = date(2026, 7, 16)
    path = _pick_local_backup()
    if path:
        backup = load_backup(path)
        ts = str(backup.get("timestamp", "") or "")
        if len(ts) >= 10 and ts[4] == "-":
            try:
                ref = date(int(ts[:4]), int(ts[5:7]), int(ts[8:10]))
            except ValueError:
                pass
        source = f"실백업 {os.path.basename(path)}"
    else:
        backup = _synthetic_backup(ref)
        source = "합성 fixture (로컬 백업은 작업일/raw_카페순위 없는 통합테스트 아티팩트라 대체)"

    print("=" * 92)
    print(" 카페 1등 실패 재발행 횟수 → 키워드 색칠 미리보기  【횟수 v4 + 전적회색】  (라이브 write 없음)")
    print(f" 데이터 소스: {source}")
    print(f" 기준일(오늘): {ref.isoformat()}")
    print("=" * 92)

    increased, held, history_gray, no_color = [], [], [], []
    total = 0

    for tab, rows in (backup.get("tabs") or {}).items():
        if "카외" not in tab:
            continue
        for row in rows:
            if not _row_usable(row):
                continue
            total += 1
            prev = _parse_fail_streak(row.get(_H_COUNT))
            prev_max = _parse_fail_streak(row.get(_H_MAX))
            prev_since = str(row.get(_H_SINCE, "") or "").strip()
            prev_ever = str(row.get(_H_EVER, "") or "").strip()
            rank = _cafe_rank(row)
            wd = str(row.get(_H_WORKDATE, "") or "").strip()
            last_wd = str(row.get(_H_LAST_WD, "") or "").strip()
            kw = str(row.get(_H_KEYWORD))
            rank_str = rank or "(빈칸=미노출)"

            new_cnt, new_wd = _next_cafe_fail_streak(
                prev, rank, wd, ref, last_count_date_str=last_wd, ever_onetop=(prev_ever == "Y")
            )
            new_max, _ = _next_cafe_fail_history(rank, prev_max, new_cnt, prev_since, ref)
            color = _fail_streak_color(new_cnt, new_max)
            c = _cause(rank, wd, last_wd, ref, ever=(prev_ever == "Y"))
            cname = _COLOR_NAME.get(id(color), "-") if color else "-"
            entry = (tab, kw, wd, rank_str, prev, new_cnt, new_max, last_wd, new_wd, cname, c)
            if c == "증가":
                increased.append(entry)
            elif c in ("같은발행재run", "2일미경과", "작업일없음", "과거1위동결") and color is not None:
                held.append(entry)
            elif c == "1등리셋" and new_max >= 1:
                history_gray.append(entry)
            else:
                no_color.append(entry)

    SEP = "  " + "-" * 90

    print(f"\n[횟수 증가] {len(increased)}개 — 새 발행이 2일↑ 경과(발행 다음다음날) 후 1등 실패\n")
    if increased:
        print(f"  {'탭':<12} {'키워드':<22} {'작업일':<7} {'카페순위':<12}"
              f" {'prev':>4} {'→cnt':>4} {'→max':>4}  {'→마지막작업일':<10} {'색단계'}")
        print(SEP)
        for tab, kw, wd, rank, prev, cnt, mx, _, new_wd, cname, _ in sorted(increased, key=lambda x: -x[5]):
            print(f"  {tab:<12} {kw:<22} {wd:<7} {rank:<12}"
                  f" {prev:>4} {cnt:>4} {mx:>4}  {new_wd:<10} {cname}")
    else:
        print("  (없음)")

    if held:
        print(f"\n[색 유지(횟수 불변)] {len(held)}개 — 같은 발행 재run·유예\n")
        print(f"  {'탭':<12} {'키워드':<22} {'작업일':<7} {'카페순위':<12}"
              f" {'cnt':>4} {'max':>4}  {'사유':<16} {'색단계'}")
        print(SEP)
        for tab, kw, wd, rank, _, cnt, mx, _, _, cname, cause in held:
            print(f"  {tab:<12} {kw:<22} {wd:<7} {rank:<12}"
                  f" {cnt:>4} {mx:>4}  {cause:<16} {cname}")

    if history_gray:
        print(f"\n[전적 있으나 현재 1등] {len(history_gray)}개 — 옅은 회색(전적 기억)\n")
        print(f"  {'탭':<12} {'키워드':<22} {'작업일':<7} {'카페순위':<12}"
              f" {'streak':>6} {'max':>4}  {'색단계'}")
        print(SEP)
        for tab, kw, wd, rank, _, cnt, mx, _, _, cname, _ in history_gray:
            print(f"  {tab:<12} {kw:<22} {wd:<7} {rank:<12}"
                  f" {cnt:>6} {mx:>4}  {cname}")

    print(f"\n[색 없음] {len(no_color)}개 — 1등 무전적(흰색)")
    for cause, n in Counter(e[10] for e in no_color).items():
        print(f"  - {cause:<18}: {n}")

    print(
        f"\n[합계] 총 {total}행 = 증가 {len(increased)} + 색유지 {len(held)} "
        f"+ 전적회색 {len(history_gray)} + 색없음 {len(no_color)}"
    )
    print("\n※ 이 출력은 계산 결과입니다. 구글시트 write·git push 하지 않았습니다.")


if __name__ == "__main__":
    main()
