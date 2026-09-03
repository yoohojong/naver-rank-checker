# -*- coding: utf-8 -*-
"""고친 자리를 하나씩 **되돌려 놓고** 검사가 실제로 빨개지는지 본다.

초록불이 '안 봤다'는 뜻인 사고가 이 저장소에 있었다(2026-08-28). 그래서 새 관문은
반드시 이렇게 확인한다 — 검사 자체를 시험한다.

    python tests/_돌연변이_확인.py

일회용 도구다. 원본은 매번 되돌려 놓는다(finally).
"""
import pathlib
import subprocess
import sys

뿌리 = pathlib.Path(__file__).resolve().parents[1]

# (이름, 파일, 되돌릴 것: 지금글자 → 옛글자, 빨개져야 하는 검사)
돌연변이 = [
    ("①워치독 연속실패: 'success' 로 끊던 것을 'failure' 만 세던 옛 셸로",
     ".github/workflows/rank-check-watchdog.yml",
     ('            [ -z "$c" ] && continue\n'
      '            [ "$c" = "success" ] && break\n'
      '            case "$c" in\n'
      '              failure|cancelled|timed_out|startup_failure) streak=$((streak+1)) ;;\n'
      '            esac\n'),
     '            [ "$c" = "failure" ] && streak=$((streak+1)) || break\n',
     "tests/unit/test_워치독_연속실패.py"),

    ("②보류_한계: 5시간 → 옛 2시간",
     "scripts/가동확인.py",
     "보류_한계 = timedelta(hours=5)", "보류_한계 = timedelta(hours=2)",
     "tests/unit/test_가동확인.py"),

    ("④가동확인 cron: 6시간마다 → 옛 하루 1회",
     ".github/workflows/가동확인.yml",
     "    - cron: '0 0,6,12,18 * * *'", "    - cron: '0 0 * * *'",
     "tests/unit/test_가동확인.py"),

    ("④정상일 때 침묵: 안 돈 회차만 알리던 것을 '늘 보낸다'로",
     "scripts/가동확인.py",
     # ★_결측_설명 에도 똑같은 세 줄이 있다 — build_report 쪽 주석까지 붙여 못 박는다.
     '    if not 빠짐:\n        return ""\n    if len(빠짐) == len(결과):\n'
     '        # 하루치가 통째로 빈 날은',
     '    if not 빠짐:\n        return "🟢 상노 점검 지난 하루: 4번 중 4번 정상"\n'
     '    if len(빠짐) == len(결과):\n        # 하루치가 통째로 빈 날은',
     "tests/unit/test_가동확인.py"),

    ("④같은 회차 두 번 알림 막기 제거",
     "scripts/가동확인.py",
     '    return {r["회차"] for r in 이번\n'
     '            if r["상태"] == 안돎 and 직전.get(r["시작"]) != 안돎}',
     '    return {r["회차"] for r in 이번 if r["상태"] == 안돎}',
     "tests/unit/test_가동확인.py"),

    ("③자가치유 시간한계: 워크플로 파일 읽기 → 옛 env TIMEOUT_MIN 만",
     "scripts/자가치유.py",
     "    if env값 > 0:\n        return env값\n    return _워크플로가_밝힌_한계분()",
     "    return env값",
     "tests/unit/test_자가치유.py"),

    ("③weekly-digest 시간 한계 삭제",
     ".github/workflows/weekly-digest.yml",
     "    timeout-minutes: 30\n", "",
     "tests/unit/test_자가치유.py"),

    ("⑤RUN_STATUS 안 읽기 → 옛 '시작 전 중단' 한 문구",
     "scripts/send_telegram_summary.py",
     "            return _결과없음(ts, run_status)",
     '            return f"❌ 상노체크 {ts} · 점검 실패(시작 전 중단) — 다음 점검에 자동 재시도"',
     "tests/unit/test_send_telegram_summary.py"),

    ("⑤RUN_STATUS 배선 끊기(워크플로)",
     ".github/workflows/rank-check.yml",
     "          RUN_STATUS: ${{ steps.run_cycle.outcome }}\n          # ★2026-09-03",
     "          # ★2026-09-03",
     "tests/unit/test_send_telegram_summary.py"),

    ("⑥같은 회차 중복 문자 막기 제거",
     "scripts/send_telegram_summary.py",
     "        if 이_회차에_이미_보고했나():\n            return 0\n", "",
     "tests/unit/test_send_telegram_summary.py"),

    ("⑥gh 인증 배선 끊기(워크플로)",
     ".github/workflows/rank-check.yml",
     "          GH_TOKEN: ${{ github.token }}\n          GH_REPO: ${{ github.repository }}\n"
     "          PYTHONIOENCODING: 'utf-8'\n        run: |\n"
     "          ./.venv/bin/python -u scripts/send_telegram_summary.py || true",
     "          PYTHONIOENCODING: 'utf-8'\n        run: |\n"
     "          ./.venv/bin/python -u scripts/send_telegram_summary.py || true",
     "tests/unit/test_send_telegram_summary.py"),
]


def main() -> int:
    결과 = []
    for 이름, 파일, 지금, 옛것, 검사 in 돌연변이:
        p = 뿌리 / 파일
        원본 = p.read_text(encoding="utf-8")
        if 지금 not in 원본:
            결과.append((이름, "심을 자리를 못 찾음(코드가 바뀌었다)", None))
            continue
        try:
            p.write_text(원본.replace(지금, 옛것, 1), encoding="utf-8")
            r = subprocess.run([sys.executable, "-m", "pytest", 검사, "-q", "--no-header",
                                "-p", "no:cacheprovider"],
                               cwd=str(뿌리), capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
        finally:
            p.write_text(원본, encoding="utf-8")
        빨감 = r.returncode != 0
        꼬리 = [L for L in (r.stdout or "").splitlines() if " passed" in L or " failed" in L]
        결과.append((이름, "🔴 빨개짐" if 빨감 else "🟢 그냥 통과(관문이 안 본다!)",
                     꼬리[-1] if 꼬리 else ""))

    print("\n=== 일부러 망가뜨렸을 때 검사가 빨개지나 ===")
    구멍 = 0
    for 이름, 판정, 꼬리 in 결과:
        print(f"{판정:<28} {이름}")
        if 꼬리:
            print(f"{'':<28}   {꼬리.strip()}")
        if not 판정.startswith("🔴"):
            구멍 += 1
    print(f"\n안 잡힌 자리: {구멍}개")
    return 1 if 구멍 else 0


if __name__ == "__main__":
    sys.exit(main())
