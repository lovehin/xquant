import pytest

from xquant import config


def test_index_codes_are_unique_and_six_digits():
    codes = [i.code for i in config.INDEXES]
    assert len(codes) == len(set(codes))
    for c in codes:
        assert len(c) == 6 and c.isdigit(), c


def test_primary_indexes_present():
    required = {"000300", "000905", "000852", "000985", "000016", "000688", "399006", "000922"}
    assert required <= {i.code for i in config.INDEXES}


def test_default_benchmark_exists():
    assert config.DEFAULT_BOND_BENCHMARK in {b.key for b in config.BOND_BENCHMARKS}


def test_allocation_map_is_monotonic_and_covers_full_range():
    bands = config.ALLOCATION_MAP
    assert bands[0].max_pct == 0 or bands[0].max_pct <= 10
    assert bands[-1].max_pct >= 90
    for a, b in zip(bands, bands[1:]):
        assert a.max_pct < b.max_pct
        assert a.equity_max <= b.equity_min  # 分位越高建议仓位越高（ERP 分位高=便宜）


def test_allocation_advice_returns_none_out_of_range():
    assert config.allocation_advice(-1) is None
    assert config.allocation_advice(101) is None


def test_allocation_advice_maps_band():
    prev = 0
    for band in config.ALLOCATION_MAP:
        mid = (prev + band.max_pct) / 2
        assert config.allocation_advice(mid) == (band.equity_min, band.equity_max)
        prev = band.max_pct


def test_high_erp_percentile_means_more_equity():
    low = config.allocation_advice(5)
    high = config.allocation_advice(95)
    assert low is not None and high is not None
    assert high[0] > low[1]
