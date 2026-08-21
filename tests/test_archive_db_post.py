# -*- coding: utf-8 -*-
"""상위노출 이력 DB 동시 적재 (시트 탈출 1단계, 2026-08-21).

왜: 이 아카이브는 기계만 쌓는 **로그**인데 구글시트 탭에 있어 카페외부 시트를 계속
무겁게 했다(실측 4만 행·24만 칸 = 문서 격자 23.9%, 매 cron 자람).

계약 — 이 코드를 넣는 것만으로는 **아무것도 안 바뀌어야 한다**:
  ① GOYU_* 환경변수가 하나라도 없으면 아무 요청도 안 보내고 건너뛴다.
  ② 행 0 이면 보내지 않는다(빈 목록이 그날 기록을 지우는 사고 방지).
  ③ 어떤 실패에도 **예외를 위로 던지지 않는다**(cron 이 죽으면 안 된다).
  ④ 로그인 실패로 적재가 302 되면 성공으로 오인하지 않는다.
  ⑤ 정상이면 서버가 알려준 기록 행 수를 그대로 돌려준다.
"""
from __future__ import annotations

import pytest

from src.archive import post_daily_archive

ROWS = [["2026-08-20", "샴푸 카외", "탈모샴푸", "카페", 3, 2]]


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch):
    for k in ("GOYU_BASE_URL", "GOYU_USER", "GOYU_PASS"):
        monkeypatch.delenv(k, raising=False)


def _set_env(monkeypatch, base="https://goyu.example", user="bot", pw="pw"):
    monkeypatch.setenv("GOYU_BASE_URL", base)
    monkeypatch.setenv("GOYU_USER", user)
    monkeypatch.setenv("GOYU_PASS", pw)


class _Resp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = text or '<input name="csrf_token" value="t0k" >'

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _Session:
    """requests.Session 흉내 — 마지막 POST 본문을 기록해 검사한다."""

    def __init__(self, post_resp):
        self.post_resp = post_resp
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, **kw):
        self.calls.append(("GET", url))
        return _Resp()

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        if url.endswith("/login"):
            return _Resp()
        return self.post_resp


def _patch_requests(monkeypatch, session):
    import types

    fake = types.SimpleNamespace(Session=lambda: session)
    monkeypatch.setitem(__import__("sys").modules, "requests", fake)
    return session


def test_환경변수_없으면_아무것도_안_보낸다(monkeypatch):
    """① 이 코드를 넣는 것만으로는 기존 동작이 안 바뀐다."""
    sess = _patch_requests(monkeypatch, _Session(_Resp()))
    out = post_daily_archive(ROWS, "2026-08-20")
    assert out["posted"] == 0
    assert "미설정" in out["skipped"]
    assert sess.calls == [], "설정이 없는데 요청을 보냈다"


def test_행_0이면_안_보낸다(monkeypatch):
    """② 빈 목록이 그날 기록을 지우는 사고를 여기서도 막는다."""
    _set_env(monkeypatch)
    sess = _patch_requests(monkeypatch, _Session(_Resp()))
    out = post_daily_archive([], "2026-08-20")
    assert out["posted"] == 0 and "행 0" in out["skipped"]
    assert sess.calls == [], "빈 목록인데 요청을 보냈다"


def test_정상이면_기록된_행수를_돌려준다(monkeypatch):
    """⑤"""
    _set_env(monkeypatch)
    sess = _patch_requests(
        monkeypatch, _Session(_Resp(200, {"ok": True, "written": 1, "total": 42})))
    out = post_daily_archive(ROWS, "2026-08-20")
    assert out == {"posted": 1, "date": "2026-08-20", "total": 42}

    posts = [c for c in sess.calls if c[0] == "POST" and c[1].endswith("/admin/exposure-archive")]
    assert len(posts) == 1
    body = posts[0][2]["json"]
    assert body == {"date": "2026-08-20", "rows": ROWS}
    assert posts[0][2]["allow_redirects"] is False, \
        "리다이렉트를 따라가면 로그인 실패를 성공으로 오인한다"


def test_로그인_실패로_302면_성공으로_안_친다(monkeypatch):
    """④ 적재가 로그인 화면으로 넘어가면 그건 실패다."""
    _set_env(monkeypatch)
    _patch_requests(monkeypatch, _Session(_Resp(302)))
    out = post_daily_archive(ROWS, "2026-08-20")
    assert out["posted"] == 0
    assert "로그인" in out["error"]


def test_서버가_건너뛰었다고_하면_그대로_전한다(monkeypatch):
    _set_env(monkeypatch)
    _patch_requests(
        monkeypatch, _Session(_Resp(200, {"ok": True, "written": 0, "skipped": "행 0 — 보존"})))
    out = post_daily_archive(ROWS, "2026-08-20")
    assert out["posted"] == 0 and out["skipped"] == "행 0 — 보존"


@pytest.mark.parametrize("boom", [RuntimeError("네트워크 끊김"), ValueError("이상한 응답")])
def test_어떤_실패에도_예외를_안_던진다(monkeypatch, boom):
    """③ 아카이브 실패가 cron 을 죽이면 안 된다."""
    _set_env(monkeypatch)

    class _Boom(_Session):
        def get(self, url, **kw):
            raise boom

    _patch_requests(monkeypatch, _Boom(_Resp()))
    out = post_daily_archive(ROWS, "2026-08-20")     # 예외가 새면 여기서 터진다
    assert out["posted"] == 0 and out["error"]


def test_HTTP_오류면_실패로_보고한다(monkeypatch):
    _set_env(monkeypatch)
    _patch_requests(monkeypatch, _Session(_Resp(500, text="서버 오류")))
    out = post_daily_archive(ROWS, "2026-08-20")
    assert out["posted"] == 0 and "500" in out["error"]
