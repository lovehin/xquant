"""命令行入口：update / serve / export / backfill / status。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import uvicorn

from xquant import bundle, pipeline, store
from xquant.config import (BUNDLE_PATH, DB_PATH, DEFAULT_BOND_BENCHMARK, SNAPSHOT_PATH,
                            WEB_DIR)


def cmd_update(args) -> int:
    conn = store.connect(DB_PATH)
    store.init_db(conn)
    try:
        result = pipeline.run(conn, bond_key=args.bond, with_network=not args.no_network,
                              progress=print)
    finally:
        conn.close()
    print("summary:", result["summary"])
    failed = [q for q in result["quality"] if q["status"] != "ok"]
    for q in result["quality"]:
        print(f"  {q['source']:<24} {q['status']:<5} rows={q.get('rows', 0):<7} "
              f"{q.get('duration_ms', 0):>7} ms  {q.get('message', '')[:40]}")
    if failed:
        print(f"注意：{len(failed)} 个数据源失败（已沿用上次成功数据）")
    return 0


def cmd_export(args) -> int:
    conn = store.connect(DB_PATH)
    store.init_db(conn)
    try:
        snap = pipeline.export_snapshot(conn, SNAPSHOT_PATH, bond_key=args.bond)
        csv_path = bundle.write_bundle(conn, args.bundle or BUNDLE_PATH)
    finally:
        conn.close()
    print("exported:", snap)
    print("exported:", csv_path)
    return 0


def cmd_serve(args) -> int:
    uvicorn.run("xquant.server:app", host=args.host, port=args.port, reload=False)
    return 0


def cmd_backfill(args) -> int:
    """回填中证 PE 日频历史（默认 2005 起）。"""
    from xquant.config import INDEXES
    from xquant.sources import csindex
    conn = store.connect(DB_PATH)
    store.init_db(conn)
    try:
        for spec in INDEXES:
            if not spec.has_csindex:
                print(f"{spec.code} {spec.name}: 跳过（非中证系列）")
                continue
            try:
                data = csindex.fetch_index(spec.code, start_date=args.start)
            except Exception as exc:
                print(f"{spec.code} {spec.name}: 失败 {exc}")
                continue
            if data["valuation"]:
                store.upsert_valuation(conn, data["valuation"])
            if data["prices"]:
                store.upsert_price(conn, data["prices"])
            print(f"{spec.code} {spec.name}: valuation={len(data['valuation'])} "
                  f"perf={len(data['perf'])}")
    finally:
        conn.close()
    return 0


def cmd_status(args) -> int:
    conn = store.connect(DB_PATH)
    store.init_db(conn)
    try:
        quality = store.latest_quality(conn)
        last_run = store.get_meta(conn, "last_run")
    finally:
        conn.close()
    snap = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8")) if SNAPSHOT_PATH.exists() else {}
    print("数据库:", DB_PATH)
    print("上次运行:", last_run)
    print("快照生成于:", snap.get("generated_at"))
    print("数据源状态:")
    for q in quality:
        print(f"  {q['source']:<24} {q['status']:<5} rows={q.get('rows', 0):<7} {q.get('ts', '')}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="xquant", description="中国股债性价比仪表盘")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("update", help="抓取数据并计算指标")
    p.add_argument("--bond", default=DEFAULT_BOND_BENCHMARK, help="债券基准 key")
    p.add_argument("--no-network", action="store_true", help="只用库中已有数据重算指标")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("export", help="导出 series.csv + snapshot.json")
    p.add_argument("--bond", default=DEFAULT_BOND_BENCHMARK)
    p.add_argument("--bundle", default=None)
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("serve", help="启动 Web 服务")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8848)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("backfill", help="回填中证 PE 日频历史")
    p.add_argument("--start", default="20050101")
    p.set_defaults(func=cmd_backfill)

    p = sub.add_parser("status", help="查看数据状态")
    p.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
