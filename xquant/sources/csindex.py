"""中证指数官方数据源。

- index-perf：日频行情 + 近四季滚动市盈率(字段名 peg)，2005 年至今。
  已验证 peg 与 CEIC「近四季滚动:沪深300指数」同口径（2026-10-20 均为 12.91）。
- indicator.xls：近 20 日的市盈率/股息率，含「总股本」与「计算用股本」两种股本口径。
"""
from __future__ import annotations

import io
from datetime import date

from xquant.sources.base import http_get_bytes, http_get_json

PERF_URL = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
INDICATOR_URL = ("https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/"
                 "autofile/indicator/{code}indicator.xls")


def _norm_date(value: str) -> str:
    v = str(value).strip()
    if len(v) == 8 and v.isdigit():
        return f"{v[:4]}-{v[4:6]}-{v[6:]}"
    return v


def parse_perf(payload: dict) -> list[dict]:
    rows: list[dict] = []
    for item in payload.get("data") or []:
        pe = item.get("peg")
        if pe is None:
            continue
        rows.append({
            "index_code": item.get("indexCode"),
            "date": _norm_date(item.get("tradeDate")),
            "close": item.get("close"),
            "pe": float(pe),
        })
    return rows


def _pick(cols, keyword):
    for c in cols:
        if keyword in str(c):
            return c
    return None


def parse_indicator(content: bytes, index_code: str) -> list[dict]:
    import pandas as pd
    df = pd.read_excel(io.BytesIO(content))
    cols = list(df.columns)
    c_date = _pick(cols, "日期")
    c_pe1 = _pick(cols, "市盈率1")
    c_pe2 = _pick(cols, "市盈率2")
    c_dp1 = _pick(cols, "股息率1")
    c_dp2 = _pick(cols, "股息率2")
    rows: list[dict] = []
    for _, r in df.iterrows():
        raw_date = r[c_date] if c_date else None
        if raw_date is None or (isinstance(raw_date, float) and pd.isna(raw_date)):
            continue
        d = _norm_date(str(int(raw_date)) if not isinstance(raw_date, str) else raw_date)
        rows.append({
            "index_code": index_code,
            "date": d,
            "source": "csindex",
            "pe_total_shares": float(r[c_pe1]) if c_pe1 and pd.notna(r[c_pe1]) else None,
            "pe_calc_shares": float(r[c_pe2]) if c_pe2 and pd.notna(r[c_pe2]) else None,
            "dividend_yield_total_shares": float(r[c_dp1]) if c_dp1 and pd.notna(r[c_dp1]) else None,
            "dividend_yield": float(r[c_dp2]) if c_dp2 and pd.notna(r[c_dp2]) else None,
        })
    return rows


def fetch_perf(index_code: str, start: str = "20050101", end: str | None = None) -> list[dict]:
    end_date = end or date.today().strftime("%Y%m%d")
    payload = http_get_json(PERF_URL, params={
        "indexCode": index_code, "startDate": start, "endDate": end_date}, timeout=60)
    return parse_perf(payload)


def fetch_indicator(index_code: str, retries: int = 3) -> list[dict]:
    """抓取近 20 日估值快照。失败会重试（该 OSS 偶发超时）。"""
    import time
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            content = http_get_bytes(INDICATOR_URL.format(code=index_code), timeout=60)
            return parse_indicator(content, index_code)
        except Exception as exc:
            last_exc = exc
            time.sleep(1.0 + attempt)
    raise last_exc if last_exc else RuntimeError("fetch_indicator failed")


def fetch_index(index_code: str, start_date: str | None = None) -> dict:
    """一次抓取某指数的全部可用数据。

    返回 {"valuation": [...], "perf": [...], "prices": [...]}：
      valuation → index_valuation 行（source=csindex，含两种股本口径的 PE 与股息率）
      perf      → 日频 PE 观测 (date, pe)，来自 index-perf 的 peg 字段
      prices    → 日频收盘价 (date, close)
    """
    start = (start_date or "20050101").replace("-", "")
    payload = http_get_json(PERF_URL, params={
        "indexCode": index_code, "startDate": start,
        "endDate": date.today().strftime("%Y%m%d")}, timeout=90)
    perf_rows = parse_perf(payload)
    prices = [{"index_code": index_code, "date": r["date"], "close": r["close"],
               "source": "csindex"} for r in perf_rows]
    valuation: list[dict] = []
    try:
        valuation = fetch_indicator(index_code)
    except Exception:
        valuation = []
    return {
        "valuation": valuation,
        "perf": [(r["date"], r["pe"]) for r in perf_rows],
        "prices": prices,
    }
