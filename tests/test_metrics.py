import pytest

from xquant import metrics


def test_graham_index_and_erp():
    assert metrics.graham_index(10) == pytest.approx(10.0)
    assert metrics.erp(10, 2.0) == pytest.approx(8.0)


def test_erp_with_negative_pe_is_none():
    assert metrics.erp(0, 2.0) is None
    assert metrics.erp(-5, 2.0) is None


def test_dividend_spread():
    assert metrics.dividend_spread(4.5, 1.7) == pytest.approx(2.8)


def test_percentile_rank_bounds():
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert metrics.percentile_rank(vals, 5.0, min_samples=5) == pytest.approx(90.0)
    assert metrics.percentile_rank(vals, 1.0, min_samples=5) == pytest.approx(10.0)
    assert metrics.percentile_rank(vals, 3.0, min_samples=5) == pytest.approx(50.0)


def test_percentile_rank_insufficient_sample():
    assert metrics.percentile_rank([1.0, 2.0], 1.5) is None


def test_percentile_series_window_limits():
    values = list(range(100))
    out = metrics.percentile_series(values, window=10, min_samples=2)
    assert len(out) == 100
    assert out[0] is None  # 窗口内只有 1 个样本，不足 min_samples
    assert out[1] == pytest.approx(75.0)  # 窗口 [0,1] 中值 1 → (1+0.5)/2
    assert out[-1] == pytest.approx(95.0)  # 窗口 [90..99] 中值 99 → (9+0.5)/10


def test_percentile_series_by_year_uses_calendar_window():
    # 每年一个观测，共 11 年；3 年窗口应只看最近 4 个年度点（2022-2025）
    dates = [f"{y}-01-15" for y in range(2015, 2026)]
    values = [float(i) for i in range(11)]
    out = metrics.percentile_series_by_year(dates, values, years=3, min_samples=2)
    assert out[-1] == pytest.approx((3 + 0.5) / 4 * 100)  # 7,8,9,10 中的最高值
    # 全历史：最后一个值处于最高位
    full = metrics.percentile_series_by_year(dates, values, years=None, min_samples=2)
    assert full[-1] == pytest.approx((10 + 0.5) / 11 * 100)
    # 样本不足窗口返回 None
    assert out[0] is None


def test_percentile_series_by_year_requires_matching_length():
    with pytest.raises(ValueError):
        metrics.percentile_series_by_year(["2026-01-02"], [1.0, 2.0], 3)


def test_percentile_series_matches_pointwise_reference():
    """向量化实现必须与逐点 percentile_rank 结果一致。"""
    values = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0] * 20
    for w in (5, 20, None):
        fast = metrics.percentile_series(values, w, min_samples=3)
        slow = []
        for i, v in enumerate(values):
            lo = 0 if w is None else max(0, i - w + 1)
            slow.append(metrics.percentile_rank(values[lo:i + 1], v, min_samples=3))
        assert fast == slow


def test_build_daily_series_forward_fills():
    obs = [("2026-01-02", 10.0), ("2026-01-06", 12.0)]
    days = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]
    assert metrics.build_daily_series(obs, days) == [
        ("2026-01-02", 10.0), ("2026-01-05", 10.0),
        ("2026-01-06", 12.0), ("2026-01-07", 12.0),
    ]


def test_build_daily_series_ignores_future_observations():
    obs = [("2026-01-02", 10.0), ("2026-01-06", 12.0)]
    days = ["2026-01-02", "2026-01-03"]
    assert metrics.build_daily_series(obs, days) == [("2026-01-02", 10.0), ("2026-01-03", 10.0)]


def test_merge_bond_inner_joins():
    pe = [("2026-01-02", 10.0), ("2026-01-05", 11.0)]
    bond = [("2026-01-02", 2.0)]
    assert metrics.merge_bond(pe, bond) == [("2026-01-02", 10.0, 2.0)]


def test_temperature_bands():
    # ERP 是 PE 的倒数类指标：分位越高越便宜
    assert metrics.temperature(5) == "很贵"
    assert metrics.temperature(30) == "偏贵"
    assert metrics.temperature(50) == "中性"
    assert metrics.temperature(75) == "偏低"
    assert metrics.temperature(95) == "便宜"
    assert metrics.temperature(None) == "未知"


def test_style_signal():
    # 利差 = ERP(沪深300) - ERP(中证1000)：分位高=大盘占优
    assert metrics.style_signal(80) == "大盘占优"
    assert metrics.style_signal(20) == "小盘占优"
    assert metrics.style_signal(None) == "未知"
