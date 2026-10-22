"""构建 GitHub Pages 静态版站点。

把一个预生成的 `data/bundle.js`（`window.XQ_STATIC = {...}`）连同前端资源打包到 `site/`，
前端检测到 `window.XQ_STATIC` 就直接用静态数据渲染，不再请求 `/api/*`。

数据量控制：所有序列共用一条交易日数组（dates），每条序列存等长的数值数组（缺失为 null）。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from xquant import bundle, pipeline, store
from xquant.config import (ALLOCATION_MAP, BACKTEST_INDEX, BUNDLE_PATH, DB_PATH, INDEXES,
                           MARKET_DIVIDEND_SERIES, WEB_DIR)


def build_bundle_data(conn) -> dict:
    """把库里前端需要的序列整理成一个可序列化的字典。"""
    snapshot = pipeline.snapshot_payload(conn)

    raw: dict[str, list[tuple[str, float]]] = {}
    for spec in INDEXES:
        raw[f"erp:{spec.code}"] = store.fetch_metric(conn, spec.code, "erp")
        raw[f"dy:{spec.code}"] = store.fetch_metric(conn, spec.code, "dy_spread")
    for code in MARKET_DIVIDEND_SERIES:
        raw[f"dy:{code}"] = store.fetch_metric(conn, code, "dy_spread")

    dates = sorted({d for points in raw.values() for d, _ in points})
    position = {d: i for i, d in enumerate(dates)}
    series: dict[str, list[float | None]] = {}
    for series_id, points in raw.items():
        if not points:
            continue
        values: list[float | None] = [None] * len(dates)
        for d, v in points:
            values[position[d]] = round(float(v), 4)
        series[series_id] = values

    style = store.fetch_metric(conn, "STYLE_500_1000", "style_spread")
    style_pct = store.fetch_metric(conn, "STYLE_500_1000", "style_pct")
    backtest = pipeline.run_backtest(conn, index_code=BACKTEST_INDEX)

    return {
        "generated_at": snapshot["generated_at"],
        "dates": dates,
        "series": series,
        "snapshot": {
            "generated_at": snapshot["generated_at"],
            "bond": snapshot["bond"],
            "indexes": snapshot["indexes"],
        },
        "style": {
            "points": [[d, v] for d, v in style],
            "percentile_points": [[d, v] for d, v in style_pct],
            "latest": list(style[-1]) if style else None,
            "percentile": style_pct[-1][1] if style_pct else None,
            "signal": snapshot["style"]["signal"],
        },
        "allocation": {
            "items": snapshot["indexes"],
            "backtest": backtest,
            "bands": [{"max_pct": b.max_pct, "equity_min": b.equity_min,
                       "equity_max": b.equity_max} for b in ALLOCATION_MAP],
        },
        "health": {
            "quality": snapshot["quality"],
            "last_run": store.get_meta(conn, "last_run"),
            "bond_benchmark": store.get_meta(conn, "last_bond_benchmark", "bond10y"),
            "refresh": None,
        },
    }


def _relative_index_html(html: str) -> str:
    """把绝对路径改成相对路径，兼容 GitHub Pages 的 /<repo>/ 子路径。"""
    html = html.replace('href="/', 'href="').replace('src="/', 'src="')
    return html.replace(
        '<script src="app.js"></script>',
        '<script src="data/bundle.js"></script>\n<script src="app.js"></script>',
    )


def build(out_dir: str | Path, db_path: str | Path | None = None,
          bundle_path: str | Path | None = None) -> Path:
    out = Path(out_dir)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    (out / "index.html").write_text(
        _relative_index_html((WEB_DIR / "index.html").read_text(encoding="utf-8")),
        encoding="utf-8")
    for name in ("style.css", "app.js"):
        shutil.copy2(WEB_DIR / name, out / name)
    shutil.copytree(WEB_DIR / "vendor", out / "vendor")
    (out / ".nojekyll").write_text("", encoding="utf-8")

    conn = store.connect(db_path or DB_PATH)
    store.init_db(conn)
    try:
        if not store.fetch_metric(conn, BACKTEST_INDEX, "erp"):
            source = Path(bundle_path or BUNDLE_PATH)
            if source.exists():
                bundle.import_bundle(conn, source)
        pipeline.ensure_percentiles(conn)
        payload = build_bundle_data(conn)
    finally:
        conn.close()

    data_dir = out / "data"
    data_dir.mkdir(exist_ok=True)
    js = "window.XQ_STATIC=" + json.dumps(payload, ensure_ascii=False,
                                          separators=(",", ":")) + ";"
    (data_dir / "bundle.js").write_text(js, encoding="utf-8")
    return out
