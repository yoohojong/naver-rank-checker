"""대체 노출 1위를 노출영역(K) 칸에 덮어 보이기 (2026-11-01 사장님).

사장님 원문(순서대로):
  "그냥 대체노출 일단 1위인것만 측정? 표기만 해주면 되는거고, 2 ~ 5위는 솔직히 필요없어 … 대체노출 1위 초록색 링크"
  "대체노출이 2 ~ 5위면 따로 덮어씌울 필요 없는거지. 원래 링크있는것들은 그대로 유지해 표기방식. 확인못함은 말이안됨."
  "대체노출 아직 적용 안된거같은데? 대체노출 열이 살아있어."
  "아니지 지금 노출영역칸이지 … 어짜피 덮어씌워졌는데 대체노출이면 우리가 쓴 링크는 아직 안떴구나 대체노출로 떴구나가 바로 보이잖아"

지키는 것:
  - 제 글 못 찾은 줄 + 우리 다른 글 1위 → K 칸에 '대체노출 1위'(그 글 링크 · 초록 글자). 판정 값(raw_노출영역 · 실패 횟수)은 그대로.
  - 2~5위만 · 제 글 찾음 · 찾기 오류 · 사장님 손 K → K 는 평소 규칙 값.
  - 수식 모드: 보이는 K 수식이 입력 키가 같을 때만 링크를 보이고, 입력이 바뀌면 평소 수식(재검사필요).
  - 옛 '대체 노출' · 'raw_대체노출' 칸은 머리글이 맞을 때만(지우기 직전 1행 다시 읽기) 없앤다. 다른 열은 안 지움.
  - 초록 규칙은 K 칸에 하나(두 번 불러도 1개). 다음 회차에 대체가 사라지면 K 는 평소 값으로 돌아온다.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src import substitute as sub
from src.crawler import CafeStatus
from src.health import HealthMonitor
from src.main import _process_row
from src.sheets import (
    HEADER_AREA, HEADER_RAW_AREA, RowUpdate, SheetsClient,
    STALE_FORMULA_WRITE_COLUMNS, SYSTEM_OUTPUT_COLUMNS, SYSTEM_OUTPUT_COLUMNS_EMPTY_LINK,
)

TAB = "샴푸 카외"
URL_A = "https://cafe.naver.com/a/1"
URL_B = "https://cafe.naver.com/b/2"
OWN = "https://cafe.naver.com/own/9"
OLD_VISIBLE = "대체 노출"
OLD_RAW = "raw_대체노출"
PREFIX = "대체노출 1위"
GREEN = {"red": 24 / 255, "green": 128 / 255, "blue": 56 / 255}


def _hit(url, rank, area="인기글"):
    return {"url": url, "area": area, "rank": rank + 3, "cafe_rank": rank, "block": "", "source": "시트"}


def _sub_row(row, hits, error=""):
    return {"tab": TAB, "row": row, "substitute_count": len(hits),
            "substitute_cell": sub.format_cell(hits), "hits": hits, "error": error}


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


def _writes(ws):
    """{범위: (값, value_input_option)}"""
    out = {}
    for call in ws.batch_update.call_args_list:
        for item in call.args[0]:
            out[item["range"]] = (item["values"][0][0], call.kwargs.get("value_input_option"))
    return out


def _apply(updates, sub_rows, **kw):
    kw.setdefault("enabled", True)
    kw.setdefault("index_error", "")
    return sub.apply_cells({TAB: updates}, sub_rows, **kw)


# ── 보통 모드(수식 아님): K 칸 값을 바로 쓰는 길 ─────────────────────────────

PLAIN_HEADERS = ["키워드", "링크", "노출영역", "노출여부(통합탭 순위)", "노출여부(카페구좌순위)", "지식인탭"]
# 노출영역 = C


def _plain_write(sub_rows, *, k="미노출 (11/1 03:00~)", rows=(2,), enabled=True, index_error=""):
    all_values = [PLAIN_HEADERS] + [["kw", OWN, "", "", "", ""] for _ in range(max(rows) - 1)]
    client, ws = _client(PLAIN_HEADERS, all_values)
    updates = [RowUpdate(row=r, columns={HEADER_AREA: k, "노출여부(통합탭 순위)": "", "노출여부(카페구좌순위)": ""})
               for r in rows]
    n = _apply(updates, sub_rows, enabled=enabled, index_error=index_error)
    client.write_results(TAB, updates)
    return n, _writes(ws), updates, client, ws


def _link_formula(url):
    return f'=HYPERLINK("{url}","{PREFIX}")'


class TestPlainK:
    def test_1위면_K칸이_대체노출_1위_링크로_덮임(self):
        n, w, _, _, _ = _plain_write([_sub_row(2, [_hit(URL_A, 1), _hit(URL_B, 2)])])
        assert n == 1
        assert w["C2"] == (_link_formula(URL_A), "USER_ENTERED")

    def test_2위가_먼저_찾혀도_1위_글로_덮음(self):
        _, w, _, _, _ = _plain_write([_sub_row(2, [_hit(URL_B, 2, area="스마트블록"), _hit(URL_A, 1)])])
        assert w["C2"] == (_link_formula(URL_A), "USER_ENTERED")

    @pytest.mark.parametrize("rank", [2, 3, 4, 5])
    def test_2_5위만_있으면_K는_평소_값(self, rank):
        n, w, _, _, _ = _plain_write([_sub_row(2, [_hit(URL_B, rank)])])
        assert n == 0
        assert w["C2"] == ("미노출 (11/1 03:00~)", "RAW")

    def test_제_글_찾은_줄은_K_그대로(self):
        # 3행 = 제 글을 찾아 맞대지 않음(기록 줄 없음)
        _, w, _, _, _ = _plain_write([_sub_row(2, [_hit(URL_A, 1)])], k="인기글 (11/1 03:00~)", rows=(2, 3))
        assert w["C3"] == ("인기글 (11/1 03:00~)", "RAW")
        # 노출 줄은 같은 화면에 다른 1위가 있어도 덮지 않는다
        assert w["C2"] == ("인기글 (11/1 03:00~)", "RAW")

    def test_찾기_오류_줄은_K_그대로(self):
        _, w, _, _, _ = _plain_write([_sub_row(2, [], error="ValueError: 깨진 화면")])
        assert w["C2"] == ("미노출 (11/1 03:00~)", "RAW")

    def test_우리글_목록을_못만들면_K_그대로(self):
        _, w, _, _, _ = _plain_write([_sub_row(2, [_hit(URL_A, 1)])], index_error="APIError: 429")
        assert w["C2"] == ("미노출 (11/1 03:00~)", "RAW")

    def test_사장님_손_K는_덮지_않음(self):
        _, w, _, _, _ = _plain_write([_sub_row(2, [_hit(URL_A, 1)])], k="확인중")
        assert w["C2"] == ("확인중", "RAW")

    @pytest.mark.parametrize("k", ["누락 (10/30 03:00~)", "삭제 (10/31 03:00)"])
    def test_누락_삭제도_덮음(self, k):
        _, w, _, _, _ = _plain_write([_sub_row(2, [_hit(URL_A, 1)])], k=k)
        assert w["C2"] == (_link_formula(URL_A), "USER_ENTERED")

    def test_스위치_끄면_K_그대로(self):
        n, w, updates, _, _ = _plain_write([_sub_row(2, [_hit(URL_A, 1)])], enabled=False)
        assert n == 0
        assert w["C2"] == ("미노출 (11/1 03:00~)", "RAW")
        assert list(updates[0].columns) == [HEADER_AREA, "노출여부(통합탭 순위)", "노출여부(카페구좌순위)"]

    def test_확인못함_글자는_어디에도_안씀(self):
        for case in ([_sub_row(2, [], error="ValueError: x")],
                     [_sub_row(2, [_hit(URL_B, 3)], error="ValueError: x")],
                     [_sub_row(2, [_hit(URL_A, 1)], error="옛 글 출처 못 읽음: 글장부(x)")]):
            _, w, _, _, _ = _plain_write(case)
            assert all("확인 못 함" not in str(v) for v, _ in w.values())

    def test_K_배경색은_판정값_그대로(self):
        # 덮어써도 칸 배경은 진짜 K(미노출 = 빨강)대로 — 우리 글이 안 떴다는 사실은 그대로 보인다
        _, _, _, _, ws = _plain_write([_sub_row(2, [_hit(URL_A, 1)])])
        fmts = [f for c in ws.batch_format.call_args_list for f in c.args[0] if f["range"] == "C2"]
        assert fmts and fmts[0]["format"]["backgroundColor"] == {"red": 1.0, "green": 0.8, "blue": 0.8}

    def test_대체노출_칸은_시스템_출력에서_빠짐(self):
        assert OLD_VISIBLE not in SYSTEM_OUTPUT_COLUMNS
        assert OLD_VISIBLE not in SYSTEM_OUTPUT_COLUMNS_EMPTY_LINK
        assert OLD_RAW not in STALE_FORMULA_WRITE_COLUMNS


# ── 수식 모드: 보이는 K = raw_노출영역 을 비추는 수식 ──────────────────────────

FORMULA_HEADERS = [
    "작업일", "작업자", "유형", "키워드", "MB", "PC", "총합", "작업아이디",
    "카페/게시글", "링크", "노출영역",
    "노출여부(통합탭 순위)", "노출여부(카페구좌순위)", "블로그", "지식인탭",
    "현재입력키", "마지막검사입력키", "raw_노출영역", "raw_통합순위",
    "raw_카페순위", "raw_지식인탭", "마지막검사시각",
]
# 노출영역 = K · 현재입력키 = P · 마지막검사입력키 = Q · raw_노출영역 = R


def _formula_write(sub_rows, *, k="미노출 (11/1 03:00~)"):
    row = {"_row": 2, "키워드": "지루성두피염원인", "링크": OWN}
    all_values = [FORMULA_HEADERS, ["5/21", "", "", "지루성두피염원인", "", "", "", "", "", OWN] + [""] * 12]
    client, ws = _client(FORMULA_HEADERS, all_values)
    upd = RowUpdate(row=2, columns={HEADER_AREA: k, "노출여부(통합탭 순위)": "", "노출여부(카페구좌순위)": ""})
    _apply([upd], sub_rows)
    client.write_stale_formula_results(TAB, [upd], row_context={2: row}, checked_at="2026-11-01 01:00 KST")
    return _writes(ws), client


class TestFormulaK:
    def test_1위면_보이는_K수식이_입력키가_같을때만_링크를_보임(self):
        w, client = _formula_write([_sub_row(2, [_hit(URL_A, 1)])])
        assert w["R2"] == ("미노출 (11/1 03:00~)", "RAW")  # 숨김 판정 값은 그대로
        formula, opt = w["K2"]
        assert opt == "USER_ENTERED"
        normal = client._build_visible_output_formula(
            {h: i for i, h in enumerate(FORMULA_HEADERS)}, 2, HEADER_RAW_AREA, k_column=True)
        assert formula == f'=IF(AND(LEN(P2)>0,P2=Q2),HYPERLINK("{URL_A}","{PREFIX}"),{normal[1:]})'

    @pytest.mark.parametrize("hits,error", [([_hit(URL_B, 2)], ""), ([], "ValueError: x"), ([], "")])
    def test_2위이하_오류_없음이면_K수식_안_건드림(self, hits, error):
        w, _ = _formula_write([_sub_row(2, hits, error)])
        assert "K2" not in w
        assert w["R2"][0] == "미노출 (11/1 03:00~)"

    def test_덮어써도_숨김_판정값_실패횟수_배경색은_대체가_없을때와_같음(self):
        def run(sub_rows):
            row = {"_row": 2, "키워드": "kw", "링크": OWN}
            vals = [FORMULA_HEADERS + ["raw_카페1등실패횟수", "raw_카페실패마지막작업일", "raw_카페실패최대",
                                       "raw_카페1등연속시작", "raw_카페1등달성"],
                    ["10/20", "", "", "kw", "", "", "", "", "", OWN] + [""] * 12 + ["1", "10/18", "1", "", ""]]
            client, ws = _client(vals[0], vals)
            upd = RowUpdate(row=2, columns={HEADER_AREA: "누락 (10/30 03:00~)",
                                            "노출여부(통합탭 순위)": "", "노출여부(카페구좌순위)": ""})
            _apply([upd], sub_rows)
            client.write_stale_formula_results(TAB, [upd], row_context={2: row}, checked_at="2026-11-01 01:00 KST")
            fmts = [f for c in ws.batch_format.call_args_list for f in c.args[0]]
            return _writes(ws), fmts

        w_on, f_on = run([_sub_row(2, [_hit(URL_A, 1)])])
        w_off, f_off = run([_sub_row(2, [_hit(URL_B, 2)])])
        assert w_on.pop("K2")[0].startswith("=IF(")
        assert w_on == w_off  # raw_노출영역 · 실패 횟수 · 1등 기록 · 검사 기준값 전부 같다
        assert f_on == f_off  # K 배경색 · 키워드 칸 색 · 가운데 맞춤도 같다

    def test_옛_raw_대체노출_칸에는_안씀(self):
        w, _ = _formula_write([_sub_row(2, [_hit(URL_A, 1)])])
        assert not any(v == URL_A or str(v).startswith(PREFIX) for v, _ in w.values())

    def test_다음_회차_시작에_K수식이_평소_수식으로_돌아옴(self):
        # 회차 앞 ensure_stale_formula_mode 가 K 칸 전부를 평소 수식으로 다시 쓴다 → 지난 덮어쓰기가 남지 않음
        client, ws = _client(FORMULA_HEADERS)
        client.ensure_stale_formula_mode(TAB, [{"_row": 2}])
        normal = client._build_visible_output_formula(
            {h: i for i, h in enumerate(FORMULA_HEADERS)}, 2, HEADER_RAW_AREA, k_column=True)
        assert _writes(ws)["K2:K2"] == (normal, "USER_ENTERED")


# ── 다음 회차: 덮인 K 를 지난 판정 값으로 읽지 않는다 ───────────────────────

def _crawler(found_html: str):
    c = MagicMock()
    c.fetch_search.return_value = found_html
    c.fetch_cafe_url_status.return_value = CafeStatus.ALIVE
    return c


def test_다음_회차_덮인_K는_raw_판정값으로_읽음(monkeypatch):
    # 보통 모드에서 K 칸이 '대체노출 1위' 로 보이면, 그것을 사장님 손 K 로 여겨 영원히 굳히면 안 된다.
    from src import main as main_mod

    res = MagicMock()
    res.exposure_area = MagicMock(value="미노출")
    res.parser_confidence = 0.0
    res.block_order = []
    res.integrated_rank = None
    res.cafe_slot_rank = None
    res.in_jisikin = False
    monkeypatch.setattr(main_mod, "parse_search_result", lambda html, link=None, **k: res)
    row = {"키워드": "kw", "링크": OWN, HEADER_AREA: PREFIX, HEADER_RAW_AREA: "누락 (10/30 03:00~)",
           "_row": 2, "_tab": TAB}
    cols = _process_row(dict(row), _crawler("<html/>"), HealthMonitor(), today_stamp="11/1 09:00")
    assert cols[HEADER_AREA] == "누락 (10/30 03:00~)"  # 덮인 글자가 아니라 지난 판정(누락 · 시점)을 잇는다

    res.exposure_area = MagicMock(value="인기글")
    res.integrated_rank, res.cafe_slot_rank = 3, 1
    row2 = dict(row)
    row2.pop(HEADER_RAW_AREA)  # 숨김 칸 없는 시트
    cols2 = _process_row(row2, _crawler("<html/>"), HealthMonitor(), today_stamp="11/1 09:00")
    assert cols2[HEADER_AREA].startswith("인기글")  # 굳지 않고 이번 판정으로 바뀜


# ── 옛 '대체 노출' 칸 없애기 + K 칸 초록 규칙 ───────────────────────────────

class _Sheet:
    """머리글 · 조건부 서식 규칙을 실제 시트처럼 들고 deleteDimension · 규칙 요청을 적용한다."""

    def __init__(self, client, ws, headers, rules=(), headers_on_reread=None):
        self.headers = list(headers)
        self.rules = [json.loads(json.dumps(r)) for r in rules]
        self.headers_on_reread = headers_on_reread  # 지우기 직전 다시 읽을 때 보일 머리글(사장님이 열을 옮김)
        self.reads = 0
        self.deleted: list = []
        ws.row_values.side_effect = self.row_values
        client.spreadsheet.fetch_sheet_metadata.side_effect = self.fetch
        client.spreadsheet.batch_update.side_effect = self.batch

    def row_values(self, n):
        assert n == 1
        self.reads += 1
        if self.headers_on_reread is not None and self.reads >= 2:
            return list(self.headers_on_reread)
        return list(self.headers)

    def fetch(self, params=None):
        return {"sheets": [{"properties": {"sheetId": 777},
                            "conditionalFormats": [json.loads(json.dumps(r)) for r in self.rules]}]}

    def batch(self, body):
        for req in body["requests"]:
            if "deleteDimension" in req:
                rg = req["deleteDimension"]["range"]
                assert rg["sheetId"] == 777 and rg["dimension"] == "COLUMNS"
                assert rg["endIndex"] == rg["startIndex"] + 1
                self.deleted.append(self.headers[rg["startIndex"]])
                del self.headers[rg["startIndex"]]
            elif "addConditionalFormatRule" in req:
                a = req["addConditionalFormatRule"]
                self.rules.insert(a.get("index", 0), a["rule"])
            elif "updateConditionalFormatRule" in req:
                u = req["updateConditionalFormatRule"]
                self.rules[u["index"]] = u["rule"]
            elif "deleteConditionalFormatRule" in req:
                del self.rules[req["deleteConditionalFormatRule"]["index"]]
        return {}

    def ours(self):
        return [r for r in self.rules
                if r["booleanRule"]["condition"].get("values") == [{"userEnteredValue": PREFIX}]]


def _rule(col, value=PREFIX, cond="TEXT_STARTS_WITH"):
    return {"ranges": [{"sheetId": 777, "startRowIndex": 1, "startColumnIndex": col, "endColumnIndex": col + 1}],
            "booleanRule": {"condition": {"type": cond, "values": [{"userEnteredValue": value}]},
                            "format": {"textFormat": {"foregroundColor": dict(GREEN)}}}}


OLD_HEADERS = FORMULA_HEADERS + [OLD_VISIBLE, OLD_RAW]  # W = 대체 노출 · X = raw_대체노출


class TestRemoveOldColumns:
    def test_옛_두_칸만_없애고_다른_열은_그대로(self):
        client, ws = _client(OLD_HEADERS)
        sheet = _Sheet(client, ws, OLD_HEADERS)
        out = client.ensure_substitute_k(TAB)
        assert out["columns_removed"] == 2
        assert sorted(sheet.deleted) == sorted([OLD_VISIBLE, OLD_RAW])
        assert sheet.headers == FORMULA_HEADERS

    def test_지우기_직전_다시_읽은_머리글이_다르면_안_지움(self):
        # 처음 읽을 땐 W = '대체 노출' 이었는데 그 사이 사장님이 열을 끼워 W 가 다른 칸이 됨
        moved = FORMULA_HEADERS + ["사장님 메모", OLD_VISIBLE, OLD_RAW]
        client, ws = _client(OLD_HEADERS)
        sheet = _Sheet(client, ws, OLD_HEADERS, headers_on_reread=moved)
        client.ensure_substitute_k(TAB)
        assert "사장님 메모" not in sheet.deleted
        assert all(h in (OLD_VISIBLE, OLD_RAW) for h in sheet.deleted)

    def test_이름이_비슷한_열은_안_지움(self):
        heads = FORMULA_HEADERS + ["대체 노출 메모", "raw_대체노출2"]
        client, ws = _client(heads)
        sheet = _Sheet(client, ws, heads)
        out = client.ensure_substitute_k(TAB)
        assert out["columns_removed"] == 0 and sheet.deleted == [] and sheet.headers == heads

    def test_옛_칸의_우리_초록_규칙도_같이_지우고_다른_규칙은_그대로(self):
        other = _rule(22, value="인기글", cond="TEXT_CONTAINS")  # 옛 칸에 걸린 남의 규칙
        client, ws = _client(OLD_HEADERS)
        sheet = _Sheet(client, ws, OLD_HEADERS, rules=[_rule(22), other])
        client.ensure_substitute_k(TAB)
        ours = sheet.ours()
        assert len(ours) == 1 and ours[0]["ranges"][0]["startColumnIndex"] == 10  # K 칸 규칙만 남음
        assert any(r["booleanRule"]["condition"]["type"] == "TEXT_CONTAINS" for r in sheet.rules)

    def test_칸_없애기_실패해도_회차는_계속(self):
        client, ws = _client(OLD_HEADERS)
        sheet = _Sheet(client, ws, OLD_HEADERS)

        def boom(body):
            if any("deleteDimension" in r for r in body["requests"]):
                raise RuntimeError("500")
            return sheet.batch(body)
        client.spreadsheet.batch_update.side_effect = boom
        out = client.ensure_substitute_k(TAB)
        assert out["columns_removed"] == 0
        assert len(sheet.ours()) == 1  # 초록 규칙은 그대로 진행

    def test_옛_칸이_없으면_지우기_요청도_없음(self):
        client, ws = _client(FORMULA_HEADERS)
        sheet = _Sheet(client, ws, FORMULA_HEADERS)
        out = client.ensure_substitute_k(TAB)
        assert out["columns_removed"] == 0 and sheet.deleted == []


class TestKRank1Format:
    def test_K칸에_초록_규칙_하나(self):
        client, ws = _client(FORMULA_HEADERS)
        sheet = _Sheet(client, ws, FORMULA_HEADERS)
        out = client.ensure_substitute_k(TAB)
        assert out["formats_added"] == 1
        (rule,) = sheet.ours()
        assert rule["ranges"] == [{"sheetId": 777, "startRowIndex": 1, "startColumnIndex": 10, "endColumnIndex": 11}]
        color = rule["booleanRule"]["format"]["textFormat"]["foregroundColor"]
        assert "#%02X%02X%02X" % tuple(round(color[c] * 255) for c in ("red", "green", "blue")) == "#188038"

    def test_두번_불러도_새_클라이언트로_불러도_1개(self):
        client, ws = _client(FORMULA_HEADERS)
        sheet = _Sheet(client, ws, FORMULA_HEADERS)
        client.ensure_substitute_k(TAB)
        client.ensure_substitute_k(TAB)
        client2, ws2 = _client(FORMULA_HEADERS)
        sheet2 = _Sheet(client2, ws2, FORMULA_HEADERS, rules=sheet.rules)
        out = client2.ensure_substitute_k(TAB)
        assert out["formats_added"] == 0 and len(sheet2.ours()) == 1

    def test_K칸의_다른_조건부_서식은_안_건드림(self):
        k_red = _rule(10, value="미노출", cond="TEXT_STARTS_WITH")
        client, ws = _client(FORMULA_HEADERS)
        sheet = _Sheet(client, ws, FORMULA_HEADERS, rules=[k_red])
        client.ensure_substitute_k(TAB)
        assert k_red in sheet.rules and len(sheet.rules) == 2

    def test_스위치_끄면_부르지_않음(self, monkeypatch):
        monkeypatch.setenv("SUBSTITUTE_SCAN", "0")
        client = MagicMock()
        out = sub.prepare_sheet_columns(client, {TAB: [{"_row": 2}]})
        assert out["enabled"] is False
        client.ensure_substitute_k.assert_not_called()

    def test_prepare_가_탭마다_모음(self):
        client = MagicMock()
        client.ensure_substitute_k.return_value = {"columns_removed": 2, "formats_added": 1}
        out = sub.prepare_sheet_columns(client, {TAB: [], "탭2": []})
        assert out["columns_removed"] == 4 and out["formats_added"] == 2 and out["tabs"] == 2
