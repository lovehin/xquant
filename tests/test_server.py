import json

import pytest
from fastapi.testclient import TestClient

from xquant import bundle, pipeline, server, store
from tests.conftest import _seed


def make_client(tmp_path):
    """服务端拿到的是空库 + 已发布的 series.csv（模拟 git pull 后的真实场景）。"""
    src = store.connect(tmp_path / "src.db")
    store.init_db(src)
    _seed(src)
    pipeline.compute_metrics(src)
    bundle.write_bundle(src, tmp_path / "series.csv")
    src.close()

    db = tmp_path / "t.db"
    empty = store.connect(db)
    store.init_db(empty)
    empty.close()
    return TestClient(server.create_app(db, bundle_path=tmp_path / "series.csv"))


def test_snapshot_endpoint(tmp_path):
    client = make_client(tmp_path)
    r = client.get("/api/snapshot")
    assert r.status_code == 200
    data = r.json()
    assert data["bond"]["key"] == "bond10y"
    codes = [i["code"] for i in data["indexes"]]
    assert "000300" in codes


def test_series_endpoint(tmp_path):
    client = make_client(tmp_path)
    r = client.get("/api/series", params={"index": "000300", "metric": "erp"})
    assert r.status_code == 200
    data = r.json()
    assert data["index_code"] == "000300"
    assert len(data["points"]) == 10
    assert data["points"][0][0] == "2026-01-02"


def test_series_endpoint_rejects_unknown_index(tmp_path):
    client = make_client(tmp_path)
    r = client.get("/api/series", params={"index": "999999", "metric": "erp"})
    assert r.status_code == 404


def test_percentile_series_computed_on_demand(tmp_path):
    client = make_client(tmp_path)
    r = client.get("/api/series", params={"index": "000300", "metric": "erp_pct_10y"})
    assert r.status_code == 200
    # 样本不足 60 时应为空
    assert r.json()["points"] == []


def test_health_endpoint(tmp_path):
    client = make_client(tmp_path)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert "quality" in r.json()


def test_index_page_served(tmp_path):
    client = make_client(tmp_path)
    r = client.get("/")
    assert r.status_code == 200
    assert "xquant" in r.text.lower()


def test_bundle_is_imported_into_db(tmp_path):
    """DB 为空时，服务端应能从 series.csv 恢复数据。"""
    client = make_client(tmp_path)
    r = client.get("/api/series", params={"index": "000300", "metric": "erp"})
    assert r.status_code == 200
    assert len(r.json()["points"]) == 10


def test_local_run_wins_over_stale_bundle(tmp_path):
    """本地刚跑过批时，旧 bundle 不应把新指标覆盖回去。"""
    import time
    client = make_client(tmp_path)
    db = tmp_path / "t.db"
    conn = store.connect(db)
    store.init_db(conn)
    store.upsert_metric(conn, [
        {"index_code": "000300", "date": "2026-01-02", "metric": "erp", "value": 99.0,
         "freq": "daily", "source": "master"}])
    store.set_meta(conn, "last_run_ts", str(time.time() + 10))
    conn.close()

    r = client.get("/api/series", params={"index": "000300", "metric": "erp"})
    assert r.json()["points"][0][1] == 99.0
