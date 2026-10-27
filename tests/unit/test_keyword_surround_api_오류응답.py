"""keyword_surround_api.fetch — HTTP 200 이어도 오류 표시가 있으면 실패. 오류 표시 없는 정상 빈 목록만 성공 0건. 네이버 요청 없음(가짜 응답)."""
import json
import importlib.util
from pathlib import Path

import pytest

_p = Path(__file__).resolve().parents[2] / "scripts" / "keyword_surround_api.py"
_s = importlib.util.spec_from_file_location("ksa", _p)
A = importlib.util.module_from_spec(_s)
_s.loader.exec_module(A)


class R:
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return json.dumps(self.body).encode()


def _fetch(body):
    return A.fetch("쇼핑", "표본", "id", "secret", lambda req, timeout: R(body))


CASES = [  # (이름, 응답, 기대 상태, 까닭에 든 글)
    ("정상 빈 목록", {"items": []}, "성공", None),
    ("정상 빈 목록+total", {"total": 0, "items": []}, "성공", None),
    ("오류만", {"errorCode": "SE99"}, "실패 오류 응답", "SE99"),
    ("오류 메시지만", {"errorMessage": "denied"}, "실패 오류 응답", "denied"),
    ("오류+빈 items", {"errorCode": "SE99", "errorMessage": "denied", "items": []}, "실패 오류 응답", "denied"),
    ("오류+찬 items", {"errorCode": "SE01", "items": [{"title": "a"}]}, "실패 오류 응답", "SE01"),
    ("오류+items 글자", {"errorCode": "SE02", "items": "bad"}, "실패 오류 응답", "SE02"),
    ("오류 표시 없고 items 없음", {}, "실패 items 없음", "items"),
    ("오류 표시 없고 items 글자", {"items": "bad"}, "실패 items 없음", "items"),
    ("객체 아님", [], "실패 items 없음", "JSON 객체가 아님"),
]


@pytest.mark.parametrize("name,body,status,word", CASES, ids=[c[0] for c in CASES])
def test_오류표시_x_items모양(name, body, status, word):
    c = _fetch(body)
    assert c["상태"] == status, (name, c)
    if status == "성공":
        assert c["개수"] == 0 and c["항목들"] == []
    else:
        assert c["개수"] == 0 and word in c["까닭"]


def test_정상_항목은_그대로():
    c = _fetch({"total": 5, "items": [{"title": "<b>가</b>", "link": "u"}]})
    assert c["상태"] == "성공" and c["개수"] == 1 and c["항목들"][0]["제목"] == "가"
