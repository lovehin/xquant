"""流水线：抓取 → 落库 → 计算指标 → 导出快照。

设计要点：
- 每个数据源独立 try/except，失败只记录不中断（降级沿用旧值）
- PE 主序列按源优先级合并：中证 peg(官方TTM) > 蛋卷周频 > 乐咕月频
- 指标全部由 metrics 纯函数计算，落 metric_series
"""
from __future__ import annotations

import bisect
import json
import statistics
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from xquant import bundle, metrics, store
from xquant.config import (BUNDLE_PATH, DEFAULT_BOND_BENCHMARK, INDEXES, LEGULEGU_CODE_TO_SYMBOL,
                            MARKET_DIVIDEND_SERIES, PERCENTILE_WINDOWS, SNAPSHOT_PATH,
                            STYLE_BIG_CODE, STYLE_INDEX, STYLE_SMALL_CODE,
                            allocation_advice, benchmark_by_key)
from xquant.sources import chinabond, csindex, danjuan, legulegu

CST = timezone(timedelta(hours=8))

# PE 源优先级（数字越小越优先）
# csindex_pe = 中证 index-perf 的 peg 字段（官方近四季滚动市盈率，主口径）
# csindex    = 中证 indicator.xls 估值快照（只带股息率与两种股本口径 PE）
PE_SOURCE_PRIORITY = {"csindex_pe": 0, "csindex": 1, "danjuan": 2, "legulegu": 3}

# 股息率源优先级（同一天多源时取优先级最高的）
# csindex = 中证「股息率2（计算用股本）」口径，作为主口径
DIVIDEND_SOURCE_PRIORITY = {"csindex": 0, "danjuan_snapshot": 1, "legulegu_gxl": 2}

# 中债收益率曲线回补起始日（中债 PBC 接口 2006 起有数据）
BOND_HISTORY_START = "20060101"


class Source:
    """数据源适配器接口。子类实现 fetch()。"""

    source = "base"

    def fetch(self, *args, **kwargs) -> dict:  # pragma: no cover - 接口声明
        raise NotImplementedError


class CsindexSource(Source):
    source = "csindex"

    def fetch(self, index_code: str, start_date: str | None = None) -> dict:
        data = csindex.fetch_index(index_code, start_date=start_date)
        # index-perf 的 peg（官方近四季滚动市盈率）单独落源，避免覆盖估值快照的股息率
        pe_rows = [_valuation_row(index_code, d, "csindex_pe", pe=pe) for d, pe in data["perf"]]
        data["valuation"] = list(data["valuation"]) + pe_rows
        return data


class DanjuanSource(Source):
    source = "danjuan"

    def fetch(self, index_code: str) -> dict:
        out = {"valuation": [], "perf": [], "prices": []}
        spec = next((i for i in INDEXES if i.code == index_code), None)
        if spec and spec.danjuan_code:
            for d, pe in danjuan.fetch_pe_history(spec.danjuan_code):
                out["valuation"].append(_valuation_row(index_code, d, "danjuan", pe=pe))
        return out


class LeguleguSource(Source):
    source = "legulegu"

    def fetch(self, index_code: str) -> dict:
        out = {"valuation": [], "perf": [], "prices": []}
        symbol = LEGULEGU_CODE_TO_SYMBOL.get(index_code)
        if symbol:
            for d, pe in legulegu.fetch_index_pe(symbol):
                out["valuation"].append(_valuation_row(index_code, d, "legulegu", pe=pe))
        return out


def _valuation_row(index_code: str, date: str, source: str, pe=None, dividend_yield=None) -> dict:
    return {
        "index_code": index_code, "date": date, "source": source,
        "pe": pe, "pe_total_shares": None, "pe_calc_shares": None, "pb": None,
        "dividend_yield": dividend_yield, "dividend_yield_total_shares": None,
    }


def default_sources() -> list[Source]:
    return [CsindexSource(), DanjuanSource(), LeguleguSource()]


SOURCES = default_sources()


def _source_series(conn, index_code: str, source: str) -> list[tuple[str, float]]:
    rows = conn.execute(
        "SELECT date, pe FROM index_valuation WHERE index_code=? AND source=? AND pe IS NOT NULL"
        " ORDER BY date", (index_code, source)).fetchall()
    return [(r["date"], float(r["pe"])) for r in rows]


def _lookup_ref(ref_obs: list[tuple[str, float]], day: str, tol_days: int = 10) -> float | None:
    """取参考源中不晚于 day、且在 tol_days 天内的最近一个观测。"""
    if not ref_obs:
        return None
    idx = bisect.bisect_right([d for d, _ in ref_obs], day) - 1
    if idx < 0:
        return None
    d, v = ref_obs[idx]
    if (date.fromisoformat(day) - date.fromisoformat(d)).days > tol_days:
        return None
    return v


def _drop_median_outliers(obs: list[tuple[str, float]], window: int = 5,
                          tol: float = 0.30) -> list[tuple[str, float]]:
    """用局部中位数剔除离群点。

    对每个点，取其前后 window 个观测（不含自身）的中位数作基准，
    偏离基准超过 tol 判为脏数据。中证接口在个别交易日会给出错值
    （如 2012-06-08、2023-05-04、2024-12-09），这里统一剔除。
    财报期那种「水平切换」不会被误伤：切换点相对局部中位数偏离有限。
    """
    if len(obs) < 3:
        return list(obs)
    vals = [v for _, v in obs]
    n = len(vals)
    keep: list[tuple[str, float]] = []
    for i in range(n):
        lo = max(0, i - window)
        hi = min(n, i + window + 1)
        neighbors = vals[lo:hi]
        neighbors = neighbors[:i - lo] + neighbors[i - lo + 1:]
        if not neighbors:
            keep.append(obs[i])
            continue
        med = statistics.median(neighbors)
        if med > 0 and abs(vals[i] - med) / med > tol:
            continue
        keep.append(obs[i])
    return keep


def _truncate_pre_step(obs: list[tuple[str, float]], ref_obs: list[tuple[str, float]],
                       step: float = 0.35, confirm: int = 20) -> list[tuple[str, float]]:
    """截断「永久性水平断点」之前的数据。

    中证接口在指数正式发布前的 PE 字段无意义（例：2012 年中证1000 的 PE 显示 9.36，
    2014-09-25 断点后才变成真实水平 48）。识别方式：出现 >35% 的跳变且之后长期维持
    新水平；若断点之前没有任何其他源的参考数据，则前面的数据不可信，整段丢弃。
    """
    for i in range(1, len(obs)):
        d0, v0 = obs[i - 1]
        d, v = obs[i]
        if v0 <= 0 or abs(v / v0 - 1) <= step:
            continue
        tail = obs[i:i + confirm]
        if len(tail) < confirm:
            break
        vals = [x[1] for x in tail]
        if max(vals) - min(vals) > 0.15 * max(vals):
            continue
        if _lookup_ref(ref_obs, d0, 10) is None:
            return obs[i:]
        break
    return obs


def build_master_pe(conn, index_code: str) -> list[tuple[str, float]]:
    """合并各源 PE 观测为单一升序序列。

    主口径为中证官方近四季滚动市盈率，但该接口在指数发布前与个别交易日有脏值，
    因此先做两道清洗：局部中位数离群点剔除 → 永久断点截断。
    注意：各家的 PE 计算方法本就不同（中证与蛋卷可差 40%），故不做跨源数值比对，
    只用其他源判断「断点之前是否本来就有可靠数据」。
    同一天取优先级最高的源。
    """
    cs = _source_series(conn, index_code, "csindex_pe")
    dj = _source_series(conn, index_code, "danjuan")
    lg = _source_series(conn, index_code, "legulegu")
    ref = sorted(dj + lg)

    cs = _drop_median_outliers(cs)
    cs = _truncate_pre_step(cs, ref)

    merged: dict[str, tuple[int, float]] = {}
    for series, source in ((cs, "csindex_pe"), (dj, "danjuan"), (lg, "legulegu")):
        for d, v in series:
            pri = PE_SOURCE_PRIORITY.get(source, 9)
            cur = merged.get(d)
            if cur is None or pri < cur[0]:
                merged[d] = (pri, v)
    return sorted((d, v[1]) for d, v in merged.items())


def _dividend_series(conn, index_code: str) -> list[tuple[str, float]]:
    """股息率序列。同一天多个源时按优先级取一个，避免口径混用跳变。"""
    rows = conn.execute(
        "SELECT date, dividend_yield, source FROM index_valuation"
        " WHERE index_code=? AND dividend_yield IS NOT NULL",
        (index_code,)).fetchall()
    best: dict[str, tuple[int, float]] = {}
    for r in rows:
        pri = DIVIDEND_SOURCE_PRIORITY.get(r["source"], 9)
        cur = best.get(r["date"])
        if cur is None or pri < cur[0]:
            best[r["date"]] = (pri, float(r["dividend_yield"]))
    return sorted((d, v[1]) for d, v in best.items())


def compute_metrics(conn, bond_key: str = DEFAULT_BOND_BENCHMARK) -> dict:
    """计算并写入全部指标序列。"""
    bench = benchmark_by_key(bond_key)
    if bench is None:
        raise ValueError(f"unknown bond benchmark: {bond_key}")
    bond = store.fetch_bond_yield(conn, bench.curve, bench.tenor)
    bond_map = dict(bond)
    days = store.trading_days(conn)
    if not days:
        return {"indices": 0, "bond": bench.key, "days": 0}

    for spec in INDEXES:
        pe_obs = build_master_pe(conn, spec.code)
        if not pe_obs:
            continue
        pe_daily = metrics.build_daily_series(pe_obs, days)
        erp_rows = []
        pe_rows = []
        for d, pe in pe_daily:
            y = bond_map.get(d)
            if y is None:
                continue
            value = metrics.erp(pe, y)
            if value is None:
                continue
            pe_rows.append({"index_code": spec.code, "date": d, "metric": "pe",
                            "value": pe, "freq": "daily", "source": "master"})
            erp_rows.append({"index_code": spec.code, "date": d, "metric": "erp",
                             "value": value, "freq": "daily", "source": "master"})
        # 整段重写，避免清洗后残留旧行
        store.delete_metric(conn, spec.code, "pe")
        store.delete_metric(conn, spec.code, "erp")
        for wname in PERCENTILE_WINDOWS:
            store.delete_metric(conn, spec.code, f"erp_pct_{wname}")
        store.delete_metric(conn, spec.code, "dy_spread")
        store.upsert_metric(conn, pe_rows)
        store.upsert_metric(conn, erp_rows)

        erp_values = [r["value"] for r in erp_rows]
        erp_dates = [r["date"] for r in erp_rows]
        for wname, years in PERCENTILE_WINDOWS.items():
            pcts = metrics.percentile_series_by_year(erp_dates, erp_values, years)
            store.upsert_metric(conn, [
                {"index_code": spec.code, "date": r["date"], "metric": f"erp_pct_{wname}",
                 "value": p, "freq": "daily", "source": "master"}
                for r, p in zip(erp_rows, pcts) if p is not None
            ])

        store.upsert_metric(conn, _dividend_spread_rows(conn, spec.code, bond_map))

    # 市场级股息率长历史（上证/深证/创业板/科创板，2005 起）
    for code in MARKET_DIVIDEND_SERIES:
        store.delete_metric(conn, code, "dy_spread")
        store.upsert_metric(conn, _dividend_spread_rows(conn, code, bond_map))

    # 风格利差：沪深300（大盘） - 中证1000（小盘）
    big = dict(store.fetch_metric(conn, STYLE_BIG_CODE, "erp"))
    small = dict(store.fetch_metric(conn, STYLE_SMALL_CODE, "erp"))
    style_rows = []
    for d in sorted(set(big) & set(small)):
        style_rows.append({"index_code": STYLE_INDEX, "date": d, "metric": "style_spread",
                           "value": big[d] - small[d], "freq": "daily", "source": "master"})
    # 清理旧口径（中证500 - 中证1000）的残留
    for legacy in ("STYLE_500_1000",):
        store.delete_metric(conn, legacy, "style_spread")
        store.delete_metric(conn, legacy, "style_pct")
    store.delete_metric(conn, STYLE_INDEX, "style_spread")
    store.delete_metric(conn, STYLE_INDEX, "style_pct")
    store.upsert_metric(conn, style_rows)
    if style_rows:
        vals = [r["value"] for r in style_rows]
        dates = [r["date"] for r in style_rows]
        pcts = metrics.percentile_series_by_year(dates, vals, PERCENTILE_WINDOWS["10y"])
        store.upsert_metric(conn, [
            {"index_code": STYLE_INDEX, "date": r["date"], "metric": "style_pct",
             "value": p, "freq": "daily", "source": "master"}
            for r, p in zip(style_rows, pcts) if p is not None
        ])
    return {"indices": len(INDEXES), "bond": bench.key, "days": len(days)}


def ensure_percentiles(conn) -> int:
    """当库里只有 ERP 序列（例如从 series.csv 导入）时，补算分位序列。"""
    filled = 0
    for spec in INDEXES:
        erp = store.fetch_metric(conn, spec.code, "erp")
        if not erp or store.fetch_metric(conn, spec.code, "erp_pct_10y"):
            continue
        values = [v for _, v in erp]
        dates = [d for d, _ in erp]
        for wname, years in PERCENTILE_WINDOWS.items():
            pcts = metrics.percentile_series_by_year(dates, values, years)
            store.delete_metric(conn, spec.code, f"erp_pct_{wname}")
            store.upsert_metric(conn, [
                {"index_code": spec.code, "date": d, "metric": f"erp_pct_{wname}",
                 "value": p, "freq": "daily", "source": "master"}
                for (d, _), p in zip(erp, pcts) if p is not None
            ])
        filled += 1

    spread = store.fetch_metric(conn, STYLE_INDEX, "style_spread")
    if spread and not store.fetch_metric(conn, STYLE_INDEX, "style_pct"):
        values = [v for _, v in spread]
        dates = [d for d, _ in spread]
        pcts = metrics.percentile_series_by_year(dates, values, PERCENTILE_WINDOWS["10y"])
        store.delete_metric(conn, STYLE_INDEX, "style_pct")
        store.upsert_metric(conn, [
            {"index_code": STYLE_INDEX, "date": d, "metric": "style_pct",
             "value": p, "freq": "daily", "source": "master"}
            for (d, _), p in zip(spread, pcts) if p is not None
        ])
    return filled


def _dividend_spread_rows(conn, index_code: str, bond_map: dict) -> list[dict]:
    rows = []
    for d, dy in _dividend_series(conn, index_code):
        y = bond_map.get(d)
        if y is None:
            continue
        value = metrics.dividend_spread(dy, y)
        if value is None:
            continue
        rows.append({"index_code": index_code, "date": d, "metric": "dy_spread",
                     "value": value, "freq": "daily", "source": "master"})
    return rows


def _stats(navs: list[float], years: float | None = None) -> dict:
    """净值序列 → 年化收益/波动/最大回撤。

    years 为实际日历跨度；不传时沿用 252 个交易日/年的近似。
    """
    if len(navs) < 2:
        return {"cagr": None, "vol": None, "max_drawdown": None, "total_return": None}
    rets = [navs[i] / navs[i - 1] - 1 for i in range(1, len(navs))]
    if years is None:
        years = len(rets) / 252
    total = navs[-1] / navs[0] - 1
    cagr = (navs[-1] / navs[0]) ** (1 / years) - 1 if years > 0 else None
    vol = statistics.pstdev(rets) * (252 ** 0.5) if len(rets) > 1 else None
    peak, mdd = navs[0], 0.0
    for v in navs:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return {"cagr": cagr, "vol": vol, "max_drawdown": mdd, "total_return": total}


def run_backtest(conn, index_code: str = "000300",
                 bond_key: str = DEFAULT_BOND_BENCHMARK) -> dict:
    """按 ERP 分位映射规则在 股票 与 债券 之间切换的规则回测。

    月末调仓：每月最后一个交易日按当月 ERP 的全历史分位决定次月权益权重（取仓位区间中值）。
    口径：股票腿为价格指数（不含股息），债券腿按当日 10Y 收益率计票息（不含价格波动）。
    """
    bench = benchmark_by_key(bond_key)
    erp = store.fetch_metric(conn, index_code, "erp")
    prices = dict(store.fetch_prices(conn, index_code))
    bond = dict(store.fetch_bond_yield(conn, bench.curve, bench.tenor))
    if not erp or not prices:
        return {"available": False, "reason": "缺少 ERP 或行情数据"}
    values = [v for _, v in erp]
    pcts = metrics.percentile_series(values, None)
    erp_pct = {d: p for (d, _), p in zip(erp, pcts) if p is not None}
    dates = sorted(set(erp_pct) & set(prices))
    if len(dates) < 250:
        return {"available": False, "reason": f"样本不足（{len(dates)} 天）"}
    month_last: dict[str, str] = {}
    for d in dates:
        month_last[d[:7]] = d
    years = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days / 365.25

    strategy_nav, equity_nav, bond_nav = [1.0], [1.0], [1.0]
    weight, switches, prev_weight = 0.5, 0, None
    for i in range(1, len(dates)):
        d, prev = dates[i], dates[i - 1]
        r_equity = prices[d] / prices[prev] - 1
        y = bond.get(d)
        r_bond = (y / 100) / 252 if y is not None else 0.0
        strategy_nav.append(strategy_nav[-1] * (1 + weight * r_equity + (1 - weight) * r_bond))
        equity_nav.append(equity_nav[-1] * (1 + r_equity))
        bond_nav.append(bond_nav[-1] * (1 + r_bond))
        if month_last.get(d[:7]) == d or i == len(dates) - 1:
            adv = allocation_advice(erp_pct.get(d))
            w = ((adv[0] + adv[1]) / 2) / 100 if adv else 0.5
            if prev_weight is not None and abs(w - prev_weight) > 0.01:
                switches += 1
            prev_weight = w
            weight = w
    return {
        "available": True,
        "index": index_code,
        "benchmark": bench.label,
        "period": [dates[0], dates[-1]],
        "rebalances": len(month_last),
        "switches": switches,
        "basis": "price_equity_coupon_bond",
        "strategy": _stats(strategy_nav, years),
        "equity_only": _stats(equity_nav, years),
        "bond_only": _stats(bond_nav, years),
    }


def _fetch_all(conn, progress=None) -> list[dict]:
    def note(msg: str) -> None:
        if progress:
            progress(msg)

    quality = []
    try:
        # 增量抓取：只补最近缺失的一段（首次从 BOND_HISTORY_START 开始）
        stored = store.fetch_bond_yield(conn, "中债国债收益率曲线", "10年")
        if stored:
            last = datetime.strptime(stored[-1][0], "%Y-%m-%d").date()
            start = (last - timedelta(days=10)).strftime("%Y%m%d")
        else:
            start = BOND_HISTORY_START
        note(f"chinabond: 从 {start} 开始抓取")
        t0 = time.perf_counter()
        rows = chinabond.fetch_bond_yields(start)
        store.upsert_bond_yield(conn, rows)
        ms = int((time.perf_counter() - t0) * 1000)
        quality.append({"source": "chinabond", "status": "ok", "rows": len(rows),
                        "message": f"from {start}", "duration_ms": ms})
        note(f"chinabond: {len(rows)} 行, {ms} ms")
    except Exception as exc:
        quality.append({"source": "chinabond", "status": "fail", "rows": 0, "message": str(exc),
                        "duration_ms": 0})

    for source in SOURCES:
        for spec in INDEXES:
            if isinstance(source, CsindexSource) and not spec.has_csindex:
                continue  # 深证系指数中证没有数据，跳过以免超时
            t0 = time.perf_counter()
            try:
                data = source.fetch(spec.code)
            except Exception as exc:
                quality.append({"source": source.source, "status": "fail", "rows": 0,
                                "message": f"{spec.code}: {exc}", "duration_ms": 0})
                note(f"{source.source}/{spec.code}: 失败 {exc}")
                continue
            ms = int((time.perf_counter() - t0) * 1000)
            valuation = data.get("valuation") or []
            prices = data.get("prices") or []
            if valuation:
                store.upsert_valuation(conn, valuation)
            if prices:
                store.upsert_price(conn, prices)
            quality.append({"source": source.source, "status": "ok",
                            "rows": len(valuation) + len(prices),
                            "message": spec.code, "duration_ms": ms})
            note(f"{source.source}/{spec.code}: {len(valuation)}+{len(prices)} 行, {ms} ms")
    try:
        t0 = time.perf_counter()
        snap = danjuan.fetch_snapshot()
        # 快照日期对齐到库中最后一个交易日，才能和债券收益率对上
        days = store.trading_days(conn)
        if days:
            last_day = days[-1]
            for row in snap:
                row["date"] = last_day
        store.upsert_valuation(conn, snap)
        ms = int((time.perf_counter() - t0) * 1000)
        quality.append({"source": "danjuan_snapshot", "status": "ok", "rows": len(snap),
                        "message": "", "duration_ms": ms})
        note(f"danjuan_snapshot: {len(snap)} 行, {ms} ms")
    except Exception as exc:
        quality.append({"source": "danjuan_snapshot", "status": "fail", "rows": 0,
                        "message": str(exc), "duration_ms": 0})
    for code, symbol in legulegu.MARKET_GXL.items():
        try:
            t0 = time.perf_counter()
            rows = legulegu.fetch_market_gxl(symbol)
            store.upsert_valuation(conn, rows)
            ms = int((time.perf_counter() - t0) * 1000)
            quality.append({"source": f"legulegu_gxl:{code}", "status": "ok",
                            "rows": len(rows), "message": "", "duration_ms": ms})
            note(f"legulegu_gxl:{code}: {len(rows)} 行, {ms} ms")
        except Exception as exc:
            quality.append({"source": f"legulegu_gxl:{code}", "status": "fail",
                            "rows": 0, "message": str(exc), "duration_ms": 0})
    return quality


def snapshot_payload(conn, bond_key: str = DEFAULT_BOND_BENCHMARK) -> dict:
    bench = benchmark_by_key(bond_key)
    indexes = []
    for spec in INDEXES:
        erp_series = store.fetch_metric(conn, spec.code, "erp")
        pe_series = store.fetch_metric(conn, spec.code, "pe")
        dy_series = store.fetch_metric(conn, spec.code, "dy_spread")
        if not erp_series:
            indexes.append({"code": spec.code, "name": spec.name, "group": spec.group,
                            "erp": None, "pe": None, "date": None, "percentile": None,
                            "temperature": "未知", "history_start": None,
                            "allocation": None, "dividend_spread": None, "windows": {}})
            continue
        latest = erp_series[-1]
        windows = {}
        for wname in PERCENTILE_WINDOWS:
            rows = store.fetch_metric(conn, spec.code, f"erp_pct_{wname}")
            if not rows:
                continue
            p = rows[-1][1]
            adv_w = allocation_advice(p)
            windows[wname] = {
                "percentile": p,
                "temperature": metrics.temperature(p),
                "allocation": {"equity_min": adv_w[0], "equity_max": adv_w[1]} if adv_w else None,
            }
        primary = windows.get("10y") or next(iter(windows.values()), {})
        pct = primary.get("percentile")
        indexes.append({
            "code": spec.code, "name": spec.name, "group": spec.group,
            "erp": latest[1],
            "pe": pe_series[-1][1] if pe_series else None,
            "date": latest[0],
            "percentile": pct,
            "temperature": primary.get("temperature", "未知"),
            "history_start": erp_series[0][0],
            "dividend_spread": dy_series[-1][1] if dy_series else None,
            "allocation": primary.get("allocation"),
            "windows": windows,
        })

    market = []
    for code, name in MARKET_DIVIDEND_SERIES.items():
        rows = store.fetch_metric(conn, code, "dy_spread")
        if not rows:
            continue
        market.append({"code": code, "name": name, "latest": rows[-1][1],
                       "date": rows[-1][0], "history_start": rows[0][0]})

    style = store.fetch_metric(conn, STYLE_INDEX, "style_spread")
    style_pct = store.fetch_metric(conn, STYLE_INDEX, "style_pct")
    bond_series = store.fetch_bond_yield(conn, bench.curve, bench.tenor)
    return {
        "generated_at": datetime.now(CST).isoformat(timespec="seconds"),
        "bond": {"key": bench.key, "label": bench.label, "curve": bench.curve,
                 "tenor": bench.tenor, "latest": bond_series[-1] if bond_series else None},
        "indexes": indexes,
        "market": market,
        "style": {
            "latest": style[-1] if style else None,
            "percentile": style_pct[-1][1] if style_pct else None,
            "signal": metrics.style_signal(style_pct[-1][1] if style_pct else None),
        },
        "quality": store.latest_quality(conn),
    }


def export_snapshot(conn, path: str | Path | None = None,
                    bond_key: str = DEFAULT_BOND_BENCHMARK) -> Path:
    path = Path(path or SNAPSHOT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot_payload(conn, bond_key), ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def run(conn, bond_key: str = DEFAULT_BOND_BENCHMARK, with_network: bool = True,
        sources: list | None = None, snapshot_path: str | Path | None = None,
        bundle_path: str | Path | None = None, progress=None) -> dict:
    global SOURCES
    if sources is not None:
        SOURCES = sources
    quality = []
    if with_network:
        quality = _fetch_all(conn, progress=progress)
        for q in quality:
            store.record_quality(conn, q["source"], q["status"], q.get("rows", 0),
                                 q.get("message", ""), q.get("duration_ms", 0))
    if progress:
        progress("计算指标…")
    t0 = time.perf_counter()
    summary = compute_metrics(conn, bond_key=bond_key)
    summary["compute_ms"] = int((time.perf_counter() - t0) * 1000)
    if progress:
        progress(f"指标计算完成 {summary['compute_ms']} ms")
    export_snapshot(conn, snapshot_path, bond_key=bond_key)
    bundle_path = bundle_path or BUNDLE_PATH
    bundle.write_bundle(conn, bundle_path)
    if progress:
        progress(f"已导出 {bundle_path}")
    store.set_meta(conn, "last_run", datetime.now(CST).isoformat(timespec="seconds"))
    store.set_meta(conn, "last_run_ts", str(time.time()))
    store.set_meta(conn, "last_bond_benchmark", bond_key)
    return {"quality": quality, "summary": summary}
