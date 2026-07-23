# -*- coding: utf-8 -*-
"""발행 검수 진단 — 왜 대상이 6건뿐이고 왜 전건 불합격인가. 읽기 전용(시트 안 씀).

임시 진단용. 원인 확정 후 지운다.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from scripts import balhaeng_geomsu as G  # noqa: E402
from src.sheets import SheetsClient  # noqa: E402


def main() -> int:
    sc = SheetsClient(os.environ["SPREADSHEET_ID"], os.environ["SERVICE_ACCOUNT_JSON"])
    탭들 = [ws for ws in sc.spreadsheet.worksheets()
            if "카외" in ws.title and not any(x in ws.title for x in G.제외탭)]
    print(f"=== 카외 탭 {len(탭들)}개 ===")
    for ws in 탭들:
        rows = ws.get_all_values()
        if not rows:
            print(f"[{ws.title}] 빈 탭")
            continue
        h = [x.strip() for x in rows[0]]
        idx = {n: i for i, n in enumerate(h)}
        링크수 = 분류있음 = 0
        분류샘플 = []
        for row in rows[1:]:
            링크 = next((c.strip() for c in row if isinstance(c, str)
                        and c.strip().startswith("http") and G.CAFE_LINK.search(c)), None)
            if not 링크:
                continue
            링크수 += 1
            i = idx.get("키워드 분류")
            v = row[i].strip() if i is not None and i < len(row) else ""
            if G.단계뽑기(v) is not None:
                분류있음 += 1
            elif len(분류샘플) < 5:
                kw = row[idx["키워드"]] if "키워드" in idx and idx["키워드"] < len(row) else "?"
                분류샘플.append(f"{kw}→{v!r}")
        print(f"\n[{ws.title}] 전체행{len(rows)-1} · 카페링크{링크수} · 단계읽힘{분류있음}")
        print(f"  헤더: {' | '.join(h)}")
        if 분류샘플:
            print(f"  단계 못읽은 예: {', '.join(분류샘플)}")

    print("\n=== 검수 대상 채점 상세 ===")
    대상 = G.대상읽기(sc, int(os.environ.get("GEOMSU_LIMIT") or "150"))
    for i, t in enumerate(대상, 1):
        try:
            post = G.한건수집(t)
        except Exception as e:
            print(f"[{i}] {t['keyword']} 수집예외 {type(e).__name__}: {e}")
            continue
        if post.get("_실패"):
            print(f"[{i}] {t['keyword']} 수집실패: {post['_실패']} — {t['url']}")
            continue
        r = G.검수기.검수(post)
        m = r["측정"]
        print(f"\n[{i}] {t['keyword']} (단계{t['stage']}) → {r['판정']}  {t['url']}")
        print(f"    글자{m['chars']}·줄{m['lines']}·키워드{m['kw_body']}"
              f"·댓글{m['댓글수']}·사진{m['photos']}")
        for d in r["지적"]:
            print(f"    {d['등급']}/{d.get('축', '?')}: {d['내용']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
