"""키워드 주변 정보 받기 — 네이버 공식 검색 API 부분 (2026-10-25 · ⑧ 디테일 코벤 창 · ④ 빈틈지도 창이 같이 씀).

키워드마다 블로그 · 카페 · 지식인 상위 30개와(쇼핑은 API 종료로 받지 않음) 검색 결과 수를 받아 JSON 한 파일로 낸다.
기존 코드는 부르지 않는 단독 파일이다(이 저장소에만 공식 검색 열쇠가 있어서 여기 둔다).
네이버 요청은 GitHub 서버에서만 나간다 — 집 PC 에서 부르면 멈춘다.

키: NAVER_OPENAPI_CLIENT_ID / NAVER_OPENAPI_CLIENT_SECRET (src/jisikin_collect.py 와 같은 열쇠).
상한: 한 번에 키워드 10개 · 네이버 요청 40번(키워드당 3번).
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
SOURCES = {"블로그": "blog", "카페": "cafearticle", "지식인": "kin"}
# 쇼핑: 네이버가 쇼핑 검색 API 를 2026-07-31 에 끝냄(대체 API 없음) → 요청 0번. 정상 0건과 구별되게 '받지 않음'으로 남긴다.
# 쇼핑은 통합검색 화면 읽기(keyword_surround.py '쇼핑(화면)')로 받는다. 진단용 PROBES 는 지우지 않고 --probe 로만 돈다.
_API_NAME = {**SOURCES, "쇼핑": "shop"}  # fetch 단독 호출(시험·진단)용 — run 은 SOURCES 만 돈다
ENDED = {"쇼핑": "받지 않음 — 네이버 쇼핑 검색 API 종료(2026-07-31, 공지 32564)"}
ALL_CELLS = tuple(SOURCES) + tuple(ENDED)
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
    url = API.format(_API_NAME[source]) + "?" + urllib.parse.urlencode(
        {"query": keyword, "display": DISPLAY, "start": 1, "sort": "sim"})
    req = urllib.request.Request(url, headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csec})
    out = {"요청주소": url, "받은시각": datetime.now(KST).isoformat(timespec="seconds")}
    try:
        with opener(req, timeout=20) as r:
            body = json.loads(r.read().decode("utf-8"))
        if not isinstance(body, dict):
            out.update(상태="실패 items 없음", 까닭=f"200 응답이 JSON 객체가 아님({type(body).__name__})"[:300], 개수=0, 항목들=[])
        elif body.get("errorCode") or body.get("errorMessage"):  # 200 이어도 오류 표시가 있으면 items 모양과 상관없이 실패
            out.update(상태="실패 오류 응답", 까닭=f"200 응답인데 오류 표시: errorCode={body.get('errorCode')} errorMessage={body.get('errorMessage')}"[:300], 개수=0, 항목들=[])
        elif not isinstance(body.get("items"), list):  # 오류 표시도 없는데 items 칸이 없거나 목록이 아니면 정상 0건이 아니라 실패
            out.update(상태="실패 items 없음", 까닭=f"200 응답인데 items 칸이 없거나 목록이 아님(items={type(body.get('items')).__name__})"[:300], 개수=0, 항목들=[])
        else:
            items = body["items"]
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
        for name, why in ENDED.items():
            per[name] = {"요청주소": "", "받은시각": datetime.now(KST).isoformat(timespec="seconds"),
                         "상태": "받지 않음", "까닭": why, "개수": 0, "항목들": []}
        rows.append({"키워드": kw, "출처": per})
    return {"받은시각": datetime.now(KST).isoformat(timespec="seconds"),
            "출처설명": "네이버 공식 검색 API(openapi.naver.com/v1/search) · 정확도순 상위 30개",
            "키워드들": rows}


def count_table(result: dict) -> str:
    head = "| 키워드 | " + " | ".join(ALL_CELLS) + " |"
    lines = [head, "|" + "---|" * (len(ALL_CELLS) + 1)]
    for row in result["키워드들"]:
        cells = []
        for s in ALL_CELLS:
            d = row["출처"][s]
            cells.append(f"{d['개수']} (전체 {d.get('검색결과수')})" if d["상태"] == "성공" else d["상태"])
        lines.append(f"| {row['키워드']} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


PROBES = [  # 쇼핑 404(SE05) 원인 가르기용 — 같은 열쇠로 주소·매개변수만 바꿔 본다(요청 8번)
    ("쇼핑 현재와 같음", "shop.json", {"display": 30, "start": 1, "sort": "sim"}),
    ("쇼핑 query만", "shop.json", {}),
    ("쇼핑 display=10", "shop.json", {"display": 10, "start": 1, "sort": "sim"}),
    ("쇼핑 sort=date", "shop.json", {"display": 10, "start": 1, "sort": "date"}),
    ("쇼핑 xml", "shop.xml", {"display": 10, "start": 1, "sort": "sim"}),
    ("대조 블로그", "blog.json", {"display": 10, "start": 1, "sort": "sim"}),
    ("대조 웹문서", "webkr.json", {"display": 10}),
    ("대조 백과", "encyc.json", {"display": 10}),
]


def probe(keyword: str, cid: str, csec: str, opener=urllib.request.urlopen) -> list[dict]:
    """쇼핑이 왜 404 인지 가르는 진단. 열쇠 값은 찍지 않는다."""
    res = []
    for name, path, extra in PROBES:
        url = "https://openapi.naver.com/v1/search/" + path + "?" + urllib.parse.urlencode({"query": keyword, **extra})
        req = urllib.request.Request(url, headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csec})
        try:
            with opener(req, timeout=20) as r:
                code, text = r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            code, text = e.code, e.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            code, text = 0, f"{type(e).__name__}: {e}"
        res.append({"이름": name, "주소": url, "상태": code, "앞글": re.sub(r"\s+", " ", text)[:160]})
        time.sleep(0.2)
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="쇼핑 404 원인 진단(요청 8번)")
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
    if a.probe:
        for r in probe(keywords[0], cid, csec):
            print(f"{r['상태']} | {r['이름']} | {r['주소'].split('?')[0]} | {r['앞글']}")
        return 0
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
