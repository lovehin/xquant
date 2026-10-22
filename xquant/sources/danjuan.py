"""蛋卷基金（雪球）指数估值数据源。

- pe_history：PE 周频历史（2016 起），公开接口
- dj 快照：当前 PE/PB/PE 分位/股息率，公开接口
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from xquant.sources.base import http_get_json

BASE = "https://danjuanfunds.com/djapi"
CST = timezone(timedelta(hours=8))


def normalize_code(code: str | None) -> str:
    """SH000300 → 000300；非 6 位结尾的（SP500/NDX/HKHSTECH…）原样保留。"""
    if not code:
        return ""
    m = re.search(r"(\d{6})$", str(code))
    return m.group(1) if m else str(code)


def _ts_to_date(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).astimezone(CST).strftime("%Y-%m-%d")


def parse_pe_history(payload: dict) -> list[tuple[str, float]]:
    items = (payload.get("data") or {}).get("index_eva_pe_growths") or []
    rows = []
    for it in items:
        pe = it.get("pe")
        if pe is None:
            continue
        rows.append((_ts_to_date(int(it["ts"])), float(pe)))
    rows.sort(key=lambda r: r[0])
    return rows


def parse_snapshot(payload: dict, day: str | None = None) -> list[dict]:
    items = (payload.get("data") or {}).get("items") or []
    day = day or datetime.now(CST).strftime("%Y-%m-%d")
    rows = []
    for it in items:
        pe = it.get("pe")
        pb = it.get("pb")
        yeild = it.get("yeild")
        rows.append({
            "index_code": normalize_code(it.get("index_code")),
            "date": day,
            "source": "danjuan_snapshot",
            "pe": float(pe) if pe else None,
            "pb": float(pb) if pb else None,
            "dividend_yield": float(yeild) * 100 if yeild else None,
        })
    return rows


def fetch_pe_history(danjuan_code: str) -> list[tuple[str, float]]:
    payload = http_get_json(f"{BASE}/index_eva/pe_history/{danjuan_code}",
                             params={"day": "all"}, timeout=40)
    return parse_pe_history(payload)


def fetch_snapshot() -> list[dict]:
    payload = http_get_json(f"{BASE}/index_eva/dj", timeout=40)
    return parse_snapshot(payload)
