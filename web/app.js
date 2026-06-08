const state = {
  region: "all",
  status: "all",
  logLevel: "ALL",
  regions: [],
  user: null,
  token: localStorage.getItem("gameops_token") || "",
  timer: null,
};

const els = {
  loginView: document.querySelector("#loginView"),
  appShell: document.querySelector("#appShell"),
  loginForm: document.querySelector("#loginForm"),
  loginUsername: document.querySelector("#loginUsername"),
  loginPassword: document.querySelector("#loginPassword"),
  ssoToken: document.querySelector("#ssoToken"),
  ssoLoginBtn: document.querySelector("#ssoLoginBtn"),
  metrics: document.querySelector("#metricsGrid"),
  regions: document.querySelector("#regionFilters"),
  regionCards: document.querySelector("#regionCards"),
  workloadRows: document.querySelector("#workloadRows"),
  alertList: document.querySelector("#alertList"),
  deploymentList: document.querySelector("#deploymentList"),
  approvalList: document.querySelector("#approvalList"),
  rollbackList: document.querySelector("#rollbackList"),
  logConsole: document.querySelector("#logConsole"),
  deployRegion: document.querySelector("#deployRegion"),
  deployStrategy: document.querySelector("#deployStrategy"),
  deployVersion: document.querySelector("#deployVersion"),
  deployImage: document.querySelector("#deployImage"),
  statusFilter: document.querySelector("#statusFilter"),
  logFilter: document.querySelector("#logFilter"),
  autoRefresh: document.querySelector("#autoRefresh"),
  refreshBtn: document.querySelector("#refreshBtn"),
  logoutBtn: document.querySelector("#logoutBtn"),
  deployForm: document.querySelector("#deployForm"),
  clock: document.querySelector("#clock"),
  toast: document.querySelector("#toast"),
  trendCanvas: document.querySelector("#trendCanvas"),
  runtimePill: document.querySelector("#runtimePill"),
  userPill: document.querySelector("#userPill"),
  cmdbGrid: document.querySelector("#cmdbGrid"),
  notifyBtn: document.querySelector("#notifyBtn"),
  diagnoseBtn: document.querySelector("#diagnoseBtn"),
  reportBtn: document.querySelector("#reportBtn"),
  aiOutput: document.querySelector("#aiOutput"),
};

const roleLabels = {
  admin: "管理员",
  release_manager: "发布负责人",
  observer: "只读观察员",
};

function has(permission) {
  return Boolean(state.user?.permissions?.includes(permission));
}

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
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const response = await fetch(path, { ...options, headers });
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof data === "string" ? data : data.error;
    throw new Error(message || "请求失败");
  }
  return data;
}

async function bootstrap() {
  if (!state.token) {
    showLogin();
    return;
  }
  try {
    const me = await api("/api/me");
    if (!me.authenticated) throw new Error("登录已过期");
    state.user = me.user;
    showApp();
    await loadAll();
  } catch (error) {
    localStorage.removeItem("gameops_token");
    state.token = "";
    showLogin();
  }
}

function showLogin() {
  els.loginView.hidden = false;
  els.appShell.hidden = true;
  syncIcons();
}

function showApp() {
  els.loginView.hidden = true;
  els.appShell.hidden = false;
  els.userPill.textContent = `${state.user.display_name} · ${roleLabels[state.user.role] || state.user.role}`;
  syncPermissionState();
  setupTimer();
  syncIcons();
}

async function loadAll() {
  try {
    const query = new URLSearchParams({ region: state.region, status: state.status });
    const logQuery = new URLSearchParams({ level: state.logLevel, limit: "100" });
    const [overview, workloads, alerts, logs, deployments, approvals, rollbacks, cmdb] = await Promise.all([
      api("/api/overview"),
      api(`/api/workloads?${query}`),
      api("/api/alerts"),
      api(`/api/logs?${logQuery}`),
      api("/api/deployments"),
      api("/api/deploy/approvals"),
      api("/api/rollbacks"),
      api("/api/cmdb"),
    ]);
    state.regions = overview.regions;
    els.runtimePill.textContent = `runtime ${overview.runtime}`;
    renderMetrics(overview.summary, overview.host);
    renderRegionFilters();
    renderRegionCards(overview.regions);
    renderWorkloads(workloads);
    renderAlerts(alerts);
    renderDeployments(deployments);
    renderApprovals(approvals);
    renderRollbacks(rollbacks);
    renderLogs(logs);
    renderDeployRegionOptions();
    renderCmdb(cmdb);
    drawTrend(overview.trend);
    syncPermissionState();
    syncIcons();
  } catch (error) {
    if (String(error.message).includes("请先登录")) {
      localStorage.removeItem("gameops_token");
      state.token = "";
      showLogin();
      return;
    }
    showToast(error.message);
  }
}

function renderMetrics(summary, host) {
  const metrics = [
    {
      label: "在线玩家",
      value: formatNumber(summary.online_players),
      sub: `容量 ${formatPercent(summary.capacity_rate)}`,
      tone: "green",
      icon: "users",
    },
    {
      label: "健康工作负载",
      value: `${summary.healthy_workloads}/${summary.total_workloads}`,
      sub: `平均 CPU ${summary.avg_cpu}%`,
      tone: "blue",
      icon: "boxes",
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
      sub: `宿主机 CPU ${host.cpu_percent}%`,
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
              <span>${region.city} · ${region.owner} · ${region.workload_count} 个 Deployment</span>
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

function renderWorkloads(workloads) {
  if (!workloads.length) {
    els.workloadRows.innerHTML = `<tr><td colspan="10" class="empty">没有符合条件的工作负载</td></tr>`;
    return;
  }
  els.workloadRows.innerHTML = workloads
    .map(
      (workload) => `
        <tr>
          <td>
            <div class="server-name">
              <strong>${workload.name}</strong>
              <span>${workload.id} · ${workload.game_mode}</span>
              ${statusChip(workload.status)}
            </div>
          </td>
          <td>${workload.namespace}/${workload.deployment}</td>
          <td>${workload.service}</td>
          <td>${formatNumber(workload.players)} / ${formatNumber(workload.capacity)}</td>
          <td>${meter(workload.cpu, "%")}</td>
          <td>${meter(workload.memory, "%")}</td>
          <td>${workload.latency_p95}ms</td>
          <td>
            <div class="image-cell">
              <strong>${workload.version}</strong>
              <span>${workload.image}</span>
            </div>
          </td>
          <td>
            <div class="replica-control">
              <button class="button icon-only small" data-action="scale" data-id="${workload.id}" data-replicas="${workload.replicas - 1}" title="缩容">
                <i data-lucide="minus"></i>
              </button>
              <span>${workload.replicas}/${workload.desired_replicas}</span>
              <button class="button icon-only small" data-action="scale" data-id="${workload.id}" data-replicas="${workload.replicas + 1}" title="扩容">
                <i data-lucide="plus"></i>
              </button>
            </div>
          </td>
          <td>
            <button class="button icon-only small" data-action="restart" data-id="${workload.id}" title="重启容器或滚动重启 Deployment">
              <i data-lucide="rotate-cw"></i>
            </button>
          </td>
        </tr>
      `
    )
    .join("");
}

function statusChip(status) {
  const labels = { running: "运行中", degraded: "降级", maintenance: "维护" };
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
    .slice(0, 10)
    .map(
      (alert) => `
        <article class="alert-item ${alert.severity}">
          <div class="alert-main">
            <div>
              <strong>${alert.title}</strong>
              <span>${alert.workload_name} · ${alert.metric}</span>
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
              <span>${deployment.strategy} · ${deployment.region} · ${deployment.target_count} 个目标</span>
            </div>
            <span class="deploy-status ${deployment.status}">${deployment.status}</span>
          </div>
          <div class="empty">${normalizeTime(deployment.finished_at)} · ${deployment.operator}</div>
        </article>
      `
    )
    .join("");
}

function renderApprovals(approvals) {
  if (!els.approvalList) return;
  if (!approvals.length) {
    els.approvalList.innerHTML = `<div class="empty">No release approvals</div>`;
    return;
  }
  els.approvalList.innerHTML = approvals
    .slice(0, 12)
    .map(
      (approval) => `
        <article class="approval-item">
          <div class="deployment-main">
            <div>
              <strong>${approval.id} - ${approval.version}</strong>
              <span>${approval.strategy} - ${approval.region} - ${approval.requested_by}</span>
            </div>
            <span class="deploy-status ${approval.status}">${approval.status}</span>
          </div>
          <div class="empty">${approval.change_window || "unrestricted"} - ${approval.reason || "no reason"}</div>
          <div class="row-actions">
            ${
              approval.status === "pending" && has("approve_deploy")
                ? `<button class="button small" data-action="approve" data-id="${approval.id}" title="Approve release">
                    <i data-lucide="check"></i><span>Approve</span>
                  </button>
                  <button class="button small" data-action="reject" data-id="${approval.id}" title="Reject release">
                    <i data-lucide="x"></i><span>Reject</span>
                  </button>`
                : ""
            }
            ${
              approval.status === "approved" && has("execute_deploy")
                ? `<button class="button small" data-action="execute" data-id="${approval.id}" title="Execute release">
                    <i data-lucide="play"></i><span>Execute</span>
                  </button>`
                : ""
            }
          </div>
        </article>
      `
    )
    .join("");
}

function renderRollbacks(rollbacks) {
  if (!els.rollbackList) return;
  if (!rollbacks.length) {
    els.rollbackList.innerHTML = `<div class="empty">No rollback records</div>`;
    return;
  }
  els.rollbackList.innerHTML = rollbacks
    .slice(0, 6)
    .map(
      (rollback) => `
        <article class="deployment-item compact">
          <div class="deployment-main">
            <div>
              <strong>${rollback.id} - ${rollback.deployment_id}</strong>
              <span>${rollback.from_version || "-"} -> ${rollback.to_version || "previous image"}</span>
            </div>
            <span>${rollback.operator}</span>
          </div>
          <div class="empty">${normalizeTime(rollback.created_at)} - ${rollback.reason || "no reason"}</div>
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
          <span>${log.actor || "-"}</span>
          <span>${log.message}</span>
        </div>
      `
    )
    .join("");
}

function renderCmdb(cmdb) {
  const regionItems = cmdb.regions
    .map((region) => `<span>${region.name}<b>${region.traffic_weight}%</b></span>`)
    .join("");
  const relationItems = cmdb.relationships
    .slice(0, 8)
    .map(
      (item) => `
        <div class="cmdb-relation">
          <strong>${item.workload_id}</strong>
          <span>${item.namespace}/${item.deployment} → ${item.service}</span>
        </div>
      `
    )
    .join("");
  els.cmdbGrid.innerHTML = `
    <div class="cmdb-card">
      <p class="eyebrow">Regions</p>
      <div class="cmdb-tags">${regionItems}</div>
    </div>
    <div class="cmdb-card">
      <p class="eyebrow">Relations</p>
      <div class="cmdb-relations">${relationItems}</div>
    </div>
  `;
}

function renderAiResult(title, data) {
  if (!data) {
    els.aiOutput.innerHTML = `<div class="empty">暂无 AI 输出</div>`;
    return;
  }
  if (Array.isArray(data.actions) || Array.isArray(data.highlights)) {
    const list = data.actions || data.highlights || [];
    const extra = data.root_causes || data.risks || [];
    els.aiOutput.innerHTML = `
      <article>
        <strong>${data.title || title}</strong>
        <p>${data.summary || ""}</p>
        <ul>${list.map((item) => `<li>${item}</li>`).join("")}</ul>
        <div class="empty">${extra.slice(0, 4).join(" · ")}</div>
      </article>
    `;
  } else {
    els.aiOutput.innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
  }
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
  drawLine(ctx, trend.players || [], width, height, "#16806f");
  drawLine(ctx, trend.latency || [], width, height, "#7055b8");
  drawLine(ctx, trend.host_cpu || [], width, height, "#b36b00");
  ctx.fillStyle = "#16806f";
  ctx.font = "12px Microsoft YaHei, Segoe UI, Arial";
  ctx.fillText("在线玩家", 16, 24);
  ctx.fillStyle = "#7055b8";
  ctx.fillText("P95 延迟", 86, 24);
  ctx.fillStyle = "#b36b00";
  ctx.fillText("宿主机 CPU", 154, 24);
}

function drawGrid(ctx, width, height) {
  ctx.strokeStyle = "#dce3e1";
  ctx.lineWidth = 1;
  for (let i = 1; i <= 4; i += 1) {
    const y = (height / 5) * i;
    ctx.beginPath();
    ctx.moveTo(14, y);
    ctx.lineTo(width - 14, y);
    ctx.stroke();
  }
}

function drawLine(ctx, values, width, height, color) {
  if (values.length < 2) return;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(1, max - min);
  const padX = 18;
  const padY = 30;
  ctx.strokeStyle = color;
  ctx.lineWidth = 2.2;
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

function syncPermissionState() {
  const canDeploy = has("deploy");
  const canRestart = has("restart");
  const canScale = has("scale");
  const canTraffic = has("traffic");
  const canNotify = has("notify");
  const canAi = has("ai");
  setDisabled(els.deployForm.querySelectorAll("input, select, button"), !canDeploy);
  setDisabled(els.workloadRows.querySelectorAll("[data-action='restart']"), !canRestart);
  setDisabled(els.workloadRows.querySelectorAll("[data-action='scale']"), !canScale);
  setDisabled(els.regionCards.querySelectorAll("[data-action='traffic']"), !canTraffic);
  if (els.approvalList) {
    setDisabled(els.approvalList.querySelectorAll("[data-action='approve'], [data-action='reject']"), !has("approve_deploy"));
    setDisabled(els.approvalList.querySelectorAll("[data-action='execute']"), !has("execute_deploy"));
  }
  if (els.deploymentList) {
    setDisabled(els.deploymentList.querySelectorAll("[data-action='rollback']"), !has("rollback"));
  }
  els.notifyBtn.disabled = !canNotify;
  els.diagnoseBtn.disabled = !canAi;
  els.reportBtn.disabled = !canAi;
}

function setDisabled(nodes, disabled) {
  nodes.forEach((node) => {
    node.disabled = disabled;
    node.classList.toggle("is-disabled", disabled);
  });
}

function setupEvents() {
  els.loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const result = await api("/api/login", {
        method: "POST",
        body: JSON.stringify({
          username: els.loginUsername.value.trim(),
          password: els.loginPassword.value,
        }),
      });
      state.token = result.token;
      state.user = result.user;
      localStorage.setItem("gameops_token", result.token);
      showApp();
      await loadAll();
    } catch (error) {
      showToast(error.message);
    }
  });
  els.ssoLoginBtn?.addEventListener("click", async () => {
    try {
      const result = await api("/api/sso/login", {
        method: "POST",
        body: JSON.stringify({ id_token: els.ssoToken.value.trim() }),
      });
      state.token = result.token;
      state.user = result.user;
      localStorage.setItem("gameops_token", result.token);
      showApp();
      await loadAll();
    } catch (error) {
      showToast(error.message);
    }
  });
  document.querySelector(".quick-users").addEventListener("click", (event) => {
    const button = event.target.closest("[data-user]");
    if (!button) return;
    els.loginUsername.value = button.dataset.user;
    els.loginPassword.value = button.dataset.pass;
  });
  els.logoutBtn.addEventListener("click", async () => {
    try {
      await api("/api/logout", { method: "POST", body: "{}" });
    } catch (error) {
      // Logout still clears local state if the session is already gone.
    }
    localStorage.removeItem("gameops_token");
    state.token = "";
    state.user = null;
    showLogin();
  });
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
  els.workloadRows.addEventListener("click", async (event) => {
    const restart = event.target.closest("[data-action='restart']");
    const scale = event.target.closest("[data-action='scale']");
    if (restart) {
      await performAction(async () => {
        await api(`/api/workloads/${restart.dataset.id}/restart`, {
          method: "POST",
          body: JSON.stringify({ operator: state.user.username }),
        });
        showToast("重启动作已提交");
      });
    }
    if (scale) {
      await performAction(async () => {
        await api(`/api/workloads/${scale.dataset.id}/scale`, {
          method: "POST",
          body: JSON.stringify({ replicas: Number(scale.dataset.replicas), operator: state.user.username }),
        });
        showToast("扩缩容动作已提交");
      });
    }
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
          operator: state.user.username,
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
          image: els.deployImage.value.trim(),
          operator: state.user.username,
        }),
      });
      showToast(`${deployment.id} 发布完成`);
    });
  });
  els.approvalList?.addEventListener("click", async (event) => {
    const approve = event.target.closest("[data-action='approve']");
    const reject = event.target.closest("[data-action='reject']");
    const execute = event.target.closest("[data-action='execute']");
    if (approve || reject) {
      const target = approve || reject;
      await performAction(async () => {
        await api(`/api/deploy/approvals/${target.dataset.id}/approve`, {
          method: "POST",
          body: JSON.stringify({
            approved: Boolean(approve),
            reason: reject ? "Rejected from GameOps UI" : "",
          }),
        });
        showToast(approve ? "Release approved" : "Release rejected");
      });
    }
    if (execute) {
      await performAction(async () => {
        await api(`/api/deploy/approvals/${execute.dataset.id}/execute`, {
          method: "POST",
          body: JSON.stringify({ operator: state.user.username }),
        });
        showToast("Release execution started");
      });
    }
  });
  els.notifyBtn.addEventListener("click", async () => {
    await performAction(async () => {
      await api("/api/notify/alerts", {
        method: "POST",
        body: JSON.stringify({ operator: state.user.username }),
      });
      showToast("告警通知已发送或记录为跳过");
    });
  });
  els.diagnoseBtn.addEventListener("click", async () => {
    await performAction(async () => {
      const data = await api("/api/ai/diagnosis");
      renderAiResult("AI 故障诊断", data);
    }, false);
  });
  els.reportBtn.addEventListener("click", async () => {
    await performAction(async () => {
      const data = await api("/api/ai/report");
      renderAiResult("AI 运维报告", data);
    }, false);
  });
}

async function performAction(action, reload = true) {
  try {
    await action();
    if (reload) await loadAll();
  } catch (error) {
    showToast(error.message);
  }
}

function setupTimer() {
  if (state.timer) {
    clearInterval(state.timer);
    state.timer = null;
  }
  if (els.autoRefresh.checked && !els.appShell.hidden) {
    state.timer = setInterval(loadAll, 10000);
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
bootstrap();
