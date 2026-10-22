# xquant 中国股债性价比仪表盘 · 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个本地运行的 Web 仪表盘，计算并展示中国 A 股的格雷厄姆指数（ERP）、股息率差、历史分位温度、大小盘风格利差与股/债配置参考。

**Architecture:** Python 后端（akshare + 直连 HTTP 抓源 → SQLite 落库 → 纯函数指标计算 → FastAPI 提供 JSON），前端为单页浅色简洁仪表盘（原生 JS + 本地 vendor 的 ECharts）。每个数据源封装成独立模块，失败隔离、沿用旧值。

**Tech Stack:** Python 3.12 / pandas 3.0 / akshare 1.19 / FastAPI 0.159 / uvicorn / SQLite / ECharts 5.5 / pytest

## Global Constraints

- Python 版本 ≥ 3.11（仓库根目录 `.venv` 已用 3.12 建好，所有命令用 `.venv/bin/python`）
- 运行/测试命令一律使用 `.venv/bin/python`，包管理用 `uv pip install --python .venv/bin/python <pkg>`
- 禁止引入 pandas 3.0 已移除的 API（如 `applymap`、`DataFrame.append`）
- 所有日期在库内一律存 TEXT，格式 `YYYY-MM-DD`；时间戳一律 ISO8601 字符串
- 所有对外数据（API 响应、snapshot.json）使用 UTF-8、键名 snake_case
- 数据库文件固定为 `data/market.db`；导出的 JSON 固定为 `data/snapshot.json`
- 指数代码统一用 6 位中证代码（`000300`、`399006`…），蛋卷前缀代码只存在于源模块内部
- 任何指标分位样本数 < 60 时返回 `null`，不得用小样本硬算
- 前端不得依赖外网 CDN：ECharts 必须下载到 `web/vendor/echarts.min.js`
- 每个源抓取失败不得中断整条流水线，必须落 `data_quality` 表并在 `/api/health` 暴露
- 提交信息使用 Conventional Commits（`feat:` / `fix:` / `test:` / `docs:` / `chore:`）
- Git 仓库已存在（已 init，首次提交为设计文档 `f749237`）；不要重新 `git init`
- 用户已有 GitHub 仓库，但地址未知：Task 12 只生成本地 git 仓库配置与 workflow 文件，`git remote add` 留给用户执行

---

## 数据源事实（2026-10-22 实测结论，实现时直接依赖，勿再重复调研）

| 源 | 接口 | 产出 | 频率/历史 |
|---|---|---|---|
| 中证指数 `index-perf` | `GET https://www.csindex.com.cn/csindex-home/perf/index-perf?indexCode={code}&startDate=YYYYMMDD&endDate=YYYYMMDD` | JSON；字段含 `tradeDate/close/peg` | 日 / 2005-01-04 → 今，一次请求返回全历史（~5300 行，~1.8MB/指数）|
| 中证指数 `indicator.xls` | `GET https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/indicator/{code}indicator.xls` | Excel，首行表头，20 行 | 日 / 仅近 20 日窗口 |
| 中债收益率曲线 | akshare `bond_china_yield(start_date, end_date)` | 列：曲线名称/日期/3月/6月/1年/3年/5年/7年/10年/30年 | 日 / 2002 → |
| 蛋卷 PE 周频 | `GET https://danjuanfunds.com/djapi/index_eva/pe_history/{SH000300}?day=all` | `data.index_eva_pe_growths[{pe, ts}]` | 周 / 2016-10-21 → |
| 蛋卷估值快照 | `GET https://danjuanfunds.com/djapi/index_eva/dj` | `data.items[]`，含 index_code/name/pe/pb/pe_percentile/yeild | 快照 / 63 指数 |
| 乐咕股债利差 | akshare `stock_ebs_lg()` | 日期/沪深300指数/股债利差/股债利差均线 | 日 / 2006 → |
| 乐咕指数 PE | akshare `stock_index_pe_lg(symbol=...)` | 日期/指数/静态市盈率/滚动市盈率/… | 月 / 2005 → |
| 乐咕市场股息率 | akshare `stock_a_gxl_lg(symbol=...)` | 日期/股息率 | 日 / 2005 → |

关键口径事实（已验证，写入代码注释）：

- 中证 `index-perf` 的 `peg` 字段 = **中证官方近四季滚动市盈率(TTM)**（2026-10-21 沪深300 = 12.77，与 CEIC 同口径 12.91 吻合；peg/close 比值仅在财报季变动，其余日随价格变动）。**这是主 PE 口径。**
- 中证 `indicator.xls` 两列市盈率是**股本口径差异**，不是静态/滚动差异：`市盈率1（总股本）` vs `市盈率2（计算用股本）`（2026-10-21 沪深300 = 13.93 / 15.47）。两者都作为辅助口径落库，主口径仍是 `peg`。
- `indicator.xls` 的 `股息率1（总股本）` / `股息率2（计算用股本）` 同理。
- 蛋卷 PE 与中证 PE 方法不同（2026-10-21 沪深300：蛋卷 12.85 / 中证 peg 12.77 / 中证 P/E1 13.93），仅作交叉校验。
- 创业板指 399006 属深证系，中证无 `indicator.xls`（404），用蛋卷周频 PE（2016→）。
- 中证全指 000985 有 `index-perf`（含 peg，2005→），无蛋卷历史。

---

## 文件结构

```
xquant/
├── pyproject.toml                  # 包元数据 + pytest 配置
├── requirements.txt                # 固定版本依赖
├── xquant/
│   ├── __init__.py                 # __version__
│   ├── config.py                   # 指数清单、债券基准、仓位映射表、路径常量
│   ├── store.py                    # SQLite schema + upsert + 查询
│   ├── metrics.py                  # 纯函数指标计算
│   ├── sources/
│   │   ├── __init__.py
│   │   ├── base.py                 # SourceResult 数据类 + 通用 HTTP helper
│   │   ├── csindex.py              # S5/S7：index-perf(PE+行情) + indicator.xls
│   │   ├── chinabond.py            # S1：中债收益率曲线
│   │   ├── danjuan.py              # S4/S6：PE 周频 + 估值快照
│   │   └── legulegu.py             # S2/S3/股息率：股债利差 + 指数PE + 市场股息率
│   ├── pipeline.py                 # 抓取→落库→算指标→导出 snapshot.json
│   ├── server.py                   # FastAPI 应用与路由
│   └── cli.py                      # update / serve / export / backfill
├── web/
│   ├── index.html
│   ├── style.css
│   ├── app.js
│   └── vendor/echarts.min.js
├── scripts/
│   ├── install_launchd.sh
│   └── com.xquant.update.plist
├── tests/
│   ├── test_config.py
│   ├── test_store.py
│   ├── test_metrics.py
│   ├── test_sources.py
│   ├── test_pipeline.py
│   └── test_server.py
├── data/                           # market.db + snapshot.json（git 跟踪）
├── docs/superpowers/{specs,plans}/
└── .github/workflows/update.yml
```

---

### Task 1: 项目骨架与配置

**Files:**
- Create: `pyproject.toml`
- Create: `requirements.txt`
- Create: `xquant/__init__.py`
- Create: `xquant/config.py`
- Create: `tests/test_config.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `xquant.config.INDEXES: list[IndexSpec]`
  - `xquant.config.IndexSpec(code, name, group, danjuan_code, legulegu_symbol, has_csindex)`
  - `xquant.config.BOND_BENCHMARKS: list[BondBenchmark]`（字段 `key, label, curve, tenor`）
  - `xquant.config.ALLOCATION_MAP: list[AllocationBand]`（字段 `max_pct, equity_min, equity_max`）
  - `xquant.config.DEFAULT_BOND_BENCHMARK = "bond10y"`
  - `xquant.config.PERCENTILE_WINDOWS = {"3y": 1095, "5y": 1825, "10y": 3650, "all": None}`
  - `xquant.config.DB_PATH`, `xquant.config.SNAPSHOT_PATH`, `xquant.config.WEB_DIR`
  - `xquant.config.index_by_code(code) -> IndexSpec`
  - `xquant.config.allocation_advice(pct) -> tuple[int, int] | None`（供 metrics/服务复用）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_config.py`：

```python
import pytest

from xquant import config


def test_index_codes_are_unique_and_six_digits():
    codes = [i.code for i in config.INDEXES]
    assert len(codes) == len(set(codes))
    for c in codes:
        assert len(c) == 6 and c.isdigit(), c


def test_primary_indexes_present():
    required = {"000300", "000905", "000852", "000985", "000016", "000688", "399006", "000922"}
    assert required <= {i.code for i in config.INDEXES}


def test_default_benchmark_exists():
    assert config.DEFAULT_BOND_BENCHMARK in {b.key for b in config.BOND_BENCHMARKS}


def test_allocation_map_is_monotonic_and_covers_full_range():
    bands = config.ALLOCATION_MAP
    assert bands[0].max_pct == 0 or bands[0].max_pct <= 10
    assert bands[-1].max_pct >= 90
    for a, b in zip(bands, bands[1:]):
        assert a.max_pct < b.max_pct
        assert a.equity_min >= b.equity_max  # 分位越高建议仓位越低


def test_allocation_advice_returns_none_out_of_range():
    assert config.allocation_advice(-1) is None
    assert config.allocation_advice(101) is None


def test_allocation_advice_maps_band():
    band = config.ALLOCATION_MAP[2]
    mid = (band.max_pct + 10) / 2
    lo, hi = config.allocation_advice(mid)
    assert (lo, hi) == (band.equity_min, band.equity_max)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xquant'`

- [ ] **Step 3: 实现 config.py**

创建 `xquant/__init__.py`：

```python
__version__ = "0.1.0"
```

创建 `xquant/config.py`：

```python
"""全局配置：指数清单、债券基准、仓位映射表。

所有口径决定都集中在本文件，改这里就能换基准/换指数/换仓位规则。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "market.db"
SNAPSHOT_PATH = DATA_DIR / "snapshot.json"
WEB_DIR = ROOT / "web"

# 最小分位样本数，低于此值分位返回 None
MIN_PERCENTILE_SAMPLES = 60


@dataclass(frozen=True)
class IndexSpec:
    code: str
    name: str
    group: str
    danjuan_code: str | None = None
    legulegu_symbol: str | None = None
    has_csindex: bool = True


@dataclass(frozen=True)
class BondBenchmark:
    key: str
    label: str
    curve: str
    tenor: str


@dataclass(frozen=True)
class AllocationBand:
    max_pct: float
    equity_min: int
    equity_max: int


INDEXES: list[IndexSpec] = [
    IndexSpec("000300", "沪深300", "宽基", "SH000300", "沪深300"),
    IndexSpec("000905", "中证500", "宽基", "SH000905", "中证500"),
    IndexSpec("000852", "中证1000", "宽基", "SH000852", "中证1000"),
    IndexSpec("000985", "中证全指", "全市场", None, None),
    IndexSpec("000016", "上证50", "宽基", "SH000016", "上证50"),
    IndexSpec("000688", "科创50", "成长", "SH000688", None),
    IndexSpec("399006", "创业板指", "成长", "SZ399006", None, has_csindex=False),
    IndexSpec("000922", "中证红利", "红利", "SH000922", None),
    IndexSpec("000015", "上证红利", "红利", "SH000015", "上证红利"),
    IndexSpec("000906", "中证800", "宽基", "SH000906", "中证800"),
]

# 乐咕乐股指数 PE 的 symbol → 中证代码映射（乐咕只支持部分指数）
LEGULEGU_SYMBOL_TO_CODE = {i.legulegu_symbol: i.code for i in INDEXES if i.legulegu_symbol}

BOND_BENCHMARKS: list[BondBenchmark] = [
    BondBenchmark("bond10y", "10年期国债", "中债国债收益率曲线", "10年"),
    BondBenchmark("bond30y", "30年期国债", "中债国债收益率曲线", "30年"),
    BondBenchmark("bond5y", "5年期国债", "中债国债收益率曲线", "5年"),
    BondBenchmark("aaa3y", "AAA中短期票据3年", "中债中短期票据收益率曲线(AAA)", "3年"),
    BondBenchmark("aaa5y", "AAA中短期票据5年", "中债中短期票据收益率曲线(AAA)", "5年"),
]

DEFAULT_BOND_BENCHMARK = "bond10y"

PERCENTILE_WINDOWS: dict[str, int | None] = {"3y": 1095, "5y": 1825, "10y": 3650, "all": None}

# 权益仓位参考映射表（按 ERP 分位从低到高），可自行调整
ALLOCATION_MAP: list[AllocationBand] = [
    AllocationBand(10, 80, 100),
    AllocationBand(30, 60, 80),
    AllocationBand(70, 40, 60),
    AllocationBand(90, 20, 40),
    AllocationBand(100, 0, 20),
]


def index_by_code(code: str) -> IndexSpec | None:
    for spec in INDEXES:
        if spec.code == code:
            return spec
    return None


def benchmark_by_key(key: str) -> BondBenchmark | None:
    for b in BOND_BENCHMARKS:
        if b.key == key:
            return b
    return None


def allocation_advice(pct: float | None) -> tuple[int, int] | None:
    """ERP 分位 → 建议权益仓位区间 (下限%, 上限%)。分位为 None 或越界返回 None。"""
    if pct is None:
        return None
    if pct < 0 or pct > 100:
        return None
    for band in ALLOCATION_MAP:
        if pct <= band.max_pct:
            return (band.equity_min, band.equity_max)
    return None
```

注意 `ALLOCATION_MAP` 的分档语义：每档的 `max_pct` 是该档**上界**，且档内 equity 区间从高到低排列。`allocation_advice(5)` → 第一档（<=10）→ (80,100)；`allocation_advice(50)` → 第三档（<=70）→ (40,60)。测试 `test_allocation_map_is_monotonic_and_covers_full_range` 中 `a.equity_min >= b.equity_max` 对 (80,100)→(60,80)→(40,60)→(20,40)→(0,20) 成立。

创建 `pyproject.toml`：

```toml
[project]
name = "xquant"
version = "0.1.0"
description = "中国 A 股股债性价比 / 格雷厄姆指数仪表盘"
requires-python = ">=3.11"
dependencies = [
    "akshare>=1.19",
    "fastapi>=0.115",
    "uvicorn>=0.30",
    "pandas>=3.0",
    "numpy>=2.0",
    "requests>=2.32",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "httpx>=0.27"]

[tool.setuptools.packages.find]
include = ["xquant*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

创建 `requirements.txt`：

```
akshare>=1.19
fastapi>=0.115
uvicorn>=0.30
pandas>=3.0
numpy>=2.0
requests>=2.32
pytest>=8.0
httpx>=0.27
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
git add pyproject.toml requirements.txt xquant/__init__.py xquant/config.py tests/test_config.py
git commit -m "feat: 项目骨架与全局配置"
```

---

### Task 2: SQLite 存储层

**Files:**
- Create: `xquant/store.py`
- Create: `tests/test_store.py`

**Interfaces:**
- Consumes: `xquant.config.DB_PATH`
- Produces:
  - `store.connect(path: str | Path) -> sqlite3.Connection`
  - `store.init_db(conn) -> None`
  - `store.upsert(conn, table: str, rows: list[dict]) -> int`（返回写入行数；`INSERT OR REPLACE`）
  - `store.upsert_bond_yield(conn, rows: list[dict]) -> int`（列 curve/date/tenor/yield）
  - `store.upsert_valuation(conn, rows: list[dict]) -> int`（列 index_code/date/source/pe/pe_total_shares/pe_calc_shares/pb/dividend_yield/dividend_yield_total_shares）
  - `store.upsert_price(conn, rows: list[dict]) -> int`（列 index_code/date/close/source）
  - `store.upsert_metric(conn, rows: list[dict]) -> int`（列 index_code/date/metric/value/freq/source）
  - `store.record_quality(conn, source, status, rows, message, duration_ms) -> None`
  - `store.fetch_metric(conn, index_code, metric, freq=None) -> list[tuple[str, float]]`（按日期升序）
  - `store.fetch_bond_yield(conn, curve, tenor, start=None, end=None) -> list[tuple[str, float]]`
  - `store.fetch_valuation(conn, index_code, source) -> list[dict]`
  - `store.fetch_prices(conn, index_code) -> list[tuple[str, float]]`
  - `store.latest_quality(conn) -> list[dict]`
  - `store.set_meta(conn, key, value) / store.get_meta(conn, key, default=None)`
  - `store.trading_days(conn, start=None, end=None) -> list[str]`（来自 bond_yield 表的日期，作为交易日历）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_store.py`：

```python
import sqlite3

from xquant import store


def make_conn():
    conn = store.connect(":memory:")
    store.init_db(conn)
    return conn


def test_upsert_is_idempotent():
    conn = make_conn()
    rows = [{"index_code": "000300", "date": "2026-10-21", "source": "csindex",
             "pe": 12.77, "pe_total_shares": 13.93, "pe_calc_shares": 15.47,
             "pb": None, "dividend_yield": 2.83, "dividend_yield_total_shares": None}]
    store.upsert_valuation(conn, rows)
    store.upsert_valuation(conn, rows)
    got = conn.execute("SELECT COUNT(*) FROM index_valuation").fetchone()[0]
    assert got == 1


def test_upsert_updates_existing_row():
    conn = make_conn()
    base = {"index_code": "000300", "date": "2026-10-21", "source": "csindex",
            "pe": 12.77, "pe_total_shares": None, "pe_calc_shares": None,
            "pb": None, "dividend_yield": None, "dividend_yield_total_shares": None}
    store.upsert_valuation(conn, [base])
    store.upsert_valuation(conn, [{**base, "pe": 13.01}])
    rows = store.fetch_valuation(conn, "000300", "csindex")
    assert rows[0]["pe"] == 13.01


def test_fetch_metric_sorted_and_filtered():
    conn = make_conn()
    store.upsert_metric(conn, [
        {"index_code": "000300", "date": "2026-10-20", "metric": "erp", "value": 5.0,
         "freq": "daily", "source": "csindex"},
        {"index_code": "000300", "date": "2026-10-21", "metric": "erp", "value": 5.2,
         "freq": "daily", "source": "csindex"},
        {"index_code": "000905", "date": "2026-10-21", "metric": "erp", "value": 3.0,
         "freq": "daily", "source": "csindex"},
    ])
    got = store.fetch_metric(conn, "000300", "erp")
    assert got == [("2026-10-20", 5.0), ("2026-10-21", 5.2)]
    only_weekly = store.fetch_metric(conn, "000300", "erp", freq="weekly")
    assert only_weekly == []


def test_bond_yield_roundtrip():
    conn = make_conn()
    store.upsert_bond_yield(conn, [
        {"curve": "中债国债收益率曲线", "date": "2026-10-21", "tenor": "10年", "yield": 1.68},
    ])
    assert store.fetch_bond_yield(conn, "中债国债收益率曲线", "10年") == [("2026-10-21", 1.68)]
    assert store.trading_days(conn) == ["2026-10-21"]


def test_quality_and_meta():
    conn = make_conn()
    store.record_quality(conn, "csindex", "ok", 5293, "", 1200)
    store.set_meta(conn, "last_run", "2026-10-21T16:30:00")
    q = store.latest_quality(conn)
    assert q[0]["source"] == "csindex" and q[0]["status"] == "ok"
    assert store.get_meta(conn, "last_run") == "2026-10-21T16:30:00"
    assert store.get_meta(conn, "missing", "x") == "x"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xquant.store'`

- [ ] **Step 3: 实现 store.py**

创建 `xquant/store.py`：

```python
"""SQLite 持久层：建表、幂等写入、查询。

所有写入走 INSERT OR REPLACE，重复跑批不会产生重复行。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable, Sequence

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


def upsert_bond_yield(conn, rows): return _upsert(conn, "bond_yield", rows)
def upsert_valuation(conn, rows): return _upsert(conn, "index_valuation", rows)
def upsert_price(conn, rows): return _upsert(conn, "index_price", rows)
def upsert_metric(conn, rows): return _upsert(conn, "metric_series", rows)


def record_quality(conn, source: str, status: str, rows: int, message: str, duration_ms: int) -> None:
    from datetime import datetime, timezone
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_store.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add xquant/store.py tests/test_store.py
git commit -m "feat: SQLite 存储层"
```

---

### Task 3: 指标计算（纯函数）

**Files:**
- Create: `xquant/metrics.py`
- Create: `tests/test_metrics.py`

**Interfaces:**
- Consumes: `xquant.config`（`MIN_PERCENTILE_SAMPLES`、`ALLOCATION_MAP`、`allocation_advice`）
- Produces:
  - `metrics.graham_index(pe: float) -> float`（`1/pe*100`）
  - `metrics.erp(pe: float, bond_yield_pct: float) -> float`（`1/pe*100 - bond_yield_pct`）
  - `metrics.dividend_spread(dividend_yield_pct: float, bond_yield_pct: float) -> float`
  - `metrics.percentile_rank(values: Sequence[float], value: float, min_samples: int = MIN_PERCENTILE_SAMPLES) -> float | None`
  - `metrics.percentile_series(values: Sequence[float], window: int | None, min_samples: int = ...) -> list[float | None]`
  - `metrics.temperature(pct: float | None) -> str`（`便宜/偏低/中性/偏贵/很贵`）
  - `metrics.build_daily_series(obs: Sequence[tuple[str, float]], days: Sequence[str]) -> list[tuple[str, float]]`（asof 前值填充；obs 为 (观测日, 值)，days 为交易日序列；返回 (日期, 值)）
  - `metrics.merge_bond(pe_series, bond_series) -> list[tuple[str, float]]`（按日期 inner join）
  - `metrics.style_signal(spread_pct: float | None) -> str`（`大盘占优/小盘占优/均衡`）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_metrics.py`：

```python
import pytest

from xquant import metrics


def test_graham_index_and_erp():
    assert metrics.graham_index(10) == pytest.approx(10.0)
    assert metrics.erp(10, 2.0) == pytest.approx(8.0)


def test_erp_with_negative_pe_is_none():
    assert metrics.erp(0, 2.0) is None
    assert metrics.erp(-5, 2.0) is None


def test_dividend_spread():
    assert metrics.dividend_spread(4.5, 1.7) == pytest.approx(2.8)


def test_percentile_rank_bounds():
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert metrics.percentile_rank(vals, 5.0, min_samples=5) == pytest.approx(90.0)
    assert metrics.percentile_rank(vals, 1.0, min_samples=5) == pytest.approx(10.0)
    assert metrics.percentile_rank(vals, 3.0, min_samples=5) == pytest.approx(50.0)


def test_percentile_rank_insufficient_sample():
    assert metrics.percentile_rank([1.0, 2.0], 1.5) is None


def test_percentile_series_window_limits():
    values = list(range(100))
    out = metrics.percentile_series(values, window=10, min_samples=2)
    assert len(out) == 100
    assert out[0] is None  # 窗口内只有 1 个样本，不足 min_samples
    assert out[1] == pytest.approx(75.0)  # 窗口 [0,1] 中值 1 → (1+0.5)/2
    assert out[-1] == pytest.approx(99.5)  # 最大值 → (99+0.5)/100


def test_build_daily_series_forward_fills():
    obs = [("2026-01-02", 10.0), ("2026-01-06", 12.0)]
    days = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07"]
    assert metrics.build_daily_series(obs, days) == [
        ("2026-01-02", 10.0), ("2026-01-05", 10.0),
        ("2026-01-06", 12.0), ("2026-01-07", 12.0),
    ]


def test_build_daily_series_ignores_future_observations():
    obs = [("2026-01-02", 10.0), ("2026-01-06", 12.0)]
    days = ["2026-01-02", "2026-01-03"]
    assert metrics.build_daily_series(obs, days) == [("2026-01-02", 10.0), ("2026-01-03", 10.0)]


def test_merge_bond_inner_joins():
    pe = [("2026-01-02", 10.0), ("2026-01-05", 11.0)]
    bond = [("2026-01-02", 2.0)]
    assert metrics.merge_bond(pe, bond) == [("2026-01-02", 10.0, 2.0)]


def test_temperature_bands():
    assert metrics.temperature(5) == "便宜"
    assert metrics.temperature(30) == "偏低"
    assert metrics.temperature(50) == "中性"
    assert metrics.temperature(75) == "偏贵"
    assert metrics.temperature(95) == "很贵"
    assert metrics.temperature(None) == "未知"


def test_style_signal():
    assert metrics.style_signal(80) == "小盘占优"
    assert metrics.style_signal(20) == "大盘占优"
    assert metrics.style_signal(None) == "未知"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xquant.metrics'`

- [ ] **Step 3: 实现 metrics.py**

创建 `xquant/metrics.py`：

```python
"""纯函数指标计算。不做任何 IO，便于单测。"""
from __future__ import annotations

from bisect import bisect_right
from typing import Sequence

from xquant.config import MIN_PERCENTILE_SAMPLES


def graham_index(pe: float | None) -> float | None:
    """格雷厄姆指数分子部分：股权收益率倒数 1/PE × 100（%）。"""
    if pe is None or pe <= 0:
        return None
    return 1.0 / pe * 100.0


def erp(pe: float | None, bond_yield_pct: float | None) -> float | None:
    """格雷厄姆指数 / 股权风险溢价 = 1/PE×100 − 债券收益率(%)。"""
    g = graham_index(pe)
    if g is None or bond_yield_pct is None:
        return None
    return g - bond_yield_pct


def dividend_spread(dividend_yield_pct: float | None, bond_yield_pct: float | None) -> float | None:
    """股息率差 = 股息率(%) − 债券收益率(%)。"""
    if dividend_yield_pct is None or bond_yield_pct is None:
        return None
    return dividend_yield_pct - bond_yield_pct


def percentile_rank(values: Sequence[float], value: float | None,
                    min_samples: int = MIN_PERCENTILE_SAMPLES) -> float | None:
    """value 在 values 中的分位（0-100），中位秩法。样本不足返回 None。"""
    if value is None:
        return None
    vals = [v for v in values if v is not None]
    if len(vals) < min_samples:
        return None
    below = sum(1 for v in vals if v < value)
    equal = sum(1 for v in vals if v == value)
    return (below + 0.5 * equal) / len(vals) * 100.0


def percentile_series(values: Sequence[float], window: int | None,
                      min_samples: int = MIN_PERCENTILE_SAMPLES) -> list[float | None]:
    """滚动窗口分位序列。window=None 表示全历史。"""
    out: list[float | None] = []
    for i, v in enumerate(values):
        if v is None:
            out.append(None)
            continue
        lo = 0 if window is None else max(0, i - window + 1)
        out.append(percentile_rank(values[lo:i + 1], v, min_samples=min_samples))
    return out


def temperature(pct: float | None) -> str:
    if pct is None:
        return "未知"
    if pct <= 20:
        return "便宜"
    if pct <= 40:
        return "偏低"
    if pct <= 60:
        return "中性"
    if pct <= 80:
        return "偏贵"
    return "很贵"


def build_daily_series(obs: Sequence[tuple[str, float]], days: Sequence[str]) -> list[tuple[str, float]]:
    """把稀疏观测（前值填充）摊到交易日序列上。obs 必须按日期升序。"""
    if not obs:
        return []
    obs_dates = [d for d, _ in obs]
    out: list[tuple[str, float]] = []
    idx = 0
    current: float | None = None
    for day in days:
        while idx < len(obs) and obs_dates[idx] <= day:
            current = obs[idx][1]
            idx += 1
        if current is not None:
            out.append((day, current))
    return out


def merge_bond(pe_series: Sequence[tuple[str, float]],
               bond_series: Sequence[tuple[str, float]]) -> list[tuple[str, float, float]]:
    """PE 序列与债券收益率序列按日期内连接。"""
    bond_map = dict(bond_series)
    out = []
    for d, pe in pe_series:
        y = bond_map.get(d)
        if y is not None:
            out.append((d, pe, y))
    return out


def style_signal(spread_pct: float | None) -> str:
    """风格利差分位：正=小盘占优，负=大盘占优。"""
    if spread_pct is None:
        return "未知"
    if spread_pct >= 60:
        return "小盘占优"
    if spread_pct <= 40:
        return "大盘占优"
    return "均衡"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_metrics.py -v`
Expected: PASS（12 passed）

- [ ] **Step 5: 提交**

```bash
git add xquant/metrics.py tests/test_metrics.py
git commit -m "feat: 指标计算纯函数"
```

---

### Task 4: 数据源 · 中证指数（PE 日频 + 估值快照 + 行情）

**Files:**
- Create: `xquant/sources/__init__.py`
- Create: `xquant/sources/base.py`
- Create: `xquant/sources/csindex.py`
- Create: `tests/test_sources.py`

**Interfaces:**
- Consumes: `xquant.config.INDEXES`
- Produces:
  - `xquant.sources.base.SourceResult(source: str, ok: bool, rows: int, message: str, duration_ms: int)`
  - `xquant.sources.base.http_get_json(url: str, params: dict | None = None, timeout: int = 30) -> Any`（带 UA、失败抛异常）
  - `xquant.sources.base.http_get_bytes(url: str, timeout: int = 30) -> bytes`
  - `xquant.sources.csindex.parse_perf(payload: dict) -> list[dict]`（→ `{"index_code","date","close","pe"}`，`peg` 字段映射为 `pe`；date 转 `YYYY-MM-DD`；丢弃 peg 为空的行）
  - `xquant.sources.csindex.parse_indicator(content: bytes, index_code: str) -> list[dict]`（→ `{"index_code","date","source","pe_total_shares","pe_calc_shares","dividend_yield_total_shares","dividend_yield"}`；表头含「市盈率1（总股本）P/E1」等中文，列名以括号前中文为准）
  - `xquant.sources.csindex.fetch_perf(index_code: str, start: str = "20050101", end: str | None = None) -> list[dict]`
  - `xquant.sources.csindex.fetch_indicator(index_code: str) -> list[dict]`
  - `xquant.sources.csindex.fetch_index(index_code: str, start_date: str | None = None) -> dict`（返回 `{"valuation": [...], "perf": [...], "prices": [...]}`，其中 perf 同时产出 pe 与 close）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_sources.py`（本任务只测解析函数，不联网）：

```python
import json

from xquant.sources import csindex


PERF_PAYLOAD = {
    "code": "200", "success": True,
    "data": [
        {"tradeDate": "20240102", "indexCode": "000300", "close": 3386.35, "peg": 11.2},
        {"tradeDate": "20240103", "indexCode": "000300", "close": 3378.30, "peg": None},
    ],
}


def test_parse_perf_maps_peg_to_pe_and_skips_null():
    rows = csindex.parse_perf(PERF_PAYLOAD)
    assert rows == [{"index_code": "000300", "date": "2024-01-02", "close": 3386.35, "pe": 11.2}]


def test_parse_perf_accepts_empty():
    assert csindex.parse_perf({"data": []}) == []


def test_parse_indicator_reads_xls_bytes(tmp_path):
    import pandas as pd
    df = pd.DataFrame({
        "日期Date": ["20261021", "20261020"],
        "指数代码Index Code": ["000300", "000300"],
        "市盈率1（总股本）P/E1": [13.93, 14.08],
        "市盈率2（计算用股本）P/E2": [15.47, 15.62],
        "股息率1（总股本）D/P1": [2.83, 2.80],
        "股息率2（计算用股本）D/P2": [2.64, 2.61],
    })
    path = tmp_path / "000300indicator.xls"
    df.to_excel(path, index=False)
    rows = csindex.parse_indicator(path.read_bytes(), "000300")
    assert rows[0]["date"] == "2026-10-21"
    assert rows[0]["pe_total_shares"] == 13.93
    assert rows[0]["pe_calc_shares"] == 15.47
    assert rows[0]["dividend_yield_total_shares"] == 2.83
    assert rows[0]["dividend_yield"] == 2.64
    assert rows[0]["source"] == "csindex"


def test_parse_indicator_handles_missing_columns(tmp_path):
    import pandas as pd
    df = pd.DataFrame({"日期Date": ["20261021"], "指数代码Index Code": ["000300"]})
    path = tmp_path / "x.xls"
    df.to_excel(path, index=False)
    rows = csindex.parse_indicator(path.read_bytes(), "000300")
    assert rows[0]["pe_total_shares"] is None
    assert rows[0]["dividend_yield"] is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_sources.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xquant.sources'`

- [ ] **Step 3: 实现 base.py**

创建 `xquant/sources/__init__.py`（空文件）。

创建 `xquant/sources/base.py`：

```python
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
```

- [ ] **Step 4: 实现 csindex.py**

创建 `xquant/sources/csindex.py`：

```python
"""中证指数官方数据源。

- index-perf：日频行情 + 近四季滚动市盈率(字段名 peg)，2005 年至今
- indicator.xls：近 20 日的市盈率/股息率（含总股本与计算用股本两种口径）
"""
from __future__ import annotations

import io
from datetime import date

from xquant.sources.base import http_get_bytes, http_get_json

PERF_URL = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
INDICATOR_URL = ("https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/"
                 "autofile/indicator/{code}indicator.xls")


def _norm_date(value: str) -> str:
    v = str(value).strip()
    if len(v) == 8 and v.isdigit():
        return f"{v[:4]}-{v[4:6]}-{v[6:]}"
    return v


def parse_perf(payload: dict) -> list[dict]:
    rows: list[dict] = []
    for item in payload.get("data") or []:
        pe = item.get("peg")
        if pe is None:
            continue
        rows.append({
            "index_code": item.get("indexCode"),
            "date": _norm_date(item.get("tradeDate")),
            "close": item.get("close"),
            "pe": float(pe),
        })
    return rows


def _pick(cols, keyword):
    for c in cols:
        if keyword in str(c):
            return c
    return None


def parse_indicator(content: bytes, index_code: str) -> list[dict]:
    import pandas as pd
    df = pd.read_excel(io.BytesIO(content))
    cols = list(df.columns)
    c_date = _pick(cols, "日期")
    c_pe1 = _pick(cols, "市盈率1")
    c_pe2 = _pick(cols, "市盈率2")
    c_dp1 = _pick(cols, "股息率1")
    c_dp2 = _pick(cols, "股息率2")
    rows: list[dict] = []
    for _, r in df.iterrows():
        raw_date = r[c_date] if c_date else None
        if raw_date is None or (isinstance(raw_date, float) and pd.isna(raw_date)):
            continue
        d = _norm_date(str(int(raw_date)) if not isinstance(raw_date, str) else raw_date)
        rows.append({
            "index_code": index_code,
            "date": d,
            "source": "csindex",
            "pe_total_shares": float(r[c_pe1]) if c_pe1 and pd.notna(r[c_pe1]) else None,
            "pe_calc_shares": float(r[c_pe2]) if c_pe2 and pd.notna(r[c_pe2]) else None,
            "dividend_yield_total_shares": float(r[c_dp1]) if c_dp1 and pd.notna(r[c_dp1]) else None,
            "dividend_yield": float(r[c_dp2]) if c_dp2 and pd.notna(r[c_dp2]) else None,
        })
    return rows


def fetch_perf(index_code: str, start: str = "20050101", end: str | None = None) -> list[dict]:
    end = end or date.today().strftime("%Y%m%d")
    payload = http_get_json(PERF_URL, params={
        "indexCode": index_code, "startDate": start, "endDate": end}, timeout=60)
    return parse_perf(payload)


def fetch_indicator(index_code: str) -> list[dict]:
    content = http_get_bytes(INDICATOR_URL.format(code=index_code), timeout=60)
    return parse_indicator(content, index_code)


def fetch_index(index_code: str, start_date: str | None = None) -> dict:
    """一次抓取某指数的全部可用数据。

    返回 {"valuation": [...], "perf": [...], "prices": [...]}：
      valuation → index_valuation 行（source=csindex）
      perf      → 日频 PE 观测 (date, pe)
      prices    → 日频收盘价 (date, close)
    """
    start = (start_date or "20050101").replace("-", "")
    payload = http_get_json(PERF_URL, params={
        "indexCode": index_code, "startDate": start,
        "endDate": date.today().strftime("%Y%m%d")}, timeout=90)
    perf_rows = parse_perf(payload)
    prices = [{"index_code": index_code, "date": r["date"], "close": r["close"],
               "source": "csindex"} for r in perf_rows]
    valuation: list[dict] = []
    try:
        valuation = fetch_indicator(index_code)
    except Exception:
        valuation = []
    return {
        "valuation": valuation,
        "perf": [(r["date"], r["pe"]) for r in perf_rows],
        "prices": prices,
    }
```

- [ ] **Step 5: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_sources.py -v`
Expected: PASS（4 passed）

- [ ] **Step 6: 冒烟验证真实抓取**

Run: `.venv/bin/python -c "from xquant.sources import csindex; d=csindex.fetch_index('000300'); print(len(d['perf']), d['perf'][-1], len(d['valuation']), d['valuation'][0])"`
Expected: 打印类似 `5217 ('2026-10-21', 12.77) 20 {...'pe_total_shares': 13.93...}`

- [ ] **Step 7: 提交**

```bash
git add xquant/sources tests/test_sources.py
git commit -m "feat: 中证指数数据源（PE 日频 + 估值快照 + 行情）"
```

---

### Task 5: 数据源 · 中债收益率曲线

**Files:**
- Modify: `xquant/sources/chinabond.py`（新建）
- Modify: `tests/test_sources.py`（追加用例）

**Interfaces:**
- Consumes: `xquant.config.BOND_BENCHMARKS`
- Produces:
  - `xquant.sources.chinabond.parse_yield_curve(df) -> list[dict]`（输入 akshare 的宽表，输出 `{"curve","date","tenor","yield"}`）
  - `xquant.sources.chinabond.fetch_bond_yields(start_date: str, end_date: str | None = None) -> list[dict]`
  - `xquant.sources.chinabond.TENORS = ["3月","6月","1年","3年","5年","7年","10年","30年"]`

- [ ] **Step 1: 追加失败测试**

在 `tests/test_sources.py` 末尾追加：

```python
def test_parse_yield_curve_long_format():
    import pandas as pd
    from xquant.sources import chinabond
    df = pd.DataFrame({
        "曲线名称": ["中债国债收益率曲线", "中债国债收益率曲线"],
        "日期": [pd.Timestamp("2026-10-21"), pd.Timestamp("2026-10-20")],
        "3月": [1.4, 1.41], "10年": [1.68, 1.7], "30年": [1.95, 1.96],
    })
    rows = chinabond.parse_yield_curve(df)
    assert {"curve": "中债国债收益率曲线", "date": "2026-10-21", "tenor": "10年",
            "yield": 1.68} in rows
    assert len(rows) == 4  # 2 天 × 2 个期限
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_sources.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xquant.sources.chinabond'`

- [ ] **Step 3: 实现 chinabond.py**

创建 `xquant/sources/chinabond.py`：

```python
"""中债收益率曲线数据源（通过 akshare bond_china_yield）。"""
from __future__ import annotations

from datetime import date, timedelta

TENORS = ["3月", "6月", "1年", "3年", "5年", "7年", "10年", "30年"]


def parse_yield_curve(df) -> list[dict]:
    rows: list[dict] = []
    for _, r in df.iterrows():
        curve = str(r["曲线名称"]).strip()
        raw_date = r["日期"]
        d = raw_date.strftime("%Y-%m-%d") if hasattr(raw_date, "strftime") else str(raw_date)[:10]
        for tenor in TENORS:
            if tenor not in df.columns:
                continue
            val = r[tenor]
            if val is None or val != val:  # NaN 检查
                continue
            rows.append({"curve": curve, "date": d, "tenor": tenor, "yield": float(val)})
    return rows


def fetch_bond_yields(start_date: str, end_date: str | None = None) -> list[dict]:
    """start_date / end_date 形如 20060101。"""
    import akshare as ak
    end = end or date.today().strftime("%Y%m%d")
    df = ak.bond_china_yield(start_date=start_date, end_date=end)
    return parse_yield_curve(df)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_sources.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 冒烟验证**

Run: `.venv/bin/python -c "from xquant.sources import chinabond; r=chinabond.fetch_bond_yields('20260101'); print(len(r)); print([x for x in r if x['tenor']=='10年'][:2])"`
Expected: 打印行数 > 200，并含 `{'curve': '中债国债收益率曲线', 'date': '2026-01-02', 'tenor': '10年', 'yield': ...}`

- [ ] **Step 6: 提交**

```bash
git add xquant/sources/chinabond.py tests/test_sources.py
git commit -m "feat: 中债收益率曲线数据源"
```

---

### Task 6: 数据源 · 蛋卷（PE 周频 + 估值快照）

**Files:**
- Create: `xquant/sources/danjuan.py`
- Modify: `tests/test_sources.py`

**Interfaces:**
- Consumes: `xquant.config.INDEXES`
- Produces:
  - `xquant.sources.danjuan.normalize_code(code: str | None) -> str`（`SH000300` → `000300`；非 6 位结尾的保留原样）
  - `xquant.sources.danjuan.parse_pe_history(payload: dict) -> list[tuple[str, float]]`（`[("2026-10-20", 12.85), ...]`，日期按 `ts` 毫秒转 Asia/Shanghai）
  - `xquant.sources.danjuan.parse_snapshot(payload: dict) -> list[dict]`（→ `{"index_code","date","source","pe","pb","dividend_yield"}`，index_code 归一化为 6 位中证代码，日期取当天）
  - `xquant.sources.danjuan.fetch_pe_history(danjuan_code: str) -> list[tuple[str, float]]`
  - `xquant.sources.danjuan.fetch_snapshot() -> list[dict]`

- [ ] **Step 1: 追加失败测试**

在 `tests/test_sources.py` 末尾追加：

```python
def test_parse_pe_history():
    from xquant.sources import danjuan
    payload = {"data": {"index_eva_pe_growths": [
        {"pe": 12.85, "ts": 1791465600000},   # 2026-10-06 (UTC 00:00)
        {"pe": 13.10, "ts": 1792070400000},
    ]}}
    rows = danjuan.parse_pe_history(payload)
    assert len(rows) == 2
    assert rows[0][1] == 12.85
    assert rows[0][0].startswith("2026-10")


def test_parse_snapshot():
    from xquant.sources import danjuan
    payload = {"data": {"items": [
        {"index_code": "SH000300", "name": "沪深300", "pe": 12.85, "pb": 1.36,
         "pe_percentile": 0.52, "yeild": 0.0298},
    ]}}
    rows = danjuan.parse_snapshot(payload)
    assert rows[0]["index_code"] == "000300"
    assert rows[0]["pe"] == 12.85
    assert rows[0]["dividend_yield"] == pytest.approx(2.98, abs=0.01)
```

需在 `tests/test_sources.py` 顶部加 `import pytest`。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_sources.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xquant.sources.danjuan'`

- [ ] **Step 3: 实现 danjuan.py**

创建 `xquant/sources/danjuan.py`：

```python
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
    payload = http_get_json(f"{BASE}/index_eva/pe_history/{danjuan_code}", params={"day": "all"}, timeout=40)
    return parse_pe_history(payload)


def fetch_snapshot() -> list[dict]:
    payload = http_get_json(f"{BASE}/index_eva/dj", timeout=40)
    return parse_snapshot(payload)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_sources.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: 冒烟验证**

Run: `.venv/bin/python -c "from xquant.sources import danjuan; r=danjuan.fetch_pe_history('SH000300'); print(len(r), r[0], r[-1]); s=danjuan.fetch_snapshot(); print(len(s), s[0])"`
Expected: 打印约 `517 ('2016-10-21', ...) ('2026-10-20', 12.85)` 与 `63 {...}`

- [ ] **Step 6: 提交**

```bash
git add xquant/sources/danjuan.py tests/test_sources.py
git commit -m "feat: 蛋卷指数估值数据源"
```

---

### Task 7: 数据源 · 乐咕乐股（股债利差 / 指数 PE / 市场股息率）

**Files:**
- Create: `xquant/sources/legulegu.py`
- Modify: `tests/test_sources.py`

**Interfaces:**
- Consumes: `xquant.config.LEGULEGU_SYMBOL_TO_CODE`
- Produces:
  - `xquant.sources.legulegu.parse_ebs(df) -> list[tuple[str, float]]`（日期 → 股债利差(%)，×100）
  - `xquant.sources.legulegu.parse_index_pe(df, index_code: str) -> list[tuple[str, float]]`（用「滚动市盈率」列）
  - `xquant.sources.legulegu.parse_market_gxl(df, code: str) -> list[dict]`（→ `{"index_code","date","source","dividend_yield"}`）
  - `xquant.sources.legulegu.fetch_ebs() -> list[tuple[str, float]]`
  - `xquant.sources.legulegu.fetch_index_pe(symbol: str) -> list[tuple[str, float]]`
  - `xquant.sources.legulegu.fetch_market_gxl(symbol: str) -> list[dict]`
  - `xquant.sources.legulegu.MARKET_GXL = {"MKT_SH": "上证A股", "MKT_SZ": "深证A股", "MKT_GEM": "创业板", "MKT_STAR": "科创板"}`

- [ ] **Step 1: 追加失败测试**

在 `tests/test_sources.py` 末尾追加：

```python
def test_parse_ebs_scales_to_percent():
    import pandas as pd
    from xquant.sources import legulegu
    df = pd.DataFrame({"日期": [pd.Timestamp("2026-10-21")], "沪深300指数": [4111.93],
                       "股债利差": [0.0657], "股债利差均线": [0.0617]})
    rows = legulegu.parse_ebs(df)
    assert rows == [("2026-10-21", pytest.approx(6.57))]


def test_parse_market_gxl():
    import pandas as pd
    from xquant.sources import legulegu
    df = pd.DataFrame({"日期": [pd.Timestamp("2026-10-21")], "股息率": [2.79]})
    rows = legulegu.parse_market_gxl(df, "MKT_SH")
    assert rows[0]["index_code"] == "MKT_SH"
    assert rows[0]["dividend_yield"] == 2.79
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_sources.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xquant.sources.legulegu'`

- [ ] **Step 3: 实现 legulegu.py**

创建 `xquant/sources/legulegu.py`：

```python
"""乐咕乐股数据源（通过 akshare）。

- stock_ebs_lg：沪深300 股债利差日频（1/PE(TTM) − 10Y国债），2006 起
- stock_index_pe_lg：宽基指数 PE 月频长史，2005 起
- stock_a_gxl_lg：市场（上证A股/深证A股/创业板/科创板）股息率日频，2005 起
"""
from __future__ import annotations

MARKET_GXL = {
    "MKT_SH": "上证A股",
    "MKT_SZ": "深证A股",
    "MKT_GEM": "创业板",
    "MKT_STAR": "科创板",
}


def _d(value) -> str:
    return value.strftime("%Y-%m-%d") if hasattr(value, "strftime") else str(value)[:10]


def parse_ebs(df) -> list[tuple[str, float]]:
    rows = []
    for _, r in df.iterrows():
        v = r["股债利差"]
        if v is None or v != v:
            continue
        rows.append((_d(r["日期"]), float(v) * 100))
    rows.sort(key=lambda x: x[0])
    return rows


def parse_index_pe(df, index_code: str) -> list[tuple[str, float]]:
    rows = []
    col = "滚动市盈率" if "滚动市盈率" in df.columns else "静态市盈率"
    for _, r in df.iterrows():
        v = r[col]
        if v is None or v != v or float(v) <= 0:
            continue
        rows.append((_d(r["日期"]), float(v)))
    rows.sort(key=lambda x: x[0])
    return rows


def parse_market_gxl(df, code: str) -> list[dict]:
    rows = []
    for _, r in df.iterrows():
        v = r["股息率"]
        if v is None or v != v:
            continue
        rows.append({"index_code": code, "date": _d(r["日期"]),
                     "source": "legulegu_gxl", "dividend_yield": float(v)})
    rows.sort(key=lambda x: x["date"])
    return rows


def fetch_ebs() -> list[tuple[str, float]]:
    import akshare as ak
    return parse_ebs(ak.stock_ebs_lg())


def fetch_index_pe(symbol: str) -> list[tuple[str, float]]:
    import akshare as ak
    return parse_index_pe(ak.stock_index_pe_lg(symbol=symbol), "")


def fetch_market_gxl(symbol: str) -> list[dict]:
    import akshare as ak
    df = ak.stock_a_gxl_lg(symbol=symbol)
    return parse_market_gxl(df, MARKET_GXL_INV[symbol])


MARKET_GXL_INV = {v: k for k, v in MARKET_GXL.items()}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_sources.py -v`
Expected: PASS（9 passed）

- [ ] **Step 5: 冒烟验证**

Run: `.venv/bin/python -c "from xquant.sources import legulegu; r=legulegu.fetch_ebs(); print(len(r), r[0], r[-1]); g=legulegu.fetch_market_gxl('上证A股'); print(len(g), g[-1])"`
Expected: 打印 `5292 ('2005-01-04', ...) ('2026-10-21', 6.57)` 与 `5292 {...'dividend_yield': 2.79}`

- [ ] **Step 6: 提交**

```bash
git add xquant/sources/legulegu.py tests/test_sources.py
git commit -m "feat: 乐咕乐股数据源"
```

---

### Task 8: 流水线（抓取 → 落库 → 指标 → 导出）

**Files:**
- Create: `xquant/pipeline.py`
- Create: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `xquant.store`、`xquant.metrics`、`xquant.config`、`xquant.sources.*`
- Produces:
  - `pipeline.build_master_pe(conn, index_code: str) -> list[tuple[str, float]]`（合并多源 PE 观测，源优先级 中证 peg > 蛋卷周频 > 乐咕月频，按日期升序，重复日期取高优先级源）
  - `pipeline.compute_metrics(conn, bond_key: str = "bond10y") -> dict`（写 metric_series，返回统计摘要）
  - `pipeline.run_backtest(conn, index_code: str = "000300", bond_key: str = "bond10y") -> dict`（按 ERP 分位映射在股票与债券间切换的规则回测）
  - `pipeline.snapshot_payload(conn, bond_key: str = "bond10y") -> dict`（仪表盘快照数据）
  - `pipeline.export_snapshot(conn, path=None) -> Path`
  - `pipeline.run(conn, bond_key: str = "bond10y", with_network: bool = True, sources: list | None = None) -> dict`（返回 `{"quality": [...], "summary": {...}}`；`with_network=False` 时只重算指标）
  - `pipeline.METRIC_KEYS = {"erp": "erp", "pe": "pe", "dy_spread": "dy_spread", "style": "style_spread"}`

- [ ] **Step 1: 写失败测试**

创建 `tests/test_pipeline.py`：

```python
import pytest

from xquant import pipeline, store


def seeded_conn():
    conn = store.connect(":memory:")
    store.init_db(conn)
    store.upsert_bond_yield(conn, [
        {"curve": "中债国债收益率曲线", "date": f"2026-01-{d:02d}", "tenor": "10年",
         "yield": 1.7} for d in range(2, 12)
    ])
    store.upsert_valuation(conn, [
        {"index_code": "000300", "date": f"2026-01-{d:02d}", "source": "csindex",
         "pe": 12.0, "pe_total_shares": None, "pe_calc_shares": None, "pb": None,
         "dividend_yield": 2.5, "dividend_yield_total_shares": None}
        for d in range(2, 12)
    ])
    store.upsert_valuation(conn, [
        {"index_code": "000905", "date": f"2026-01-{d:02d}", "source": "csindex",
         "pe": 20.0, "pe_total_shares": None, "pe_calc_shares": None, "pb": None,
         "dividend_yield": 1.5, "dividend_yield_total_shares": None}
        for d in range(2, 12)
    ])
    store.upsert_valuation(conn, [
        {"index_code": "000852", "date": f"2026-01-{d:02d}", "source": "csindex",
         "pe": 30.0, "pe_total_shares": None, "pe_calc_shares": None, "pb": None,
         "dividend_yield": 1.2, "dividend_yield_total_shares": None}
        for d in range(2, 12)
    ])
    return conn


def test_build_master_pe_prefers_csindex_and_keeps_legulegu_history():
    conn = seeded_conn()
    store.upsert_valuation(conn, [
        {"index_code": "000300", "date": "2025-12-01", "source": "legulegu",
         "pe": 11.0, "pe_total_shares": None, "pe_calc_shares": None, "pb": None,
         "dividend_yield": None, "dividend_yield_total_shares": None},
    ])
    rows = pipeline.build_master_pe(conn, "000300")
    assert rows[0] == ("2025-12-01", 11.0)
    assert rows[1][0] == "2026-01-02" and rows[1][1] == 12.0
    assert len(rows) == 11  # 1 条历史 + 10 条日频


def test_compute_metrics_writes_erp_and_percentiles():
    conn = seeded_conn()
    pipeline.compute_metrics(conn)
    erp = store.fetch_metric(conn, "000300", "erp")
    # PE=12 → 8.3333%，减 1.7% → 6.6333
    assert erp[0][1] == pytest.approx(6.6333, abs=1e-4)
    assert store.fetch_metric(conn, "000300", "erp_pct_10y") == []  # 样本不足不写


def test_compute_metrics_writes_dividend_spread():
    conn = seeded_conn()
    pipeline.compute_metrics(conn)
    ds = store.fetch_metric(conn, "000300", "dy_spread")
    assert ds[0][1] == pytest.approx(0.8, abs=1e-9)  # 2.5 - 1.7


def test_run_without_network_recomputes_and_exports(tmp_path):
    conn = seeded_conn()
    out = tmp_path / "snapshot.json"
    result = pipeline.run(conn, with_network=False, snapshot_path=out)
    assert result["summary"]["indices"] >= 3
    assert out.exists()
    import json
    data = json.loads(out.read_text())
    assert data["generated_at"]
    assert any(i["code"] == "000300" for i in data["indexes"])
    assert data["indexes"][0]["erp"] is not None


def test_source_failure_is_isolated():
    conn = seeded_conn()

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
        result = pipeline.run(conn, with_network=True)
    finally:
        pipeline.SOURCES = pipeline.default_sources()
    statuses = {q["source"]: q["status"] for q in result["quality"]}
    assert statuses["boom"] == "fail"
    assert statuses["good"] == "ok"


def test_run_backtest_computes_stats():
    import datetime as dt
    conn = store.connect(":memory:")
    store.init_db(conn)
    days = [(dt.date(2024, 1, 1) + dt.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(400)]
    store.upsert_bond_yield(conn, [
        {"curve": "中债国债收益率曲线", "date": d, "tenor": "10年", "yield": 1.8} for d in days])
    store.upsert_valuation(conn, [
        {"index_code": "000300", "date": d, "source": "csindex", "pe": 12.0,
         "pe_total_shares": None, "pe_calc_shares": None, "pb": None,
         "dividend_yield": None, "dividend_yield_total_shares": None} for d in days])
    store.upsert_price(conn, [
        {"index_code": "000300", "date": d, "close": 4000.0, "source": "csindex"} for d in days])
    pipeline.compute_metrics(conn)
    bt = pipeline.run_backtest(conn)
    assert bt["available"] is True
    assert bt["strategy"]["cagr"] is not None
    assert bt["equity_only"]["cagr"] is not None
    assert bt["period"][0] < bt["period"][1]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xquant.pipeline'`

- [ ] **Step 3: 实现 pipeline.py**

创建 `xquant/pipeline.py`：

```python
"""流水线：抓取 → 落库 → 计算指标 → 导出快照。

设计要点：
- 每个数据源独立 try/except，失败只记录不中断（降级沿用旧值）
- PE 主序列按源优先级合并：中证 peg(官方TTM) > 蛋卷周频 > 乐咕月频
- 指标全部由 metrics 纯函数计算，落 metric_series
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

from xquant import metrics, store
from xquant.config import (ALLOCATION_MAP, BOND_BENCHMARKS, DEFAULT_BOND_BENCHMARK,
                            INDEXES, LEGULEGU_SYMBOL_TO_CODE, PERCENTILE_WINDOWS,
                            SNAPSHOT_PATH, allocation_advice, benchmark_by_key)
from xquant.sources import chinabond, csindex, danjuan, legulegu

CST = timezone(timedelta(hours=8))

# PE 源优先级（数字越小越优先）
PE_SOURCE_PRIORITY = {"csindex": 0, "danjuan": 1, "legulegu": 2}


class Source:
    """数据源适配器接口。子类实现 fetch()。"""

    source = "base"

    def fetch(self, *args, **kwargs) -> dict:  # pragma: no cover - 接口声明
        raise NotImplementedError


class CsindexSource(Source):
    source = "csindex"

    def fetch(self, index_code: str, start_date: str | None = None) -> dict:
        return csindex.fetch_index(index_code, start_date=start_date)


class DanjuanSource(Source):
    source = "danjuan"

    def fetch(self, index_code: str) -> dict:
        out = {"valuation": [], "perf": [], "prices": []}
        spec = next((i for i in INDEXES if i.code == index_code), None)
        if spec and spec.danjuan_code:
            for d, pe in danjuan.fetch_pe_history(spec.danjuan_code):
                out["valuation"].append({
                    "index_code": index_code, "date": d, "source": "danjuan",
                    "pe": pe, "pe_total_shares": None, "pe_calc_shares": None,
                    "pb": None, "dividend_yield": None,
                    "dividend_yield_total_shares": None,
                })
        return out


class LeguleguSource(Source):
    source = "legulegu"

    def fetch(self, index_code: str) -> dict:
        out = {"valuation": [], "perf": [], "prices": []}
        symbol = LEGULEGU_SYMBOL_TO_CODE.get(index_code)
        if symbol:
            for d, pe in legulegu.fetch_index_pe(symbol):
                out["valuation"].append({
                    "index_code": index_code, "date": d, "source": "legulegu",
                    "pe": pe, "pe_total_shares": None, "pe_calc_shares": None,
                    "pb": None, "dividend_yield": None,
                    "dividend_yield_total_shares": None,
                })
        return out


def default_sources() -> list[Source]:
    return [CsindexSource(), DanjuanSource(), LeguleguSource()]


SOURCES = default_sources()


def build_master_pe(conn, index_code: str) -> list[tuple[str, float]]:
    """合并各源 PE 观测为单一升序序列；同一天取优先级最高的源。"""
    rows = conn.execute(
        "SELECT date, pe, source FROM index_valuation WHERE index_code=? AND pe IS NOT NULL",
        (index_code,)).fetchall()
    if not rows:
        return []
    best: dict[str, tuple[int, float]] = {}
    for r in rows:
        pri = PE_SOURCE_PRIORITY.get(r["source"], 9)
        cur = best.get(r["date"])
        if cur is None or pri < cur[0]:
            best[r["date"]] = (pri, float(r["pe"]))
    return sorted((d, v[1]) for d, v in best.items())


def _dividend_series(conn, index_code: str) -> list[tuple[str, float]]:
    rows = conn.execute(
        "SELECT date, dividend_yield FROM index_valuation WHERE index_code=? AND dividend_yield IS NOT NULL",
        (index_code,)).fetchall()
    return sorted((r["date"], float(r["dividend_yield"])) for r in rows)


def compute_metrics(conn, bond_key: str = DEFAULT_BOND_BENCHMARK) -> dict:
    """计算并写入全部指标序列。"""
    bench = benchmark_by_key(bond_key)
    if bench is None:
        raise ValueError(f"unknown bond benchmark: {bond_key}")
    bond = store.fetch_bond_yield(conn, bench.curve, bench.tenor)
    bond_map = dict(bond)
    days = store.trading_days(conn)
    if not days:
        return {"indices": 0, "bond": bench.key}

    for spec in INDEXES:
        pe_obs = build_master_pe(conn, spec.code)
        if not pe_obs:
            continue
        pe_daily = metrics.build_daily_series(pe_obs, days)
        erp_rows = []
        pe_rows = []
        for d, pe in pe_daily:
            y = bond_map.get(d)
            if y is None:
                continue
            value = metrics.erp(pe, y)
            if value is None:
                continue
            pe_rows.append({"index_code": spec.code, "date": d, "metric": "pe",
                            "value": pe, "freq": "daily", "source": "master"})
            erp_rows.append({"index_code": spec.code, "date": d, "metric": "erp",
                             "value": value, "freq": "daily", "source": "master"})
        store.upsert_metric(conn, pe_rows)
        store.upsert_metric(conn, erp_rows)

        erp_values = [r["value"] for r in erp_rows]
        for wname, wsize in PERCENTILE_WINDOWS.items():
            pcts = metrics.percentile_series(erp_values, wsize)
            store.upsert_metric(conn, [
                {"index_code": spec.code, "date": r["date"], "metric": f"erp_pct_{wname}",
                 "value": p, "freq": "daily", "source": "master"}
                for r, p in zip(erp_rows, pcts) if p is not None
            ])

        dy_rows = []
        for d, dy in _dividend_series(conn, spec.code):
            y = bond_map.get(d)
            if y is None:
                continue
            value = metrics.dividend_spread(dy, y)
            if value is None:
                continue
            dy_rows.append({"index_code": spec.code, "date": d, "metric": "dy_spread",
                            "value": value, "freq": "daily", "source": "master"})
        store.upsert_metric(conn, dy_rows)

    # 风格利差：中证500 - 中证1000
    s500 = dict(store.fetch_metric(conn, "000905", "erp"))
    s1000 = dict(store.fetch_metric(conn, "000852", "erp"))
    style_rows = []
    for d in sorted(set(s500) & set(s1000)):
        style_rows.append({"index_code": "STYLE_500_1000", "date": d, "metric": "style_spread",
                           "value": s500[d] - s1000[d], "freq": "daily", "source": "master"})
    store.upsert_metric(conn, style_rows)
    if style_rows:
        vals = [r["value"] for r in style_rows]
        pcts = metrics.percentile_series(vals, PERCENTILE_WINDOWS["10y"])
        store.upsert_metric(conn, [
            {"index_code": "STYLE_500_1000", "date": r["date"], "metric": "style_pct",
             "value": p, "freq": "daily", "source": "master"}
            for r, p in zip(style_rows, pcts) if p is not None
        ])
    return {"indices": len(INDEXES), "bond": bench.key, "days": len(days)}


def _fetch_all(conn) -> list[dict]:
    quality = []
    # 债券曲线
    try:
        rows = chinabond.fetch_bond_yields("20060101")
        store.upsert_bond_yield(conn, rows)
        quality.append({"source": "chinabond", "status": "ok", "rows": len(rows), "message": ""})
    except Exception as exc:
        quality.append({"source": "chinabond", "status": "fail", "rows": 0, "message": str(exc)})

    for source in SOURCES:
        for spec in INDEXES:
            try:
                data = source.fetch(spec.code)
            except Exception as exc:
                quality.append({"source": source.source, "status": "fail", "rows": 0,
                                "message": f"{spec.code}: {exc}"})
                continue
            valuation = data.get("valuation") or []
            prices = data.get("prices") or []
            if valuation:
                store.upsert_valuation(conn, valuation)
            if prices:
                store.upsert_price(conn, prices)
            quality.append({"source": source.source, "status": "ok",
                            "rows": len(valuation) + len(prices),
                            "message": spec.code})
    # 蛋卷快照（补充当前股息率）
    try:
        snap = danjuan.fetch_snapshot()
        store.upsert_valuation(conn, snap)
        quality.append({"source": "danjuan_snapshot", "status": "ok", "rows": len(snap), "message": ""})
    except Exception as exc:
        quality.append({"source": "danjuan_snapshot", "status": "fail", "rows": 0, "message": str(exc)})
    # 乐咕市场股息率长史
    for code, symbol in legulegu.MARKET_GXL.items():
        try:
            rows = legulegu.fetch_market_gxl(symbol)
            store.upsert_valuation(conn, rows)
            quality.append({"source": f"legulegu_gxl:{code}", "status": "ok",
                            "rows": len(rows), "message": ""})
        except Exception as exc:
            quality.append({"source": f"legulegu_gxl:{code}", "status": "fail",
                            "rows": 0, "message": str(exc)})
    return quality


def _stats(navs: list[float]) -> dict:
    """净值序列 → 年化收益/波动/最大回撤。"""
    if len(navs) < 2:
        return {"cagr": None, "vol": None, "max_drawdown": None, "total_return": None}
    rets = [navs[i] / navs[i - 1] - 1 for i in range(1, len(navs))]
    years = len(rets) / 252
    total = navs[-1] / navs[0] - 1
    cagr = (navs[-1] / navs[0]) ** (1 / years) - 1 if years > 0 else None
    vol = statistics.pstdev(rets) * (252 ** 0.5) if len(rets) > 1 else None
    peak, mdd = navs[0], 0.0
    for v in navs:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)
    return {"cagr": cagr, "vol": vol, "max_drawdown": mdd, "total_return": total}


def run_backtest(conn, index_code: str = "000300",
                 bond_key: str = DEFAULT_BOND_BENCHMARK) -> dict:
    """按 ERP 分位映射规则在 股票 与 债券 之间切换的规则回测。

    月度调仓：每月最后一个交易日按当月 ERP 的全历史分位决定次月权益权重（取仓位区间中值）。
    """
    bench = benchmark_by_key(bond_key)
    erp = store.fetch_metric(conn, index_code, "erp")
    prices = dict(store.fetch_prices(conn, index_code))
    bond = dict(store.fetch_bond_yield(conn, bench.curve, bench.tenor))
    if not erp or not prices:
        return {"available": False, "reason": "缺少 ERP 或行情数据"}
    values = [v for _, v in erp]
    pcts = metrics.percentile_series(values, None)
    erp_pct = {d: p for (d, _), p in zip(erp, pcts) if p is not None}
    dates = sorted(set(erp_pct) & set(prices))
    if len(dates) < 250:
        return {"available": False, "reason": f"样本不足（{len(dates)} 天）"}
    month_last: dict[str, str] = {}
    for d in dates:
        month_last[d[:7]] = d

    strategy_nav, equity_nav, bond_nav = [1.0], [1.0], [1.0]
    weight, switches, prev_weight = 0.5, 0, None
    for i in range(1, len(dates)):
        d, prev = dates[i], dates[i - 1]
        r_equity = prices[d] / prices[prev] - 1
        y = bond.get(d)
        r_bond = (y / 100) / 252 if y is not None else 0.0
        strategy_nav.append(strategy_nav[-1] * (weight * r_equity + (1 - weight) * r_bond))
        equity_nav.append(equity_nav[-1] * (1 + r_equity))
        bond_nav.append(bond_nav[-1] * (1 + r_bond))
        if month_last.get(d[:7]) == d or i == len(dates) - 1:
            adv = allocation_advice(erp_pct.get(d))
            w = ((adv[0] + adv[1]) / 2) / 100 if adv else 0.5
            if prev_weight is not None and abs(w - prev_weight) > 0.01:
                switches += 1
            prev_weight = w
            weight = w
    return {
        "available": True,
        "index": index_code,
        "benchmark": bench.label,
        "period": [dates[0], dates[-1]],
        "switches": switches,
        "strategy": _stats(strategy_nav),
        "equity_only": _stats(equity_nav),
        "bond_only": _stats(bond_nav),
    }


def snapshot_payload(conn, bond_key: str = DEFAULT_BOND_BENCHMARK) -> dict:
    bench = benchmark_by_key(bond_key)
    indexes = []
    for spec in INDEXES:
        erp_series = store.fetch_metric(conn, spec.code, "erp")
        pe_series = store.fetch_metric(conn, spec.code, "pe")
        dy_series = store.fetch_metric(conn, spec.code, "dy_spread")
        if not erp_series:
            indexes.append({"code": spec.code, "name": spec.name, "group": spec.group,
                            "erp": None, "pe": None, "percentile": None,
                            "temperature": "未知", "history_start": None,
                            "allocation": None, "dividend_spread": None})
            continue
        latest = erp_series[-1]
        pct = None
        for wname in ("10y", "all", "5y", "3y"):
            rows = store.fetch_metric(conn, spec.code, f"erp_pct_{wname}")
            if rows:
                pct = rows[-1][1]
                break
        adv = allocation_advice(pct)
        indexes.append({
            "code": spec.code, "name": spec.name, "group": spec.group,
            "erp": latest[1],
            "pe": pe_series[-1][1] if pe_series else None,
            "date": latest[0],
            "percentile": pct,
            "temperature": metrics.temperature(pct),
            "history_start": erp_series[0][0],
            "dividend_spread": dy_series[-1][1] if dy_series else None,
            "allocation": {"equity_min": adv[0], "equity_max": adv[1]} if adv else None,
        })
    style = store.fetch_metric(conn, "STYLE_500_1000", "style_spread")
    style_pct = store.fetch_metric(conn, "STYLE_500_1000", "style_pct")
    bond_series = store.fetch_bond_yield(conn, bench.curve, bench.tenor)
    return {
        "generated_at": datetime.now(CST).isoformat(timespec="seconds"),
        "bond": {"key": bench.key, "label": bench.label, "curve": bench.curve, "tenor": bench.tenor,
                 "latest": bond_series[-1] if bond_series else None},
        "indexes": indexes,
        "style": {
            "latest": style[-1] if style else None,
            "percentile": style_pct[-1][1] if style_pct else None,
            "signal": metrics.style_signal(style_pct[-1][1] if style_pct else None),
        },
        "quality": store.latest_quality(conn),
    }


def export_snapshot(conn, path: str | Path | None = None, bond_key: str = DEFAULT_BOND_BENCHMARK) -> Path:
    path = Path(path or SNAPSHOT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot_payload(conn, bond_key), ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def run(conn, bond_key: str = DEFAULT_BOND_BENCHMARK, with_network: bool = True,
        sources: list | None = None, snapshot_path: str | Path | None = None) -> dict:
    global SOURCES
    if sources is not None:
        SOURCES = sources
    quality = []
    if with_network:
        quality = _fetch_all(conn)
        for q in quality:
            store.record_quality(conn, q["source"], q["status"], q.get("rows", 0),
                                 q.get("message", ""), q.get("duration_ms", 0))
    summary = compute_metrics(conn, bond_key=bond_key)
    export_snapshot(conn, snapshot_path, bond_key=bond_key)
    store.set_meta(conn, "last_run", datetime.now(CST).isoformat(timespec="seconds"))
    store.set_meta(conn, "last_bond_benchmark", bond_key)
    return {"quality": quality, "summary": summary}
```

说明：`test_source_failure_is_isolated` 里 `Boom`/`Good` 无 `fetch_index` 之外的行为，`Good.fetch` 返回空 dict 三个键，因此 `_fetch_all` 不会因缺键崩溃；`Boom.fetch` 抛异常被捕获并记为 fail。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_pipeline.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 端到端跑一次真实数据**

Run: `.venv/bin/python -c "from xquant import pipeline, store; c=store.connect('data/market.db'); store.init_db(c); r=pipeline.run(c); print(r['summary']); print([ (q['source'],q['status'],q['rows']) for q in r['quality']])"`

Expected: summary 中 indices=10、days>5000；quality 中 csindex/chinabond/danjuan/legulegu 多数为 ok。打印可能超过 2 分钟（10 个指数 × 1.8MB）。

若 `csindex` 某指数失败（如 399006 无 csindex 数据），该指数应自动降级为蛋卷 PE，不影响整体。

- [ ] **Step 6: 提交**

```bash
git add xquant/pipeline.py tests/test_pipeline.py data/market.db data/snapshot.json
git commit -m "feat: 数据流水线与指标计算"
```

---

### Task 9: FastAPI 服务与 API

**Files:**
- Create: `xquant/server.py`
- Create: `tests/test_server.py`

**Interfaces:**
- Consumes: `xquant.store`、`xquant.metrics`、`xquant.config`、`xquant.pipeline`
- Produces:
  - `server.create_app(db_path: str | Path | None = None) -> FastAPI`
  - `server.app`（模块级默认实例，DB 路径取 `config.DB_PATH`）
  - 路由：`GET /`（返回 `web/index.html`）、`GET /api/snapshot`、`GET /api/series?index=&metric=&window=`、`GET /api/compare?metric=`、`GET /api/style`、`GET /api/allocation`、`GET /api/health`、`POST /api/refresh`
  - `/api/series` 响应体：`{"index_code","metric","window","freq","unit","source","points":[[date, value], ...]}`
  - `/api/snapshot` 响应体：与 `pipeline.snapshot_payload` 一致

- [ ] **Step 1: 写失败测试**

创建 `tests/test_server.py`：

```python
import json

from fastapi.testclient import TestClient

from xquant import pipeline, server, store


def make_client(tmp_path):
    db = tmp_path / "t.db"
    conn = store.connect(db)
    store.init_db(conn)
    pipeline.run(conn, with_network=False, snapshot_path=tmp_path / "s.json")
    conn.close()
    return TestClient(server.create_app(db))


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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xquant.server'`

- [ ] **Step 3: 实现 server.py**

创建 `xquant/server.py`：

```python
"""FastAPI 服务：提供仪表盘所需的 JSON 接口。"""
from __future__ import annotations

import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from xquant import metrics, pipeline, store
from xquant.config import (ALLOCATION_MAP, DB_PATH, DEFAULT_BOND_BENCHMARK, INDEXES,
                            PERCENTILE_WINDOWS, WEB_DIR, allocation_advice, benchmark_by_key)

_refresh_lock = threading.Lock()
_refresh_state = {"running": False, "started_at": None, "finished_at": None, "error": None}


def create_app(db_path: str | Path | None = None) -> FastAPI:
    app = FastAPI(title="xquant 股债性价比仪表盘", version="0.1.0")
    db = Path(db_path) if db_path else None

    def conn():
        c = store.connect(db if db is not None else DB_PATH)
        store.init_db(c)
        return c

    @app.get("/")
    def index_page():
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/api/snapshot")
    def snapshot():
        c = conn()
        try:
            return JSONResponse(pipeline.snapshot_payload(c, DEFAULT_BOND_BENCHMARK))
        finally:
            c.close()

    @app.get("/api/series")
    def series(index: str = Query(...), metric: str = Query("erp"),
               window: str | None = Query(None)):
        spec = next((i for i in INDEXES if i.code == index), None)
        if spec is None and index != "STYLE_500_1000":
            raise HTTPException(status_code=404, detail=f"unknown index {index}")
        c = conn()
        try:
            if metric.startswith("erp_pct_"):
                wname = metric.removeprefix("erp_pct_")
                if wname not in PERCENTILE_WINDOWS:
                    raise HTTPException(status_code=400, detail=f"unknown window {wname}")
                rows = store.fetch_metric(c, index, metric)
                if not rows:
                    rows = store.fetch_metric(c, index, "erp")
                    vals = [v for _, v in rows]
                    pcts = metrics.percentile_series(vals, PERCENTILE_WINDOWS[wname])
                    rows = [(d, p) for (d, _), p in zip(rows, pcts) if p is not None]
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
            spread = store.fetch_metric(c, "STYLE_500_1000", "style_spread")
            pct = store.fetch_metric(c, "STYLE_500_1000", "style_pct")
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
            snap = pipeline.snapshot_payload(c, DEFAULT_BOND_BENCHMARK)
            return {
                "items": snap["indexes"],
                "backtest": pipeline.run_backtest(c),
                "bands": [{"max_pct": b.max_pct, "equity_min": b.equity_min,
                           "equity_max": b.equity_max} for b in ALLOCATION_MAP],
            }
        finally:
            c.close()

    @app.get("/api/health")
    def health():
        c = conn()
        try:
            quality = store.latest_quality(c)
            return {"quality": quality, "last_run": store.get_meta(c, "last_run"),
                    "bond_benchmark": store.get_meta(c, "last_bond_benchmark", DEFAULT_BOND_BENCHMARK),
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
                c = store.connect(db) if db else store.connect("data/market.db")
                store.init_db(c)
                try:
                    pipeline.run(c)
                finally:
                    c.close()
            except Exception as exc:
                _refresh_state["error"] = str(exc)
            finally:
                _refresh_state["running"] = False

        threading.Thread(target=worker, daemon=True).start()
        return {"started": True, "state": _refresh_state}

    return app


app = create_app()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_server.py -v`
Expected: PASS（5 passed）

注意 `tests/test_server.py` 用 `from tests.test_pipeline import seeded_conn`，需要 `tests/__init__.py`（空文件）才能作为包导入；若 pytest 报 import 错误，改为在本文件内复制 `seeded_conn` 定义。

- [ ] **Step 5: 提交**

```bash
git add xquant/server.py tests/test_server.py tests/__init__.py
git commit -m "feat: FastAPI 服务与接口"
```

---

### Task 10: 前端骨架 + 指标卡 + ERP 主图

**Files:**
- Create: `web/vendor/echarts.min.js`（下载）
- Create: `web/index.html`
- Create: `web/style.css`
- Create: `web/app.js`

**Interfaces:**
- Consumes: `GET /api/snapshot`、`GET /api/series`、`GET /api/compare`、`GET /api/style`、`GET /api/allocation`、`GET /api/health`
- Produces: 浅色简洁单页仪表盘；全局 `window.XQ` 对象暴露 `state`、`loadSnapshot()`、`renderAll()`

- [ ] **Step 1: 下载 ECharts 到本地 vendor**

Run:
```bash
mkdir -p web/vendor
curl -L --max-time 60 "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js" -o web/vendor/echarts.min.js
ls -l web/vendor/echarts.min.js
```
Expected: 文件约 1.0MB

- [ ] **Step 2: 写 index.html**

创建 `web/index.html`：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>xquant · 中国股债性价比仪表盘</title>
<link rel="stylesheet" href="/style.css">
</head>
<body>
<header class="topbar">
  <div class="brand">
    <span class="logo">xquant</span>
    <span class="sub">中国股债性价比 · 格雷厄姆指数</span>
  </div>
  <div class="topbar-right">
    <span id="bond-label" class="pill">10年期国债</span>
    <span id="updated-at" class="muted"></span>
    <button id="refresh-btn" class="btn">刷新数据</button>
  </div>
</header>

<section class="cards" id="cards"></section>

<section class="panel">
  <div class="panel-head">
    <h2>格雷厄姆指数 / 股权风险溢价</h2>
    <div class="controls">
      <label>指数 <select id="erp-index"></select></label>
      <label>窗口
        <select id="erp-window">
          <option value="3y">近3年</option>
          <option value="5y">近5年</option>
          <option value="10y" selected>近10年</option>
          <option value="all">全历史</option>
        </select>
      </label>
    </div>
  </div>
  <p class="caption" id="erp-caption"></p>
  <div id="chart-erp" class="chart chart-lg"></div>
</section>

<section class="panel">
  <div class="panel-head"><h2>股息率差（股息率 − 10年期国债）</h2></div>
  <p class="caption" id="dy-caption"></p>
  <div id="chart-dy" class="chart"></div>
</section>

<section class="panel">
  <div class="panel-head"><h2>多指数对比</h2></div>
  <div id="chart-compare" class="chart"></div>
</section>

<section class="panel">
  <div class="panel-head"><h2>大小盘风格（ERP(中证500) − ERP(中证1000)）</h2></div>
  <p class="caption" id="style-caption"></p>
  <div id="chart-style" class="chart"></div>
</section>

<section class="panel">
  <div class="panel-head"><h2>股 / 债配置参考</h2></div>
  <div id="allocation-table" class="table-wrap"></div>
</section>

<section class="panel">
  <details>
    <summary>数据健康与口径说明</summary>
    <div id="health" class="table-wrap"></div>
    <p class="disclaimer">本页所有指标由公开数据源自行计算，口径以各图表说明为准；配置建议为固定规则映射，仅供参考，不构成投资建议。</p>
  </details>
</section>

<script src="/vendor/echarts.min.js"></script>
<script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 3: 写 style.css**

创建 `web/style.css`：

```css
:root {
  --bg: #f7f8fa;
  --card: #ffffff;
  --text: #1f2328;
  --muted: #6b7280;
  --line: #e6e8eb;
  --primary: #2563eb;
  --up: #dc2626;
  --down: #16a34a;
  --warn: #d97706;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;
  font-size: 14px; line-height: 1.55;
}
.topbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 24px; background: var(--card); border-bottom: 1px solid var(--line);
  position: sticky; top: 0; z-index: 10;
}
.brand .logo { font-weight: 700; font-size: 18px; letter-spacing: .5px; }
.brand .sub { color: var(--muted); margin-left: 10px; font-size: 13px; }
.topbar-right { display: flex; align-items: center; gap: 12px; }
.pill { background: #eef2ff; color: var(--primary); padding: 2px 10px; border-radius: 999px; font-size: 12px; }
.muted { color: var(--muted); font-size: 12px; }
.btn {
  border: 1px solid var(--primary); background: var(--primary); color: #fff;
  padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 13px;
}
.btn:disabled { opacity: .6; cursor: progress; }
main, section { max-width: 1240px; margin: 0 auto; padding: 0 24px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; margin: 20px 0; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; }
.card h3 { margin: 0 0 6px; font-size: 14px; font-weight: 600; }
.card .value { font-size: 24px; font-weight: 650; font-variant-numeric: tabular-nums; }
.card .sub { color: var(--muted); font-size: 12px; }
.badge { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 12px; margin-top: 6px; }
.badge.cheap { background: #dcfce7; color: #15803d; }
.badge.mid { background: #fef9c3; color: #a16207; }
.badge.expensive { background: #fee2e2; color: #b91c1c; }
.badge.unknown { background: #f1f5f9; color: #64748b; }
.panel { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 16px 18px; margin-bottom: 16px; }
.panel-head { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; }
.panel-head h2 { font-size: 15px; margin: 0; }
.controls { display: flex; gap: 14px; align-items: center; }
.controls label { color: var(--muted); font-size: 12px; }
select { padding: 4px 8px; border: 1px solid var(--line); border-radius: 6px; background: #fff; color: var(--text); }
.caption { color: var(--muted); font-size: 12px; margin: 6px 0 10px; }
.chart { width: 100%; height: 340px; }
.chart-lg { height: 420px; }
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { text-align: right; padding: 7px 10px; border-bottom: 1px solid var(--line); }
th:first-child, td:first-child { text-align: left; }
th { color: var(--muted); font-weight: 500; }
.disclaimer { color: var(--muted); font-size: 12px; margin-top: 12px; }
details summary { cursor: pointer; font-size: 15px; font-weight: 600; }
```

- [ ] **Step 4: 写 app.js**

创建 `web/app.js`：

```javascript
/* xquant 前端：浅色简洁仪表盘 */
(function () {
  "use strict";

  const state = { snapshot: null, seriesCache: {}, compare: null, style: null, allocation: null };

  const fmt = (v, digits = 2) =>
    v === null || v === undefined || Number.isNaN(v) ? "—" : Number(v).toFixed(digits);

  const tempClass = (t) =>
    t === "便宜" || t === "偏低" ? "cheap" : t === "偏贵" || t === "很贵" ? "expensive" : "unknown";

  async function getJSON(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(url + " → " + r.status);
    return r.json();
  }

  function renderCards(snap) {
    const el = document.getElementById("cards");
    el.innerHTML = snap.indexes
      .map((i) => {
        const alloc = i.allocation ? `${i.allocation.equity_min}%–${i.allocation.equity_max}%` : "—";
        return `<div class="card">
          <h3>${i.name} <span class="muted">${i.code}</span></h3>
          <div class="value">${fmt(i.erp)}<span class="sub"> %</span></div>
          <div class="sub">PE ${fmt(i.pe)} · 分位 ${fmt(i.percentile, 0)}%</div>
          <span class="badge ${tempClass(i.temperature)}">${i.temperature}</span>
          <div class="sub">建议权益仓位 ${alloc}</div>
        </div>`;
      })
      .join("");
    document.getElementById("bond-label").textContent = snap.bond.label;
    document.getElementById("updated-at").textContent =
      "更新于 " + (snap.generated_at || "").replace("T", " ");
  }

  const chartBase = {
    backgroundColor: "transparent",
    textStyle: { color: "#6b7280", fontFamily: "-apple-system, PingFang SC, sans-serif" },
    grid: { left: 52, right: 24, top: 28, bottom: 40 },
    tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
  };

  function makeChart(id) {
    const c = echarts.init(document.getElementById(id), null, { renderer: "canvas" });
    window.addEventListener("resize", () => c.resize());
    return c;
  }

  async function renderERP() {
    const code = document.getElementById("erp-index").value;
    const win = document.getElementById("erp-window").value;
    const data = await getJSON(`/api/series?index=${code}&metric=erp`);
    const points = data.points;
    const chart = makeChart("chart-erp");
    const values = points.map((p) => p[1]);
    const sorted = values.slice().sort((a, b) => a - b);
    const q = (p) => sorted[Math.min(sorted.length - 1, Math.floor((p / 100) * sorted.length))];
    chart.setOption({
      ...chartBase,
      tooltip: { trigger: "axis", valueFormatter: (v) => fmt(v) + " %" },
      xAxis: { type: "category", data: points.map((p) => p[0]), boundaryGap: false },
      yAxis: { type: "value", name: "%", scale: true },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 16 }],
      series: [
        { name: "格雷厄姆指数", type: "line", showSymbol: false, data: values,
          lineStyle: { width: 1.8, color: "#2563eb" },
          areaStyle: { color: "rgba(37,99,235,0.08)" },
          markLine: { silent: true, symbol: "none", label: { formatter: "{b}" },
            data: [{ yAxis: q(30), name: "30分位", lineStyle: { color: "#16a34a", type: "dashed" } },
                   { yAxis: q(70), name: "70分位", lineStyle: { color: "#dc2626", type: "dashed" } }] } },
      ],
    });
    const spec = state.snapshot.indexes.find((i) => i.code === code);
    document.getElementById("erp-caption").textContent =
      `口径：中证官方近四季滚动市盈率(TTM) ÷ 100 − ${state.snapshot.bond.label}；` +
      `序列起始 ${points.length ? points[0][0] : "—"}；分位窗口 ${win}。`;
  }

  async function renderDY() {
    const code = document.getElementById("erp-index").value;
    let data;
    try {
      data = await getJSON(`/api/series?index=${code}&metric=dy_spread`);
    } catch (e) {
      document.getElementById("chart-dy").innerHTML = "<p class='muted'>暂无股息率数据</p>";
      return;
    }
    const chart = makeChart("chart-dy");
    chart.setOption({
      ...chartBase,
      tooltip: { trigger: "axis", valueFormatter: (v) => fmt(v) + " %" },
      xAxis: { type: "category", data: data.points.map((p) => p[0]), boundaryGap: false },
      yAxis: { type: "value", name: "%", scale: true },
      series: [{ name: "股息率差", type: "line", showSymbol: false, data: data.points.map((p) => p[1]),
        lineStyle: { width: 1.6, color: "#0891b2" }, areaStyle: { color: "rgba(8,145,178,0.08)" } }],
    });
    document.getElementById("dy-caption").textContent =
      `口径：中证官方股息率（计算用股本口径） − ${state.snapshot.bond.label}；` +
      `序列起始 ${data.points[0][0]}（股息率历史自 2026-10-22 起逐日累积）。`;
  }

  async function renderCompare() {
    const data = await getJSON("/api/compare?metric=erp");
    const palette = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2", "#be185d", "#4d7c0f"];
    const chart = makeChart("chart-compare");
    chart.setOption({
      ...chartBase,
      legend: { type: "scroll", top: 0 },
      tooltip: { trigger: "axis" },
      xAxis: { type: "category", data: data.series.length ? data.series[0].points.map((p) => p[0]) : [] },
      yAxis: { type: "value", name: "%", scale: true },
      series: data.series.map((s, i) => ({
        name: s.name, type: "line", showSymbol: false, connectNulls: true,
        data: s.points.map((p) => p[1]), lineStyle: { width: 1.3, color: palette[i % palette.length] },
      })),
    });
  }

  async function renderStyle() {
    const data = await getJSON("/api/style");
    const chart = makeChart("chart-style");
    chart.setOption({
      ...chartBase,
      tooltip: { trigger: "axis" },
      xAxis: { type: "category", data: data.points.map((p) => p[0]), boundaryGap: false },
      yAxis: { type: "value", name: "%", scale: true },
      series: [{ name: "风格利差", type: "line", showSymbol: false, data: data.points.map((p) => p[1]),
        lineStyle: { width: 1.6, color: "#7c3aed" } }],
    });
    document.getElementById("style-caption").textContent =
      `最新 ${fmt(data.latest && data.latest[1])}%，历史分位 ${fmt(data.percentile, 0)}%，信号：${data.signal}`;
  }

  async function renderAllocation() {
    const data = await getJSON("/api/allocation");
    const rows = data.items
      .filter((i) => i.erp !== null)
      .map((i) => `<tr><td>${i.name}</td><td>${fmt(i.erp)}</td><td>${fmt(i.percentile, 0)}%</td>
        <td>${i.temperature}</td><td>${i.allocation ? i.allocation.equity_min + "%–" + i.allocation.equity_max + "%" : "—"}</td></tr>`)
      .join("");
    const bt = data.backtest || {};
    let btHtml = "";
    if (bt.available) {
      const pct = (v) => (v === null || v === undefined ? "—" : (v * 100).toFixed(1) + "%");
      btHtml = `<h3 style="font-size:14px;margin:16px 0 6px">规则回测：沪深300 vs ${bt.benchmark}
        （${bt.period[0]} ~ ${bt.period[1]}，切换 ${bt.switches} 次）</h3>
        <table><thead><tr><th>组合</th><th>年化收益</th><th>年化波动</th><th>最大回撤</th><th>累计收益</th></tr></thead>
        <tbody>
          <tr><td>股债切换（按分位）</td><td>${pct(bt.strategy.cagr)}</td><td>${pct(bt.strategy.vol)}</td>
              <td>${pct(bt.strategy.max_drawdown)}</td><td>${pct(bt.strategy.total_return)}</td></tr>
          <tr><td>满仓股票</td><td>${pct(bt.equity_only.cagr)}</td><td>${pct(bt.equity_only.vol)}</td>
              <td>${pct(bt.equity_only.max_drawdown)}</td><td>${pct(bt.equity_only.total_return)}</td></tr>
          <tr><td>满仓债券</td><td>${pct(bt.bond_only.cagr)}</td><td>${pct(bt.bond_only.vol)}</td>
              <td>${pct(bt.bond_only.max_drawdown)}</td><td>${pct(bt.bond_only.total_return)}</td></tr>
        </tbody></table>`;
    } else {
      btHtml = `<p class="caption">回测样本不足，暂不展示（${bt.reason || "数据不足"}）。</p>`;
    }
    document.getElementById("allocation-table").innerHTML =
      `<table><thead><tr><th>指数</th><th>ERP %</th><th>分位</th><th>状态</th><th>建议权益仓位</th></tr></thead>
       <tbody>${rows}</tbody></table>
       <p class="caption">规则：ERP 分位 ≤10% → 权益 80–100%；≤30% → 60–80%；≤70% → 40–60%；≤90% → 20–40%；其余 → 0–20%。</p>
       ${btHtml}`;
  }

  async function renderHealth() {
    const data = await getJSON("/api/health");
    const rows = (data.quality || [])
      .map((q) => `<tr><td>${q.source}</td><td>${q.status}</td><td>${q.rows ?? ""}</td>
        <td>${q.ts || ""}</td><td style="text-align:left">${(q.message || "").slice(0, 80)}</td></tr>`)
      .join("");
    document.getElementById("health").innerHTML =
      `<table><thead><tr><th>数据源</th><th>状态</th><th>行数</th><th>时间</th><th>说明</th></tr></thead>
       <tbody>${rows}</tbody></table>`;
  }

  async function renderAll() {
    state.snapshot = await getJSON("/api/snapshot");
    renderCards(state.snapshot);
    const sel = document.getElementById("erp-index");
    if (!sel.options.length) {
      state.snapshot.indexes.forEach((i) => {
        const o = document.createElement("option");
        o.value = i.code; o.textContent = `${i.name} (${i.code})`;
        sel.appendChild(o);
      });
      sel.value = "000300";
      sel.addEventListener("change", () => { renderERP(); renderDY(); });
      document.getElementById("erp-window").addEventListener("change", renderERP);
    }
    await renderERP();
    await renderDY();
    await renderCompare();
    await renderStyle();
    await renderAllocation();
    await renderHealth();
  }

  document.addEventListener("DOMContentLoaded", async () => {
    document.getElementById("refresh-btn").addEventListener("click", async (e) => {
      e.target.disabled = true;
      e.target.textContent = "抓取中…";
      try {
        await fetch("/api/refresh", { method: "POST" });
        setTimeout(async () => {
          await renderAll();
          e.target.disabled = false;
          e.target.textContent = "刷新数据";
        }, 8000);
      } catch (err) {
        e.target.disabled = false;
        e.target.textContent = "刷新数据";
      }
    });
    try {
      await renderAll();
    } catch (err) {
      document.getElementById("cards").innerHTML =
        `<div class="card"><h3>加载失败</h3><div class="sub">${err.message}</div></div>`;
    }
  });

  window.XQ = { state, renderAll, getJSON };
})();
```

- [ ] **Step 5: 启动服务并在浏览器验证**

Run（后台）：
```bash
.venv/bin/python -m uvicorn xquant.server:app --host 127.0.0.1 --port 8848
```
然后用浏览器打开 `http://127.0.0.1:8848`，确认：8 张以上指标卡有数值、ERP 曲线渲染、其余图表有内容。截图确认浅色风格与排版无错位。

- [ ] **Step 6: 提交**

```bash
git add web/
git commit -m "feat: 前端仪表盘（指标卡 + ERP 主图）"
```

---

### Task 11: 前端补齐（股息率差 / 对比 / 风格 / 配置 / 健康）已完成于 Task 10，本任务做校验与打磨

**Files:**
- Modify: `web/app.js`、`web/style.css`

**Interfaces:**
- Consumes: 同 Task 10
- Produces: 五个图表与两张表格全部有真实数据渲染

- [ ] **Step 1: 写一个离线校验脚本**

创建 `scripts/check_frontend.py`：

```python
"""静态校验：前端 index.html 引用的接口在 FastAPI 路由里都存在。"""
import re
import sys
from pathlib import Path

from xquant.server import app

ROOT = Path(__file__).resolve().parent.parent
html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")

routes = {r.path for r in app.routes if hasattr(r, "path")}
used = set(re.findall(r"[\"'`](/api/[a-zA-Z0-9_\-/]*)", js + html))
missing = sorted(u for u in used if u.split("?")[0] not in routes)
if missing:
    print("缺少路由:", missing)
    sys.exit(1)
print("OK 前端引用的接口均存在:", sorted(used))
```

- [ ] **Step 2: 运行校验**

Run: `.venv/bin/python scripts/check_frontend.py`
Expected: `OK 前端引用的接口均存在: [...]`

- [ ] **Step 3: 浏览器全量检查**

打开页面，逐个确认：股息率差图有曲线（若股息率序列太短则显示提示文案）、多指数对比图有 8 条线、风格图有曲线、配置建议表格有行、数据健康表格列出各源状态。

- [ ] **Step 4: 提交**

```bash
git add web/ scripts/check_frontend.py
git commit -m "feat: 前端补齐与静态校验脚本"
```

---

### Task 12: CLI、GitHub Actions、本机定时、README

**Files:**
- Create: `xquant/cli.py`
- Create: `.github/workflows/update.yml`
- Create: `scripts/install_launchd.sh`
- Create: `scripts/com.xquant.update.plist`
- Create: `README.md`

**Interfaces:**
- Consumes: `xquant.pipeline`、`xquant.store`、`xquant.config`
- Produces:
  - `python -m xquant.cli update [--bond bond10y] [--no-network]`
  - `python -m xquant.cli serve [--host 127.0.0.1] [--port 8848]`
  - `python -m xquant.cli export`
  - `python -m xquant.cli backfill [--start 20050101]`

- [ ] **Step 1: 实现 cli.py**

创建 `xquant/cli.py`：

```python
"""命令行入口：update / serve / export / backfill。"""
from __future__ import annotations

import argparse

import uvicorn

from xquant import pipeline, store
from xquant.config import DB_PATH, DEFAULT_BOND_BENCHMARK, SNAPSHOT_PATH


def cmd_update(args) -> int:
    conn = store.connect(DB_PATH)
    store.init_db(conn)
    try:
        result = pipeline.run(conn, bond_key=args.bond, with_network=not args.no_network)
    finally:
        conn.close()
    print("summary:", result["summary"])
    for q in result["quality"]:
        print(f"  {q['source']:<24} {q['status']:<5} rows={q.get('rows', 0)} {q.get('message', '')[:60]}")
    return 0


def cmd_export(args) -> int:
    conn = store.connect(DB_PATH)
    store.init_db(conn)
    try:
        path = pipeline.export_snapshot(conn, SNAPSHOT_PATH, bond_key=args.bond)
    finally:
        conn.close()
    print("exported:", path)
    return 0


def cmd_serve(args) -> int:
    uvicorn.run("xquant.server:app", host=args.host, port=args.port, reload=False)
    return 0


def cmd_backfill(args) -> int:
    """回填中证 PE 日频历史（默认 2005 起）。"""
    from xquant.sources import csindex
    from xquant.config import INDEXES
    conn = store.connect(DB_PATH)
    store.init_db(conn)
    try:
        for spec in INDEXES:
            if not spec.has_csindex:
                continue
            try:
                data = csindex.fetch_index(spec.code, start_date=args.start)
            except Exception as exc:
                print(f"{spec.code} 失败: {exc}")
                continue
            if data["valuation"]:
                store.upsert_valuation(conn, data["valuation"])
            if data["prices"]:
                store.upsert_price(conn, data["prices"])
            print(f"{spec.code}: valuation={len(data['valuation'])} perf={len(data['perf'])}")
    finally:
        conn.close()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="xquant")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("update", help="抓取数据并计算指标")
    p.add_argument("--bond", default=DEFAULT_BOND_BENCHMARK)
    p.add_argument("--no-network", action="store_true", help="只用库中已有数据重算指标")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("export", help="导出 snapshot.json")
    p.add_argument("--bond", default=DEFAULT_BOND_BENCHMARK)
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("serve", help="启动 Web 服务")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8848)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("backfill", help="回填中证 PE 日频历史")
    p.add_argument("--start", default="20050101")
    p.set_defaults(func=cmd_backfill)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: 实现 GitHub Actions workflow**

创建 `.github/workflows/update.yml`：

```yaml
name: update-market-data

on:
  schedule:
    - cron: "30 8 * * 1-5"   # 北京时间 16:30
  workflow_dispatch:

concurrency:
  group: update-market-data
  cancel-in-progress: false

jobs:
  update:
    runs-on: ubuntu-latest
    timeout-minutes: 40
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Update data
        run: python -m xquant.cli update
      - name: Commit data
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add data/market.db data/snapshot.json
          if git diff --staged --quiet; then
            echo "no data change"
          else
            git commit -m "chore: 更新市场数据 $(date -u +%Y-%m-%dT%H:%M:%SZ)"
            git push
          fi
```

- [ ] **Step 3: 实现本机 launchd 定时（备用方案）**

创建 `scripts/com.xquant.update.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.xquant.update</string>
  <key>ProgramArguments</key>
  <array>
    <string>__ROOT__/.venv/bin/python</string>
    <string>-m</string>
    <string>xquant.cli</string>
    <string>update</string>
  </array>
  <key>WorkingDirectory</key><string>__ROOT__</string>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>6</integer><key>Hour</key><integer>16</integer><key>Minute</key><integer>30</integer></dict>
  </array>
  <key>StandardOutPath</key><string>__ROOT__/data/update.log</string>
  <key>StandardErrorPath</key><string>__ROOT__/data/update.err.log</string>
</dict>
</plist>
```

创建 `scripts/install_launchd.sh`：

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST="$ROOT/scripts/com.xquant.update.plist"
sed "s|__ROOT__|$ROOT|g" "$PLIST" > "$HOME/Library/LaunchAgents/com.xquant.update.plist"
launchctl unload "$HOME/Library/LaunchAgents/com.xquant.update.plist" 2>/dev/null || true
launchctl load "$HOME/Library/LaunchAgents/com.xquant.update.plist"
echo "已安装: $HOME/Library/LaunchAgents/com.xquant.update.plist"
```

Run: `chmod +x scripts/install_launchd.sh`

- [ ] **Step 4: 写 README.md**

创建 `README.md`：

````markdown
# xquant · 中国股债性价比仪表盘

本地运行的 Web 仪表盘：格雷厄姆指数（ERP）、股息率差、历史分位温度、大小盘风格利差、股/债配置参考。

## 快速开始

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python -m xquant.cli update      # 抓数据（首次约 2-5 分钟）
.venv/bin/python -m xquant.cli serve       # http://127.0.0.1:8848
```

## 指标口径

| 指标 | 定义 |
|---|---|
| 格雷厄姆指数 / ERP | `1/PE(TTM)×100 − 10年期国债收益率` |
| ERP 分位 | ERP 在近 3/5/10 年或全历史中的分位（0-100） |
| 股息率差 | `指数股息率 − 10年期国债收益率` |
| 风格利差 | `ERP(中证500) − ERP(中证1000)`，取分位判定大小盘风格 |
| 配置参考 | ERP 分位 → 建议权益仓位区间（规则化映射，见 `xquant/config.py`） |

## 数据源

| 数据 | 来源 | 频率 / 历史 |
|---|---|---|
| 指数 PE(TTM)、收盘价 | 中证指数 `index-perf` | 日 / 2005→ |
| 指数市盈率与股息率（两种股本口径） | 中证指数 `indicator.xls` | 日 / 近 20 日窗口，逐日累积 |
| 国债与信用债收益率曲线 | 中国债券信息网（中债） | 日 / 2002→ |
| 指数 PE 周频 | 蛋卷基金 | 周 / 2016→ |
| 沪深300 股债利差（官方口径） | 乐咕乐股 | 日 / 2006→ |
| 市场上层/深/创业板/科创板股息率 | 乐咕乐股 | 日 / 2005→ |

主 PE 口径为中证官方「近四季滚动市盈率」；其余来源用于交叉校验与长历史补齐。

## 每日自动更新

- GitHub Actions：`.github/workflows/update.yml`（北京时间 16:30，提交 `data/`）。首次使用需自行 `git remote add <你的仓库>` 并 push。
- 本机 launchd（备用）：`bash scripts/install_launchd.sh`

## 目录

```
xquant/config.py     指数清单、债券基准、仓位映射
xquant/sources/      各数据源适配器
xquant/store.py      SQLite 持久层
xquant/metrics.py    指标纯函数
xquant/pipeline.py   抓取→落库→指标→快照
xquant/server.py     FastAPI
web/                 单页前端（ECharts 本地 vendor）
```

## 免责声明

所有指标由公开数据自行计算，配置建议为固定规则映射，仅供参考，不构成投资建议。
````

- [ ] **Step 5: 验证 CLI**

Run: `.venv/bin/python -m xquant.cli export`
Expected: 打印 `exported: /Users/nbody/Desktop/xquant/data/snapshot.json`

Run: `.venv/bin/python -m xquant.cli --help`
Expected: 列出 update / export / serve / backfill

- [ ] **Step 6: 提交**

```bash
git add xquant/cli.py .github/workflows/update.yml scripts README.md
git commit -m "feat: CLI、GitHub Actions 与本机定时"
```

---

### Task 13: 端到端验收

**Files:**
- Modify: `README.md`（补验收结果）
- Create: `docs/superpowers/plans/2026-10-22-xquant-acceptance.md`

- [ ] **Step 1: 全量测试**

Run: `.venv/bin/python -m pytest -v`
Expected: 全部 PASS（≥ 38 个用例）

- [ ] **Step 2: 清库重跑全量数据**

```bash
rm -f data/market.db data/market.db-wal data/market.db-shm
.venv/bin/python -m xquant.cli update
```
Expected: 无异常；quality 中 csindex/chinabond/danjuan/legulegu/danjuan_snapshot 均为 ok

- [ ] **Step 3: 校验关键数值合理性**

Run:
```bash
.venv/bin/python - <<'PY'
import json, pathlib
snap = json.loads(pathlib.Path("data/snapshot.json").read_text())
for i in snap["indexes"]:
    print(f"{i['name']:<8} ERP={i['erp']} PE={i['pe']} 分位={i['percentile']} {i['temperature']} 起始={i['history_start']}")
print("style:", snap["style"])
PY
```
Expected:
- 沪深300 ERP 落在 3%~8% 区间（PE≈12.8、10Y 国债≈1.7% 时约 6.1%）
- 每个指数 history_start 为 2005 附近（创业板指为 2016 附近）
- 分位为 0-100 的数值或 null

- [ ] **Step 4: 浏览器终验**

启动 `.venv/bin/python -m xquant.cli serve`，浏览器打开 `http://127.0.0.1:8848`：
- 8 张以上指标卡有值，温度色正确
- ERP 主图有曲线、30/70 分位虚线可见
- 股息率差图有曲线或明确提示
- 多指数对比图有多条线
- 风格图有曲线且显示信号文字
- 配置建议表有行
- 数据健康表列出各源状态
- 点击「刷新数据」按钮有响应

截图存到 `docs/` 备查。

- [ ] **Step 5: 写验收文档**

创建 `docs/superpowers/plans/2026-10-22-xquant-acceptance.md`，记录：测试通过数、各源状态、关键指标当前值与起始日、已知限制（股息率历史从 2026-10-22 起累积；PE 口径以中证官方为准）。

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "docs: 端到端验收记录"
```

---

## 交付后待用户操作

1. `git remote add origin <你的仓库地址>` 并 `git push -u origin main`（仓库名由用户提供，Task 12 的 workflow 不依赖仓库名）
2. 在 GitHub 仓库 Settings → Actions 启用 workflow；如需手动触发用 workflow_dispatch
3. 如选本机定时：`bash scripts/install_launchd.sh`
