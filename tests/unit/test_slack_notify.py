"""slack_notify 단위 테스트. 외부 의존 없음(urllib mock). pytest fixture 미사용 —
스모크 실행/회귀 양쪽 호환.

검증 포인트:
(a) 미설정 시 [SLACK][SKIP] + False (비차단).
(b) open_dm → getUploadURLExternal → upload → completeUploadExternal 순서·payload.
(c) 토큰이 로그/에러에 절대 노출 안 됨.
"""
import contextlib
import io
import json
import os
import urllib.parse
from unittest import mock

import src.slack_notify as slack_notify

_SECRET_KEYS = ("SLACK_BOT_TOKEN", "SLACK_TARGET_USER_ID", "SLACK_TARGET_EMAIL")


class _Resp:
    """urlopen 컨텍스트매니저 목: .status 와 .read() 둘 다 지원."""

    def __init__(self, status=200, body=b""):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _json_resp(obj: dict) -> _Resp:
    return _Resp(body=json.dumps(obj).encode("utf-8"))


def _set_secrets():
    os.environ["SLACK_BOT_TOKEN"] = "xoxb-SUPER-SECRET-TOKEN"
    os.environ["SLACK_TARGET_USER_ID"] = "U_TARGET"


def _clear_secrets(saved):
    for k in _SECRET_KEYS:
        os.environ.pop(k, None)
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v


# ── (a) 미설정 → SKIP + False ────────────────────────────────────────────────
def test_photo_skip_without_secret():
    saved = {k: os.environ.pop(k, None) for k in _SECRET_KEYS}
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert slack_notify.send_slack_photo(b"img", filename="r.png") is False
        assert "[SLACK][SKIP]" in buf.getvalue()
    finally:
        _clear_secrets(saved)


def test_document_skip_without_secret():
    saved = {k: os.environ.pop(k, None) for k in _SECRET_KEYS}
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert slack_notify.send_slack_document(b"<html>", "r.html") is False
        assert "[SLACK][SKIP]" in buf.getvalue()
    finally:
        _clear_secrets(saved)


def test_skip_when_only_token_set():
    """토큰만 있고 대상 유저ID 없으면 SKIP."""
    saved = {k: os.environ.pop(k, None) for k in _SECRET_KEYS}
    try:
        os.environ["SLACK_BOT_TOKEN"] = "xoxb-x"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert slack_notify.send_slack_photo(b"img") is False
        assert "[SLACK][SKIP]" in buf.getvalue()
    finally:
        _clear_secrets(saved)


# ── (b) 전체 흐름 순서·payload ────────────────────────────────────────────────
def _make_dispatcher(calls):
    def _dispatch(req, timeout=None):
        url = req.full_url
        calls.append((url, req.get_method(), req.data, dict(req.header_items())))
        if "conversations.open" in url:
            return _json_resp({"ok": True, "channel": {"id": "D_DM_CHANNEL"}})
        if "files.getUploadURLExternal" in url:
            return _json_resp({"ok": True,
                               "upload_url": "https://files.slack.com/upload/v1/ABC",
                               "file_id": "F_FILE_ID"})
        if url.startswith("https://files.slack.com/upload"):
            return _Resp(status=200, body=b"OK")
        if "files.completeUploadExternal" in url:
            return _json_resp({"ok": True, "files": [{"id": "F_FILE_ID"}]})
        raise AssertionError(f"예상치 못한 URL 호출: {url}")

    return _dispatch


def test_photo_full_flow_order_and_payload():
    saved = {k: os.environ.get(k) for k in _SECRET_KEYS}
    _set_secrets()
    calls = []
    try:
        with mock.patch("urllib.request.urlopen", side_effect=_make_dispatcher(calls)):
            ok = slack_notify.send_slack_photo(
                b"PNGBYTES", filename="cafe_daily.png", initial_comment="달성률 80%")
        assert ok is True

        # 4단계 순서
        assert len(calls) == 4
        urls = [c[0] for c in calls]
        assert "conversations.open" in urls[0]
        assert "files.getUploadURLExternal" in urls[1]
        assert urls[2].startswith("https://files.slack.com/upload")
        assert "files.completeUploadExternal" in urls[3]

        # ① conversations.open: JSON body {"users": U_TARGET}
        open_body = json.loads(calls[0][2].decode("utf-8"))
        assert open_body == {"users": "U_TARGET"}

        # ② getUploadURLExternal: filename + length(=바이트수) 쿼리
        get_qs = urllib.parse.parse_qs(urls[1].split("?", 1)[1])
        assert get_qs["filename"] == ["cafe_daily.png"]
        assert get_qs["length"] == [str(len(b"PNGBYTES"))]

        # ③ upload: 파일 바이트가 multipart 본문에 포함
        assert b"PNGBYTES" in calls[2][2]

        # ④ completeUploadExternal: files(id) + channel_id + initial_comment
        complete_fields = urllib.parse.parse_qs(calls[3][2].decode("utf-8"))
        files_arg = json.loads(complete_fields["files"][0])
        assert files_arg[0]["id"] == "F_FILE_ID"
        assert complete_fields["channel_id"] == ["D_DM_CHANNEL"]
        assert complete_fields["initial_comment"] == ["달성률 80%"]
    finally:
        _clear_secrets(saved)


def test_document_full_flow_returns_true():
    saved = {k: os.environ.get(k) for k in _SECRET_KEYS}
    _set_secrets()
    calls = []
    try:
        with mock.patch("urllib.request.urlopen", side_effect=_make_dispatcher(calls)):
            ok = slack_notify.send_slack_document(
                b"<html>report</html>", "cafe_monthly.html", initial_comment="월간")
        assert ok is True
        assert len(calls) == 4
        # 문서도 동일 업로드 흐름을 탄다
        assert "files.getUploadURLExternal" in calls[1][0]
    finally:
        _clear_secrets(saved)


def test_returns_false_when_open_dm_fails():
    saved = {k: os.environ.get(k) for k in _SECRET_KEYS}
    _set_secrets()
    try:
        with mock.patch("urllib.request.urlopen",
                        return_value=_json_resp({"ok": False, "error": "user_not_found"})):
            assert slack_notify.send_slack_photo(b"img") is False
    finally:
        _clear_secrets(saved)


# ── (c) 토큰 비노출 ───────────────────────────────────────────────────────────
def test_token_in_auth_header_not_url_or_body():
    """토큰은 Authorization 헤더로만 — URL/본문엔 절대 없어야 한다."""
    saved = {k: os.environ.get(k) for k in _SECRET_KEYS}
    _set_secrets()
    calls = []
    try:
        with mock.patch("urllib.request.urlopen", side_effect=_make_dispatcher(calls)):
            slack_notify.send_slack_photo(b"img", filename="r.png")
        for url, _method, data, headers in calls:
            assert "xoxb-SUPER-SECRET-TOKEN" not in url
            if data is not None:
                assert b"xoxb-SUPER-SECRET-TOKEN" not in data
        # Slack API 호출엔 Bearer 헤더가 실려 있어야 한다(파일 업로드 POST 제외).
        api_calls = [h for u, _m, _d, h in calls if u.startswith(slack_notify._API_BASE)]
        assert api_calls, "Slack API 호출이 최소 1건 있어야 함"
        for headers in api_calls:
            joined = " ".join(f"{k}:{v}" for k, v in headers.items())
            assert "Bearer xoxb-SUPER-SECRET-TOKEN" in joined
    finally:
        _clear_secrets(saved)


def test_token_never_logged_on_exception():
    """urlopen 예외 메시지에 토큰이 실려도 우리 로그엔 절대 안 찍힌다."""
    saved = {k: os.environ.get(k) for k in _SECRET_KEYS}
    _set_secrets()
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with mock.patch("urllib.request.urlopen",
                            side_effect=Exception("xoxb-SUPER-SECRET-TOKEN leaked in msg")):
                assert slack_notify.send_slack_photo(b"img", filename="r.png") is False
        out = buf.getvalue()
        assert "xoxb-SUPER-SECRET-TOKEN" not in out
        assert "[SLACK][WARN]" in out  # 실패는 경고로만
    finally:
        _clear_secrets(saved)


# ── 이메일 자동 조회 경로 ─────────────────────────────────────────────────────

def _make_email_dispatcher(calls):
    """EMAIL 경로 5단계: lookupByEmail → conversations.open → getUploadURL → upload → complete."""
    def _dispatch(req, timeout=None):
        url = req.full_url
        calls.append((url, req.get_method(), req.data, dict(req.header_items())))
        if "users.lookupByEmail" in url:
            return _json_resp({"ok": True, "user": {"id": "U_FROM_EMAIL"}})
        if "conversations.open" in url:
            return _json_resp({"ok": True, "channel": {"id": "D_DM_CHANNEL"}})
        if "files.getUploadURLExternal" in url:
            return _json_resp({"ok": True,
                               "upload_url": "https://files.slack.com/upload/v1/ABC",
                               "file_id": "F_FILE_ID"})
        if url.startswith("https://files.slack.com/upload"):
            return _Resp(status=200, body=b"OK")
        if "files.completeUploadExternal" in url:
            return _json_resp({"ok": True, "files": [{"id": "F_FILE_ID"}]})
        raise AssertionError(f"예상치 못한 URL 호출: {url}")
    return _dispatch


def test_user_id_overrides_email_no_lookup_called():
    """(a) USER_ID 가 있으면 lookupByEmail 은 호출하지 않는다."""
    saved = {k: os.environ.get(k) for k in _SECRET_KEYS}
    _set_secrets()
    os.environ["SLACK_TARGET_EMAIL"] = "hansu@example.com"  # USER_ID 와 EMAIL 둘 다 세팅
    calls = []
    try:
        with mock.patch("urllib.request.urlopen", side_effect=_make_dispatcher(calls)):
            ok = slack_notify.send_slack_photo(b"img", filename="r.png")
        assert ok is True
        urls = [c[0] for c in calls]
        assert not any("lookupByEmail" in u for u in urls), "USER_ID 있을 때 lookupByEmail 호출 금지"
        assert any("conversations.open" in u for u in urls)
    finally:
        _clear_secrets(saved)


def test_email_only_triggers_lookup_and_uses_resolved_id():
    """(b) EMAIL 만 있으면 lookupByEmail → 얻은 id 로 open_dm → 정상 발송."""
    saved = {k: os.environ.get(k) for k in _SECRET_KEYS}
    try:
        os.environ["SLACK_BOT_TOKEN"] = "xoxb-SUPER-SECRET-TOKEN"
        os.environ["SLACK_TARGET_EMAIL"] = "hansu@example.com"
        # USER_ID 없음 — EMAIL 경로 강제
        calls = []
        with mock.patch("urllib.request.urlopen", side_effect=_make_email_dispatcher(calls)):
            ok = slack_notify.send_slack_photo(b"img", filename="r.png", initial_comment="테스트")
        assert ok is True

        urls = [c[0] for c in calls]
        # 5단계 순서 확인
        assert len(calls) == 5
        assert "users.lookupByEmail" in urls[0]
        assert "conversations.open" in urls[1]
        assert "files.getUploadURLExternal" in urls[2]
        assert urls[3].startswith("https://files.slack.com/upload")
        assert "files.completeUploadExternal" in urls[4]

        # lookupByEmail 쿼리에 email 파라미터 포함 여부
        lookup_qs = urllib.parse.parse_qs(urls[0].split("?", 1)[1])
        assert lookup_qs["email"] == ["hansu@example.com"]

        # conversations.open 에 조회한 id(U_FROM_EMAIL) 전달 여부
        open_body = json.loads(calls[1][2].decode("utf-8"))
        assert open_body == {"users": "U_FROM_EMAIL"}
    finally:
        _clear_secrets(saved)


def test_email_lookup_failure_returns_false_no_leak():
    """(c) lookupByEmail 실패 시 False 반환, 로그에 이메일·토큰 미노출."""
    saved = {k: os.environ.get(k) for k in _SECRET_KEYS}
    try:
        os.environ["SLACK_BOT_TOKEN"] = "xoxb-SUPER-SECRET-TOKEN"
        os.environ["SLACK_TARGET_EMAIL"] = "hansu@example.com"
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            with mock.patch("urllib.request.urlopen",
                            return_value=_json_resp({"ok": False, "error": "users_not_found"})):
                result = slack_notify.send_slack_photo(b"img", filename="r.png")
        assert result is False
        out = buf.getvalue()
        assert "hansu@example.com" not in out, "이메일 로그 노출 금지"
        assert "xoxb-SUPER-SECRET-TOKEN" not in out, "토큰 로그 노출 금지"
        assert "[SLACK][WARN]" in out
    finally:
        _clear_secrets(saved)


def test_skip_when_token_set_but_both_target_missing():
    """(d) 토큰은 있지만 USER_ID·EMAIL 둘 다 없으면 SKIP + False."""
    saved = {k: os.environ.get(k) for k in _SECRET_KEYS}
    try:
        os.environ["SLACK_BOT_TOKEN"] = "xoxb-SUPER-SECRET-TOKEN"
        # USER_ID, EMAIL 모두 없음
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert slack_notify.send_slack_photo(b"img", filename="r.png") is False
        assert "[SLACK][SKIP]" in buf.getvalue()
    finally:
        _clear_secrets(saved)
