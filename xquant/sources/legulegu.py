"""乐咕乐股数据源（通过 akshare）。

- stock_ebs_lg：沪深300 股债利差日频（1/PE(TTM) − 10Y国债），2006 起
- stock_index_pe_lg：宽基指数 PE 月频长史，2005 起
- stock_a_gxl_lg：市场（上证A股/深证A股/创业板/科创板）股息率日频，2005 起
"""
from __future__ import annotations

MARKET_GXL = {
    "MKT_SH": "上证A股",
    "MKT_SZ": "深证A股",
    "MKT_GEM": "创业板",
    "MKT_STAR": "科创板",
}
MARKET_GXL_INV = {v: k for k, v in MARKET_GXL.items()}


def _d(value) -> str:
    return value.strftime("%Y-%m-%d") if hasattr(value, "strftime") else str(value)[:10]


def parse_ebs(df) -> list[tuple[str, float]]:
    rows = []
    for _, r in df.iterrows():
        v = r["股债利差"]
        if v is None or v != v:
            continue
        rows.append((_d(r["日期"]), float(v) * 100))
    rows.sort(key=lambda x: x[0])
    return rows


def parse_index_pe(df, index_code: str) -> list[tuple[str, float]]:
    rows = []
    col = "滚动市盈率" if "滚动市盈率" in df.columns else "静态市盈率"
    for _, r in df.iterrows():
        v = r[col]
        if v is None or v != v or float(v) <= 0:
            continue
        rows.append((_d(r["日期"]), float(v)))
    rows.sort(key=lambda x: x[0])
    return rows


def parse_market_gxl(df, code: str) -> list[dict]:
    rows = []
    for _, r in df.iterrows():
        v = r["股息率"]
        if v is None or v != v:
            continue
        rows.append({"index_code": code, "date": _d(r["日期"]),
                     "source": "legulegu_gxl", "dividend_yield": float(v)})
    rows.sort(key=lambda x: x["date"])
    return rows


def fetch_ebs() -> list[tuple[str, float]]:
    import akshare as ak
    return parse_ebs(ak.stock_ebs_lg())


def fetch_index_pe(symbol: str) -> list[tuple[str, float]]:
    import akshare as ak
    return parse_index_pe(ak.stock_index_pe_lg(symbol=symbol), "")


def fetch_market_gxl(symbol: str) -> list[dict]:
    import akshare as ak
    df = ak.stock_a_gxl_lg(symbol=symbol)
    return parse_market_gxl(df, MARKET_GXL_INV[symbol])
