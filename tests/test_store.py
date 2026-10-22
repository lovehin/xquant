import sqlite3

from xquant import store


def make_conn():
    conn = store.connect(":memory:")
    store.init_db(conn)
    return conn


def test_upsert_is_idempotent():
    conn = make_conn()
    rows = [{"index_code": "000300", "date": "2026-10-21", "source": "csindex",
             "pe": 12.77, "pe_total_shares": 13.93, "pe_calc_shares": 15.47,
             "pb": None, "dividend_yield": 2.83, "dividend_yield_total_shares": None}]
    store.upsert_valuation(conn, rows)
    store.upsert_valuation(conn, rows)
    got = conn.execute("SELECT COUNT(*) FROM index_valuation").fetchone()[0]
    assert got == 1


def test_upsert_updates_existing_row():
    conn = make_conn()
    base = {"index_code": "000300", "date": "2026-10-21", "source": "csindex",
            "pe": 12.77, "pe_total_shares": None, "pe_calc_shares": None,
            "pb": None, "dividend_yield": None, "dividend_yield_total_shares": None}
    store.upsert_valuation(conn, [base])
    store.upsert_valuation(conn, [{**base, "pe": 13.01}])
    rows = store.fetch_valuation(conn, "000300", "csindex")
    assert rows[0]["pe"] == 13.01


def test_fetch_metric_sorted_and_filtered():
    conn = make_conn()
    store.upsert_metric(conn, [
        {"index_code": "000300", "date": "2026-10-20", "metric": "erp", "value": 5.0,
         "freq": "daily", "source": "csindex"},
        {"index_code": "000300", "date": "2026-10-21", "metric": "erp", "value": 5.2,
         "freq": "daily", "source": "csindex"},
        {"index_code": "000905", "date": "2026-10-21", "metric": "erp", "value": 3.0,
         "freq": "daily", "source": "csindex"},
    ])
    got = store.fetch_metric(conn, "000300", "erp")
    assert got == [("2026-10-20", 5.0), ("2026-10-21", 5.2)]
    only_weekly = store.fetch_metric(conn, "000300", "erp", freq="weekly")
    assert only_weekly == []


def test_bond_yield_roundtrip():
    conn = make_conn()
    store.upsert_bond_yield(conn, [
        {"curve": "中债国债收益率曲线", "date": "2026-10-21", "tenor": "10年", "yield": 1.68},
    ])
    assert store.fetch_bond_yield(conn, "中债国债收益率曲线", "10年") == [("2026-10-21", 1.68)]
    assert store.trading_days(conn) == ["2026-10-21"]


def test_quality_and_meta():
    conn = make_conn()
    store.record_quality(conn, "csindex", "ok", 5293, "", 1200)
    store.set_meta(conn, "last_run", "2026-10-21T16:30:00")
    q = store.latest_quality(conn)
    assert q[0]["source"] == "csindex" and q[0]["status"] == "ok"
    assert store.get_meta(conn, "last_run") == "2026-10-21T16:30:00"
    assert store.get_meta(conn, "missing", "x") == "x"
