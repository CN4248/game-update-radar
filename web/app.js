/* ============================================================
   Game Update Radar · WebUI
   Vanilla JS, no build step, no CDN.
   ============================================================ */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const ESC_MAP = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ESC_MAP[c]);
const icon = (name, cls = "") => `<svg class="icon ${cls}"><use href="#i-${name}"></use></svg>`;

function safeUrl(url) {
  try {
    const u = new URL(url, location.origin);
    return ["http:", "https:"].includes(u.protocol) ? u.href : "#";
  } catch { return "#"; }
}

function fmtDate(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return esc(value);
  return d.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
}
function fmtFull(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return esc(value);
  return d.toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}
function relTime(value) {
  if (!value) return "从未";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  const diff = Math.max(0, Date.now() - d.getTime());
  if (diff < 60_000) return "刚刚";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`;
  if (diff < 604_800_000) return `${Math.floor(diff / 86_400_000)} 天前`;
  return fmtDate(value);
}
const titleOf = (s, n = 38) => (s && s.length > n ? `${s.slice(0, n)}…` : (s || "（无标题）"));

/* ------------------------------ themes ------------------------------ */
const THEMES = {
  midnight: { label: "深空蓝", mode: "dark", bg: "#070b12", surface: "#111927", surface2: "#172235", surface3: "#1d2b42", text: "#e8eefc", muted: "#8b9bb4", faint: "#5d6b82", border: "rgba(255,255,255,.075)", borderStrong: "rgba(255,255,255,.14)", accent: "#5b8cff", accent2: "#22d3ee", shadow: "0 18px 50px rgba(0,0,0,.28)" },
  aurora: { label: "极光紫", mode: "dark", bg: "#0a0714", surface: "#151126", surface2: "#1d1835", surface3: "#272047", text: "#f0ecff", muted: "#a79bc2", faint: "#746990", border: "rgba(196,181,253,.10)", borderStrong: "rgba(196,181,253,.18)", accent: "#a78bfa", accent2: "#22d3ee", shadow: "0 18px 50px rgba(0,0,0,.34)" },
  forest: { label: "森林绿", mode: "dark", bg: "#07130f", surface: "#0e1f19", surface2: "#142b22", surface3: "#1b382d", text: "#e7f7ef", muted: "#8fb3a2", faint: "#5d7f70", border: "rgba(167,243,208,.09)", borderStrong: "rgba(167,243,208,.16)", accent: "#34d399", accent2: "#a3e635", shadow: "0 18px 50px rgba(0,0,0,.30)" },
  sunset: { label: "日落橙", mode: "dark", bg: "#140b08", surface: "#21130d", surface2: "#2d1a12", surface3: "#3b2319", text: "#fff1e8", muted: "#c2a08e", faint: "#8d6f60", border: "rgba(251,146,60,.10)", borderStrong: "rgba(251,146,60,.18)", accent: "#fb923c", accent2: "#f43f5e", shadow: "0 18px 50px rgba(0,0,0,.32)" },
  rose: { label: "玫瑰红", mode: "dark", bg: "#12080f", surface: "#1f101a", surface2: "#2b1624", surface3: "#3a1d30", text: "#ffedf5", muted: "#c49aaf", faint: "#8d6679", border: "rgba(251,113,133,.10)", borderStrong: "rgba(251,113,133,.18)", accent: "#fb7185", accent2: "#f0abfc", shadow: "0 18px 50px rgba(0,0,0,.32)" },
  ocean: { label: "深海青", mode: "dark", bg: "#04121a", surface: "#0a1e2a", surface2: "#102a39", surface3: "#16384b", text: "#e5f8ff", muted: "#87acbd", faint: "#587c8d", border: "rgba(34,211,238,.10)", borderStrong: "rgba(34,211,238,.18)", accent: "#22d3ee", accent2: "#38bdf8", shadow: "0 18px 50px rgba(0,0,0,.32)" },
  daylight: { label: "浅色日间", mode: "light", bg: "#f4f6fb", surface: "#ffffff", surface2: "#eef2f9", surface3: "#e1e8f3", text: "#111827", muted: "#5f6b7f", faint: "#8b95a7", border: "rgba(15,23,42,.08)", borderStrong: "rgba(15,23,42,.16)", accent: "#3b6ef6", accent2: "#0891b2", shadow: "0 14px 40px rgba(15,23,42,.08)" },
};

function hexToRgba(hex, alpha) {
  let h = String(hex || "").replace("#", "").trim();
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  if (!/^[0-9a-fA-F]{6}$/.test(h)) return `rgba(91,140,255,${alpha})`;
  const n = parseInt(h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
}

function applyTheme(name, overrides = {}, mode = null) {
  const base = THEMES[name] || THEMES.midnight;
  const t = { ...base, ...overrides };
  const root = document.documentElement;
  root.dataset.theme = mode || base.mode || "dark";
  const vars = {
    "--bg": t.bg, "--surface": t.surface, "--surface-2": t.surface2, "--surface-3": t.surface3,
    "--text": t.text, "--muted": t.muted, "--faint": t.faint, "--border": t.border,
    "--border-strong": t.borderStrong, "--accent": t.accent, "--accent-2": t.accent2,
    "--accent-soft": hexToRgba(t.accent, 0.14), "--shadow": t.shadow,
  };
  Object.entries(vars).forEach(([k, v]) => root.style.setProperty(k, v));
  root.style.setProperty("--radius", `${Number(state.uiRadius) || 14}px`);
  root.dataset.density = state.uiDensity || "comfortable";
  state.theme = name;
  state.themeOverrides = { ...overrides };
  try { localStorage.setItem("gur-theme", JSON.stringify({ name, overrides, mode: root.dataset.theme, density: state.uiDensity, radius: state.uiRadius })); } catch { /* ignore */ }
}

function applySettingsTheme() {
  const ui = state.settings?.ui || {};
  state.uiDensity = ui.density || "comfortable";
  state.uiRadius = Number(ui.radius) || 14;
  const overrides = {};
  if (ui.accent) overrides.accent = ui.accent;
  if (ui.accent2) overrides.accent2 = ui.accent2;
  if (ui.background) overrides.bg = ui.background;
  if (ui.surface) overrides.surface = ui.surface;
  if (ui.text) overrides.text = ui.text;
  applyTheme(ui.theme || "midnight", overrides, ui.mode || null);
}

/* ------------------------------ state ------------------------------ */
const ROUTES = {
  dashboard: { title: "雷达总览", sub: "最近公告、扫描状态与系统健康一屏掌握" },
  sources: { title: "监控源", sub: "添加游戏官网、调整扫描频率，并让 AI 判断页面可行性" },
  items: { title: "公告动态", sub: "所有抓取到的公告与版本更新判定结果" },
  alerts: { title: "提醒记录", sub: "每次触发通知的完整投递结果，可手动重发" },
  channels: { title: "通知渠道", sub: "邮件、短信、Telegram、Webhook、Bark 等" },
  ai: { title: "AI 与网络", sub: "模型接入、代理设置与连通性测试" },
  settings: { title: "主题与设置", sub: "自定义颜色主题、扫描策略与数据管理" },
  logs: { title: "运行日志", sub: "扫描、AI 判定、通知投递的排障记录" },
};

const state = {
  route: "dashboard",
  summary: null,
  sources: [],
  channels: [],
  presets: [],
  settings: null,
  meta: null,
  itemsData: { items: [], total: 0 },
  itemsLoaded: false,
  alertsData: { alerts: [], total: 0 },
  alertsLoaded: false,
  logsData: [],
  sourceQuery: "",
  sourceFilter: "all",
  itemQuery: "",
  itemSource: "",
  itemOnlyUpdate: false,
  alertFilter: "all",
  logLevel: "all",
  theme: "midnight",
  themeOverrides: {},
  uiDensity: "comfortable",
  uiRadius: 14,
  lastProbe: null,
  confirmResolve: null,
  booted: false,
};

const FALLBACK_SETTINGS = {
  general: { default_interval_minutes: 60, max_age_days: 45, timezone: "Asia/Shanghai", log_retention: 5000 },
  ai: { enabled: false, provider: "deepseek", base_url: "https://api.deepseek.com/v1", api_key: "", model: "deepseek-chat", temperature: 0.1, max_tokens: 900, timeout_seconds: 45, prompt_extra: "", auto_repair: true, repair_max_attempts: 3, repair_cooldown_minutes: 360 },
  proxy: { enabled: false, http_proxy: "", https_proxy: "", no_proxy: "localhost,127.0.0.1", test_url: "https://api.ipify.org?format=json" },
  browser: { enabled: true, auto_render: true, url: "http://127.0.0.1:3000", token: "", wait_ms: 1200, timeout_seconds: 45 },
  ui: { theme: "midnight", mode: "", accent: "", accent2: "", background: "", surface: "", text: "", density: "comfortable", radius: 14 },
};

/* ------------------------------ api / toast ------------------------------ */
async function api(path, options = {}) {
  const opts = { ...options, headers: { ...(options.headers || {}) } };
  if (opts.body && typeof opts.body !== "string") {
    opts.body = JSON.stringify(opts.body);
    opts.headers["Content-Type"] = "application/json";
  }
  const res = await fetch(path, opts);
  const text = await res.text();
  let data = {};
  if (text) { try { data = JSON.parse(text); } catch { data = { detail: text }; } }
  if (!res.ok) throw new Error(data.detail || `请求失败（HTTP ${res.status}）`);
  return data;
}

function toast(message, type = "ok", timeout = 4600) {
  const root = $("#toast-root");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.innerHTML = `${icon(type === "err" ? "alert" : "check")}<div>${esc(message)}</div>`;
  root.appendChild(el);
  setTimeout(() => { el.style.opacity = "0"; el.style.transform = "translateX(12px)"; el.style.transition = ".2s"; setTimeout(() => el.remove(), 220); }, timeout);
}

function setBusy(btn, busy, label = "处理中…") {
  if (!btn) return;
  if (busy) {
    if (!btn.dataset.original) btn.dataset.original = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner" style="width:14px;height:14px;margin:0;border-width:2px"></span>${esc(label)}`;
  } else {
    btn.disabled = false;
    if (btn.dataset.original) btn.innerHTML = btn.dataset.original;
  }
}

/* ------------------------------ loaders ------------------------------ */
async function loadSettings() {
  const data = await api("/api/settings");
  state.settings = data.settings || FALLBACK_SETTINGS;
  state.meta = data;
  applySettingsTheme();
}
async function loadSummary() { state.summary = await api("/api/summary"); }
async function loadSources() { state.sources = (await api("/api/sources")).sources || []; }
async function loadChannels() { state.channels = (await api("/api/channels")).channels || []; }
async function loadPresets() { state.presets = (await api("/api/presets")).presets || []; }
async function loadItems() {
  const p = new URLSearchParams({ limit: "200" });
  if (state.itemSource) p.set("source_id", state.itemSource);
  if (state.itemOnlyUpdate) p.set("only_update", "true");
  state.itemsData = await api(`/api/items?${p.toString()}`);
  state.itemsLoaded = true;
}
async function loadAlerts() {
  state.alertsData = await api("/api/alerts?limit=200");
  state.alertsLoaded = true;
}
async function loadLogs() {
  const p = new URLSearchParams({ limit: "250" });
  if (state.logLevel !== "all") p.set("level", state.logLevel);
  state.logsData = (await api(`/api/logs?${p.toString()}`)).logs || [];
}

async function refreshAll() {
  const results = await Promise.allSettled([loadSummary(), loadSources(), loadChannels(), loadPresets()]);
  results.filter((r) => r.status === "rejected").forEach((r) => console.warn("refresh:", r.reason));
  if (state.route === "items" && state.itemsLoaded) await loadItems().catch(() => {});
  if (state.route === "alerts" && state.alertsLoaded) await loadAlerts().catch(() => {});
  render();
}

/* ------------------------------ ui pieces ------------------------------ */
function pill(text, cls = "muted", dot = false) {
  return `<span class="pill ${cls}${dot ? " dot" : ""}">${esc(text)}</span>`;
}
function statusPill(status) {
  const map = { ok: ["正常", "ok"], idle: ["待扫描", "muted"], scanning: ["扫描中", "accent"], error: ["错误", "err"], degraded: ["降级", "warn"], disabled: ["已停用", "muted"] };
  const [label, cls] = map[status] || [status || "未知", "muted"];
  return pill(label, cls, cls !== "muted");
}
function alertPill(status) {
  const map = { sent: ["已送达", "ok"], partial: ["部分送达", "warn"], failed: ["失败", "err"], skipped: ["已跳过", "muted"], pending: ["待发送", "accent"] };
  const [label, cls] = map[status] || [status || "未知", "muted"];
  return pill(label, cls, false);
}
function statCard(iconName, value, label, extra = "") {
  return `<div class="panel stat">
    <div class="stat-top"><div class="stat-ico">${icon(iconName)}</div></div>
    <div class="stat-num">${esc(value)}</div>
    <div class="stat-label">${esc(label)}</div>
    ${extra ? `<div class="stat-extra">${extra}</div>` : ""}
  </div>`;
}
function emptyState(iconName, title, desc, action = "") {
  return `<div class="empty"><div class="empty-icon">${icon(iconName, "lg")}</div><h4>${esc(title)}</h4><p>${desc}</p>${action}</div>`;
}
function loading(text = "正在加载…") {
  return `<div class="loading-wrap"><span class="spinner"></span><p>${esc(text)}</p></div>`;
}
function panel(title, sub, body, action = "", cls = "") {
  return `<div class="panel ${cls}"><div class="panel-h"><div><h3>${title}</h3>${sub ? `<p>${esc(sub)}</p>` : ""}</div>${action}</div><div class="panel-b">${body}</div></div>`;
}
function field(label, input, hint = "", full = false) {
  return `<div class="field ${full ? "full" : ""}"><label>${label}</label>${input}${hint ? `<span class="hint">${hint}</span>` : ""}</div>`;
}
function sourceInitial(name) { return esc((name || "?").trim().slice(0, 1).toUpperCase()); }

/* ------------------------------ theme studio ------------------------------ */
function themeCards() {
  return Object.entries(THEMES).map(([key, t]) => `
    <button type="button" class="theme-card ${state.theme === key ? "on" : ""}" data-action="theme-select" data-theme-name="${key}">
      <div class="theme-swatches"><i style="background:${t.bg}"></i><i style="background:${t.surface}"></i><i style="background:${t.accent}"></i><i style="background:${t.accent2}"></i></div>
      <b>${esc(t.label)}</b><span>${t.mode === "light" ? "浅色" : "深色"} · ${esc(key)}</span>
    </button>`).join("");
}

/* ------------------------------ views ------------------------------ */
function viewDashboard() {
  const s = state.summary;
  if (!s) return loading("正在读取雷达状态…");
  const c = s.counts || {};
  const health = [
    ["bot", "AI 分析", s.ai?.ready ? `已就绪 · ${s.ai.model || "默认模型"}` : (s.ai?.enabled ? "已启用但未配置" : "未启用"), s.ai?.ready ? "ok" : "warn"],
    ["wifi", "网络代理", s.proxy?.enabled ? "已启用" : "未启用（直连）", s.proxy?.enabled ? "ok" : "muted"],
    ["clock", "定时调度", s.scheduler?.running ? `运行中 · ${s.scheduler.next_run_at ? relTime(s.scheduler.next_run_at) : "待命中"}` : "未运行", s.scheduler?.running ? "ok" : "err"],
    ["database", "数据存储", "SQLite · 本地持久化", "ok"],
  ];
  const items = (s.recent_items || []).map((it) => `
    <div class="activity-item">
      <div class="activity-mark ${it.is_update ? "update" : ""}">${icon(it.is_update ? "sparkles" : "news", "sm")}</div>
      <div class="activity-main">
        ${it.url ? `<a href="${esc(safeUrl(it.url))}" target="_blank" rel="noopener" class="title">${esc(it.title)}</a>` : `<span class="title">${esc(it.title)}</span>`}
        <div class="activity-meta"><span>${esc(it.source_name || "")}</span><span>·</span><span>${fmtDate(it.published_at || it.first_seen_at)}</span>${it.is_update ? pill("版本更新", "accent") : pill("普通公告", "muted")}</div>
      </div>
      <div class="activity-time">${relTime(it.published_at || it.first_seen_at)}</div>
    </div>`).join("");
  const sourceRows = (s.source_states || []).map((src) => `
    <div class="source-row">
      <div class="source-avatar">${sourceInitial(src.name)}</div>
      <div class="source-row-main"><strong>${esc(src.name)}</strong><span>${src.last_scan_at ? `上次扫描 ${relTime(src.last_scan_at)}` : "尚未扫描"}</span></div>
      <div class="source-row-side">${statusPill(src.status)}<div class="status-line-inline">${src.fail_count ? `连续失败 ${src.fail_count}` : " "}</div></div>
    </div>`).join("");
  const alerts = (s.recent_alerts || []).map((a) => `
    <div class="activity-item">
      <div class="activity-mark ${a.status === "sent" ? "update" : ""}">${icon("bell", "sm")}</div>
      <div class="activity-main"><span class="title">${esc(a.title)}</span><div class="activity-meta"><span>${esc(a.source_name || "")}</span><span>·</span><span>${fmtDate(a.created_at)}</span>${alertPill(a.status)}</div></div>
    </div>`).join("");

  return `
    <div class="stat-grid">
      ${statCard("radar", c.sources ?? 0, "监控源", `<b>${c.sources_enabled ?? 0}</b> 个启用 · ${c.sources_error ?? 0} 个异常`)}
      ${statCard("news", c.items ?? 0, "已收录公告", `<b>${c.updates ?? 0}</b> 条被判定为版本更新`)}
      ${statCard("sparkles", c.updates_24h ?? 0, "最近 24h 更新", `累计提醒 <b>${c.alerts_24h ?? 0}</b> 次`)}
      ${statCard("plug", c.channels ?? 0, "通知渠道", `共 ${c.alerts ?? 0} 条提醒记录`)}
    </div>
    <div class="grid-2">
      <div class="panel">
        <div class="panel-h"><div><h3>${icon("news", "sm")}最新公告动态</h3><p>按发布时间排序，来自所有监控源</p></div><button class="btn ghost sm" data-route="items">查看全部 ${icon("chevron", "sm")}</button></div>
        <div class="activity">${items || emptyState("news", "还没有公告", "添加监控源并执行一次扫描，这里就会出现最新公告。", `<button class="btn primary sm" data-action="add-source">${icon("plus", "sm")}添加监控源</button>`)}</div>
      </div>
      <div class="panel">
        <div class="panel-h"><div><h3>${icon("radar", "sm")}监控源状态</h3><p>${c.sources_enabled ?? 0} 个启用中</p></div><button class="btn ghost sm" data-route="sources">管理</button></div>
        <div>${sourceRows || emptyState("radar", "暂无监控源", "先添加一个游戏官网新闻页。")}</div>
        <div class="panel-b" style="border-top:1px solid var(--border)">
          <div class="health-list">
            ${health.map(([ico, label, value, cls]) => `<div class="health-row">${icon(ico, "sm")}<span>${esc(label)}</span><b>${cls === "ok" ? pill("正常", "ok") : cls === "err" ? pill("异常", "err") : cls === "warn" ? pill("待配置", "warn") : pill("关闭", "muted")}<span style="margin-left:6px;color:var(--muted);font-weight:400">${esc(value)}</span></b></div>`).join("")}
          </div>
        </div>
      </div>
    </div>
    <div class="grid-2 equal" style="margin-top:var(--gap)">
      <div class="panel">
        <div class="panel-h"><div><h3>${icon("bell", "sm")}最近提醒</h3><p>通知投递历史</p></div><button class="btn ghost sm" data-route="alerts">全部记录</button></div>
        <div class="activity">${alerts || emptyState("bell", "还没有提醒", "当检测到版本更新公告时，会通过已启用的渠道通知你。")}</div>
      </div>
      <div class="panel">
        <div class="panel-h"><div><h3>${icon("play", "sm")}快捷操作</h3><p>常用任务一键执行</p></div></div>
        <div class="panel-b" style="display:flex;flex-direction:column;gap:10px">
          <button class="btn primary" data-action="scan-all">${icon("play", "sm")}立即扫描全部监控源</button>
          <button class="btn" data-action="add-source">${icon("plus", "sm")}添加游戏官网 / 检测可行性</button>
          <button class="btn" data-route="channels">${icon("plug", "sm")}配置通知渠道</button>
          <button class="btn ghost" data-route="logs">${icon("terminal", "sm")}查看运行日志</button>
          <div class="note" style="margin-top:4px">${icon("shield", "sm")}<div>所有数据只保存在本地 <b>./data</b>，API Key 与通知密钥使用 Fernet 加密后落盘。</div></div>
        </div>
      </div>
    </div>`;
}

function filteredSources() {
  const q = state.sourceQuery.trim().toLowerCase();
  return state.sources.filter((s) => {
    if (state.sourceFilter === "enabled" && !s.enabled) return false;
    if (state.sourceFilter === "error" && !["error", "degraded"].includes(s.status)) return false;
    if (!q) return true;
    return `${s.name} ${s.url}`.toLowerCase().includes(q);
  });
}

function sourceCard(s) {
  const st = s.enabled ? s.status : "disabled";
  const repaired = s.selectors && s.selectors._repair && s.selectors._repair.ok_at;
  const rendered = s.selectors && s.selectors._render && s.selectors._render.ok_at;
  return `<article class="panel source-card">
    <div class="source-head">
      <div class="source-avatar">${sourceInitial(s.name)}</div>
      <div class="source-title"><h3>${esc(s.name)} ${statusPill(st)}</h3><a href="${esc(safeUrl(s.url))}" target="_blank" rel="noopener">${esc(s.url)} ${icon("external", "sm")}</a></div>
      <div class="source-actions">
        <button class="icon-btn" data-action="scan-source" data-id="${s.id}" title="立即扫描">${icon("play", "sm")}</button>
        <button class="icon-btn" data-action="edit-source" data-id="${s.id}" title="编辑">${icon("edit", "sm")}</button>
        <button class="icon-btn danger" data-action="delete-source" data-id="${s.id}" title="删除">${icon("trash", "sm")}</button>
      </div>
    </div>
    <div class="source-url">${esc(s.url)}</div>
    <div class="source-meta">
      ${pill(s.strategy === "auto" ? "自动解析" : s.strategy.toUpperCase(), "accent")}
      ${repaired ? pill("AI 策略", "ok") : ""}
      ${rendered ? pill("浏览器", "ok") : ""}
      ${pill(`每 ${s.interval_minutes} 分钟`, "muted")}
      ${s.use_proxy ? pill("走代理", "muted") : pill("直连", "muted")}
      ${s.last_http_status ? pill(`HTTP ${s.last_http_status}`, s.last_http_status >= 400 ? "err" : "muted") : ""}
    </div>
    <div class="source-stats">
      <div class="source-stat"><b>${s.item_count ?? 0}</b><span>公告</span></div>
      <div class="source-stat"><b>${s.update_count ?? 0}</b><span>更新</span></div>
      <div class="source-stat"><b>${s.fail_count ?? 0}</b><span>连续失败</span></div>
    </div>
    <div class="source-foot">
      <span class="last">${icon("clock", "sm")}${s.last_scan_at ? relTime(s.last_scan_at) : "尚未扫描"}${s.next_run_at ? ` · 下次 ${relTime(s.next_run_at)}` : ""}</span>
      <div class="ops"><button class="btn ghost xs" data-action="repair-source" data-id="${s.id}" title="AI 自动生成并验证抓取策略">${icon("sparkles", "sm")}AI 修复</button><button class="btn ghost xs" data-action="probe-source" data-id="${s.id}">${icon("search", "sm")}可行性</button><button class="btn xs" data-action="edit-source" data-id="${s.id}">编辑</button></div>
    </div>
    ${s.last_error ? `<div class="note warn" style="padding:7px 9px;font-size:10.5px">${icon("alert", "sm")}<div>${esc(s.last_error).slice(0, 220)}</div></div>` : ""}
  </article>`;
}

function viewSources() {
  const list = filteredSources();
  const grid = list.length ? list.map(sourceCard).join("") : emptyState("radar", "没有匹配的监控源", "试试更换筛选条件，或添加一个新的游戏官网。", `<button class="btn primary sm" data-action="add-source">${icon("plus", "sm")}添加监控源</button>`);
  return `
    <div class="toolbar">
      <div class="search-box">${icon("search", "sm")}<input id="source-search" placeholder="搜索游戏名或网址…" value="${esc(state.sourceQuery)}"></div>
      <div class="seg">
        <button class="${state.sourceFilter === "all" ? "on" : ""}" data-action="source-filter" data-filter="all">全部</button>
        <button class="${state.sourceFilter === "enabled" ? "on" : ""}" data-action="source-filter" data-filter="enabled">已启用</button>
        <button class="${state.sourceFilter === "error" ? "on" : ""}" data-action="source-filter" data-filter="error">异常</button>
      </div>
      <div class="spacer"></div>
    </div>
    <div class="source-grid" id="source-grid">${grid}</div>
    <div class="section-title"><div><h2>${icon("layers", "sm")}内置游戏预设</h2><p>一键添加常见游戏官网；可行性以添加后的检测结果为准</p></div></div>
    <div class="preset-grid">
      ${state.presets.map((p) => `<div class="preset"><div class="source-avatar" style="width:30px;height:30px;font-size:11px">${sourceInitial(p.name)}</div><div class="preset-main"><b>${esc(p.name)} ${p.verified ? pill("已验证", "ok") : ""}</b><span>${esc(p.url)}</span></div>${p.installed ? `<span class="pill muted">已添加</span>` : `<button class="btn xs" data-action="add-preset" data-key="${esc(p.key)}">添加</button>`}</div>`).join("") || `<span class="hint">暂无预设</span>`}
    </div>`;
}

function filteredItems() {
  const q = state.itemQuery.trim().toLowerCase();
  return (state.itemsData.items || []).filter((it) => !q || `${it.title} ${it.summary || ""} ${it.source_name || ""}`.toLowerCase().includes(q));
}
function itemRow(it) {
  const conf = Math.round((Number(it.confidence) || 0) * 100);
  return `<div class="item-row">
    <span class="item-bullet ${it.is_update ? "update" : ""}"></span>
    <div class="item-body">
      <h4>${it.url ? `<a href="${esc(safeUrl(it.url))}" target="_blank" rel="noopener">${esc(it.title)}</a>` : esc(it.title)}</h4>
      ${it.ai_summary || it.summary ? `<p class="item-summary">${esc(it.ai_summary || it.summary)}</p>` : ""}
      <div class="item-meta"><span>${esc(it.source_name || "")}</span><span>·</span><span>${fmtDate(it.published_at || it.first_seen_at)}</span>${it.is_update ? pill("版本更新", "accent") : pill("普通公告", "muted")}${it.reason ? `<span title="${esc(it.reason)}">· ${esc(titleOf(it.reason, 46))}</span>` : ""}</div>
    </div>
    <div class="item-side"><span class="pill ${it.is_update ? "accent" : "muted"}">${conf}%</span><div class="conf" title="AI/规则置信度"><i style="width:${Math.min(100, Math.max(0, conf))}%"></i></div><span style="font-size:9.5px;color:var(--faint)">${it.notified ? "已通知" : "未通知"}</span></div>
  </div>`;
}
function renderItemRows() {
  const list = filteredItems();
  const box = $("#item-list-container");
  if (!box) return;
  box.innerHTML = list.length ? `<div class="item-list">${list.map(itemRow).join("")}</div>` : emptyState("search", "没有匹配的公告", "调整筛选条件或先执行一次扫描。");
  const count = $("#item-count");
  if (count) count.textContent = `${list.length} / ${state.itemsData.total || 0}`;
}

function viewItems() {
  const sources = state.sources.map((s) => `<option value="${s.id}" ${String(state.itemSource) === String(s.id) ? "selected" : ""}>${esc(s.name)}</option>`).join("");
  return `
    <div class="toolbar">
      <select class="select inline" id="item-source-filter"><option value="">全部监控源</option>${sources}</select>
      <div class="search-box">${icon("search", "sm")}<input id="item-search" placeholder="搜索公告标题或摘要…" value="${esc(state.itemQuery)}"></div>
      <label class="switch"><input type="checkbox" id="item-only-update" ${state.itemOnlyUpdate ? "checked" : ""}><span class="track"></span>只看版本更新</label>
      <div class="spacer"></div>
      <button class="btn ghost" data-action="refresh-items">${icon("refresh", "sm")}刷新</button>
    </div>
    <div class="panel"><div class="panel-h"><div><h3>${icon("news", "sm")}公告列表</h3><p><span id="item-count">0 / 0</span> 条 · 数据来自 SQLite</p></div></div>
      <div id="item-list-container">${!state.itemsLoaded ? loading("正在读取公告…") : filteredItems().length ? `<div class="item-list">${filteredItems().map(itemRow).join("")}</div>` : emptyState("news", "还没有公告", "先添加监控源并执行一次扫描。")}</div>
    </div>`;
}

function alertRow(a) {
  const chips = (a.channel_results || []).map((r) => `<span class="chip-result ${r.ok ? "ok" : "err"}" title="${esc(r.message || "")}">${esc(r.name || r.type || "渠道")} ${r.ok ? "✓" : "×"}</span>`).join("");
  return `<div class="alert-row">
    <div class="alert-icon">${icon(a.status === "sent" ? "check" : "bell", "sm")}</div>
    <div class="alert-main"><h4>${a.item_url ? `<a href="${esc(safeUrl(a.item_url))}" target="_blank" rel="noopener">${esc(a.title)}</a>` : esc(a.title)}</h4><p>${esc(titleOf(a.message || "", 180))}</p><div class="alert-channels">${chips || `<span class="chip-result">无渠道结果</span>`}</div></div>
    <div class="alert-side">${alertPill(a.status)}<span style="font-size:10px;color:var(--faint)">${fmtDate(a.created_at)}</span><button class="btn ghost xs" data-action="resend-alert" data-id="${a.id}">重发</button></div>
  </div>`;
}
function filteredAlerts() {
  const list = state.alertsData.alerts || [];
  return state.alertFilter === "all" ? list : list.filter((a) => a.status === state.alertFilter);
}
function renderAlertRows() {
  const box = $("#alert-list-container");
  if (!box) return;
  const list = filteredAlerts();
  box.innerHTML = list.length ? `<div class="alert-list">${list.map(alertRow).join("")}</div>` : emptyState("bell", "没有提醒记录", "当检测到版本更新时，这里会留下每次投递的完整结果。");
}

function viewAlerts() {
  const filters = [["all", "全部"], ["sent", "已送达"], ["partial", "部分送达"], ["failed", "失败"], ["skipped", "已跳过"]];
  return `
    <div class="toolbar">
      <div class="seg">${filters.map(([k, v]) => `<button class="${state.alertFilter === k ? "on" : ""}" data-action="alert-filter" data-filter="${k}">${v}</button>`).join("")}</div>
      <div class="spacer"></div><button class="btn ghost" data-action="refresh-alerts">${icon("refresh", "sm")}刷新</button>
    </div>
    <div class="panel"><div class="panel-h"><div><h3>${icon("bell", "sm")}通知时间线</h3><p>${state.alertsData.total || 0} 条记录</p></div></div>
      <div id="alert-list-container">${!state.alertsLoaded ? loading("正在读取提醒记录…") : filteredAlerts().length ? `<div class="alert-list">${filteredAlerts().map(alertRow).join("")}</div>` : emptyState("bell", "还没有提醒", "检测到版本更新后，通知渠道会自动收到消息；也可以先测试渠道连通性。")}</div>
    </div>`;
}

const CHANNEL_ICONS = { email: "mail", telegram: "send", webhook: "webhook", bark: "bell", serverchan: "server", pushplus: "wechat", ntfy: "radio", twilio: "message", console: "terminal" };
function channelTypeMeta(type) { return state.meta?.channel_types?.[type] || { label: type, fields: [] }; }
function channelSummary(ch) {
  const cfg = ch.config || {};
  const mask = (v) => (typeof v === "string" && v.includes("•") ? v : v);
  switch (ch.type) {
    case "email": return `${mask(cfg.host || "SMTP")} → ${mask(cfg.to_addr || "?")}`;
    case "telegram": return `Chat ${mask(cfg.chat_id || "?")}`;
    case "webhook": return mask(cfg.url || "未配置 URL");
    case "bark": return `Device ${mask(cfg.device_key || "?")}`;
    case "serverchan": return `SendKey ${mask(cfg.sendkey || "?")}`;
    case "pushplus": return `Token ${mask(cfg.token || "?")}`;
    case "ntfy": return `${mask(cfg.server || "https://ntfy.sh")} / ${mask(cfg.topic || "?")}`;
    case "twilio": return `${mask(cfg.from_number || "?")} → ${mask(cfg.to_number || "?")}`;
    case "console": return "写入运行日志，不产生外部请求";
    default: return Object.keys(cfg).length ? Object.keys(cfg).join(", ") : "未配置";
  }
}
function channelCard(ch) {
  const meta = channelTypeMeta(ch.type);
  return `<article class="panel channel-card">
    <div class="channel-head"><div class="channel-icon">${icon(CHANNEL_ICONS[ch.type] || "plug")}</div><div class="channel-title"><h3>${esc(ch.name)}</h3><span>${esc(meta.label || ch.type)}</span></div>${ch.enabled ? pill("启用", "ok", true) : pill("停用", "muted")}</div>
    <div class="channel-config" title="${esc(channelSummary(ch))}">${esc(channelSummary(ch))}</div>
    <div class="channel-foot">
      <label class="switch"><input type="checkbox" data-toggle-channel="${ch.id}" ${ch.enabled ? "checked" : ""}><span class="track"></span>启用</label>
      <div style="display:flex;gap:4px">
        <button class="btn ghost xs" data-action="test-channel" data-id="${ch.id}">${icon("send", "sm")}测试</button>
        <button class="icon-btn" data-action="edit-channel" data-id="${ch.id}" title="编辑">${icon("edit", "sm")}</button>
        <button class="icon-btn danger" data-action="delete-channel" data-id="${ch.id}" title="删除">${icon("trash", "sm")}</button>
      </div>
    </div>
  </article>`;
}
function viewChannels() {
  return `<div class="toolbar"><div class="note" style="flex:1">${icon("shield", "sm")}<div>通知密钥在数据库中加密保存；测试发送会立即调用对应服务。</div></div></div>
    <div class="channel-grid">${state.channels.length ? state.channels.map(channelCard).join("") : emptyState("plug", "还没有通知渠道", "添加邮件、Telegram 或 Webhook，检测到更新时就能收到提醒。", `<button class="btn primary sm" data-action="add-channel">${icon("plus", "sm")}添加第一个渠道</button>`)}</div>`;
}

function viewAI() {
  const s = state.settings?.ai || FALLBACK_SETTINGS.ai;
  const p = state.settings?.proxy || FALLBACK_SETTINGS.proxy;
  const b = state.settings?.browser || FALLBACK_SETTINGS.browser;
  const providers = state.meta?.providers || [{ key: "deepseek", label: "DeepSeek", base_url: "https://api.deepseek.com/v1", model: "deepseek-chat" }];
  const providerOpts = providers.map((x) => `<option value="${esc(x.key)}" ${s.provider === x.key ? "selected" : ""}>${esc(x.label)}</option>`).join("");
  const maskedKey = s.api_key && s.api_key.includes("•") ? s.api_key : "";
  const maskedToken = b.token && b.token.includes("•") ? b.token : "";
  return `
    <div class="grid-2 equal">
      <div class="panel">
        <div class="panel-h"><div><h3>${icon("bot", "sm")}AI 模型接入</h3><p>OpenAI 兼容 / Anthropic / Ollama</p></div><label class="switch"><input type="checkbox" id="ai-enabled" ${s.enabled ? "checked" : ""}><span class="track"></span>启用</label></div>
        <div class="panel-b">
          <div class="form-grid">
            ${field("服务商", `<select class="select" id="ai-provider">${providerOpts}</select>`)}
            ${field("模型名称", `<input class="input" id="ai-model" value="${esc(s.model || "")}" placeholder="deepseek-chat">`)}
            ${field("API Base URL", `<input class="input" id="ai-base-url" value="${esc(s.base_url || "")}" placeholder="https://api.deepseek.com/v1">`, "OpenAI 兼容接口通常以 /v1 结尾", true)}
            ${field("API Key", `<input class="input" id="ai-api-key" type="password" autocomplete="new-password" placeholder="${maskedKey ? `已保存（${esc(maskedKey)}），留空保持不变` : "sk-…"}" value="">`, "仅保存在本机数据库，AES/Fernet 加密", true)}
            <div class="field"><label>Temperature</label><div class="field-row"><input class="input" id="ai-temperature" type="number" step="0.1" min="0" max="2" value="${Number(s.temperature ?? 0.1)}"><span class="hint" style="white-space:nowrap">0–2</span></div></div>
            ${field("最大输出 Token", `<input class="input" id="ai-max-tokens" type="number" min="64" max="8000" value="${Number(s.max_tokens ?? 900)}">`)}
            ${field("自动修复抓取策略", `<label class="switch"><input type="checkbox" id="ai-auto-repair" ${s.auto_repair !== false ? "checked" : ""}><span class="track"></span>扫描到 0 条时让 AI 分析页面</label>`, "AI 会生成并实际验证 HTML 选择器、data-* 链接或 JSON API 策略；失败后按冷却时间重试。", true)}
            ${field("修复最多尝试次数", `<input class="input" id="ai-repair-attempts" type="number" min="1" max="5" value="${Number(s.repair_max_attempts ?? 3)}">`, "1–5 次，每次都会真实抓取并校验结果")}
            ${field("失败冷却（分钟）", `<input class="input" id="ai-repair-cooldown" type="number" min="0" max="10080" value="${Number(s.repair_cooldown_minutes ?? 360)}">`, "失败后避免每分钟重复调用 AI")}
            ${field("额外系统提示词（可选）", `<textarea class="textarea" id="ai-prompt-extra" placeholder="例如：把补丁说明归纳成 3 条重点">${esc(s.prompt_extra || "")}</textarea>`, "会附加到判定与摘要提示词中", true)}
          </div>
          <div style="display:flex;gap:9px;margin-top:16px;flex-wrap:wrap">
            <button class="btn primary" data-action="save-ai">${icon("check", "sm")}保存 AI 设置</button>
            <button class="btn" data-action="test-ai">${icon("sparkles", "sm")}测试连通性</button>
          </div>
          <div id="ai-test-result" style="margin-top:12px"></div>
          <div class="note" style="margin-top:14px">${icon("sparkles", "sm")}<div>AI 用于“是否版本更新”的复核、摘要与抓取策略修复。页面识别到 0 条时会先尝试浏览器渲染，仍失败才让 AI 修复；每次生成的策略都会先实际提取验证，失败不会覆盖原策略。</div></div>
        </div>
      </div>
      <div class="panel">
        <div class="panel-h"><div><h3>${icon("wifi", "sm")}网络代理</h3><p>访问海外游戏官网时使用</p></div><label class="switch"><input type="checkbox" id="proxy-enabled" ${p.enabled ? "checked" : ""}><span class="track"></span>启用</label></div>
        <div class="panel-b">
          <div class="form-grid">
            ${field("HTTP 代理", `<input class="input" id="proxy-http" value="${esc(p.http_proxy || "")}" placeholder="http://127.0.0.1:7890">`, "支持 http:// 与 socks5://", true)}
            ${field("HTTPS 代理", `<input class="input" id="proxy-https" value="${esc(p.https_proxy || "")}" placeholder="http://127.0.0.1:7890">`, "留空时 HTTPS 复用 HTTP 代理", true)}
            ${field("不走代理的地址", `<input class="input" id="proxy-no" value="${esc(p.no_proxy || "")}" placeholder="localhost,127.0.0.1">`, "逗号分隔", true)}
            ${field("测试目标 URL", `<input class="input" id="proxy-test-url" value="${esc(p.test_url || "https://api.ipify.org?format=json")}">`, "测试代理是否真的能访问外网", true)}
          </div>
          <div style="display:flex;gap:9px;margin-top:16px;flex-wrap:wrap">
            <button class="btn primary" data-action="save-proxy">${icon("check", "sm")}保存代理设置</button>
            <button class="btn" data-action="test-proxy">${icon("wifi", "sm")}测试代理</button>
          </div>
          <div id="proxy-test-result" style="margin-top:12px"></div>
          <div class="note warn" style="margin-top:14px">${icon("alert", "sm")}<div>代理对所有文章抓取与 AI 请求生效。SMTP 邮件由 Python 直接连接邮件服务器，不经过 HTTP 代理。</div></div>
        </div>
      </div>
    </div>
    <div class="section-title"><div><h2>${icon("globe", "sm")}浏览器渲染（JavaScript 页面）</h2><p>由同网络命名空间的 Browserless 容器执行页面脚本，再交给抓取器解析；不占用额外端口</p></div></div>
    <div class="panel">
      <div class="panel-b">
        <div class="form-grid">
          <div class="field full"><label class="switch" style="display:inline-flex"><input type="checkbox" id="browser-enabled" ${b.enabled ? "checked" : ""}><span class="track"></span>启用浏览器渲染</label><span class="hint">静态抓取识别 0 条时自动调用；也可用于 Angular/React/Vue 等前端渲染站点。</span></div>
          <div class="field full"><label class="switch" style="display:inline-flex"><input type="checkbox" id="browser-auto" ${b.auto_render !== false ? "checked" : ""}><span class="track"></span>扫描失败时自动渲染</label><span class="hint">关闭后只能在可行性检测/编辑时手动使用。</span></div>
          ${field("Browserless 地址", `<input class="input" id="browser-url" value="${esc(b.url || "http://127.0.0.1:3000")}" placeholder="http://127.0.0.1:3000">`, "默认由 docker-compose 的 browser 服务共享网络；本机开发可填 http://127.0.0.1:3000", true)}
          ${field("访问 Token（可选）", `<input class="input" id="browser-token" type="password" autocomplete="new-password" placeholder="${maskedToken ? `已保存（${esc(maskedToken)}），留空保持不变` : "未设置"}" value="">`, "只有给 Browserless 配置了 TOKEN 时才需要", true)}
          ${field("等待页面稳定（毫秒）", `<input class="input" id="browser-wait" type="number" min="0" max="15000" step="100" value="${Number(b.wait_ms ?? 1200)}">`, "networkidle2 后再等待的额外时间；过短会漏掉懒加载列表")}
          ${field("单次渲染超时（秒）", `<input class="input" id="browser-timeout" type="number" min="5" max="120" value="${Number(b.timeout_seconds ?? 45)}">`, "包含导航与等待时间")}
        </div>
        <div style="display:flex;gap:9px;margin-top:16px;flex-wrap:wrap">
          <button class="btn primary" data-action="save-browser">${icon("check", "sm")}保存浏览器设置</button>
          <button class="btn" data-action="test-browser">${icon("globe", "sm")}测试浏览器</button>
        </div>
        <div id="browser-test-result" style="margin-top:12px"></div>
        <div class="note warn" style="margin-top:14px">${icon("alert", "sm")}<div>Browserless 容器自身的出网代理需要在 compose 的 browser 服务上设置 HTTP_PROXY/HTTPS_PROXY；本页的“网络代理”只作用于 Python 抓取与 AI 请求。</div></div>
      </div>
    </div>
    <div class="section-title"><div><h2>${icon("layers", "sm")}游戏官网可行性说明</h2><p>不同站点的页面结构差异很大，添加后建议先点一次“可行性”</p></div></div>
    <div class="panel"><div class="panel-b"><div class="preset-grid">
      ${state.presets.map((p) => `<div class="preset"><div class="preset-main"><b>${esc(p.name)} ${p.verified ? pill("已验证", "ok") : ""}</b><span>${esc(p.url)}</span></div>${p.installed ? pill("已添加", "muted") : `<button class="btn xs" data-action="add-preset" data-key="${esc(p.key)}">添加</button>`}</div>`).join("")}
    </div></div></div>`;
}

function viewSettings() {
  const g = state.settings?.general || FALLBACK_SETTINGS.general;
  const ui = state.settings?.ui || FALLBACK_SETTINGS.ui;
  const overrides = state.themeOverrides || {};
  const t = { ...(THEMES[state.theme] || THEMES.midnight), ...overrides };
  const tz = ["Asia/Shanghai", "UTC", "Asia/Tokyo", "Asia/Seoul", "America/New_York", "Europe/London", "Europe/Berlin", "Australia/Sydney"];
  return `
    <div class="form-section">
      <h4>${icon("palette", "sm")}颜色主题</h4>
      <p>选择预设主题，或直接修改颜色变量；所有颜色会即时预览，保存后同步到服务端。</p>
      <div class="theme-grid">${themeCards()}</div>
      <div class="form-grid" style="margin-top:16px">
        <div class="field"><label>强调色</label><div class="color-row"><input type="color" id="theme-accent" value="${esc(t.accent)}"><input class="input" id="theme-accent-text" value="${esc(t.accent)}"></div></div>
        <div class="field"><label>辅助色</label><div class="color-row"><input type="color" id="theme-accent2" value="${esc(t.accent2)}"><input class="input" id="theme-accent2-text" value="${esc(t.accent2)}"></div></div>
        <div class="field"><label>页面背景</label><div class="color-row"><input type="color" id="theme-bg" value="${esc(t.bg)}"><input class="input" id="theme-bg-text" value="${esc(t.bg)}"></div></div>
        <div class="field"><label>卡片表面</label><div class="color-row"><input type="color" id="theme-surface" value="${esc(t.surface)}"><input class="input" id="theme-surface-text" value="${esc(t.surface)}"></div></div>
        <div class="field"><label>主文字</label><div class="color-row"><input type="color" id="theme-text" value="${esc(t.text)}"><input class="input" id="theme-text-text" value="${esc(t.text)}"></div></div>
        <div class="field"><label>明暗模式</label><select class="select" id="theme-mode"><option value="dark" ${document.documentElement.dataset.theme !== "light" ? "selected" : ""}>深色</option><option value="light" ${document.documentElement.dataset.theme === "light" ? "selected" : ""}>浅色</option></select></div>
        <div class="field"><label>界面密度</label><select class="select" id="theme-density"><option value="compact" ${state.uiDensity === "compact" ? "selected" : ""}>紧凑</option><option value="comfortable" ${state.uiDensity === "comfortable" ? "selected" : ""}>标准</option><option value="spacious" ${state.uiDensity === "spacious" ? "selected" : ""}>宽松</option></select></div>
        <div class="field"><label>圆角：<span id="radius-label">${state.uiRadius}px</span></label><input class="range" id="theme-radius" type="range" min="0" max="24" value="${state.uiRadius}"></div>
      </div>
      <div style="display:flex;gap:9px;margin-top:16px;flex-wrap:wrap"><button class="btn primary" data-action="save-ui">${icon("check", "sm")}保存主题</button><button class="btn ghost" data-action="theme-reset">恢复默认</button></div>
    </div>

    <div class="form-section">
      <h4>${icon("clock", "sm")}扫描与保留策略</h4>
      <p>定时器按监控源各自的 interval 运行；这里设置新建监控源的默认值。</p>
      <div class="form-grid">
        ${field("默认扫描间隔（分钟）", `<input class="input" id="gen-interval" type="number" min="5" max="1440" value="${Number(g.default_interval_minutes || 60)}">`)}
        ${field("公告最大回溯天数", `<input class="input" id="gen-max-age" type="number" min="1" max="730" value="${Number(g.max_age_days || 45)}">`, "首次扫描只收录这个时间范围内的公告")}
        ${field("时区", `<select class="select" id="gen-timezone">${tz.map((x) => `<option value="${x}" ${g.timezone === x ? "selected" : ""}>${x}</option>`).join("")}</select>`, "修改后重启容器生效")}
        ${field("日志保留条数", `<input class="input" id="gen-log-retention" type="number" min="100" max="100000" value="${Number(g.log_retention || 5000)}">`)}
      </div>
      <div style="display:flex;gap:9px;margin-top:16px"><button class="btn primary" data-action="save-general">${icon("check", "sm")}保存设置</button></div>
    </div>

    <div class="form-section">
      <h4>${icon("database", "sm")}数据与备份</h4>
      <p>导出包含监控源、脱敏设置和渠道配置；通知密钥不会以明文导出。</p>
      <div style="display:flex;gap:9px;flex-wrap:wrap"><button class="btn" data-action="export">${icon("download", "sm")}导出配置 JSON</button><button class="btn ghost" data-route="logs">${icon("terminal", "sm")}运行日志</button></div>
      <div class="note warn" style="margin-top:14px">${icon("alert", "sm")}<div>WebUI 本身不含登录鉴权。暴露到公网时请放在 Nginx / Caddy 后并加 Basic Auth 或仅监听内网。</div></div>
    </div>`;
}

function viewLogs() {
  const rows = state.logsData.map((l) => `<div class="log-row"><span class="t">${fmtFull(l.ts)}</span><span class="log-level ${esc(l.level)}">${esc(l.level)}</span><span class="mod" title="${esc(l.event || "")}">${esc(l.event || "")}</span><span class="m">${esc(l.message)}${l.detail ? `<br><span style="color:var(--faint)">${esc(l.detail)}</span>` : ""}</span></div>`).join("");
  return `
    <div class="toolbar">
      <div class="seg">${[["all", "全部"], ["info", "INFO"], ["warning", "WARN"], ["error", "ERROR"]].map(([k, v]) => `<button class="${state.logLevel === k ? "on" : ""}" data-action="log-filter" data-level="${k}">${v}</button>`).join("")}</div>
      <div class="spacer"></div>
      <button class="btn ghost" data-action="refresh-logs">${icon("refresh", "sm")}刷新</button>
      <button class="btn danger" data-action="clear-logs">${icon("trash", "sm")}清空日志</button>
    </div>
    <div class="panel"><div class="panel-h"><div><h3>${icon("terminal", "sm")}运行日志</h3><p>最近 ${state.logsData.length} 条 · 按时间倒序</p></div></div>
      <div style="max-height:calc(100vh - 280px);overflow:auto">${state.logsData.length ? rows : emptyState("terminal", "暂无日志", "扫描、通知和 AI 调用都会写入这里。")}</div>
    </div>`;
}

function renderView() {
  switch (state.route) {
    case "sources": return viewSources();
    case "items": return viewItems();
    case "alerts": return viewAlerts();
    case "channels": return viewChannels();
    case "ai": return viewAI();
    case "settings": return viewSettings();
    case "logs": return viewLogs();
    default: return viewDashboard();
  }
}

function renderTopActions() {
  const scanBtn = `<button class="btn primary" data-action="scan-all">${icon("play", "sm")}<span>立即扫描</span></button>`;
  const addBtn = `<button class="btn primary" data-action="add-source">${icon("plus", "sm")}<span>添加监控源</span></button>`;
  switch (state.route) {
    case "dashboard": return `<button class="btn ghost" data-action="refresh">${icon("refresh", "sm")}<span>刷新</span></button>${scanBtn}`;
    case "sources": return `<button class="btn ghost" data-action="scan-all">${icon("play", "sm")}<span>全部扫描</span></button>${addBtn}`;
    case "items": return `<button class="btn ghost" data-action="refresh-items">${icon("refresh", "sm")}<span>刷新</span></button>`;
    case "alerts": return `<button class="btn ghost" data-action="refresh-alerts">${icon("refresh", "sm")}<span>刷新</span></button>`;
    case "channels": return `<button class="btn primary" data-action="add-channel">${icon("plus", "sm")}<span>添加渠道</span></button>`;
    case "ai": return `<button class="btn ghost" data-action="refresh">${icon("refresh", "sm")}<span>刷新</span></button>`;
    case "settings": return `<button class="btn ghost" data-action="export">${icon("download", "sm")}<span>导出</span></button>`;
    case "logs": return `<button class="btn ghost" data-action="refresh-logs">${icon("refresh", "sm")}<span>刷新</span></button>`;
    default: return "";
  }
}

function updateSidebarStatus() {
  const s = state.summary;
  const ai = s?.ai;
  const aiReady = !!ai?.ready;
  $("#nav-source-count").textContent = String(state.sources.length || 0);
  const set = (dot, txt, on, onText, offText) => {
    const d = $(dot), t = $(txt);
    if (!d || !t) return;
    d.className = `status-dot ${on ? "on" : "off"}`;
    t.textContent = on ? onText : offText;
  };
  set("#dot-ai", "#txt-ai", aiReady, "就绪", ai?.enabled ? "待配置" : "关闭");
  set("#dot-proxy", "#txt-proxy", !!s?.proxy?.enabled, "已启用", "直连");
  set("#dot-scheduler", "#txt-scheduler", !!s?.scheduler?.running, "运行中", "未运行");
}

function render() {
  const meta = ROUTES[state.route] || ROUTES.dashboard;
  $$(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.route === state.route));
  $("#page-title").textContent = meta.title;
  $("#page-sub").textContent = meta.sub;
  $("#top-actions").innerHTML = renderTopActions();
  $("#view").innerHTML = renderView();
  updateSidebarStatus();
}

/* ------------------------------ modal ------------------------------ */
function openModal({ title, sub = "", body, footer = "", wide = false }) {
  $("#modal-title").textContent = title;
  $("#modal-sub").textContent = sub;
  $("#modal-body").innerHTML = body;
  $("#modal-foot").innerHTML = footer;
  $("#modal").classList.toggle("wide", wide);
  $("#modal-root").hidden = false;
  document.body.style.overflow = "hidden";
  setTimeout(() => { const first = $("#modal-body input, #modal-body select, #modal-body textarea"); if (first) first.focus(); }, 40);
}
function closeModal() {
  $("#modal-root").hidden = true;
  document.body.style.overflow = "";
  if (state.confirmResolve) { state.confirmResolve(false); state.confirmResolve = null; }
}
function confirmDialog(title, text, okLabel = "确认", danger = true) {
  return new Promise((resolve) => {
    state.confirmResolve = resolve;
    openModal({
      title, sub: "", body: `<div class="note ${danger ? "warn" : ""}" style="font-size:12.5px">${icon("alert", "sm")}<div>${esc(text)}</div></div>`,
      footer: `<button class="btn ghost" data-action="confirm-no">取消</button><button class="btn ${danger ? "danger" : "primary"}" data-action="confirm-yes">${esc(okLabel)}</button>`,
    });
  });
}

/* ------------------------------ source modal ------------------------------ */
function probeHtml(r) {
  if (!r) return "";
  const conf = Math.round((Number(r.confidence) <= 1 ? Number(r.confidence) * 100 : Number(r.confidence)) || 0);
  const klass = r.feasible ? "good" : "bad";
  const samples = (r.sample_items || []).slice(0, 5).map((x) => `<div class="probe-sample"><b>${esc(x.title)}</b>${x.published_at ? ` · ${fmtDate(x.published_at)}` : ""}</div>`).join("");
  const risks = (r.risks || []).map((x) => `<li>${esc(x)}</li>`).join("");
  return `<div class="probe ${klass}">
    <div class="probe-head"><div class="probe-score">${conf}</div><div><b>${r.feasible ? "可以监控这个页面" : "这个页面暂时不适合直接监控"}</b><span>解析策略：${esc(r.strategy || "unknown")} · 条目 ${r.item_count ?? 0} · 带日期 ${r.dated_count ?? 0} · ${r.ai_used ? "AI 已参与评估" : "规则评估"}</span></div></div>
    <div class="probe-body">
      <div class="probe-metrics">${r.http_status ? pill(`HTTP ${r.http_status}`, "muted") : ""}${r.needs_browser ? pill("需要浏览器渲染", "warn") : ""}${r.ai_used ? pill("AI 判定", "accent") : ""}${r.newest_item_age_days != null ? pill(`最新条目 ${r.newest_item_age_days} 天前`, "muted") : ""}</div>
      ${samples ? `<div><div class="hint" style="margin-bottom:3px">样例条目</div><div class="probe-samples">${samples}</div></div>` : ""}
      ${risks ? `<div><div class="hint" style="margin-bottom:3px">风险与限制</div><ul class="probe-list">${risks}</ul></div>` : ""}
      ${r.recommendation ? `<div class="probe-tip">${esc(r.recommendation)}</div>` : ""}
      ${r.error ? `<div class="probe-tip" style="color:var(--danger)">${esc(r.error)}</div>` : ""}
      ${r.feasible ? `<button type="button" class="btn sm" data-action="apply-probe">${icon("check", "sm")}采用建议策略（${esc(r.strategy || "auto")}）</button>` : ""}
    </div>
  </div>`;
}

function openSourceModal(source = null, preset = null) {
  const s = source || {};
  const p = preset || {};
  const editing = !!source;
  const strategy = s.strategy || p.strategy || "auto";
  const name = s.name || p.name || "";
  const url = s.url || p.url || "";
  const useProxy = s.use_proxy ?? true;
  const enabled = s.enabled ?? true;
  const interval = s.interval_minutes ?? 60;
  const locale = s.locale || p.locale || "zh";
  const selectors = s.selectors && Object.keys(s.selectors).length ? JSON.stringify(s.selectors, null, 2) : "";
  state.lastProbe = null;
  const presetPicker = !editing ? `<div class="form-section"><h4>${icon("layers", "sm")}从预设开始</h4><p>选择游戏官网自动填入地址；仍建议点“检测可行性”。</p><div class="preset-grid">${state.presets.map((x) => `<button type="button" class="preset" data-action="use-preset" data-key="${esc(x.key)}" style="text-align:left"><div class="source-avatar" style="width:30px;height:30px;font-size:11px">${sourceInitial(x.name)}</div><div class="preset-main"><b>${esc(x.name)} ${x.verified ? pill("已验证", "ok") : ""}</b><span>${esc(x.url)}</span></div></button>`).join("")}</div></div>` : "";
  const body = `${presetPicker}
    <form id="source-form" autocomplete="off">
      <div class="form-grid">
        ${field("游戏名称 <span class='req'>*</span>", `<input class="input" id="src-name" value="${esc(name)}" placeholder="例如：KARDS">`)}
        ${field("新闻页 URL <span class='req'>*</span>", `<input class="input" id="src-url" value="${esc(url)}" placeholder="https://www.kardsplayer.com/zh/news">`, "填官网的新闻/公告列表页，而不是单篇文章", true)}
        ${field("解析策略", `<select class="select" id="src-strategy"><option value="auto" ${strategy === "auto" ? "selected" : ""}>自动（推荐）</option><option value="rsc" ${strategy === "rsc" ? "selected" : ""}>Next.js RSC</option><option value="html" ${strategy === "html" ? "selected" : ""}>HTML 链接</option><option value="json" ${strategy === "json" ? "selected" : ""}>JSON 接口</option></select>`)}
        ${field("扫描间隔（分钟）", `<input class="input" id="src-interval" type="number" min="5" max="1440" value="${Number(interval)}">`)}
        ${field("语言", `<select class="select" id="src-locale"><option value="zh" ${locale === "zh" ? "selected" : ""}>中文</option><option value="en" ${locale === "en" ? "selected" : ""}>English</option><option value="ja" ${locale === "ja" ? "selected" : ""}>日本語</option><option value="ko" ${locale === "ko" ? "selected" : ""}>한국어</option></select>`)}
        <div class="field"><label>开关</label><div style="display:flex;gap:16px;padding-top:5px"><label class="switch"><input type="checkbox" id="src-enabled" ${enabled ? "checked" : ""}><span class="track"></span>启用定时扫描</label><label class="switch"><input type="checkbox" id="src-use-proxy" ${useProxy ? "checked" : ""}><span class="track"></span>走网络代理</label></div></div>
        ${field("备注", `<input class="input" id="src-notes" value="${esc(s.notes || p.notes || "")}" placeholder="例如：国服公告、需要代理">`, "", true)}
      </div>
      <details class="advanced"><summary>高级：关键词与自定义选择器</summary>
        <div class="form-grid">
          ${field("强包含关键词（逗号分隔）", `<input class="input" id="src-keywords" value="${esc(s.keywords_include || "")}" placeholder="版本更新, 补丁, update">`, "命中后提高“版本更新”判定")}
          ${field("排除关键词（逗号分隔）", `<input class="input" id="src-exclude" value="${esc(s.keywords_exclude || "")}" placeholder="赛事, 周边, 招聘">`)}
          ${field("自定义选择器 JSON", `<textarea class="textarea" id="src-selectors" placeholder='{"item":"article","title":"h2","link":"a","date":"time"}'>${esc(selectors)}</textarea>`, "留空使用自动解析；仅在自动失败时使用", true)}
        </div>
      </details>
    </form>
    <div id="probe-result">${editing && s.feasibility && Object.keys(s.feasibility).length ? probeHtml(s.feasibility) : ""}</div>`;
  const footer = `<button class="btn ghost left" data-action="probe-form">${icon("sparkles", "sm")}AI 检测可行性</button><button class="btn ghost" data-action="modal-close">取消</button><button class="btn primary" data-action="save-source" data-id="${editing ? source.id : ""}">${icon("check", "sm")}${editing ? "保存修改" : "保存并开始监控"}</button>`;
  openModal({ title: editing ? "编辑监控源" : "添加监控源", sub: editing ? "修改后会重新计算调度计划" : "先检测可行性，再决定是否启用定时扫描", body, footer, wide: true });
}

function collectSourceForm() {
  const id = $("#modal-foot [data-action='save-source']")?.dataset.id || "";
  const name = $("#src-name").value.trim();
  const url = $("#src-url").value.trim();
  if (!name) throw new Error("请填写游戏名称");
  if (!/^https?:\/\//i.test(url)) throw new Error("URL 必须以 http:// 或 https:// 开头");
  let selectors = {};
  const rawSelectors = $("#src-selectors").value.trim();
  if (rawSelectors) {
    try { selectors = JSON.parse(rawSelectors); } catch { throw new Error("自定义选择器不是合法 JSON"); }
  }
  return {
    id,
    payload: {
      name, url, strategy: $("#src-strategy").value, interval_minutes: Number($("#src-interval").value) || 60,
      locale: $("#src-locale").value, enabled: $("#src-enabled").checked, use_proxy: $("#src-use-proxy").checked,
      notes: $("#src-notes").value.trim(), keywords_include: $("#src-keywords").value.trim(),
      keywords_exclude: $("#src-exclude").value.trim(), selectors,
    },
  };
}

/* ------------------------------ channel modal ------------------------------ */
function channelFieldHtml(f, cfg) {
  const raw = cfg?.[f.key];
  const masked = typeof raw === "string" && raw.includes("•");
  const val = masked ? "" : (raw ?? "");
  const req = f.required && !masked ? "required" : "";
  const ph = masked ? `已保存（${esc(raw)}），留空保持不变` : (f.placeholder || "");
  let input = "";
  if (f.type === "select") {
    input = `<select class="select" data-cfg="${esc(f.key)}">${(f.options || []).map((o) => `<option value="${esc(o)}" ${String(val) === String(o) ? "selected" : ""}>${esc(o)}</option>`).join("")}</select>`;
  } else if (f.type === "textarea") {
    input = `<textarea class="textarea" data-cfg="${esc(f.key)}" placeholder="${ph}">${esc(val)}</textarea>`;
  } else {
    const type = f.type === "secret" ? "password" : f.type === "number" ? "number" : "text";
    input = `<input class="input" data-cfg="${esc(f.key)}" type="${type}" value="${esc(val)}" placeholder="${ph}" ${req} autocomplete="off">`;
  }
  return field(`${esc(f.label)}${f.required && !masked ? " <span class='req'>*</span>" : ""}`, input, f.hint || "", !!f.full || f.type === "textarea");
}
function renderChannelFields(type, cfg = {}) {
  const box = $("#channel-fields");
  if (!box) return;
  const meta = channelTypeMeta(type);
  const defaults = type === "email" ? { port: "587", encryption: "starttls", subject_prefix: "[游戏更新]" } : type === "webhook" ? { method: "POST" } : type === "bark" ? { server: "https://api.day.app" } : type === "ntfy" ? { server: "https://ntfy.sh", priority: "high" } : type === "telegram" ? { api_base: "https://api.telegram.org" } : {};
  box.innerHTML = (meta.fields || []).length ? `<div class="form-grid">${meta.fields.map((f) => channelFieldHtml(f, { ...defaults, ...cfg })).join("")}</div>` : `<div class="note">${icon("terminal", "sm")}<div>该渠道不需要额外配置，测试消息会写入运行日志。</div></div>`;
}
function openChannelModal(channel = null) {
  const editing = !!channel;
  const types = state.meta?.channel_types || {};
  const type = channel?.type || (types.email ? "email" : Object.keys(types)[0] || "email");
  const typeOpts = Object.entries(types).map(([k, v]) => `<option value="${esc(k)}" ${type === k ? "selected" : ""}>${esc(v.label || k)}</option>`).join("");
  const body = `<form id="channel-form" autocomplete="off"><div class="form-grid">
      ${field("渠道名称 <span class='req'>*</span>", `<input class="input" id="ch-name" value="${esc(channel?.name || "")}" placeholder="例如：我的邮箱">`)}
      ${field("渠道类型", `<select class="select" id="ch-type" ${editing ? "disabled" : ""}>${typeOpts}</select>`)}
      <div class="field full"><label class="switch"><input type="checkbox" id="ch-enabled" ${channel?.enabled ?? true ? "checked" : ""}><span class="track"></span>启用该渠道</label></div>
    </div>
    <div id="channel-fields" style="margin-top:16px"></div></form>`;
  const footer = `<button class="btn ghost left" data-action="save-channel" data-test="1" data-id="${editing ? channel.id : ""}">${icon("send", "sm")}保存并测试</button><button class="btn ghost" data-action="modal-close">取消</button><button class="btn primary" data-action="save-channel" data-id="${editing ? channel.id : ""}">${icon("check", "sm")}保存</button>`;
  openModal({ title: editing ? "编辑通知渠道" : "添加通知渠道", sub: "密钥字段留空表示保持原值；保存后建议立即测试", body, footer });
  renderChannelFields(type, channel?.config || {});
}

function collectChannelForm() {
  const id = $("#modal-foot [data-action='save-channel']:last-child")?.dataset.id || "";
  const name = $("#ch-name").value.trim();
  const type = $("#ch-type").value;
  if (!name) throw new Error("请填写渠道名称");
  const meta = channelTypeMeta(type);
  const config = {};
  (meta.fields || []).forEach((f) => {
    const el = $(`[data-cfg="${f.key}"]`);
    if (!el) return;
    let value = el.value.trim();
    if (f.type === "secret" && !value) return;
    if (f.type === "number" && value !== "") value = Number(value);
    if (value !== "") config[f.key] = value;
  });
  return { id, type, payload: { name, config, enabled: $("#ch-enabled").checked } };
}

/* ------------------------------ views binding / filters ------------------------------ */
function applySourceFilter() {
  const grid = $("#source-grid");
  if (!grid) return;
  const list = filteredSources();
  grid.innerHTML = list.length ? list.map(sourceCard).join("") : emptyState("radar", "没有匹配的监控源", "试试更换筛选条件，或添加一个新的游戏官网。");
}
function applyItemFilter() { renderItemRows(); }
function applyAlertFilter() { renderAlertRows(); }

/* ------------------------------ actions ------------------------------ */
async function handleAction(act, el) {
  const id = Number(el.dataset.id || 0);
  switch (act) {
    case "refresh":
      await refreshAll();
      toast("已刷新");
      break;
    case "scan-all": {
      const r = await api("/api/scan-all", { method: "POST" });
      toast(`已排队扫描 ${r.queued || 0} 个监控源`);
      setTimeout(refreshAll, 2800);
      break;
    }
    case "scan-source": {
      await api(`/api/sources/${id}/scan`, { method: "POST" });
      toast("扫描任务已排队");
      setTimeout(refreshAll, 2600);
      break;
    }
    case "repair-source": {
      const src = state.sources.find((x) => Number(x.id) === id);
      if (!src) break;
      setBusy(el, true, "AI 分析中…");
      try {
        const r = await api(`/api/sources/${id}/repair`, { method: "POST" });
        if (r.ok) {
          toast(`AI 策略已生效，识别 ${r.items_found || 0} 条；已排队重新扫描`, "ok", 6500);
          setTimeout(refreshAll, 2800);
        } else {
          toast(r.error || "AI 未能生成可用策略", "err", 8000);
        }
        await loadSources();
        render();
      } finally { setBusy(el, false); }
      break;
    }
    case "add-source": openSourceModal(); break;
    case "edit-source": {
      const src = state.sources.find((x) => Number(x.id) === id);
      if (src) openSourceModal(src);
      break;
    }
    case "delete-source": {
      const src = state.sources.find((x) => Number(x.id) === id);
      if (!src) break;
      if (!(await confirmDialog("删除监控源", `将删除「${src.name}」及其全部公告记录，此操作不可撤销。`, "删除"))) break;
      await api(`/api/sources/${id}`, { method: "DELETE" });
      toast("监控源已删除");
      await refreshAll();
      break;
    }
    case "probe-source": {
      const src = state.sources.find((x) => Number(x.id) === id);
      if (!src) break;
      toast("正在检测页面可行性…");
      const r = await api(`/api/sources/${id}/probe`, { method: "POST" });
      toast(r.feasible ? "检测完成：可以监控" : "检测完成：页面可能不可直接解析", r.feasible ? "ok" : "err");
      await loadSources();
      render();
      openSourceModal(state.sources.find((x) => Number(x.id) === id));
      break;
    }
    case "probe-form": {
      const url = $("#src-url").value.trim();
      const name = $("#src-name").value.trim() || url;
      if (!/^https?:\/\//i.test(url)) { toast("请先填写合法的 URL", "err"); break; }
      setBusy(el, true, "检测中…");
      try {
        const r = await api("/api/feasibility", { method: "POST", body: { url, name, use_ai: true, use_proxy: $("#src-use-proxy").checked } });
        state.lastProbe = r;
        $("#probe-result").innerHTML = probeHtml(r);
        toast(r.feasible ? "可以监控这个页面" : "页面可行性较低，请查看建议", r.feasible ? "ok" : "err");
      } finally { setBusy(el, false); }
      break;
    }
    case "apply-probe": {
      if (!state.lastProbe) break;
      const strat = state.lastProbe.strategy;
      if (["auto", "rsc", "html", "json"].includes(strat)) $("#src-strategy").value = strat;
      if (state.lastProbe.recommendation) $("#src-notes").value = titleOf(state.lastProbe.recommendation, 160);
      toast(`已采用 ${strat || "auto"} 策略`);
      break;
    }
    case "save-source": {
      const { id: sourceId, payload } = collectSourceForm();
      setBusy(el, true, "保存中…");
      try {
        if (sourceId) await api(`/api/sources/${sourceId}`, { method: "PUT", body: payload });
        else await api("/api/sources", { method: "POST", body: payload });
        closeModal();
        toast(sourceId ? "监控源已更新" : "监控源已添加，准备首次扫描");
        await refreshAll();
      } finally { setBusy(el, false); }
      break;
    }
    case "use-preset": {
      const p = state.presets.find((x) => x.key === el.dataset.key);
      if (!p) break;
      $("#src-name").value = p.name;
      $("#src-url").value = p.url;
      $("#src-strategy").value = p.strategy || "auto";
      $("#src-locale").value = p.locale || "zh";
      $("#src-notes").value = p.notes || "";
      toast(`已填入 ${p.name} 预设`);
      $("#src-url").scrollIntoView({ behavior: "smooth", block: "center" });
      break;
    }
    case "add-preset": {
      setBusy(el, true, "添加中…");
      try {
        await api(`/api/presets/${encodeURIComponent(el.dataset.key)}`, { method: "POST", body: { enabled: true } });
        toast("预设已添加，首次扫描会建立基线");
        await refreshAll();
      } finally { setBusy(el, false); }
      break;
    }
    case "add-channel": openChannelModal(); break;
    case "edit-channel": {
      const ch = state.channels.find((x) => Number(x.id) === id);
      if (ch) openChannelModal(ch);
      break;
    }
    case "save-channel": {
      const { id: chId, type, payload } = collectChannelForm();
      const shouldTest = el.dataset.test === "1";
      setBusy(el, true, "保存中…");
      try {
        let channelId = chId;
        if (chId) await api(`/api/channels/${chId}`, { method: "PUT", body: payload });
        else channelId = (await api("/api/channels", { method: "POST", body: { ...payload, type } })).id;
        closeModal();
        toast("通知渠道已保存");
        await loadChannels();
        render();
        if (shouldTest && channelId) {
          const r = await api(`/api/channels/${channelId}/test`, { method: "POST" });
          toast(r.ok ? "测试消息已发送" : `测试失败：${r.result?.message || "未知错误"}`, r.ok ? "ok" : "err", 7000);
        }
      } finally { setBusy(el, false); }
      break;
    }
    case "delete-channel": {
      const ch = state.channels.find((x) => Number(x.id) === id);
      if (!ch) break;
      if (!(await confirmDialog("删除通知渠道", `确定删除「${ch.name}」？`, "删除"))) break;
      await api(`/api/channels/${id}`, { method: "DELETE" });
      toast("渠道已删除");
      await loadChannels();
      render();
      break;
    }
    case "test-channel": {
      setBusy(el, true, "发送中…");
      try {
        const r = await api(`/api/channels/${id}/test`, { method: "POST" });
        toast(r.ok ? `测试消息已发送（${r.result?.latency_ms ?? 0}ms）` : `测试失败：${r.result?.message || "未知错误"}`, r.ok ? "ok" : "err", 7000);
      } finally { setBusy(el, false); }
      break;
    }
    case "resend-alert": {
      setBusy(el, true, "重发中…");
      try {
        const r = await api(`/api/alerts/${id}/resend`, { method: "POST" });
        toast(r.ok ? "提醒已重发" : "重发未成功，请查看渠道结果", r.ok ? "ok" : "err");
        await loadAlerts();
        render();
      } finally { setBusy(el, false); }
      break;
    }
    case "save-ai": {
      setBusy(el, true, "保存中…");
      try {
        const values = {
          enabled: $("#ai-enabled").checked, provider: $("#ai-provider").value,
          base_url: $("#ai-base-url").value.trim(), model: $("#ai-model").value.trim(),
          temperature: Number($("#ai-temperature").value), max_tokens: Number($("#ai-max-tokens").value),
          prompt_extra: $("#ai-prompt-extra").value.trim(),
          auto_repair: $("#ai-auto-repair").checked,
          repair_max_attempts: Number($("#ai-repair-attempts").value),
          repair_cooldown_minutes: Number($("#ai-repair-cooldown").value),
        };
        const key = $("#ai-api-key").value.trim();
        if (key) values.api_key = key;
        await api("/api/settings/ai", { method: "PUT", body: { values } });
        await loadSettings();
        render();
        toast("AI 设置已保存");
      } finally { setBusy(el, false); }
      break;
    }
    case "test-ai": {
      setBusy(el, true, "测试中…");
      const box = $("#ai-test-result");
      if (box) box.innerHTML = `<div class="note">${icon("sparkles", "sm")}<div>正在请求模型，最长等待 45 秒…</div></div>`;
      try {
        const r = await api("/api/ai/test", { method: "POST", body: {
          enabled: $("#ai-enabled").checked, provider: $("#ai-provider").value,
          base_url: $("#ai-base-url").value.trim(), model: $("#ai-model").value.trim(),
          api_key: $("#ai-api-key").value.trim() || undefined,
        } });
        if (box) box.innerHTML = r.ok
          ? `<div class="note">${icon("check", "sm")}<div><b>连接成功</b> · ${esc(r.model || "模型")} · ${r.latency_ms ?? "?"}ms<br><span style="color:var(--faint)">${esc(r.message || "")}</span></div></div>`
          : `<div class="note warn">${icon("alert", "sm")}<div><b>连接失败</b><br>${esc(r.error || "未知错误")}</div></div>`;
      } catch (e) {
        if (box) box.innerHTML = `<div class="note warn">${icon("alert", "sm")}<div>${esc(e.message)}</div></div>`;
      } finally { setBusy(el, false); }
      break;
    }
    case "save-proxy": {
      setBusy(el, true, "保存中…");
      try {
        await api("/api/settings/proxy", { method: "PUT", body: { values: {
          enabled: $("#proxy-enabled").checked, http_proxy: $("#proxy-http").value.trim(),
          https_proxy: $("#proxy-https").value.trim(), no_proxy: $("#proxy-no").value.trim(),
          test_url: $("#proxy-test-url").value.trim(),
        } } });
        await loadSettings();
        toast("代理设置已保存");
      } finally { setBusy(el, false); }
      break;
    }
    case "test-proxy": {
      setBusy(el, true, "测试中…");
      const box = $("#proxy-test-result");
      if (box) box.innerHTML = `<div class="note">${icon("wifi", "sm")}<div>正在通过当前代理访问测试地址…</div></div>`;
      try {
        const r = await api("/api/proxy/test", { method: "POST", body: { url: $("#proxy-test-url").value.trim() || undefined } });
        if (box) box.innerHTML = r.ok
          ? `<div class="note">${icon("check", "sm")}<div><b>代理可用</b> · HTTP ${r.status} · ${r.elapsed_ms ?? "?"}ms · 代理${r.proxy_used ? "已使用" : "未使用"}<br><span style="color:var(--faint)">${esc(r.final_url || "")}</span></div></div>`
          : `<div class="note warn">${icon("alert", "sm")}<div><b>连接失败</b><br>${esc(r.error || "未知错误")}</div></div>`;
      } catch (e) {
        if (box) box.innerHTML = `<div class="note warn">${icon("alert", "sm")}<div>${esc(e.message)}</div></div>`;
      } finally { setBusy(el, false); }
      break;
    }
    case "save-browser": {
      setBusy(el, true, "保存中…");
      try {
        const values = {
          enabled: $("#browser-enabled").checked,
          auto_render: $("#browser-auto").checked,
          url: $("#browser-url").value.trim(),
          wait_ms: Number($("#browser-wait").value),
          timeout_seconds: Number($("#browser-timeout").value),
        };
        const token = $("#browser-token").value.trim();
        if (token) values.token = token;
        await api("/api/settings/browser", { method: "PUT", body: { values } });
        await loadSettings();
        render();
        toast("浏览器渲染设置已保存");
      } finally { setBusy(el, false); }
      break;
    }
    case "test-browser": {
      setBusy(el, true, "渲染中…");
      const box = $("#browser-test-result");
      if (box) box.innerHTML = `<div class="note">${icon("globe", "sm")}<div>正在通过 Browserless 渲染 https://example.com，最长等待 45 秒…</div></div>`;
      try {
        const r = await api("/api/browser/test", { method: "POST", body: {} });
        if (box) box.innerHTML = r.ok
          ? `<div class="note">${icon("check", "sm")}<div><b>浏览器可用</b> · HTTP ${r.status} · ${r.elapsed_ms ?? "?"}ms · ${r.bytes ?? "?"} 字节<br><span style="color:var(--faint)">${esc(r.title || r.final_url || "")}</span></div></div>`
          : `<div class="note warn">${icon("alert", "sm")}<div><b>渲染失败</b><br>${esc(r.error || "未知错误")}</div></div>`;
      } catch (e) {
        if (box) box.innerHTML = `<div class="note warn">${icon("alert", "sm")}<div>${esc(e.message)}</div></div>`;
      } finally { setBusy(el, false); }
      break;
    }
    case "save-general": {
      setBusy(el, true, "保存中…");
      try {
        await api("/api/settings/general", { method: "PUT", body: { values: {
          default_interval_minutes: Number($("#gen-interval").value), max_age_days: Number($("#gen-max-age").value),
          timezone: $("#gen-timezone").value, log_retention: Number($("#gen-log-retention").value),
        } } });
        await loadSettings();
        toast("扫描与保留策略已保存");
      } finally { setBusy(el, false); }
      break;
    }
    case "save-ui": {
      setBusy(el, true, "保存中…");
      try {
        const o = state.themeOverrides || {};
        await api("/api/settings/ui", { method: "PUT", body: { values: {
          theme: state.theme, mode: document.documentElement.dataset.theme,
          accent: o.accent || "", accent2: o.accent2 || "", background: o.bg || "",
          surface: o.surface || "", text: o.text || "", density: state.uiDensity, radius: Number(state.uiRadius),
        } } });
        await loadSettings();
        toast("主题已保存");
      } finally { setBusy(el, false); }
      break;
    }
    case "theme-select": {
      const name = el.dataset.themeName;
      state.uiRadius = Number(state.uiRadius) || 14;
      applyTheme(name, {});
      render();
      break;
    }
    case "theme-reset": {
      state.uiDensity = "comfortable"; state.uiRadius = 14;
      applyTheme("midnight", {});
      render();
      toast("已恢复默认主题（尚未保存）");
      break;
    }
    case "export": window.location.href = "/api/export"; break;
    case "refresh-items": setBusy(el, true, "加载中…"); try { await loadItems(); render(); } finally { setBusy(el, false); } break;
    case "refresh-alerts": setBusy(el, true, "加载中…"); try { await loadAlerts(); render(); } finally { setBusy(el, false); } break;
    case "refresh-logs": setBusy(el, true, "加载中…"); try { await loadLogs(); render(); } finally { setBusy(el, false); } break;
    case "alert-filter": state.alertFilter = el.dataset.filter; render(); break;
    case "log-filter": state.logLevel = el.dataset.level; await loadLogs(); render(); break;
    case "source-filter": state.sourceFilter = el.dataset.filter; render(); break;
    case "clear-logs":
      if (!(await confirmDialog("清空运行日志", "将删除全部历史日志，此操作不可撤销。", "清空"))) break;
      await api("/api/logs", { method: "DELETE" });
      await loadLogs(); render(); toast("日志已清空");
      break;
    case "modal-close": closeModal(); break;
    case "confirm-yes": { const r = state.confirmResolve; state.confirmResolve = null; closeModal(); if (r) r(true); break; }
    case "confirm-no": { const r = state.confirmResolve; state.confirmResolve = null; closeModal(); if (r) r(false); break; }
    default: break;
  }
}

/* ------------------------------ events ------------------------------ */
function navigate(route, push = true) {
  if (!ROUTES[route]) route = "dashboard";
  state.route = route;
  if (push) history.replaceState(null, "", `#/${route}`);
  document.body.classList.remove("nav-open");
  render();
  loadRouteData(route).catch((e) => { console.error(e); toast(e.message, "err"); });
}

async function loadRouteData(route) {
  if (route === "items") { await loadItems(); render(); }
  else if (route === "alerts") { await loadAlerts(); render(); }
  else if (route === "logs") { await loadLogs(); render(); }
}

function bindEvents() {
  document.addEventListener("click", async (e) => {
    const routeBtn = e.target.closest("[data-route]");
    if (routeBtn) { e.preventDefault(); navigate(routeBtn.dataset.route); return; }
    const btn = e.target.closest("[data-action]");
    if (!btn) return;
    e.preventDefault();
    try { await handleAction(btn.dataset.action, btn); }
    catch (err) { console.error(err); toast(err.message || "操作失败", "err", 7000); }
  });

  document.addEventListener("change", async (e) => {
    if (e.target.id === "ch-type") { renderChannelFields(e.target.value, {}); return; }
    if (e.target.id === "ai-provider") {
      const p = (state.meta?.providers || []).find((x) => x.key === e.target.value);
      if (p) { if (p.base_url) $("#ai-base-url").value = p.base_url; if (p.model) $("#ai-model").value = p.model; }
      return;
    }
    if (e.target.id === "item-source-filter") { state.itemSource = e.target.value; await loadItems(); render(); return; }
    if (e.target.id === "item-only-update") { state.itemOnlyUpdate = e.target.checked; await loadItems(); render(); return; }
    if (e.target.matches("[data-toggle-channel]")) {
      const ch = state.channels.find((x) => Number(x.id) === Number(e.target.dataset.toggleChannel));
      if (!ch) return;
      try { await api(`/api/channels/${ch.id}`, { method: "PUT", body: { enabled: e.target.checked } }); toast(e.target.checked ? "渠道已启用" : "渠道已停用"); await loadChannels(); render(); }
      catch (err) { toast(err.message, "err"); e.target.checked = !e.target.checked; }
      return;
    }
    if (e.target.id === "theme-mode") { applyTheme(state.theme, state.themeOverrides, e.target.value); return; }
    if (e.target.id === "theme-density") { state.uiDensity = e.target.value; document.documentElement.dataset.density = state.uiDensity; return; }
  });

  document.addEventListener("input", (e) => {
    if (e.target.id === "source-search") { state.sourceQuery = e.target.value; applySourceFilter(); return; }
    if (e.target.id === "item-search") { state.itemQuery = e.target.value; applyItemFilter(); return; }
    const map = { "theme-accent": "accent", "theme-accent2": "accent2", "theme-bg": "bg", "theme-surface": "surface", "theme-text": "text" };
    const key = map[e.target.id];
    if (key) {
      state.themeOverrides = { ...(state.themeOverrides || {}), [key]: e.target.value };
      applyTheme(state.theme, state.themeOverrides);
      const textEl = $(`#${e.target.id}-text`); if (textEl) textEl.value = e.target.value;
      return;
    }
    const textMap = { "theme-accent-text": ["accent", "theme-accent"], "theme-accent2-text": ["accent2", "theme-accent2"], "theme-bg-text": ["bg", "theme-bg"], "theme-surface-text": ["surface", "theme-surface"], "theme-text-text": ["text", "theme-text"] };
    const tk = textMap[e.target.id];
    if (tk && /^#[0-9a-fA-F]{6}$/.test(e.target.value)) {
      state.themeOverrides = { ...(state.themeOverrides || {}), [tk[0]]: e.target.value };
      applyTheme(state.theme, state.themeOverrides);
      const colorEl = $(`#${tk[1]}`); if (colorEl) colorEl.value = e.target.value;
      return;
    }
    if (e.target.id === "theme-radius") {
      state.uiRadius = Number(e.target.value);
      document.documentElement.style.setProperty("--radius", `${state.uiRadius}px`);
      const label = $("#radius-label"); if (label) label.textContent = `${state.uiRadius}px`;
    }
  });

  document.addEventListener("submit", (e) => e.preventDefault());
  $("#mobile-menu").addEventListener("click", () => document.body.classList.toggle("nav-open"));
  $("#sidebar-mask").addEventListener("click", () => document.body.classList.remove("nav-open"));
  $("#modal-root").addEventListener("click", (e) => { if (e.target.id === "modal-root") closeModal(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#modal-root").hidden) closeModal(); });
  window.addEventListener("hashchange", () => {
    const r = location.hash.replace(/^#\/?/, "") || "dashboard";
    if (r !== state.route) navigate(r, false);
  });
}

/* ------------------------------ boot ------------------------------ */
async function boot() {
  bindEvents();
  try {
    const saved = JSON.parse(localStorage.getItem("gur-theme") || "null");
    if (saved) {
      state.uiDensity = saved.density || "comfortable";
      state.uiRadius = Number(saved.radius) || 14;
      applyTheme(saved.name || "midnight", saved.overrides || {}, saved.mode || null);
    }
  } catch { /* ignore */ }
  const initial = location.hash.replace(/^#\/?/, "") || "dashboard";
  state.route = ROUTES[initial] ? initial : "dashboard";
  try { await loadSettings(); } catch (e) { state.settings = FALLBACK_SETTINGS; console.warn("settings:", e); toast("设置读取失败，使用默认主题", "err"); }
  const results = await Promise.allSettled([loadSummary(), loadSources(), loadChannels(), loadPresets()]);
  results.filter((r) => r.status === "rejected").forEach((r) => console.warn("boot:", r.reason));
  state.booted = true;
  render();
  if (["items", "alerts", "logs"].includes(state.route)) await loadRouteData(state.route);
}

boot().catch((e) => {
  console.error(e);
  const view = $("#view");
  if (view) view.innerHTML = `<div class="empty"><div class="empty-icon">${icon("alert", "lg")}</div><h4>界面初始化失败</h4><p>${esc(e.message)}</p><button class="btn" data-action="refresh">重试</button></div>`;
});
