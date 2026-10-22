"""FastAPI 服务：提供仪表盘所需的 JSON 接口。

数据来源：本地 SQLite（data/market.db）。若数据库为空或比 data/series.csv 旧，
启动时会自动从 series.csv 导入，这样 git pull 到的新数据能直接被读到。
"""
from __future__ import annotations

import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from xquant import bundle, metrics, pipeline, store
from xquant.config import (ALLOCATION_MAP, BACKTEST_INDEX, BUNDLE_PATH, DB_PATH,
                            DEFAULT_BOND_BENCHMARK, INDEXES, PERCENTILE_WINDOWS, WEB_DIR,
                            benchmark_by_key)

_refresh_lock = threading.Lock()
_refresh_state = {"running": False, "started_at": None, "finished_at": None, "error": None}


def create_app(db_path: str | Path | None = None,
               bundle_path: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="xquant 股债性价比仪表盘", version="0.1.0")
    db = Path(db_path) if db_path else None
    bundle_file = Path(bundle_path) if bundle_path else BUNDLE_PATH
    pct_cache: dict[tuple[str, str], list[tuple[str, float]]] = {}
    cache_lock = threading.Lock()

    def conn():
        c = store.connect(db if db is not None else DB_PATH)
        store.init_db(c)
        return c

    def sync_bundle(c) -> None:
        """series.csv 比库里新时导入（git pull 后自动生效）。

        保护：若本地刚跑过批（last_run_ts 更新），说明库里的数据比 bundle 新，
        此时不导入，避免旧快照覆盖刚算出的指标。
        """
        if not bundle_file.exists():
            return
        ctime = bundle_file.stat().st_mtime
        last = store.get_meta(c, "bundle_imported_at", "0")
        try:
            last_ts = float(last)
        except (TypeError, ValueError):
            last_ts = 0.0
        if ctime <= last_ts:
            return
        local_ts = store.get_meta(c, "last_run_ts", "0")
        try:
            local_run = float(local_ts)
        except (TypeError, ValueError):
            local_run = 0.0
        if local_run > ctime:
            return
        n = bundle.import_bundle(c, bundle_file)
        store.set_meta(c, "bundle_imported_at", str(ctime))
        with cache_lock:
            pct_cache.clear()

    def percentile_rows(c, index_code: str, wname: str) -> list[tuple[str, float]]:
        key = (index_code, wname)
        with cache_lock:
            if key in pct_cache:
                return pct_cache[key]
        rows = store.fetch_metric(c, index_code, f"erp_pct_{wname}")
        if not rows:
            erp = store.fetch_metric(c, index_code, "erp")
            values = [v for _, v in erp]
            pcts = metrics.percentile_series(values, PERCENTILE_WINDOWS[wname])
            rows = [(d, p) for (d, _), p in zip(erp, pcts) if p is not None]
        with cache_lock:
            pct_cache[key] = rows
        return rows

    @app.get("/")
    def index_page():
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/api/snapshot")
    def snapshot():
        c = conn()
        try:
            sync_bundle(c)
            return JSONResponse(pipeline.snapshot_payload(c, DEFAULT_BOND_BENCHMARK))
        finally:
            c.close()

    @app.get("/api/series")
    def series(index: str = Query(...), metric: str = Query("erp"),
               window: str | None = Query(None)):
        spec = next((i for i in INDEXES if i.code == index), None)
        if spec is None and index not in ("STYLE_500_1000",) and not index.startswith("MKT_"):
            raise HTTPException(status_code=404, detail=f"unknown index {index}")
        c = conn()
        try:
            sync_bundle(c)
            if metric.startswith("erp_pct_"):
                wname = metric.removeprefix("erp_pct_")
                if wname not in PERCENTILE_WINDOWS:
                    raise HTTPException(status_code=400, detail=f"unknown window {wname}")
                rows = percentile_rows(c, index, wname)
                # 分位样本不足时返回空序列（200），由前端提示
                return {"index_code": index, "metric": metric, "window": window,
                        "points": [[d, v] for d, v in rows]}
            else:
                rows = store.fetch_metric(c, index, metric)
            if not rows:
                raise HTTPException(status_code=404, detail=f"no data for {index}/{metric}")
            return {"index_code": index, "metric": metric, "window": window,
                    "points": [[d, v] for d, v in rows]}
        finally:
            c.close()

    @app.get("/api/compare")
    def compare(metric: str = Query("erp")):
        c = conn()
        try:
            sync_bundle(c)
            out = []
            for spec in INDEXES:
                rows = store.fetch_metric(c, spec.code, metric)
                if rows:
                    out.append({"code": spec.code, "name": spec.name, "group": spec.group,
                                "points": [[d, v] for d, v in rows]})
            return {"metric": metric, "series": out}
        finally:
            c.close()

    @app.get("/api/style")
    def style():
        c = conn()
        try:
            sync_bundle(c)
            spread = store.fetch_metric(c, "STYLE_500_1000", "style_spread")
            pct = store.fetch_metric(c, "STYLE_500_1000", "style_pct")
            if not pct:
                values = [v for _, v in spread]
                pcts = metrics.percentile_series(values, PERCENTILE_WINDOWS["10y"])
                pct = [(d, p) for (d, _), p in zip(spread, pcts) if p is not None]
            return {
                "points": [[d, v] for d, v in spread],
                "percentile_points": [[d, v] for d, v in pct],
                "latest": spread[-1] if spread else None,
                "percentile": pct[-1][1] if pct else None,
                "signal": metrics.style_signal(pct[-1][1] if pct else None),
            }
        finally:
            c.close()

    @app.get("/api/allocation")
    def allocation():
        c = conn()
        try:
            sync_bundle(c)
            snap = pipeline.snapshot_payload(c, DEFAULT_BOND_BENCHMARK)
            return {
                "items": snap["indexes"],
                "backtest": pipeline.run_backtest(c, index_code=BACKTEST_INDEX),
                "bands": [{"max_pct": b.max_pct, "equity_min": b.equity_min,
                           "equity_max": b.equity_max} for b in ALLOCATION_MAP],
            }
        finally:
            c.close()

    @app.get("/api/health")
    def health():
        c = conn()
        try:
            sync_bundle(c)
            return {"quality": store.latest_quality(c),
                    "last_run": store.get_meta(c, "last_run"),
                    "bond_benchmark": store.get_meta(c, "last_bond_benchmark",
                                                    DEFAULT_BOND_BENCHMARK),
                    "refresh": _refresh_state}
        finally:
            c.close()

    @app.post("/api/refresh")
    def refresh():
        with _refresh_lock:
            if _refresh_state["running"]:
                return JSONResponse({"started": False, "reason": "already running",
                                     "state": _refresh_state})
            _refresh_state.update({"running": True, "started_at": None, "error": None})

        def worker():
            from datetime import datetime, timezone
            try:
                _refresh_state["started_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                c = conn()
                try:
                    pipeline.run(c)
                finally:
                    c.close()
                with cache_lock:
                    pct_cache.clear()
            except Exception as exc:
                _refresh_state["error"] = str(exc)
            finally:
                _refresh_state["running"] = False
                _refresh_state["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

        threading.Thread(target=worker, daemon=True).start()
        return {"started": True, "state": _refresh_state}

    # 静态资源（注册在最后，保证前面的 API 路由优先匹配）
    if WEB_DIR.exists():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

    return app


app = create_app()
