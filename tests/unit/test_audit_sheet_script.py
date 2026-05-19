"""Tests for the read-only audit_sheet helper."""


def test_filter_data_missing_tab_returns_error_shape():
    from scripts.audit_sheet import _filter_data

    data = {"바디워시 카외": [{"_row": 2}]}

    filtered, error = _filter_data(data, "없는탭", None)

    assert filtered == {}
    assert error is not None
    assert error["code"] == "TAB_NOT_FOUND"


def test_filter_data_missing_row_returns_error_shape():
    from scripts.audit_sheet import _filter_data

    data = {"바디워시 카외": [{"_row": 2}]}

    filtered, error = _filter_data(data, "바디워시 카외", 999)

    assert filtered == {"바디워시 카외": []}
    assert error is not None
    assert error["code"] == "ROW_NOT_FOUND"
