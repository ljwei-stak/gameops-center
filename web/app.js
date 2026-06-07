const state = {
  region: "all",
  status: "all",
  logLevel: "ALL",
  regions: [],
  timer: null,
};

const els = {
  metrics: document.querySelector("#metricsGrid"),
  regions: document.querySelector("#regionFilters"),
  regionCards: document.querySelector("#regionCards"),
  serverRows: document.querySelector("#serverRows"),
  alertList: document.querySelector("#alertList"),
  deploymentList: document.querySelector("#deploymentList"),
  logConsole: document.querySelector("#logConsole"),
  deployRegion: document.querySelector("#deployRegion"),
  deployStrategy: document.querySelector("#deployStrategy"),
  deployVersion: document.querySelector("#deployVersion"),
  operator: document.querySelector("#operator"),
  statusFilter: document.querySelector("#statusFilter"),
  logFilter: document.querySelector("#logFilter"),
  autoRefresh: document.querySelector("#autoRefresh"),
  refreshBtn: document.querySelector("#refreshBtn"),
  deployForm: document.querySelector("#deployForm"),
  clock: document.querySelector("#clock"),
  toast: document.querySelector("#toast"),
  trendCanvas: document.querySelector("#trendCanvas"),
};

function formatNumber(value) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function formatPercent(value) {
  return `${(value * 100).toFixed(1)}%`;
}

function normalizeTime(value) {
  if (!value) return "";
  return value.replace("T", " ").replace("+08:00", "");
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "请求失败");
  }
  return data;
}

async function loadAll() {
  try {
    const query = new URLSearchParams({
      region: state.region,
      status: state.status,
    });
    const logQuery = new URLSearchParams({
      level: state.logLevel,
      limit: "80",
    });
    const [overview, servers, alerts, logs, deployments] = await Promise.all([
      api("/api/overview"),
      api(`/api/servers?${query}`),
      api("/api/alerts"),
      api(`/api/logs?${logQuery}`),
      api("/api/deployments"),
    ]);
    state.regions = overview.regions;
    renderMetrics(overview.summary);
    renderRegionFilters();
    renderRegionCards(overview.regions);
    renderServers(servers);
    renderAlerts(alerts);
    renderDeployments(deployments);
    renderLogs(logs);
    renderDeployRegionOptions();
    drawTrend(overview.trend);
    syncIcons();
  } catch (error) {
    showToast(error.message);
  }
}

function renderMetrics(summary) {
  const metrics = [
    {
      label: "在线玩家",
      value: formatNumber(summary.online_players),
      sub: `容量 ${formatPercent(summary.capacity_rate)}`,
      tone: "green",
      icon: "users",
    },
    {
      label: "健康节点",
      value: `${summary.healthy_servers}/${summary.total_servers}`,
      sub: `平均 CPU ${summary.avg_cpu}%`,
      tone: "blue",
      icon: "server-cog",
    },
    {
      label: "活跃告警",
      value: summary.active_alerts,
      sub: `平均内存 ${summary.avg_memory}%`,
      tone: summary.active_alerts > 0 ? "amber" : "green",
      icon: "bell",
    },
    {
      label: "P95 延迟",
      value: `${summary.avg_latency_p95}ms`,
      sub: "全战区平均",
      tone: summary.avg_latency_p95 > 130 ? "red" : "violet",
      icon: "gauge",
    },
  ];
  els.metrics.innerHTML = metrics
    .map(
      (metric) => `
        <article class="metric-card">
          <div class="metric-top">
            <div>
              <p class="eyebrow">${metric.label}</p>
              <div class="metric-value">${metric.value}</div>
            </div>
            <div class="metric-icon tone-${metric.tone}">
              <i data-lucide="${metric.icon}"></i>
            </div>
          </div>
          <div class="metric-sub">${metric.sub}</div>
        </article>
      `
    )
    .join("");
}

function renderRegionFilters() {
  const options = [{ id: "all", name: "全部" }, ...state.regions];
  els.regions.innerHTML = options
    .map(
      (region) => `
        <button class="segment ${state.region === region.id ? "active" : ""}" data-region="${region.id}">
          ${region.name}
        </button>
      `
    )
    .join("");
}

function renderDeployRegionOptions() {
  const current = els.deployRegion.value || "all";
  const options = [{ id: "all", name: "全部战区" }, ...state.regions];
  els.deployRegion.innerHTML = options
    .map((region) => `<option value="${region.id}">${region.name}</option>`)
    .join("");
  els.deployRegion.value = options.some((item) => item.id === current) ? current : "all";
}

function renderRegionCards(regions) {
  els.regionCards.innerHTML = regions
    .map(
      (region) => `
        <article class="region-item">
          <div class="region-main">
            <div>
              <strong>${region.name}</strong>
              <span>${region.city} · ${region.owner} · ${region.server_count} 台</span>
            </div>
            <span>${region.traffic_weight}%</span>
          </div>
          <div class="meter-line">
            <div class="meter ${region.capacity_rate > 0.9 ? "warn" : ""}">
              <span style="width:${Math.min(region.capacity_rate * 100, 100)}%"></span>
            </div>
            <b>${formatPercent(region.capacity_rate)}</b>
          </div>
          <div class="region-actions">
            <button class="button small" data-action="traffic" data-region="${region.id}" data-delta="-5" title="降低流量">
              <i data-lucide="minus"></i><span>-5</span>
            </button>
            <button class="button small" data-action="traffic" data-region="${region.id}" data-delta="5" title="提升流量">
              <i data-lucide="plus"></i><span>+5</span>
            </button>
          </div>
        </article>
      `
    )
    .join("");
}

function renderServers(servers) {
  if (!servers.length) {
    els.serverRows.innerHTML = `<tr><td colspan="8" class="empty">没有符合条件的服务器</td></tr>`;
    return;
  }
  els.serverRows.innerHTML = servers
    .map(
      (server) => `
        <tr>
          <td>
            <div class="server-name">
              <strong>${server.name}</strong>
              <span>${server.id}</span>
              ${statusChip(server.status)}
            </div>
          </td>
          <td>${server.game_mode}</td>
          <td>${formatNumber(server.players)} / ${formatNumber(server.capacity)}</td>
          <td>${meter(server.cpu, "%")}</td>
          <td>${meter(server.memory, "%")}</td>
          <td>${server.latency_p95}ms</td>
          <td>${server.version}</td>
          <td>
            <button class="button small" data-action="restart" data-id="${server.id}" title="重启服务器">
              <i data-lucide="rotate-cw"></i>
              <span>重启</span>
            </button>
          </td>
        </tr>
      `
    )
    .join("");
}

function statusChip(status) {
  const labels = {
    running: "运行中",
    degraded: "降级",
    maintenance: "维护",
  };
  return `<span class="chip ${status}">${labels[status] || status}</span>`;
}

function meter(value, suffix) {
  const level = value >= 88 ? "crit" : value >= 76 ? "warn" : "";
  return `
    <div class="meter-line">
      <div class="meter ${level}">
        <span style="width:${Math.min(value, 100)}%"></span>
      </div>
      <b>${value}${suffix}</b>
    </div>
  `;
}

function renderAlerts(alerts) {
  if (!alerts.length) {
    els.alertList.innerHTML = `<div class="empty">暂无告警</div>`;
    return;
  }
  els.alertList.innerHTML = alerts
    .slice(0, 8)
    .map(
      (alert) => `
        <article class="alert-item ${alert.severity}">
          <div class="alert-main">
            <div>
              <strong>${alert.title}</strong>
              <span>${alert.server_name} · ${alert.metric}</span>
            </div>
            <span>${alert.severity}</span>
          </div>
          <div class="empty">当前 ${alert.value}，阈值 ${alert.threshold} · ${alert.runbook}</div>
        </article>
      `
    )
    .join("");
}

function renderDeployments(deployments) {
  if (!deployments.length) {
    els.deploymentList.innerHTML = `<div class="empty">暂无发布记录</div>`;
    return;
  }
  els.deploymentList.innerHTML = deployments
    .map(
      (deployment) => `
        <article class="deployment-item">
          <div class="deployment-main">
            <div>
              <strong>${deployment.id} · ${deployment.version}</strong>
              <span>${deployment.strategy} · ${deployment.region}</span>
            </div>
            <span>${deployment.status}</span>
          </div>
          <div class="empty">${normalizeTime(deployment.finished_at)} · ${deployment.operator} · ${deployment.target_count} 台</div>
        </article>
      `
    )
    .join("");
}

function renderLogs(logs) {
  if (!logs.length) {
    els.logConsole.innerHTML = `<div class="empty">暂无日志</div>`;
    return;
  }
  els.logConsole.innerHTML = logs
    .map(
      (log) => `
        <div class="log-line">
          <span class="log-time">${normalizeTime(log.time)}</span>
          <span class="log-level ${log.level}">${log.level}</span>
          <span>${log.source}</span>
          <span>${log.message}</span>
        </div>
      `
    )
    .join("");
}

function drawTrend(trend) {
  const canvas = els.trendCanvas;
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(rect.width * ratio));
  canvas.height = Math.max(1, Math.floor(rect.height * ratio));
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  const width = rect.width;
  const height = rect.height;
  ctx.clearRect(0, 0, width, height);
  drawGrid(ctx, width, height);
  drawLine(ctx, trend.players || [], width, height, "#16806f", "players");
  drawLine(ctx, trend.latency || [], width, height, "#7055b8", "latency");
  ctx.fillStyle = "#667065";
  ctx.font = "12px Microsoft YaHei, Segoe UI, Arial";
  ctx.fillText("在线玩家", 16, 24);
  ctx.fillStyle = "#7055b8";
  ctx.fillText("P95 延迟", 92, 24);
}

function drawGrid(ctx, width, height) {
  ctx.strokeStyle = "#e0e6dc";
  ctx.lineWidth = 1;
  for (let i = 1; i <= 4; i += 1) {
    const y = (height / 5) * i;
    ctx.beginPath();
    ctx.moveTo(14, y);
    ctx.lineTo(width - 14, y);
    ctx.stroke();
  }
}

function drawLine(ctx, values, width, height, color, mode) {
  if (values.length < 2) return;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(1, max - min);
  const padX = 18;
  const padY = 28;
  ctx.strokeStyle = color;
  ctx.lineWidth = mode === "players" ? 2.5 : 2;
  ctx.beginPath();
  values.forEach((value, index) => {
    const x = padX + (index / (values.length - 1)) * (width - padX * 2);
    const y = height - padY - ((value - min) / range) * (height - padY * 2);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

function showToast(message) {
  els.toast.textContent = message;
  els.toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => els.toast.classList.remove("show"), 2600);
}

function syncIcons() {
  if (window.lucide) {
    window.lucide.createIcons({ attrs: { "stroke-width": 1.8 } });
  }
}

function setupEvents() {
  els.refreshBtn.addEventListener("click", loadAll);
  els.statusFilter.addEventListener("change", (event) => {
    state.status = event.target.value;
    loadAll();
  });
  els.logFilter.addEventListener("change", (event) => {
    state.logLevel = event.target.value;
    loadAll();
  });
  els.autoRefresh.addEventListener("change", setupTimer);
  els.regions.addEventListener("click", (event) => {
    const button = event.target.closest("[data-region]");
    if (!button) return;
    state.region = button.dataset.region;
    loadAll();
  });
  els.serverRows.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-action='restart']");
    if (!button) return;
    await performAction(async () => {
      await api(`/api/servers/${button.dataset.id}/restart`, {
        method: "POST",
        body: JSON.stringify({ operator: els.operator.value || "ops-user" }),
      });
      showToast("服务器已重启");
    });
  });
  els.regionCards.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-action='traffic']");
    if (!button) return;
    await performAction(async () => {
      await api("/api/traffic", {
        method: "POST",
        body: JSON.stringify({
          region: button.dataset.region,
          delta: Number(button.dataset.delta),
          operator: els.operator.value || "ops-user",
        }),
      });
      showToast("流量权重已调整");
    });
  });
  els.deployForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    await performAction(async () => {
      const deployment = await api("/api/deploy", {
        method: "POST",
        body: JSON.stringify({
          region: els.deployRegion.value,
          version: els.deployVersion.value.trim(),
          strategy: els.deployStrategy.value,
          operator: els.operator.value.trim() || "release-bot",
        }),
      });
      showToast(`${deployment.id} 发布完成`);
    });
  });
}

async function performAction(action) {
  try {
    await action();
    await loadAll();
  } catch (error) {
    showToast(error.message);
  }
}

function setupTimer() {
  if (state.timer) {
    clearInterval(state.timer);
    state.timer = null;
  }
  if (els.autoRefresh.checked) {
    state.timer = setInterval(loadAll, 8000);
  }
}

function setupClock() {
  const tick = () => {
    els.clock.textContent = new Intl.DateTimeFormat("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(new Date());
  };
  tick();
  setInterval(tick, 1000);
}

setupEvents();
setupClock();
setupTimer();
loadAll();

