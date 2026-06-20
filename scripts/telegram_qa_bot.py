"""telegram_qa_bot: 텔레그램 Q&A 봇 — long-poll 루프 → 의도분류 → 답장. M11+M12.

GitHub Actions(공개 repo, 무료·무제한)에서 실행. **long-polling 루프**(getUpdates timeout)로
메시지가 오는 즉시(보통 몇 초) 답한다 — 예전 '5분마다 한 번 확인'의 지연 제거(M12).
한 run 은 예산(QA_LOOP_SECONDS, 기본 4h) 동안 계속 듣다가 종료 → cron `*/5` 가 큐에 대기시킨
다음 run 이 곧바로 이어받음(concurrency cancel-in-progress=false 핸드오프). 공개 repo Actions 무료.
offset 영속 불필요 — 텔레그램 **서버측 ack**(getUpdates offset)로 중복 방지. 사장님(TELEGRAM_CHAT_ID)만 응답.
critic 보강: 독성 메시지 안전추출(ack-only), raw 로깅 금지, 폭주 방지(배치당 최대 N), 신선도 고지.
"""
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fetch_yesterday_backup import download_backup, list_success_runs, pick_run_near_hours  # noqa: E402
from src import llm_answer  # noqa: E402
from src import llm_intent  # noqa: E402
from src import qa_context  # noqa: E402
from src import qa_formatter as qa  # noqa: E402
from src.notify import send_report  # noqa: E402
from src.snapshot_diff import diff_backups, load_backup  # noqa: E402

_API = "https://api.telegram.org/bot{token}/{method}"
MAX_ANSWERS_PER_BATCH = 5  # 배치당 폭주 방지(long-poll 한 응답에서 최대 N건)


def _token():
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def _owner():
    return os.environ.get("TELEGRAM_CHAT_ID", "").strip()


def _loop_budget():
    """이 run 이 듣는 시간(초). 기본 4h — Actions 잡 6h 한도 안전 내. cron 이 다음 run 핸드오프."""
    try:
        return max(0.0, float(os.environ.get("QA_LOOP_SECONDS", "14400")))
    except ValueError:
        return 14400.0


def _data_ttl():
    """백업 데이터 캐시 수명(초). 기본 30분 — 4h 루프 중 새 점검(6h 주기) 반영(staleness 방지)."""
    try:
        return max(0.0, float(os.environ.get("QA_DATA_TTL", "1800")))
    except ValueError:
        return 1800.0


def _poll_timeout():
    """getUpdates long-poll 대기 초. 서버가 이 시간 동안 잡고 있다가 메시지 오면 즉시 반환."""
    try:
        return max(0, int(os.environ.get("QA_POLL_TIMEOUT", "50")))
    except ValueError:
        return 50


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
        # 소켓 타임아웃 > 텔레그램 long-poll timeout (서버가 timeout 초간 연결 유지) → +15 여유
        return _tg("getUpdates", params, timeout=timeout + 15).get("result", [])
    except Exception as e:  # noqa: BLE001 — url/token 노출 금지
        print(f"[QA] getUpdates 실패: {type(e).__name__}")
        return None  # None=호출 에러(루프가 backoff), []=정상 빈 결과 와 구분


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
_cache_ts = 0.0


def load_data_once():
    """최신 백업 vs ~24h 백업 → (reports, curr_backup, curr_ts, baseline_available).

    TTL 캐시(기본 30분): long-poll 루프가 4h 도는 동안 새 점검(6h 주기) 결과를 반영한다.
    (예전 5분 1회 프로세스 땐 매 run 이 신선했음 — 장수 프로세스 staleness 회귀 차단.)
    """
    global _cache, _cache_ts
    now = time.monotonic()
    if _cache is not None and (now - _cache_ts) < _data_ttl():
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
    _cache_ts = now
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
    header = qa.fmt_header(curr_ts, has_base)
    # 1순위 '똑똑한 답': AI(Groq)가 압축 데이터로 직접 작성 (D-059). 실패/키없음 시 템플릿 폴백.
    smart = llm_answer.compose(text, qa_context.build_context(reports, curr))
    if smart:
        return header + "\n\n" + smart
    # 폴백: 기존 키워드/의도 → 고정 템플릿 (AI 미사용 시에도 봇 동작 보장)
    tab_names = list((curr.get("tabs") or {}).keys())
    intent, arg, confident = qa.classify_with_confidence(text, tab_names)
    if not confident:
        llm = llm_intent.classify(text, tab_names)
        if llm:
            intent, arg = llm
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


def _handle_batch(updates, owner):
    """updates 배치 처리 → (answered, max_uid). owner 외 무답(ack만), 파싱실패 ack만, 배치당 폭주 cap."""
    max_uid = None
    answered = 0
    for u in updates:
        ex = safe_extract(u)
        mid = ex[0] if ex else u.get("update_id")
        if mid is not None and (max_uid is None or mid > max_uid):
            max_uid = mid
        if ex is None:
            continue  # 파싱 실패 = ack만
        _, sender, text = ex
        if sender != owner:
            continue  # 남의 메시지 = ack만(무답, 유출 방지)
        if answered >= MAX_ANSWERS_PER_BATCH:
            continue  # 폭주 방지
        try:
            send_report(answer(text))
            answered += 1
        except Exception as e:  # noqa: BLE001
            print(f"[QA] 답장 실패: {type(e).__name__}")
    return answered, max_uid


def main():
    if not _token() or not _owner():
        print("[QA][SKIP] secret 미설정")
        return 0
    try:
        _tg("deleteWebhook", {})  # 폴링 충돌 방지(idempotent)
    except Exception:  # noqa: BLE001
        pass
    owner = _owner()
    budget = _loop_budget()
    poll_to = _poll_timeout()
    start = time.monotonic()
    offset = None
    total = 0
    loops = 0
    backoff = 1
    # long-poll 루프: 메시지 오면 즉시(몇 초) 답, 없으면 서버가 poll_to 초 잡고 있다 반환.
    while time.monotonic() - start < budget:
        loops += 1
        updates = get_updates(offset=offset, timeout=poll_to)
        if updates is None:  # 호출 에러 → 지수 backoff(로그·텔레그램 API 폭주 방지)
            time.sleep(min(backoff, 60))
            backoff = min(backoff * 2, 60)
            continue
        backoff = 1
        if not updates:  # 정상 빈 결과(long-poll timeout) → 즉시 재폴(지연 0)
            if poll_to <= 0:
                time.sleep(1)  # 단축폴 설정 시에만 tight-loop 방지
            continue
        answered, max_uid = _handle_batch(updates, owner)
        total += answered
        if max_uid is not None:
            offset = max_uid + 1  # 다음 getUpdates 에 실어 서버측 ack + 재수신 방지
    if offset is not None:
        get_updates(offset=offset, timeout=0)  # 마지막 배치 서버 ack(재시작 시 중복 답 방지)
    print(f"[QA] long-poll 루프 {loops}회 · 답장 {total}건 · budget 종료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
