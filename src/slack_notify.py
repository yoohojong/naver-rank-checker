"""slack_notify: 리포트 이미지/파일을 한수연님 슬랙 DM 으로 발송. 2026-07-16.

목적: 사장님이 텔레그램(notify.py)으로 받는 일·주·월 리포트를 동일하게
한수연님 슬랙 DM 으로도 발송. 텔레그램 흐름은 무손상 — 이건 순수 추가.

설계(notify.py 방어패턴 모방):
- 표준 라이브러리 urllib 만 사용(requirements 무수정).
- env: SLACK_BOT_TOKEN(xoxb-...), SLACK_TARGET_USER_ID(한수연 멤버ID U...).
  둘 중 하나라도 없으면 [SLACK][SKIP] 후 False(비차단, 예외 X).
- files.upload 은 2025 deprecated → files_upload_v2 3단계 흐름:
    ① files.getUploadURLExternal (GET) → upload_url + file_id
    ② upload_url 에 파일 바이트 multipart POST
    ③ files.completeUploadExternal (POST) → DM 채널에 게시(initial_comment)
- DM 채널 = conversations.open(users=SLACK_TARGET_USER_ID) 의 channel.id.
- 토큰은 Authorization: Bearer 헤더로만 — 에러/로그에 토큰·url 절대 출력 금지(D-048 가드).
- 실패/미설정 = 경고 후 False(비차단, 예외 전파 X).
"""
import json
import os
import urllib.parse
import urllib.request

HTTP_TIMEOUT_SEC = 15  # 무응답 시 job 매달림 방지
_API_BASE = "https://slack.com/api/"
_BOUNDARY = "----nrcSlackBoundaryK3P8"


def slack_secrets() -> tuple:
    return (
        os.environ.get("SLACK_BOT_TOKEN", "").strip(),
        os.environ.get("SLACK_TARGET_USER_ID", "").strip(),
    )


def _auth_headers(token: str, extra: dict = None) -> dict:
    """토큰은 헤더로만 — 절대 URL/본문/로그에 넣지 않는다."""
    headers = {"Authorization": f"Bearer {token}"}
    if extra:
        headers.update(extra)
    return headers


def _read_json(req: "urllib.request.Request", timeout: int) -> dict:
    """Slack Web API 응답(JSON) 파싱. 실패 = 경고 후 {} (토큰/url 노출 금지)."""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
        return json.loads(body)
    except Exception as e:  # noqa: BLE001 — 토큰/url 노출 금지: type 만 출력
        print(f"[SLACK][WARN] API 호출 실패: {type(e).__name__}")
        return {}


def _api_post_json(method: str, token: str, payload: dict, timeout: int) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        _API_BASE + method, data=data,
        headers=_auth_headers(token, {"Content-Type": "application/json; charset=utf-8"}),
        method="POST",
    )
    return _read_json(req, timeout)


def _api_post_form(method: str, token: str, fields: dict, timeout: int) -> dict:
    data = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(
        _API_BASE + method, data=data,
        headers=_auth_headers(token, {"Content-Type": "application/x-www-form-urlencoded"}),
        method="POST",
    )
    return _read_json(req, timeout)


def _api_get(method: str, token: str, params: dict, timeout: int) -> dict:
    url = _API_BASE + method + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=_auth_headers(token), method="GET")
    return _read_json(req, timeout)


def _open_dm(token: str, user_id: str, timeout: int = HTTP_TIMEOUT_SEC) -> str:
    """conversations.open → DM 채널 id 반환(실패 시 "")."""
    resp = _api_post_json("conversations.open", token, {"users": user_id}, timeout)
    if not resp.get("ok"):
        print(f"[SLACK][WARN] DM 오픈 실패: {resp.get('error', 'no_response')}")
        return ""
    return (resp.get("channel") or {}).get("id", "")


def _multipart_body(field: str, filename: str, file_bytes: bytes, content_type: str) -> bytes:
    """upload_url 용 multipart/form-data 본문 수동 조립(requests 없이)."""
    crlf = b"\r\n"
    b = b"--" + _BOUNDARY.encode()
    return b"".join([
        b + crlf,
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"'.encode("utf-8") + crlf,
        f"Content-Type: {content_type}".encode() + crlf + crlf,
        file_bytes + crlf,
        b + b"--" + crlf,
    ])


def _upload_bytes(upload_url: str, filename: str, file_bytes: bytes,
                  content_type: str, timeout: int) -> bool:
    """getUploadURLExternal 이 준 URL 에 파일 바이트 multipart POST. 성공 True."""
    body = _multipart_body("file", filename, file_bytes, content_type)
    req = urllib.request.Request(
        upload_url, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={_BOUNDARY}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception as e:  # noqa: BLE001 — 토큰/url 노출 금지
        print(f"[SLACK][WARN] 업로드 실패: {type(e).__name__}")
        return False


def _upload_and_share(file_bytes: bytes, filename: str, content_type: str,
                      title: str = "", initial_comment: str = "",
                      timeout: int = HTTP_TIMEOUT_SEC) -> bool:
    """files_upload_v2 3단계 + DM 게시 공용. 성공 True. 미설정/실패 = 경고 후 False."""
    token, user_id = slack_secrets()
    if not token or not user_id:
        print("[SLACK][SKIP] SLACK_BOT_TOKEN/SLACK_TARGET_USER_ID 미설정 — 슬랙 발송 건너뜀")
        return False

    channel_id = _open_dm(token, user_id, timeout)
    if not channel_id:
        return False

    # ① 업로드 URL 발급 (filename + 바이트 길이)
    got = _api_get("files.getUploadURLExternal", token,
                   {"filename": filename, "length": len(file_bytes)}, timeout)
    if not got.get("ok"):
        print(f"[SLACK][WARN] 업로드URL 발급 실패: {got.get('error', 'no_response')}")
        return False
    upload_url = got.get("upload_url", "")
    file_id = got.get("file_id", "")
    if not upload_url or not file_id:
        print("[SLACK][WARN] 업로드URL 응답 불완전")
        return False

    # ② 파일 바이트 업로드
    if not _upload_bytes(upload_url, filename, file_bytes, content_type, timeout):
        return False

    # ③ 업로드 완료 + DM 채널에 게시(initial_comment)
    fields = {
        "files": json.dumps([{"id": file_id, "title": title or filename}]),
        "channel_id": channel_id,
    }
    if initial_comment:
        fields["initial_comment"] = initial_comment
    done = _api_post_form("files.completeUploadExternal", token, fields, timeout)
    if not done.get("ok"):
        print(f"[SLACK][WARN] 업로드 완료 실패: {done.get('error', 'no_response')}")
        return False
    return True


def send_slack_photo(image_bytes: bytes, filename: str = "report.png",
                     title: str = "", initial_comment: str = "") -> bool:
    """PNG 이미지 1건을 한수연님 DM 으로 발송(일·주간 대시보드)."""
    return _upload_and_share(image_bytes, filename, "image/png",
                             title=title, initial_comment=initial_comment)


def send_slack_document(file_bytes: bytes, filename: str, title: str = "",
                        initial_comment: str = "", content_type: str = "text/html") -> bool:
    """파일 1건(월간 HTML 등)을 한수연님 DM 으로 발송."""
    return _upload_and_share(file_bytes, filename, content_type,
                             title=title, initial_comment=initial_comment)
