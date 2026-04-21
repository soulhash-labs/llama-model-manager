const state = {
  data: null,
  discovery: [],
  discoveryScanned: false,
  toastId: 0,
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

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  const payload = await response.json().catch(() => ({ ok: false, error: "Invalid JSON response" }));
  if (!response.ok) {
    throw new Error(payload.error || "Request failed");
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
  if (data.demo) {
    messages.push("Demo mode is active. Registry and runtime values are sample data, not your local machine.");
  }
  if (!data.registry_exists) {
    messages.push(`No registry file exists yet at ${data.registry_file}. Save a model to create it, or scan a root and stage one from discovery.`);
  }
  if (!data.defaults_exists) {
    messages.push(`Defaults file is missing at ${data.defaults_file}. The dashboard is using built-in fallbacks until you save defaults.`);
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

  setText("#status-subtitle", `${health}. ${activeMode}. ${activeLanes}. ${registryLabel(registryCount)} in registry.`);
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

function renderStatus(data) {
  const current = data.current || {};
  const doctor = data.doctor || {};
  const mode = data.mode || {};
  const nextMode = mode.configured_mode === "single-client" ? "Switch To Multi Client" : "Switch To Single Client";

  renderNotice(data);
  renderHero(data);

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
  setText("#opencode-model", data.opencode_model || "-");
  setText("#toggle-mode", nextMode);
  setTitle(
    "#toggle-mode",
    mode.configured_mode === "single-client"
      ? "Restart the server in multi-client mode so multiple requests can run at once."
      : "Restart the server in single-client mode so one request runs at a time.",
  );
}

function renderModels(models) {
  const tbody = $("#models-table tbody");
  const template = $("#model-row-template");
  const currentAlias = state.data?.current?.alias || "";
  tbody.innerHTML = "";
  setText("#registry-count", String(models.length));

  if (!models.length) {
    const registryPath = state.data?.registry_file || "~/.config/llama-server/models.tsv";
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
    const root = $("#discovery-root")?.value.trim() || state.data?.discovery_root || "~/models";
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
    const root = $("#discovery-root")?.value.trim() || state.data?.discovery_root || "~/models";
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
  $("#default-log").value = defaults.LLAMA_SERVER_LOG || "";
  $("#default-extra").value = defaults.LLAMA_SERVER_EXTRA_ARGS || "";
}

async function refreshState() {
  state.data = await api("/api/state");
  $("#discovery-root").value = state.data.discovery_root || "";
  renderStatus(state.data);
  renderModels(state.data.models || []);
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

async function saveDefaults(event) {
  event.preventDefault();
  const submitButton = event.submitter || $("#defaults-form button[type='submit']");
  const payload = {
    LLAMA_SERVER_HOST: $("#default-host").value.trim(),
    LLAMA_SERVER_PORT: $("#default-port").value.trim(),
    LLAMA_SERVER_DEVICE: $("#default-device").value.trim(),
    LLAMA_SERVER_CONTEXT: $("#default-context").value.trim(),
    LLAMA_SERVER_NGL: $("#default-ngl").value.trim(),
    LLAMA_SERVER_BATCH: $("#default-batch").value.trim(),
    LLAMA_SERVER_THREADS: $("#default-threads").value.trim(),
    LLAMA_SERVER_PARALLEL: $("#default-parallel").value.trim(),
    LLAMA_SERVER_LOG: $("#default-log").value.trim(),
    LLAMA_SERVER_EXTRA_ARGS: $("#default-extra").value.trim(),
  };

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
  const nextMode = state.data?.mode?.configured_mode === "single-client" ? "multi" : "single";
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

function bindEvents() {
  $("#refresh-all").addEventListener("click", (event) => withButtonBusy(event.currentTarget, "Refreshing...", async () => {
    await refreshState();
    await scanModels();
  }, {
    successMessage: "Dashboard state refreshed.",
  }).catch(showError));
  $("#toggle-mode").addEventListener("click", (event) => performModeToggle(event.currentTarget).catch(showError));
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
  bindEvents();
  await refreshState();
  renderDiscovery(state.discovery);
}
main().catch(showError);
