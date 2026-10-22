"""SQLite 持久层：建表、幂等写入、查询。

所有写入走 INSERT OR REPLACE，重复跑批不会产生重复行。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

SCHEMA = """
CREATE TABLE IF NOT EXISTS bond_yield (
    curve TEXT NOT NULL, date TEXT NOT NULL, tenor TEXT NOT NULL, yield REAL,
    PRIMARY KEY (curve, date, tenor)
);
CREATE TABLE IF NOT EXISTS index_valuation (
    index_code TEXT NOT NULL, date TEXT NOT NULL, source TEXT NOT NULL,
    pe REAL, pe_total_shares REAL, pe_calc_shares REAL, pb REAL,
    dividend_yield REAL, dividend_yield_total_shares REAL,
    PRIMARY KEY (index_code, date, source)
);
CREATE TABLE IF NOT EXISTS index_price (
    index_code TEXT NOT NULL, date TEXT NOT NULL, close REAL, source TEXT NOT NULL,
    PRIMARY KEY (index_code, date, source)
);
CREATE TABLE IF NOT EXISTS metric_series (
    index_code TEXT NOT NULL, date TEXT NOT NULL, metric TEXT NOT NULL,
    value REAL, freq TEXT NOT NULL, source TEXT NOT NULL,
    PRIMARY KEY (index_code, date, metric, freq)
);
CREATE TABLE IF NOT EXISTS data_quality (
    ts TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL,
    rows INTEGER, message TEXT, duration_ms INTEGER
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

TABLES = {
    "bond_yield": ("curve", "date", "tenor", "yield"),
    "index_valuation": ("index_code", "date", "source", "pe", "pe_total_shares",
                        "pe_calc_shares", "pb", "dividend_yield", "dividend_yield_total_shares"),
    "index_price": ("index_code", "date", "close", "source"),
    "metric_series": ("index_code", "date", "metric", "value", "freq", "source"),
}


def connect(path: str | Path) -> sqlite3.Connection:
    p = Path(path)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def _upsert(conn: sqlite3.Connection, table: str, rows: Sequence[dict[str, Any]]) -> int:
    cols = TABLES[table]
    placeholders = ",".join("?" for _ in cols)
    sql = f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({placeholders})"
    payload = [tuple(r.get(c) for c in cols) for r in rows]
    if not payload:
        return 0
    conn.executemany(sql, payload)
    conn.commit()
    return len(payload)


def upsert_bond_yield(conn, rows):
    return _upsert(conn, "bond_yield", rows)


def upsert_valuation(conn, rows):
    return _upsert(conn, "index_valuation", rows)


def upsert_price(conn, rows):
    return _upsert(conn, "index_price", rows)


def upsert_metric(conn, rows):
    return _upsert(conn, "metric_series", rows)


def record_quality(conn, source: str, status: str, rows: int, message: str, duration_ms: int) -> None:
    conn.execute(
        "INSERT INTO data_quality (ts, source, status, rows, message, duration_ms) VALUES (?,?,?,?,?,?)",
        (datetime.now(timezone.utc).isoformat(timespec="seconds"), source, status, rows,
         message[:500], duration_ms),
    )
    conn.commit()


def latest_quality(conn) -> list[dict]:
    cur = conn.execute(
        "SELECT q.* FROM data_quality q JOIN (SELECT source, MAX(ts) mx FROM data_quality GROUP BY source) m"
        " ON q.source = m.source AND q.ts = m.mx ORDER BY q.source")
    return [dict(r) for r in cur.fetchall()]


def fetch_metric(conn, index_code: str, metric: str, freq: str | None = None) -> list[tuple[str, float]]:
    sql = "SELECT date, value FROM metric_series WHERE index_code=? AND metric=?"
    args: list[Any] = [index_code, metric]
    if freq:
        sql += " AND freq=?"
        args.append(freq)
    sql += " ORDER BY date"
    return [(r["date"], r["value"]) for r in conn.execute(sql, args) if r["value"] is not None]


def fetch_bond_yield(conn, curve: str, tenor: str, start: str | None = None,
                     end: str | None = None) -> list[tuple[str, float]]:
    sql = "SELECT date, yield FROM bond_yield WHERE curve=? AND tenor=?"
    args: list[Any] = [curve, tenor]
    if start:
        sql += " AND date>=?"
        args.append(start)
    if end:
        sql += " AND date<=?"
        args.append(end)
    sql += " ORDER BY date"
    return [(r["date"], r["yield"]) for r in conn.execute(sql, args) if r["yield"] is not None]


def fetch_valuation(conn, index_code: str, source: str | None = None) -> list[dict]:
    sql = "SELECT * FROM index_valuation WHERE index_code=?"
    args: list[Any] = [index_code]
    if source:
        sql += " AND source=?"
        args.append(source)
    sql += " ORDER BY date"
    return [dict(r) for r in conn.execute(sql, args)]


def fetch_prices(conn, index_code: str, source: str | None = None) -> list[tuple[str, float]]:
    sql = "SELECT date, close FROM index_price WHERE index_code=?"
    args: list[Any] = [index_code]
    if source:
        sql += " AND source=?"
        args.append(source)
    sql += " ORDER BY date"
    return [(r["date"], r["close"]) for r in conn.execute(sql, args) if r["close"] is not None]


def trading_days(conn, start: str | None = None, end: str | None = None) -> list[str]:
    sql = "SELECT DISTINCT date FROM bond_yield"
    args: list[Any] = []
    if start:
        sql += " WHERE date>=?"
        args.append(start)
    if end:
        sql += " AND date<=?"
        args.append(end)
    sql += " ORDER BY date"
    return [r["date"] for r in conn.execute(sql, args)]


def set_meta(conn, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (key, str(value)))
    conn.commit()


def get_meta(conn, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default
