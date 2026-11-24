# 손님(로그인 없음 · 쿠키 없음) 화면 21개를 서버에서 받아 저장(읽기만 · 2026-11-25)
import json, os, re, time, datetime
from playwright.sync_api import sync_playwright
OUT = "out"; os.makedirs(OUT, exist_ok=True)
UA_PC = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
UA_M = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mobile/15E148 Safari/604.1".replace("like Mobile", "like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile")
PC = ("PC", "https://smartstore.naver.com", UA_PC, {"width": 1440, "height": 900}, False)
MO = ("휴대폰", "https://m.smartstore.naver.com", UA_M, {"width": 390, "height": 844}, True)
SCREENS = []  # (id, device, url, kind)
SCREENS.append(("01_스토어홈_PC", PC, "/goyu777", "store"))
SCREENS.append(("02_스토어홈_휴대폰", MO, "/goyu777", "store"))
n = 3
for name, pid in [("교정기", "13889385174"), ("마사지기", "13889380939"), ("이완기", "13884386311")]:
    for d in (PC, MO):
        SCREENS.append((f"{n:02d}_상품{pid}{name}_{d[0]}", d, f"/goyu777/products/{pid}", "product")); n += 1
for pid in ["12678043071","13471917235","13131336302","13031591940","12744433878","12711412037","12709545439","12707419078","11215985849"]:
    SCREENS.append((f"{n:02d}_타브랜드{pid}_PC", PC, f"/main/products/{pid}", "other")); n += 1
MALL = "https://yeopropillow.com/"
SCREENS += [(f"{n:02d}_자사몰_PC_첫화면", ("PC", "", UA_PC, PC[3], False), MALL, "mall"),
            (f"{n+1:02d}_자사몰_PC_바닥", ("PC", "", UA_PC, PC[3], False), MALL, "mall_bottom"),
            (f"{n+2:02d}_자사몰_휴대폰_첫화면", ("휴대폰", "", UA_M, MO[3], True), MALL, "mall"),
            (f"{n+3:02d}_자사몰_휴대폰_펼친메뉴", ("휴대폰", "", UA_M, MO[3], True), MALL, "mall_menu")]
assert len(SCREENS) == 21, len(SCREENS)
KEYS = ["건강보법", "카테키산", "KoU", "옆으로베개", "스텝닥터"]
IMG_JS = """() => [...document.querySelectorAll('img')].map(i => ({src: i.getAttribute('src'), currentSrc: i.currentSrc, alt: i.alt, w: Math.round(i.getBoundingClientRect().width), h: Math.round(i.getBoundingClientRect().height)}))
 .concat([...document.querySelectorAll('*')].map(e => ({bg: getComputedStyle(e).backgroundImage})).filter(x => x.bg && x.bg !== 'none'))"""
log = []
with sync_playwright() as p:
    b = p.chromium.launch(args=["--mute-audio"])
    for sid, (dev, host, ua, vp, mob), path, kind in SCREENS:
        url = path if path.startswith("http") else host + path
        rec = {"id": sid, "url": url, "time": datetime.datetime.utcnow().isoformat() + "Z"}
        ctx = b.new_context(locale="ko-KR", user_agent=ua, viewport=vp, is_mobile=mob)  # 새 칸 = 쿠키 없음
        pg = ctx.new_page()
        try:
            r = pg.goto(url, wait_until="domcontentloaded", timeout=40000); time.sleep(6)
            rec["status"] = r.status if r else None; rec["final_url"] = pg.url; rec["title"] = pg.title()
            if kind == "product":  # 상세 펼침 · 아래 칸까지 불러오기
                for t in ["상세정보 펼쳐보기", "상세정보 더보기", "펼쳐보기", "더보기"]:
                    try:
                        loc = pg.get_by_text(t, exact=False).first
                        if loc.count() and loc.is_visible():
                            loc.click(timeout=3000); rec["expand_clicked"] = t; break
                    except Exception as e:
                        rec.setdefault("expand_err", repr(e)[:120])
                for _ in range(8):
                    pg.mouse.wheel(0, 1500); time.sleep(0.8)
                pg.evaluate("window.scrollTo(0,0)"); time.sleep(1)
            if kind == "mall_bottom":
                pg.evaluate("window.scrollTo(0, document.body.scrollHeight)"); time.sleep(2)
            if kind == "mall_menu":
                try:
                    c = pg.query_selector("[class*=eNavFold], [class*=btnMenu], [class*=menu_open], .xans-layout-statelogon a[href='#none'], button[class*=menu]")
                    if c: c.click(timeout=3000); rec["menu_clicked"] = True; time.sleep(2)
                    else: rec["menu_clicked"] = False
                except Exception as e:
                    rec["menu_err"] = repr(e)[:150]
            html = pg.content(); txt = pg.inner_text("body")
            open(f"{OUT}/{sid}.html", "w", encoding="utf-8").write(html)
            json.dump(pg.evaluate(IMG_JS), open(f"{OUT}/{sid}.srcs.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            rec["count_visible"] = {k: txt.count(k) for k in KEYS}; rec["count_html"] = {k: html.count(k) for k in KEYS}
            rec["body_head"] = txt[:200]
            pg.screenshot(path=f"{OUT}/{sid}.png", full_page=(kind in ("product",) and False))
        except Exception as e:
            rec["error"] = repr(e)
        json.dump({k: rec.get(k) for k in ("id","url","final_url","status","title","error")}, open(f"{OUT}/{sid}.status.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        log.append(rec); print(rec, flush=True)
        ctx.close(); time.sleep(3)
    b.close()
json.dump(log, open(f"{OUT}/log.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
