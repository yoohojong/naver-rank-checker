"""쇼핑 검색 API 종료(2026-07-31) — run 은 shop.json 을 부르지 않고 쇼핑 칸을 '받지 않음'으로 남긴다."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import keyword_surround_api as A  # noqa: E402


class R:
    def __init__(self, body):
        self.b = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.b


def test_쇼핑_요청_0번_종료_표시():
    urls = []

    def opener(req, timeout):
        urls.append(req.full_url)
        return R({"total": 1, "items": [{"title": "a", "link": "l"}]})
    r = A.run(["k1", "k2"], "id", "sec", opener, pause=0)
    assert len(urls) == 6 and not any("shop" in u for u in urls)
    for row in r["키워드들"]:
        c = row["출처"]["쇼핑"]
        assert c["상태"] == "받지 않음" and "종료(2026-07-31, 공지 32564)" in c["까닭"] and c["개수"] == 0
        assert list(row["출처"]) == ["블로그", "카페", "지식인", "쇼핑"]
    assert "받지 않음" in A.count_table(r)
    json.dumps(r, ensure_ascii=False)


def test_진단_PROBES_쇼핑은_남아있다():
    assert any("shop" in p[1] for p in A.PROBES)
