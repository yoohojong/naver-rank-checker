"""경쟁사 블로그 · 카페 글 본문 받기 — 글마다 사업자 표기 · 광고 표시 · 판매처 주소가 있는지 가른다.

2026-10-26 ⑥ 경쟁사 신고 프로그램 창 · 사장님 '그래 가자'(순위체커 저장소에 새 실행 파일만 더하기 · 기존 코드 안 고침).
이 PC 는 네이버를 열지 않으므로 GitHub 서버에서만 돈다. 요청 사이 간격을 두고, 블로그마다 글 수 상한을 둔다.

입력(환경값)
  BLOGS      쉼표로 가른 블로그 아이디
  CAFES      쉼표로 가른 카페 주소 이름(cafe.naver.com/<이름>)
  MARKERS    쉼표로 가른 찾을 낱말(사업자번호 · 상호 · 상품 이름)
  SHOP_QUERY 쉼표로 가른 쇼핑 검색어(공식 검색 API · 실패하면 응답 원문을 남긴다)
  MAX_POSTS  블로그 · 카페마다 받을 글 수 상한(기본 60)
  MODE       '세기만'(기본) = 글 목록 · 전체 글 수만 받고 본문은 받지 않는다 / '본문' = 글마다 본문까지 받는다

2026-10-27 기본을 '세기만'으로 바꿈 — 사장님 "글 몇개인지 파악하고 조금씩 넓혀가는단계로 해도 될 듯".
먼저 글 수를 세고, 본문은 필요한 곳만 MODE=본문 으로 다시 부른다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

KST = dt.timezone(dt.timedelta(hours=9))
UA = ("Mozilla/5.0 (Linux; Android 14; SM-S918N) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36")
AD_WORDS = ["원고료", "광고", "협찬", "소정의", "제공받", "체험단", "대가", "수수료"]
LINK_HOSTS = ["coreof.co.kr", "runmoa.com", "smartstore.naver.com", "brand.naver.com",
              "coupang.com", "link.coupang.com", "naver.me", "store.kakao.com"]


def now() -> str:
    return dt.datetime.now(KST).isoformat(timespec="seconds")


def get(url: str, headers: dict | None = None, pause: float = 1.0) -> tuple[int, str]:
    time.sleep(pause)
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:2000]
    except Exception as e:  # 연결 실패도 기록만 하고 다음으로
        return -1, repr(e)[:500]


def strip_tags(s: str) -> str:
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t​\xa0]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


def inspect(text: str, raw: str, markers: list[str]) -> dict:
    links = sorted({u for u in re.findall(r'https?://[^\s"\'<>]+', html.unescape(raw))
                    if any(h in u for h in LINK_HOSTS)})
    return {
        "찾을낱말": [m for m in markers if m and m in text],
        "광고낱말": [w for w in AD_WORDS if w in text],
        "판매처주소": links[:30],
        "끝부분": text[-400:],
    }


def blog_posts(blog: str, limit: int) -> tuple[list[dict], dict]:
    posts, meta, page = [], {"블로그": blog}, 1
    while len(posts) < limit:
        url = ("https://blog.naver.com/PostTitleListAsync.naver?blogId=%s&viewdate=&currentPage=%d"
               "&categoryNo=0&parentCategoryNo=&countPerPage=30" % (urllib.parse.quote(blog), page))
        code, body = get(url, {"Referer": "https://blog.naver.com/%s" % blog})
        meta.setdefault("목록응답", []).append(code)
        if code != 200:
            meta["목록오류"] = body[:300]
            break
        try:
            data = json.loads(body.replace("\\'", "'"))
        except ValueError:
            meta["목록오류"] = "모양 다름: " + body[:300]
            break
        meta["전체글수"] = data.get("totalCount")
        items = data.get("postList") or []
        for it in items:
            posts.append({"logNo": it.get("logNo"),
                          "제목": urllib.parse.unquote_plus(it.get("title", "")),
                          "날짜": it.get("addDate")})
        if len(items) < 30:
            break
        page += 1
    return posts[:limit], meta


def blog_body(blog: str, log_no: str, markers: list[str]) -> dict:
    url = "https://m.blog.naver.com/PostView.naver?blogId=%s&logNo=%s" % (blog, log_no)
    code, raw = get(url, {"Referer": "https://m.blog.naver.com/%s" % blog})
    row = {"주소": "https://blog.naver.com/%s/%s" % (blog, log_no), "응답": code, "받은시각": now()}
    if code != 200:
        row["오류"] = raw[:300]
        return row
    m = re.search(r'(?s)<div class="se-main-container">(.*?)<div class="(?:post_footer|wrap_postdata|section_t1)', raw)
    part = m.group(1) if m else raw
    text = strip_tags(part)
    row.update({"글자수": len(text), "본문": text[:4000]})
    row.update(inspect(text, part, markers))
    return row


def cafe_posts(cafe: str, limit: int, markers: list[str], bodies: bool = True) -> dict:
    out = {"카페": cafe, "받은시각": now(), "글": []}
    code, body = get("https://apis.naver.com/cafe-web/cafe2/CafeGateInfo.json?cluburl=%s" % cafe,
                     {"Referer": "https://m.cafe.naver.com/%s" % cafe})
    out["카페정보응답"] = code
    clubid = None
    try:
        info = json.loads(body)
        clubid = info["message"]["result"]["cafeInfoView"]["cafeId"]
        out["카페이름"] = info["message"]["result"]["cafeInfoView"].get("cafeName")
        out["회원수"] = info["message"]["result"]["cafeInfoView"].get("memberCount")
    except Exception:
        out["카페정보오류"] = body[:300]
        return out
    out["카페번호"] = clubid
    code, body = get("https://apis.naver.com/cafe-web/cafe2/ArticleListV2dot1.json?search.clubid=%s"
                     "&search.queryType=lastArticle&search.page=1&search.perPage=%d" % (clubid, min(limit, 50)),
                     {"Referer": "https://m.cafe.naver.com/%s" % cafe})
    out["목록응답"] = code
    try:
        arts = json.loads(body)["message"]["result"]["articleList"]
    except Exception:
        out["목록오류"] = body[:300]
        return out
    for a in arts[:limit]:
        aid = a.get("articleId")
        row = {"주소": "https://cafe.naver.com/%s/%s" % (cafe, aid), "제목": a.get("subject"),
               "글쓴이": a.get("writerNickname"), "날짜": a.get("writeDateTimestamp")}
        if not bodies:
            out["글"].append(row)
            continue
        c2, b2 = get("https://apis.naver.com/cafe-web/cafe-articleapi/v2.1/cafes/%s/articles/%s?useCafeId=true"
                     % (clubid, aid), {"Referer": "https://m.cafe.naver.com/%s/%s" % (cafe, aid)})
        row["응답"] = c2
        try:
            content = json.loads(b2)["result"]["article"]["contentHtml"]
            text = strip_tags(content)
            row.update({"글자수": len(text), "본문": text[:4000]})
            row.update(inspect(text, content, markers))
        except Exception:
            row["오류"] = b2[:300]
        out["글"].append(row)
    return out


def shop(queries: list[str]) -> list[dict]:
    cid, csec = os.environ.get("NAVER_OPENAPI_CLIENT_ID", ""), os.environ.get("NAVER_OPENAPI_CLIENT_SECRET", "")
    res = []
    for q in queries:
        url = "https://openapi.naver.com/v1/search/shop.json?query=%s&display=100&start=1&sort=sim" % urllib.parse.quote(q)
        code, body = get(url, {"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csec}, pause=0.3)
        row = {"검색어": q, "응답": code, "받은시각": now()}
        try:
            d = json.loads(body)
            row["검색결과수"] = d.get("total")
            row["항목들"] = [{"상품": strip_tags(i.get("title", "")), "판매처": i.get("mallName"),
                            "가격": i.get("lprice"), "주소": i.get("link"), "브랜드": i.get("brand"),
                            "제조사": i.get("maker")} for i in d.get("items", [])]
            if code != 200:
                row["오류원문"] = d
        except ValueError:
            row["오류원문"] = body[:500]
        res.append(row)
    return res


def split(name: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, "").split(",") if x.strip()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="out")
    a = ap.parse_args(argv)
    markers = split("MARKERS")
    limit = int(os.environ.get("MAX_POSTS") or 60)
    mode = (os.environ.get("MODE") or "세기만").strip()
    if mode not in ("세기만", "본문"):
        print("MODE 는 '세기만' 또는 '본문'만 받습니다:", mode, file=sys.stderr)
        return 2
    bodies = mode == "본문"
    result = {"받은시각": now(), "방식": mode, "찾을낱말": markers, "블로그": [], "카페": [], "쇼핑": []}
    for b in split("BLOGS"):
        posts, meta = blog_posts(b, limit)
        meta["글"] = [{**p, **blog_body(b, p["logNo"], markers)} for p in posts] if bodies else posts
        result["블로그"].append(meta)
        print(b, "목록", meta.get("목록응답"), "전체 글", meta.get("전체글수"), "받은 글", len(meta["글"]),
              "낱말 걸린 글", sum(1 for g in meta["글"] if g.get("찾을낱말")) if bodies else "(세기만)", flush=True)
    for c in split("CAFES"):
        r = cafe_posts(c, limit, markers, bodies)
        result["카페"].append(r)
        print(c, "카페", r.get("카페정보응답"), r.get("목록응답"), "글", len(r["글"]), flush=True)
    if split("SHOP_QUERY"):
        result["쇼핑"] = shop(split("SHOP_QUERY"))
        for s in result["쇼핑"]:
            print("쇼핑", s["검색어"], s["응답"], s.get("검색결과수"), flush=True)
    os.makedirs(a.out_dir, exist_ok=True)
    path = os.path.join(a.out_dir, "글본문_%s.json" % dt.datetime.now(KST).strftime("%Y%m%d-%H%M"))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("저장", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

