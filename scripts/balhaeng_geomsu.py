# -*- coding: utf-8 -*-
"""발행 검수 — 매일 1회. 시트 링크 → 카페 글 수집 → 채점 → '발행 검수' 탭 기록.

사장님 승인(2026-07-23): "전체로 자동으로 시트에 반영까지 해서 ㄱㄱ 매일 1번씩"

무엇을 보나(사장님 원문): "상위노출 로직 기준에 맞게 썼는지, 그리고 ai 티 나지 않게
문맥이 괜찮은지, 실수한게 없는지".

시트 쓰기 범위 — **'발행 검수' 탭에만 쓴다. 기존 탭은 절대 건드리지 않는다.**
  · 탭이 없으면 만든다. 있으면 링크 기준으로 갱신(같은 글은 덮어쓰고 새 글은 추가).
  · 고쳐서 합격이 되면 상태가 '해결'로 바뀐다 — 작업자가 손으로 체크할 필요 없다.

검수 로직 정본은 team-project/cafe-external/ 이다. 여기 scripts/audit/ 는 그 복사본.
"""
from __future__ import annotations

import importlib.util
import json
import os
import random
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

from curl_cffi import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from src.sheets import SheetsClient  # noqa: E402

KST = timezone(timedelta(hours=9))
IMPERSONATE = "chrome131"
CAFE_LINK = re.compile(r"cafe\.naver\.com/(?:f-e/cafes/(\d+)/articles/(\d+)|([^/?#]+)/(\d+))")
제외탭 = ("백업", "삭제전", "복사본", "이력", "스테이징", "발행 검수")
탭이름 = "발행 검수"
# ★사장님 지적(2026-07-23): "처음걸린날 마지막검사 이것도 두개나 써줘야하나?
#   상태는 굳이 필요한가?" → 셋 다 뺐다.
#   · 상태 = 판정과 같은 말. 두 번 쓸 이유가 없다.
#   · 처음 걸린 날 = 아무도 안 본다. 필요해지면 그때 넣는다.
#   · 마지막 검사 → '검사일' 하나로. 이 값이 오래됐으면 검사가 멈춘 것이다.
헤더 = ["키워드", "작업자", "작업일", "카페/게시판", "작업아이디", "글 링크",
        "판정", "무엇이 걸렸나", "측정", "검사일"]
옛헤더들 = [
    ["키워드", "글 링크", "판정", "무엇이 걸렸나", "측정",
     "처음 걸린 날", "마지막 검사", "상태"],
    ["키워드", "작업자", "작업일", "카페/게시판", "작업아이디", "글 링크",
     "판정", "무엇이 걸렸나", "측정", "처음 걸린 날", "마지막 검사", "상태"],
]
링크열 = 헤더.index("글 링크")          # 행을 알아보는 열쇠
측정열 = 헤더.index("측정")


def _검수모듈():
    spec = importlib.util.spec_from_file_location(
        "audit", os.path.join(HERE, "audit", "발행본_검수.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


검수기 = _검수모듈()


def 쉬기():
    time.sleep(random.uniform(3.5, 5.25))


def 본문풀기(html: str) -> tuple[str, int]:
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html or "", flags=re.S | re.I)
    사진 = [0]

    def 자리(_m):
        사진[0] += 1
        return f"\n(사진{사진[0]})\n"

    t = re.sub(r"<img\b[^>]*>", 자리, t, flags=re.I)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"</(p|div|h\d)>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = (t.replace("&nbsp;", " ").replace("​", "").replace("&amp;", "&")
          .replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"'))
    본문 = "\n".join(ln.strip() for ln in t.splitlines() if ln.strip())
    return re.sub(r"\n{3,}", "\n\n", 본문).strip(), 사진[0]


def 단계뽑기(분류: str) -> int | None:
    """단계는 **'키워드 분류'** 칸에 있다('5 브랜드제품' / '4 대안' / '3 증상').

    ★2026-07-23 치명 오류 정정: 처음에 '유형' 칸에서 뽑았는데, 그 칸은 이 레포가 관리하는
      노출 구좌 타입(AB·인기글·스마트블록)이라 단계가 들어갈 리 없다. 그 결과 stage=None 이
      되어 **글자수·키워드 횟수 검사가 통째로 빠진 채** 60행이 시트에 기록됐다.
      (사장님이 첫째로 보고 싶다고 한 상위노출 로직을 하나도 안 재고 있었다.)
    """
    m = re.match(r"\s*([345])", 분류 or "")
    return int(m.group(1)) if m else None


def 대상읽기(sc: SheetsClient, limit: int) -> tuple[list[dict], list]:
    """검수할 글 목록과, 단계를 못 읽어 건너뛴 목록을 함께 돌려준다.

    ★숨김 탭 제외(2026-07-23) — 사장님 규칙: 카외 보고·집계는 숨김 탭을 뺀다.
      '두드러기 카외'(숨김)가 대상에 들어가 매번 57건이 '단계 없어 건너뜀'으로
      잡혔다. 그 탭엔 '키워드 분류' 열 자체가 없다 — 고칠 수 있는 문제가 아니라
      애초에 안 봐야 할 탭이었다. gspread 공식 인자를 쓴다(내부 속성 접근 금지 —
      라이브러리가 바뀌면 조용히 '안 숨김'으로 떨어져 문제가 되살아난다).
    """
    본, 키, 건너뜀 = [], set(), []
    탭들 = [ws for ws in sc.spreadsheet.worksheets(exclude_hidden=True)
            if "카외" in ws.title and not any(x in ws.title for x in 제외탭)]
    print(f"  검수 탭 {len(탭들)}개: {', '.join(ws.title for ws in 탭들)}")
    # 탭 크기에 비례해 몫을 준다(균등이면 큰 탭이 며칠씩 밀린다 — 실측 27행 미갱신).
    크기 = [max(1, ws.row_count) for ws in 탭들]
    총 = sum(크기) or 1
    몫들 = [max(1, int(limit * c / 총)) for c in 크기]
    for 탭순, ws in enumerate(탭들):
        rows = ws.get_all_values()
        if not rows:
            continue
        h = rows[0]
        idx = {이름: i for i, 이름 in enumerate(x.strip() for x in h)}
        for row in reversed(rows[1:]):
            링크 = next((c.strip() for c in row
                        if isinstance(c, str) and c.strip().startswith("http")
                        and CAFE_LINK.search(c)), None)
            if not 링크:
                continue
            m = CAFE_LINK.search(링크)
            ident = (m.group(1) or m.group(3), m.group(2) or m.group(4))
            if ident in 키:
                continue
            키.add(ident)

            def 칸(이름):
                i = idx.get(이름)
                return row[i].strip() if i is not None and i < len(row) else ""

            stage = 단계뽑기(칸("키워드 분류"))
            if stage is None:
                건너뜀.append((ws.title, 칸("키워드")))
                continue
            본.append({"url": 링크, "keyword": 칸("키워드"), "stage": stage,
                       "product": "바디" if "바디" in ws.title else "샴푸",
                       # 누가·언제·어디에 올렸나 — 부적합을 누가 고쳐야 하는지 바로 보이게
                       "작업자": 칸("작업자"), "작업일": 칸("작업일"),
                       "카페": 칸("카페/게시판"), "작업아이디": 칸("작업아이디")})
            if len(본) >= sum(몫들[:탭순 + 1]) or len(본) >= limit:
                break
    if 건너뜀:
        print(f"  단계(키워드 분류) 없어 건너뜀 {len(건너뜀)}건 "
              f"— 예: {', '.join(k for _, k in 건너뜀[:3])}")
    # 건너뛴 글은 조용히 사라지면 안 된다 — 검사 못 한 몫으로 보고에 싣는다.
    return 본[:limit], 건너뜀


def 한건수집(t: dict) -> dict:
    link = t["url"]
    m = CAFE_LINK.search(link)
    cafe_id, art_id = (m.group(1), m.group(2)) if m.group(1) else (None, m.group(4))
    page = requests.get(link, impersonate=IMPERSONATE, timeout=25)
    쉬기()
    gid = cafe_id
    if not gid:
        mm = re.search(r'g_sClubId\s*=\s*"(\d+)"', page.text or "")
        gid = mm.group(1) if mm else None
    if not gid:
        return {**t, "_실패": "카페번호 못 찾음"}

    a = requests.get(f"https://apis.naver.com/cafe-web/cafe-articleapi/v3/cafes/{gid}/articles/{art_id}",
                     impersonate=IMPERSONATE, timeout=25, headers={"Referer": link})
    쉬기()
    if a.status_code != 200:
        return {**t, "_실패": f"글 없음({a.status_code})"}
    res = a.json().get("result", {})
    art = res.get("article", res)
    본문, 사진 = 본문풀기(art.get("contentHtml") or art.get("content") or "")
    w = art.get("writer") or {}
    글쓴이 = w.get("nick") or w.get("nickName") or ""

    c = requests.get(f"https://apis.naver.com/cafe-web/cafe-articleapi/v2/cafes/{gid}"
                     f"/articles/{art_id}/comments/pages/1?requestFrom=A&orderBy=asc&perPage=100",
                     impersonate=IMPERSONATE, timeout=25, headers={"Referer": link})
    쉬기()
    댓글 = []
    if c.status_code == 200:
        body = c.json()
        cres = body.get("result") or (body.get("message") or {}).get("result") or {}
        cs = cres.get("comments", [])
        if isinstance(cs, dict):
            cs = cs.get("items", [])
        for x in cs:
            if x.get("isDeleted"):
                continue
            cw = x.get("writer") or {}
            닉 = cw.get("nick") or cw.get("nickName") or ""
            if x.get("isArticleWriter") and 글쓴이:
                닉 = 글쓴이
            텍스트, _ = 본문풀기(x.get("content") or "")
            댓글.append({"author": 닉, "text": 텍스트, "depth": 1 if x.get("isRef") else 0})

    return {**t, "title": (art.get("subject") or "").strip(), "body": 본문,
            "photos": 사진, "author": 글쓴이, "comments": 댓글,
            "disease": t.get("keyword")}


def _끝열(n):
    return chr(ord("A") + n - 1)


def 탭준비(sc: SheetsClient):
    try:
        ws = sc.spreadsheet.worksheet(탭이름)
    except Exception:
        ws = sc.spreadsheet.add_worksheet(title=탭이름, rows=500, cols=len(헤더))
        _헤더쓰기(ws)
        print(f"  '{탭이름}' 탭 새로 만듦")
        return ws

    # 이미 있는 탭이면 헤더가 옛 형태(8칸)인지 보고, 그렇다면 새 형태(12칸)로 옮긴다.
    # ★그냥 헤더만 바꾸면 기존 행의 값이 엉뚱한 열로 밀린다 → 값도 같이 옮겨야 한다.
    기존 = ws.get_all_values()
    지금헤더 = [x.strip() for x in 기존[0]] if 기존 else []
    if 지금헤더 and 지금헤더 != 헤더 and any(지금헤더 == o for o in 옛헤더들):
        print(f"  옛 헤더({len(지금헤더)}칸) 발견 — 새 헤더({len(헤더)}칸)로 옮깁니다")
        폭 = max(len(지금헤더), len(헤더))     # 줄어든 칸은 빈 값으로 덮어쓴다(지우지 않음)
        옮긴행 = []
        for row in 기존[1:]:
            옛값 = dict(zip(지금헤더, list(row) + [""] * len(지금헤더)))
            # 이름으로 옮긴다 — 열 순서가 바뀌어도 값이 엉뚱한 칸으로 가지 않는다.
            새 = [옛값.get("마지막 검사", "") if 이름 == "검사일" else 옛값.get(이름, "")
                  for 이름 in 헤더]
            옮긴행.append(새 + [""] * (폭 - len(헤더)))
        _헤더쓰기(ws, 폭)
        if 옮긴행:
            ws.update(values=옮긴행,
                      range_name=f"A2:{_끝열(폭)}{len(옮긴행) + 1}",
                      value_input_option="USER_ENTERED")
        print(f"  {len(옮긴행)}행 옮김(값 보존)")
    return ws


def _헤더쓰기(ws, 폭=None):
    폭 = 폭 or len(헤더)
    ws.update(values=[헤더 + [""] * (폭 - len(헤더))], range_name="A1")
    ws.format(f"A1:{_끝열(len(헤더))}1",
              {"textFormat": {"bold": True},
               "backgroundColor": {"red": .93, "green": .95, "blue": .97}})
    ws.freeze(rows=1)


def 시트반영(ws, 결과들: list[tuple[dict, dict]], 실패들: list[dict]):
    """링크 기준 upsert. 고쳐서 합격이 되면 상태가 '해결'로 바뀐다."""
    기존 = ws.get_all_values()
    본문행 = 기존[1:] if 기존 else []
    자리 = {r[링크열].strip(): i + 2 for i, r in enumerate(본문행)
            if len(r) > 링크열 and r[링크열].strip()}
    오늘 = datetime.now(KST).strftime("%Y-%m-%d")
    끝 = _끝열(len(헤더))

    def 행만들기(post, 판정, 걸린것, 측정):
        """헤더 순서대로 한 줄을 만든다. 누가·언제·어디에 올렸는지도 같이 적는다."""
        칸 = [""] * len(헤더)
        칸[헤더.index("키워드")] = post.get("keyword", "")
        칸[헤더.index("작업자")] = post.get("작업자", "")
        칸[헤더.index("작업일")] = post.get("작업일", "")
        칸[헤더.index("카페/게시판")] = post.get("카페", "")
        칸[헤더.index("작업아이디")] = post.get("작업아이디", "")
        칸[헤더.index("글 링크")] = post["url"]
        칸[헤더.index("판정")] = 판정
        칸[헤더.index("무엇이 걸렸나")] = 걸린것
        칸[헤더.index("측정")] = 측정
        칸[헤더.index("검사일")] = 오늘
        return 칸

    바꿀것, 새행 = [], []
    for post, res in 결과들:
        지적 = [d["내용"] for d in res["지적"] if d["등급"] != "참고"]
        m = res["측정"]
        측정 = (f'글자{m["chars"]}·줄{m["lines"]}·키워드{m["kw_body"]}'
                f'·댓글{m["댓글수"]}·사진{m["photos"]}')
        row = 행만들기(post, res["판정"], " / ".join(지적[:6]), 측정)
        r = 자리.get(post["url"])
        if r:
            바꿀것.append({"range": f"A{r}:{끝}{r}", "values": [row]})
        else:
            새행.append(row)

    for post in 실패들:
        r = 자리.get(post["url"])
        if r:
            # 어제 잰 측정·처음 걸린 날을 지우지 않는다(일시 차단 한 번에 기록이 날아갔다)
            옛 = 기존[r - 1]
            row = 행만들기(post, "수집실패", post.get("_실패", ""),
                          옛[측정열] if len(옛) > 측정열 else "")
            바꿀것.append({"range": f"A{r}:{끝}{r}", "values": [row]})
        else:
            새행.append(행만들기(post, "수집실패", post.get("_실패", ""), ""))

    보기 = (바꿀것[0]["values"][0] if 바꿀것 else (새행[0] if 새행 else None))
    if 보기:
        print("  기록 예시: " + " | ".join(
            f"{이름}={값}" for 이름, 값 in zip(헤더, 보기)
            if 이름 in ("키워드", "작업자", "작업일", "카페/게시판", "작업아이디", "판정")))
    if 바꿀것:
        ws.batch_update(바꿀것)
    if 새행:
        ws.append_rows(새행, value_input_option="USER_ENTERED")
    print(f"  시트 반영 — 갱신 {len(바꿀것)}행 · 추가 {len(새행)}행")


def 검수하기(sc: SheetsClient, limit: int, 쓰기: bool, 마감분: int) -> dict:
    """검수를 끝까지 돌리고 결과를 돌려준다. 여기서 나는 예외는 '고장'이다."""
    대상, 건너뜀 = 대상읽기(sc, limit)
    print(f"  검수 대상 {len(대상)}건", flush=True)
    if not 대상:
        raise RuntimeError("검수할 글이 한 건도 안 잡혔습니다 — 시트 링크 열·탭 이름이 "
                           "바뀌었거나, 봐야 할 탭이 숨김으로 되어 있을 수 있습니다")

    # ★시간 예산(2026-07-23) — 네이버가 응답을 늦추면 150건이 워크플로 제한시간을
    #   넘길 수 있다. 넘기면 실행이 '취소'로 끝나 알림이 한 통도 안 나간다.
    #   가장 알아야 하는 날 가장 조용해지는 구조라 여기서 스스로 끊는다.
    마감 = time.monotonic() + 마감분 * 60
    결과들, 실패들, 시간초과 = [], [], []
    for i, t in enumerate(대상, 1):
        if time.monotonic() > 마감:
            시간초과 = 대상[i - 1:]
            print(f"  ⏱ {마감분}분 넘겨 남은 {len(시간초과)}건은 다음 판으로 넘깁니다")
            break
        print(f"  [{i}/{len(대상)}] {t['keyword'] or '?'}", flush=True)
        try:
            post = 한건수집(t)
        except Exception as e:
            post = {**t, "_실패": type(e).__name__}
        if post.get("_실패"):
            실패들.append(post)
            continue
        결과들.append((post, 검수기.검수(post)))

    n = Counter(r["판정"] for _, r in 결과들)
    print(f"\n=== 결과 — 합격 {n['합격']} · 보류 {n['보류']} · 불합격 {n['불합격']} "
          f"· 수집실패 {len(실패들)}")

    # ★시트 쓰기가 실패해도 채점 결과를 버리지 않는다. 40분 걸려 다 재놓고
    #   보고까지 못 받는 것이 제일 나쁘다 — 보고는 보내고 실패는 따로 알린다.
    시트오류 = ""
    if 쓰기:
        try:
            시트반영(탭준비(sc), 결과들, 실패들)
        except Exception as e:
            시트오류 = 사람말로(e)
            print(f"  ✗ 시트에 쓰지 못했습니다 — {시트오류}")
    else:
        print("  (GEOMSU_WRITE=0 — 시트에 쓰지 않음)")

    return {"결과들": 결과들, "실패들": 실패들, "건너뜀": 건너뜀, "수": n,
            "시간초과": 시간초과, "시트오류": 시트오류}


def 보고문(요약: dict, 시트url: str) -> str:
    """사장님이 이것만 읽고 다음 행동을 정할 수 있게 쓴다. 로그를 열게 만들지 않는다."""
    결과들, 실패들, 건너뜀, n = (요약["결과들"], 요약["실패들"],
                                 요약["건너뜀"], 요약["수"])
    이제 = datetime.now(KST)
    오늘 = f"{이제.month}/{이제.day}"
    줄 = [f"📋 발행 검수 {오늘}",
          f"검사 {len(결과들)}건 — 합격 {n['합격']} · 고쳐야 함 {n['불합격']} · "
          f"한번 봐야 함 {n['보류']}"]
    if 실패들:
        줄.append(f"글을 못 읽은 것 {len(실패들)}건")

    def 지적줄(묶음, 제목):
        if not 묶음:
            return
        줄.append("")
        줄.append(제목)
        for p, r in 묶음[:12]:
            지적 = [d["내용"] for d in r["지적"] if d["등급"] == "치명"] or \
                   [d["내용"] for d in r["지적"] if d["등급"] == "주의"]
            앞 = " ".join(x for x in (p.get("keyword") or "?",
                                      f"({p.get('작업자')})" if p.get("작업자") else "") if x)
            줄.append(f"· {앞} — {' / '.join(지적[:2])}")
        if len(묶음) > 12:
            줄.append(f"· … 외 {len(묶음) - 12}건")

    불합격 = [(p, r) for p, r in 결과들 if r["판정"] == "불합격"]
    보류 = [(p, r) for p, r in 결과들 if r["판정"] == "보류"]
    지적줄(불합격, "고쳐야 할 글")
    지적줄(보류, "사람이 한번 봐야 할 글")
    if 결과들 and not 불합격 and not 보류:
        줄.append("")
        줄.append("고칠 글 없음 — 전부 통과")

    if 요약.get("시간초과"):
        줄.append("")
        줄.append(f"시간이 모자라 못 본 글 {len(요약['시간초과'])}건 — 다음 검사 때 봅니다")
    if 건너뜀:
        줄.append("")
        줄.append(f"검사 못 한 글 {len(건너뜀)}건 — 시트 '키워드 분류' 칸이 비어 있어 "
                  f"상위노출 기준(글자수·키워드 횟수)을 잴 수 없습니다")
    if 요약.get("시트오류"):
        줄.append("")
        줄.append(f"⚠️ 결과를 시트에 쓰지 못했습니다 — {요약['시트오류']}")
    # 전건이 같은 이유로 걸리면 기준 쪽을 의심해야 한다. 경보가 아니라 보고 안 한 줄로 알린다.
    if 결과들 and n["합격"] == 0 and n["보류"] == 0 and len(결과들) >= 5:
        사유 = {d["내용"].split("(")[0].split(":")[0].strip()
                for _, r in 결과들 for d in r["지적"] if d["등급"] == "치명"}
        if len(사유) == 1:
            줄.append("")
            줄.append(f"⚠️ 검사한 글 전부가 같은 이유로 걸렸습니다({', '.join(사유)}) "
                      f"— 글이 아니라 검수 기준이 어긋난 것일 수 있습니다")
    if 시트url:
        줄.append("")
        줄.append(f"시트: {시트url}")
    return "\n".join(줄)


def 알림보내기(본문: str) -> bool:
    """실제로 보냈는지를 돌려준다.

    ★send_report 는 성공·실패를 삼키고 늘 0을 준다(다른 스크립트가 종료코드로 쓰는
      함수라 손대지 않는다). 토큰이 만료되면 매일 초록불인 채로 사장님만 아무것도
      못 받는 상태가 되므로, 여기서는 한 통이라도 실제로 갔는지 직접 확인한다.
    """
    try:
        from src.notify import send_telegram, split_message, PER_CHAT_INTERVAL_SEC
        조각 = split_message(본문)
        보냄 = 0
        for i, 한조각 in enumerate(조각):
            if send_telegram(한조각):
                보냄 += 1
            if i < len(조각) - 1:
                time.sleep(PER_CHAT_INTERVAL_SEC)
        return 보냄 > 0
    except Exception as e:
        print(f"  [알림] 발송 실패({type(e).__name__})")
        return False


def 사람말로(e: Exception) -> str:
    """흔한 고장은 사장님이 읽고 바로 행동할 수 있는 한 줄로 바꾼다."""
    이름, 글 = type(e).__name__, str(e)
    if 이름 == "KeyError":
        return f"실행에 필요한 값이 등록돼 있지 않습니다({글}) — GitHub Secrets 확인"
    if "PERMISSION" in 글.upper() or "403" in 글:
        return "구글시트에 접근하지 못했습니다 — 서비스 계정이 시트에서 빠졌는지 확인"
    if "404" in 글 and "spreadsheet" in 글.lower():
        return "구글시트를 찾지 못했습니다 — 시트가 지워졌거나 주소가 바뀌었습니다"
    if 이름 in ("Timeout", "ConnectionError", "ConnectTimeout", "ReadTimeout"):
        return "네트워크가 끊겨 검수를 마치지 못했습니다 — 내일 다시 돕니다"
    return 글[:200] or 이름


def _숫자(이름: str, 기본: int) -> int:
    값 = (os.environ.get(이름) or "").strip()
    try:
        return max(1, int(값)) if 값 else 기본
    except ValueError:
        print(f"  [{이름}] '{값}' 은 숫자가 아니라 {기본} 으로 봅니다")
        return 기본


def main() -> int:
    limit = _숫자("GEOMSU_LIMIT", 60)
    마감분 = _숫자("GEOMSU_DEADLINE_MIN", 90)     # 워크플로 제한(120분)보다 넉넉히 앞
    쓰기 = (os.environ.get("GEOMSU_WRITE") or "1").strip() != "0"
    알림 = (os.environ.get("GEOMSU_NOTIFY") or "1").strip() != "0"
    print(f"=== 발행 검수 {datetime.now(KST):%Y-%m-%d %H:%M} (최대 {limit}건) ===", flush=True)

    # ★보고와 경보를 나눈다(2026-07-23 영구 수정).
    #   전에는 '조용히 끝나면 아무도 안 본다'는 이유로 결과가 마음에 안 들면 일부러
    #   실패로 끝내 텔레그램을 울렸다. 그래서 ①고칠 글이 있는 정상 상태와 ②진짜 고장이
    #   같은 문구("검수가 실패했습니다 — 로그를 확인해 주세요")로 나갔고, 사장님은
    #   무슨 일인지 알 수 없었다. 매일 울리면 아무도 안 본다는 문제도 그대로였다.
    #   → 결과는 **매일 보고**로 보낸다. 실패로 끝내는 건 **진짜 고장일 때만**이다.
    try:
        sc = SheetsClient(os.environ["SPREADSHEET_ID"], os.environ["SERVICE_ACCOUNT_JSON"])
        요약 = 검수하기(sc, limit, 쓰기, 마감분)
    except Exception as e:
        이유 = 사람말로(e)
        print(f"  ✗ 고장 — {type(e).__name__}: {e}")
        if 알림 and 알림보내기(f"🚨 발행 검수가 돌지 못했습니다 "
                              f"({datetime.now(KST):%m/%d})\n{이유}\n{_런링크()}"):
            _알림표시남기기()     # ★보낸 게 확인됐을 때만. 아니면 워크플로가 대신 알린다.
        return 1

    # 전멸은 자연스러운 결과가 아니다 — 링크가 낡았거나 네이버가 막고 있다.
    전체 = len(요약["결과들"]) + len(요약["실패들"])
    전멸 = bool(전체) and len(요약["실패들"]) / 전체 > 0.5
    시트url = getattr(sc.spreadsheet, "url", "") or ""
    보냈나 = False

    if 알림:
        본문 = 보고문(요약, 시트url)
        if 전멸:
            본문 = (f"🚨 글을 못 읽은 것이 절반을 넘습니다 — 링크가 낡았거나 "
                    f"네이버가 막고 있을 수 있습니다\n\n{본문}")
        보냈나 = 알림보내기(본문)
        print("  텔레그램 보고 보냄" if 보냈나 else "  ✗ 텔레그램 보고를 보내지 못했습니다")

    # ★보고가 유일한 통로다. 그 통로가 막히면 조용히 초록불로 끝내지 않는다 —
    #   실패로 끝내면 GitHub 이 실패 메일을 보내 두 번째 통로가 된다.
    if 알림 and not 보냈나:
        return 1
    if 전멸 or 요약["시트오류"]:
        if 보냈나:
            _알림표시남기기()
        return 1
    return 0


def _런링크() -> str:
    """Actions 실행 주소. 사장님이 눌러서 바로 볼 수 있게."""
    서버 = os.environ.get("GITHUB_SERVER_URL", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run = os.environ.get("GITHUB_RUN_ID", "")
    return f"{서버}/{repo}/actions/runs/{run}" if all((서버, repo, run)) else ""


def _알림표시남기기() -> None:
    """이미 이유를 담아 알렸다는 표시. 워크플로가 두 번째 알림을 안 보내게."""
    try:
        with open(os.path.join(os.path.dirname(HERE), ".geomsu_alerted"), "w") as f:
            f.write("1")
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
