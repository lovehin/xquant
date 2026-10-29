import pytest

from xquant import bundle, store


def seeded_conn():
    conn = store.connect(":memory:")
    store.init_db(conn)
    store.upsert_metric(conn, [
        {"index_code": "000300", "date": "2026-01-02", "metric": "erp", "value": 6.63,
         "freq": "daily", "source": "master"},
        {"index_code": "000300", "date": "2026-01-02", "metric": "pe", "value": 12.0,
         "freq": "daily", "source": "master"},
        {"index_code": "000300", "date": "2026-01-02", "metric": "dy_spread", "value": 0.8,
         "freq": "daily", "source": "master"},
        {"index_code": "STYLE_300_1000", "date": "2026-01-02", "metric": "style_spread",
         "value": 1.67, "freq": "daily", "source": "master"},
    ])
    store.upsert_bond_yield(conn, [
        {"curve": "中债国债收益率曲线", "date": "2026-01-02", "tenor": "10年", "yield": 1.7}])
    store.upsert_price(conn, [
        {"index_code": "000300", "date": "2026-01-02", "close": 4000.0, "source": "csindex"}])
    return conn


def test_write_and_read_bundle_roundtrip(tmp_path):
    conn = seeded_conn()
    path = bundle.write_bundle(conn, tmp_path / "series.csv")
    data = bundle.read_bundle(path)
    assert data["erp:000300"] == [("2026-01-02", 6.63)]
    assert data["dy:000300"] == [("2026-01-02", 0.8)]
    assert data["style:spread"] == [("2026-01-02", 1.67)]
    assert data["bond:10年:中债国债收益率曲线"] == [("2026-01-02", 1.7)]
    assert data["price:000300"] == [("2026-01-02", 4000.0)]
    # PE 历史不入包（当前 PE 在 snapshot.json）
    assert "pe:000300" not in data


def test_bundle_keeps_only_benchmark_bond_series(tmp_path):
    conn = seeded_conn()
    store.upsert_bond_yield(conn, [
        {"curve": "中债国债收益率曲线", "date": "2026-01-02", "tenor": "7年", "yield": 1.5}])
    path = bundle.write_bundle(conn, tmp_path / "series.csv")
    data = bundle.read_bundle(path)
    assert "bond:10年:中债国债收益率曲线" in data
    assert "bond:7年:中债国债收益率曲线" not in data


def test_import_bundle_is_idempotent(tmp_path):
    conn = seeded_conn()
    path = bundle.write_bundle(conn, tmp_path / "series.csv")
    target = store.connect(":memory:")
    store.init_db(target)
    n1 = bundle.import_bundle(target, path)
    n2 = bundle.import_bundle(target, path)
    assert n1 == n2
    assert store.fetch_metric(target, "000300", "erp") == [("2026-01-02", 6.63)]
    assert store.fetch_bond_yield(target, "中债国债收益率曲线", "10年") == [("2026-01-02", 1.7)]
    assert store.fetch_prices(target, "000300") == [("2026-01-02", 4000.0)]


def test_import_missing_file_returns_zero(tmp_path):
    conn = store.connect(":memory:")
    store.init_db(conn)
    assert bundle.import_bundle(conn, tmp_path / "nope.csv") == 0


def test_bundle_file_is_sorted_and_compact(tmp_path):
    conn = seeded_conn()
    path = bundle.write_bundle(conn, tmp_path / "series.csv")
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert lines[0] == "series_id,date,value"
    ids = [ln.split(",")[0] for ln in lines[1:]]
    assert ids == sorted(ids)
    assert "erp:000300,2026-01-02,6.63" in lines

def test_prices_deduped_across_sources(tmp_path):
    """同一日期存在 csindex 与 bundle 两种来源时，导出只保留一条（csindex 优先）。"""
    conn = store.connect(":memory:")
    store.init_db(conn)
    store.upsert_price(conn, [
        {"index_code": "000300", "date": "2026-01-02", "close": 4000.0, "source": "bundle"},
        {"index_code": "000300", "date": "2026-01-02", "close": 4010.0, "source": "csindex"},
    ])
    path = bundle.write_bundle(conn, tmp_path / "series.csv")
    data = bundle.read_bundle(path)
    assert data["price:000300"] == [("2026-01-02", 4010.0)]
