"""T-M18 디벨롭: 정확도 최악 root cause 종합 진단.

입력: .harness/comparison-500-after-fix.json (사장님 수기 vs parser 결과 500행 비교)
출력: mismatch case 별 분류 + 수치 + 영향 ↑ case 식별.

비교 컬럼:
- area_match: K (노출영역) 일치 여부
- L_match: L (통합탭 순위) 일치 여부
- M_match: M (카페구좌순위) 일치 여부
- J_match: J (지식인탭) 일치 여부
"""
from __future__ import annotations
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def main() -> int:
    p = Path(__file__).resolve().parent.parent / ".harness" / "comparison-500-after-fix.json"
    if not p.exists():
        print(f"❌ {p} 없음")
        return 1
    rows = json.load(open(p, encoding="utf-8"))

    total = len(rows)
    print(f"=== comparison-500-after-fix.json 종합 진단 ({total} 행) ===\n")

    # 일치/불일치 통계
    area_match = sum(1 for r in rows if r.get("area_match"))
    L_match = sum(1 for r in rows if r.get("L_match"))
    M_match = sum(1 for r in rows if r.get("M_match"))
    J_match = sum(1 for r in rows if r.get("J_match"))
    all_match = sum(1 for r in rows if r.get("area_match") and r.get("L_match") and r.get("M_match") and r.get("J_match"))

    print(f"전체 4 컬럼 일치: {all_match} / {total} = {all_match/total*100:.1f}%")
    print(f"K (노출영역) 일치: {area_match} / {total} = {area_match/total*100:.1f}%")
    print(f"L (통합탭 순위) 일치: {L_match} / {total} = {L_match/total*100:.1f}%")
    print(f"M (카페구좌순위) 일치: {M_match} / {total} = {M_match/total*100:.1f}%")
    print(f"J (지식인) 일치: {J_match} / {total} = {J_match/total*100:.1f}%")
    print()

    # K mismatch 패턴 분류 (사장님 수기 m_area → parser p_area)
    k_pattern: Counter = Counter()
    k_case_samples: dict = defaultdict(list)
    for r in rows:
        if not r.get("area_match"):
            m = r.get("m_area") or "(빈칸)"
            p_ = r.get("p_area") or "(빈칸)"
            key = f"{m} → {p_}"
            k_pattern[key] += 1
            if len(k_case_samples[key]) < 3:
                k_case_samples[key].append({
                    "kw": r.get("kw"),
                    "link": (r.get("link") or "")[:80],
                })

    print(f"=== K (노출영역) mismatch 패턴 분류 ===")
    print(f"형식: 사장님 수기 → parser 결과 | 행 수\n")
    for key, count in k_pattern.most_common():
        print(f"  {key:30}  {count} 행")
        for s in k_case_samples[key][:2]:
            print(f"      kw={s['kw']!r:30}  link={s['link']}")
    print()

    # 영역별 mismatch case 분류
    print(f"=== mismatch case 종합 분류 ===\n")

    # case 1: 사장님 = AB/인기글, parser = 미노출 (false negative)
    case_false_neg = [r for r in rows if r.get("m_area") in ("AB", "인기글") and r.get("p_area") == "미노출"]
    # case 2: 사장님 = 미노출, parser = AB/인기글 (false positive)
    case_false_pos = [r for r in rows if r.get("m_area") in ("미노출", "", None) and r.get("p_area") in ("AB", "인기글")]
    # case 3: AB ↔ 인기글 cross (분류 잘못)
    case_class_swap = [r for r in rows if (r.get("m_area") == "AB" and r.get("p_area") == "인기글") or (r.get("m_area") == "인기글" and r.get("p_area") == "AB")]
    # case 4: 사장님 = 빈칸 (작업 미진행) — 영향 다름
    case_empty_m = [r for r in rows if r.get("m_area") in ("", None)]

    print(f"Case 1 - false negative (사장님 노출 → parser 미노출): {len(case_false_neg)}")
    print(f"Case 2 - false positive (사장님 미노출 → parser 노출): {len(case_false_pos)}")
    print(f"Case 3 - AB↔인기글 cross (분류 잘못): {len(case_class_swap)}")
    print(f"Case 4 - 사장님 K 빈칸 (검증 X): {len(case_empty_m)}")
    print()

    # L/M mismatch 만 (K 는 일치) — 순위 정확도 문제
    L_only = [r for r in rows if r.get("area_match") and not r.get("L_match")]
    M_only = [r for r in rows if r.get("area_match") and not r.get("M_match")]
    print(f"Case 5 - K 일치하지만 L 다름: {len(L_only)} (순위 차이 또는 시점)")
    print(f"Case 6 - K 일치하지만 M 다름: {len(M_only)} (M 계산 fix 부작용 가능)")
    print()

    # L/M 분리 fix 부작용 검출 — 사장님 m_M ≠ m_L (사장님 컨벤션 L=M 인지 분리인지)
    L_eq_M = sum(1 for r in rows if r.get("m_L") == r.get("m_M") and r.get("m_L") is not None)
    L_ne_M = sum(1 for r in rows if r.get("m_L") != r.get("m_M") and r.get("m_L") is not None and r.get("m_M") is not None)
    M_null_L_some = sum(1 for r in rows if r.get("m_M") is None and r.get("m_L") is not None)
    print(f"=== 사장님 L vs M 컨벤션 분석 ===")
    print(f"L == M (둘 다 있음): {L_eq_M}")
    print(f"L ≠ M (둘 다 있음): {L_ne_M}")
    print(f"L 있음 + M 빈칸: {M_null_L_some}")
    print()

    # false positive sample (D-020 Case A 검증)
    if case_false_pos:
        print(f"=== Case 2 (false positive) sample 5 ===")
        for r in case_false_pos[:5]:
            print(f"  kw={r.get('kw')!r:30}  link={(r.get('link') or '')[:80]}")
            print(f"      parser: K={r.get('p_area')}, L={r.get('p_L')}, M={r.get('p_M')}, J={r.get('p_J')}")
            print(f"      사장님: K={r.get('m_area')!r}, L={r.get('m_L')}, M={r.get('m_M')}, J={r.get('m_J')}")
        print()

    # false negative sample (D-020 Case B 후보)
    if case_false_neg:
        print(f"=== Case 1 (false negative) sample 5 ===")
        for r in case_false_neg[:5]:
            print(f"  kw={r.get('kw')!r:30}  link={(r.get('link') or '')[:80]}")
            print(f"      사장님: K={r.get('m_area')}, L={r.get('m_L')}, M={r.get('m_M')}")
            print(f"      parser: K={r.get('p_area')}, L={r.get('p_L')}, M={r.get('p_M')}")
        print()

    # cross sample (분류 swap)
    if case_class_swap:
        print(f"=== Case 3 (AB↔인기글) sample 5 ===")
        for r in case_class_swap[:5]:
            print(f"  kw={r.get('kw')!r:30}  link={(r.get('link') or '')[:80]}")
            print(f"      사장님={r.get('m_area')}, parser={r.get('p_area')}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
