"""키워드 주변 정보 받기 — 네이버 공식 검색 API 부분 (2026-10-25 · ⑧ 디테일 코벤 창 · ④ 빈틈지도 창이 같이 씀).

키워드마다 블로그 · 카페 · 지식인 · 쇼핑 상위 30개와 검색 결과 수를 받아 JSON 한 파일로 낸다.
기존 코드는 부르지 않는 단독 파일이다(이 저장소에만 공식 검색 열쇠가 있어서 여기 둔다).
네이버 요청은 GitHub 서버에서만 나간다 — 집 PC 에서 부르면 멈춘다.

키: NAVER_OPENAPI_CLIENT_ID / NAVER_OPENAPI_CLIENT_SECRET (src/jisikin_collect.py 와 같은 열쇠).
상한: 한 번에 키워드 10개 · 네이버 요청 40번.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
API = "https://openapi.naver.com/v1/search/{}.json"
# 출처 이름 → API 이름. 표의 칸 순서도 이 순서다.
SOURCES = {"블로그": "blog", "카페": "cafearticle", "지식인": "kin", "쇼핑": "shop"}
DISPLAY = 30
MAX_KEYWORDS = 10
MAX_REQUESTS = 40
DEFAULT_KEYWORDS = "딕션관리기,식스칙구균제,메아리셋,열보초크림"
_TAG = re.compile(r"<[^>]+>")


def clean(text: str) -> str:
    return html.unescape(_TAG.sub("", text or "")).strip()


def item_row(source: str, it: dict) -> dict:
    """API 항목 → 우리 칸. 원래 칸도 '원문'에 그대로 남긴다(거르기는 다음 단계)."""
    row = {"제목": clean(it.get("title", "")), "주소": it.get("link", ""),
           "요약": clean(it.get("description", ""))}
    if source == "블로그":
        row.update(날짜=it.get("postdate", ""), 블로그=it.get("bloggername", ""))
    elif source == "카페":
        row.update(카페이름=it.get("cafename", ""), 카페주소=it.get("cafeurl", ""))
    elif source == "쇼핑":
        row.update(판매처=it.get("mallName", ""), 최저가=it.get("lprice", ""), 최고가=it.get("hprice", ""),
                   브랜드=it.get("brand", ""), 제조사=it.get("maker", ""),
                   분류=" > ".join(x for x in (it.get(f"category{i}", "") for i in range(1, 5)) if x))
    row["원문"] = it
    return row


def fetch(source: str, keyword: str, cid: str, csec: str, opener=urllib.request.urlopen) -> dict:
    url = API.format(SOURCES[source]) + "?" + urllib.parse.urlencode(
        {"query": keyword, "display": DISPLAY, "start": 1, "sort": "sim"})
    req = urllib.request.Request(url, headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csec})
    out = {"요청주소": url, "받은시각": datetime.now(KST).isoformat(timespec="seconds")}
    try:
        with opener(req, timeout=20) as r:
            body = json.loads(r.read().decode("utf-8"))
        items = body.get("items") or []
        out.update(상태="성공", 검색결과수=body.get("total"), 개수=len(items),
                   항목들=[item_row(source, it) for it in items])
    except urllib.error.HTTPError as e:
        out.update(상태=f"실패 HTTP {e.code}", 까닭=e.read().decode("utf-8", "replace")[:300], 개수=0, 항목들=[])
    except Exception as e:  # 연결 오류도 칸에 남기고 다음 키워드로 간다
        out.update(상태="실패", 까닭=f"{type(e).__name__}: {e}"[:300], 개수=0, 항목들=[])
    return out


def run(keywords: list[str], cid: str, csec: str, opener=urllib.request.urlopen, pause: float = 0.2) -> dict:
    if len(keywords) > MAX_KEYWORDS:
        raise SystemExit(f"키워드가 {len(keywords)}개 — 한 번에 {MAX_KEYWORDS}개까지만 받습니다")
    if len(keywords) * len(SOURCES) > MAX_REQUESTS:
        raise SystemExit("네이버 요청 상한(40번)을 넘습니다")
    rows = []
    for kw in keywords:
        per = {}
        for source in SOURCES:
            per[source] = fetch(source, kw, cid, csec, opener)
            time.sleep(pause)
        rows.append({"키워드": kw, "출처": per})
    return {"받은시각": datetime.now(KST).isoformat(timespec="seconds"),
            "출처설명": "네이버 공식 검색 API(openapi.naver.com/v1/search) · 정확도순 상위 30개",
            "키워드들": rows}


def count_table(result: dict) -> str:
    head = "| 키워드 | " + " | ".join(SOURCES) + " |"
    lines = [head, "|" + "---|" * (len(SOURCES) + 1)]
    for row in result["키워드들"]:
        cells = []
        for s in SOURCES:
            d = row["출처"][s]
            cells.append(f"{d['개수']} (전체 {d.get('검색결과수')})" if d["상태"] == "성공" else d["상태"])
        lines.append(f"| {row['키워드']} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", default=os.environ.get("KEYWORDS") or DEFAULT_KEYWORDS,
                    help="쉼표로 가른 키워드")
    ap.add_argument("--out-dir", default="out")
    a = ap.parse_args(argv)
    if os.environ.get("GITHUB_ACTIONS") != "true":
        print("멈춤: 네이버 요청은 GitHub 서버에서만 보냅니다(집 PC 금지)")
        return 2
    cid = os.environ.get("NAVER_OPENAPI_CLIENT_ID", "")
    csec = os.environ.get("NAVER_OPENAPI_CLIENT_SECRET", "")
    if not cid or not csec:
        print("멈춤: NAVER_OPENAPI_CLIENT_ID/SECRET 이 이 실행에 없습니다")
        return 2
    keywords = [k.strip() for k in a.keywords.split(",") if k.strip()]
    result = run(keywords, cid, csec)
    Path(a.out_dir).mkdir(parents=True, exist_ok=True)
    name = f"키워드주변_{datetime.now(KST).strftime('%Y%m%d-%H%M')}.json"
    (Path(a.out_dir) / name).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    table = count_table(result)
    print(name)
    print(table)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"### {name}\n\n{table}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
