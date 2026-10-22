"""中债收益率曲线数据源（通过 akshare bond_china_yield）。"""
from __future__ import annotations

from datetime import date

TENORS = ["3月", "6月", "1年", "3年", "5年", "7年", "10年", "30年"]


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


def fetch_bond_yields(start_date: str, end_date: str | None = None) -> list[dict]:
    """start_date / end_date 形如 20060101。"""
    import akshare as ak
    end = end_date or date.today().strftime("%Y%m%d")
    df = ak.bond_china_yield(start_date=start_date, end_date=end)
    return parse_yield_curve(df)
