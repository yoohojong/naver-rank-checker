"""notify 단위 테스트 (M10 T-M10.2). 외부 의존 없음(urllib mock). pytest fixture 미사용 —
스모크 실행/회귀 양쪽 호환.
"""
import contextlib
import io
import os
from unittest import mock

import src.notify as notify


def test_split_message_short():
    assert notify.split_message("hi") == ["hi"]
    assert notify.split_message("") == []


def test_split_message_long():
    text = "\n".join("x" * 100 for _ in range(60))  # ~6000자
    chunks = notify.split_message(text, limit=500)
    assert len(chunks) >= 2
    assert all(len(c) <= 500 for c in chunks)


def test_send_telegram_skip_without_secret():
    saved = {k: os.environ.pop(k, None) for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")}
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert notify.send_telegram("hi") is False
        assert "[TELEGRAM][SKIP]" in buf.getvalue()
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


def test_send_telegram_success():
    os.environ["TELEGRAM_BOT_TOKEN"] = "t"
    os.environ["TELEGRAM_CHAT_ID"] = "c"
    try:
        class _Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch("urllib.request.urlopen", return_value=_Resp()):
            assert notify.send_telegram("hi") is True
    finally:
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        os.environ.pop("TELEGRAM_CHAT_ID", None)


def test_send_telegram_http_fail_nonblocking():
    os.environ["TELEGRAM_BOT_TOKEN"] = "t"
    os.environ["TELEGRAM_CHAT_ID"] = "c"
    try:
        with mock.patch("urllib.request.urlopen", side_effect=Exception("boom")):
            assert notify.send_telegram("hi") is False  # 예외 전파 X
    finally:
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        os.environ.pop("TELEGRAM_CHAT_ID", None)


def test_send_report_always_zero():
    with mock.patch.object(notify.time, "sleep", lambda *a: None), mock.patch.object(
        notify, "send_telegram", return_value=True
    ) as m:
        assert notify.send_report("a\nb") == 0
        assert m.called
