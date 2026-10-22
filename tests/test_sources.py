import pytest

from xquant.sources import csindex


PERF_PAYLOAD = {
    "code": "200", "success": True,
    "data": [
        {"tradeDate": "20240102", "indexCode": "000300", "close": 3386.35, "peg": 11.2},
        {"tradeDate": "20240103", "indexCode": "000300", "close": 3378.30, "peg": None},
    ],
}


def test_parse_perf_maps_peg_to_pe_and_skips_null():
    rows = csindex.parse_perf(PERF_PAYLOAD)
    assert rows == [{"index_code": "000300", "date": "2024-01-02", "close": 3386.35, "pe": 11.2}]


def test_parse_perf_accepts_empty():
    assert csindex.parse_perf({"data": []}) == []


def test_parse_indicator_reads_xls_bytes(tmp_path):
    import pandas as pd
    df = pd.DataFrame({
        "日期Date": ["20261021", "20261020"],
        "指数代码Index Code": ["000300", "000300"],
        "市盈率1（总股本）P/E1": [13.93, 14.08],
        "市盈率2（计算用股本）P/E2": [15.47, 15.62],
        "股息率1（总股本）D/P1": [2.83, 2.80],
        "股息率2（计算用股本）D/P2": [2.64, 2.61],
    })
    path = tmp_path / "000300indicator.xls"
    df.to_excel(path, index=False)
    rows = csindex.parse_indicator(path.read_bytes(), "000300")
    assert rows[0]["date"] == "2026-10-21"
    assert rows[0]["pe_total_shares"] == 13.93
    assert rows[0]["pe_calc_shares"] == 15.47
    assert rows[0]["dividend_yield_total_shares"] == 2.83
    assert rows[0]["dividend_yield"] == 2.64
    assert rows[0]["source"] == "csindex"


def test_parse_indicator_handles_missing_columns(tmp_path):
    import pandas as pd
    df = pd.DataFrame({"日期Date": ["20261021"], "指数代码Index Code": ["000300"]})
    path = tmp_path / "x.xls"
    df.to_excel(path, index=False)
    rows = csindex.parse_indicator(path.read_bytes(), "000300")
    assert rows[0]["pe_total_shares"] is None
    assert rows[0]["dividend_yield"] is None
