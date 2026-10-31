"""알림 정리(2026-11-01) — ① send_report 가 실제 발송 결과를 남긴다 ② 큰 급감을 쓴 실행은 '✅'로 시작하지 않는다."""
from unittest import mock

from src import notify
from scripts.send_telegram_summary import build_brief


def _결과줄(capsys):
    return [l for l in capsys.readouterr().out.splitlines() if l.startswith("[TELEGRAM][결과]")]


def test_다_보내면_보냄_줄(capsys):
    with mock.patch.object(notify.time, "sleep", lambda *a: None), \
         mock.patch.object(notify, "send_telegram", return_value=True):
        assert notify.send_report("a") == 0
    assert _결과줄(capsys) == ["[TELEGRAM][결과] 보냄 1/1조각"]


def test_못_보내도_0_이지만_못_보냄_줄과_경고(capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with mock.patch.object(notify.time, "sleep", lambda *a: None), \
         mock.patch.object(notify, "send_telegram", side_effect=[True, False]), \
         mock.patch.object(notify, "split_message", return_value=["x", "y"]):
        assert notify.send_report("xy") == 0
    out = capsys.readouterr().out
    assert "[TELEGRAM][결과] 못 보냄 1/2조각" in out
    assert "::warning::텔레그램 보고 1/2조각 못 보냄" in out


def test_비밀값_없으면_못_보냄으로_남는다(capsys, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert notify.send_report("a") == 0
    assert "[TELEGRAM][결과] 못 보냄 1/1조각" in capsys.readouterr().out


def _요약(status, base=363, cur=0, ratio=1.0):
    return {"success_rate": 1.0, "total_rows_processed": 922, "code_change_suspected": False,
            "exposure_drop": {"status": status, "baseline_exposed": base, "current_exposed": cur,
                              "drop_ratio": ratio, "rows_compared": 922, "rows_unreadable": 0},
            "exposure_drop_status": status, "exposure_drop_hold": False}


def test_사람_스위치로_363에서_0_을_쓴_실행은_체크로_시작하지_않는다():
    msg = build_brief(_요약("풀림(사람 스위치)"), ts="10/31 15:00")
    assert not msg.startswith("✅"), msg
    assert msg.startswith("📉")
    assert "363→0줄(100% 감소)" in msg and "사람 스위치로 그대로 씀" in msg


def test_급감_재확인도_체크로_시작하지_않는다():
    msg = build_brief(_요약("급감 재확인", 552, 173, 0.6866), ts="10/31 18:00")
    assert msg.startswith("📉") and "🔁" in msg


def test_평범한_통과는_그대로_체크():
    msg = build_brief(_요약("통과", 500, 498, 0.004), ts="10/31 18:00")
    assert msg.startswith("✅") and "🔓" not in msg


def test_스위치_실행이라도_멈춤이면_멈춤_글():
    s = _요약("풀림(사람 스위치)")
    s["exposure_drop_hold"] = True
    assert build_brief(s, ts="t").startswith("⏸")


def test_GOYU_NOTIFY_OFF_면_통신하지_않는다(monkeypatch, capsys):
    monkeypatch.setenv("GOYU_NOTIFY_OFF", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    with mock.patch("urllib.request.urlopen") as u:
        assert notify.send_telegram("hi") is False
        assert notify.send_document(b"x", "a.txt") is False if hasattr(notify, "send_document") else True
        assert not u.called
    assert "GOYU_NOTIFY_OFF=1" in capsys.readouterr().out
