"""全局配置：指数清单、债券基准、仓位映射表。

所有口径决定都集中在本文件，改这里就能换基准/换指数/换仓位规则。

口径备注（2026-10-22 实测确认）：
- 主 PE 口径为中证官网 ``index-perf`` 接口返回的 ``peg`` 字段，即中证官方
  「近四季滚动市盈率」(TTM)，日频、2005 年至今。已与 CEIC 同口径序列交叉验证。
- 中证 ``indicator.xls`` 的「市盈率1/市盈率2」是**股本口径**差异
  （总股本 vs 计算用股本），不是静态/滚动差异，两者都落库作辅助口径。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "market.db"
SNAPSHOT_PATH = DATA_DIR / "snapshot.json"
BUNDLE_PATH = DATA_DIR / "series.csv"
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
    # 中证一级行业指数（中证官网 PE 日频自 2011-06 起，价格自 2004 起）
    IndexSpec("000928", "中证能源", "行业"),
    IndexSpec("000929", "中证原材料", "行业"),
    IndexSpec("000930", "中证工业", "行业"),
    IndexSpec("000931", "中证可选消费", "行业"),
    IndexSpec("000932", "中证主要消费", "行业"),
    IndexSpec("000933", "中证医药卫生", "行业"),
    IndexSpec("000934", "中证金融地产", "行业"),
    IndexSpec("000935", "中证信息技术", "行业"),
    IndexSpec("000936", "中证通信服务", "行业"),
    IndexSpec("000937", "中证公用事业", "行业"),
]

# 乐咕乐股指数 PE 的 symbol → 中证代码映射（乐咕只支持部分指数）
LEGULEGU_SYMBOL_TO_CODE = {i.legulegu_symbol: i.code for i in INDEXES if i.legulegu_symbol}

# 中证代码 → 乐咕乐股 symbol（抓取时用）
LEGULEGU_CODE_TO_SYMBOL = {i.code: i.legulegu_symbol for i in INDEXES if i.legulegu_symbol}

# 市场层面股息率序列（乐咕乐股，日频 2005 起），用于市场级股债性价比长历史
MARKET_DIVIDEND_SERIES = {
    "MKT_SH": "上证A股",
    "MKT_SZ": "深证A股",
    "MKT_GEM": "创业板",
    "MKT_STAR": "科创板",
}

BOND_BENCHMARKS: list[BondBenchmark] = [
    BondBenchmark("bond10y", "10年期国债", "中债国债收益率曲线", "10年"),
    BondBenchmark("bond30y", "30年期国债", "中债国债收益率曲线", "30年"),
    BondBenchmark("bond5y", "5年期国债", "中债国债收益率曲线", "5年"),
    BondBenchmark("aaa3y", "AAA中短期票据3年", "中债中短期票据收益率曲线(AAA)", "3年"),
    BondBenchmark("aaa5y", "AAA中短期票据5年", "中债中短期票据收益率曲线(AAA)", "5年"),
]

DEFAULT_BOND_BENCHMARK = "bond10y"

# 规则回测使用的指数
BACKTEST_INDEX = "000300"
# 回测预热：至少积累约 5 年 ERP 历史后再按分位交易，
# 避免 2006–2011 年（乐咕月频口径、样本短）的早期信号失真
BACKTEST_WARMUP_DAYS = 1250

# 分位窗口按「日历年份」定义（None=全历史）。序列是交易日，不能用交易日数近似年份：
# 旧的 1095/1825/3650 实际跨 4.4/7.3/14.6 年，会把「近10年」算成近15年。
PERCENTILE_WINDOWS: dict[str, int | None] = {"3y": 3, "5y": 5, "10y": 10, "all": None}

# 风格利差：沪深300（大盘） − 中证1000（小盘）
STYLE_BIG_CODE = "000300"
STYLE_SMALL_CODE = "000852"
STYLE_INDEX = "STYLE_300_1000"

# 权益仓位参考映射表（按 ERP 分位从低到高），可自行调整
# ERP 分位越高 = 股票相对债券越便宜 = 建议权益仓位越高（注意与 PE 分位方向相反）
ALLOCATION_MAP: list[AllocationBand] = [
    AllocationBand(10, 0, 20),
    AllocationBand(30, 20, 40),
    AllocationBand(70, 40, 60),
    AllocationBand(90, 60, 80),
    AllocationBand(100, 80, 100),
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
    """ERP 分位 → 建议权益仓位区间 (下限%, 上限%)。分位越高（越便宜）仓位越高。

    分位为 None 或越界返回 None。
    """
    if pct is None:
        return None
    if pct < 0 or pct > 100:
        return None
    for band in ALLOCATION_MAP:
        if pct <= band.max_pct:
            return (band.equity_min, band.equity_max)
    return None
