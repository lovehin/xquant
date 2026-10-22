import pytest
from datetime import date, timedelta

from xquant import pipeline, store


def _row(code, date, pe, source):
    return {"index_code": code, "date": date, "source": source, "pe": pe,
            "pe_total_shares": None, "pe_calc_shares": None, "pb": None,
            "dividend_yield": None, "dividend_yield_total_shares": None}


def _conn():
    conn = store.connect(":memory:")
    store.init_db(conn)
    return conn


def test_outlier_against_reference_is_dropped():
    conn = _conn()
    store.upsert_valuation(conn, [
        _row("000300", "2024-01-02", 12.0, "csindex_pe"),
        _row("000300", "2024-01-03", 12.1, "csindex_pe"),
        _row("000300", "2024-01-04", 4.0, "csindex_pe"),   # 脏点
        _row("000300", "2024-01-05", 12.2, "csindex_pe"),
    ])
    rows = pipeline.build_master_pe(conn, "000300")
    assert ("2024-01-04", 4.0) not in rows
    assert ("2024-01-04", 12.1) not in rows  # 脏点当天整条被剔除（不做插值）
    assert ("2024-01-02", 12.0) in rows and ("2024-01-05", 12.2) in rows


def test_two_day_outlier_run_is_dropped():
    conn = _conn()
    rows = [_row("000300", f"2024-12-{d:02d}", 26.2 + d * 0.02, "csindex_pe") for d in range(2, 6)]
    rows.append(_row("000300", "2024-12-06", 41.7, "csindex_pe"))
    rows.append(_row("000300", "2024-12-09", 41.7, "csindex_pe"))
    rows += [_row("000300", f"2024-12-{d:02d}", 26.5 + d * 0.02, "csindex_pe")
             for d in range(10, 16)]
    store.upsert_valuation(conn, rows)
    out = pipeline.build_master_pe(conn, "000300")
    assert ("2024-12-06", 41.7) not in out
    assert ("2024-12-09", 41.7) not in out
    assert ("2024-12-05", 26.3) in out
    assert ("2024-12-10", 26.7) in out


def test_single_day_spike_is_dropped():
    """单日错值（中证接口偶发）：2.52 夹在 1.0x 之间。"""
    conn = _conn()
    rows = [_row("000905", f"2023-05-{d:02d}", 1.0 + d * 0.01, "csindex_pe") for d in range(1, 4)]
    rows.append(_row("000905", "2023-05-04", 2.52, "csindex_pe"))
    rows += [_row("000905", f"2023-05-{d:02d}", 1.2 + d * 0.01, "csindex_pe") for d in range(5, 12)]
    store.upsert_valuation(conn, rows)
    out = pipeline.build_master_pe(conn, "000905")
    assert ("2023-05-04", 2.52) not in out


def test_legitimate_level_change_is_kept():
    """长期维持的新水平（真实口径切换）不应被当成毛刺剔除。"""
    conn = _conn()
    rows = [_row("000300", f"2024-01-{d:02d}", 12.0 + d * 0.01, "csindex_pe") for d in range(2, 12)]
    rows += [_row("000300", f"2024-02-{d:02d}", 20.0 + d * 0.01, "csindex_pe") for d in range(1, 12)]
    store.upsert_valuation(conn, rows)
    out = pipeline.build_master_pe(conn, "000300")
    assert len(out) == 21  # 10 + 11，两段都保留


def test_different_source_methodologies_are_not_merged_by_value():
    """中证与蛋卷口径不同（可差 40%），不得因此互相剔除。"""
    conn = _conn()
    store.upsert_valuation(conn, [
        _row("000852", "2024-01-02", 27.0, "csindex_pe"),
        _row("000852", "2024-01-02", 38.6, "danjuan"),
    ])
    out = pipeline.build_master_pe(conn, "000852")
    assert out == [("2024-01-02", 27.0)]  # 主口径优先，但没有丢数据


def test_permanent_step_before_launch_is_truncated():
    """中证在指数发布前的 PE 无意义，应整段丢弃。"""
    conn = _conn()
    rows = [_row("000852", "2012-06-29", 9.3, "csindex_pe"),
        _row("000852", "2012-07-02", 9.4, "csindex_pe")]
    # 断点：2014-09-25 起 PE 跳到 47 并维持
    for i in range(40):
        day = (date(2014, 9, 25) + timedelta(days=i)).strftime("%Y-%m-%d")
        rows.append(_row("000852", day, 47.0 + i * 0.01, "csindex_pe"))
    store.upsert_valuation(conn, rows)
    out = pipeline.build_master_pe(conn, "000852")
    assert out[0][0] >= "2014-09-25"


def test_preferred_source_wins_on_same_day():
    conn = _conn()
    store.upsert_valuation(conn, [
        _row("000300", "2024-01-02", 12.77, "csindex_pe"),
        _row("000300", "2024-01-02", 12.85, "danjuan"),
        _row("000300", "2024-01-02", 13.00, "legulegu"),
    ])
    out = pipeline.build_master_pe(conn, "000300")
    assert out == [("2024-01-02", 12.77)]


def test_other_source_survives_when_main_source_dropped():
    conn = _conn()
    store.upsert_valuation(conn, [
        _row("000852", "2014-10-31", 48.0, "csindex_pe"),
        _row("000852", "2014-10-31", 47.0, "danjuan"),
    ])
    out = pipeline.build_master_pe(conn, "000852")
    assert out == [("2014-10-31", 48.0)]
