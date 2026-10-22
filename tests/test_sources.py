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


def test_parse_yield_curve_long_format():
    import pandas as pd
    from xquant.sources import chinabond
    df = pd.DataFrame({
        "曲线名称": ["中债国债收益率曲线", "中债国债收益率曲线"],
        "日期": [pd.Timestamp("2026-10-21"), pd.Timestamp("2026-10-20")],
        "3月": [1.4, 1.41], "10年": [1.68, 1.7], "30年": [1.95, 1.96],
    })
    rows = chinabond.parse_yield_curve(df)
    assert {"curve": "中债国债收益率曲线", "date": "2026-10-21", "tenor": "10年",
            "yield": 1.68} in rows
    assert len(rows) == 6  # 2 天 × 3 个期限


def test_parse_pe_history():
    from xquant.sources import danjuan
    payload = {"data": {"index_eva_pe_growths": [
        {"pe": 12.85, "ts": 1791465600000},
        {"pe": 13.10, "ts": 1792070400000},
    ]}}
    rows = danjuan.parse_pe_history(payload)
    assert len(rows) == 2
    assert rows[0][1] == 12.85
    assert rows[0][0].startswith("2026-10")


def test_parse_snapshot():
    from xquant.sources import danjuan
    payload = {"data": {"items": [
        {"index_code": "SH000300", "name": "沪深300", "pe": 12.85, "pb": 1.36,
         "pe_percentile": 0.52, "yeild": 0.0298},
    ]}}
    rows = danjuan.parse_snapshot(payload)
    assert rows[0]["index_code"] == "000300"
    assert rows[0]["pe"] == 12.85
    assert rows[0]["dividend_yield"] == pytest.approx(2.98, abs=0.01)


def test_parse_ebs_scales_to_percent():
    import pandas as pd
    from xquant.sources import legulegu
    df = pd.DataFrame({"日期": [pd.Timestamp("2026-10-21")], "沪深300指数": [4111.93],
                       "股债利差": [0.0657], "股债利差均线": [0.0617]})
    rows = legulegu.parse_ebs(df)
    assert rows == [("2026-10-21", pytest.approx(6.57))]


def test_parse_market_gxl():
    import pandas as pd
    from xquant.sources import legulegu
    df = pd.DataFrame({"日期": [pd.Timestamp("2026-10-21")], "股息率": [2.79]})
    rows = legulegu.parse_market_gxl(df, "MKT_SH")
    assert rows[0]["index_code"] == "MKT_SH"
    assert rows[0]["dividend_yield"] == 2.79


def test_parse_index_pe_uses_ttm_column():
    import pandas as pd
    from xquant.sources import legulegu
    df = pd.DataFrame({"日期": [pd.Timestamp("2026-09-30")], "静态市盈率": [13.56],
                       "滚动市盈率": [12.48]})
    rows = legulegu.parse_index_pe(df, "000300")
    assert rows == [("2026-09-30", 12.48)]


