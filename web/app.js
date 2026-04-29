const state = {
  data: null,
  discovery: [],
  discoveryScanned: false,
  toastId: 0,
  lastObservedGlyphKey: "",
};

const STORAGE_KEYS = {
  cleanupRetentionDays: "llama-model-manager.cleanupRetentionDays",
  remoteQuery: "llama-model-manager.remoteQuery",
  remoteLimit: "llama-model-manager.remoteLimit",
  remoteHideGated: "llama-model-manager.remoteHideGated",
  remoteDestinationRoot: "llama-model-manager.remoteDestinationRoot",
  contextGlyphosActivated: "llama-model-manager.contextGlyphosActivated",
  activityPanelVisible: "llama-model-manager.activityPanelVisible",
};

function $(selector) {
  return document.querySelector(selector);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function healthSummary(raw) {
  return String(raw || "unavailable").split(" ")[0];
}

function healthLabel(raw) {
  const summary = healthSummary(raw);
  if (summary === "ok") return "Healthy";
  if (summary === "unavailable") return "Unavailable";
  return summary;
}

function joinNotes(parts) {
  return parts.filter(Boolean).join(" · ");
}

function formatLocalTime(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  const parsed = new Date(text);
  if (!Number.isFinite(parsed.getTime())) return text;
  return parsed.toLocaleString();
}

function formatRelativeTime(value) {
  const parsed = value instanceof Date ? value : new Date(value);
  if (!Number.isFinite(parsed.getTime())) return "";
  const seconds = Math.max(0, Math.round((Date.now() - parsed.getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

function dateFromGlyphAttempt(item) {
  const time = Number(item?.time || 0);
  if (Number.isFinite(time) && time > 0) {
    return new Date(time * 1000);
  }
  const text = String(item?.happened_at || item?.created_at || "").trim();
  if (!text) return null;
  const parsed = new Date(text);
  return Number.isFinite(parsed.getTime()) ? parsed : null;
}

function isAtOrAfter(value, startValue) {
  if (!startValue) return true;
  const itemDate = value instanceof Date ? value : new Date(value);
  const startDate = new Date(startValue);
  if (!Number.isFinite(itemDate.getTime()) || !Number.isFinite(startDate.getTime())) return true;
  return itemDate.getTime() >= startDate.getTime();
}

function setNodeHidden(node, hidden) {
  if (node) node.classList.toggle("hidden", Boolean(hidden));
}

function titleize(value) {
  return String(value || "")
    .split("-")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function modeLabel(mode) {
  if (!mode) return "Stopped";
  if (mode === "single-client") return "Single Client";
  if (mode === "multi-client") return "Multi Client";
  return titleize(mode);
}

function laneLabel(parallel) {
  const count = Number(parallel);
  if (Number.isFinite(count) && count > 0) {
    return `${count} ${count === 1 ? "lane" : "lanes"} active`;
  }
  if (parallel) return `${parallel} lanes active`;
  return "lane count unavailable";
}

function registryLabel(count) {
  return `${count} ${count === 1 ? "model" : "models"}`;
}

function binarySummary(doctor) {
  if ((doctor.binary_status || "") === "unavailable") {
    return "Runtime unavailable";
  }

  const label = (doctor.binary_label && doctor.binary_label !== "none")
    ? doctor.binary_label
    : ((doctor.binary_backend && doctor.binary_backend !== "none" && doctor.binary_backend !== "external") ? doctor.binary_backend : "");
  const source = (doctor.binary_source && doctor.binary_source !== "none")
    ? doctor.binary_source.replaceAll("-", " ")
    : "";
  const status = (doctor.binary_status && doctor.binary_status !== "compatible")
    ? doctor.binary_status
    : "";

  return joinNotes([
    label,
    source,
    status,
  ]);
}

function basename(path) {
  return String(path || "").split("/").filter(Boolean).pop() || "";
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let amount = bytes;
  for (const unit of units) {
    if (amount < 1024 || unit === units[units.length - 1]) {
      return unit === "B" ? `${Math.round(amount)} ${unit}` : `${amount.toFixed(1)} ${unit}`;
    }
    amount /= 1024;
  }
  return `${bytes} B`;
}

function compactHomePath(value, data = {}) {
  const text = String(value || "").trim();
  const home = String(data?.meta?.home_dir || "").replace(/\/$/, "");
  if (!text || !home) {
    return text;
  }
  const normalizedHome = home.endsWith("/") ? home.slice(0, -1) : home;
  if (text === normalizedHome) {
    return "~";
  }
  if (text.startsWith(`${normalizedHome}/`)) {
    return `~/${text.slice(normalizedHome.length + 1)}`;
  }
  return text;
}

function displayPath(path) {
  const value = String(path || "");
  const homeDir = String(state.data?.meta?.home_dir || "");
  if (!value || !homeDir) return value;
  if (value === homeDir) return "~";
  if (value.startsWith(`${homeDir}/`)) return `~/${value.slice(homeDir.length + 1)}`;
  return value;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  const payload = await response.json().catch(() => ({ ok: false, error: "Invalid JSON response" }));
  if (!response.ok) {
    const error = new Error(payload.error || "Request failed");
    error.code = payload.code || "";
    throw error;
  }
  return payload;
}

function modelPresetSummary(model) {
  const parts = [];
  if (model.context) parts.push(`ctx ${model.context}`);
  if (model.ngl) parts.push(`ngl ${model.ngl}`);
  if (model.batch) parts.push(`b ${model.batch}`);
  if (model.threads) parts.push(`thr ${model.threads}`);
  if (model.parallel) parts.push(`np ${model.parallel}`);
  if (model.device) parts.push(model.device);
  if (model.mmproj) parts.push("mmproj");
  return parts.length ? parts.join(" · ") : "defaults";
}

function setText(selector, value) {
  const node = $(selector);
  if (node) node.textContent = value ?? "-";
}

function setTitle(selector, value) {
  const node = $(selector);
  if (node) node.title = value ?? "";
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function beginButtonBusy(button, pendingLabel) {
  if (!button) return () => {};
  const originalLabel = button.textContent;
  button.disabled = true;
  button.dataset.busy = "true";
  button.textContent = pendingLabel;
  return () => {
    button.disabled = false;
    button.textContent = originalLabel;
    delete button.dataset.busy;
  };
}

async function withButtonBusy(button, pendingLabel, task, options = {}) {
  const restore = beginButtonBusy(button, pendingLabel);
  try {
    const result = await task();
    if (options.successMessage) {
      showToast(options.successMessage, options.successKind || "success");
    }
    return result;
  } finally {
    restore();
  }
}

function pulseButton(button, pendingLabel, duration = 220) {
  const restore = beginButtonBusy(button, pendingLabel);
  window.setTimeout(restore, duration);
}

function toastRole(kind) {
  return kind === "error" ? "alert" : "status";
}

function showToast(message, kind = "info", options = {}) {
  const stack = $("#toast-stack");
  if (!stack || !message) return;

  const timeout = options.timeout ?? (kind === "error" ? 5200 : 2800);
  const toast = document.createElement("article");
  toast.className = `toast toast-${kind}`;
  toast.id = `toast-${++state.toastId}`;
  toast.setAttribute("role", toastRole(kind));
  toast.innerHTML = `
    <div class="toast-mark"></div>
    <div class="toast-body">${escapeHtml(message)}</div>
    <button type="button" class="toast-dismiss" aria-label="Dismiss notification">Dismiss</button>
  `;

  const dismiss = () => {
    toast.classList.remove("is-visible");
    window.setTimeout(() => toast.remove(), 180);
  };

  toast.querySelector(".toast-dismiss")?.addEventListener("click", dismiss);
  stack.appendChild(toast);
  window.requestAnimationFrame(() => toast.classList.add("is-visible"));
  window.setTimeout(dismiss, timeout);
}

function renderEmptyRow(tbody, colSpan, eyebrow, title, copy) {
  const row = document.createElement("tr");
  row.className = "empty-row";
  row.innerHTML = `
    <td colspan="${colSpan}">
      <div class="empty-state">
        <span class="empty-eyebrow">${escapeHtml(eyebrow)}</span>
        <strong class="empty-title">${escapeHtml(title)}</strong>
        <span class="empty-copy">${escapeHtml(copy)}</span>
      </div>
    </td>
  `;
  tbody.appendChild(row);
}

function holdButtonBusy(button, pendingLabel) {
  beginButtonBusy(button, pendingLabel);
}

function focusModelForm() {
  $("#model-form")?.scrollIntoView({ behavior: "smooth", block: "start" });
  $("#model-alias")?.focus();
}

function renderNotice(data) {
  const notice = $("#top-notice");
  if (!notice) return;

  const messages = [];
  const downloadJobs = data.download_jobs?.items || [];
  const activeDownloads = downloadJobs.filter((job) => ["queued", "running"].includes(String(job.status || "")));
  const resumableDownloads = downloadJobs.filter((job) => job.resume_available);
  if (data.demo) {
    messages.push("Demo mode is active. Registry and runtime values are sample data, not your local machine.");
  }
  if (!data.registry_exists) {
    messages.push(`No registry file exists yet at ${displayPath(data.registry_file)}. Save a model to create it, or scan a root and stage one from discovery.`);
  }
  if (!data.defaults_exists) {
    messages.push(`Defaults file is missing at ${displayPath(data.defaults_file)}. The dashboard is using built-in fallbacks until you save defaults.`);
  }
  if ((data.doctor?.external_owner || "") === "yes" && data.doctor?.external_owner_message) {
    messages.push(data.doctor.external_owner_message);
  }
  if (activeDownloads.length) {
    messages.push(`${activeDownloads.length} remote download ${activeDownloads.length === 1 ? "is" : "are"} currently active.`);
  }
  if (resumableDownloads.length) {
    const resumableBytes = resumableDownloads.reduce((total, job) => total + Number(job.partial_bytes || 0), 0);
    messages.push(`${resumableDownloads.length} interrupted download ${resumableDownloads.length === 1 ? "has" : "have"} ${formatBytes(resumableBytes)} of resumable partial data.`);
  }

  if (!messages.length) {
    notice.classList.add("hidden");
    notice.textContent = "";
    return;
  }

  notice.textContent = messages.join(" ");
  notice.classList.remove("hidden");
}

function renderHero(data) {
  const current = data.current || {};
  const doctor = data.doctor || {};
  const mode = data.mode || {};
  const registryCount = (data.models || []).length;
  const activeMode = modeLabel(mode.active_mode);
  const activeLanes = laneLabel(mode.active_parallel);
  const health = healthLabel(current.health);

  const unifiedMemoryLabel = (current.cuda_unified_memory || doctor.cuda_unified_memory) === "enabled" ? "Unified memory enabled." : "Unified memory disabled.";
  setText("#status-subtitle", `${health}. ${activeMode}. ${activeLanes}. ${registryLabel(registryCount)} in registry. ${unifiedMemoryLabel}`);
  setText("#hero-current-model", current.alias || "stopped");
  setText("#hero-current-path", basename(current.model) || "No model loaded");
  setText("#hero-current-mode", activeMode);
  setText("#hero-lanes", joinNotes([
    activeLanes,
    current.active_context ? `ctx ${current.active_context}` : "",
  ]) || "mode detail unavailable");
  setText("#hero-endpoint", data.api_base || "-");
  setText("#hero-build", binarySummary(doctor) || (doctor.build_info ? `build ${doctor.build_info}` : (doctor.server || "-")));
  setTitle("#hero-build", joinNotes([
    doctor.binary_message || "",
    doctor.binary_guidance || "",
  ]));
  setText("#hero-registry-count", registryLabel(registryCount));
  setText("#hero-health", `Health: ${health}`);
}

function serviceFlag(service, key) {
  return String(service?.[key] || "").toLowerCase() === "yes";
}

function dashboardServiceStatusLabel(service) {
  const status = String(service?.status || "unavailable");
  if (status === "running") return "Running";
  if (status === "stopped") return "Stopped";
  if (status === "not-installed") return "Not Installed";
  return "Unavailable";
}

function dashboardServiceSupportLabel(service) {
  if (!serviceFlag(service, "supported")) return "Unavailable On This System";
  if (!serviceFlag(service, "manager_reachable")) return "Session Unavailable";
  return "Available";
}

function renderDashboardService(service) {
  const supported = serviceFlag(service, "supported");
  const reachable = serviceFlag(service, "manager_reachable");
  const installed = serviceFlag(service, "installed");
  const enabled = serviceFlag(service, "enabled");
  const active = serviceFlag(service, "active");
  const logsAvailable = serviceFlag(service, "logs_available");

  setText("#dashboard-service-status", dashboardServiceStatusLabel(service));
  setText("#dashboard-service-message", service?.message || "-");
  setText("#dashboard-service-lifecycle", installed ? (active ? "Running" : "Installed") : "Not Installed");
  setText("#dashboard-service-login", installed ? (enabled ? "Enabled At Login" : "Not enabled at login") : "Install first");
  setText("#dashboard-service-url", service?.url || "-");
  setText("#dashboard-service-unit", service?.unit || "-");
  setText("#dashboard-service-support", dashboardServiceSupportLabel(service));
  setText("#dashboard-service-path", service?.unit_file ? displayPath(service.unit_file) : "-");

  const installButton = $("#dashboard-service-install");
  const enableButton = $("#dashboard-service-enable");
  const restartButton = $("#dashboard-service-restart");
  const stopButton = $("#dashboard-service-stop");
  const disableButton = $("#dashboard-service-disable");
  const removeButton = $("#dashboard-service-remove");
  const logsButton = $("#dashboard-service-logs");

  if (installButton) installButton.disabled = !supported || !reachable || !serviceFlag(service, "installable") || installed;
  if (enableButton) enableButton.disabled = !supported || !reachable || !installed || enabled;
  if (restartButton) restartButton.disabled = !supported || !reachable || !installed;
  if (stopButton) stopButton.disabled = !supported || !reachable || !installed || !active;
  if (disableButton) disableButton.disabled = !supported || !reachable || !installed || !enabled;
  if (removeButton) removeButton.disabled = !installed;
  if (logsButton) logsButton.disabled = !supported || !reachable || !installed || !logsAvailable;
}

function renderOwnershipConflict(doctor) {
  const card = $("#ownership-conflict-card");
  if (!card) return;

  if ((doctor.external_owner || "") !== "yes") {
    card.classList.add("hidden");
    setText("#ownership-conflict-status", "-");
    setText("#ownership-conflict-unit", "-");
    setText("#ownership-conflict-message", "-");
    return;
  }

  card.classList.remove("hidden");
  setText("#ownership-conflict-status", doctor.external_owner_unit || "External Process");
  setText("#ownership-conflict-unit", doctor.external_owner_unit ? `Unit ${doctor.external_owner_unit}` : "A foreign llama-server already owns this port.");
  setText("#ownership-conflict-message", doctor.external_owner_message || "Stop or move the conflicting service before switching models here.");
}

function renderStatus(data) {
  const current = data.current || {};
  const doctor = data.doctor || {};
  const mode = data.mode || {};
  const effectiveMode = mode.active_mode || mode.configured_mode || "";
  const nextMode = effectiveMode === "single-client" ? "Switch To Multi Client" : "Switch To Single Client";

  renderNotice(data);
  renderHero(data);
  renderDashboardService(data.dashboard_service || {});
  renderOwnershipConflict(doctor);
  renderOperationActivity(data.operation_activity || {}, data.meta || {});
  renderGlyphosTelemetry(data.glyphos_telemetry || {}, data);
  renderObservedGlyphRoutes(data.glyphos_telemetry || {}, data.meta?.dashboard_started_at || "");
  renderContextGlyphosPipeline(deriveContextGlyphosPipeline(data), deriveContextModeMcp(data), data.glyphos_telemetry || {});

  setText("#metric-model", current.alias || "stopped");
  setText("#metric-model-path", current.model || "No model running");
  setText("#metric-health", healthLabel(current.health));
  setText(
    "#metric-mode",
    joinNotes([
      mode.configured_mode ? `configured ${modeLabel(mode.configured_mode)}` : "",
      mode.active_mode ? `active ${modeLabel(mode.active_mode)}` : "",
      mode.active_parallel ? `lanes ${mode.active_parallel}` : "",
    ]) || "mode unavailable",
  );
  setText("#metric-offload", doctor.offload || "-");
  setText(
    "#metric-kv",
    joinNotes([
      doctor.kv_buffer ? `KV ${doctor.kv_buffer}` : "",
      doctor.graph_splits ? `splits ${doctor.graph_splits}` : "",
    ]) || "-",
  );
  setText("#metric-gpu-memory", doctor.fit_posture || "not reported");
  setText(
    "#metric-gpu-processes",
    joinNotes([
      doctor.gpu_memory || "",
      doctor.system_memory || "",
      doctor.cuda_unified_memory ? `UM ${doctor.cuda_unified_memory}` : "",
      doctor.gpu_process_count && doctor.gpu_process_count !== "0"
        ? `${doctor.gpu_process_count} llama-server process${doctor.gpu_process_count === "1" ? "" : "es"}`
        : "no llama-server GPU peers detected",
    ]),
  );
  setTitle("#metric-gpu-processes", joinNotes([
    doctor.fit_guidance || "",
    doctor.auto_fit_override_reason ? `override ${doctor.auto_fit_override_reason}` : "",
    doctor.gpu_processes || "",
  ]));
  setText("#metric-endpoint", data.api_base || "-");
  setText(
    "#metric-build",
    joinNotes([
      binarySummary(doctor),
      doctor.build_info ? `build ${doctor.build_info}` : "",
    ]) || (doctor.server || "-"),
  );
  setTitle(
    "#metric-build",
    joinNotes([
      doctor.binary_message || "",
      doctor.binary_guidance || "",
    ]),
  );
  setText("#api-base", data.api_base || "-");
  setText("#integration-endpoint-note", "OpenAI-compatible local endpoint.");
  setText("#opencode-model", data.opencode_model || "-");
  setText("#opencode-path", joinNotes([
    data.opencode_config_exists ? "config present" : "config missing",
    displayPath(data.opencode_config_file || ""),
  ]) || "-");
  setText("#opencode-state", joinNotes([
    data.opencode_preset ? `${data.opencode_preset} preset` : "not yet synced",
    data.opencode_timeout_ms ? `timeout ${Math.round(Number(data.opencode_timeout_ms) / 1000)}s` : "",
    data.opencode_chunk_timeout_ms ? `chunk ${Math.round(Number(data.opencode_chunk_timeout_ms) / 1000)}s` : "",
    data.opencode_note || "",
  ]) || "-");
  const opencodeBadge = $("#opencode-preset-badge");
  if (opencodeBadge) {
    opencodeBadge.classList.toggle("hidden", data.opencode_preset !== "long-run");
    opencodeBadge.title = data.opencode_note || "Long-run preset active for extended local reasoning sessions.";
  }
  setText("#openclaw-model", data.openclaw_model || "-");
  setText("#openclaw-path", joinNotes([
    `profile ${data.openclaw_profile || "main"}`,
    data.openclaw_config_exists ? "config present" : "config missing",
    displayPath(data.openclaw_config_file || ""),
  ]) || "-");
  setText("#claude-model", data.claude_model_id || "-");
  setText("#claude-path", joinNotes([
    data.claude_settings_exists ? "settings present" : "settings missing",
    displayPath(data.claude_settings_file || ""),
    data.claude_base_url || "",
  ]) || "-");
  const claudeGateway = data.claude_gateway || {};
  setText("#claude-gateway-status", (claudeGateway.running || "") === "yes" ? "Running" : "Stopped");
  setText("#claude-gateway-url", joinNotes([
    claudeGateway.url || "-",
    claudeGateway.model_id ? `model ${claudeGateway.model_id}` : "",
    claudeGateway.upstream_timeout_seconds ? `timeout ${claudeGateway.upstream_timeout_seconds}s` : "",
  ]) || "-");
  setText("#glyphos-model", data.glyphos_model || "-");
  setText("#glyphos-path", joinNotes([
    displayPath(data.glyphos_config_file || ""),
    data.glyphos_routing_preference || "",
  ]) || "-");
  setText("#toggle-mode", nextMode);
  setTitle(
    "#toggle-mode",
    mode.active_mode && mode.configured_mode && mode.active_mode !== mode.configured_mode
      ? `Runtime is currently ${modeLabel(mode.active_mode)} but defaults are configured for ${modeLabel(mode.configured_mode)}. The next switch follows the active runtime mode.`
      : effectiveMode === "single-client"
      ? "Restart the server in multi-client mode so multiple requests can run at once."
      : "Restart the server in single-client mode so one request runs at a time.",
  );
}

function isTruthySetting(value) {
  return ["1", "true", "yes", "on"].includes(String(value || "").trim().toLowerCase());
}

function contextGlyphosLocallyActivated() {
  try {
    return window.localStorage.getItem(STORAGE_KEYS.contextGlyphosActivated) === "1";
  } catch {
    return false;
  }
}

function setContextGlyphosLocallyActivated() {
  try {
    window.localStorage.setItem(STORAGE_KEYS.contextGlyphosActivated, "1");
  } catch {
    // Backend defaults remain the source of truth if browser storage is unavailable.
  }
}

function activityPanelVisible() {
  try {
    return window.localStorage.getItem(STORAGE_KEYS.activityPanelVisible) === "1";
  } catch {
    return false;
  }
}

function setActivityPanelVisible(visible) {
  try {
    window.localStorage.setItem(STORAGE_KEYS.activityPanelVisible, visible ? "1" : "0");
  } catch {
    // Visibility falls back to the default collapsed state if storage is unavailable.
  }
}

function renderActivityPanelVisibility(visible = activityPanelVisible()) {
  const panel = $(".activity-panel");
  const button = $("#toggle-activity-panel");
  const body = $("#activity-panel-body");
  panel?.classList.toggle("is-collapsed", !visible);
  if (button) button.textContent = visible ? "Hide Audit" : "Show Audit";
  if (body) body.hidden = !visible;
}

function deriveContextModeMcp(data) {
  const provided = data.context_mode_mcp || {};
  if (Object.keys(provided).length) return provided;
  return {
    available: true,
    lifecycle_matrix_exists: true,
    typecheck_script_exists: true,
    root: "integrations/context-mode-mcp",
  };
}

function deriveContextGlyphosPipeline(data) {
  const provided = data.context_glyphos_pipeline || {};
  if (Object.keys(provided).length) return provided;

  const defaults = data.defaults || {};
  const enabled = isTruthySetting(defaults.LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE) || contextGlyphosLocallyActivated();
  const hasActiveModel = Boolean((data.current || {}).model || data.glyphos_model);
  const glyphosReady = Boolean(data.glyphos_config_exists);
  const glyphosIntegrationReady = Boolean((data.glyphos_telemetry || {}).available);
  const blockers = [];
  if (!enabled) blockers.push("activate feature");
  if (!hasActiveModel) blockers.push("no active model");
  if (!glyphosReady) blockers.push("GlyphOS config missing");
  if (!glyphosIntegrationReady) blockers.push("GlyphOS integration unavailable");
  const ready = enabled && hasActiveModel && glyphosReady && glyphosIntegrationReady;

  return {
    enabled,
    ready,
    status: ready ? "ready" : (enabled ? "activation_pending" : "off"),
    label: ready ? "Enabled" : (enabled ? "Blocked" : "Off"),
    blockers,
    benefit: "Feature setting for Context MCP plus GlyphOS local routing.",
  };
}

function renderContextGlyphosPipeline(pipeline, contextModeMcp, glyphosTelemetry = {}) {
  const card = $("#context-glyphos-card");
  const badge = $("#context-glyphos-badge");
  const blockersNode = $("#context-glyphos-blockers");
  if (!card || !badge || !blockersNode) return;

  const status = pipeline.status || "off";
  const enabled = Boolean(pipeline.enabled);
  const routing = glyphosTelemetry?.routing && typeof glyphosTelemetry.routing === "object" ? glyphosTelemetry.routing : {};
  const observedAttempts = Number(routing.total_attempts || 0);
  card.classList.toggle("is-ready", status === "ready");
  card.classList.toggle("is-warn", status === "activation_pending");
  card.classList.toggle("is-off", status === "off");
  badge.textContent = status === "ready" ? "Enabled" : status === "activation_pending" ? "Blocked" : "Off";
  badge.classList.toggle("integration-badge-ready", status === "ready");
  badge.classList.toggle("integration-badge-warn", status === "activation_pending");
  badge.classList.toggle("integration-badge-muted", status === "off");

  setText("#context-glyphos-status", status === "ready" ? "Combined pipeline configured" : status === "activation_pending" ? "Feature enabled, waiting on prerequisites" : "Combined pipeline disabled");
  setText("#context-glyphos-path", joinNotes([
    contextModeMcp.available ? "Context MCP present" : "Context MCP missing",
    contextModeMcp.lifecycle_matrix_exists ? "lifecycle check available" : "",
    contextModeMcp.typecheck_script_exists ? "typecheck available" : "",
    contextModeMcp.root ? displayPath(contextModeMcp.root) : "",
  ]) || "-");
  setText(
    "#context-glyphos-benefit",
    enabled
      ? (observedAttempts > 0
        ? `Feature is enabled. Glyph-routed traffic has been observed in this dashboard session (${observedAttempts} attempts).`
        : "Feature is enabled, but no glyph-routed traffic has been observed in this dashboard session.")
      : "Activate Feature enables the combined setting and syncs GlyphOS configuration. Observed traffic appears separately.",
  );

  blockersNode.innerHTML = "";
  const blockers = Array.isArray(pipeline.blockers) ? pipeline.blockers : [];
  if (!blockers.length) {
    const chip = document.createElement("span");
    chip.className = "chip chip-success";
    chip.textContent = "configured";
    blockersNode.append(chip);
    return;
  }
  blockers.forEach((blocker) => {
    const chip = document.createElement("span");
    chip.className = status === "off" ? "chip chip-neutral" : "chip chip-danger";
    chip.textContent = blocker;
    blockersNode.append(chip);
  });
}

function renderModels(models) {
  const tbody = $("#models-table tbody");
  const template = $("#model-row-template");
  const currentAlias = state.data?.current?.alias || "";
  tbody.innerHTML = "";
  setText("#registry-count", String(models.length));

  if (!models.length) {
    const registryPath = displayPath(state.data?.registry_file || "~/.config/llama-server/models.tsv");
    const registryHint = state.data?.registry_exists
      ? "Use Scan Root to discover GGUF files or fill in the Model Editor below to create the first entry."
      : `No registry file exists yet. Saving a model will create ${registryPath}.`;
    renderEmptyRow(
      tbody,
      4,
      "Registry Empty",
      "No models are registered yet.",
      registryHint,
    );
    return;
  }

  for (const model of models) {
    const row = template.content.firstElementChild.cloneNode(true);
    const detailBits = [model.exists === "yes" ? "present" : "missing"];
    if (model.notes) detailBits.push(model.notes);

    row.dataset.alias = model.alias;
    row.classList.toggle("is-active", model.alias === currentAlias);
    row.querySelector(".alias-cell").textContent = model.alias;
    row.querySelector(".path-cell").innerHTML = `
      <div>${escapeHtml(model.path)}</div>
      <div class="secondary-line">${escapeHtml(detailBits.join(" · "))}</div>
    `;
    row.querySelector(".preset-cell").textContent = modelPresetSummary(model);
    row.querySelector("button[data-action='switch']").title =
      `Start serving ${model.alias} now using its saved presets and the global defaults.`;
    row.querySelector("button[data-action='edit']").title =
      `Load ${model.alias} into the editor so you can inspect or change settings without switching the live server.`;
    row.querySelector("button[data-action='remove']").title =
      `Remove the ${model.alias} registry entry. The model file stays on disk.`;
    tbody.appendChild(row);
  }
}

function renderDiscovery(items) {
  const tbody = $("#discovery-table tbody");
  const template = $("#discovery-row-template");
  tbody.innerHTML = "";
  setText("#discovery-count", String(items.length));

  if (!state.discoveryScanned) {
    const root = displayPath($("#discovery-root")?.value.trim() || state.data?.discovery_root || "~/models");
    renderEmptyRow(
      tbody,
      5,
      "Scan Ready",
      "Discovery has not run yet.",
      `Press Scan Root to walk ${root} for GGUF files. This avoids a recursive scan every time the dashboard opens.`,
    );
    return;
  }

  if (!items.length) {
    const root = displayPath($("#discovery-root")?.value.trim() || state.data?.discovery_root || "~/models");
    renderEmptyRow(
      tbody,
      5,
      "Nothing Found",
      "No GGUF candidates in this root yet.",
      `Try another folder or add model files under ${root}. Matching mmproj files are picked up automatically.`,
    );
    return;
  }

  for (const item of items) {
    const row = template.content.firstElementChild.cloneNode(true);
    const imported = item.imported === "yes";
    const action = row.querySelector("button");

    row.dataset.alias = item.alias;
    row.dataset.path = item.path;
    row.dataset.mmproj = item.mmproj || "";
    row.classList.toggle("is-imported", imported);
    row.querySelector(".alias-cell").textContent = item.alias;
    row.querySelector(".path-cell").textContent = item.path;
    row.querySelector(".mmproj-cell").textContent = item.mmproj || "-";
    row.querySelector(".status-cell").textContent = imported ? "already in registry" : "ready to stage";
    action.textContent = imported ? "Tune" : "Stage";
    action.title = imported
      ? `Load ${item.alias} into the editor to inspect or adjust its saved settings.`
      : `Copy ${item.alias} into the editor so you can review it and save it into the registry.`;
    tbody.appendChild(row);
  }
}

function remoteFitLabel(status) {
  if (!status) return "Unknown";
  if (status === "good-fit") return "Good Fit";
  if (status === "likely-tight") return "Likely Tight";
  if (status === "likely-incompatible") return "Likely Incompatible";
  return titleize(status);
}

function renderRemoteModels(remoteStore) {
  const tbody = $("#remote-models-table tbody");
  const template = $("#remote-row-template");
  if (!tbody || !template) return;
  tbody.innerHTML = "";

  const store = remoteStore && typeof remoteStore === "object" ? remoteStore : {};
  const rawItems = Array.isArray(store.items) ? store.items : [];
  const items = rawItems.filter((item) => item && typeof item === "object");

  const fetchedAt = String(store.fetched_at || "").trim();
  const fetchedLabel = fetchedAt ? `cached ${fetchedAt}` : "";
  setText("#remote-fetched-at", fetchedLabel ? `· ${fetchedLabel}` : "");
  setText("#remote-count", String(items.length));

  const guidance = $("#remote-guidance");
  if (guidance) {
    guidance.textContent = "";
    guidance.classList.add("hidden");
  }

  const query = String(store.query || "").trim();
  const hideGated = Boolean($("#remote-hide-gated")?.checked);
  const visible = hideGated
    ? items.filter((item) => String(item.gated || "") !== "yes" && String(item.private || "") !== "yes")
    : items;

  if (!query && !items.length) {
    renderEmptyRow(
      tbody,
      5,
      "Search Remote",
      "No remote cache has been built yet.",
      "Run Search Remote to fetch a cached list of Hugging Face GGUF artifacts. Downloads are only allowed for cached entries.",
    );
    return;
  }

  if (!visible.length) {
    const message = hideGated && items.length
      ? `All ${items.length} cached entries are gated/private. Disable Hide gated/private to view them.`
      : "No cached GGUF artifacts match the current filters.";
    renderEmptyRow(
      tbody,
      5,
      "Nothing Cached",
      "No usable remote artifacts in view.",
      message,
    );
    return;
  }

  if (hideGated && visible.length !== items.length && guidance) {
    guidance.textContent = `${items.length - visible.length} gated/private repo ${items.length - visible.length === 1 ? "entry is" : "entries are"} hidden.`;
    guidance.classList.remove("hidden");
  }

  for (const item of visible.slice(0, 300)) {
    const row = template.content.firstElementChild.cloneNode(true);
    const repoId = String(item.repo_id || "");
    const artifactName = String(item.artifact_name || "");
    const sourceUrl = String(item.source_url || "");
    const downloadUrl = String(item.download_url || "");
    const sizeBytes = Number(item.size_bytes || 0);
    const sizeHuman = String(item.size_human || "") || formatBytes(sizeBytes);
    const status = String(item.compatibility_status || "unknown");
    const summary = String(item.compatibility_summary || "");
    const gated = String(item.gated || "") === "yes";
    const priv = String(item.private || "") === "yes";

    row.dataset.repoId = repoId;
    row.dataset.artifactName = artifactName;
    row.dataset.downloadUrl = downloadUrl;

    row.querySelector(".repo-cell").innerHTML = sourceUrl
      ? `<a href="${escapeHtml(sourceUrl)}" target="_blank" rel="noreferrer">${escapeHtml(repoId || sourceUrl)}</a>`
      : escapeHtml(repoId);

    row.querySelector(".remote-artifact-cell").innerHTML = `
      <div>${escapeHtml(artifactName || "artifact")}</div>
      <div class="secondary-line">${escapeHtml(joinNotes([
        item.quant ? `quant ${item.quant}` : "",
        item.architecture ? String(item.architecture) : "",
        item.context ? `ctx ${item.context}` : "",
        item.mmproj_artifact_name ? "mmproj available" : "",
        gated ? "gated" : "",
        priv ? "private" : "",
      ]))}</div>
    `;

    row.querySelector(".size-cell").textContent = sizeHuman || "-";
    row.querySelector(".fit-cell").innerHTML = `
      <span class="status-pill status-${escapeHtml(status)}">${escapeHtml(remoteFitLabel(status))}</span>
      ${summary ? `<div class="secondary-line">${escapeHtml(summary)}</div>` : ""}
    `;

    const button = row.querySelector("button[data-action='download-remote']");
    if (button) {
      const disabledReason = gated || priv
        ? "This repo is gated/private on Hugging Face. Authentication is not supported in this manager."
        : (!repoId || !artifactName || !downloadUrl)
          ? "Remote metadata is incomplete for this artifact. Search again."
          : "";
      button.disabled = Boolean(disabledReason);
      button.title = disabledReason || `Queue download for ${artifactName}.`;
    }
    tbody.appendChild(row);
  }
}

function downloadStatusLabel(job) {
  const status = titleize(job.status || "unknown") || "Unknown";
  if (String(job.status || "") === "queued" && Number(job.queue_position || 0) > 0) {
    return Number(job.queue_position) === 1 ? `${status} · next` : `${status} · #${job.queue_position}`;
  }
  if (job.resume_available) {
    return `${status} · resumable`;
  }
  if (job.cancel_requested && ["queued", "running"].includes(String(job.status || ""))) {
    return `${status} · cancelling`;
  }
  return status;
}

function activityLabel(route, action) {
  const labels = {
    "/api/glyphos/sync": "config sync",
    "/api/context-glyphos/activate": "feature enable",
    "/api/opencode/sync": "config sync",
    "/api/openclaw/sync": "config sync",
    "/api/claude/sync": "config sync",
  };
  return labels[route] || action || "api";
}

function activityDetailNotes(route, existingDetail) {
  const notes = [];
  if (route === "/api/glyphos/sync") {
    notes.push("control action only", "writes GlyphOS config", "does not prove routed traffic");
  } else if (route === "/api/context-glyphos/activate") {
    notes.push("control action only", "enables combined feature setting", "does not prove routed traffic");
  }
  if (existingDetail) notes.push(existingDetail);
  return joinNotes(notes);
}

function renderOperationActivity(activityStore, meta = {}) {
  const feed = $("#activity-feed");
  const note = $("#activity-session-note");
  if (!feed) return;
  const store = activityStore && typeof activityStore === "object" ? activityStore : {};
  const allEvents = Array.isArray(store.events) ? store.events.filter((event) => event && typeof event === "object") : [];
  const startedAt = String(meta.dashboard_started_at || "");
  const events = allEvents.filter((event) => isAtOrAfter(event.happened_at || "", startedAt));
  const olderCount = Math.max(0, allEvents.length - events.length);
  const startedLabel = formatLocalTime(startedAt);
  if (note) {
    note.textContent = olderCount
      ? `${olderCount} older control ${olderCount === 1 ? "entry is" : "entries are"} hidden. Showing actions recorded since this dashboard process started${startedLabel ? ` at ${startedLabel}` : ""}.`
      : `Showing actions recorded since this dashboard process started${startedLabel ? ` at ${startedLabel}` : ""}.`;
  }

  if (!events.length) {
    feed.innerHTML = `
      <div class="activity-empty">
        <span class="empty-eyebrow">No Activity</span>
        <strong class="empty-title">No control actions recorded in this dashboard session.</strong>
        <span class="empty-copy">Audit entries are control-plane only and do not prove inference or glyph-routed traffic.</span>
      </div>
    `;
    return;
  }

  const rows = events.slice(0, 12).map((event) => {
    const route = String(event.route || "");
    const action = String(event.action || "");
    const actor = String(event.actor_source || "");
    const status = String(event.status || "");
    const durationMs = Number(event.duration_ms || 0);
    const happenedAt = formatLocalTime(event.happened_at || "");
    const errorCode = String(event.error_code || "");
    const errorMessage = String(event.error_message || "");
    const detail = activityDetailNotes(route, errorMessage || errorCode ? joinNotes([errorCode, errorMessage]) : "");

    return `
      <article class="activity-event">
        <div class="activity-main">
          <div class="activity-title">
            <span class="status-pill status-${escapeHtml(status || "unknown")}">${escapeHtml(titleize(status || "unknown"))}</span>
            <strong>${escapeHtml(joinNotes([activityLabel(route, action), route || ""]))}</strong>
          </div>
          <div class="activity-meta">${escapeHtml(joinNotes([
            actor ? `actor ${actor}` : "",
            Number.isFinite(durationMs) && durationMs > 0 ? `${Math.round(durationMs)}ms` : "",
            happenedAt ? happenedAt : "",
          ]))}</div>
          ${detail ? `<div class="activity-detail">${escapeHtml(detail)}</div>` : ""}
        </div>
      </article>
    `;
  });

  feed.innerHTML = rows.join("");
}

function renderGlyphosTelemetry(glyphosTelemetry, data = {}) {
  const card = $("#glyphos-card");
  const badge = $("#glyphos-badge");
  const statusNode = $("#glyphos-status");
  const summaryNode = $("#glyphos-telemetry-summary");
  const reasonsNode = $("#glyphos-telemetry-reasons");
  const recentNode = $("#glyphos-telemetry-recent");
  if (!summaryNode || !reasonsNode || !recentNode) return;

  const telemetry = glyphosTelemetry && typeof glyphosTelemetry === "object" ? glyphosTelemetry : {};
  const available = Boolean(telemetry.available);
  const routing = telemetry.routing && typeof telemetry.routing === "object" ? telemetry.routing : {};
  const total = Number(routing.total_attempts || 0);
  const attemptsByTarget = routing.attempts_by_target && typeof routing.attempts_by_target === "object" ? routing.attempts_by_target : {};
  const reasonCounts = routing.fallback_reason_counts && typeof routing.fallback_reason_counts === "object" ? routing.fallback_reason_counts : {};
  const recent = Array.isArray(routing.recent_attempts) ? routing.recent_attempts.filter((item) => item && typeof item === "object") : [];

  if (!available) {
    if (badge) badge.textContent = "Unavailable";
    if (statusNode) statusNode.textContent = "GlyphOS integration unavailable";
    card?.classList.remove("is-ready", "is-warn");
    card?.classList.add("is-off");
    badge?.classList.remove("integration-badge-ready", "integration-badge-warn");
    badge?.classList.add("integration-badge-muted");
    summaryNode.textContent = "Last route: never observed.";
    setNodeHidden(summaryNode, false);
    reasonsNode.innerHTML = "";
    recentNode.innerHTML = "";
    return;
  }

  if (badge) badge.textContent = "Configured";
  if (statusNode) statusNode.textContent = total > 0 ? "Configured for local routing" : "Configured for local routing. No traffic observed yet.";
  card?.classList.add("is-ready");
  card?.classList.remove("is-warn", "is-off");
  badge?.classList.add("integration-badge-ready");
  badge?.classList.remove("integration-badge-warn", "integration-badge-muted");

  const last = recent[0] || null;
  const lastDate = last ? dateFromGlyphAttempt(last) : null;
  const lastLabel = last ? joinNotes([
    `Last route: ${last.success ? "ok" : "error"}`,
    last.target ? `target ${last.target}` : "",
    last.reason_code ? `reason ${last.reason_code}` : "",
    lastDate ? formatLocalTime(lastDate) : "",
    lastDate ? formatRelativeTime(lastDate) : "",
  ]) : "Last route: never observed.";

  if (total === 0) {
    summaryNode.textContent = "";
    setNodeHidden(summaryNode, true);
  } else {
    summaryNode.textContent = lastLabel;
    setNodeHidden(summaryNode, false);
  }

  const targetBits = Object.entries(attemptsByTarget)
    .map(([target, count]) => `${target} ${count}`)
    .slice(0, 6);

  const reasonPairs = Object.entries(reasonCounts)
    .sort((a, b) => Number(b[1] || 0) - Number(a[1] || 0))
    .slice(0, 8);
  reasonsNode.innerHTML = reasonPairs.map(([key, count]) => {
    const label = `${key} ${count}`;
    const kind = String(key || "").includes(".error") ? "chip-danger" : "chip-neutral";
    return `<span class="chip ${kind}" title="${escapeHtml(key)}">${escapeHtml(label)}</span>`;
  }).join("");

  recentNode.innerHTML = recent.slice(0, 8).map((item) => {
    const target = String(item.target || "");
    const reason = String(item.reason_code || "");
    const success = Boolean(item.success);
    const latency = Number(item.latency_ms || 0);
    const time = dateFromGlyphAttempt(item);
    const label = joinNotes([
      success ? "ok" : "error",
      target,
      reason,
      Number.isFinite(latency) && latency > 0 ? `${latency}ms` : "",
      time ? formatLocalTime(time) : "",
      time ? formatRelativeTime(time) : "",
    ]);
    return `<div class="telemetry-item">${escapeHtml(label)}</div>`;
  }).join("");

  if (total === 0) {
    recentNode.innerHTML = '<div class="telemetry-item">idle</div>';
  } else if (!targetBits.length) {
    reasonsNode.innerHTML = '<span class="chip chip-neutral">observed</span>';
  }
}

function glyphAttemptKey(item) {
  if (!item) return "";
  return [
    item.time || "",
    item.target || "",
    item.reason_code || "",
    item.success ? "ok" : "error",
  ].join("|");
}

function pulseObservedGlyphRoutes() {
  ["#observed-glyph-last-status", "#observed-glyph-total", "#observed-glyph-targets", "#observed-glyph-feed"].forEach((selector) => {
    const node = $(selector);
    if (!node) return;
    node.classList.remove("pulse-signal");
    void node.offsetWidth;
    node.classList.add("pulse-signal");
  });
}

function renderObservedGlyphRoutes(glyphosTelemetry, dashboardStartedAt = "") {
  const feed = $("#observed-glyph-feed");
  if (!feed) return;
  const telemetry = glyphosTelemetry && typeof glyphosTelemetry === "object" ? glyphosTelemetry : {};
  const routing = telemetry.routing && typeof telemetry.routing === "object" ? telemetry.routing : {};
  const total = Number(routing.total_attempts || 0);
  const recent = Array.isArray(routing.recent_attempts) ? routing.recent_attempts.filter((item) => item && typeof item === "object") : [];
  const sessionRecent = recent.filter((item) => {
    const date = dateFromGlyphAttempt(item);
    return !date || isAtOrAfter(date, dashboardStartedAt);
  });
  const observedCount = Number.isFinite(total) && total > sessionRecent.length ? total : sessionRecent.length;
  const latest = sessionRecent[0] || null;
  const latestKey = glyphAttemptKey(latest);
  if (latestKey && state.lastObservedGlyphKey && latestKey !== state.lastObservedGlyphKey) {
    pulseObservedGlyphRoutes();
  }
  if (latestKey) state.lastObservedGlyphKey = latestKey;

  if (!Boolean(telemetry.available) || !observedCount || !sessionRecent.length) {
    setText("#observed-glyph-last-status", "Never observed");
    setText("#observed-glyph-last-detail", observedCount ? "Glyph route attempts were counted, but no recent route detail is available." : "No glyph-routed traffic has been seen by this dashboard session yet.");
    setText("#observed-glyph-total", String(observedCount || 0));
    setText("#observed-glyph-total-detail", observedCount ? `${observedCount} glyph route ${observedCount === 1 ? "attempt was" : "attempts were"} counted in this dashboard session.` : "No glyph route attempts observed in this dashboard session.");
    setText("#observed-glyph-targets", "None yet");
    setText("#observed-glyph-targets-detail", "Targets will appear here after the first observed glyph route.");
    feed.innerHTML = `
      <div class="activity-empty">
        <span class="empty-eyebrow">No Observed Routes</span>
        <strong class="empty-title">No glyph-routed traffic observed yet.</strong>
        <span class="empty-copy">Sync and Activate Feature write configuration only. The first routed inference call will appear here.</span>
      </div>
    `;
    return;
  }

  const latestDate = dateFromGlyphAttempt(latest);
  const targetCounts = new Map();
  sessionRecent.forEach((item) => {
    const target = String(item.target || "unknown");
    targetCounts.set(target, (targetCounts.get(target) || 0) + 1);
  });
  const targetSummary = [...targetCounts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([target, count]) => `${target} ${count}`)
    .join(", ");

  setText("#observed-glyph-last-status", latest.success ? "Observed OK" : "Observed Error");
  setText("#observed-glyph-last-detail", joinNotes([
    latest.target ? `target ${latest.target}` : "",
    latest.reason_code ? `reason ${latest.reason_code}` : "",
    latestDate ? formatLocalTime(latestDate) : "",
    latestDate ? formatRelativeTime(latestDate) : "",
  ]) || "-");
  setText("#observed-glyph-total", String(observedCount));
  setText("#observed-glyph-total-detail", `${observedCount} glyph route ${observedCount === 1 ? "attempt" : "attempts"} observed in this dashboard session.`);
  setText("#observed-glyph-targets", targetSummary || "Unknown");
  setText("#observed-glyph-targets-detail", "Most recent observed route targets in this dashboard session.");

  feed.innerHTML = sessionRecent.slice(0, 10).map((item) => {
    const date = dateFromGlyphAttempt(item);
    const latency = Number(item.latency_ms || 0);
    return `
      <div class="telemetry-item">
        ${escapeHtml(joinNotes([
          item.success ? "ok" : "error",
          item.target ? `target ${item.target}` : "",
          item.reason_code ? `reason ${item.reason_code}` : "",
          Number.isFinite(latency) && latency > 0 ? `${latency}ms` : "",
          date ? formatLocalTime(date) : "",
          date ? formatRelativeTime(date) : "",
        ]))}
      </div>
    `;
  }).join("");
}

function renderDownloads(jobs) {
  const tbody = $("#downloads-table tbody");
  const template = $("#download-row-template");
  if (!tbody || !template) return;
  tbody.innerHTML = "";
  setText("#download-count", String(jobs.length));
  const hasRunningJobs = jobs.some((job) => String(job.status || "") === "running");
  const hasPartialData = jobs.some((job) => Number(job.partial_bytes || 0) > 0);
  const recoverButton = $("#recover-downloads");
  const cleanupButton = $("#cleanup-downloads");
  const cleanupDuplicatesButton = $("#cleanup-duplicate-downloads");
  const deleteOrphansButton = $("#delete-orphaned-artifacts");
  const pauseQueueButton = $("#pause-download-queue");
  const resumeQueueButton = $("#resume-download-queue");
  const clearQueueButton = $("#clear-download-queue");
  const storage = state.data?.download_storage || {};
  const policy = state.data?.download_policy || {};
  if (recoverButton) {
    recoverButton.hidden = !hasRunningJobs;
    recoverButton.title = hasRunningJobs
      ? "Mark stale running jobs from an old web-manager process as failed so they can be resumed or retried."
      : "No running download jobs need stale-worker recovery.";
  }
  if (cleanupButton) {
    cleanupButton.hidden = !hasPartialData;
    cleanupButton.title = hasPartialData
      ? "Remove stale partial files from old cancelled or failed jobs. Active and fresh partials are kept."
      : "No partial download files are currently tracked.";
  }
  if (cleanupDuplicatesButton) {
    cleanupDuplicatesButton.hidden = !storage.duplicate_completed_count;
    cleanupDuplicatesButton.title = storage.duplicate_completed_count
      ? "Remove redundant completed job records that point at the same artifact path. Model files are kept."
      : "No duplicate completed job records are currently tracked.";
  }
  if (deleteOrphansButton) {
    deleteOrphansButton.hidden = !storage.orphaned_artifact_count;
    deleteOrphansButton.title = storage.orphaned_artifact_count
      ? "Delete orphaned GGUF files under known download roots. Registry and completed-job artifacts are kept."
      : "No orphaned GGUF files are currently tracked.";
  }
  if (pauseQueueButton) {
    pauseQueueButton.hidden = Boolean(policy.queue_paused);
    pauseQueueButton.disabled = !policy.queued_downloads;
    pauseQueueButton.title = policy.queued_downloads
      ? "Pause starting queued downloads. Running jobs continue."
      : "No queued downloads are waiting.";
  }
  if (resumeQueueButton) {
    resumeQueueButton.hidden = !policy.queue_paused;
    resumeQueueButton.title = "Resume starting queued downloads up to the running slot limit.";
  }
  if (clearQueueButton) {
    clearQueueButton.hidden = !policy.queued_downloads;
    clearQueueButton.title = policy.queued_downloads
      ? "Remove all queued jobs. Running jobs and files are not touched."
      : "No queued downloads are waiting.";
  }
  setText(
    "#download-storage-summary",
    joinNotes([
      storage.partial_bytes ? `${formatBytes(storage.partial_bytes)} partials retained` : "",
      storage.duplicate_completed_count ? `${storage.duplicate_completed_count} duplicate completed artifact ${storage.duplicate_completed_count === 1 ? "path" : "paths"}` : "",
      storage.orphaned_artifact_count ? `${storage.orphaned_artifact_count} orphaned artifact ${storage.orphaned_artifact_count === 1 ? "file" : "files"} (${formatBytes(storage.orphaned_artifact_bytes || 0)})` : "",
      Number.isFinite(Number(policy.max_active_downloads)) ? `${policy.running_downloads || 0}/${policy.max_active_downloads} running slots used` : "",
      policy.queued_downloads ? `${policy.queued_downloads} queued` : "",
    ]),
  );
  const slotInput = $("#download-slot-limit");
  if (slotInput && document.activeElement !== slotInput && Number(policy.max_active_downloads || 0) > 0) {
    slotInput.value = String(policy.max_active_downloads);
  }
  const duplicateGuidance = $("#download-duplicate-guidance");
  if (duplicateGuidance) {
    const guidance = [];
    if (policy.at_capacity) {
      guidance.push(`Running download slots are full (${policy.running_downloads}/${policy.max_active_downloads}). New artifacts will wait in the queue until a slot opens.`);
    }
    if (policy.queue_paused) {
      guidance.push("Download queue is paused and will stay paused across web-manager restarts. Running jobs continue, but queued jobs will not start until resumed.");
    }
    if (policy.next_queued_job?.artifact_name) {
      guidance.push(`Next queued artifact: ${policy.next_queued_job.artifact_name}.`);
    }
    if (policy.duplicate_active_count) {
      guidance.push(`${policy.duplicate_active_count} duplicate active artifact ${policy.duplicate_active_count === 1 ? "entry was" : "entries were"} detected. New starts reuse the existing active job for the same artifact.`);
    }
    if (storage.duplicate_completed_count) {
      guidance.push(`${storage.duplicate_completed_job_records || 0} redundant completed job ${storage.duplicate_completed_job_records === 1 ? "record points" : "records point"} at existing artifact paths. ${storage.duplicate_cleanup_guidance || "Review before deleting files."}`);
    }
    if (storage.orphaned_artifact_count) {
      guidance.push(`${storage.orphaned_artifact_count} orphaned artifact ${storage.orphaned_artifact_count === 1 ? "file is" : "files are"} under known download roots. ${storage.orphaned_cleanup_guidance || "Review before deleting files."}`);
    }
    if (guidance.length) {
      duplicateGuidance.textContent = guidance.join(" ");
      duplicateGuidance.classList.remove("hidden");
    } else {
      duplicateGuidance.textContent = "";
      duplicateGuidance.classList.add("hidden");
    }
  }

  if (!jobs.length) {
    renderEmptyRow(
      tbody,
      4,
      "No Transfers",
      "No remote download jobs are tracked yet.",
      "Remote downloads will appear here with cancel, resume, and retry controls once they are started.",
    );
    return;
  }

  for (const job of jobs) {
    const row = template.content.firstElementChild.cloneNode(true);
    const status = String(job.status || "");
    const progress = Number(job.progress || 0);
    const percent = Number.isFinite(progress) ? Math.round(Math.min(progress, 1) * 100) : 0;
    const bytes = `${formatBytes(job.bytes_downloaded || 0)} / ${formatBytes(job.bytes_total || 0)}`;
    const partial = job.partial_bytes > 0 ? `partial ${formatBytes(job.partial_bytes)}` : "";
    const cancelButton = row.querySelector("button[data-action='cancel']");
    const resumeButton = row.querySelector("button[data-action='resume']");
    const retryButton = row.querySelector("button[data-action='retry']");
    const removeQueuedButton = row.querySelector("button[data-action='remove-queued']");
    const prioritizeQueuedButton = row.querySelector("button[data-action='prioritize-queued']");
    const deprioritizeQueuedButton = row.querySelector("button[data-action='deprioritize-queued']");

    row.dataset.jobId = job.id || "";
    row.querySelector(".artifact-cell").innerHTML = `
      <div>${escapeHtml(job.artifact_name || job.id || "download")}</div>
      <div class="secondary-line">${escapeHtml(joinNotes([job.repo_id || "", compactHomePath(job.destination_root || "", state.data)]))}</div>
    `;
    row.querySelector(".download-status-cell").innerHTML = `
      <span class="status-pill status-${escapeHtml(status || "unknown")}">${escapeHtml(downloadStatusLabel(job))}</span>
      ${job.error ? `<div class="secondary-line">${escapeHtml(job.error)}</div>` : ""}
    `;
    row.querySelector(".download-progress-cell").innerHTML = `
      <div class="progress-track" aria-label="Download progress">
        <span style="width: ${percent}%"></span>
      </div>
      <div class="secondary-line">${escapeHtml(joinNotes([`${percent}%`, bytes, partial]))}</div>
    `;

    cancelButton.hidden = !["queued", "running"].includes(status);
    resumeButton.hidden = !job.resume_available;
    retryButton.hidden = !["failed", "cancelled"].includes(status);
    removeQueuedButton.hidden = status !== "queued";
    prioritizeQueuedButton.hidden = status !== "queued" || !job.can_prioritize;
    deprioritizeQueuedButton.hidden = status !== "queued" || !job.can_deprioritize;
    const label = job.artifact_name || job.id;
    cancelButton.title = status === "queued"
      ? `Cancel ${label}. Removes it from the queue. Partial data is preserved when possible for resume.`
      : `Cancel ${label}. Requests cancellation for the active transfer. Partial data is preserved when possible for resume.`;
    resumeButton.title = `Resume ${label} from ${formatBytes(job.partial_bytes || 0)}. Use Retry to restart from byte zero.`;
    retryButton.title = `Retry ${label} from byte zero. Use Resume when a partial file exists.`;
    removeQueuedButton.title = `Remove queued job ${label}. No files are deleted; partial cleanup is separate.`;
    prioritizeQueuedButton.title = `Move queued job ${label} ahead of other queued downloads (does not interrupt running jobs).`;
    deprioritizeQueuedButton.title = `Move queued job ${label} one slot later (does not interrupt running jobs).`;

    const statusCell = row.querySelector(".download-status-cell");
    if (statusCell) {
      const hints = [];
      if (status === "queued" && policy.queue_paused) {
        hints.push("Queue paused: resume the queue to start.");
      }
      if (status === "queued" && policy.at_capacity) {
        hints.push(`At capacity: waits for a running slot (${policy.running_downloads}/${policy.max_active_downloads}).`);
      }
      if (status === "failed") {
        hints.push("Failed: use Resume if partial data exists, otherwise Retry.");
      }
      if (status === "cancelled") {
        hints.push("Cancelled: use Resume to continue partial, or Retry to restart.");
      }
      statusCell.title = hints.join(" ");
      if (hints.length) {
        statusCell.insertAdjacentHTML("beforeend", `<div class="secondary-line">${escapeHtml(hints.join(" "))}</div>`);
      }
    }
    tbody.appendChild(row);
  }
}

function loadCleanupRetentionPreference() {
  const input = $("#cleanup-retention-days");
  if (!input) return;
  const saved = window.localStorage.getItem(STORAGE_KEYS.cleanupRetentionDays);
  if (saved !== null && saved !== "" && Number.isFinite(Number(saved))) {
    input.value = saved;
  }
}

function saveCleanupRetentionPreference() {
  const input = $("#cleanup-retention-days");
  if (!input) return;
  const value = Math.max(0, Number(input.value || 7));
  input.value = String(value);
  window.localStorage.setItem(STORAGE_KEYS.cleanupRetentionDays, String(value));
}

function loadRemotePreferences() {
  const queryInput = $("#remote-query");
  const limitInput = $("#remote-limit");
  const rootInput = $("#remote-destination-root");
  const hideInput = $("#remote-hide-gated");

  if (queryInput) {
    const saved = window.localStorage.getItem(STORAGE_KEYS.remoteQuery);
    if (saved !== null && saved !== "") queryInput.value = saved;
  }
  if (limitInput) {
    const saved = window.localStorage.getItem(STORAGE_KEYS.remoteLimit);
    if (saved !== null && saved !== "" && Number.isFinite(Number(saved))) {
      limitInput.value = saved;
    }
  }
  if (rootInput) {
    const saved = window.localStorage.getItem(STORAGE_KEYS.remoteDestinationRoot);
    if (saved !== null && saved !== "") rootInput.value = saved;
  }
  if (hideInput) {
    const saved = window.localStorage.getItem(STORAGE_KEYS.remoteHideGated);
    if (saved !== null) hideInput.checked = saved === "1";
  }
}

function saveRemotePreferences() {
  const queryInput = $("#remote-query");
  const limitInput = $("#remote-limit");
  const rootInput = $("#remote-destination-root");
  const hideInput = $("#remote-hide-gated");

  if (queryInput) window.localStorage.setItem(STORAGE_KEYS.remoteQuery, queryInput.value.trim());
  if (limitInput) window.localStorage.setItem(STORAGE_KEYS.remoteLimit, String(Math.max(1, Number(limitInput.value || 30))));
  if (rootInput) window.localStorage.setItem(STORAGE_KEYS.remoteDestinationRoot, rootInput.value.trim());
  if (hideInput) window.localStorage.setItem(STORAGE_KEYS.remoteHideGated, hideInput.checked ? "1" : "0");
}

function fillModelForm(model) {
  $("#model-alias").value = model.alias || "";
  $("#model-path").value = model.path || "";
  $("#model-mmproj").value = model.mmproj || "";
  $("#model-extra").value = model.extra_args || "";
  $("#model-context").value = model.context || "";
  $("#model-ngl").value = model.ngl || "";
  $("#model-batch").value = model.batch || "";
  $("#model-threads").value = model.threads || "";
  $("#model-parallel").value = model.parallel || "";
  $("#model-device").value = model.device || "";
  $("#model-notes").value = model.notes || "";
}

function clearModelForm() {
  fillModelForm({
    alias: "",
    path: "",
    mmproj: "",
    extra_args: "",
    context: "",
    ngl: "",
    batch: "",
    threads: "",
    parallel: "",
    device: "",
    notes: "",
  });
}

function renderDefaults(defaults) {
  $("#default-host").value = defaults.LLAMA_SERVER_HOST || "";
  $("#default-port").value = defaults.LLAMA_SERVER_PORT || "";
  $("#default-device").value = defaults.LLAMA_SERVER_DEVICE || "";
  $("#default-context").value = defaults.LLAMA_SERVER_CONTEXT || "";
  $("#default-ngl").value = defaults.LLAMA_SERVER_NGL || "";
  $("#default-batch").value = defaults.LLAMA_SERVER_BATCH || "";
  $("#default-threads").value = defaults.LLAMA_SERVER_THREADS || "";
  $("#default-parallel").value = defaults.LLAMA_SERVER_PARALLEL || "";
  $("#default-cuda-unified-memory").checked = String(defaults.GGML_CUDA_ENABLE_UNIFIED_MEMORY || "").trim() === "1";
  $("#default-log").value = defaults.LLAMA_SERVER_LOG || "";
  $("#default-extra").value = defaults.LLAMA_SERVER_EXTRA_ARGS || "";
  $("#default-sync-opencode").value = defaults.LLAMA_MODEL_SYNC_OPENCODE || "1";
  $("#default-sync-claude").value = defaults.LLAMA_MODEL_SYNC_CLAUDE || "0";
  $("#default-sync-openclaw").value = defaults.LLAMA_MODEL_SYNC_OPENCLAW || "0";
  $("#default-sync-glyphos").value = defaults.LLAMA_MODEL_SYNC_GLYPHOS || "0";
  $("#default-context-glyphos-pipeline").checked = isTruthySetting(defaults.LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE) || contextGlyphosLocallyActivated();
  $("#default-openclaw-profile").value = defaults.OPENCLAW_PROFILE || "";
  $("#default-openclaw-api-key").value = defaults.OPENCLAW_API_KEY || "";
  $("#default-claude-gateway-host").value = defaults.CLAUDE_GATEWAY_HOST || "";
  $("#default-claude-gateway-port").value = defaults.CLAUDE_GATEWAY_PORT || "";
  $("#default-claude-gateway-log").value = defaults.CLAUDE_GATEWAY_LOG || "";
  $("#default-claude-gateway-timeout").value = defaults.CLAUDE_GATEWAY_UPSTREAM_TIMEOUT_SECONDS || "";
  $("#default-claude-base-url").value = defaults.CLAUDE_BASE_URL || "";
  $("#default-claude-model-id").value = defaults.CLAUDE_MODEL_ID || "";
  $("#default-claude-auth-token").value = defaults.CLAUDE_AUTH_TOKEN || "";
  $("#default-claude-api-key").value = defaults.CLAUDE_API_KEY || "";
}

async function refreshState() {
  state.data = await api("/api/state");
  $("#discovery-root").value = displayPath(state.data.discovery_root || "");
  const remoteRoot = $("#remote-destination-root");
  if (remoteRoot && !remoteRoot.value.trim()) {
    remoteRoot.value = compactHomePath(state.data.discovery_root, state.data) || "";
  }
  renderStatus(state.data);
  renderModels(state.data.models || []);
  renderRemoteModels(state.data.remote_models || {});
  renderDownloads(state.data.download_jobs?.items || []);
  renderDefaults(state.data.defaults || {});
}

async function refreshLogs() {
  const payload = await api("/api/logs?lines=100");
  const output = $("#logs-output");
  output.classList.remove("hidden");
  output.textContent = payload.content || "";
  output.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function scanModels() {
  const root = $("#discovery-root").value.trim();
  const payload = await api("/api/discover", {
    method: "POST",
    body: JSON.stringify({ root }),
  });
  state.discoveryScanned = true;
  state.discovery = payload.items || [];
  renderDiscovery(state.discovery);
  return payload.items || [];
}

async function saveModel(event) {
  event.preventDefault();
  const submitButton = event.submitter || $("#model-form button[type='submit']");
  const payload = {
    alias: $("#model-alias").value.trim(),
    path: $("#model-path").value.trim(),
    mmproj: $("#model-mmproj").value.trim(),
    extra_args: $("#model-extra").value.trim(),
    context: $("#model-context").value.trim(),
    ngl: $("#model-ngl").value.trim(),
    batch: $("#model-batch").value.trim(),
    threads: $("#model-threads").value.trim(),
    parallel: $("#model-parallel").value.trim(),
    device: $("#model-device").value.trim(),
    notes: $("#model-notes").value.trim(),
  };

  await withButtonBusy(submitButton, "Saving...", async () => {
    await api("/api/models/save", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    await refreshState();
    await scanModels();
    clearModelForm();
  }, {
    successMessage: `Saved ${payload.alias || "model"} to the registry.`,
  });
}

async function performDashboardServiceAction(action, button, options = {}) {
  const managed = Boolean(state.data?.meta?.dashboard_service_managed);
  if (options.confirmMessage && !window.confirm(options.confirmMessage)) return;

  if (options.expectDisconnect && managed) {
    const restore = beginButtonBusy(button, options.pendingLabel || "Working...");
    try {
      await fetch("/api/dashboard-service", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
    } catch (error) {
      console.info("dashboard service action likely disconnected the current page", error);
    } finally {
      restore();
    }
    showToast(options.disconnectMessage || "Service action requested. This page may disconnect.", "info", { timeout: 5200 });
    return;
  }

  await withButtonBusy(button, options.pendingLabel || "Working...", async () => {
    await api("/api/dashboard-service", {
      method: "POST",
      body: JSON.stringify({ action }),
    });
    await refreshState();
  }, {
    successMessage: options.successMessage,
    successKind: options.successKind || "success",
  });
}

async function loadDashboardServiceLogs(button) {
  await withButtonBusy(button, "Loading...", async () => {
    const payload = await api("/api/dashboard-service/logs?lines=100");
    const output = $("#service-logs-output");
    output.classList.remove("hidden");
    output.textContent = payload.content || "";
    output.scrollIntoView({ behavior: "smooth", block: "start" });
  }, {
    successMessage: "Loaded dashboard service logs.",
    successKind: "info",
  });
}

async function performIntegrationSync(path, button, pendingLabel, successMessage, payload = {}) {
  await withButtonBusy(button, pendingLabel, async () => {
    await api(path, { method: "POST", body: JSON.stringify(payload) });
    await refreshState();
  }, {
    successMessage,
  });
}

function collectDefaultsPayload() {
  return {
    LLAMA_SERVER_HOST: $("#default-host").value.trim(),
    LLAMA_SERVER_PORT: $("#default-port").value.trim(),
    LLAMA_SERVER_DEVICE: $("#default-device").value.trim(),
    LLAMA_SERVER_CONTEXT: $("#default-context").value.trim(),
    LLAMA_SERVER_NGL: $("#default-ngl").value.trim(),
    LLAMA_SERVER_BATCH: $("#default-batch").value.trim(),
    LLAMA_SERVER_THREADS: $("#default-threads").value.trim(),
    LLAMA_SERVER_PARALLEL: $("#default-parallel").value.trim(),
    GGML_CUDA_ENABLE_UNIFIED_MEMORY: $("#default-cuda-unified-memory").checked ? "1" : "",
    LLAMA_SERVER_LOG: $("#default-log").value.trim(),
    LLAMA_SERVER_EXTRA_ARGS: $("#default-extra").value.trim(),
    LLAMA_MODEL_SYNC_OPENCODE: $("#default-sync-opencode").value.trim(),
    LLAMA_MODEL_SYNC_CLAUDE: $("#default-sync-claude").value.trim(),
    LLAMA_MODEL_SYNC_OPENCLAW: $("#default-sync-openclaw").value.trim(),
    LLAMA_MODEL_SYNC_GLYPHOS: $("#default-sync-glyphos").value.trim(),
    LLAMA_MODEL_CONTEXT_GLYPHOS_PIPELINE: $("#default-context-glyphos-pipeline").checked ? "1" : "",
    OPENCLAW_PROFILE: $("#default-openclaw-profile").value.trim(),
    OPENCLAW_API_KEY: $("#default-openclaw-api-key").value.trim(),
    CLAUDE_GATEWAY_HOST: $("#default-claude-gateway-host").value.trim(),
    CLAUDE_GATEWAY_PORT: $("#default-claude-gateway-port").value.trim(),
    CLAUDE_GATEWAY_LOG: $("#default-claude-gateway-log").value.trim(),
    CLAUDE_GATEWAY_UPSTREAM_TIMEOUT_SECONDS: $("#default-claude-gateway-timeout").value.trim(),
    CLAUDE_BASE_URL: $("#default-claude-base-url").value.trim(),
    CLAUDE_MODEL_ID: $("#default-claude-model-id").value.trim(),
    CLAUDE_AUTH_TOKEN: $("#default-claude-auth-token").value.trim(),
    CLAUDE_API_KEY: $("#default-claude-api-key").value.trim(),
  };
}

async function activateContextGlyphos(button) {
  await withButtonBusy(button, "Activating...", async () => {
    $("#default-context-glyphos-pipeline").checked = true;
    $("#default-sync-glyphos").value = "1";
    try {
      await api("/api/context-glyphos/activate", { method: "POST", body: "{}" });
    } catch (error) {
      const isUnknownActivationRoute = error.code === "unknown_route" || String(error.message || "").toLowerCase().includes("unknown api route");
      if (!isUnknownActivationRoute) {
        throw error;
      }
      await api("/api/defaults/save", {
        method: "POST",
        body: JSON.stringify(collectDefaultsPayload()),
      });
      await api("/api/glyphos/sync", { method: "POST", body: "{}" });
    }
    setContextGlyphosLocallyActivated();
    await refreshState();
    const pipeline = deriveContextGlyphosPipeline(state.data || {});
    if (pipeline.ready) {
      showToast("Context + GlyphOS is ready.", "success");
      return;
    }
    const blockers = Array.isArray(pipeline.blockers) && pipeline.blockers.length
      ? ` Blocked by: ${pipeline.blockers.join(", ")}.`
      : "";
    showToast(`Context + GlyphOS activation saved, but it is not ready yet.${blockers}`, "info", { timeout: 6200 });
  }, {
    successMessage: "",
  });
}

async function performClaudeGatewayAction(action, button, options = {}) {
  await withButtonBusy(button, options.pendingLabel || "Working...", async () => {
    await api("/api/claude-gateway", {
      method: "POST",
      body: JSON.stringify({ action }),
    });
    await refreshState();
  }, {
    successMessage: options.successMessage,
    successKind: options.successKind || "info",
  });
}

async function loadClaudeGatewayLogs(button) {
  await withButtonBusy(button, "Loading...", async () => {
    const payload = await api("/api/claude-gateway/logs?lines=100");
    const output = $("#claude-gateway-logs-output");
    output.classList.remove("hidden");
    output.textContent = payload.content || "";
    output.scrollIntoView({ behavior: "smooth", block: "start" });
  }, {
    successMessage: "Loaded Claude gateway logs.",
    successKind: "info",
  });
}

async function saveDefaults(event) {
  event.preventDefault();
  const submitButton = event.submitter || $("#defaults-form button[type='submit']");
  const payload = collectDefaultsPayload();

  await withButtonBusy(submitButton, "Saving...", async () => {
    await api("/api/defaults/save", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    await refreshState();
  }, {
    successMessage: "Global defaults updated.",
  });
}

async function performModeToggle(button) {
  const mode = state.data?.mode || {};
  const effectiveMode = mode.active_mode || mode.configured_mode || "";
  const nextMode = effectiveMode === "single-client" ? "multi" : "single";
  await withButtonBusy(button, "Switching...", async () => {
    await api("/api/mode", {
      method: "POST",
      body: JSON.stringify({ mode: nextMode }),
    });
    await refreshState();
  }, {
    successMessage: nextMode === "multi" ? "Client mode set to Multi Client." : "Client mode set to Single Client.",
  });
}

function findModel(alias) {
  return (state.data?.models || []).find((model) => model.alias === alias);
}

async function onModelTableClick(event) {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const row = button.closest("tr");
  const alias = row?.dataset.alias;
  if (!alias) return;

  if (button.dataset.action === "switch") {
    await withButtonBusy(button, "Serving...", async () => {
      await api("/api/switch", { method: "POST", body: JSON.stringify({ target: alias }) });
      await refreshState();
    }, {
      successMessage: `Serving ${alias}.`,
    });
    return;
  }

  if (button.dataset.action === "edit") {
    const model = findModel(alias);
    if (model) {
      pulseButton(button, "Opening...");
      fillModelForm(model);
      focusModelForm();
      showToast(`${alias} loaded into the editor.`, "info", { timeout: 2200 });
    }
    return;
  }

  if (button.dataset.action === "remove") {
    if (!window.confirm(`Remove ${alias} from the registry?`)) return;
    await withButtonBusy(button, "Removing...", async () => {
      await api("/api/models/delete", { method: "POST", body: JSON.stringify({ alias }) });
      await refreshState();
      await scanModels();
    }, {
      successMessage: `Removed ${alias} from the registry.`,
    });
  }
}

async function onDiscoveryTableClick(event) {
  const button = event.target.closest("button[data-action='import']");
  if (!button) return;

  const row = button.closest("tr");
  if (!row) return;
  const imported = row.querySelector(".status-cell")?.textContent === "already in registry";
  const alias = row.dataset.alias || "";

  pulseButton(button, imported ? "Opening..." : "Staging...");
  if (imported) {
    const model = findModel(alias);
    if (model) {
      fillModelForm(model);
    } else {
      fillModelForm({
        alias,
        path: row.dataset.path || "",
        mmproj: row.dataset.mmproj || "",
        extra_args: "",
        context: "",
        ngl: "",
        batch: "",
        threads: "",
        parallel: "",
        device: "",
        notes: "",
      });
      showToast(`${alias} is marked as imported, but no matching registry entry is loaded.`, "error");
    }
  } else {
    fillModelForm({
      alias,
      path: row.dataset.path || "",
      mmproj: row.dataset.mmproj || "",
      extra_args: "",
      context: "",
      ngl: "",
      batch: "",
      threads: "",
      parallel: "",
      device: "",
      notes: "",
    });
  }
  focusModelForm();
  showToast(`${alias || "Model"} loaded into the editor.`, "info", { timeout: 2200 });
}

async function onDownloadsTableClick(event) {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const row = button.closest("tr");
  const jobId = row?.dataset.jobId;
  if (!jobId) return;

  const action = button.dataset.action;
  if (action === "remove-queued") {
    const confirmed = window.confirm("Remove this queued download job? Running downloads and files will be left alone.");
    if (!confirmed) return;
  }
  const endpoint = action === "remove-queued"
    ? "/api/downloads/remove-queued"
    : action === "prioritize-queued"
      ? "/api/downloads/prioritize-queued"
      : action === "deprioritize-queued"
        ? "/api/downloads/deprioritize-queued"
      : `/api/downloads/${action}`;
  const busyLabel = action === "cancel"
    ? "Cancelling..."
    : action === "resume"
      ? "Resuming..."
      : action === "remove-queued"
        ? "Removing..."
        : action === "prioritize-queued"
          ? "Prioritizing..."
          : action === "deprioritize-queued"
            ? "Moving..."
            : "Retrying...";
  await withButtonBusy(button, busyLabel, async () => {
    const payload = await api(endpoint, {
      method: "POST",
      body: JSON.stringify({ id: jobId }),
    });
    await refreshState();
    return payload;
  }, {
    successMessage: action === "cancel"
      ? "Download cancellation requested."
      : action === "resume"
        ? "Download resume queued."
        : action === "remove-queued"
          ? "Queued download removed."
          : action === "prioritize-queued"
            ? "Queued download moved to run next."
            : action === "deprioritize-queued"
              ? "Queued download moved later."
              : "Download retry queued.",
    successKind: action === "cancel" ? "info" : "success",
  });
}

async function performRemoteSearch(button) {
  saveRemotePreferences();
  const query = $("#remote-query")?.value.trim() || "";
  const limit = Math.max(1, Math.round(Number($("#remote-limit")?.value || 30)));
  await withButtonBusy(button, "Searching...", async () => {
    const payload = await api("/api/remote/search", {
      method: "POST",
      body: JSON.stringify({ query, limit }),
    });
    state.data.remote_models = payload.remote_models || {};
    renderRemoteModels(state.data.remote_models);
    return payload;
  }, {
    successMessage: query ? `Remote cache refreshed for "${query}".` : "Remote cache loaded.",
    successKind: "success",
  });
}

async function onRemoteTableClick(event) {
  const button = event.target.closest("button[data-action='download-remote']");
  if (!button) return;
  const row = button.closest("tr");
  const repoId = row?.dataset.repoId || "";
  const artifactName = row?.dataset.artifactName || "";
  const destinationRoot = $("#remote-destination-root")?.value.trim() || state.data?.discovery_root || "";
  if (!destinationRoot) {
    showToast("Destination root is required for downloads.", "error");
    return;
  }
  await withButtonBusy(button, "Queueing...", async () => {
    const payload = await api("/api/downloads/start", {
      method: "POST",
      body: JSON.stringify({
        repo_id: repoId,
        artifact_name: artifactName,
        destination_root: destinationRoot,
      }),
    });
    await refreshState();
    return payload;
  }, {
    successMessage: `Queued ${artifactName || "remote download"}.`,
    successKind: "success",
  });
}

async function cleanupDownloads(button) {
  let removedCount = 0;
  await withButtonBusy(button, "Cleaning...", async () => {
    saveCleanupRetentionPreference();
    const retentionDays = Math.max(0, Number($("#cleanup-retention-days")?.value || 7));
    const maxAgeSeconds = Math.round(retentionDays * 24 * 60 * 60);
    const payload = await api("/api/downloads/cleanup", {
      method: "POST",
      body: JSON.stringify({ max_age_seconds: maxAgeSeconds }),
    });
    removedCount = (payload.removed || []).length;
    await refreshState();
    return payload;
  }, {
    successMessage: `${removedCount} old partial ${removedCount === 1 ? "file" : "files"} cleaned.`,
    successKind: "info",
  });
}

async function recoverDownloads(button) {
  let recoveredCount = 0;
  await withButtonBusy(button, "Recovering...", async () => {
    const payload = await api("/api/downloads/recover", {
      method: "POST",
      body: JSON.stringify({}),
    });
    recoveredCount = (payload.recovered || []).length;
    await refreshState();
    return payload;
  }, {
    successMessage: `${recoveredCount} stale download ${recoveredCount === 1 ? "job" : "jobs"} recovered.`,
    successKind: "info",
  });
}

async function cleanupDuplicateDownloads(button) {
  const confirmed = window.confirm(
    "Remove redundant completed job records that point at the same artifact path? Model files will be kept.",
  );
  if (!confirmed) return;

  let removedCount = 0;
  await withButtonBusy(button, "Cleaning...", async () => {
    const payload = await api("/api/downloads/cleanup-duplicates", {
      method: "POST",
      body: JSON.stringify({}),
    });
    removedCount = (payload.removed || []).length;
    await refreshState();
    return payload;
  }, {
    successMessage: `${removedCount} duplicate completed job ${removedCount === 1 ? "record" : "records"} cleaned. Model files kept.`,
    successKind: "info",
  });
}

async function deleteOrphanedArtifacts(button) {
  const storage = state.data?.download_storage || {};
  const count = Number(storage.orphaned_artifact_count || 0);
  const bytes = formatBytes(storage.orphaned_artifact_bytes || 0);
  const confirmed = window.confirm(
    `Delete ${count} orphaned GGUF ${count === 1 ? "file" : "files"} (${bytes}) under known download roots? Registry and completed-job artifacts will be kept.`,
  );
  if (!confirmed) return;

  let removedCount = 0;
  await withButtonBusy(button, "Deleting...", async () => {
    const paths = (storage.orphaned_artifacts || []).map((item) => item.path).filter(Boolean);
    const payload = await api("/api/downloads/delete-orphans", {
      method: "POST",
      body: JSON.stringify({ paths }),
    });
    removedCount = (payload.removed || []).length;
    await refreshState();
    return payload;
  }, {
    successMessage: `${removedCount} orphaned artifact ${removedCount === 1 ? "file" : "files"} deleted.`,
    successKind: "info",
  });
}

async function setDownloadQueuePaused(button, paused) {
  const endpoint = paused ? "/api/downloads/pause-queue" : "/api/downloads/resume-queue";
  await withButtonBusy(button, paused ? "Pausing..." : "Resuming...", async () => {
    const payload = await api(endpoint, {
      method: "POST",
      body: JSON.stringify({}),
    });
    await refreshState();
    return payload;
  }, {
    successMessage: paused ? "Download queue paused. Running jobs continue." : "Download queue resumed.",
    successKind: "info",
  });
}

async function saveDownloadPolicy(button) {
  let maxActive = Math.max(1, Number($("#download-slot-limit")?.value || 2));
  maxActive = Math.round(maxActive);
  await withButtonBusy(button, "Saving...", async () => {
    const payload = await api("/api/downloads/policy", {
      method: "POST",
      body: JSON.stringify({ max_active_downloads: maxActive }),
    });
    await refreshState();
    return payload;
  }, {
    successMessage: `Download running slots set to ${maxActive}.`,
    successKind: "success",
  });
}

async function clearDownloadQueue(button) {
  const queuedCount = Number(state.data?.download_policy?.queued_downloads || 0);
  const confirmed = window.confirm(
    `Remove ${queuedCount} queued download ${queuedCount === 1 ? "job" : "jobs"}? Running downloads and files will be left alone.`,
  );
  if (!confirmed) return;

  let removedCount = 0;
  await withButtonBusy(button, "Clearing...", async () => {
    const payload = await api("/api/downloads/clear-queued", {
      method: "POST",
      body: JSON.stringify({}),
    });
    removedCount = (payload.removed || []).length;
    await refreshState();
    return payload;
  }, {
    successMessage: `${removedCount} queued download ${removedCount === 1 ? "job" : "jobs"} removed.`,
    successKind: "info",
  });
}

function bindEvents() {
  $("#remote-search")?.addEventListener("click", (event) => performRemoteSearch(event.currentTarget).catch(showError));
  $("#remote-hide-gated")?.addEventListener("change", () => {
    saveRemotePreferences();
    renderRemoteModels(state.data?.remote_models || {});
  });
  $("#remote-models-table")?.addEventListener("click", (event) => onRemoteTableClick(event).catch(showError));
  $("#downloads-table")?.addEventListener("click", (event) => onDownloadsTableClick(event).catch(showError));
  $("#cleanup-downloads")?.addEventListener("click", (event) => cleanupDownloads(event.currentTarget).catch(showError));
  $("#recover-downloads")?.addEventListener("click", (event) => recoverDownloads(event.currentTarget).catch(showError));
  $("#cleanup-duplicate-downloads")?.addEventListener("click", (event) => cleanupDuplicateDownloads(event.currentTarget).catch(showError));
  $("#delete-orphaned-artifacts")?.addEventListener("click", (event) => deleteOrphanedArtifacts(event.currentTarget).catch(showError));
  $("#pause-download-queue")?.addEventListener("click", (event) => setDownloadQueuePaused(event.currentTarget, true).catch(showError));
  $("#resume-download-queue")?.addEventListener("click", (event) => setDownloadQueuePaused(event.currentTarget, false).catch(showError));
  $("#save-download-policy")?.addEventListener("click", (event) => saveDownloadPolicy(event.currentTarget).catch(showError));
  $("#clear-download-queue")?.addEventListener("click", (event) => clearDownloadQueue(event.currentTarget).catch(showError));
  $("#refresh-all").addEventListener("click", (event) => withButtonBusy(event.currentTarget, "Refreshing...", async () => {
    await refreshState();
    await scanModels();
  }, {
    successMessage: "Dashboard state refreshed.",
  }).catch(showError));
  $("#toggle-mode").addEventListener("click", (event) => performModeToggle(event.currentTarget).catch(showError));
  $("#toggle-activity-panel")?.addEventListener("click", () => {
    const visible = !activityPanelVisible();
    setActivityPanelVisible(visible);
    renderActivityPanelVisibility(visible);
  });
  $("#restart-server").addEventListener("click", (event) => withButtonBusy(event.currentTarget, "Restarting...", async () => {
    await api("/api/restart", { method: "POST", body: JSON.stringify({}) });
    await refreshState();
  }, {
    successMessage: "Server restarted.",
  }).catch(showError));
  $("#stop-server").addEventListener("click", async () => {
    if (!window.confirm("Stop llama-server now?")) return;
    await withButtonBusy($("#stop-server"), "Stopping...", async () => {
      await api("/api/stop", { method: "POST", body: JSON.stringify({}) });
      await refreshState();
    }, {
      successMessage: "Server stopped.",
      successKind: "info",
    });
  });
  $("#load-logs").addEventListener("click", (event) => withButtonBusy(event.currentTarget, "Loading...", async () => {
    await refreshLogs();
  }, {
    successMessage: "Loaded recent server logs.",
    successKind: "info",
  }).catch(showError));
  $("#dashboard-service-install").addEventListener("click", (event) => performDashboardServiceAction("install", event.currentTarget, {
    pendingLabel: "Installing...",
    successMessage: "Dashboard service installed.",
  }).catch(showError));
  $("#dashboard-service-enable").addEventListener("click", (event) => performDashboardServiceAction("enable", event.currentTarget, {
    pendingLabel: "Enabling...",
    successMessage: "Dashboard service will start at login.",
  }).catch(showError));
  $("#dashboard-service-restart").addEventListener("click", (event) => performDashboardServiceAction("restart", event.currentTarget, {
    pendingLabel: "Restarting...",
    successMessage: "Dashboard service restarted.",
    successKind: "info",
  }).catch(showError));
  $("#dashboard-service-stop").addEventListener("click", (event) => {
    const managed = Boolean(state.data?.meta?.dashboard_service_managed);
    const confirmMessage = managed
      ? "This page is currently being served by the managed dashboard service. Stopping it will disconnect this page. Continue?"
      : "Stop the optional dashboard background service?";
    return performDashboardServiceAction("stop", event.currentTarget, {
      pendingLabel: "Stopping...",
      successMessage: "Dashboard service stopped.",
      successKind: "info",
      confirmMessage,
      expectDisconnect: true,
      disconnectMessage: "Dashboard service stop requested. This page may disconnect if it was being served by that service.",
    }).catch(showError);
  });
  $("#dashboard-service-disable").addEventListener("click", (event) => performDashboardServiceAction("disable", event.currentTarget, {
    pendingLabel: "Disabling...",
    successMessage: "Dashboard service will no longer start at login.",
    successKind: "info",
  }).catch(showError));
  $("#dashboard-service-remove").addEventListener("click", (event) => {
    const managed = Boolean(state.data?.meta?.dashboard_service_managed);
    const confirmMessage = managed
      ? "This removes the installed dashboard service unit. If this page is being served by that service, it may disconnect. Continue?"
      : "Remove the installed dashboard service unit?";
    return performDashboardServiceAction("uninstall", event.currentTarget, {
      pendingLabel: "Removing...",
      successMessage: "Dashboard service removed.",
      successKind: "info",
      confirmMessage,
      expectDisconnect: true,
      disconnectMessage: "Dashboard service removal requested. This page may disconnect if it was being served by that service.",
    }).catch(showError);
  });
  $("#dashboard-service-logs").addEventListener("click", (event) => loadDashboardServiceLogs(event.currentTarget).catch(showError));
  $("#sync-opencode-balanced").addEventListener("click", (event) => performIntegrationSync("/api/opencode/sync", event.currentTarget, "Syncing...", "opencode synced with the balanced preset.", { preset: "balanced" }).catch(showError));
  $("#sync-opencode-long-run").addEventListener("click", (event) => performIntegrationSync("/api/opencode/sync", event.currentTarget, "Syncing...", "opencode synced with the long-run preset.", { preset: "long-run" }).catch(showError));
  $("#sync-openclaw").addEventListener("click", (event) => performIntegrationSync("/api/openclaw/sync", event.currentTarget, "Syncing...", "OpenClaw synced.").catch(showError));
  $("#sync-claude").addEventListener("click", (event) => performIntegrationSync("/api/claude/sync", event.currentTarget, "Syncing...", "Claude Code settings synced.").catch(showError));
  $("#sync-glyphos").addEventListener("click", (event) => performIntegrationSync("/api/glyphos/sync", event.currentTarget, "Syncing...", "GlyphOS config synced.").catch(showError));
  $("#sync-glyphos-combined").addEventListener("click", (event) => activateContextGlyphos(event.currentTarget).catch(showError));
  $("#claude-gateway-start").addEventListener("click", (event) => performClaudeGatewayAction("start", event.currentTarget, { pendingLabel: "Starting...", successMessage: "Claude gateway started." }).catch(showError));
  $("#claude-gateway-restart").addEventListener("click", (event) => performClaudeGatewayAction("restart", event.currentTarget, { pendingLabel: "Restarting...", successMessage: "Claude gateway restarted." }).catch(showError));
  $("#claude-gateway-stop").addEventListener("click", (event) => performClaudeGatewayAction("stop", event.currentTarget, { pendingLabel: "Stopping...", successMessage: "Claude gateway stopped." }).catch(showError));
  $("#claude-gateway-logs").addEventListener("click", (event) => loadClaudeGatewayLogs(event.currentTarget).catch(showError));
  $("#scan-models").addEventListener("click", (event) => withButtonBusy(event.currentTarget, "Scanning...", async () => {
    const items = await scanModels();
    showToast(items.length ? `Found ${items.length} model candidate${items.length === 1 ? "" : "s"}.` : "No model candidates found in this root.", items.length ? "success" : "info");
  }).catch(showError));
  $("#clear-model-form").addEventListener("click", clearModelForm);
  $("#model-form").addEventListener("submit", (event) => saveModel(event).catch(showError));
  $("#defaults-form").addEventListener("submit", (event) => saveDefaults(event).catch(showError));
  $("#models-table").addEventListener("click", (event) => onModelTableClick(event).catch(showError));
  $("#discovery-table").addEventListener("click", (event) => onDiscoveryTableClick(event).catch(showError));
}

function showError(error) {
  console.error(error);
  showToast(error.message || String(error), "error");
}

async function main() {
  loadCleanupRetentionPreference();
  loadRemotePreferences();
  renderActivityPanelVisibility();
  bindEvents();
  await refreshState();
  renderDiscovery(state.discovery);
}
main().catch(showError);
