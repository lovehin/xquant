import json

import pytest

from xquant import pipeline, static_site, store
from tests.conftest import _seed


def _build(tmp_path):
    db = tmp_path / "t.db"
    conn = store.connect(db)
    store.init_db(conn)
    _seed(conn)
    pipeline.compute_metrics(conn)
    conn.close()
    return static_site.build(tmp_path / "site", db_path=db, bundle_path=tmp_path / "none.csv")


def _bundle(site):
    text = (site / "data" / "bundle.js").read_text(encoding="utf-8")
    assert text.startswith("window.XQ_STATIC=")
    assert text.endswith(";")
    return json.loads(text[len("window.XQ_STATIC="):-1])


def test_site_files_exist(tmp_path):
    site = _build(tmp_path)
    for name in ("index.html", "app.js", "style.css", ".nojekyll",
                 "vendor/echarts.min.js", "data/bundle.js"):
        assert (site / name).exists(), name


def test_index_html_uses_relative_paths_and_loads_bundle(tmp_path):
    site = _build(tmp_path)
    html = (site / "index.html").read_text(encoding="utf-8")
    assert 'src="/' not in html and 'href="/' not in html  # Pages 子路径兼容
    assert '<script src="data/bundle.js"></script>' in html
    assert html.index("data/bundle.js") < html.index('src="app.js"')


def test_bundle_contains_snapshot_and_aligned_series(tmp_path):
    site = _build(tmp_path)
    data = _bundle(site)
    assert data["dates"] and data["dates"] == sorted(data["dates"])
    assert "erp:000300" in data["series"]
    values = data["series"]["erp:000300"]
    assert len(values) == len(data["dates"])
    assert all(v is None or isinstance(v, (int, float)) for v in values)
    assert data["snapshot"]["indexes"][0]["code"] == "000300"
    assert data["allocation"]["backtest"] is not None
    assert "quality" in data["health"]


def test_bundle_series_lengths_match_date_axis(tmp_path):
    site = _build(tmp_path)
    data = _bundle(site)
    n = len(data["dates"])
    for series_id, values in data["series"].items():
        assert len(values) == n, series_id


def test_frontend_supports_static_mode():
    js = (static_site.WEB_DIR / "app.js").read_text(encoding="utf-8")
    assert "window.XQ_STATIC" in js
    assert "XQ_STATIC" in js and "静态版" in js
