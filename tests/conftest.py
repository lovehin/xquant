"""共享测试夹具。"""
import pytest

from xquant import store


def _seed(conn):
    store.upsert_bond_yield(conn, [
        {"curve": "中债国债收益率曲线", "date": f"2026-01-{d:02d}", "tenor": "10年",
         "yield": 1.7} for d in range(2, 12)
    ])
    # PE 主口径（中证官方滚动市盈率）与估值快照（股息率）分开落源，与生产一致
    for code, pe, dy in (("000300", 12.0, 2.5), ("000905", 20.0, 1.5), ("000852", 30.0, 1.2)):
        store.upsert_valuation(conn, [
            {"index_code": code, "date": f"2026-01-{d:02d}", "source": "csindex_pe",
             "pe": pe, "pe_total_shares": None, "pe_calc_shares": None, "pb": None,
             "dividend_yield": None, "dividend_yield_total_shares": None}
            for d in range(2, 12)
        ])
        store.upsert_valuation(conn, [
            {"index_code": code, "date": f"2026-01-{d:02d}", "source": "csindex",
             "pe": None, "pe_total_shares": None, "pe_calc_shares": None, "pb": None,
             "dividend_yield": dy, "dividend_yield_total_shares": None}
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
