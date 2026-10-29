"""대체 노출 비포·애프터 세기 (AI 없음 · 새 검색 0 · 시트 읽기 0).

한 회차 산출물(row-trace jsonl)만 읽어, 같은 회차 안에서
  비포 = 지금 판정(K)으로 상위노출인 줄
  애프터 = 비포 + 'K 는 미노출·누락·삭제인데 같은 검색 화면에 우리 다른 글이 떠 있는 줄'
을 탭별 · 전체로 센다. 대체 줄 표(키워드 · 시트 그 줄 글 · 대신 뜬 글 · 구좌 · 순위)도 함께.

쓰는 법:
    python scripts/count_substitute_before_after.py <row-trace.jsonl> [--substitute <substitute.jsonl>] [--out 결과.json]

  - row-trace 에 substitute_* 칸이 없으면(고침 전 회차) '대체 칸 없음 — 셀 수 없음' 으로 끝낸다(0 으로 치지 않음).
  - --substitute 를 주면 대체 줄 표에 대신 뜬 글 주소·구좌·순위를 낱낱이 싣는다.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

EXPOSED = {"AB", "스마트블록", "인기글", "중복노출", "중복노출(AB)", "중복노출(스마트블록)", "중복노출(인기글)"}
NOT_FOUND = {"미노출", "누락", "삭제"}


def _read_jsonl(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def count(trace_rows: list[dict], substitute_rows: list[dict] | None = None) -> dict:
    rows = [r for r in trace_rows if r.get("status") == "write_ready"]
    if rows and not any("substitute_scanned" in r for r in rows):
        return {"error": "대체 칸 없음 — 셀 수 없음 (고침 전 회차이거나 SUBSTITUTE_SCAN=0)"}
    sub_by = {(s.get("tab"), s.get("row")): s for s in (substitute_rows or [])}
    per_tab: dict = defaultdict(lambda: {"줄": 0, "비포": 0, "애프터": 0, "못찾은줄": 0, "대체": 0, "맞대기실패": 0,
                                         "대체_확인못함": 0})
    table = []
    for r in rows:
        t = per_tab[r.get("tab", "")]
        base = r.get("new_K_base") or ""
        t["줄"] += 1
        exposed = base in EXPOSED
        failed = bool(r.get("substitute_error"))
        found = (not exposed) and base in NOT_FOUND and int(r.get("substitute_count") or 0) > 0
        # 2026-10-30 지적 2: 맞대기 오류 · 옛 글 출처 못 읽음(부분 자료)으로 찾은 대체는 완전 확인이 아니다 →
        # '대체' · '애프터' 에 넣지 않고 '대체_확인못함' 으로 따로 센다(맞대기실패에도 들어감).
        substituted = found and not failed
        if exposed:
            t["비포"] += 1
        if base in NOT_FOUND:
            t["못찾은줄"] += 1
        if failed:
            t["맞대기실패"] += 1
        if found and failed:
            t["대체_확인못함"] += 1
        if substituted:
            t["대체"] += 1
            sub = sub_by.get((r.get("tab"), r.get("row"))) or {}
            for h in sub.get("hits") or [{"url": "", "area": "", "rank": None, "cafe_rank": None, "source": ""}]:
                table.append({
                    "탭": r.get("tab", ""), "행": r.get("row"), "키워드": r.get("keyword", ""),
                    "K": base, "시트 그 줄 글": r.get("original_link", ""),
                    "대신 뜬 글": h.get("url", ""), "구좌": h.get("area", ""),
                    "순위": h.get("cafe_rank") or h.get("rank"), "출처": h.get("source", ""),
                    "칸 글자": r.get("substitute_cell", ""),
                })
        if exposed or substituted:
            t["애프터"] += 1
    total = {k: sum(v[k] for v in per_tab.values())
             for k in ("줄", "비포", "애프터", "못찾은줄", "대체", "맞대기실패", "대체_확인못함")}

    def rate(d):
        n = d["줄"] or 1
        return {**d, "비포 비율": round(d["비포"] / n, 4), "애프터 비율": round(d["애프터"] / n, 4)}

    return {
        "전체": rate(total),
        "탭별": {k: rate(v) for k, v in sorted(per_tab.items())},
        "대체 줄 표": table,
        "읽은 줄": len(trace_rows),
        "센 줄(write_ready)": len(rows),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("trace")
    ap.add_argument("--substitute", default="")
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    res = count(_read_jsonl(a.trace), _read_jsonl(a.substitute) if a.substitute else None)
    text = json.dumps(res, ensure_ascii=False, indent=1)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    t = res.get("전체")
    if t:
        print(f"전체 {t['줄']}줄 · 비포 상위노출 {t['비포']} ({t['비포 비율']:.1%}) → 애프터 {t['애프터']} "
              f"({t['애프터 비율']:.1%}) · 못 찾은 줄 {t['못찾은줄']} 중 대체 {t['대체']} · 맞대기 실패 {t['맞대기실패']}"
              f" (그중 찾았으나 확인 못 함 {t['대체_확인못함']} — 애프터에 안 넣음)")
        for tab, d in res["탭별"].items():
            print(f"  {tab}: {d['줄']}줄 · 비포 {d['비포']} ({d['비포 비율']:.1%}) → 애프터 {d['애프터']} ({d['애프터 비율']:.1%})")
    else:
        print(res["error"])
        return 2
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
