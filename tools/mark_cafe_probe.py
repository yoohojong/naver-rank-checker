import io, json, time
from curl_cffi import requests as R
from PIL import Image
S = R.Session(impersonate="chrome"); U = json.load(open("tools/probe_urls.json"))
out = []
for u in U:
    for t in ["", "w300", "w640", "w800", "w1080", "w1280", "w1600", "w1920", "w2048", "w3840", "f1600", "type=original"]:
        uu = u + ("?type=" + t if t and not t.startswith("type=") else ("?" + t if t else ""))
        time.sleep(0.6); g = S.get(uu, headers={"Referer": "https://cafe.naver.com/"}, timeout=60)
        try: wh = Image.open(io.BytesIO(g.content)).size
        except Exception: wh = None
        out.append(dict(url=u[-40:], type=t or "(값 없음)", status=g.status_code, wh=wh, bytes=len(g.content))); print(out[-1], flush=True)
import os; os.makedirs("out", exist_ok=True); json.dump(out, open("out/probe.json", "w"), ensure_ascii=False)
