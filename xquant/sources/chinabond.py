"""中债收益率曲线数据源（通过 akshare bond_china_yield）。

注意：中债接口限制单次查询跨度小于一年，超出范围会返回空表，
因此这里按 330 天分段抓取再拼接。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

TENORS = ["3月", "6月", "1年", "3年", "5年", "7年", "10年", "30年"]

# 单次查询的最大天数（中债要求跨度小于一年，留出余量）
MAX_CHUNK_DAYS = 330


def parse_yield_curve(df) -> list[dict]:
    rows: list[dict] = []
    for _, r in df.iterrows():
        curve = str(r["曲线名称"]).strip()
        raw_date = r["日期"]
        d = raw_date.strftime("%Y-%m-%d") if hasattr(raw_date, "strftime") else str(raw_date)[:10]
        for tenor in TENORS:
            if tenor not in df.columns:
                continue
            val = r[tenor]
            if val is None or val != val:  # NaN 检查
                continue
            rows.append({"curve": curve, "date": d, "tenor": tenor, "yield": float(val)})
    return rows


def _chunks(start: date, end: date, chunk_days: int) -> list[tuple[date, date]]:
    out = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=chunk_days), end)
        out.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    return out


def fetch_bond_yields(start_date: str, end_date: str | None = None, workers: int = 4) -> list[dict]:
    """start_date / end_date 形如 20060101。

    中债接口单次查询跨度不能超过一年，这里按 MAX_CHUNK_DAYS 分块并发抓取。
    """
    import akshare as ak
    from concurrent.futures import ThreadPoolExecutor

    start = datetime.strptime(start_date, "%Y%m%d").date()
    end = datetime.strptime(end_date, "%Y%m%d").date() if end_date else date.today()
    if start > end:
        return []

    def job(chunk: tuple[date, date]) -> list[dict]:
        s, e = chunk
        df = ak.bond_china_yield(start_date=s.strftime("%Y%m%d"),
                                 end_date=e.strftime("%Y%m%d"))
        return parse_yield_curve(df)

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        for part in ex.map(job, _chunks(start, end, MAX_CHUNK_DAYS)):
            rows.extend(part)
    rows.sort(key=lambda r: (r["curve"], r["date"], r["tenor"]))
    return rows
