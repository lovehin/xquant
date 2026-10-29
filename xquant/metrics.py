"""纯函数指标计算。不做任何 IO，便于单测。

口径：
- 格雷厄姆指数 GI = 1/PE(TTM)×100 − 债券收益率(%)，与 ERP 同值，库中统一存 erp
- 分位采用中位秩法（mid-rank），样本不足返回 None
"""
from __future__ import annotations

from typing import Sequence

from xquant.config import MIN_PERCENTILE_SAMPLES


def graham_index(pe: float | None) -> float | None:
    """格雷厄姆指数分子部分：股权收益率倒数 1/PE × 100（%）。"""
    if pe is None or pe <= 0:
        return None
    return 1.0 / pe * 100.0


def erp(pe: float | None, bond_yield_pct: float | None) -> float | None:
    """格雷厄姆指数 / 股权风险溢价 = 1/PE×100 − 债券收益率(%)。"""
    g = graham_index(pe)
    if g is None or bond_yield_pct is None:
        return None
    return g - bond_yield_pct


def dividend_spread(dividend_yield_pct: float | None, bond_yield_pct: float | None) -> float | None:
    """股息率差 = 股息率(%) − 债券收益率(%)。"""
    if dividend_yield_pct is None or bond_yield_pct is None:
        return None
    return dividend_yield_pct - bond_yield_pct


def percentile_rank(values: Sequence[float], value: float | None,
                    min_samples: int = MIN_PERCENTILE_SAMPLES) -> float | None:
    """value 在 values 中的分位（0-100），中位秩法。样本不足返回 None。"""
    if value is None:
        return None
    vals = [v for v in values if v is not None]
    if len(vals) < min_samples:
        return None
    below = sum(1 for v in vals if v < value)
    equal = sum(1 for v in vals if v == value)
    return (below + 0.5 * equal) / len(vals) * 100.0


def percentile_series(values: Sequence[float], window: int | None,
                      min_samples: int = MIN_PERCENTILE_SAMPLES) -> list[float | None]:
    """滚动窗口分位序列。window=None 表示全历史。

    与逐点调用 percentile_rank 的结果完全一致（同样的中位秩定义），
    但内部用 numpy 向量化，长历史（数千点 × 多个窗口）下快两个数量级。
    """
    import numpy as np

    arr = np.asarray([np.nan if v is None else float(v) for v in values], dtype=float)
    n = arr.size
    out: list[float | None] = [None] * n
    w = n if window is None else int(window)
    for i in range(n):
        v = arr[i]
        if np.isnan(v):
            continue
        lo = max(0, i - w + 1)
        seg = arr[lo:i + 1]
        valid = seg[~np.isnan(seg)]
        if valid.size < min_samples:
            continue
        below = int(np.count_nonzero(valid < v))
        equal = int(np.count_nonzero(valid == v))
        out[i] = (below + 0.5 * equal) / valid.size * 100.0
    return out


def temperature(pct: float | None) -> str:
    """ERP 分位 → 估值温度。

    ERP = 1/PE − 债券收益率，是 PE 的倒数类指标：分位越高，说明股票相对债券
    越便宜。因此分位高 → 便宜，分位低 → 贵（与 PE 分位的方向相反）。
    """
    if pct is None:
        return "未知"
    if pct <= 20:
        return "很贵"
    if pct <= 40:
        return "偏贵"
    if pct <= 60:
        return "中性"
    if pct <= 80:
        return "偏低"
    return "便宜"


def build_daily_series(obs: Sequence[tuple[str, float]], days: Sequence[str]) -> list[tuple[str, float]]:
    """把稀疏观测（前值填充）摊到交易日序列上。obs 必须按日期升序。"""
    if not obs:
        return []
    obs_dates = [d for d, _ in obs]
    out: list[tuple[str, float]] = []
    idx = 0
    current: float | None = None
    for day in days:
        while idx < len(obs) and obs_dates[idx] <= day:
            current = obs[idx][1]
            idx += 1
        if current is not None:
            out.append((day, current))
    return out


def merge_bond(pe_series: Sequence[tuple[str, float]],
               bond_series: Sequence[tuple[str, float]]) -> list[tuple[str, float, float]]:
    """PE 序列与债券收益率序列按日期内连接。"""
    bond_map = dict(bond_series)
    out = []
    for d, pe in pe_series:
        y = bond_map.get(d)
        if y is not None:
            out.append((d, pe, y))
    return out


def style_signal(spread_pct: float | None) -> str:
    """风格利差分位：正=小盘占优，负=大盘占优。"""
    if spread_pct is None:
        return "未知"
    if spread_pct >= 60:
        return "小盘占优"
    if spread_pct <= 40:
        return "大盘占优"
    return "均衡"
