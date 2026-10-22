"""共享测试夹具。"""
import pytest

from xquant import store


def _seed(conn):
    store.upsert_bond_yield(conn, [
        {"curve": "中债国债收益率曲线", "date": f"2026-01-{d:02d}", "tenor": "10年",
         "yield": 1.7} for d in range(2, 12)
    ])
    store.upsert_valuation(conn, [
        {"index_code": "000300", "date": f"2026-01-{d:02d}", "source": "csindex",
         "pe": 12.0, "pe_total_shares": None, "pe_calc_shares": None, "pb": None,
         "dividend_yield": 2.5, "dividend_yield_total_shares": None}
        for d in range(2, 12)
    ])
    store.upsert_valuation(conn, [
        {"index_code": "000905", "date": f"2026-01-{d:02d}", "source": "csindex",
         "pe": 20.0, "pe_total_shares": None, "pe_calc_shares": None, "pb": None,
         "dividend_yield": 1.5, "dividend_yield_total_shares": None}
        for d in range(2, 12)
    ])
    store.upsert_valuation(conn, [
        {"index_code": "000852", "date": f"2026-01-{d:02d}", "source": "csindex",
         "pe": 30.0, "pe_total_shares": None, "pe_calc_shares": None, "pb": None,
         "dividend_yield": 1.2, "dividend_yield_total_shares": None}
        for d in range(2, 12)
    ])
    store.upsert_valuation(conn, [
        {"index_code": "MKT_SH", "date": f"2026-01-{d:02d}", "source": "legulegu_gxl",
         "pe": None, "pe_total_shares": None, "pe_calc_shares": None, "pb": None,
         "dividend_yield": 2.8, "dividend_yield_total_shares": None}
        for d in range(2, 12)
    ])
    return conn


@pytest.fixture
def conn():
    conn = store.connect(":memory:")
    store.init_db(conn)
    _seed(conn)
    return conn
