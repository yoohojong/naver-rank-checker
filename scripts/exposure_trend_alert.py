#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""exposure_trend_alert.py — 상위노출 개수 감소 감지 · 텔레그램 알림

무엇: '상위노출_이력' 시트(비공개)에서 날짜별 노출 건수를 집계해
      이전 주 대비 최근 주 평균이 DROP_PCT 이상 줄면 텔레그램 알림을 보낸다.
      탭(카테고리)별 분해도 함께 보고한다.

알고리즘: guardian/trend_watch.py 의 detect_exposure_trend() 동일 로직.
  - 최신 W일 평균 vs 직전 W일 평균 비교.
  - 하락률 >= DROP_PCT% 이면 DOWN 판정 → 알림 발송(--send 시).
  - 두 창 중 어느 하나라도 데이터 부족이면 UNKNOWN(발송 없음).

안전 원칙:
  1. 읽기 전용 — 어떤 시트/파일/DB도 수정하지 않는다.
  2. 기본 dry-run — 알림 문구를 콘솔에만 출력.
     실제 발송은 --send 플래그 시에만.
  3. 데이터 없으면 '데이터 없음'으로 표기. 추측 금지.
  4. 예외 → 크래시 없이 종료 코드 1 반환.
  5. 기존 워크플로 / 기존 시트 쓰기 코드 일체 건드리지 않는다.

사용:
  python scripts/exposure_trend_alert.py --fixture
  python scripts/exposure_trend_alert.py --live
  python scripts/exposure_trend_alert.py --live --send

환경변수:
  SPREADSHEET_ID           Google Sheets 파일 키 (GitHub secret)
  SERVICE_ACCOUNT_JSON     서비스 계정 JSON 전체 문자열 (GitHub secret)
  TELEGRAM_BOT_TOKEN       텔레그램 봇 토큰 (GitHub secret)
  TELEGRAM_CHAT_ID         텔레그램 채팅 ID (GitHub secret)
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

# Windows 콘솔 utf-8 안전 출력
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ---------------------------------------------------------------------------
# 임계값 (이 상수만 바꾸면 전체 동작 변경)
# ---------------------------------------------------------------------------
EXPOSURE_DROP_PCT = 10       # 이전 창 대비 하락 % 기준 (기본 10%)
EXPOSURE_WINDOW_DAYS = 7     # 비교 창 크기 (기본 7일 = 주간)
ARCHIVE_TAB_NAME = "상위노출_이력"

# 심각도
DOWN = "DOWN"
OK = "OK"
UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# 공통 유틸
# ---------------------------------------------------------------------------

def _now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _parse_date(s):
    """YYYY-MM-DD 계열 문자열 → date 또는 None."""
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------------------
# 추세 감지 — trend_watch.py 동일 알고리즘 (독립 복사)
# ---------------------------------------------------------------------------

def detect_exposure_trend(daily_exposure, source_label):
    """daily_exposure: [(date, int)] 날짜순 정렬 리스트.

    최신 W일 평균 vs 직전 W일 평균 비교.
    DROP_PCT 이상 감소 → DOWN. 데이터 부족 → UNKNOWN. 정상 → OK.

    반환: {"axis", "level", "what", "source", "detail", ...}
    """
    def _alert(level, what, detail=None):
        return {
            "axis": "상위노출",
            "level": level,
            "what": what,
            "source": source_label,
            "detail": detail,
        }

    if not daily_exposure:
        return _alert(UNKNOWN, "데이터 없음 — --live 또는 --fixture 필요")

    series = sorted(daily_exposure, key=lambda x: x[0])
    W = EXPOSURE_WINDOW_DAYS

    if len(series) < W:
        return _alert(
            UNKNOWN,
            f"데이터 {len(series)}일치뿐 — 주간 비교에 최소 {W}일 필요",
            {"days_available": len(series)},
        )

    recent_w = series[-W:]
    prev_w = series[-(W * 2):-W] if len(series) >= W * 2 else None

    recent_avg = sum(r[1] for r in recent_w) / len(recent_w)

    if not prev_w:
        return _alert(
            UNKNOWN,
            f"이전 주 데이터 없음 — 비교 불가. 최근 {W}일 평균: {recent_avg:.1f}개",
        )

    prev_avg = sum(r[1] for r in prev_w) / len(prev_w)

    if prev_avg == 0:
        return _alert(UNKNOWN, "이전 창 평균 0 — 나눗셈 불가(비교 생략)")

    drop_pct = (prev_avg - recent_avg) / prev_avg * 100

    if drop_pct >= EXPOSURE_DROP_PCT:
        what = (
            f"주간 평균 하락 {drop_pct:.0f}%: "
            f"{prev_w[0][0]}~{prev_w[-1][0]} 평균 {prev_avg:.1f}개 → "
            f"{recent_w[0][0]}~{recent_w[-1][0]} 평균 {recent_avg:.1f}개"
        )
        return _alert(
            DOWN,
            what,
            {"prev_avg": prev_avg, "recent_avg": recent_avg, "drop_pct": drop_pct},
        )

    return _alert(
        OK,
        f"주간 평균 유지 (이전 {prev_avg:.1f}개 → 최근 {recent_avg:.1f}개, -{drop_pct:.0f}%)",
    )


# ---------------------------------------------------------------------------
# 데이터 로드 — 실 시트 (read-only)
# ---------------------------------------------------------------------------

def load_exposure_from_sheet():
    """SPREADSHEET_ID + SERVICE_ACCOUNT_JSON 으로 '상위노출_이력' 탭 읽기.

    헤더: [날짜, 탭, 키워드, 노출영역, 통합순위]
    인덱스: 0=날짜, 1=탭(카테고리), 2=키워드, ...

    반환: (
        total_series: [(date, int)] or None,
        by_tab: {탭명: [(date, int)]} or {},
        source_label: str
    )
    """
    spreadsheet_id = os.environ.get("SPREADSHEET_ID", "").strip()
    svc_json = os.environ.get("SERVICE_ACCOUNT_JSON", "").strip()

    if not spreadsheet_id:
        return None, {}, "SPREADSHEET_ID env 미설정"
    if not svc_json:
        return None, {}, "SERVICE_ACCOUNT_JSON env 미설정"

    try:
        import gspread
    except ImportError as e:
        return None, {}, f"gspread 없음: {e}"

    try:
        # BOM 제거 (src/sheets.py 동일 패턴)
        if svc_json.startswith("﻿"):
            svc_json = svc_json[1:]
        creds_dict = json.loads(svc_json)
        gc = gspread.service_account_from_dict(creds_dict)
        ws = gc.open_by_key(spreadsheet_id).worksheet(ARCHIVE_TAB_NAME)
        rows = ws.get_all_values()
    except Exception as e:
        return None, {}, f"시트 접근 실패: {type(e).__name__}: {e}"

    if len(rows) < 2:
        return None, {}, f"'{ARCHIVE_TAB_NAME}' 탭 비어있음 (헤더만 또는 빈 탭)"

    # 날짜별 집계: 전체 + 탭별
    daily_total = defaultdict(int)
    daily_by_tab = defaultdict(lambda: defaultdict(int))

    for row in rows[1:]:
        if not row:
            continue
        d = _parse_date(row[0] if row else "")
        if d is None:
            continue
        daily_total[d] += 1
        tab_name = str(row[1]).strip() if len(row) > 1 else ""
        if tab_name:
            daily_by_tab[tab_name][d] += 1

    total_series = sorted(daily_total.items())
    by_tab_series = {
        tab: sorted(day_counts.items())
        for tab, day_counts in daily_by_tab.items()
    }

    n_days = len(total_series)
    n_rows = sum(v for _, v in total_series)
    source = f"'{ARCHIVE_TAB_NAME}' live read ({n_rows}건 / {n_days}일)"

    return (total_series if total_series else None), by_tab_series, source


# ---------------------------------------------------------------------------
# Fixture — 합성 데이터로 로직 검증 (--fixture)
# ---------------------------------------------------------------------------

def build_fixtures():
    """하락·정상·데이터부족 케이스 합성. 검증 목적."""
    today = date.today()

    def days_ago(n):
        return today - timedelta(days=n)

    W = EXPOSURE_WINDOW_DAYS

    # 하락 케이스: 이전 주 평균 12 → 최근 주 평균 8 (−33%)
    exposure_down = (
        [(days_ago(W * 2 - 1 - i), 12) for i in range(W)]
        + [(days_ago(W - 1 - i), 8) for i in range(W)]
    )

    # 정상 케이스: 이전 주 평균 10 → 최근 주 평균 9.5 (−5%, 임계 미달)
    exposure_ok = (
        [(days_ago(W * 2 - 1 - i), 10) for i in range(W)]
        + [(days_ago(W - 1 - i), 9 if i % 2 == 0 else 10) for i in range(W)]
    )

    # 데이터 부족 케이스: W-1 일치만 있어 UNKNOWN
    exposure_short = [(days_ago(i), 10) for i in range(W - 1)]

    return {
        "exposure_down": (exposure_down, "fixture/exposure_down"),
        "exposure_ok": (exposure_ok, "fixture/exposure_ok"),
        "exposure_short": (exposure_short, "fixture/exposure_short"),
    }


def run_fixture():
    """합성 fixture 로 로직 검증. 반환: (모두 통과 여부: bool, 보고 줄들: list)."""
    fx = build_fixtures()
    lines = ["[fixture 검증]"]
    passed = 0
    failed = 0

    checks = [
        ("노출 하락 케이스", detect_exposure_trend(*fx["exposure_down"]), DOWN),
        ("노출 정상 케이스", detect_exposure_trend(*fx["exposure_ok"]), OK),
        ("노출 데이터부족", detect_exposure_trend(*fx["exposure_short"]), UNKNOWN),
    ]

    for label, result, expected in checks:
        actual = result["level"]
        flag = "PASS" if actual == expected else "FAIL"
        if actual == expected:
            passed += 1
        else:
            failed += 1
        lines.append(f"  {flag} {label}: 기대={expected} 실제={actual} | {result['what']}")

    lines.append(f"\n  결과: {passed}통과 / {failed}실패 (총 {passed + failed})")
    return failed == 0, lines


# ---------------------------------------------------------------------------
# 메시지 조립
# ---------------------------------------------------------------------------

def build_console_report(overall_alert, tab_alerts):
    """콘솔 출력용 보고 문자열."""
    all_alerts = [overall_alert] + tab_alerts
    down_alerts = [a for a in all_alerts if a["level"] == DOWN]
    unknown_alerts = [a for a in all_alerts if a["level"] == UNKNOWN]

    lines = []
    if down_alerts:
        lines.append(f"[exposure_trend_alert] 하락 감지 — {_now_str()}")
        for a in down_alerts:
            label = a.get("tab", "전체")
            lines.append(f"  [하락] [{label}] {a['what']} | 출처: {a['source']}")
    for a in unknown_alerts:
        label = a.get("tab", "전체")
        lines.append(f"  [데이터없음] [{label}] {a['what']}")
    if not down_alerts and not unknown_alerts:
        lines.append(f"[exposure_trend_alert] 이상 없음 ({_now_str()})")
    elif not down_alerts:
        lines.append(f"[exposure_trend_alert] 하락 없음 ({_now_str()})")
    return "\n".join(lines)


def build_telegram_message(overall_alert, tab_alerts):
    """텔레그램 발송 문구. DOWN 없으면 None (조용)."""
    all_alerts = [overall_alert] + tab_alerts
    down_alerts = [a for a in all_alerts if a["level"] == DOWN]
    if not down_alerts:
        return None

    lines = ["📉 상위노출 감소 알림", ""]
    for a in down_alerts:
        label = a.get("tab", "전체")
        lines.append(f"[{label}] {a['what']}")
        lines.append(f"  출처: {a['source']}")
        lines.append("")
    lines.append(f"(읽기 전용 · {_now_str()} · exposure_trend_alert.py)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 텔레그램 발송 — src.notify.send_report 재사용 (--send 시에만)
# ---------------------------------------------------------------------------

def _send_telegram_alert(text):
    """src.notify.send_report 를 재사용. 실패해도 예외 없음(비차단)."""
    try:
        # 실행 위치(scripts/)와 무관하게 repo 루트를 sys.path 에 추가
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if repo_root not in sys.path:
            sys.path.insert(0, repo_root)
        from src.notify import send_report  # noqa: PLC0415
        send_report(text)
        return True
    except Exception as e:
        print(f"[exposure_trend_alert] 발송 실패 (비차단): {type(e).__name__}: {e}")
        return False


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    global EXPOSURE_DROP_PCT, EXPOSURE_WINDOW_DAYS  # noqa: PLW0603 — --drop-pct/--window-days 오버라이드용

    ap = argparse.ArgumentParser(
        description=(
            "상위노출 개수 감소 감지 — "
            "이전 주 평균 대비 최근 주 평균 하락 >= 임계시 알림 (기본 dry-run)"
        )
    )
    ap.add_argument(
        "--fixture",
        action="store_true",
        help="합성 fixture 로 로직 검증 (시트 접근 없음)",
    )
    ap.add_argument(
        "--live",
        action="store_true",
        help="실 시트 read-only (SPREADSHEET_ID + SERVICE_ACCOUNT_JSON 필요)",
    )
    ap.add_argument(
        "--send",
        action="store_true",
        help="하락 감지 시 텔레그램 발송 (TELEGRAM_BOT_TOKEN/CHAT_ID 필요)",
    )
    ap.add_argument(
        "--drop-pct",
        type=float,
        default=EXPOSURE_DROP_PCT,
        help=f"하락 임계 %% (기본 {EXPOSURE_DROP_PCT})",
    )
    ap.add_argument(
        "--window-days",
        type=int,
        default=EXPOSURE_WINDOW_DAYS,
        help=f"비교 창 일수 (기본 {EXPOSURE_WINDOW_DAYS})",
    )
    args = ap.parse_args()

    # 임계값 오버라이드
    EXPOSURE_DROP_PCT = args.drop_pct
    EXPOSURE_WINDOW_DAYS = args.window_days

    # --- fixture 모드 ---
    if args.fixture:
        passed, lines = run_fixture()
        for line in lines:
            print(line)
        return 0 if passed else 1

    # --- 데이터 로드 ---
    total_series, by_tab_series, source_label = None, {}, "데이터 없음 — --live 필요"

    if args.live:
        total_series, by_tab_series, source_label = load_exposure_from_sheet()
        print(f"[exposure_trend_alert] {source_label}")

    # --- 추세 감지 ---
    overall_alert = detect_exposure_trend(total_series, source_label)

    tab_alerts = []
    for tab_name, series in sorted(by_tab_series.items()):
        tab_alert = detect_exposure_trend(series, f"{source_label}/{tab_name}")
        tab_alert["tab"] = tab_name
        tab_alerts.append(tab_alert)

    # --- 콘솔 출력 ---
    print(build_console_report(overall_alert, tab_alerts))

    # --- 발송 (--send 시에만) ---
    if args.send:
        msg = build_telegram_message(overall_alert, tab_alerts)
        if msg:
            _send_telegram_alert(msg)
        else:
            print("[exposure_trend_alert] 하락 없음 → 발송 안 함.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
