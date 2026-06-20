"""telegram_qa_bot: 텔레그램 Q&A 봇 — getUpdates 폴링 → 의도분류 → 답장. M11.

GitHub Actions 5분 cron(공개 repo, 무료)에서 실행. offset 영속 불필요 —
텔레그램 **서버측 ack**(getUpdates offset)로 중복 방지(critic C-2 회피). 사장님(TELEGRAM_CHAT_ID)만 응답.
critic 보강: 독성 메시지 안전추출(ack-only), raw 로깅 금지, 폭주 방지(run당 최대 N), 신선도 고지.
"""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetch_yesterday_backup import download_backup, list_success_runs, pick_run_near_hours  # noqa: E402
from src import llm_intent  # noqa: E402
from src import qa_formatter as qa  # noqa: E402
from src.notify import send_report  # noqa: E402
from src.snapshot_diff import diff_backups, load_backup  # noqa: E402

_API = "https://api.telegram.org/bot{token}/{method}"
MAX_ANSWERS_PER_RUN = 5  # 폭주 방지


def _token():
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def _owner():
    return os.environ.get("TELEGRAM_CHAT_ID", "").strip()


def _tg(method, params=None, timeout=20):
    url = _API.format(token=_token(), method=method)
    data = json.dumps(params or {}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def get_updates(offset=None, timeout=0):
    params = {"timeout": timeout, "limit": 100, "allowed_updates": ["message"]}
    if offset is not None:
        params["offset"] = offset
    try:
        return _tg("getUpdates", params).get("result", [])
    except Exception as e:  # noqa: BLE001 — url/token 노출 금지
        print(f"[QA] getUpdates 실패: {type(e).__name__}")
        return []


def safe_extract(update):
    """update → (update_id, sender_id, text) | None. 파싱 실패=None(ack-only, critic 폴리즌 방어)."""
    try:
        uid = update.get("update_id")
        if uid is None:
            return None
        msg = update.get("message") or {}
        sender = (msg.get("from") or {}).get("id")
        text = msg.get("text") or ""
        return (uid, str(sender) if sender is not None else None, text)
    except Exception:  # noqa: BLE001
        return None


_cache = None


def load_data_once():
    """최신 백업 vs ~24h 백업 → (reports, curr_backup, curr_ts, baseline_available). run당 1회."""
    global _cache
    if _cache is not None:
        return _cache
    runs = list_success_runs()
    curr = prev = None
    curr_ts = "?"
    if runs:
        rs = sorted(runs, key=lambda r: str(r.get("createdAt", "")), reverse=True)
        cid = str(rs[0]["databaseId"])
        cpath = download_backup(cid)
        if cpath:
            curr = load_backup(cpath)
            curr_ts = str(curr.get("timestamp", "?"))
            pid = pick_run_near_hours(runs, rs[0].get("createdAt"), hours=24, tolerance_h=5, exclude_run_id=cid)
            if pid:
                ppath = download_backup(pid)
                if ppath:
                    prev = load_backup(ppath)
    reports = diff_backups(prev, curr) if curr else []
    _cache = (reports, curr, curr_ts, prev is not None)
    return _cache


def answer(text):
    """질문 텍스트 → 답 문자열."""
    reports, curr, curr_ts, has_base = (None, None, "?", False)
    tab_names = []
    # help 는 데이터 없이
    intent0, _ = qa.classify_intent(text, [])
    if intent0 == "help":
        return qa.fmt_help()
    reports, curr, curr_ts, has_base = load_data_once()
    if not curr:
        return "데이터를 아직 못 불러왔어요(백업 없음). 잠시 후 다시 물어봐 주세요."
    tab_names = list((curr.get("tabs") or {}).keys())
    intent, arg, confident = qa.classify_with_confidence(text, tab_names)
    if not confident:
        # 키워드로 확신 못한 자유 질문만 Groq 자연어 분류(질문 글만 전송). 실패 시 키워드 결과 유지.
        llm = llm_intent.classify(text, tab_names)
        if llm:
            intent, arg = llm
    header = qa.fmt_header(curr_ts, has_base)
    builders = {
        "missing": lambda: qa.fmt_missing(reports),
        "deleted": lambda: qa.fmt_deleted(reports),
        "rank": lambda: qa.fmt_rank(reports, arg),
        "product": lambda: qa.fmt_product(reports, arg),
        "type": lambda: qa.fmt_type(reports),
        "jisikin": lambda: qa.fmt_jisikin(reports),
        "summary": lambda: qa.fmt_summary(reports),
        "keyword": lambda: qa.fmt_keyword(curr, arg),
    }
    b = builders.get(intent)
    if b is None:
        return qa.fmt_help()
    return header + "\n\n" + b()


def main():
    if not _token() or not _owner():
        print("[QA][SKIP] secret 미설정")
        return 0
    try:
        _tg("deleteWebhook", {})  # 폴링 충돌 방지(idempotent)
    except Exception:  # noqa: BLE001
        pass
    updates = get_updates(timeout=0)
    if not updates:
        print("[QA] 새 메시지 없음")
        return 0
    owner = _owner()
    max_uid = None
    answered = 0
    for u in updates:
        ex = safe_extract(u)
        mid = ex[0] if ex else u.get("update_id")
        if mid is not None and (max_uid is None or mid > max_uid):
            max_uid = mid
        if ex is None:
            continue  # 파싱 실패 = ack만
        uid, sender, text = ex
        if sender != owner:
            continue  # 남의 메시지 = ack만(무답, 유출 방지)
        if answered >= MAX_ANSWERS_PER_RUN:
            continue  # 폭주 방지
        try:
            send_report(answer(text))
            answered += 1
        except Exception as e:  # noqa: BLE001
            print(f"[QA] 답장 실패: {type(e).__name__}")
    # 서버측 ack (답장 시도 끝난 뒤 = at-least-once)
    if max_uid is not None:
        get_updates(offset=max_uid + 1, timeout=0)
    print(f"[QA] update {len(updates)}건 · 답장 {answered}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
