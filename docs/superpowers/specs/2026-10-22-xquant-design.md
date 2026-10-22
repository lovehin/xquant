# xquant — 中国股债性价比 / 格雷厄姆指数 仪表盘 设计文档

- 日期：2026-10-22
- 状态：已与用户确认设计，待实现
- 形态：本地运行的单页 Web 应用（浅色简洁风格）

---

## 1. 目标与范围

做一个本地 Web 仪表盘，回答中国 A 股当前相对债券是贵还是便宜，并给出可解释的股/债配置参考。

覆盖三个口径 + 三个衍生指标：

| 指标 | 定义 | 作用 |
|---|---|---|
| 格雷厄姆指数 GI | `1/PE(TTM) − 10Y 国债收益率` | 主指标：股权收益率相对无风险利率的溢价 |
| 股权风险溢价 ERP 分位 | GI 在近 3/5/10 年 / 全历史的分位数 | 判断当前贵贱水平 |
| 股息率差 | `指数股息率 − 10Y 国债收益率` | 红利类资产的股债性价比，交叉验证 |
| 风格利差 | `ERP(中证500) − ERP(中证1000)` 分位 | 大小盘风格择时参考 |
| 债性/股性建议 | ERP 分位 → 建议权益仓位区间 | 仓位参考（规则化映射，非投资建议） |

### 1.1 明确的非目标

- 不做择时回测框架、不做收益归因、不做实盘交易
- 不做多用户 / 登录 / 权限
- 不做移动端 App（响应式做，但不专门优化）
- 不承诺数据源永不变动：每个源独立封装，坏了只降级不影响其他

---

## 2. 数据层

### 2.1 数据源清单（2026-10-22 全部实测可用）

| # | 数据 | 来源 | 接入方式 | 频率 / 历史 | 覆盖指数 |
|---|---|---|---|---|---|
| S1 | 中债收益率曲线 | 中国债券信息网 | akshare `bond_china_yield` | 日 / 2002→ | 国债 1-30Y、AAA 中短期票据、商业银行普通债 |
| S2 | 沪深300 股债利差 | 乐咕乐股 | akshare `stock_ebs_lg` | 日 / 2006→ | 沪深300 |
| S3 | 宽基 PE 月频长史 | 乐咕乐股 | akshare `stock_index_pe_lg` | 月 / 2005→ | 沪深300/上证50/中证500/中证1000/中证800/中证100/上证180/上证380/创业板50/深证红利/上证红利 |
| S4 | 指数 PE 周频史 | 蛋卷基金 | `GET danjuanfunds.com/djapi/index_eva/pe_history/{code}?day=all` | 周 / 2016→ | 沪深300/中证500/中证1000/中证红利/上证50/科创50/创业板指/深证成指/中证100/深证红利/上证红利 等 |
| S5 | 中证官方 PE（滚动）+ 行情 | 中证指数官网 | `GET csindex.com.cn/csindex-home/perf/index-perf?indexCode={code}&...` | 日 / 2005→ | 全部中证系列（`peg` 字段即官方近四季滚动市盈率） |
| S6 | 中证官方 PE/股息率（两种股本口径） | 中证指数官网 | `GET oss-ch.csindex.com.cn/.../autofile/indicator/{code}indicator.xls` | 日（近 20 日窗口） | 000300/000905/000852/000985/000016/000688/000922/000010/000906 |
| S7 | 估值快照（PE/PB/PE分位/股息率） | 蛋卷基金 | `GET danjuanfunds.com/djapi/index_eva/dj` | 快照（63 指数） | 含中证系列与深证系列 |
| S8 | 市场上层/深/创业板/科创板股息率 | 乐咕乐股 | akshare `stock_a_gxl_lg` | 日 / 2005→ | 市场级股息率长历史 |

### 2.2 目标指数清单

| code | 名称 | 组 | 数据可用性 |
|---|---|---|---|
| 000300 | 沪深300 | 宽基 | S3 月 / S4 周 / S5 日 / S6 快照 |
| 000905 | 中证500 | 宽基 | S3 月 / S4 周 / S5 日 / S6 快照 |
| 000852 | 中证1000 | 宽基 | S3 月 / S4 周 / S5 日 / S6 快照 |
| 000985 | 中证全指 | 全市场 | S5 日 / S6 快照（无 S3/S4 历史） |
| 000016 | 上证50 | 宽基 | S3 月 / S4 周 / S5 日 / S6 快照 |
| 000688 | 科创50 | 成长 | S4 周 / S5 日 / S6 快照 |
| 399006 | 创业板指 | 成长 | S4 周 / S6 快照 / S7 行情 |
| 000922 | 中证红利 | 红利 | S4 周 / S5 日 / S6 快照 |
| 000015 | 上证红利 | 红利 | S3 月 / S4 周 / S6 快照 |
| 000906 | 中证800 | 宽基 | S3 月 / S6 快照 |

主界面默认展示前 8 个（000985 与 000906 作为补充行）。

### 2.3 口径统一规则

1. **主 PE 口径 = 中证官网 `index-perf` 的 `peg` 字段**（中证官方「近四季滚动市盈率」TTM，日频，2005 年至今，含中证全指）。已用 CEIC 同口径序列交叉验证：2026-10-20 中证 peg 12.91 ≈ CEIC 12.91。
   - 中证 `indicator.xls` 的 `市盈率1/市盈率2` 是**股本口径差异**（总股本 vs 计算用股本），不是静态/滚动差异，两者作为辅助口径落库。
   - 蛋卷 PE 与乐咕 PE 方法不同，仅作交叉校验与长历史补齐。
2. **债券基准**统一用「中债国债收益率曲线 10 年期」。备用基准（30Y 国债、AAA 中短期票据 3Y/5Y）在配置里可切换，切换后所有派生指标同步重算。
3. **股息率差**采用中证 `indicator.xls` 的「股息率2（计算用股本）」口径。
4. **分位数窗口**默认「近 10 年」，UI 可切 3 年 / 5 年 / 10 年 / 全历史。
5. **PE 主序列按源优先级合并**：中证 peg（日频）> 蛋卷周频（2016→）> 乐咕月频（2005→）。稀疏观测按「前值填充」摊到交易日历上，每行记录来源与观测日。**不同源的观测不混用于同一天**（同日取高优先级源）。
6. **格雷厄姆指数与 ERP 数值相同**（同一定义 `1/PE×100 − 债券收益率`），库中统一以指标名 `erp` 存储，界面标注为「格雷厄姆指数 / ERP」。

### 2.4 已知缺口与应对

| 缺口 | 应对 |
|---|---|
| 000985 无蛋卷/乐咕历史 | 中证 `index-perf` 提供其 2005 年至今的日频 PE（`peg`），主指标曲线完整 |
| 创业板指 399006 无中证数据（深证系） | 用蛋卷周频 PE（2016→）前值填充；界面标注实际来源与起始日 |
| 股息率历史短（S5 仅 20 日窗口） | 每日跑批把 S5 快照累积入库；从今天起自动变长。当前值用蛋卷快照补 |
| 股息率无长历史 | 乐咕「市场上层/深/创业板/科创板股息率」提供 2005→ 日频市场级序列，作为市场层面股债性价比的长历史补充 |
| PE 口径三家不一致 | 主口径固定中证官方 `peg`；S3/S4 作为交叉校验列存入 `index_valuation`，界面标注来源 |
| GitHub Actions runner 在境外可能抓不到境内源 | 单源失败不阻塞；沿用上次成功值；`data_quality` 表记录每个源状态；UI「数据健康」面板显示降级告警 |

---

## 3. 指标计算（`metrics.py`，纯函数，无 IO）

```
gi      = (1 / pe_ttm) * 100          # 股权收益率倒数，%
erp     = gi - bond_yield_10y         # 格雷厄姆指数 / ERP，百分点
pct     = rank(erp, window) * 100     # 分位数 0-100
dy_spread = dividend_yield - bond_yield_10y
style   = erp(000905) - erp(000852)   # 风格利差，再取分位
```

- 分位数算法：`percentileofscore`（线性插值），窗口不足时返回 `None` 并在 UI 显示「样本不足」
- 温度灯映射（ERP 分位）：≤20 绿（便宜）/ 20-40 黄绿 / 40-60 黄 / 60-80 橙 / ≥80 红（贵）
- 配置建议映射表（`config.py` 内可调，默认）：

  | ERP 分位 | 建议权益仓位 |
  |---|---|
  | ≤10% | 80–100% |
  | 10–30% | 60–80% |
  | 30–70% | 40–60% |
  | 70–90% | 20–40% |
  | ≥90% | 0–20% |

- 回测：按上述映射在历史 ERP 分位上切换「沪深300 vs 10Y 国债」，输出年化收益、年化波动、最大回撤、切换次数。**仅作参考展示，页面注明规则化映射非投资建议**。

---

## 4. 系统架构

```
xquant/
├── pyproject.toml
├── requirements.txt              # akshare, fastapi, uvicorn, pandas, numpy, py-mini-racer
├── xquant/
│   ├── __init__.py
│   ├── config.py                 # 指数清单、债券基准、仓位映射、源开关
│   ├── sources/
│   │   ├── base.py               # Source 协议：name / fetch() / describe()
│   │   ├── chinabond.py          # S1
│   │   ├── legulegu.py           # S2 S3
│   │   ├── csindex.py            # S5 S7
│   │   └── danjuan.py            # S4 S6
│   ├── store.py                  # SQLite schema + upsert + 查询
│   ├── metrics.py                # 第 3 节全部计算，纯函数
│   ├── pipeline.py               # 抓取→标准化→落库→算指标→导出
│   ├── server.py                 # FastAPI
│   └── cli.py                    # update | serve | export | backfill
├── web/
│   ├── index.html
│   ├── app.js
│   ├── style.css
│   └── vendor/echarts.min.js     # 本地 vendor，不依赖 CDN
├── data/
│   ├── market.db                 # SQLite
│   └── snapshot.json             # 导出给静态前端/分享用
├── scripts/
│   ├── install_launchd.sh        # 本机定时（可选备用）
│   └── launchd/com.xquant.update.plist
├── tests/
│   ├── test_metrics.py
│   └── test_store.py
├── docs/superpowers/specs/
└── .github/workflows/update.yml
```

### 4.1 数据库 schema（SQLite）

```sql
CREATE TABLE bond_yield (
  curve TEXT, date TEXT, tenor TEXT, yield REAL,
  PRIMARY KEY (curve, date, tenor)
);
CREATE TABLE index_valuation (
  index_code TEXT, date TEXT, source TEXT,
  pe REAL, pe_ttm REAL, pb REAL, dividend_yield REAL,
  PRIMARY KEY (index_code, date, source)
);
CREATE TABLE index_price (
  index_code TEXT, date TEXT, close REAL, source TEXT,
  PRIMARY KEY (index_code, date, source)
);
CREATE TABLE metric_series (
  index_code TEXT, date TEXT, metric TEXT, value REAL, freq TEXT, source TEXT,
  PRIMARY KEY (index_code, date, metric, freq)
);
CREATE TABLE data_quality (
  ts TEXT, source TEXT, status TEXT, rows INTEGER, message TEXT, duration_ms INTEGER
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
```

`metric` 取值：`gi`、`erp`、`erp_pct_3y/5y/10y/all`、`dy_spread`、`style_spread`、`style_pct`。

### 4.2 API

| 路由 | 方法 | 说明 |
|---|---|---|
| `/` | GET | 前端页面 |
| `/api/snapshot` | GET | 所有指数当前值 + 分位 + 温度 + 数据新鲜度 + 仓位建议 |
| `/api/series?index=000300&metric=erp&window=10y` | GET | 单序列时间序列（含 freq、来源标注） |
| `/api/compare` | GET | 多指数 ERP 对比（绝对/标准化） |
| `/api/style` | GET | 风格利差 + 信号 |
| `/api/allocation` | GET | 仓位建议 + 回测统计 |
| `/api/health` | GET | 各数据源状态、最近错误 |
| `/api/refresh` | POST | 触发本机抓取一次（需本机可访问境内源） |

### 4.3 前端（浅色简洁）

- 配色：白底 `#ffffff`、正文 `#1f2328`、主色 `#2563eb`、涨/贵 `#dc2626`、跌/便宜 `#16a34a`、网格 `#e6e8eb`
- 字体：系统字体栈（`-apple-system, "PingFang SC", "Microsoft YaHei", sans-serif`）
- 图表：ECharts 浅色主题，本地 vendor
- 布局：顶部 8 张指标卡（横向自适应）→ ERP 主图 → 股息率差图 → 多指数对比 → 风格图 → 配置建议表 → 数据健康折叠面板
- 每个图表标题右侧带「口径」小字标注（如「中证官方 PE(TTM) − 中债10Y国债」），并标注序列起始日期
- 「刷新数据」按钮在右上角，点击后调 `/api/refresh`，按钮显示进度，完成后热更新

---

## 5. 数据更新机制

### 5.1 GitHub Actions（用户已有仓库，主方案）

仓库地址待用户提供（实现收尾阶段需要 `git remote add` + 首次 push）；本地代码不依赖该地址即可开发与运行。

`.github/workflows/update.yml`：
- cron `30 8 * * 1-5`（UTC 16:30 = 北京时间 16:30）
- job：装依赖 → `python -m xquant.cli update` → `git commit` 数据文件（`data/market.db`、`data/snapshot.json`）→ push
- 用 `concurrency` 防止并发写；用 `actions/checkout` v4 + `python/setup-python` v5
- 失败时只发日志，不破坏仓库里的既有数据（update 命令先写临时文件，成功才覆盖）

### 5.2 本地手动刷新

- 页面按钮 → `/api/refresh` → 后端在后台线程跑 `pipeline.run()`，进度写入 `meta` 表，前端轮询 `/api/health` 显示状态
- CLI：`python -m xquant.cli update`（同一套逻辑）

### 5.3 本机定时（可选备用）

`scripts/install_launchd.sh` 安装 launchd 任务，交易日 16:30 跑 update。

---

## 6. 错误处理与降级

| 场景 | 行为 |
|---|---|
| 某个数据源抓取失败 | 该源本次不更新，沿用库中旧值；`data_quality` 记 `fail` + 错误信息；其他源正常入库；API 正常返回，`/api/health` 标红；UI 数据健康面板提示「XX 数据源已 N 天未更新」 |
| 所有源失败 | 不覆盖已有数据文件，退出码非 0，CI 不提交 |
| 某指数 PE 缺失 | 该指数该日期不写入 metric_series，UI 上标「数据缺失」灰显，不插值 |
| 分位窗口样本不足 | 分位返回 `null`，UI 显示「样本不足（N 个观测）」 |
| 前端请求失败 | 显示错误条 + 重试按钮，页面其余部分保持上次渲染 |

---

## 7. 测试

- `tests/test_metrics.py`：
  - GI 计算正确性（给定 PE=10、债券 2% → GI=8）
  - 分位数边界（当前值为历史最大 → 100，最小 → 0）
  - 样本不足返回 None
  - 仓位映射表单调性（分位越高建议仓位越低）
- `tests/test_store.py`：upsert 幂等（同日同源重复写入不产生重复行）、schema 初始化
- 不做网络测试桩（源都是线上免费接口，靠真实跑批验证）

---

## 8. 验收标准

1. `python -m xquant.cli update` 在本地能跑通，库里出现 8 个指数的 GI/ERP 序列与 10Y 国债曲线
2. `python -m xquant.cli serve` 后打开页面：指标卡有值且分位合理（与蛋卷/乐咕口径量级一致，允许方法差异）
3. 页面 7 个板块均有内容，切换指数/窗口/债券基准能联动
4. 断开某个源（改配置关掉）后再跑 update，不崩溃，已有数据完好
5. `/api/refresh` 能在页面上触发一次抓取并热更新
6. GitHub Actions workflow 文件就位，用户 push 到自己的仓库后能跑出数据文件
7. 页面明示：数据来源、口径、频率、历史起始日，以及「规则化映射非投资建议」

---

## 9. 风险清单

| 风险 | 影响 | 缓解 |
|---|---|---|
| GitHub runner 抓不到中债/中证 | 自动更新失败 | 已有降级策略 + 本机 launchd 备选；用户也可改成本机为主 |
| 蛋卷/乐咕接口变更或加风控 | 该源失效 | 每个源独立模块，改动只影响一个；S5 中证官方作为主要 PE 源 |
| PE 口径三家不一致 | 数值与外部网站对不上 | 主口径固定中证官方 + 页面标注来源 + 交叉校验列 |
| 股息率历史从零开始 | 股息率差曲线短 | 从今日起累积；页面标注起始日 |
| 浅色主题图表细节多 | 视觉不统一 | 统一 ECharts 浅色主题 + CSS 变量，统一间距/字号规范 |
