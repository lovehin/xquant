import pytest

from xquant import pipeline, store


def test_build_master_pe_prefers_csindex_and_keeps_legulegu_history(conn):
    store.upsert_valuation(conn, [
        {"index_code": "000300", "date": "2025-12-01", "source": "legulegu",
         "pe": 11.0, "pe_total_shares": None, "pe_calc_shares": None, "pb": None,
         "dividend_yield": None, "dividend_yield_total_shares": None},
    ])
    rows = pipeline.build_master_pe(conn, "000300")
    assert rows[0] == ("2025-12-01", 11.0)
    assert rows[1][0] == "2026-01-02" and rows[1][1] == 12.0
    assert len(rows) == 11  # 1 条历史 + 10 条日频


def test_compute_metrics_writes_erp_and_percentiles(conn):
    pipeline.compute_metrics(conn)
    erp = store.fetch_metric(conn, "000300", "erp")
    # PE=12 → 8.3333%，减 1.7% → 6.6333
    assert erp[0][1] == pytest.approx(6.6333, abs=1e-4)
    assert store.fetch_metric(conn, "000300", "erp_pct_10y") == []  # 样本不足不写


def test_compute_metrics_writes_dividend_spread(conn):
    pipeline.compute_metrics(conn)
    ds = store.fetch_metric(conn, "000300", "dy_spread")
    assert ds[0][1] == pytest.approx(0.8, abs=1e-9)  # 2.5 - 1.7


def test_compute_metrics_writes_market_dividend_spread(conn):
    pipeline.compute_metrics(conn)
    m = store.fetch_metric(conn, "MKT_SH", "dy_spread")
    assert m[0][1] == pytest.approx(1.1, abs=1e-9)  # 2.8 - 1.7


def test_compute_metrics_writes_style_spread(conn):
    pipeline.compute_metrics(conn)
    style = store.fetch_metric(conn, "STYLE_300_1000", "style_spread")
    # ERP(300)=1/12*100-1.7=6.6333；ERP(1000)=1/30*100-1.7=1.6333；差=5.0
    assert style[0][1] == pytest.approx(5.0, abs=1e-4)


def test_run_without_network_recomputes_and_exports(tmp_path, conn):
    out = tmp_path / "snapshot.json"
    result = pipeline.run(conn, with_network=False, snapshot_path=out,
                          bundle_path=tmp_path / "series.csv")
    assert result["summary"]["indices"] >= 3
    assert out.exists()
    import json
    data = json.loads(out.read_text())
    assert data["generated_at"]
    assert any(i["code"] == "000300" for i in data["indexes"])
    assert data["indexes"][0]["erp"] is not None


def test_source_failure_is_isolated(conn, tmp_path):

    class Boom:
        source = "boom"

        def fetch(self, *a, **kw):
            raise RuntimeError("boom")

    class Good:
        source = "good"

        def fetch(self, *a, **kw):
            return {"valuation": [], "perf": [], "prices": []}

    pipeline.SOURCES = [Boom(), Good()]
    try:
        result = pipeline.run(conn, with_network=True, snapshot_path=tmp_path / "s.json",
                              bundle_path=tmp_path / "series.csv")
    finally:
        pipeline.SOURCES = pipeline.default_sources()
    statuses = {q["source"]: q["status"] for q in result["quality"]}
    assert statuses["boom"] == "fail"
    assert statuses["good"] == "ok"


def test_run_backtest_computes_stats(conn):
    import datetime as dt
    conn = store.connect(":memory:")
    store.init_db(conn)
    days = [(dt.date(2024, 1, 1) + dt.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(400)]
    store.upsert_bond_yield(conn, [
        {"curve": "中债国债收益率曲线", "date": d, "tenor": "10年", "yield": 1.8} for d in days])
    store.upsert_valuation(conn, [
        {"index_code": "000300", "date": d, "source": "csindex_pe", "pe": 12.0,
         "pe_total_shares": None, "pe_calc_shares": None, "pb": None,
         "dividend_yield": None, "dividend_yield_total_shares": None} for d in days])
    store.upsert_price(conn, [
        {"index_code": "000300", "date": d, "close": 4000.0, "source": "csindex"} for d in days])
    pipeline.compute_metrics(conn)
    bt = pipeline.run_backtest(conn, warmup=60)
    assert bt["available"] is True
    assert bt["strategy"]["cagr"] is not None
    assert bt["equity_only"]["cagr"] is not None
    assert bt["period"][0] < bt["period"][1]
