# -*- coding: utf-8 -*-
"""comment_reads — 댓글 읽기 결과를 날짜 넘어 기억한다 + read_all 예산·차단기.

왜 있나: 키워드가 1,240개로 늘며 하루 댓글 2.6만 건이 됐는데 매일 처음부터 다시
읽으니 무료 한도(하루 20만 토큰)와 시간(180분)을 다 태웠다 — 7/29~8/16 매일 밤
시간 초과 취소, 8/17~19 모델 404. 한 달간 시트가 어제(실은 7/23) 값에 멈춰 있었다.
읽은 결과를 남기면 다음 날은 새 댓글만 읽는다(brand_verdicts 와 같은 무늬).
"""
import pytest

from scripts import collect_comment_brands as ccb
from src import brand_from_comments, comment_reads


def test_한번_읽은_댓글은_기억한다(tmp_path):
    path = str(tmp_path / "reads.json")
    reads = comment_reads.load(path)
    comment_reads.put(reads, "안티트로 정착했어요", ["안티트로"], "2026-08-20")
    comment_reads.put(reads, "그냥 잡담", [], "2026-08-20")
    assert comment_reads.save(reads, path)
    다시 = comment_reads.load(path)
    assert comment_reads.get(다시, "안티트로 정착했어요") == ["안티트로"]
    assert comment_reads.get(다시, "그냥 잡담") == []       # 제품 없던 댓글도 '읽었다'
    assert comment_reads.get(다시, "처음 보는 댓글") is None


def test_오래_안_보인_댓글은_청소된다():
    reads = {}
    comment_reads.put(reads, "옛날 댓글", [], "2026-06-01")
    comment_reads.put(reads, "요즘 댓글", [], "2026-08-19")
    남은 = comment_reads.prune(reads, "2026-08-20")
    assert comment_reads.get(남은, "옛날 댓글") is None
    assert comment_reads.get(남은, "요즘 댓글") == []


def test_다시_보인_댓글은_날짜가_되살아나_청소를_피한다():
    reads = {}
    comment_reads.put(reads, "계속 보이는 댓글", ["안티트로"], "2026-06-01")
    comment_reads.touch(reads, "계속 보이는 댓글", "2026-08-20")
    남은 = comment_reads.prune(reads, "2026-08-20")
    assert comment_reads.get(남은, "계속 보이는 댓글") == ["안티트로"]


def test_깨진_파일이면_빈것으로_시작(tmp_path):
    p = tmp_path / "깨짐.json"
    p.write_text("{망가", encoding="utf-8")
    assert comment_reads.load(str(p)) == {}


# ── read_all 예산·차단기 ────────────────────────────────────────────────────

def test_회차_예산을_다_쓰면_멈추고_남은건_못읽은걸로_센다(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    calls = {"n": 0}

    def fake_read_batch(texts, **kw):
        calls["n"] += 1
        return {}

    monkeypatch.setattr(brand_from_comments, "read_batch", fake_read_batch)
    texts = [f"댓글{i}" for i in range(100)]        # 20개씩 5묶음
    out, stat = brand_from_comments.read_all(texts, max_batches=2)
    assert calls["n"] == 2                           # 예산만큼만 불렀다
    assert stat["묶음"] == 5 and stat["못읽은묶음"] == 3
    assert stat["예산사용"] == 2
    assert any("다음 회차" in x for x in stat["탈"])


def test_연속으로_실패하면_그만두고_한도만_태우지_않는다(monkeypatch):
    # 8/19 실사고 재현: 모델 404 로 1,304묶음을 전부 헛호출하며 시간을 태웠다.
    monkeypatch.setenv("GROQ_API_KEY", "k")
    calls = {"n": 0}

    def fake_read_batch(texts, **kw):
        calls["n"] += 1
        return None

    monkeypatch.setattr(brand_from_comments, "read_batch", fake_read_batch)
    texts = [f"댓글{i}" for i in range(400)]        # 20묶음
    out, stat = brand_from_comments.read_all(texts)
    assert calls["n"] == 5                           # 5연속 실패에서 끊었다
    assert stat["못읽은묶음"] == 20                   # 안 부른 몫도 못읽은걸로 정직하게


def test_성공한_묶음은_빈_결과라도_읽은자리에_남는다(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")

    def fake_read_batch(texts, **kw):
        return {0: ["안티트로"]} if "안티트로" in texts[0] else {}

    monkeypatch.setattr(brand_from_comments, "read_batch", fake_read_batch)
    out, stat = brand_from_comments.read_all(["안티트로 써요", "잡담"], batch=1)
    assert out == {0: ["안티트로"]}
    assert stat["읽은자리"] == {0, 1}                # 빈 결과(잡담)도 '읽은 자리'다


# ── extract_brands 가 캐시를 실제로 쓴다 ────────────────────────────────────

def test_읽은_댓글은_AI_에_다시_보내지_않는다(tmp_path, monkeypatch):
    reads_path = str(tmp_path / "reads.json")
    verdict_path = str(tmp_path / "verdicts.json")
    reads = {}
    comment_reads.put(reads, "안티트로 정착했어요", ["안티트로"], "2026-08-19")
    comment_reads.save(reads, reads_path)

    보낸것 = []

    def fake_read_all(texts, **kw):
        보낸것.extend(texts)
        return {0: ["맥단비"]}, {"댓글": len(texts), "묶음": 1, "못읽은묶음": 0,
                                "탈": [], "뽑은이름": 1, "예산사용": 1,
                                "읽은자리": {0}}

    monkeypatch.setattr(ccb.brand_from_comments, "read_all", fake_read_all)
    monkeypatch.setattr(ccb.shop_probe, "verified",
                        lambda names, stat=None: (list(names), {}))

    mentions = [
        {"댓글": "안티트로 정착했어요", "키워드": "비듬샴푸", "글": "u1", "원천": "댓글"},
        {"댓글": "맥단ㅂI 써봤는데", "키워드": "비듬샴푸", "글": "u2", "원천": "댓글"},
    ]
    ms, verdicts, stat = ccb.extract_brands(
        mentions, verdict_path=verdict_path, today="2026-08-20", reads_path=reads_path)

    assert 보낸것 == ["맥단ㅂI 써봤는데"]             # 캐시에 있던 건 안 보냈다
    assert stat["캐시읽음"] == 1
    assert {m["키"] for m in ms} == {"안티트로", "맥단비"}   # 캐시 이름 + 새 이름 둘 다 산다
    다시 = comment_reads.load(reads_path)
    assert comment_reads.get(다시, "맥단ㅂI 써봤는데") == ["맥단비"]   # 새로 읽은 것도 남았다


def test_못_읽은_댓글은_캐시에_남기지_않는다(tmp_path, monkeypatch):
    # 실패를 '읽었는데 없음'으로 남기면 그 댓글은 영원히 다시 안 읽는다 — 구분이 생명.
    reads_path = str(tmp_path / "reads.json")
    verdict_path = str(tmp_path / "verdicts.json")

    def fake_read_all(texts, **kw):
        return {}, {"댓글": len(texts), "묶음": 1, "못읽은묶음": 1,
                    "탈": ["HTTP 429"], "뽑은이름": 0, "예산사용": 1,
                    "읽은자리": set()}

    monkeypatch.setattr(ccb.brand_from_comments, "read_all", fake_read_all)
    monkeypatch.setattr(ccb.shop_probe, "verified",
                        lambda names, stat=None: (list(names), {}))

    mentions = [{"댓글": "새 댓글", "키워드": "비듬샴푸", "글": "u1", "원천": "댓글"}]
    ccb.extract_brands(mentions, verdict_path=verdict_path,
                       today="2026-08-20", reads_path=reads_path)
    다시 = comment_reads.load(reads_path)
    assert comment_reads.get(다시, "새 댓글") is None   # 내일 다시 읽는다
