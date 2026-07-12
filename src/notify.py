"""notify: 텔레그램 Bot API sendMessage 발송. M10 T-M10.2.

검증(2026-06-19, gate2 공식/검색 확인):
- 메시지 길이 한도 = 4096 UTF-8 chars (초과 시 분할 필요).
- 전송 한도 = 한 채팅당 초당 1건 (분할 발송 시 간격 둔다).
설계: urllib 만 사용(requirements 무수정). plain text(parse_mode 없음 = markdown escape 불필요).
발송 실패·secret 미설정 = 비차단(예외 X). 토큰은 URL 에만 — 에러에 url/token 출력 금지(D-048 가드).
"""
import json
import os
import time
import urllib.request

MAX_LEN = 4096  # 텔레그램 sendMessage text 한도 (UTF-8 chars, 공식 확인)
PER_CHAT_INTERVAL_SEC = 1.1  # 한 채팅당 초당 1건 → 분할 발송 간격
HTTP_TIMEOUT_SEC = 10  # critic: 무응답 시 job timeout 매달림 방지
_API = "https://api.telegram.org/bot{token}/sendMessage"


def telegram_secrets() -> tuple:
    return (
        os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
        os.environ.get("TELEGRAM_CHAT_ID", "").strip(),
    )


def split_message(text: str, limit: int = MAX_LEN) -> list:
    """limit 초과 시 줄 경계 우선 분할 (한 줄이 limit 초과면 강제로 자른다)."""
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    chunks: list = []
    buf = ""
    for line in text.split("\n"):
        while len(line) > limit:  # 초장문 단일 줄
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(line[:limit])
            line = line[limit:]
        add = line if not buf else "\n" + line
        if len(buf) + len(add) > limit:
            chunks.append(buf)
            buf = line
        else:
            buf += add
    if buf:
        chunks.append(buf)
    return chunks


def send_telegram(text: str, *, timeout: int = HTTP_TIMEOUT_SEC) -> bool:
    """sendMessage 1건. 성공 True. secret 미설정/HTTP 실패 = 경고 후 False(예외 X)."""
    token, chat_id = telegram_secrets()
    if not token or not chat_id:
        print("[TELEGRAM][SKIP] TELEGRAM_BOT_TOKEN/CHAT_ID 미설정 — 발송 건너뜀")
        return False
    payload = json.dumps(
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    ).encode("utf-8")
    req = urllib.request.Request(
        _API.format(token=token),
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception as e:  # noqa: BLE001 — url/token 노출 금지: type 만 출력
        print(f"[TELEGRAM][WARN] 발송 실패: {type(e).__name__}")
        return False


def send_report(text: str) -> int:
    """긴 보고 분할 발송. 항상 0 반환(워크플로 비차단). secret 없으면 [SKIP] 후 0."""
    chunks = split_message(text)
    for i, chunk in enumerate(chunks):
        send_telegram(chunk)
        if i < len(chunks) - 1:
            time.sleep(PER_CHAT_INTERVAL_SEC)
    return 0


# ── 이미지/파일 발송 (일·주·월 대시보드용, 2026-07-13 추가) ────────────────────
# 텍스트 sendMessage 흐름은 위 그대로 유지. 아래는 순수 추가(기존 미호출=무영향).
# 캡션 한도 = 1024 UTF-8 chars(공식). urllib 만 사용(멀티파트 수동 조립).
_API_PHOTO = "https://api.telegram.org/bot{token}/sendPhoto"
_API_DOC = "https://api.telegram.org/bot{token}/sendDocument"
_BOUNDARY = "----nrcReportBoundaryZ7Q9"
CAPTION_MAX = 1024


def _multipart_body(text_fields: dict, file_field: str, filename: str,
                    file_bytes: bytes, content_type: str) -> bytes:
    """multipart/form-data 본문 수동 조립 (requests 없이)."""
    crlf = b"\r\n"
    b = b"--" + _BOUNDARY.encode()
    parts = []
    for k, v in text_fields.items():
        parts.append(
            b + crlf
            + f'Content-Disposition: form-data; name="{k}"'.encode() + crlf + crlf
            + str(v).encode("utf-8") + crlf
        )
    parts.append(
        b + crlf
        + f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"'.encode("utf-8") + crlf
        + f"Content-Type: {content_type}".encode() + crlf + crlf
        + file_bytes + crlf
    )
    parts.append(b + b"--" + crlf)
    return b"".join(parts)


def _send_file(api: str, file_field: str, filename: str, file_bytes: bytes,
               content_type: str, caption: str = "", timeout: int = 30) -> bool:
    """sendPhoto/sendDocument 공용. 성공 True. secret 미설정/실패 = 경고 후 False."""
    token, chat_id = telegram_secrets()
    if not token or not chat_id:
        print("[TELEGRAM][SKIP] 토큰/CHAT_ID 미설정 — 파일 발송 건너뜀")
        return False
    fields = {"chat_id": chat_id}
    if caption:
        fields["caption"] = caption[:CAPTION_MAX]
    body = _multipart_body(fields, file_field, filename, file_bytes, content_type)
    req = urllib.request.Request(
        api.format(token=token), data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={_BOUNDARY}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception as e:  # noqa: BLE001 — url/token 노출 금지
        print(f"[TELEGRAM][WARN] 파일 발송 실패: {type(e).__name__}")
        return False


def send_photo(image_bytes: bytes, caption: str = "", filename: str = "report.png") -> bool:
    """PNG 이미지 1건 발송(sendPhoto)."""
    return _send_file(_API_PHOTO, "photo", filename, image_bytes, "image/png", caption)


def send_document(file_bytes: bytes, filename: str, caption: str = "",
                  content_type: str = "text/html") -> bool:
    """파일 1건 발송(sendDocument). 대시보드 HTML·리포트 파일용."""
    return _send_file(_API_DOC, "document", filename, file_bytes, content_type, caption)
