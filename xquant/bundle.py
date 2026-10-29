"""发布产物：把库里的序列导出成紧凑文本，供 Git 每日提交与网页读取。

- series.csv：长表 series_id,date,value，按 series_id、date 排序（追加友好，git delta 极小）
- snapshot.json：当前值、分位、配置建议、数据健康

SQLite 库只做本地抓取缓存，不进版本库。
"""
from __future__ import annotations

import csv
from pathlib import Path

from xquant import store
from xquant.config import BACKTEST_INDEX, BOND_BENCHMARKS, STYLE_INDEX

SERIES_HEADER = ["series_id", "date", "value"]

# series_id 前缀 → metric 名
PREFIX_MAP = {
    "erp": "erp",
    "dy": "dy_spread",
}


def _bond_id(curve: str, tenor: str) -> str:
    return f"bond:{tenor}:{curve}"


def _parse_bond_id(series_id: str) -> tuple[str, str] | None:
    if not series_id.startswith("bond:"):
        return None
    rest = series_id[len("bond:"):]
    tenor, _, curve = rest.partition(":")
    if not curve:
        return None
    return curve, tenor


def write_bundle(conn, path: str | Path) -> Path:
    """导出 series.csv。

    只导出网页与回测真正需要的序列，控制文件体积：
      erp:*        各指数格雷厄姆指数（主序列）
      dy:*         股息率差（指数 + 市场级）
      style:spread 大小盘风格利差（沪深300 − 中证1000）
      bond:*       债券基准收益率（仅 config.BOND_BENCHMARKS 里的组合）
      price:*      回测用行情（仅 config.BACKTEST_INDEX）
    PE 历史与分位序列不入包：当前 PE 在 snapshot.json，分位由服务端按需计算。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[str, str, float]] = []

    for metric, prefix in (("erp", "erp"), ("dy_spread", "dy")):
        for r in conn.execute(
            "SELECT index_code, date, value FROM metric_series WHERE metric=? AND value IS NOT NULL"
            " ORDER BY index_code, date", (metric,)):
            rows.append((f"{prefix}:{r['index_code']}", r["date"], float(r["value"])))

    for r in conn.execute(
            "SELECT date, value FROM metric_series WHERE index_code=?"
            " AND metric='style_spread' AND value IS NOT NULL ORDER BY date", (STYLE_INDEX,)):
        rows.append(("style:spread", r["date"], float(r["value"])))

    wanted = {(b.curve, b.tenor) for b in BOND_BENCHMARKS}
    for r in conn.execute(
            "SELECT curve, date, tenor, yield FROM bond_yield WHERE yield IS NOT NULL"
            " ORDER BY curve, tenor, date"):
        if (r["curve"], r["tenor"]) not in wanted:
            continue
        rows.append((_bond_id(r["curve"], r["tenor"]), r["date"], float(r["yield"])))

    # 行情可能因 bundle 导入存在多来源重复行，导出时按日期去重（csindex 优先）
    seen_dates: set[str] = set()
    for r in conn.execute(
            "SELECT index_code, date, close, source FROM index_price WHERE close IS NOT NULL"
            " AND index_code=? ORDER BY index_code, date,"
            " CASE source WHEN 'csindex' THEN 0 ELSE 1 END", (BACKTEST_INDEX,)):
        if r["date"] in seen_dates:
            continue
        seen_dates.add(r["date"])
        rows.append((f"price:{r['index_code']}", r["date"], float(r["close"])))

    rows.sort(key=lambda x: (x[0], x[1]))
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(SERIES_HEADER)
        for series_id, date, value in rows:
            writer.writerow([series_id, date, f"{value:.6f}".rstrip("0").rstrip(".") or "0"])
    tmp.replace(path)  # 原子替换，避免读到半截文件
    return path


def read_bundle(path: str | Path) -> dict[str, list[tuple[str, float]]]:
    """读回 series.csv → {series_id: [(date, value), ...]}"""
    out: dict[str, list[tuple[str, float]]] = {}
    path = Path(path)
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) < 3:
                continue
            series_id, date, value = row[0], row[1], row[2]
            try:
                out.setdefault(series_id, []).append((date, float(value)))
            except ValueError:
                continue
    return out


def import_bundle(conn, path: str | Path) -> int:
    """把 series.csv 导入数据库（幂等），返回导入行数。"""
    data = read_bundle(path)
    if not data:
        return 0
    metrics_rows: list[dict] = []
    bond_rows: list[dict] = []
    price_rows: list[dict] = []

    for series_id, points in data.items():
        if series_id.startswith("style:"):
            metric = "style_spread" if series_id.endswith("spread") else "style_pct"
            for date, value in points:
                metrics_rows.append({"index_code": STYLE_INDEX, "date": date,
                                     "metric": metric, "value": value,
                                     "freq": "daily", "source": "bundle"})
            continue
        bond = _parse_bond_id(series_id)
        if bond:
            curve, tenor = bond
            for date, value in points:
                bond_rows.append({"curve": curve, "date": date, "tenor": tenor, "yield": value})
            continue
        prefix, _, code = series_id.partition(":")
        if prefix == "price":
            for date, value in points:
                price_rows.append({"index_code": code, "date": date, "close": value,
                                   "source": "bundle"})
            continue
        metric = PREFIX_MAP.get(prefix)
        if not metric:
            continue
        for date, value in points:
            metrics_rows.append({"index_code": code, "date": date, "metric": metric,
                                 "value": value, "freq": "daily", "source": "bundle"})

    if metrics_rows:
        store.upsert_metric(conn, metrics_rows)
    if bond_rows:
        store.upsert_bond_yield(conn, bond_rows)
    if price_rows:
        store.upsert_price(conn, price_rows)
    return len(metrics_rows) + len(bond_rows) + len(price_rows)
