/* xquant 前端：浅色简洁仪表盘
 *
 * 两种数据来源：
 *   1. 本地服务：fetch /api/*
 *   2. GitHub Pages 静态版：window.XQ_STATIC（由 `python -m xquant.cli static` 预生成）
 */
(function () {
  "use strict";

  const STATIC = window.XQ_STATIC || null;
  const state = { snapshot: null, indexes: [], charts: {} };

  const fmt = (v, digits = 2) =>
    v === null || v === undefined || Number.isNaN(v) ? "—" : Number(v).toFixed(digits);

  const tempClass = (t) =>
    t === "便宜" || t === "偏低" ? "cheap" : t === "偏贵" || t === "很贵" ? "expensive" : "unknown";

  async function getJSON(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(url + " → " + r.status);
    return r.json();
  }

  function staticSeries(id) {
    const arr = STATIC.series[id];
    if (!arr) return [];
    const out = [];
    for (let i = 0; i < arr.length; i++) {
      if (arr[i] !== null && arr[i] !== undefined) out.push([STATIC.dates[i], arr[i]]);
    }
    return out;
  }

  const dataSnapshot = () => (STATIC ? Promise.resolve(STATIC.snapshot) : getJSON("/api/snapshot"));

  async function dataSeries(index, metric) {
    if (!STATIC) return getJSON(`/api/series?index=${index}&metric=${metric}`);
    const id = metric === "dy_spread" ? `dy:${index}` : `${metric}:${index}`;
    const points = staticSeries(id);
    if (!points.length) throw new Error(`no data for ${index}/${metric}`);
    return { index_code: index, metric, points };
  }

  async function dataCompare() {
    if (!STATIC) return getJSON("/api/compare?metric=erp");
    const series = STATIC.snapshot.indexes
      .map((i) => ({ code: i.code, name: i.name, group: i.group, points: staticSeries(`erp:${i.code}`) }))
      .filter((s) => s.points.length);
    return { metric: "erp", series };
  }

  const dataStyle = () => (STATIC ? Promise.resolve(STATIC.style) : getJSON("/api/style"));
  const dataAllocation = () =>
    STATIC ? Promise.resolve(STATIC.allocation) : getJSON("/api/allocation");
  const dataHealth = () => (STATIC ? Promise.resolve(STATIC.health) : getJSON("/api/health"));

  function renderCards(snap) {
    document.getElementById("cards").innerHTML = snap.indexes
      .map((i) => {
        const alloc = i.allocation ? `${i.allocation.equity_min}%–${i.allocation.equity_max}%` : "—";
        return `<div class="card">
          <h3>${i.name} <span class="muted">${i.code}</span></h3>
          <div class="value">${fmt(i.erp)}<span class="sub"> %</span></div>
          <div class="sub">PE ${fmt(i.pe)} · 分位 ${fmt(i.percentile, 0)}% · ${i.date || "—"}</div>
          <span class="badge ${tempClass(i.temperature)}">${i.temperature}</span>
          <div class="sub">建议权益仓位 ${alloc}</div>
        </div>`;
      })
      .join("");
    document.getElementById("bond-label").textContent = snap.bond.label;
    document.getElementById("updated-at").textContent =
      "更新于 " + (snap.generated_at || "").replace("T", " ").slice(0, 16);
  }

  const chartBase = {
    backgroundColor: "transparent",
    textStyle: { color: "#6b7280", fontFamily: "-apple-system, PingFang SC, sans-serif" },
    grid: { left: 56, right: 24, top: 30, bottom: 44 },
    tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
  };

  function chart(id) {
    if (state.charts[id]) return state.charts[id];
    const c = echarts.init(document.getElementById(id), null, { renderer: "canvas" });
    window.addEventListener("resize", () => c.resize());
    state.charts[id] = c;
    return c;
  }

  function quantileLines(values, lowPct, highPct) {
    const sorted = values.slice().sort((a, b) => a - b);
    if (!sorted.length) return [];
    const at = (p) => sorted[Math.min(sorted.length - 1, Math.floor((p / 100) * sorted.length))];
    return [
      { yAxis: at(highPct), name: `${highPct}分位`, lineStyle: { color: "#dc2626", type: "dashed" } },
      { yAxis: at(lowPct), name: `${lowPct}分位`, lineStyle: { color: "#16a34a", type: "dashed" } },
    ];
  }

  async function renderERP() {
    const code = document.getElementById("erp-index").value;
    const win = document.getElementById("erp-window").value;
    const data = await dataSeries(code, "erp");
    const points = data.points;
    const values = points.map((p) => p[1]);
    const c = chart("chart-erp");
    c.setOption({
      ...chartBase,
      tooltip: { trigger: "axis", valueFormatter: (v) => fmt(v) + " %" },
      xAxis: { type: "category", data: points.map((p) => p[0]), boundaryGap: false },
      yAxis: { type: "value", name: "%", scale: true },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 16 }],
      series: [
        {
          name: "格雷厄姆指数", type: "line", showSymbol: false, data: values,
          lineStyle: { width: 1.8, color: "#2563eb" },
          areaStyle: { color: "rgba(37,99,235,0.08)" },
          markLine: {
            silent: true, symbol: "none", label: { formatter: "{b}" },
            data: quantileLines(values, 30, 70),
          },
        },
      ],
    });
    const spec = state.snapshot.indexes.find((i) => i.code === code);
    document.getElementById("erp-caption").textContent =
      `口径：中证官方近四季滚动市盈率(TTM) ÷ 100 − ${state.snapshot.bond.label}；` +
      `序列 ${points.length ? points[0][0] : "—"} ~ ${points.length ? points[points.length - 1][0] : "—"}；` +
      `当前 ${fmt(spec && spec.erp)}%（${spec ? spec.temperature : "—"}，近${win === "all" ? "全历史" : win.replace("y", "年")}分位 ${fmt(spec && spec.percentile, 0)}%）。`;
  }

  async function renderDY() {
    const code = document.getElementById("dy-index").value;
    const c = chart("chart-dy");
    let data;
    try {
      data = await dataSeries(code, "dy_spread");
    } catch (e) {
      c.clear();
      document.getElementById("dy-caption").textContent = "该指数暂无股息率数据。";
      return;
    }
    const points = data.points;
    c.setOption({
      ...chartBase,
      tooltip: { trigger: "axis", valueFormatter: (v) => fmt(v) + " %" },
      xAxis: { type: "category", data: points.map((p) => p[0]), boundaryGap: false },
      yAxis: { type: "value", name: "%", scale: true },
      series: [{
        name: "股息率差", type: "line", showSymbol: false, data: points.map((p) => p[1]),
        lineStyle: { width: 1.6, color: "#0891b2" },
        areaStyle: { color: "rgba(8,145,178,0.08)" },
      }],
    });
    document.getElementById("dy-caption").textContent =
      `口径：中证官方股息率（计算用股本口径） − ${state.snapshot.bond.label}；` +
      `序列 ${points.length ? points[0][0] : "—"} ~ ${points.length ? points[points.length - 1][0] : "—"}。`;
  }

  async function renderCompare() {
    const data = await dataCompare();
    const palette = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2", "#be185d", "#4d7c0f", "#0f766e", "#a16207"];
    const c = chart("chart-compare");
    const dates = data.series.length ? data.series[0].points.map((p) => p[0]) : [];
    const dateSet = new Set(dates);
    data.series.forEach((s) => s.points.forEach((p) => dateSet.add(p[0])));
    const axis = Array.from(dateSet).sort();
    c.setOption({
      ...chartBase,
      legend: { type: "scroll", top: 0 },
      tooltip: { trigger: "axis" },
      xAxis: { type: "category", data: axis },
      yAxis: { type: "value", name: "%", scale: true },
      dataZoom: [{ type: "inside" }, { type: "slider", height: 14 }],
      series: data.series.map((s, i) => {
        const map = new Map(s.points.map((p) => [p[0], p[1]]));
        return {
          name: s.name, type: "line", showSymbol: false, connectNulls: true,
          data: axis.map((d) => (map.has(d) ? map.get(d) : null)),
          lineStyle: { width: 1.3, color: palette[i % palette.length] },
        };
      }),
    });
  }

  async function renderStyle() {
    const data = await dataStyle();
    const c = chart("chart-style");
    const points = data.points || [];
    c.setOption({
      ...chartBase,
      tooltip: { trigger: "axis", valueFormatter: (v) => fmt(v) + " %" },
      xAxis: { type: "category", data: points.map((p) => p[0]), boundaryGap: false },
      yAxis: { type: "value", name: "%", scale: true },
      series: [{
        name: "风格利差", type: "line", showSymbol: false, data: points.map((p) => p[1]),
        lineStyle: { width: 1.6, color: "#7c3aed" },
        areaStyle: { color: "rgba(124,58,237,0.08)" },
        markLine: {
          silent: true, symbol: "none", label: { formatter: "{b}" },
          data: [{ yAxis: 0, name: "平局", lineStyle: { color: "#9ca3af", type: "dashed" } }],
        },
      }],
    });
    document.getElementById("style-caption").textContent =
      `最新 ${fmt(data.latest && data.latest[1])}%，近10年分位 ${fmt(data.percentile, 0)}%，信号：${data.signal}` +
      `（分位高=小盘 ERP 更高=小盘占优）`;
  }

  async function renderAllocation() {
    const data = await dataAllocation();
    const rows = data.items
      .filter((i) => i.erp !== null)
      .map((i) => `<tr><td>${i.name}</td><td>${fmt(i.erp)}</td><td>${fmt(i.percentile, 0)}%</td>
        <td>${i.temperature}</td><td>${i.allocation ? i.allocation.equity_min + "%–" + i.allocation.equity_max + "%" : "—"}</td></tr>`)
      .join("");
    const bt = data.backtest || {};
    let btHtml = "";
    if (bt.available) {
      const pct = (v) => (v === null || v === undefined ? "—" : (v * 100).toFixed(1) + "%");
      btHtml = `<h3 class="subtitle">规则回测：沪深300 vs ${bt.benchmark}
        （${bt.period[0]} ~ ${bt.period[1]}，月度调仓 ${bt.switches} 次）</h3>
        <table><thead><tr><th>组合</th><th>年化收益</th><th>年化波动</th><th>最大回撤</th><th>累计收益</th></tr></thead>
        <tbody>
          <tr><td>股债切换（按 ERP 分位）</td><td>${pct(bt.strategy.cagr)}</td><td>${pct(bt.strategy.vol)}</td>
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
       <p class="caption">规则：ERP 分位 ≤10% → 权益 0–20%；≤30% → 20–40%；≤70% → 40–60%；≤90% → 60–80%；其余 → 80–100%。<br>注：ERP 分位越高代表股票相对债券越便宜，故仓位随分位递增。</p>
       ${btHtml}`;
  }

  async function renderHealth() {
    const data = await dataHealth();
    const rows = (data.quality || [])
      .map((q) => `<tr><td>${q.source}</td><td>${q.status === "ok" ? "正常" : "失败"}</td><td>${q.rows ?? ""}</td>
        <td>${q.ts || ""}</td><td style="text-align:left">${(q.message || "").slice(0, 60)}</td></tr>`)
      .join("");
    document.getElementById("health").innerHTML =
      `<table><thead><tr><th>数据源</th><th>状态</th><th>行数</th><th>时间</th><th>说明</th></tr></thead>
       <tbody>${rows || "<tr><td colspan='5' class='muted'>暂无抓取记录</td></tr>"}</tbody></table>
       <p class="caption">上次运行：${data.last_run || "—"}</p>`;
  }

  function fillIndexSelects(indexes) {
    const erp = document.getElementById("erp-index");
    const dy = document.getElementById("dy-index");
    if (erp.options.length) return;
    indexes.forEach((i) => {
      const o = document.createElement("option");
      o.value = i.code; o.textContent = `${i.name} (${i.code})`;
      erp.appendChild(o);
    });
    erp.value = "000300";
    ["MKT_SH", "MKT_SZ", "MKT_GEM", "MKT_STAR"].forEach((code) => {
      const name = { MKT_SH: "上证A股", MKT_SZ: "深证A股", MKT_GEM: "创业板", MKT_STAR: "科创板" }[code];
      const o = document.createElement("option");
      o.value = code; o.textContent = `${name}（市场级，长历史）`;
      dy.appendChild(o);
    });
    indexes.forEach((i) => {
      const o = document.createElement("option");
      o.value = i.code; o.textContent = `${i.name} (${i.code})`;
      dy.appendChild(o);
    });
    erp.addEventListener("change", renderERP);
    dy.addEventListener("change", renderDY);
    document.getElementById("erp-window").addEventListener("change", renderERP);
  }

  async function renderAll() {
    state.snapshot = await dataSnapshot();
    renderCards(state.snapshot);
    fillIndexSelects(state.snapshot.indexes);
    await Promise.all([
      renderERP(), renderDY(), renderCompare(), renderStyle(), renderAllocation(), renderHealth(),
    ]);
  }

  document.addEventListener("DOMContentLoaded", async () => {
    const btn = document.getElementById("refresh-btn");
    if (STATIC) {
      // 静态版（GitHub Pages）没有后端，只展示自动更新的数据
      btn.textContent = "静态版 · 数据每日自动更新";
      btn.disabled = true;
      btn.style.opacity = "0.75";
      btn.style.cursor = "default";
    } else {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        btn.textContent = "抓取中…";
        try {
          await fetch("/api/refresh", { method: "POST" });
          const timer = setInterval(async () => {
            const h = await getJSON("/api/health");
            if (h.refresh && !h.refresh.running) {
              clearInterval(timer);
              btn.disabled = false;
              btn.textContent = "刷新数据";
              await renderAll();
            }
          }, 2000);
        } catch (err) {
          btn.disabled = false;
          btn.textContent = "刷新数据";
        }
      });
    }
    try {
      await renderAll();
    } catch (err) {
      document.getElementById("cards").innerHTML =
        `<div class="card"><h3>加载失败</h3><div class="sub">${err.message}</div></div>`;
    }
  });

  window.XQ = { state, renderAll, getJSON };
})();
