# -*- coding: utf-8 -*-
"""
발행본 검수 — 발행한 카페 글이 제대로 나갔는지 채점한다. (2026-07-23)

★사장님이 보고 싶은 것은 딱 세 가지다(2026-07-23 원문):
   "상위노출 로직 기준에 맞게 썼는지, 그리고 ai 티 나지 않게 문맥이 괜찮은지,
    실수한게 없는지를 보고싶은거야"

  ① 로직 — 상위노출 기준(키워드 5~6회·글자수·제목 형태·댓글 키워드)
  ② 문맥 — AI 티가 나는가(말투 단조로움·설명서투·3박자 나열·자료 없이 지어냄)
  ③ 실수 — 사고(칸 누락·복붙 중복·[제품명] 안 바꿈·고정문구 변형·자리 어긋남)

  이 셋에 안 들어가는 것은 넣지 않는다. 사장님이 명시적으로 뺀 것:
    다른 글과 겹침(유사문서) / 사진 장수 / 성분·약리 표현 후보 / 사진 자리 /
    키워드로 시작하는 문단  → 전부 제거(교차 대조는 --교차 옵션으로만).

왜 필요한가: 게이트 2종(원고·댓글)은 **만들 때**만 돈다. 직원이 손수 다듬어(2번)
발행한 최종 실물은 아무도 다시 재지 않아, 편집 중에 깨져도 조용히 발행된다.

판정:
  ✗ 치명 → 불합격 (숫자로 잴 수 있는 것 + 명백한 사고)
  △ 주의 → 보류 (사람이 읽고 판단할 것)
  · 참고 → 표시만

입력(JSON 1건 또는 리스트):
{
  "url": "...", "keyword": "지루성두피염", "stage": 5, "disease": "지루성 두피염",
  "author": "글쓴이닉네임", "title": "...", "body": "본문(줄바꿈 유지)",
  "photos": 2, "photo_hashes": ["..."],
  "comments": [{"author":"닉","text":"...","depth":0}, ...],
  "material_path": "통합자료.txt"   // 선택 — 자료 없이 지어냈는지
}

사용법:
  python 발행본_검수.py 발행본.json
  python 발행본_검수.py 발행본들.json --json > 결과.json
  python 발행본_검수.py 발행본들.json --llm     # AI 티 심사(무료 티어 키 있을 때만)
  python 발행본_검수.py 발행본들.json --교차    # 글끼리 겹치는지도 본다(기본 꺼짐)

정본(충돌 시 이깁니다): 원고_프롬프트_복붙용.md · 댓글_고정문구_사전.md · 댓글_결정로그_verbatim.md
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = Path(__file__).parent


def _load(mod_name: str, filename: str):
    """한글 파일명 형제 모듈을 경로로 직접 불러온다(cwd 의존 제거)."""
    spec = importlib.util.spec_from_file_location(mod_name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


원고게이트 = _load("wongo_gate", "원고_게이트검사.py")
댓글게이트 = _load("comment_gate", "댓글_게이트검사.py")

치명, 주의, 참고 = "치명", "주의", "참고"
로직, 문맥, 실수 = "로직", "문맥", "실수"


# ══════════════════════════════════════════════════════════════════════
# 공통 도구
# ══════════════════════════════════════════════════════════════════════
def _ngrams(text: str, n: int = 3):
    t = re.sub(r"\s+", "", text)
    return {t[i:i + n] for i in range(max(0, len(t) - n + 1))}


def _닮음(a: str, b: str) -> float:
    """두 글의 닮은 정도(0~1). 글자 3개씩 끊어 겹치는 비율."""
    ga, gb = _ngrams(a, 3), _ngrams(b, 3)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    common = set(a) & set(b)
    num = sum(a[k] * b[k] for k in common)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return num / (na * nb) if na and nb else 0.0


def _해밍(h1: str, h2: str) -> int:
    """사진 지문(dHash) 두 개가 몇 비트 다른지. 6 이하면 사실상 같은 사진."""
    if not h1 or not h2 or len(h1) != len(h2):
        return 999
    try:
        return bin(int(h1, 16) ^ int(h2, 16)).count("1")
    except ValueError:
        return 999


def _지문목록(post) -> list[str]:
    """사진 지문을 안전하게 꺼낸다(정수·문자열·단색값이 섞여도 죽지 않는다)."""
    raw = post.get("photo_hashes")
    if not isinstance(raw, list):
        return []
    out = []
    for h in raw:
        if not isinstance(h, str) or not re.fullmatch(r"[0-9a-fA-F]{8,32}", h):
            continue
        if len(set(h.lower())) == 1:      # 단색·자리표시 이미지
            continue
        out.append(h.lower())
    return out


def _본문줄(body: str):
    """말투 검사용 줄. (사진N) 자리 표기는 글이 아니므로 뺀다."""
    return [ln.strip() for ln in body.splitlines()
            if ln.strip() and not 원고게이트.PHOTO_LINE.match(ln.strip())]


# ══════════════════════════════════════════════════════════════════════
# ① 로직 — 상위노출 기준 (정본: 원고_프롬프트_복붙용.md)
# ══════════════════════════════════════════════════════════════════════
def 로직검사(post, r) -> list[tuple[str, str, str]]:
    """숫자로 재는 것만. 게이트가 잰 결과를 등급으로 옮기고 제목 형태를 더 본다."""
    out = []
    kw = post.get("keyword") or ""
    title = (post.get("title") or "").strip()

    for name, (ok, msg) in (r.get("gate") or {}).items():
        if ok:
            continue
        if name in ("글자수", "키워드", "줄"):
            out.append((치명, 로직, f"{name}: {msg}"))
        elif name == "사진":
            out.append((주의, 로직, "본문에 사진이 없음"))
        elif name == "감정자음":
            # ★독립검증 M-1: '문맥 축에서 본다'고 주석만 달고 어디서도 안 봤다.
            #   ㅠ를 전부 지워도 지적이 0건이었다 — 정본 밴드(12~23)가 조용히 버려졌다.
            out.append((주의, 문맥, f"감정자음 {msg} — 정본 밴드를 벗어남"))
        elif name == "최장줄":
            out.append((주의, 문맥, f"한 줄이 너무 긺 {msg} — 모바일에서 벽글로 보임"))

    # 제목 (정본 #제목: 키워드 맨 앞 + 질문형 + 20자 안팎)
    if title and kw:
        if not title.startswith(kw):
            out.append((치명, 로직, f"제목이 키워드로 시작하지 않음 — 정본은 맨 앞"))
        # 1차 관측: '이런가요/계신가요'의 '가요'가 빠져 131건(33%) 오탐이었다
        if not re.search(r"[?？]|가요|나요|까요|는지|계세요|있을까|어때|괜찮", title):
            out.append((주의, 로직, "제목이 질문형이 아님"))
        if len(title) > 32:
            out.append((참고, 로직, f"제목 {len(title)}자 — 정본은 20자 안팎"))
    return out


# ══════════════════════════════════════════════════════════════════════
# ② 문맥 — AI 티가 나는가 (정본 #말투·#디테일)
# ══════════════════════════════════════════════════════════════════════
댓글유도_마감 = re.compile(
    r"(댓글\s*(좀\s*)?(부탁|남겨|달아)|추천\s*(좀\s*)?부탁|써보신\s*분|어떻게\s*(해결|하셨)|"
    r"있으면\s*(댓글|알려)|알려\s*주세요|여쭤|조언\s*부탁|공유\s*(좀\s*)?부탁|"
    r"얘기가\s*듣고\s*싶|뭘\s*믿어야|신중하게\s*고르고|어떻게\s*해결하셨|있을까요|있으신가요|계실까요)")
종결어미 = re.compile(r"(더라구요|더라고요|거든요|던데요|네요|까봐|잖아요|더라구|던데|겠어요|"
                      r"해요|어요|아요|예요|이에요|요|죠|다)[\s.,;~!?ㅠㅜ]*$")
삼박자 = re.compile(r"[가-힣]{2,}(하)?고\s+[가-힣]{2,}(하)?고\s+[가-힣]{2,}")
# ★1차 관측(395건): '입니다'만 보고 잡으니 "사진 보이시죠.. 딱 이 상태입니다ㅠㅠ" 같은
#   자연스러운 강조까지 104건(26%) 걸렸다. 정본이 말하는 건 '설명서·정보 요약 말투'다.
#   → ①감정 표시 없이 격식체로 끝나는 줄 ②글을 정리하는 표지어, 둘을 합쳐 센다.
격식종결 = re.compile(r"(합니다|입니다|됩니다|하였습니다|바랍니다)[\s.]*$")
설명표지 = re.compile(r"(첫째|둘째|셋째|다음과\s*같|이러한|따라서|또한|아울러|권장|"
                      r"효과적입니다|중요합니다|필요합니다|주의해야)")
진단명 = re.compile(r"(지루성\s*피부염|지루성\s*두피염|모낭염|건선|아토피|말라세지아|접촉성\s*피부염)")
불용어 = {
    "그냥", "진짜", "정말", "너무", "약간", "조금", "계속", "자꾸", "다시", "이제", "아직",
    "저는", "제가", "근데", "그래서", "그런데", "이거", "그거", "저도", "여기", "거의",
    "하나", "하루", "이번", "저번", "요즘", "때문", "이런", "그런", "같아요", "있어요",
    "없어요", "해서", "하고", "인데", "라서", "부터", "까지", "한번", "정도", "생각",
}


def 문맥검사(post) -> list[tuple[str, str, str]]:
    out = []
    body = post.get("body") or ""
    kw = post.get("keyword") or ""
    lines = _본문줄(body)
    if not lines:
        return [(치명, 실수, "본문이 비어 있음 — 수집 실패이거나 발행 사고")]
    joined = "\n".join(lines)

    # 마무리가 댓글 유도인가 (정본 6슬롯 ⑥ — 댓글판이 안 열리면 글이 헛돈다)
    if not 댓글유도_마감.search(" ".join(lines[-3:])):
        out.append((주의, 로직, "마무리가 댓글 유도로 끝나지 않음 — 댓글판이 안 열림"))

    # 설명서·정보 요약 말투 (정본 '이렇게는 쓰지 않습니다' 1순위)
    격식 = sum(1 for ln in lines
               if 격식종결.search(ln) and not re.search(r"[ㅠㅜ;~!]", ln))
    표지 = len(설명표지.findall(joined))
    # ★독립검증 M-6: 단위가 다른 둘을 그냥 더해, 격식 종결이 0줄인데도 표지어만 5개면
    #   '안내문'이라고 단정했다. 치명은 **격식체로 끝나는 줄이 실제로 여럿일 때만**.
    if 격식 >= 3 and 격식 + 표지 >= 5:
        out.append((치명, 문맥, f"설명서·정보 요약 말투(격식 종결 {격식}줄·정리 표지 {표지}곳) — 안내문으로 읽힘"))
    elif 격식 + 표지 >= 3:
        out.append((주의, 문맥, f"설명투가 섞임(격식 종결 {격식}줄·정리 표지 {표지}곳) — 급하게 쓴 글 느낌이 깨짐"))

    # 3박자 나열 (정본이 콕 집은 AI 티: "간지럽고 건조하고 비듬도")
    삼 = 삼박자.findall(joined)
    if len(삼) >= 2:
        out.append((주의, 문맥, f"'~고 ~고 ~' 3박자 나열 {len(삼)}곳 — 정본이 지목한 AI 티"))

    # 모든 문장이 마침표로 완결 (정본 '이렇게는 쓰지 않습니다')
    마침 = sum(1 for ln in lines if ln.endswith("."))
    if len(lines) >= 8 and 마침 / len(lines) > 0.7:
        out.append((주의, 문맥, f"마침표로 끝나는 줄 {마침}/{len(lines)} — 정갈해서 AI 티"))

    # 종결어미 편중 (정본: 같은 종결이 이어지면 단조롭고 AI 티)
    endings = [m.group(1) for ln in lines
               if (m := 종결어미.search(re.sub(r"[ㅠㅜ]+", "", ln)))]
    if len(endings) >= 8:
        top, cnt = Counter(endings).most_common(1)[0]
        if cnt / len(endings) > 0.6:
            out.append((주의, 문맥, f"종결어미 '{top}'가 {cnt}/{len(endings)}줄 — 리듬이 없음"))

    # 감정자음 (정본: 한 종류로 12~23회 / 그걸로 끝나는 줄은 절반 이하)
    n_tt, n_tw = joined.count("ㅠ"), joined.count("ㅜ")
    총 = n_tt + n_tw
    if 총 and min(n_tt, n_tw) / 총 > 0.25:
        out.append((주의, 문맥, f"ㅠ와 ㅜ를 섞어 씀({n_tt}/{n_tw}) — 정본은 한 종류로"))
    emo_end = sum(1 for ln in lines if re.search(r"[ㅠㅜ]+[\s.,;~!?]*$", ln))
    if emo_end / len(lines) > 0.5:
        out.append((참고, 문맥, f"ㅠ/ㅜ로 끝나는 줄 {emo_end}/{len(lines)} — 절반 이하로"))

    # 같은 단어 반복 (정본: 같은 단어·표현을 두 번 이상 쓰지 않는다)
    words = [w for w in re.findall(r"[가-힣]{2,}", joined)
             if w not in 불용어 and kw and w not in kw and kw not in w]
    rep = [(w, c) for w, c in Counter(words).most_common(5) if c >= 4]
    if rep:
        out.append((참고, 문맥, "같은 단어 반복: " + ", ".join(f"{w}×{c}" for w, c in rep)))

    # 진단명·의학 인과 (정본: 글 전체에서 1번까지)
    dx = 진단명.findall(joined)
    if len(dx) > 1 and not 진단명.search(kw):
        out.append((주의, 로직, f"진단명·의학 인과 {len(dx)}회 — 정본은 1번까지"))

    # 자료 없이 지어냈는가 (정본: 디테일은 반드시 수집 자료에서)
    mp = post.get("material_path")
    if mp and Path(mp).exists():
        mat = Path(mp).read_text(encoding="utf-8", errors="replace")
        bg, mg = _ngrams(joined), _ngrams(mat)
        ratio = len(bg & mg) / len(bg) if bg else 0.0
        post["_자료반영률"] = round(ratio, 3)
        if ratio < 0.15:
            out.append((주의, 문맥, f"수집 자료와 겹치는 표현 {ratio:.0%} — 자료 없이 지어낸 글일 수 있음"))
    return out


# ══════════════════════════════════════════════════════════════════════
# ③ 실수 — 사고 (칸·복붙·치환 누락·자리)
# ══════════════════════════════════════════════════════════════════════
사진문구 = re.compile(r"사진\s*(보이시|보시)|사진\s*첨부|사진처럼")

# 정본 12칸 화자 자리: A 글 B 글 C B D E 글 F 글 G
글쓴이자리 = (1, 3, 8, 10)
B자리 = (2, 5)
단독자리 = (0, 4, 6, 7, 9, 11)


def 실수검사(post) -> list[tuple[str, str, str]]:
    out = []
    body = post.get("body") or ""
    title = post.get("title") or ""
    전체 = title + "\n" + body + "\n" + "\n".join(
        (c.get("text") or "") for c in (post.get("comments") or []))

    # ★★[제품명]을 실제 자사명으로 안 바꾸고 발행 — 가장 큰 사고.
    #   생성본에는 [제품명]이 들어 있고, 직원이 손질(2번)하며 바꿔야 한다.
    #   발행본에 남아 있으면 그대로 나간 것이다.
    # ★독립검증 T-1: 대괄호 안 아무 말이나 자리표시로 보면 [내돈내산]·[질문]·[후기] 같은
    #   흔한 카페 말머리가 전부 치명 오탐이었다. 생성본이 쓰는 자리표시는 종류가 정해져 있으니
    #   그것만 본다.
    남은자리 = re.findall(r"\[(?:제품명|브랜드명|제품|키워드|질병명|상징재|증상명)\]|○○○|×××", 전체)
    if 남은자리:
        out.append((치명, 실수, f"바꾸지 않은 자리표시가 남아 있음: {', '.join(sorted(set(남은자리))[:3])}"))

    # 사진 문구는 있는데 사진이 없음
    photos = post.get("photos")
    if photos is None:
        photos = sum(1 for ln in body.splitlines()
                     if 원고게이트.PHOTO_LINE.match(ln.strip()))
    if 사진문구.search(title + "\n" + body) and photos == 0:
        out.append((치명, 실수, "'사진 보이시죠' 문구는 있는데 사진 0장"))

    # 같은 사진을 이 글 안에서 두 번
    hashes = _지문목록(post)
    for a in range(len(hashes)):
        for b in range(a + 1, len(hashes)):
            if _해밍(hashes[a], hashes[b]) <= 6:
                out.append((주의, 실수, f"{a+1}번·{b+1}번 사진이 사실상 같은 사진"))
                break

    # 본문이 잘렸는가 (수집 사고 또는 발행 사고)
    줄 = _본문줄(body)
    if 줄 and len(re.sub(r"\s", "", 줄[-1])) > 60 and not re.search(r"[.?!~ㅠㅜ;]$", 줄[-1]):
        out.append((주의, 실수, "마지막 줄이 문장 중간에서 끊김 — 잘렸는지 확인"))
    return out


def 댓글_중복검사(comments) -> list[tuple[str, str, str]]:
    """★사장님 지적(2026-07-23): "11번째 댓글과 12번째 댓글이 달라야하는데
    똑같이 발행하는 경우도 있으니까 이런것도 잡고싶은건데"
    """
    out = []
    칸 = [re.sub(r"\s+", "", (c.get("text") or "")) for c in comments]
    for i in range(len(칸)):
        for j in range(i + 1, len(칸)):
            if len(칸[i]) < 10 or len(칸[j]) < 10:
                continue
            if 칸[i] == 칸[j]:
                out.append((치명, 실수, f"{i+1}번째와 {j+1}번째 댓글이 글자까지 똑같음 — 복붙 사고"))
                continue
            닮음 = _닮음(칸[i], 칸[j])
            if 닮음 >= 0.75:
                out.append((치명, 실수, f"{i+1}번째와 {j+1}번째 댓글이 사실상 같은 내용({닮음:.0%} 겹침)"))
            elif 닮음 >= 0.55:
                out.append((주의, 실수, f"{i+1}번째와 {j+1}번째 댓글이 많이 닮음({닮음:.0%})"))
    return out


def 제품전달_검사(comments, 제품명: str) -> list[tuple[str, str, str]]:
    """제품 전달 슬롯(ㄴB·ㄴD)이 살아 있는지.

    ★독립검증 M-2: 생성 시점에는 댓글 게이트 [4]가 [제품명] 자리표시를 세어 이걸 지켰다.
      발행본에서는 그 자리에 실제 이름이 들어가므로 [4]를 껐는데, 대체 검사가 없어
      **제품 전달이 통째로 빠진 글이 통과했다**(ㄴB·ㄴD를 '그 샴푸'로 바꿔도 치명 0).
      실제 제품명(product_name)을 주면 그 자리에 있는지 본다.
    """
    out = []
    if len(comments) != 12:
        return out
    if not 제품명:
        return out          # 못 돌린 사실은 결과의 '미검사' 칸에 담아 끝에 한 줄로 알린다
    자리 = [5, 6]                      # ㄴB(6번째) · ㄴD(7번째)
    있음 = [i for i in 자리 if 제품명 in (comments[i].get("text") or "")]
    if not 있음:
        out.append((치명, 실수, f"제품 전달 칸(6·7번째)에 '{제품명}'이 없음 — 추천이 통째로 빠짐"))
    전체 = sum((c.get("text") or "").count(제품명) for c in comments)
    if 전체 > 3:
        out.append((주의, 실수, f"'{제품명}'이 댓글에 {전체}회 — 정본은 2회(많으면 광고 티)"))
    return out


def 화자패턴검사(comments, author) -> list[tuple[str, str, str]]:
    """댓글 12칸의 실제 화자가 정본 배치와 맞는지. (라벨은 발행되면 사라지고 닉네임만 남는다)"""
    out = []
    if len(comments) != 12:
        return out
    닉 = [(c.get("author") or "").strip() for c in comments]
    a = (author or "").strip()
    if a:
        # ★2026-07-23 실측: 발행본의 칸 배치가 정본 템플릿과 조금 다르다(글쓴이 답글 위치·횟수).
        #   고정 자리로 보면 정상 글 15건이 불합격했다 → 불변식 하나만 본다:
        #   **글쓴이는 답글로만 등장한다**(독립 댓글로 나오면 대화가 깨진다).
        독립글쓴이 = [i for i, c in enumerate(comments)
                      if (c.get("author") or "").strip() == a and not c.get("depth")]
        if 독립글쓴이:
            out.append((치명, 실수,
                        f"글쓴이가 독립 댓글로 등장({', '.join(str(i+1) for i in 독립글쓴이)}번째) — 정본은 답글로만"))
    if 닉[B자리[0]] and 닉[B자리[0]] != 닉[B자리[1]]:
        out.append((치명, 실수, "3번째(원인 설명)와 6번째(제품 전달)가 다른 사람 — 같은 사람이 이어받는다"))
    단독닉 = [닉[i] for i in 단독자리 if 닉[i]]
    if len(set(단독닉)) < len(단독닉):
        겹침 = [n for n, c in Counter(단독닉).items() if c > 1]
        out.append((주의, 실수, f"한 사람이 여러 칸을 맡음({', '.join(겹침)})"))
    return out


# ★2026-07-23 결정(실제 발행본 17건 실측 후): 고정문구를 **원문 일치**로 보지 않는다.
#   실측: 발행된 17건 전부 고정문구가 변주돼 있었다. 구조·순서는 지켰고 문장만 다시 썼다.
#   수백 건이 같은 문장을 쓰면 유사문서로 묶여 상위노출 자체가 죽는다 —
#   문구 통일보다 노출이 우선이므로 **'뜻·기능이 살아 있나'로 검사**한다.
#   (원문과 다른 것 자체는 참고로만 표시. 기능이 빠지면 치명.)
#   질병명은 글마다 다르게 쓴다(실측: 비듬 / 지루성두피 / 지루성두피염) → 이름 대신 역할로 본다.
기능칸 = [
    ("쪽지·처방 되묻기", (r"쪽지", r"처방")),
    ("삭제 예고",        (r"(삭제|지울|지웠|내릴)", r"(몇시간|이따|나중에|곧)")),
    ("검색 유도",        (r"{kw}", r"(검색|찾아|정보)")),
    ("공감 마무리",      (r"(고민|힘들|반복|남일|저장하고|저만|비슷)", r".")),
]


def 기능_자리검사(comments, keyword, disease) -> list[tuple[str, str, str]]:
    """고정문구가 하던 '일'이 댓글판 어딘가에 살아 있는지 본다(문장은 달라도 된다)."""
    out = []
    if not comments:
        return out
    칸 = [(c.get("text") or "") for c in comments]
    # 공백 차이로 어긋나는 걸 막는다("지루성 두피염" vs "지루성두피염" — 실측 16건 오탐)
    민 = [re.sub(r"\s", "", t) for t in 칸]
    for 이름, (p1, p2) in 기능칸:
        a = p1.format(kw=re.escape(re.sub(r"\s", "", keyword)),
                      disease=re.escape(re.sub(r"\s", "", disease)))
        b = re.sub(r"\s\*", "", p2)
        어디 = [i for i, t in enumerate(민)
                if re.search(a, t) and re.search(b, t)]
        if not 어디:
            out.append((치명, 실수, f"'{이름}' 칸이 없음 — 댓글판의 그 역할이 통째로 빠졌다"))
    # 원문 그대로인지는 참고로만
    원문 = [("쪽지", 댓글게이트.T1_C), ("삭제예고", 댓글게이트.T1_B2_OPEN),
            ("검색유도", 댓글게이트.T1_F.format(kw=keyword)),
            ("질병마무리", 댓글게이트.T1_G.format(disease=disease))]
    다른것 = [이름 for 이름, 문구 in 원문 if 문구 not in "\n".join(칸)]
    if 다른것:
        out.append((참고, 실수, f"고정문구를 바꿔 씀({', '.join(다른것)}) — 유사문서 방지에는 오히려 유리"))
    return out


def 댓글_라벨복원(comments, author):
    """카페 댓글(닉네임·답글깊이)을 게이트가 읽는 12칸 라벨 텍스트로 되돌린다."""
    letters, lines = {}, []
    for c in comments:
        nick = (c.get("author") or "").strip()
        if author and nick == author.strip():
            label = "글쓴이"
        else:
            if nick not in letters:
                letters[nick] = chr(ord("A") + len(letters))
            label = letters[nick]
        prefix = "ㄴ " if c.get("depth", 0) else ""
        text = re.sub(r"\s*\n\s*", " ", (c.get("text") or "").strip())
        lines.append(f"{prefix}{label} : {text}")
    return "\n\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
# 한 건 채점
# ══════════════════════════════════════════════════════════════════════
def 검수(post: dict) -> dict:
    kw = post.get("keyword") or ""
    body = post.get("body") or ""
    title = post.get("title") or ""
    findings: list[tuple[str, str, str]] = []

    # 단계 정규화 — 3/4/5가 아니면 로직 검사가 통째로 빠지므로 그렇게 말한다
    try:
        stage = int(post.get("stage"))
    except (TypeError, ValueError):
        stage = None
    post["stage"] = stage
    if stage not in 원고게이트.BANDS:
        findings.append((치명, 로직,
            f"단계(3/4/5)가 없거나 이상함: {post.get('stage')!r} — 글자수·키워드 검사가 빠진다"))
    if not kw:
        findings.append((치명, 로직, "키워드가 비어 있음 — 검사 자체가 불가"))
    if not title:
        findings.append((주의, 실수, "제목이 비어 있음 — 수집 누락 의심"))

    # 게이트로 숫자 측정 (키워드가 비면 count 가 쓰레기값이 되므로 대체값)
    r = 원고게이트.measure(title, body, kw or "\x00없음\x00", stage=(stage if kw else None))
    # ★독립검증 T-2: 시트에서 오는 값은 문자열이 기본이라 photos='2' 면 게이트 안에서
    #   비교하다 죽었다(배치 전체 중단). 숫자로 정규화하고, 숫자가 아니면 본문에서 센다.
    photos = post.get("photos")
    try:
        photos = int(photos) if photos is not None else None
    except (TypeError, ValueError):
        photos = sum(1 for ln in body.splitlines()
                     if 원고게이트.PHOTO_LINE.match(ln.strip()))
    post["photos"] = photos
    if photos is not None:
        r["photos"] = photos
        if stage in 원고게이트.BANDS and kw:
            r["gate"] = 원고게이트._grade(r, 원고게이트.BANDS[stage])
    측정 = {k: r[k] for k in ("chars", "lines", "longest", "photos",
                             "kw_title", "kw_body", "kw_total", "main_emo", "main_cnt")}

    findings += 로직검사(post, r)
    findings += 문맥검사(post)
    findings += 실수검사(post)

    # 댓글
    comments = post.get("comments") or []
    측정["댓글수"] = len(comments)
    if comments:
        author = (post.get("author") or "").strip()
        닉모음 = {(c.get("author") or "").strip() for c in comments}
        글쓴이확인 = bool(author) and author in 닉모음
        if not 글쓴이확인:
            findings.append((주의, 실수, "글쓴이 닉네임을 댓글에서 못 찾음 — 배치 검사는 건너뜀(수집 확인)"))

        labeled = 댓글_라벨복원(comments, author if 글쓴이확인 else "")
        post["_댓글_라벨복원"] = labeled
        fails, warns = 댓글게이트.check(
            labeled, kw, post.get("disease") or kw, post.get("product") or "샴푸")
        구조검사 = ("[1]", "[8]", "[9]", "[5]")
        for f in fails:
            # [4]는 생성 시점 검사다([제품명] 자리표시가 1~2회 있어야 한다는 뜻).
            # 발행본에는 그 자리에 실제 제품명이 들어가 있어야 하므로 여기선 보지 않는다
            # (자리표시가 남아 있는 사고는 실수검사가 치명으로 잡는다).
            if f.startswith("[4]"):
                continue
            if not 글쓴이확인 and f.startswith(구조검사):
                findings.append((참고, 실수, f"(글쓴이 미확인·판정 보류) {f}"))
                continue
            # 축·심각도 배정(독립검증 M-7): [1]칸순서·[2]고정문구·[8]글쓴이자리 = 구조 사고,
            # [6]금칙어·[7]D6·[9-1]A칸·[10]ㄴB = 설득/말투, [3]키워드 = 상위노출 로직
            if f.startswith("[3]"):
                findings.append((치명, 로직, f"댓글 {f}"))
            elif f.startswith("[2]"):
                # 원문 일치는 참고. 기능이 살아 있는지는 기능_자리검사가 치명으로 본다.
                findings.append((참고, 실수, f"댓글 {f}"))
            elif f.startswith("[1]"):
                # 라벨 순서: 실제 발행본은 정본 템플릿과 칸 배치가 조금 다르다(2026-07-23 실측).
                # 칸 수(12)는 아래에서 따로 치명으로 본다.
                findings.append((주의, 실수, f"댓글 {f}"))
            elif f.startswith("[8]"):
                # 글쓴이가 '독립 댓글로 등장'하는 것만 치명(화자패턴검사). 횟수는 참고.
                findings.append((참고 if "회" in f else 치명, 실수, f"댓글 {f}"))
            elif f.startswith(("[6]", "[7]")):
                # ★사장님 결정(2026-07-23): "치료용은 검수기준 제외. 적어도 여기서는.
                #   대안비교문장도 제외." → 발행본 검수에서는 이 둘을 안 본다.
                #   (생성 시점 게이트에는 그대로 남아 있다.)
                if "치료용" in f or "대안 비교" in f or "D6" in f:
                    continue
                findings.append((치명, 문맥, f"댓글 {f}"))
            elif f.startswith(("[9", "[10")):      # [9]·[9-1]·[10] 전부
                if "대안 비교" in f:                  # 사장님 결정으로 제외
                    continue
                findings.append((주의, 문맥, f"댓글 {f}"))
            else:
                findings.append((주의, 실수, f"댓글 {f}"))
        for w in warns:
            findings.append((참고, 실수, f"댓글 {w}"))

        if 글쓴이확인:
            findings += 화자패턴검사(comments, author)
        findings += 기능_자리검사(comments, kw, post.get("disease") or kw)
        findings += 제품전달_검사(comments, post.get("product_name") or "")
        findings += 댓글_중복검사(comments)
    else:
        findings.append((치명, 실수, "댓글 0개 — 댓글판이 아예 없음(또는 수집 실패)"))

    치명수 = sum(1 for g, _, _ in findings if g == 치명)
    주의수 = sum(1 for g, _, _ in findings if g == 주의)
    return {
        "url": post.get("url"), "keyword": kw, "stage": stage,
        "판정": "불합격" if 치명수 else ("보류" if 주의수 else "합격"),
        "치명": 치명수, "주의": 주의수,
        "측정": 측정, "자료반영률": post.get("_자료반영률"),
        # 못 돌린 검사를 조용히 넘기지 않는다(무엇을 안 봤는지 끝에 한 줄로 알린다)
        "미검사": ([] if post.get("product_name") else ["제품 전달(제품명 미지정)"])
                  + ([] if _지문목록(post) else ["사진 중복(지문 없음)"]),
        "지적": [{"등급": g, "축": x, "내용": m} for g, x, m in findings],
    }


# ══════════════════════════════════════════════════════════════════════
# 교차 대조 — 기본 꺼짐 (사장님: "다른글과 겹치는건 상관 없고")
# ══════════════════════════════════════════════════════════════════════
def 교차검사(posts, results, 임계: float = 0.55):
    vecs = [Counter(_ngrams(p.get("body") or "", 3)) for p in posts]
    for i in range(len(posts)):
        for j in range(i + 1, len(posts)):
            if _cosine(vecs[i], vecs[j]) >= 임계:
                sim = _cosine(vecs[i], vecs[j])
                for k in (i, j):
                    other = posts[j if k == i else i].get("keyword") or "?"
                    results[k]["지적"].append(
                        {"등급": 주의, "축": 실수, "내용": f"다른 글과 {sim:.0%} 겹침(‘{other}’)"})
                    results[k]["주의"] += 1
                    if results[k]["판정"] == "합격":
                        results[k]["판정"] = "보류"

    지문 = [(i, n, h) for i, p in enumerate(posts)
            for n, h in enumerate(_지문목록(p), 1)]
    겹친글 = {}
    for x in range(len(지문)):
        for y in range(x + 1, len(지문)):
            i, n1, h1 = 지문[x]
            j, n2, h2 = 지문[y]
            if i != j and _해밍(h1, h2) <= 6:
                겹친글.setdefault(i, set()).add(posts[j].get("keyword") or "?")
                겹친글.setdefault(j, set()).add(posts[i].get("keyword") or "?")
    for i, 짝 in 겹친글.items():
        results[i]["지적"].append(
            {"등급": 주의, "축": 실수,
             "내용": f"같은 사진을 다른 글에도 씀 ({', '.join(sorted(짝)[:3])})"})
        results[i]["주의"] += 1
        if results[i]["판정"] == "합격":
            results[i]["판정"] = "보류"


# ══════════════════════════════════════════════════════════════════════
# AI 티 심사 — 무료 티어만 (기본 꺼짐, 키 없으면 조용히 건너뜀)
# ══════════════════════════════════════════════════════════════════════
_FREE_PROVIDERS = [
    # (이름, 주소, 모델, 환경변수, 키 파일) — 하루 한도 큰 쪽부터. 둘 다 카드 등록 없는 무료 티어.
    ("cerebras", "https://api.cerebras.ai/v1/chat/completions", "llama-3.3-70b",
     "CEREBRAS_API_KEY", "cerebras_key.txt"),
    ("groq", "https://api.groq.com/openai/v1/chat/completions", "llama-3.3-70b-versatile",
     "GROQ_API_KEY", "groq_key.txt"),
]
_KEY_DIR = HERE / "secrets"      # .gitignore 의 **/secrets/ 로 커밋에서 제외되는 폴더


def _키(env: str, 파일: str) -> str:
    """환경변수 → secrets 파일 순으로 찾는다.

    사장님은 발급받은 키를 secrets 폴더에 메모장으로 붙여넣기만 하면 된다.
    (환경변수 설정은 번거롭고, 이 폴더는 깃에 올라가지 않는다.)
    """
    v = os.environ.get(env)
    if v:
        return _키정리(v)
    f = _KEY_DIR / 파일
    if f.exists():
        # ★독립검증 M-5: 메모장이 UTF-8로 저장하면 앞에 BOM(﻿)을 몰래 붙인다.
        #   BOM 은 공백이 아니라 .strip() 으로 안 지워지고, 서버는 401 만 돌려준다.
        #   비개발자가 스스로 풀 수 없는 함정이라 여기서 치운다(utf-8-sig).
        return _키정리(f.read_text(encoding="utf-8-sig", errors="replace"))
    return ""


_UA = "cafe-external-audit/1.0"     # 기본 파이썬 UA 는 Cloudflare 가 막는다(403 code 1010)
_모델캐시: dict[str, str] = {}

# 품질 순(큰 모델부터). 목록에 있는 첫 번째를 쓴다.
_모델선호 = ("gpt-oss-120b", "llama-3.3-70b-versatile", "llama-3.3-70b", "zai-glm-4.7",
             "llama-4-scout-17b-16e-instruct", "qwen-3-32b", "gemma-4-31b")


def _모델(chat_url: str, key: str, 기본: str) -> str:
    """그 계정이 실제로 쓸 수 있는 모델을 물어서 고른다.

    ★모델 이름을 코드에 적어두면 공급사가 목록을 바꿀 때 조용히 404가 난다.
      실제로 그렇게 됐다(2026-07-23: 적어둔 llama-3.3-70b 가 이 계정에 없어 404).
    """
    if chat_url in _모델캐시:
        return _모델캐시[chat_url]
    골라진 = 기본
    try:
        import requests
        r = requests.get(chat_url.replace("/chat/completions", "/models"),
                         headers={"Authorization": f"Bearer {key}", "User-Agent": _UA}, timeout=15)
        if r.status_code == 200:
            있는것 = [m.get("id") for m in r.json().get("data", []) if m.get("id")]
            골라진 = next((p for p in _모델선호 if p in 있는것), 있는것[0] if 있는것 else 기본)
    except Exception:
        pass
    _모델캐시[chat_url] = 골라진
    return 골라진


def _키정리(원문: str) -> str:
    """붙여넣다 딸려온 것들을 치운다 — BOM·따옴표·설명줄·앞뒤 공백."""
    for 줄 in 원문.splitlines():
        줄 = 줄.replace("﻿", "").strip().strip('"\'').strip()
        if 줄.startswith(("#", "//")) or not 줄:
            continue
        m = re.search(r"(csk-[\w-]+|gsk_[\w-]+|sk-[\w-]+)", 줄)   # 설명과 같이 붙여넣은 경우
        return m.group(1) if m else 줄
    return ""
_LLM_SYSTEM = (
    "너는 네이버 카페 글을 읽는 평범한 사용자다. 이 글이 '광고팀이 쓴 티'가 나는지, "
    "실제로 고생하는 사람이 급하게 쓴 글로 읽히는지만 본다. 문법이나 완성도를 칭찬하지 마라 "
    "— 오히려 너무 정갈하면 AI 티다. 반드시 JSON만 출력한다: "
    '{"사람같은가":1-5,"어디서_티나나":["...","..."]}')


def llm_심사(post: dict) -> dict | None:
    try:
        import requests
    except ImportError:
        return None
    user = f"[제목] {post.get('title')}\n[본문]\n{(post.get('body') or '')[:2500]}"
    for name, url, model, env, 파일 in _FREE_PROVIDERS:
        key = _키(env, 파일)
        if not key:
            continue
        try:
            resp = requests.post(
                url, headers={"Authorization": f"Bearer {key}",
                              "Content-Type": "application/json", "User-Agent": _UA},
                json={"model": _모델(url, key, model),
                      "messages": [{"role": "system", "content": _LLM_SYSTEM},
                                   {"role": "user", "content": user}],
                      # gpt-oss 계열은 생각 과정을 먼저 쓴다. 400으로는 답이 잘려
                      # JSON 이 깨지고 결과가 통째로 사라졌다(2026-07-23 실측).
                      "max_tokens": 2000, "temperature": 0.2},
                timeout=60)
            if resp.status_code != 200:
                continue
            m = re.search(r"\{.*\}", resp.json()["choices"][0]["message"]["content"], re.S)
            if m:
                out = json.loads(m.group(0))
                out["_provider"] = name
                return out
        except Exception:
            continue
    return None


# ══════════════════════════════════════════════════════════════════════
def _출력(res: dict):
    mark = {"합격": "O", "보류": "△", "불합격": "X"}[res["판정"]]
    print(f'\n[{mark}] {res["판정"]}  · {res["keyword"]} (단계 {res["stage"]})  {res.get("url") or ""}')
    m = res["측정"]
    print(f'   글자 {m["chars"]} · 줄 {m["lines"]} · 키워드 본문 {m["kw_body"]}(제목 {m["kw_title"]}) '
          f'· 댓글 {m["댓글수"]} · 사진 {m["photos"]} · {m["main_emo"]} {m["main_cnt"]}')
    if res.get("자료반영률") is not None:
        print(f'   자료 반영 {res["자료반영률"]:.0%}')
    for 축 in (로직, 문맥, 실수):
        묶음 = [d for d in res["지적"] if d["축"] == 축]
        if not 묶음:
            continue
        print(f'   [{축}]')
        기호 = {치명: "✗", 주의: "△", 참고: "·"}
        for d in 묶음:
            print(f'     {기호[d["등급"]]} {d["내용"]}')
    if res.get("llm"):
        L = res["llm"]
        print(f'   [AI 티/{L.get("_provider")}] 사람같은가 {L.get("사람같은가")}/5')
        for s in (L.get("어디서_티나나") or [])[:5]:
            print(f'     · {s}')


def 키확인() -> int:
    """AI 티 심사용 무료 키가 제대로 들어갔는지만 본다. 키 값은 화면에 찍지 않는다."""
    print("=== AI 티 심사 키 확인 ===")
    print(f"  키를 두는 곳: {_KEY_DIR}")
    산 = False
    for name, url, model, env, 파일 in _FREE_PROVIDERS:
        key = _키(env, 파일)
        if not key:
            print(f"  [ ] {name:9s} — 없음  (여기에 붙여넣기: {_KEY_DIR / 파일})")
            continue
        try:
            import requests
            쓸모델 = _모델(url, key, model)
            r = requests.post(
                url, headers={"Authorization": f"Bearer {key}",
                              "Content-Type": "application/json", "User-Agent": _UA},
                json={"model": 쓸모델, "messages": [{"role": "user", "content": "안녕"}],
                      "max_tokens": 5},
                timeout=20)
            if r.status_code == 200:
                print(f"  [O] {name:9s} — 잘 됩니다 (키 …{key[-4:]} · 모델 {쓸모델})")
                산 = True
            else:
                print(f"  [X] {name:9s} — 키는 있는데 거절당했습니다 (응답 {r.status_code}) — 키를 다시 확인")
        except ImportError:
            print("  requests 가 없습니다:  pip install requests")
            return 1
        except Exception as e:
            print(f"  [X] {name:9s} — 연결 실패: {type(e).__name__}")
    if 산:
        print("\n  준비 끝. 이제 검수할 때 --llm 을 붙이면 AI 티 심사가 같이 돕니다.")
        return 0
    print("\n  아직 쓸 수 있는 키가 없습니다.")
    return 2      # 1은 '불합격'이라 겹치면 자동화가 오독한다(독립검증 M-3)


def html리포트(results: list[dict], 경로: Path):
    """사장님·직원이 눈으로 보는 실물. 콘솔 출력은 실무에서 아무도 안 본다."""
    색 = {"합격": "#0b8a3d", "보류": "#c77700", "불합격": "#d21f1f"}
    기호 = {치명: "✗", 주의: "△", 참고: "·"}
    n = Counter(r["판정"] for r in results)
    카드 = []
    for r in sorted(results, key=lambda x: {"불합격": 0, "보류": 1, "합격": 2}[x["판정"]]):
        m = r["측정"]
        지적 = ""
        for 축 in (로직, 문맥, 실수):
            묶 = [d for d in r["지적"] if d["축"] == 축]
            if not 묶:
                continue
            줄 = "".join(
                f'<li class="{d["등급"]}">{기호[d["등급"]]} {d["내용"]}</li>' for d in 묶)
            지적 += f'<div class="axis"><b>{축}</b><ul>{줄}</ul></div>'
        llm = ""
        if r.get("llm"):
            L = r["llm"]
            팁 = "".join(f"<li>· {s}</li>" for s in (L.get("어디서_티나나") or [])[:5])
            llm = (f'<div class="axis"><b>AI 티 심사</b> — 사람 같은가 '
                   f'<b>{L.get("사람같은가")}/5</b><ul>{팁}</ul></div>')
        링크 = (f'<a href="{r["url"]}" target="_blank">글 열기</a>'
                if str(r.get("url") or "").startswith("http") else (r.get("url") or ""))
        카드.append(f'''<section>
  <h2><span class="badge" style="background:{색[r["판정"]]}">{r["판정"]}</span>
      {r["keyword"]} <small>단계 {r["stage"]}</small></h2>
  <p class="meta">글자 {m["chars"]} · 줄 {m["lines"]} · 키워드 본문 {m["kw_body"]}(제목 {m["kw_title"]})
     · 댓글 {m["댓글수"]} · 사진 {m["photos"]} · {m["main_emo"]} {m["main_cnt"]}
     <span class="url">{링크}</span></p>
  {지적 or '<p class="ok">지적 없음</p>'}{llm}
</section>''')
    못돈 = Counter(x for r in results for x in r.get("미검사", []))
    못돈줄 = "".join(f"<li>{k} — {v}건</li>" for k, v in 못돈.items())
    경로.write_text(f'''<!doctype html><meta charset="utf-8">
<title>발행본 검수 결과</title>
<style>
 body{{font:15px/1.7 -apple-system,"맑은 고딕",sans-serif;max-width:900px;margin:24px auto;padding:0 16px;color:#1f2933}}
 h1{{font-size:22px;margin-bottom:4px}} h2{{font-size:17px;margin:0 0 6px}}
 .sum{{display:flex;gap:10px;margin:14px 0 22px}}
 .sum div{{flex:1;text-align:center;border:1px solid #e3e6ea;border-radius:10px;padding:10px}}
 .sum b{{display:block;font-size:24px}}
 section{{border:1px solid #e3e6ea;border-radius:10px;padding:14px 16px;margin-bottom:12px}}
 .badge{{color:#fff;border-radius:6px;padding:2px 9px;font-size:13px;margin-right:6px}}
 .meta{{color:#6b7684;font-size:13px;margin:0 0 8px}} .url a{{margin-left:8px}}
 .axis{{margin-top:8px}} .axis b{{font-size:13px;color:#4e5968}}
 ul{{margin:4px 0 0;padding-left:18px}} li{{margin:2px 0}}
 li.치명{{color:#d21f1f}} li.주의{{color:#c77700}} li.참고{{color:#8b95a1}}
 .ok{{color:#0b8a3d;margin:6px 0 0}} .skip{{color:#8b95a1;font-size:13px;margin-top:18px}}
</style>
<h1>발행본 검수 결과</h1>
<p class="meta">{len(results)}건 — 상위노출 로직 · AI 티(문맥) · 실수 세 축</p>
<div class="sum">
 <div><b style="color:{색["합격"]}">{n["합격"]}</b>합격</div>
 <div><b style="color:{색["보류"]}">{n["보류"]}</b>보류(사람이 봄)</div>
 <div><b style="color:{색["불합격"]}">{n["불합격"]}</b>불합격</div>
</div>
{"".join(카드)}
{f'<div class="skip">못 돌린 검사<ul>{못돈줄}</ul></div>' if 못돈줄 else ""}
''', encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="발행본 검수 — 로직·문맥(AI티)·실수 세 축으로 채점")
    ap.add_argument("input", nargs="?", help="발행본 JSON (객체 1건 또는 리스트)")
    ap.add_argument("--json", action="store_true", help="사람용 출력 대신 JSON")
    ap.add_argument("--llm", action="store_true",
                    help="AI 티 심사 추가(무료 티어 키 있을 때만). "
                         "⚠️본문 앞 2500자가 외부 API로 전송됩니다.")
    ap.add_argument("--교차", action="store_true",
                    help="글끼리 겹치는지·같은 사진 돌려썼는지도 본다(기본 꺼짐)")
    ap.add_argument("--키확인", action="store_true", help="AI 티 심사용 무료 키가 들어갔는지 확인")
    ap.add_argument("--html", nargs="?", const="검수결과.html",
                    help="결과를 볼 수 있는 화면(HTML)으로 저장하고 연다")
    ap.add_argument("--유사임계", type=float, default=0.55)
    a = ap.parse_args()
    if a.키확인:                       # 축약형(--키)도 여기로 온다
        return 키확인()
    if not a.input:
        ap.error("검수할 JSON 파일을 주세요 (또는 --키확인)")
    if not Path(a.input).exists():
        print(f"파일이 없습니다: {a.input}")
        return 2

    data = json.loads(Path(a.input).read_text(encoding="utf-8"))
    posts = data if isinstance(data, list) else [data]
    results = [검수(p) for p in posts]
    if a.교차 and len(posts) > 1:
        교차검사(posts, results, a.유사임계)
    if a.llm:
        for p, r in zip(posts, results):
            if got := llm_심사(p):
                r["llm"] = got

    if a.html:
        경로 = Path(a.html)
        html리포트(results, 경로)
        print(f"검수 결과: {경로.resolve()}")
        try:
            os.startfile(경로.resolve())      # 바로 열어준다(직원이 명령창을 안 봐도 되게)
        except Exception:
            pass

    if a.json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
    elif not a.html:
        for r in results:
            _출력(r)
        n = Counter(r["판정"] for r in results)
        print(f'\n=== 합계 {len(results)}건 — 합격 {n["합격"]} · 보류 {n["보류"]} · 불합격 {n["불합격"]}')
        # 못 돌린 검사는 조용히 넘기지 않고 끝에 한 줄로 알린다(글마다 붙이면 노이즈)
        못돈 = Counter(x for r in results for x in r.get("미검사", []))
        for 항목, c in 못돈.items():
            print(f'    ※ 못 돌린 검사: {항목} — {c}건')
    return 1 if any(r["판정"] == "불합격" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
