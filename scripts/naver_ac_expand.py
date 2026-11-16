"""네이버 검색창 자동완성 늘려 치기(세부키워드 방식) — 읽기 전용 시험(지시 1116-0030 욕구 빈틈조사 · 2026-11-16).

씨앗마다: 씨앗 → 씨앗+' ' → 씨앗+' '+가~하 첫 글자 열네 개 → 나온 말 중 경계 낱말이 든 것을 다시 쳐서(깊이 2) 나온 말 전부.
검색량은 재지 않는다(수집 PC 의 검색광고 도구가 잰다). 결과 out/naver_ac.json: [{q, depth, items}] + 모든 말 목록.
환경: KEYWORDS(쉼표 씨앗) · BOUND(쉼표 경계 낱말 — 비우면 씨앗) · MAX_Q(부르기 상한, 기본 900).
"""
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

AC = "https://ac.search.naver.com/nx/ac"
SUFFIX = ["", " "] + [" " + c for c in "가나다라마바사아자차카타파하"]


def ac(q):
    p = {"q": q, "con": "1", "frm": "nv", "ans": "2", "r_format": "json", "r_enc": "UTF-8",
         "r_unicode": "0", "t_koreng": "1", "run": "2", "rev": "4", "q_enc": "UTF-8", "st": "100"}
    req = urllib.request.Request(AC + "?" + urllib.parse.urlencode(p),
                                 headers={"User-Agent": "Mozilla/5.0", "Referer": "https://search.naver.com/"})
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read().decode("utf-8"))
    out = []
    for grp in d.get("items", []):
        for it in grp:
            if it and isinstance(it, list) and it[0]:
                out.append(str(it[0]).strip())
    return out


def main():
    f = Path("probe_inputs/naver_ac.json")
    if not os.environ.get("KEYWORDS") and f.exists():  # push 로 돌 때 — 입력 파일에서
        cfg = json.loads(f.read_text(encoding="utf-8"))
        os.environ["KEYWORDS"] = ",".join(cfg.get("keywords", []))
        os.environ["BOUND"] = ",".join(cfg.get("bound", []))
        os.environ["MAX_Q"] = str(cfg.get("max_q", 900))
    seeds = [s.strip() for s in os.environ.get("KEYWORDS", "").split(",") if s.strip()]
    bound = [s.strip().replace(" ", "") for s in os.environ.get("BOUND", "").split(",") if s.strip()] or [s.replace(" ", "") for s in seeds]
    max_q = int(os.environ.get("MAX_Q", "900") or 900)
    done, log, allw, n, fails = set(), [], {}, 0, 0
    queue = [(s + suf, 1) for s in seeds for suf in SUFFIX]
    while queue and n < max_q:
        q, depth = queue.pop(0)
        if q in done:
            continue
        done.add(q)
        try:
            items = ac(q)
        except Exception as e:  # 막히면 까닭만 남기고 다음
            fails += 1
            log.append({"q": q, "depth": depth, "error": repr(e)[:200]})
            time.sleep(2)
            continue
        n += 1
        log.append({"q": q, "depth": depth, "items": items})
        for w in items:
            allw.setdefault(w, q)
            if depth < 2 and any(b in w.replace(" ", "") for b in bound) and w not in done:
                queue.append((w, depth + 1))
                queue.append((w + " ", depth + 1))
        time.sleep(0.35)
    Path("out").mkdir(exist_ok=True)
    Path("out/naver_ac.json").write_text(json.dumps(
        {"seeds": seeds, "bound": bound, "calls": n, "fails": fails, "left_in_queue": len(queue),
         "words": [{"말": w, "처음_나온_검색": q} for w, q in allw.items()], "log": log},
        ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"calls": n, "fails": fails, "words": len(allw), "left": len(queue)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
