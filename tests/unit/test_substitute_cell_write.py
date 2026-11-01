"""대체 노출 1위 초록 글자 조건부 서식 · 같은 글 최고 순위 (2026-11-01).

2026-11-01 사장님 "아니지 지금 노출영역칸이지" 이후 초록 글자 규칙은 따로 둔 '대체 노출' 칸이 아니라
노출영역(K) 칸에 건다(sheets.ensure_substitute_k). K 칸 덮어쓰기 · 옛 칸 없애기 시험은 test_대체노출_K덮어쓰기.py.
여기 남은 것: 규칙은 두 번 걸어도 1개 · 503 뒤에도 1개 · 범위 · 색 고치기 · 넓은 범위 알아보기(GPT 1·2차 지적 C·D·2·3),
같은 글이 두 구좌에 뜨면 가장 좋은 순위로(지적 B).
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from src import substitute as sub
from src.sheets import SheetsClient

TAB = "샴푸 카외"
URL_A = "https://cafe.naver.com/a/1"
URL_B = "https://cafe.naver.com/b/2"
OWN = "https://cafe.naver.com/own/9"

def _client(headers, all_values=None):
    creds = json.dumps({
        "type": "service_account", "client_email": "x@example.iam.gserviceaccount.com",
        "private_key": "[REDACTED PRIVATE KEY]\n", "token_uri": "https://oauth2.googleapis.com/token",
    })
    with patch("src.sheets.gspread.service_account_from_dict") as auth:
        gc, sheet, ws = MagicMock(), MagicMock(), MagicMock()
        ws.id = 777
        ws.col_count = len(headers)
        ws.row_values.return_value = headers
        ws.get_all_values.return_value = all_values if all_values is not None else [headers]
        sheet.worksheet.return_value = ws
        gc.open_by_key.return_value = sheet
        auth.return_value = gc
        client = SheetsClient(spreadsheet_id="abc", service_account_json=creds)
    return client, ws


def _written(ws):
    out = {}
    for call in ws.batch_update.call_args_list:
        for item in call.args[0]:
            out[item["range"]] = item["values"][0][0]
    return out


RULE_HEADERS = ["키워드", "링크", "작업일", "작업자", "유형", "카페", "노출영역"]
# 노출영역(K 역할) = 7번째 칸 = G (index 6) — 규칙 대상 칸


# ── 2026-11-01 1위 초록 글자 조건부 서식 ──────────────────────────────────

def _rule_requests(client):
    out = []
    for call in client.spreadsheet.batch_update.call_args_list:
        for req in call.args[0]["requests"]:
            if "addConditionalFormatRule" in req:
                out.append(req["addConditionalFormatRule"])
    return out


def _with_live_rules(client):
    """spreadsheet.batch_update 로 더한 규칙을 다음 fetch_sheet_metadata 가 돌려주게(실제 시트처럼)."""
    rules: list = []

    def fetch(params=None):
        return {"sheets": [{"properties": {"sheetId": 777}, "conditionalFormats": list(rules)}]}

    def batch(body):
        for req in body["requests"]:
            if "addConditionalFormatRule" in req:
                rules.append(req["addConditionalFormatRule"]["rule"])
        return {}

    client.spreadsheet.fetch_sheet_metadata.side_effect = fetch
    client.spreadsheet.batch_update.side_effect = batch
    return rules


class TestSubstituteRank1Format:
    def test_초록_글자_규칙_내용(self):
        client, _ = _client(RULE_HEADERS)
        _with_live_rules(client)
        out = client.ensure_substitute_k(TAB)
        assert out["formats_added"] == 1
        (req,) = _rule_requests(client)
        rule = req["rule"]
        assert req["index"] == 0
        assert rule["ranges"] == [{"sheetId": 777, "startRowIndex": 1, "startColumnIndex": 6, "endColumnIndex": 7}]  # G
        cond = rule["booleanRule"]["condition"]
        assert cond == {"type": "TEXT_STARTS_WITH", "values": [{"userEnteredValue": "대체노출 1위"}]}
        assert cond["values"][0]["userEnteredValue"] == sub.RANK1_CELL_PREFIX
        color = rule["booleanRule"]["format"]["textFormat"]["foregroundColor"]
        assert "#%02X%02X%02X" % tuple(round(color[c] * 255) for c in ("red", "green", "blue")) == "#188038"

    def test_같은_클라이언트로_두번_불러도_규칙_1개(self):
        client, _ = _client(RULE_HEADERS)
        rules = _with_live_rules(client)
        client.ensure_substitute_k(TAB)
        out2 = client.ensure_substitute_k(TAB)
        assert out2["formats_added"] == 0
        assert len(rules) == 1

    def test_다음_회차_새_클라이언트도_시트_규칙을_읽고_안_더함(self):
        client1, _ = _client(RULE_HEADERS)
        rules = _with_live_rules(client1)
        client1.ensure_substitute_k(TAB)
        client2, _ = _client(RULE_HEADERS)
        client2.spreadsheet.fetch_sheet_metadata.return_value = {
            "sheets": [{"properties": {"sheetId": 777}, "conditionalFormats": list(rules)}]}
        out = client2.ensure_substitute_k(TAB)
        assert out["formats_added"] == 0
        assert _rule_requests(client2) == []

    def test_다른_칸이나_다른_조건의_규칙은_같은_규칙으로_안_봄(self):
        client, _ = _client(RULE_HEADERS)
        other_col = {"ranges": [{"sheetId": 777, "startRowIndex": 1, "startColumnIndex": 2, "endColumnIndex": 3}],
                     "booleanRule": {"condition": {"type": "TEXT_STARTS_WITH",
                                                   "values": [{"userEnteredValue": "대체노출 1위"}]}}}
        other_cond = {"ranges": [{"sheetId": 777, "startRowIndex": 1, "startColumnIndex": 6, "endColumnIndex": 7}],
                      "booleanRule": {"condition": {"type": "TEXT_CONTAINS",
                                                    "values": [{"userEnteredValue": "인기글"}]}}}
        client.spreadsheet.fetch_sheet_metadata.return_value = {
            "sheets": [{"properties": {"sheetId": 777}, "conditionalFormats": [other_col, other_cond]}]}
        out = client.ensure_substitute_k(TAB)
        assert out["formats_added"] == 1

    def test_서식_목록_못_읽으면_안_더함(self):
        client, _ = _client(RULE_HEADERS)
        client.spreadsheet.fetch_sheet_metadata.side_effect = RuntimeError("403")
        out = client.ensure_substitute_k(TAB)
        assert out["formats_added"] == 0
        assert _rule_requests(client) == []

# ── 2026-11-01 GPT 1차 검토 지적 A~D ─────────────────────────────────────
# A. (옛 '대체 노출' 칸의 옛 형식 값 비우기 — 11-01 그 칸을 없애며 함께 사라짐)
# B. 같은 글이 위 구좌 2위 · 아래 구좌 1위면 scan 이 위쪽만 남겨 1위를 놓친다.
# C. 규칙 추가가 서버엔 들어갔는데 503 → 다시 보내 규칙 2개. 같은 규칙이 여럿이면 하나만 남긴다.
# D. 같은 조건 · 같은 칸이지만 범위가 일부 행뿐이거나 색이 다른 규칙도 '있다'로 쳤다 → 맞게 고친다.

from src.parser import OurPostHit  # noqa: E402

PREFIX = sub.RANK1_CELL_PREFIX
GREEN = {"red": 24 / 255, "green": 128 / 255, "blue": 56 / 255}


class TestScanSamePostBestRank:
    """지적 B."""

    def _scan(self, monkeypatch, found):
        idx = sub.build_index({"다른탭": [{"링크": URL_A}, {"링크": URL_B}]})
        monkeypatch.setattr(sub, "find_all_our_posts",
                            lambda html, is_ours: [h for h in found if is_ours(h.url)])
        return sub.scan("<html/>", idx, TAB, "kw", own_link=OWN)

    def test_위_구좌_2위_아래_구좌_1위인_같은_글이면_1위(self, monkeypatch):
        hits = self._scan(monkeypatch, [
            OurPostHit(area="스마트블록", integrated_rank=4, cafe_slot_rank=2, url=URL_A, block_name="b"),
            OurPostHit(area="인기글", integrated_rank=7, cafe_slot_rank=1, url=URL_A),
        ])
        assert sub.rank1_url(hits) == URL_A
        assert len(hits) == 1  # 기록 형식 그대로: 같은 글은 한 줄
        assert hits[0]["area"] == "인기글" and hits[0]["cafe_rank"] == 1

    def test_같은_글_위가_더_좋으면_위쪽_그대로_순서도_그대로(self, monkeypatch):
        hits = self._scan(monkeypatch, [
            OurPostHit(area="AB", integrated_rank=1, cafe_slot_rank=1, url=URL_A),
            OurPostHit(area="스마트블록", integrated_rank=5, cafe_slot_rank=3, url=URL_B, block_name="b"),
            OurPostHit(area="인기글", integrated_rank=6, cafe_slot_rank=2, url=URL_A),
        ])
        assert [(h["url"], h["area"], h["cafe_rank"]) for h in hits] == [
            (URL_A, "AB", 1), (URL_B, "스마트블록", 3)]


def _our_rule(col=6, *, start_row=1, end_row=None, color=None, sheet_id=777):
    rg = {"sheetId": sheet_id, "startRowIndex": start_row, "startColumnIndex": col, "endColumnIndex": col + 1}
    if end_row is not None:
        rg["endRowIndex"] = end_row
    return {"ranges": [rg],
            "booleanRule": {"condition": {"type": "TEXT_STARTS_WITH", "values": [{"userEnteredValue": PREFIX}]},
                            "format": {"textFormat": {"foregroundColor": dict(color or GREEN)}}}}


class _LiveSheet:
    """조건부 서식 규칙을 실제 시트처럼 들고 add/update/delete 요청을 적용한다."""

    def __init__(self, client, rules, fail_after_apply=0):
        self.rules = list(rules)
        self.fail_after_apply = fail_after_apply  # 서버엔 들어갔는데 503 응답을 몇 번 돌려줄지
        client.spreadsheet.fetch_sheet_metadata.side_effect = self.fetch
        client.spreadsheet.batch_update.side_effect = self.batch

    def fetch(self, params=None):
        return {"sheets": [{"properties": {"sheetId": 777},
                            "conditionalFormats": [json.loads(json.dumps(r)) for r in self.rules]}]}

    def batch(self, body):
        import gspread
        for req in body["requests"]:
            if "addConditionalFormatRule" in req:
                a = req["addConditionalFormatRule"]
                self.rules.insert(a.get("index", 0), a["rule"])
            elif "updateConditionalFormatRule" in req:
                u = req["updateConditionalFormatRule"]
                assert u["sheetId"] == 777
                self.rules[u["index"]] = u["rule"]
            elif "deleteConditionalFormatRule" in req:
                d = req["deleteConditionalFormatRule"]
                assert d["sheetId"] == 777
                del self.rules[d["index"]]
        if self.fail_after_apply:
            self.fail_after_apply -= 1
            resp = MagicMock()
            resp.status_code = 503
            resp.json.return_value = {"error": {"code": 503, "message": "unavailable", "status": "UNAVAILABLE"}}
            raise gspread.exceptions.APIError(resp)
        return {}

    def ours(self, col=6):
        return [r for r in self.rules
                if r["booleanRule"]["condition"].get("values") == [{"userEnteredValue": PREFIX}]
                and r["ranges"][0]["startColumnIndex"] == col]


@pytest.fixture
def _no_sleep(monkeypatch):
    monkeypatch.setattr("src.sheets.time.sleep", lambda s: None)


class TestRank1FormatRetryAndDedup:
    """지적 C · D."""

    def test_503_뒤_다시_보내도_규칙은_1개(self, _no_sleep):
        client, _ = _client(RULE_HEADERS)
        live = _LiveSheet(client, [], fail_after_apply=1)
        client.ensure_substitute_k(TAB)
        assert len(live.ours()) == 1

    def test_같은_규칙이_둘이면_하나만_남김_다른_규칙은_그대로(self, _no_sleep):
        other = {"ranges": [{"sheetId": 777, "startRowIndex": 1, "startColumnIndex": 2, "endColumnIndex": 3}],
                 "booleanRule": {"condition": {"type": "TEXT_CONTAINS", "values": [{"userEnteredValue": "인기글"}]},
                                 "format": {"textFormat": {"bold": True}}}}
        client, _ = _client(RULE_HEADERS)
        live = _LiveSheet(client, [_our_rule(), other, _our_rule()])
        out = client.ensure_substitute_k(TAB)
        assert len(live.ours()) == 1
        assert other in live.rules and len(live.rules) == 2
        assert out["formats_added"] == 0

    def test_범위가_일부_행뿐이면_2행부터_끝까지로_고침(self, _no_sleep):
        client, _ = _client(RULE_HEADERS)
        live = _LiveSheet(client, [_our_rule(end_row=50)])
        client.ensure_substitute_k(TAB)
        (rule,) = live.ours()
        assert rule["ranges"] == [{"sheetId": 777, "startRowIndex": 1, "startColumnIndex": 6, "endColumnIndex": 7}]

    def test_색이_다르면_초록으로_고침(self, _no_sleep):
        client, _ = _client(RULE_HEADERS)
        live = _LiveSheet(client, [_our_rule(color={"red": 1.0, "green": 0.0, "blue": 0.0})])
        client.ensure_substitute_k(TAB)
        (rule,) = live.ours()
        color = rule["booleanRule"]["format"]["textFormat"]["foregroundColor"]
        assert "#%02X%02X%02X" % tuple(round(color[c] * 255) for c in ("red", "green", "blue")) == "#188038"

    def test_맞는_규칙_하나면_아무_요청도_안_보냄(self, _no_sleep):
        client, _ = _client(RULE_HEADERS)
        _LiveSheet(client, [_our_rule()])
        client.ensure_substitute_k(TAB)
        client.spreadsheet.batch_update.assert_not_called()


# ── 2026-11-01 GPT 2차 검토 지적 1~3 ─────────────────────────────────────
# 1(A). (옛 칸 값 비우기 — 11-01 그 칸을 없애며 함께 사라짐. '지우기 직전 다시 읽기'는 옛 칸 없애기에 그대로 씀)
# 2(D). 같은 조건인데 범위가 옆 칸까지 넓은 규칙(G:H)을 우리 규칙으로 못 알아보고 하나 더 만든다.
# 3(D). 색 판정이 옛 foregroundColor 를 foregroundColorStyle 보다 먼저 본다(실제로는 Style 이 이김).


def _wide_rule(start_col, end_col, value=None):
    return {"ranges": [{"sheetId": 777, "startRowIndex": 1, "startColumnIndex": start_col, "endColumnIndex": end_col}],
            "booleanRule": {"condition": {"type": "TEXT_STARTS_WITH",
                                          "values": [{"userEnteredValue": value or PREFIX}]},
                            "format": {"textFormat": {"foregroundColor": dict(GREEN)}}}}


def _prefix_rules(live, value=PREFIX):
    return [r for r in live.rules if r["booleanRule"]["condition"].get("values") == [{"userEnteredValue": value}]]


class TestRank1RuleWideRange:
    """2차 지적 2."""

    @pytest.mark.parametrize("start_col,end_col", [(6, 8), (5, 7), (5, 9)])  # G:H · F:G · F:I — 모두 G 포함
    def test_대상칸을_포함한_넓은_범위는_우리_규칙으로_보고_한칸으로_고침(self, _no_sleep, start_col, end_col):
        client, _ = _client(RULE_HEADERS)
        live = _LiveSheet(client, [_wide_rule(start_col, end_col)])
        out = client.ensure_substitute_k(TAB)
        (rule,) = _prefix_rules(live)
        assert rule["ranges"] == [{"sheetId": 777, "startRowIndex": 1, "startColumnIndex": 6, "endColumnIndex": 7}]
        assert out["formats_added"] == 0 and out["formats_fixed"] == 1

    def test_조건값이_다른_넓은_규칙은_손대지_않음(self, _no_sleep):
        other = _wide_rule(6, 8, value="대체노출")
        client, _ = _client(RULE_HEADERS)
        live = _LiveSheet(client, [other])
        out = client.ensure_substitute_k(TAB)
        assert other in live.rules  # 그대로
        assert len(_prefix_rules(live)) == 1 and out["formats_added"] == 1

    def test_대상칸을_안_덮는_규칙은_우리_규칙_아님(self, _no_sleep):
        other = _wide_rule(7, 9)  # H:I — G 를 안 덮음
        client, _ = _client(RULE_HEADERS)
        live = _LiveSheet(client, [other])
        out = client.ensure_substitute_k(TAB)
        assert other in live.rules and out["formats_added"] == 1


class TestRank1ColorStyleFirst:
    """2차 지적 3."""

    RED = {"red": 1.0, "green": 0.0, "blue": 0.0}

    def _rule(self, legacy, style):
        rule = _our_rule()
        rule["booleanRule"]["format"]["textFormat"] = {"foregroundColor": dict(legacy),
                                                       "foregroundColorStyle": {"rgbColor": dict(style)}}
        return rule

    def test_Style이_빨강이면_옛_칸이_초록이어도_고침(self, _no_sleep):
        client, _ = _client(RULE_HEADERS)
        live = _LiveSheet(client, [self._rule(GREEN, self.RED)])
        out = client.ensure_substitute_k(TAB)
        assert out["formats_fixed"] == 1
        (rule,) = live.ours()
        tf = rule["booleanRule"]["format"]["textFormat"]
        assert "foregroundColorStyle" not in tf
        assert "#%02X%02X%02X" % tuple(round(tf["foregroundColor"][c] * 255) for c in ("red", "green", "blue")) == "#188038"

    def test_Style이_초록이면_옛_칸이_빨강이어도_안_고침(self, _no_sleep):
        client, _ = _client(RULE_HEADERS)
        _LiveSheet(client, [self._rule(self.RED, GREEN)])
        out = client.ensure_substitute_k(TAB)
        client.spreadsheet.batch_update.assert_not_called()
        assert out["formats_fixed"] == 0

    def test_Style이_테마색이면_옛_칸이_초록이어도_고침(self, _no_sleep):
        client, _ = _client(RULE_HEADERS)
        rule = _our_rule()
        rule["booleanRule"]["format"]["textFormat"] = {"foregroundColor": dict(GREEN),
                                                       "foregroundColorStyle": {"themeColor": "ACCENT1"}}
        _LiveSheet(client, [rule])
        out = client.ensure_substitute_k(TAB)
        assert out["formats_fixed"] == 1
