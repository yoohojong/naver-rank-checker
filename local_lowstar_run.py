# -*- coding: utf-8 -*-
"""local_lowstar_run: 사장님 컴퓨터의 '사장님 로그인 크롬'으로 경쟁사 저점후기 자동 수집 → 드라이브.

왜: 스마트스토어 후기는 네이버 로그인이 있어야 보임(서버 무인수집 불가). 사장님이 별도 창에서
로그인 1회만 하면, 이 스크립트가 상품 목록을 돌며 저점(별점<=3) 후기를 모아 드라이브 '다리'로 저장.

수집 방식(확장과 동일 '학습'):
  상품 페이지가 실제로 쏘는 '후기 query-pages 요청'(URL+body)을 가로채 학습한 뒤, 그 요청을
  '별점 낮은순'으로 바꿔 page 루프 재호출 → score<=3 만 모은다. (브랜드 /n/v1/... 과 스마트스토어
  /i/v1/contents/reviews/group-products/... 의 주소·ID 차이를 '학습'이 자동 흡수 — 2026-06-23 진단 확인.)
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

from src.review_lowstar import _UA  # UA만 재사용(수집 로직은 학습 방식으로 자체 구현)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BRIDGE_URL = (
    "https://script.google.com/macros/s/"
    "AKfycbx-SDZ4upXCBARovOpwEqBy7-eCmuTo00iQjr9QRVu20I1KxKJpXFekcKMzwbpi3z2y/exec"
)
PROFILE_DIR = r"D:\claude code\.naver-auto-profile"
KW_FILE = os.environ.get("KW_FILE", r"/tmp/harvest/키워드별_상품주소.txt")  # 키워드별 상품URL 매핑
ONLY_URL = os.environ.get("ONLY_URL", "")   # 검증용: 한 URL만(키워드='검증')
MAX_SCORE = 3
MAX_PER_PRODUCT = 200
MAX_PAGES = 30
PAGE_SIZE = 20
STOP_AFTER_EMPTY_PAGES = 2
LOGIN_WAIT_SEC = 1800

# 후기요청 식별(브랜드/스마트스토어 공통 변형).
_REVIEW_URL_KEYS = ("reviews/query-pages", "reviews/group-products/query-pages")

# 학습한 요청을 세션 내부에서 별점 낮은순으로 재호출하는 fetch.
_REPLAY_JS = r"""
async (cfg) => {
  try {
    const r = await fetch(cfg.url, {
      method: "POST",
      headers: {"Content-Type": "application/json", "Accept": "application/json"},
      body: JSON.stringify(cfg.body),
      credentials: "include"
    });
    const t = await r.text();
    let j = null; try { j = JSON.parse(t); } catch (e) {}
    return {status: r.status, json: j, head: j ? null : t.slice(0, 160)};
  } catch (e) { return {status: -1, error: String(e)}; }
}
"""


def _log(msg: str) -> None:
    try:
        print(msg, flush=True)
    except Exception:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def _source_of(url: str) -> str:
    if "brand.naver.com" in url:
        return "브랜드"
    if "smartstore.naver.com" in url:
        return "스마트스토어"
    return "네이버"


def _pick_items(j):
    if not isinstance(j, dict):
        return []
    return j.get("contents") or j.get("reviews") or j.get("reviewList") or j.get("list") or []


def _pick_score(c):
    for k in ("reviewScore", "score", "rating"):
        v = c.get(k)
        if isinstance(v, (int, float)):
            return v
        try:
            if v is not None:
                return float(v)
        except (TypeError, ValueError):
            pass
    return None


def _pick_content(c):
    for k in ("reviewContent", "content", "reviewBody"):
        v = c.get(k)
        if v:
            return str(v).strip()
    return ""


def _build_body(learned, page):
    """학습 body 복제 + 페이지/사이즈/정렬키(변형 모두) 강제."""
    b = dict(learned)
    for sk in ("reviewSearchSortType", "sortType", "sort"):
        if sk in b or sk == "reviewSearchSortType":
            b[sk] = "REVIEW_SCORE_ASC"
    if isinstance(b.get("page"), dict):
        b["page"]["page"] = page
        if "size" in b["page"]:
            b["page"]["size"] = PAGE_SIZE
        if "pageSize" in b["page"]:
            b["page"]["pageSize"] = PAGE_SIZE
    else:
        b["page"] = page
    if "pageSize" not in b:
        b["pageSize"] = PAGE_SIZE
    return b


def collect_via_learn(pg, url, max_reviews, max_score, max_pages):
    """상품 페이지의 후기요청을 학습 → 별점 낮은순 재호출 → score<=max_score 수집."""
    captured = {"url": None, "body": None}

    def on_req(req):
        try:
            u = req.url
            if req.method == "POST" and any(k in u for k in _REVIEW_URL_KEYS):
                bd = req.post_data
                if bd and not captured["url"]:
                    captured["url"] = u
                    captured["body"] = bd
        except Exception:
            pass

    pg.on("request", on_req)
    try:
        pg.goto(url, wait_until="domcontentloaded", timeout=45000)
        time.sleep(4)
        # 후기 지연로드 유발: 스크롤 + '리뷰' 탭 클릭 시도.
        for _ in range(4):
            pg.mouse.wheel(0, 3000)
            time.sleep(1.0)
        for sel in ("text=리뷰", "a:has-text('리뷰')", "text=후기"):
            try:
                el = pg.query_selector(sel)
                if el:
                    el.click()
                    time.sleep(2.5)
                    break
            except Exception:
                pass
        # 학습 폴링.
        for _ in range(10):
            if captured["url"]:
                break
            pg.mouse.wheel(0, 2000)
            time.sleep(1.0)
    finally:
        try:
            pg.remove_listener("request", on_req)
        except Exception:
            pass

    if not captured["url"]:
        return [], "후기요청 못 읽음"
    try:
        learned = json.loads(captured["body"])
    except Exception:
        return [], "body 파싱 실패"
    if not isinstance(learned, dict):
        return [], "body 형식"

    out = []
    empty_streak = 0
    for page in range(1, max_pages + 1):
        body = _build_body(learned, page)
        res = pg.evaluate(_REPLAY_JS, {"url": captured["url"], "body": body})
        if not res or res.get("status") != 200:
            break
        items = _pick_items(res.get("json"))
        if not items:
            break
        low_here = 0
        for c in items:
            s = _pick_score(c)
            if isinstance(s, (int, float)) and s > max_score:
                continue
            body_txt = _pick_content(c)
            if not body_txt:
                continue
            low_here += 1
            out.append({"score": s if isinstance(s, (int, float)) else "", "content": body_txt})
            if len(out) >= max_reviews:
                return out, "ok"
        if low_here == 0:
            empty_streak += 1
            if empty_streak >= STOP_AFTER_EMPTY_PAGES:
                break
        else:
            empty_streak = 0
        time.sleep(1.0)
    return out, "ok"


def _post_bridge(keyword, url, rows):
    """저점후기 → 다리(웹앱) → '수집결과_리뷰' 탭에 키워드별 append → 자동적재가 키워드 폴더로."""
    body = json.dumps({
        "keyword": keyword, "sourceUrl": url,
        "rows": [{"score": r.get("score"), "content": r.get("content")} for r in rows],
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BRIDGE_URL, data=body,
                                 headers={"Content-Type": "text/plain;charset=utf-8"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=40).read()
    except Exception:
        pass  # 302 전에 append 는 실행됨
    return True


def _reflect_status(per_kw):
    """수집 끝나면 다리(reflectStatus)로 시트 '수집상태' 칸에 '✅ M/D 저점리뷰 수집(N건)' 자동 표시.
    구조적 재발방지: 러너가 시트에 안 쓰던 구멍을 메움(이전엔 별도 reflect 안 돌리면 표시 누락)."""
    items = [{"keyword": k, "count": v} for k, v in per_kw.items() if v > 0]
    if not items:
        return
    body = json.dumps({"mode": "reflectStatus", "token": "cafe-deposit-2026",
                       "marker": "저점리뷰 수집", "items": items}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BRIDGE_URL, data=body,
                                 headers={"Content-Type": "text/plain;charset=utf-8"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=120).read()
        _log(f"REFLECT: 수집상태 자동 반영 요청 {len(items)}개 키워드")
    except Exception as e:
        _log(f"REFLECT 실패(비차단): {e}")


def parse_kw_file(path):
    """키워드별_상품주소.txt → OrderedDict {키워드: [url,...]}."""
    from collections import OrderedDict
    kw = OrderedDict()
    cur = None
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.rstrip("\n")
            if ln.startswith("# "):
                cur = ln[2:].rsplit(" (", 1)[0].strip()
                kw.setdefault(cur, [])
            elif cur and ln.strip().startswith("http"):
                kw[cur].append(ln.strip())
    return kw


def _wait_for_login(ctx, pg):
    try:
        pg.bring_to_front()
    except Exception:
        pass
    pg.goto("https://nid.naver.com/nidlogin.login", wait_until="domcontentloaded", timeout=45000)
    _log("LOGIN_WAIT: 새로 뜬 큰 창(네이버 로그인 화면)에서 로그인 해주세요. 로그인되면 자동 진행합니다...")
    t0 = time.time()
    while time.time() - t0 < LOGIN_WAIT_SEC:
        try:
            names = {c.get("name") for c in ctx.cookies() if "naver" in (c.get("domain") or "")}
        except Exception:
            names = set()
        if "NID_AUT" in names or "NID_SES" in names:
            _log("LOGIN_OK: 로그인 감지됨. 수집 시작합니다.")
            return True
        time.sleep(3)
    _log("LOGIN_TIMEOUT: 로그인이 감지되지 않았습니다.")
    return False


def main():
    if ONLY_URL:
        kw_urls = {"검증": [ONLY_URL]}
    else:
        if not os.path.exists(KW_FILE):
            _log(f"ERR: 키워드 매핑 없음 - {KW_FILE}")
            return 1
        kw_urls = parse_kw_file(KW_FILE)
    total_urls = sum(len(v) for v in kw_urls.values())
    _log(f"START: 키워드 {len(kw_urls)}개 / 상품 URL {total_urls}개")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE_DIR, channel="chrome", headless=False, no_viewport=True,
            user_agent=_UA, locale="ko-KR",
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
        )
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        if not _wait_for_login(ctx, pg):
            ctx.close()
            return 2

        cache = {}  # url -> rows (같은 상품 중복수집 방지)
        appended = collected = total = 0
        per_kw = {}  # 키워드별 저점 건수(수집상태 자동반영용)
        for keyword, urls in kw_urls.items():
            for url in urls:
                if url in cache:
                    rows = cache[url]
                else:
                    try:
                        rows, _reason = collect_via_learn(pg, url, MAX_PER_PRODUCT, MAX_SCORE, MAX_PAGES)
                    except Exception as e:
                        rows = []
                        _log(f"  [{keyword}] 실패 {type(e).__name__} - {url[:45]}")
                    cache[url] = rows
                    collected += 1
                    time.sleep(random.uniform(4, 11))  # 과속 차단 회피
                if rows:
                    _post_bridge(keyword, url, rows)  # 키워드별 탭 append → 자동적재가 키워드 폴더로
                    appended += 1
                    total += len(rows)
                    per_kw[keyword] = per_kw.get(keyword, 0) + len(rows)
                    _log(f"  [{keyword}] {url[:42]} -> 저점 {len(rows)}건 (탭 append)")
                else:
                    _log(f"  [{keyword}] {url[:42]} -> 0건")

        _log(f"DONE: 키워드 {len(kw_urls)}개 / 수집상품 {collected}개 / append {appended} / 후기 총 {total}건")
        # ★ (2026-06-27) 구조적 재발방지: 수집 끝나면 시트 '수집상태'에 자동 반영(러너가 시트 미기록이던 구멍 메움).
        _reflect_status(per_kw)
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
