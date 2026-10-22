"""数据源公共设施：统一结果对象 + HTTP helper。"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


@dataclass
class SourceResult:
    source: str
    ok: bool
    rows: int = 0
    message: str = ""
    duration_ms: int = 0


def http_get_json(url: str, params: dict | None = None, timeout: int = 30) -> Any:
    resp = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def http_get_bytes(url: str, timeout: int = 30) -> bytes:
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    resp.raise_for_status()
    return resp.content


class Timer:
    """上下文管理器，测量耗时毫秒。"""

    def __init__(self) -> None:
        self.ms = 0

    def __enter__(self) -> "Timer":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc) -> None:
        self.ms = int((time.perf_counter() - self._t0) * 1000)
