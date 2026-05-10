"""1회용: 네이버 검색 페이지 수집해서 tests/fixtures/naver/ 에 저장."""
import time
import requests
from pathlib import Path

OUT = Path(__file__).parent.parent / "tests" / "fixtures" / "naver"
OUT.mkdir(parents=True, exist_ok=True)

KEYWORDS = {
    "ab_cafe_top": "등드름해초필링",
    "popular_cafe": "트러블크림",
    "smart_block": "두피관리법",
    "mixed_blocks": "샴푸순위",
    "no_match": "ㅁㄴㅇㄻㄴㅇㄻㄴㅇㄹ",
}

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://www.naver.com/",
}


def main():
    for label, kw in KEYWORDS.items():
        url = f"https://search.naver.com/search.naver?query={kw}"
        print(f"Fetching: {kw} → {label}")
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            out_path = OUT / f"{label}.html"
            out_path.write_text(r.text, encoding="utf-8")
            print(f"  Saved: {out_path.name} ({len(r.text)} chars)")
        except requests.RequestException as e:
            print(f"  FAILED: {e}")
        time.sleep(2)
    print("Done.")


if __name__ == "__main__":
    main()
