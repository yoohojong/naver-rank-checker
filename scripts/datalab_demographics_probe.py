# -*- coding: utf-8 -*-
"""데이터랩 성비·연령대 — 기존(지식인용) NAVER_OPENAPI_CLIENT_ID/SECRET 재사용 시도.

배경 (team-project 사장님 지시 2026-08-26, "2-2. 네이버 데이터랩에서 성비·연령대
비율을 찾아 자료로 달라"):
  team-project 쪽에는 이 기능을 쓸 네이버 키가 없다(NAVER_CLIENT_ID/SECRET 미설정).
  사장님이 "아니 근데 이미 있을텐데 분명히"라고 하셨고 — 실제로 이 저장소
  (naver-rank-checker)에 카페외부 지식인 수집용으로 등록된 NAVER_OPENAPI_CLIENT_ID/
  SECRET 이 살아서 돌고 있다(cafe-material-collect.yml 실행 이력 다수 성공).

  문제는 그 키가 "검색"(지식인) API 용으로 등록됐다는 것 — 같은 네이버 애플리케이션에
  "데이터랩(검색어트렌드)" 사용 API 체크박스가 켜져 있는지는 실제로 호출해보기 전엔
  모른다. 이 스크립트가 그 확인이다: 한 키워드로 먼저 1회 찔러보고(프로브),
  성공하면 곧바로 top-30 전체를 돈다.

  ⚠️ team-project 코드(cafe-external/naver_datalab_demographics.py)와 로직은
  동일 — 이 저장소가 쓰는 env var 이름(NAVER_OPENAPI_CLIENT_ID/SECRET)에 맞춘
  독립 실행본이다(이 저장소는 team-project 를 체크아웃할 권한이 없는 별도
  저장소라 로직을 그대로 옮겨왔다). 키워드 목록은
  team-project/cafe-external/키워드_비타겟_통합정리_2026-08-26.csv 의
  TARGET 판정 중 검색량 상위 30개를 그대로 박아넣었다(교차 체크아웃 불가).

방법 — 데이터랩은 "이 키워드의 성비/연령이 몇 %"를 직접 안 준다. 같은 기간을
  성별/연령대별로 따로 물어(호출을 쪼개서) 나온 상대지수를 비교해 비율을 역산한다:
    성비 = 남성 호출 평균지수 / (남성 호출 평균지수 + 여성 호출 평균지수)
    연령대 비율 = 그 연령대 호출 평균지수 / (전 연령대 호출 평균지수 합)
  절대 인원수가 아니라 "상대적으로 어느 쪽이 더 찾는가"의 근사 비율.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, timedelta

from curl_cffi import requests

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "data", "datalab_demographics_result.json")

DATALAB_URL = "https://openapi.naver.com/v1/datalab/search"

AGE_BUCKETS = {
    "1": "0~12세", "2": "13~18세", "3": "19~24세", "4": "25~29세",
    "5": "30~34세", "6": "35~39세", "7": "40~44세", "8": "45~49세",
    "9": "50~54세", "10": "55~60세", "11": "60세 이상",
}
GENDERS = {"m": "남성", "f": "여성"}

# team-project cafe-external/키워드_비타겟_통합정리_2026-08-26.csv 의 TARGET 판정
# 중 검색량 내림차순 상위 30개 (2026-08-26 기준, 교차 저장소 체크아웃 불가라 고정).
TOP30_KEYWORDS = [
    "샴푸 지루성두피염", "바디워시 도브바디스크럽", "바디워시 닥터브로너스",
    "샴푸 두피스케일링", "샴푸 아윤채샴푸", "샴푸 로마샴푸", "샴푸 닥터그루트샴푸",
    "샴푸 헤드앤숄더", "샴푸 지루성두피염샴푸", "샴푸 두피뾰루지", "샴푸 볼빅샴푸",
    "바디워시 일리윤바디워시", "바디워시 등드름바디워시", "샴푸 비듬샴푸",
    "바디워시 엉덩이뾰루지", "바디워시 해피바스바디워시", "샴푸 아로마티카샴푸",
    "샴푸 두피가려움", "바디워시 등드름없애는법", "샴푸 청소년샴푸", "샴푸 모낭염치료",
    "바디워시 바이오가바디워시", "바디워시 등드름", "샴푸 아모스녹차실감샴푸",
    "바디워시 스트라이덱스패드", "샴푸 비듬없애는방법", "샴푸 쿨링샴푸", "샴푸 쿨샴푸",
    "바디워시 세타필바디워시", "바디워시 모공각화증바디워시",
]


def _credentials():
    cid = os.environ.get("NAVER_OPENAPI_CLIENT_ID", "").strip()
    sec = os.environ.get("NAVER_OPENAPI_CLIENT_SECRET", "").strip()
    return cid, sec


def _call(cid, sec, keyword, months=3, gender=None, ages=None):
    end = date.today()
    start = end - timedelta(days=30 * months)
    body = {
        "startDate": start.strftime("%Y-%m-%d"),
        "endDate": end.strftime("%Y-%m-%d"),
        "timeUnit": "month",
        "keywordGroups": [{"groupName": keyword, "keywords": [keyword]}],
    }
    if gender:
        body["gender"] = gender
    if ages:
        body["ages"] = ages
    r = requests.post(
        DATALAB_URL,
        headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": sec,
                 "Content-Type": "application/json"},
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"), timeout=20)
    if r.status_code != 200:
        body_txt = (r.text or "")[:400]
        for _secret in (sec, cid):
            if _secret:
                body_txt = body_txt.replace(_secret, "[가림]")
        raise RuntimeError(f"HTTP {r.status_code} — 응답: {body_txt}")
    d = r.json()
    if "results" not in d:
        raise RuntimeError(f"results 없음 — 응답: {json.dumps(d, ensure_ascii=False)[:400]}")
    return d


def _avg_ratio(series):
    vals = [p.get("ratio", 0) for p in series]
    return sum(vals) / len(vals) if vals else 0.0


def keyword_demographics(cid, sec, keyword, months=3, sleep=0.4):
    gender_avg = {}
    for g in GENDERS:
        d = _call(cid, sec, keyword, months=months, gender=g)
        gender_avg[g] = _avg_ratio(d["results"][0]["data"])
        time.sleep(sleep)

    age_avg = {}
    for a in AGE_BUCKETS:
        d = _call(cid, sec, keyword, months=months, ages=[a])
        age_avg[a] = _avg_ratio(d["results"][0]["data"])
        time.sleep(sleep)

    g_total = sum(gender_avg.values()) or 1
    a_total = sum(age_avg.values()) or 1
    return {
        "키워드": keyword,
        "성비(근사)": {GENDERS[g]: round(v / g_total * 100, 1) for g, v in gender_avg.items()},
        "연령대비율(근사)": {AGE_BUCKETS[a]: round(v / a_total * 100, 1) for a, v in age_avg.items()},
        "주의": "데이터랩 상대지수를 세그먼트별로 따로 호출해 역산한 근사 비율 — 절대 인원수 아님",
    }


def main():
    cid, sec = _credentials()
    if not cid or not sec:
        print("::error:: NAVER_OPENAPI_CLIENT_ID/SECRET 미설정", file=sys.stderr)
        sys.exit(1)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)

    # 1) 프로브 — 이 앱이 "데이터랩(검색어트렌드)" 권한을 갖고 있는지 1회로 먼저 확인.
    #    지식인("검색") 전용으로 등록됐을 가능성이 있어 여기서 갈릴 수 있다.
    probe_kw = TOP30_KEYWORDS[0]
    print(f"[프로브] '{probe_kw}' 남성 세그먼트 1회 호출로 데이터랩 권한 확인 중…")
    try:
        _call(cid, sec, probe_kw, months=3, gender="m")
        print("[프로브] ✅ 성공 — 이 키는 데이터랩 권한도 갖고 있음. 전체 30개로 진행합니다.")
    except RuntimeError as e:
        msg = str(e)
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump({
                "막힘": "프로브 실패 — 이 NAVER_OPENAPI 키는 지식인(검색)용으로 등록됐고 "
                        "데이터랩(검색어트렌드) 권한은 없는 것으로 보입니다. 네이버 개발자센터 "
                        "(developers.naver.com) → 해당 Application → '사용 API' 목록에서 "
                        "'검색어트렌드(데이터랩)' 체크박스를 추가로 켜야 합니다.",
                "원본오류": msg,
            }, f, ensure_ascii=False, indent=1)
        print(f"::error:: 프로브 실패 — {msg}", file=sys.stderr)
        print(f"[중단] {OUT} — 데이터랩 권한 없음으로 판단, 원본 오류 저장 완료")
        sys.exit(4)  # 4 = "권한 없음"으로 구분 (사장님 조치 필요: 체크박스 하나 추가)

    # 2) 전체 30개.
    results = []
    for i, kw in enumerate(TOP30_KEYWORDS, 1):
        try:
            res = keyword_demographics(cid, sec, kw)
        except RuntimeError as e:
            print(f"::warning:: '{kw}' 실패 — {e}", file=sys.stderr)
            continue
        results.append(res)
        top_age = max(res["연령대비율(근사)"].items(), key=lambda x: x[1])
        print(f"[{i}/{len(TOP30_KEYWORDS)}] {kw}: 성비={res['성비(근사)']} 연령대상위={top_age}")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"결과": results}, f, ensure_ascii=False, indent=1)
    print(f"[완료] {OUT} — {len(results)}/{len(TOP30_KEYWORDS)}개 키워드")


if __name__ == "__main__":
    main()
