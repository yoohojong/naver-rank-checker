# -*- coding: utf-8 -*-
"""10-31 임시 진단 (읽기 전용 · probe 가지 전용 · main 에 합치지 않음).

10-31 15:00 실행(41174777839)이 시트를 읽을 때 '카외' 탭 링크 칸이 전부 비어 있었다
(12:00 사본 916 → 15:00 사본 0 · 15:12 읽기 4 · 15:18 읽기 다 있음).
누가 · 언제 비웠다가 되살렸는지를 구글 드라이브 판 기록(revisions)과 활동 기록(Drive Activity)으로 본다.

공개 저장소 로그에 남으므로 사람 이름 · 메일 · 링크 · 키워드는 찍지 않는다.
찍는 것: 판 시각(한국 시각) · 고친 쪽 구분(서비스계정 / 사람A·B…) · 탭별 줄 수 · 링크 있는 줄 수.
네이버 요청 없음 · 시트 쓰기 없음.
"""
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from google.oauth2 import service_account
from google.auth.transport.requests import AuthorizedSession

KST = timezone(timedelta(hours=9))
FROM = datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)   # 전부
TO = datetime(2026, 12, 31, 0, 0, tzinfo=timezone.utc)

raw = os.environ["SERVICE_ACCOUNT_JSON"]
if raw.startswith("﻿"):
    raw = raw[1:]
info = json.loads(raw)
sa_email = info.get("client_email", "")
fid = os.environ["SPREADSHEET_ID"]
creds = service_account.Credentials.from_service_account_info(
    info,
    scopes=[
        "https://www.googleapis.com/auth/drive.readonly",
        "https://www.googleapis.com/auth/drive.activity.readonly",
    ],
)
s = AuthorizedSession(creds)

labels: dict[str, str] = {}


def who(email: str | None, me: bool | None = None, kind: str = "") -> str:
    if me or (email and email == sa_email):
        return "서비스계정(순위체커)"
    key = email or kind or "모름"
    if key not in labels:
        labels[key] = "사람" + "ABCDEFGHIJ"[len(labels) % 10]
    return labels[key]


def kst(ts: str) -> str:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(KST).strftime("%m-%d %H:%M:%S")


# 1) 판 기록
revs = []
token = None
while True:
    params = {
        "fields": "nextPageToken,revisions(id,modifiedTime,lastModifyingUser(emailAddress,me,displayName),exportLinks)",
        "pageSize": 200,
    }
    if token:
        params["pageToken"] = token
    r = s.get(f"https://www.googleapis.com/drive/v3/files/{fid}/revisions", params=params, timeout=60)
    print("REVISIONS_HTTP", r.status_code, flush=True)
    if r.status_code != 200:
        print("REVISIONS_ERR", r.text[:300].replace(fid, "<id>"), flush=True)
        break
    j = r.json()
    revs += j.get("revisions", [])
    token = j.get("nextPageToken")
    if not token:
        break
print("REVISIONS_TOTAL", len(revs), flush=True)

window = []
prev = None
for rv in revs:
    t = datetime.fromisoformat(rv["modifiedTime"].replace("Z", "+00:00"))
    if t < FROM:
        prev = rv
        continue
    if t > TO:
        continue
    window.append(rv)
if prev:
    window.insert(0, prev)

try:
    import openpyxl  # noqa: E402
except Exception as e:  # pragma: no cover
    openpyxl = None
    print("NO_OPENPYXL", repr(e)[:80])

for rv in window:
    u = rv.get("lastModifyingUser") or {}
    line = f"REV {kst(rv['modifiedTime'])} KST · 고친쪽={who(u.get('emailAddress'), u.get('me'))}"
    link = (rv.get("exportLinks") or {}).get(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    if not link or openpyxl is None:
        print(line, "· 내려받기 길 없음", flush=True)
        continue
    try:
        x = s.get(link, timeout=180)
        if x.status_code != 200:
            print(line, "· 내려받기", x.status_code, flush=True)
            continue
        wb = openpyxl.load_workbook(io.BytesIO(x.content), read_only=True, data_only=True)
        parts = []
        for ws in wb.worksheets:
            if not ws.title.endswith("카외"):
                continue
            rows = ws.iter_rows(values_only=True)
            head = [str(c or "").strip() for c in next(rows, [])]
            li = head.index("링크") if "링크" in head else None
            ki = head.index("키워드") if "키워드" in head else None
            n = nl = 0
            for row in rows:
                if not row:
                    continue
                kw = row[ki] if ki is not None and ki < len(row) else None
                lk = row[li] if li is not None and li < len(row) else None
                if kw is None and lk is None:
                    continue
                n += 1
                if lk is not None and str(lk).strip():
                    nl += 1
            parts.append(f"{ws.title} 줄{n} 링크{nl} 링크칸={'K' if li == 10 else li}")
        print(line, "·", " | ".join(parts), flush=True)
    except Exception as e:
        print(line, "· 읽기 실패", repr(e)[:120], flush=True)

# 2) 활동 기록 (API 가 꺼져 있으면 상태 코드만)
body = {
    "itemName": f"items/{fid}",
    "filter": f'time >= "{FROM.isoformat()}" AND time <= "{TO.isoformat()}"',
    "pageSize": 100,
}
acts = []
for _ in range(10):
    r = s.post("https://driveactivity.googleapis.com/v2/activity:query", json=body, timeout=60)
    print("ACTIVITY_HTTP", r.status_code, flush=True)
    if r.status_code != 200:
        print("ACTIVITY_ERR", r.text[:600].replace(fid, "<id>").replace(sa_email, "<sa>"), flush=True)
        break
    j = r.json()
    acts += j.get("activities", [])
    if not j.get("nextPageToken"):
        break
    body["pageToken"] = j["nextPageToken"]
for a in sorted(acts, key=lambda a: a.get("timestamp") or a.get("timeRange", {}).get("endTime", "")):
    ts = a.get("timestamp") or a.get("timeRange", {}).get("endTime", "")
    action = list((a.get("primaryActionDetail") or {}).keys())
    actors = []
    for ac in a.get("actors", []):
        if "user" in ac:
            ku = ac["user"].get("knownUser", {})
            actors.append(who(ku.get("personName"), ku.get("isCurrentUser"), "user"))
        else:
            actors.append(list(ac.keys())[0])
    print(f"ACT {kst(ts) if ts else '?'} KST · {action} · {actors}", flush=True)

print("LABELS", len(labels), "명(사람 구분만, 이름 · 메일은 안 찍음)", flush=True)
