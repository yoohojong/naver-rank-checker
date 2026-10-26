"""욕구 검색어의 달마다 검색 흐름 받기 — 네이버 데이터랩 검색어 트렌드(공식 API).

2026-10-26 노력 욕구 창 · 사장님 "같은 프로그램인데 … 그 선 연결이 안되어있던걸".
keyword-surround-api 와 같은 방식: 새 실행 파일만 더하고 기존 코드는 고치지 않는다.

- 한 번 부를 때 묶음 5개까지 → 기준 검색어 1개 + 검색어 4개.
  기준 검색어가 모든 호출에 들어가므로, 기준 대비 비율로 바꾸면 호출끼리 견줄 수 있다.
- 결과: out/need_datalab_monthly.json
  {"기준": 기준 검색어, "기간": [시작, 끝], "검색어": {검색어: [{"달": "2023-10", "기준대비": 0.42, "원값": 12.3}, ...]}}
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://openapi.naver.com/v1/datalab/search"


def call(body, cid, secret):
    req = urllib.request.Request(
        API,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "X-Naver-Client-Id": cid,
            "X-Naver-Client-Secret": secret,
            "Content-Type": "application/json",
        },
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:300]
            print(f"HTTP {e.code}: {msg}", file=sys.stderr)
            if e.code in (429, 500, 502, 503) and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="out")
    ap.add_argument("--start", default=os.environ.get("START") or "2023-10-01")
    ap.add_argument("--end", default=os.environ.get("END") or "2026-09-30")
    ap.add_argument("--anchor", default=os.environ.get("ANCHOR") or "다이어트")
    a = ap.parse_args()

    cid = os.environ.get("NAVER_OPENAPI_CLIENT_ID", "")
    secret = os.environ.get("NAVER_OPENAPI_CLIENT_SECRET", "")
    if not cid or not secret:
        sys.exit("열쇠 없음: NAVER_OPENAPI_CLIENT_ID / SECRET")

    raw = os.environ.get("KEYWORDS", "")
    seen, words = set(), []
    for w in raw.replace("\n", ",").split(","):
        w = w.strip()
        if w and w != a.anchor and w not in seen:
            seen.add(w)
            words.append(w)
    if not words:
        sys.exit("검색어 없음: KEYWORDS")

    result, failed = {}, []
    for i in range(0, len(words), 4):
        chunk = words[i:i + 4]
        groups = [{"groupName": "__기준__", "keywords": [a.anchor]}]
        groups += [{"groupName": w, "keywords": [w]} for w in chunk]
        body = {"startDate": a.start, "endDate": a.end, "timeUnit": "month", "keywordGroups": groups}
        try:
            res = call(body, cid, secret)
        except Exception as e:  # 한 묶음이 실패해도 나머지는 받는다
            print(f"실패 {chunk}: {e}", file=sys.stderr)
            failed += chunk
            continue
        series = {g["title"]: {d["period"][:7]: d["ratio"] for d in g["data"]} for g in res["results"]}
        base = series.get("__기준__", {})
        for w in chunk:
            rows = []
            for month, v in sorted(series.get(w, {}).items()):
                b = base.get(month)
                rows.append({"달": month, "원값": v, "기준대비": round(v / b, 4) if b else None})
            result[w] = rows
        time.sleep(0.2)
        print(f"{min(i + 4, len(words))}/{len(words)}")

    os.makedirs(a.out_dir, exist_ok=True)
    out = {"기준": a.anchor, "기간": [a.start, a.end], "검색어": result, "실패": failed}
    with open(os.path.join(a.out_dir, "need_datalab_monthly.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"받음 {len(result)} · 실패 {len(failed)}")
    if not result:
        sys.exit(1)


if __name__ == "__main__":
    main()
