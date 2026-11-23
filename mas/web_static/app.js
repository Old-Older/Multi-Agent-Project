"use strict";

const el = (id) => document.getElementById(id);
const storageKey = "mas.workspace.v1";
const stateLabels = {
  idle: "待启动", queued: "排队中", running: "运行中", waiting: "等待回复",
  completed: "已结束", failed: "运行失败",
};
const eventLabels = {
  chat: "消息", task_assign: "任务委派", task_result: "任务反馈",
  hitl_request: "向你提问", hitl_response: "人工回复", status: "状态更新",
  tool: "工具调用", tool_call: "工具调用", round: "任务轮次", final: "最终答复", error: "运行错误",
};
let examples = [];
let tasks = [""];
let activeTask = 0;
let runId = null;
let busy = false;
let timer;
let pollNumber = 0;
let questionId = null;
let renderedResults = "";
let sendingAnswer = false;
let configMenu = null;
let preferredInteraction = "auto";
let runInteraction = null;
let switchingMode = false;

const limitFields = {budget: "budget", research: "research", min_use: "min-use"};

function choice(group) {
  return el(group).querySelector("input:checked").value;
}

function selectChoice(group, value) {
  const input = [...el(group).querySelectorAll("input")].find((item) => item.value === value);
  if (input) input.checked = true;
}

// Used for drafts as well as POST options. The password is added only at dispatch.
function publicSettings() {
  if (!configMenu) return undefined;
  const options = {
    provider: el("provider").value, model: el("model-name").value.trim(),
    key_source: choice("key-source"), preset: choice("preset"), interaction: preferredInteraction,
  };
  if (options.preset === "custom") {
    for (const [key, id] of Object.entries(limitFields)) {
      options[key] = el(id).value === "" ? null : el(id).valueAsNumber;
    }
  }
  return options;
}

function updateSettingsSummary() {
  if (!configMenu) return;
  const provider = configMenu.providers[el("provider").value];
  const custom = choice("key-source") === "custom";
  const preset = choice("preset");
  let presetName = configMenu.presets[preset]?.name || "自定义";
  if (preset === "environment") {
    const defaults = configMenu.presets.environment;
    const match = [configMenu.presets.fast, configMenu.presets.full].find((item) =>
      Object.keys(limitFields).every((key) => item[key] === defaults[key]));
    presetName = "环境默认 · " + (match?.name || "自定义参数");
  }
  const keyStatus = custom ? (busy && runId ? "本次密钥" : el("api-key").value.trim() ? "本次密钥已填" : "待输入密钥")
    : provider.has_key ? "服务端密钥已配置" : "服务端密钥未配置";
  const lockHint = busy && runId ? "。本次运行结束后可更改配置。" : "";
  const interactionName = choice("interaction") === "auto" ? "自动回复" : "人工回复";
  el("config-summary").textContent = [provider.name, presetName, keyStatus, interactionName].join(" · ") + lockHint;
  el("custom-key-row").hidden = !custom || Boolean(busy && runId);
}

function applyPreset(values) {
  const preset = choice("preset");
  for (const [key, id] of Object.entries(limitFields)) {
    const field = el(id);
    const value = values?.[key] ?? configMenu.presets[preset]?.[key];
    if (value !== undefined) field.value = value;
    field.readOnly = preset !== "custom";
  }
  updateSettingsSummary();
}

function applyProvider(saved = {}) {
  const provider = configMenu.providers[el("provider").value];
  el("model-name").value = saved.model || provider.model;
  el("model-name").placeholder = provider.model;
  el("server-key-option").textContent = provider.has_key ? "本机 Key（已配置）" : "本机 Key（未配置）";
  selectChoice("key-source", saved.key_source || (provider.has_key ? "server" : "custom"));
  el("api-key").value = "";
  updateSettingsSummary();
}

function restoreSettings(saved = {}, activeRun = false) {
  if (!configMenu) return;
  saved ||= {};
  if (activeRun) {
    // Runs created before interaction was configurable used manual answers.
    runInteraction = saved.interaction === "auto" ? "auto" : "manual";
  } else {
    preferredInteraction = saved.interaction === "manual" ? "manual" : "auto";
  }
  selectChoice("interaction", activeRun ? runInteraction : preferredInteraction);
  const defaultProvider = Object.hasOwn(configMenu.providers, configMenu.provider) ? configMenu.provider : "hkgai";
  el("provider").value = Object.hasOwn(configMenu.providers, saved.provider) ? saved.provider : defaultProvider;
  selectChoice("preset", saved.preset === "custom" || Object.hasOwn(configMenu.presets, saved.preset)
    ? saved.preset : configMenu.preset);
  applyProvider(saved);
  applyPreset(choice("preset") === "custom" ? {...configMenu.presets.environment, ...saved} : saved);
}

async function loadSettings(saved) {
  const menu = await api("/api/config");
  el("provider").replaceChildren();
  for (const [id, provider] of Object.entries(menu.providers)) el("provider").add(new Option(provider.name, id));
  configMenu = menu;
  restoreSettings(saved);
  el("config-fields").disabled = busy;
}

function settingsError(id, message) {
  el(id).focus();
  throw new Error(message);
}

function runSettings() {
  const options = publicSettings();
  if (!configMenu.interaction) {
    if (options.interaction === "auto") {
      settingsError("start", "当前服务版本仅支持人工回复。请使用新版服务启动自动模式，或选择人工回复。");
    }
    delete options.interaction;
  }
  options.model ||= configMenu.providers[options.provider].model;
  if (options.key_source === "custom") {
    options.api_key = el("api-key").value.trim();
    if (!options.api_key) settingsError("api-key", "请输入本次运行的 API 密钥。");
  } else if (!configMenu.providers[options.provider].has_key) {
    settingsError("custom-key-choice", "该服务尚未配置密钥。请选择「输入本次 Key」并填写密钥。");
  }
  if (options.preset === "custom") {
    if (!Number.isFinite(options.budget) || options.budget < 0) settingsError("budget", "每轮时限应为大于或等于 0 的秒数。");
    if (!Number.isInteger(options.research) || options.research < 0) settingsError("research", "检索次数应为大于或等于 0 的整数。");
    if (!Number.isFinite(options.min_use) || options.min_use < 0 || options.min_use >= 1) settingsError("min-use", "最早交付比例应大于或等于 0 且小于 1。");
  }
  return options;
}

function node(tag, className, content) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (content !== undefined) item.textContent = content;
  return item;
}

function notice(id, message) {
  el(id).textContent = message || "";
  el(id).hidden = !message;
}

function save() {
  try {
    sessionStorage.setItem(storageKey, JSON.stringify({
      roles: el("roles").value, tasks, activeTask, example: el("example").value, runId, config: publicSettings(),
    }));
  } catch { /* The page also works with browser storage disabled. */ }
}

function loadDraft() {
  try {
    const draft = JSON.parse(sessionStorage.getItem(storageKey));
    if (typeof draft?.roles === "string" && Array.isArray(draft.tasks)
        && draft.tasks.length && draft.tasks.every((task) => typeof task === "string")) return draft;
  } catch { /* Start with the first available template. */ }
  return null;
}

async function api(path, payload) {
  const response = await fetch(path, payload === undefined ? {cache: "no-store"} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || data.detail || "服务请求失败（HTTP " + response.status + "）");
    error.status = response.status;
    throw error;
  }
  return data;
}

function loadEditor(id, text) {
  const editor = el(id);
  editor.value = text;
  editor.setSelectionRange(0, 0);
  editor.scrollTop = 0;
}

function renderTasks() {
  const buttons = tasks.map((_, index) => {
    const button = node("button", "round", "第 " + (index + 1) + " 轮");
    button.type = "button";
    button.setAttribute("aria-pressed", String(index === activeTask));
    button.addEventListener("click", () => {
      activeTask = index;
      renderTasks();
      el("rounds").children[index].focus();
      save();
    });
    return button;
  });
  el("rounds").replaceChildren(...buttons);
  loadEditor("task", tasks[activeTask]);
  el("task-count").textContent = "共 " + tasks.length + " 轮 · 按顺序执行";
  el("remove-task").hidden = tasks.length < 2;
}

function setBusy(value) {
  busy = value;
  if (!busy) runInteraction = null;
  selectChoice("interaction", runInteraction ?? preferredInteraction);
  for (const id of ["start", "example", "import-roles", "import-task", "add-task", "remove-task"]) {
    el(id).disabled = value;
  }
  el("roles").readOnly = el("task").readOnly = value;
  el("config-fields").disabled = value || !configMenu;
  el("switch-mode-row").hidden = !runId || runInteraction !== "manual" || !busy;
  el("switch-mode").disabled = switchingMode || sendingAnswer;
  updateSettingsSummary();
  el("start-label").textContent = value ? "运行中" : "启动运行";
}

function useExample(id) {
  const example = examples.find((item) => item.id === id);
  el("example").value = example ? id : "";
  loadEditor("roles", example?.roles || "");
  tasks = example?.tasks?.length ? [...example.tasks] : [""];
  activeTask = 0;
  renderTasks();
  notice("setup-error", "");
  save();
}

function markEdited() {
  el("example").value = "";
  notice("setup-error", "");
  save();
}

function showView(results) {
  for (const [id, active] of [["events", !results], ["results", results]]) {
    el(id + "-view").hidden = !active;
    el(id + "-tab").classList.toggle("active", active);
    el(id + "-tab").setAttribute("aria-pressed", String(active));
  }
}

function renderEvents(events) {
  const list = el("events");
  const nearEnd = list.scrollHeight - list.clientHeight - list.scrollTop < 60;
  // Run events are append-only. Preserve scroll position and text selection while polling.
  if (events.length < list.children.length) list.replaceChildren();
  const fragment = document.createDocumentFragment();
  for (const event of events.slice(list.children.length)) {
    const item = node("li", "event");
    const heading = node("div", "event-head");
    const label = event.automatic ? "自动回复" : eventLabels[event.kind] || event.kind || "进度";
    const speaker = event.automatic && event.sender === "human" ? null : event.sender;
    heading.append(node("strong", "", speaker ? speaker + " · " + label : label));
    const stamp = event.ts ?? event.time;
    if (stamp) {
      const date = new Date(typeof stamp === "number" ? stamp * 1000 : stamp);
      if (!Number.isNaN(date.valueOf())) {
        const time = node("time", "", date.toLocaleTimeString("zh-CN", {hour12: false}));
        time.dateTime = date.toISOString();
        heading.append(time);
      }
    }
    item.append(heading, node("p", "message", event.text));
    fragment.append(item);
  }
  list.append(fragment);
  list.hidden = !events.length;
  el("events-empty").hidden = Boolean(events.length);
  el("event-count").textContent = events.length;
  if (nearEnd && !el("events-view").hidden) list.scrollTop = list.scrollHeight;
}

function fileList(files) {
  const list = node("ul", "file-list");
  for (const file of files) {
    if (typeof file.url !== "string") continue;
    const target = new URL(file.url, location.href);
    if (target.origin !== location.origin || !["http:", "https:"].includes(target.protocol)) continue;
    const link = node("a", "", file.name);
    link.href = target.href;
    link.download = file.name;
    const row = node("li");
    row.append(link);
    list.append(row);
  }
  return list;
}

function renderResults(results, files) {
  const signature = JSON.stringify([results, files]);
  if (signature === renderedResults) return;
  renderedResults = signature;
  const listed = new Set();
  el("results").replaceChildren(...results.map((result, index) => {
    const card = node("article", "result");
    card.append(node("h3", "", result.title || ("第 " + (index + 1) + " 轮结果")));
    if (result.success === false) card.append(node("p", "result-failed", "本轮未完成"));
    if (result.text) card.append(node("p", "result-text", result.text));
    if (result.files?.length) {
      card.append(fileList(result.files));
      for (const file of result.files) listed.add(file.url);
    }
    return card;
  }));
  const extra = files.filter((file) => !listed.has(file.url));
  el("extra-files").replaceChildren();
  if (extra.length) {
    const block = node("section", "files-block");
    block.append(node("h3", "", "交付文件"), fileList(extra));
    el("extra-files").append(block);
  }
  el("result-count").textContent = results.length;
  el("results-empty").hidden = Boolean(results.length || files.length);
}

function renderQuestion(question) {
  el("question-form").hidden = !question;
  if (questionId === (question?.id ?? null)) return;
  questionId = question?.id ?? null;
  el("answer").value = "";
  el("answer-error").textContent = "";
  if (!question) return;
  el("question-heading").textContent = (question.sender || "团队") + " 需要你的回复";
  el("question-text").textContent = question.text;
  el("question-options").replaceChildren(...(question.options || []).map((option) => {
    const button = node("button", "", option);
    button.type = "button";
    button.addEventListener("click", () => { el("answer").value = option; el("answer").focus(); });
    return button;
  }));
}

function renderRun(run) {
  const status = run.status;
  const active = ["queued", "running", "waiting"].includes(status);
  if (active && ["auto", "manual"].includes(run.interaction)) runInteraction = run.interaction;
  setBusy(active);
  if (runInteraction !== "manual") notice("switch-error", "");
  el("status").dataset.state = status;
  el("status").textContent = stateLabels[status] || status;
  el("empty-title").textContent = active ? "等待团队消息" : "暂无协作记录";
  el("empty-note").textContent = active ? "收到第一条事件后将自动显示。" : "本次运行没有产生协作事件。";
  notice("run-error", run.error);
  renderEvents(run.events || []);
  renderResults(run.results || [], run.files || []);
  renderQuestion(runInteraction === "auto" ? null : run.question);
}

async function refresh(id) {
  const poll = ++pollNumber;
  clearTimeout(timer);
  try {
    const run = await api("/api/runs/" + encodeURIComponent(id));
    if (runId !== id || poll !== pollNumber) return;
    renderRun(run);
    if (busy) timer = setTimeout(() => refresh(id), 1000);
  } catch (error) {
    if (runId !== id || poll !== pollNumber) return;
    if (error.status === 404) {
      renderRun({status: "failed", error: "找不到上次运行。可以用当前配置重新启动。"});
      runId = null;
      save();
    } else {
      notice("run-error", "暂时无法读取运行进度，将自动重试。" + error.message);
      timer = setTimeout(() => refresh(id), 2500);
    }
  }
}

async function resumeActive() {
  const {id} = await api("/api/active");
  if (!id) return false;
  const inputs = await api("/api/runs/" + encodeURIComponent(id) + "/inputs");
  const example = examples.find((item) => item.roles === inputs.roles
    && item.tasks.length === inputs.tasks.length
    && item.tasks.every((task, index) => task === inputs.tasks[index]));
  el("example").value = example?.id || "";
  loadEditor("roles", inputs.roles);
  tasks = inputs.tasks;
  activeTask = runId === id ? Math.min(activeTask, tasks.length - 1) : 0;
  runId = id;
  restoreSettings(inputs.config, true);
  renderTasks();
  save();
  el("events").replaceChildren();
  renderRun({status: "running"});
  await refresh(id);
  return true;
}

async function start() {
  if (busy) return;
  if (!el("roles").value.trim()) {
    notice("setup-error", "请填写角色定义，或选择场景模板。");
    el("roles").focus();
    return;
  }
  const emptyRound = tasks.findIndex((task) => !task.trim());
  if (emptyRound !== -1) {
    activeTask = emptyRound;
    renderTasks();
    notice("setup-error", "请先填写第 " + (emptyRound + 1) + " 轮任务。");
    el("task").focus();
    return;
  }
  notice("setup-error", "");
  try {
    if (!configMenu) {
      await loadSettings();
      notice("setup-error", "已重新读取配置，请核对模型与运行参数后启动。");
      return;
    }
    const config = runSettings();
    setBusy(true);
    const result = await api("/api/runs", {roles: el("roles").value, tasks, config});
    el("api-key").value = "";
    runId = result.id;
    runInteraction = config.interaction || "manual";
    save();
    showView(false);
    el("events").replaceChildren();
    renderRun({status: "queued"});
    if (matchMedia("(max-width: 820px)").matches) el("monitor-title").scrollIntoView({block: "start"});
    await refresh(runId);
  } catch (error) {
    if (error.status === 409) {
      try { if (await resumeActive()) return; }
      catch (resumeError) { notice("run-error", resumeError.message); }
    }
    setBusy(false);
    notice("setup-error", error.message);
  }
}

async function importFiles(event, roles) {
  const input = event.target;
  const files = [...input.files].sort((a, b) => a.name.localeCompare(b.name, undefined, {numeric: true}));
  input.value = "";
  if (!files.length || busy) return;
  try {
    const texts = await Promise.all(files.map((file) => file.text()));
    if (busy) return;
    if (roles) loadEditor("roles", texts[0]);
    else {
      if (texts.length === 1) tasks[activeTask] = texts[0];
      else { tasks = texts; activeTask = 0; }
      renderTasks();
    }
    markEdited();
  } catch (error) { notice("setup-error", "文件读取失败。" + error.message); }
}

async function answer(event) {
  event.preventDefault();
  if (!questionId || sendingAnswer || switchingMode) return;
  const reply = el("answer").value.trim();
  if (!reply) { el("answer-error").textContent = "请先输入回复。"; el("answer").focus(); return; }
  sendingAnswer = true;
  el("switch-mode").disabled = true;
  el("send-answer").disabled = true;
  try {
    await api("/api/runs/" + encodeURIComponent(runId) + "/answer", {id: questionId, answer: reply});
    await refresh(runId);
  } catch (error) { el("answer-error").textContent = error.message; }
  finally {
    sendingAnswer = false;
    el("switch-mode").disabled = switchingMode;
    el("send-answer").disabled = false;
  }
}

async function switchToAuto() {
  if (!busy || !runId || runInteraction !== "manual" || switchingMode || sendingAnswer) return;
  const id = runId;
  const path = "/api/runs/" + encodeURIComponent(id);
  switchingMode = true;
  el("switch-mode").disabled = el("send-answer").disabled = true;
  notice("switch-error", "");
  try {
    await api(path + "/auto", {});
    if (runId !== id || !busy) return;
    runInteraction = "auto";
    setBusy(busy);
    renderQuestion(null);
    const inputs = await api(path + "/inputs");
    if (runId === id && busy) restoreSettings(inputs.config, true);
  } catch (error) {
    const message = error.status === 404 && !configMenu?.interaction
      ? "当前服务版本尚未支持运行中切换，仍可在此人工回复。" : error.message;
    notice("switch-error", message);
  } finally {
    switchingMode = false;
    el("switch-mode").disabled = el("send-answer").disabled = false;
    if (runId === id) await refresh(id);
  }
}

async function init() {
  const draft = loadDraft();
  let loadError;
  setBusy(true);
  try {
    const data = await api("/api/examples");
    examples = data.examples;
    for (const example of examples) el("example").add(new Option(example.name, example.id));
  } catch (error) { loadError = "场景模板加载失败，可手动粘贴或导入文件。" + error.message; }
  if (draft) {
    loadEditor("roles", draft.roles);
    el("example").value = draft.example || "";
    tasks = draft.tasks;
    activeTask = Number.isInteger(draft.activeTask) && tasks[draft.activeTask] !== undefined ? draft.activeTask : 0;
    runId = draft.runId || null;
    renderTasks();
  } else useExample(examples[0]?.id);
  try { await loadSettings(draft?.config); }
  catch (error) {
    el("config-summary").textContent = "配置加载失败";
    loadError = [loadError, "未能读取模型配置，点击启动运行可重试。" + error.message].filter(Boolean).join(" ");
  }
  if (loadError) notice("setup-error", loadError);
  try { if (await resumeActive()) return; }
  catch (error) { notice("run-error", "未能恢复当前运行。" + error.message); }
  if (runId) await refresh(runId);
  else setBusy(false);
}

el("provider").addEventListener("change", () => { applyProvider(); save(); });
el("key-source").addEventListener("change", () => {
  el("api-key").value = ""; updateSettingsSummary(); save();
});
el("api-key").addEventListener("input", updateSettingsSummary);
el("preset").addEventListener("change", () => { applyPreset(); save(); });
el("interaction").addEventListener("change", () => {
  preferredInteraction = choice("interaction"); updateSettingsSummary(); save();
});
for (const id of ["model-name", ...Object.values(limitFields)]) el(id).addEventListener("input", save);
el("example").addEventListener("change", () => useExample(el("example").value));
el("roles").addEventListener("input", markEdited);
el("task").addEventListener("input", () => { tasks[activeTask] = el("task").value; markEdited(); });
el("import-roles").addEventListener("click", () => el("roles-file").click());
el("import-task").addEventListener("click", () => el("task-file").click());
el("roles-file").addEventListener("change", (event) => importFiles(event, true));
el("task-file").addEventListener("change", (event) => importFiles(event, false));
el("add-task").addEventListener("click", () => {
  tasks.push(""); activeTask = tasks.length - 1; renderTasks(); markEdited(); el("task").focus();
});
el("remove-task").addEventListener("click", () => {
  if (tasks.length < 2) return;
  tasks.splice(activeTask, 1); activeTask = Math.min(activeTask, tasks.length - 1);
  renderTasks(); markEdited();
});
el("start").addEventListener("click", start);
el("question-form").addEventListener("submit", answer);
el("switch-mode").addEventListener("click", switchToAuto);
el("events-tab").addEventListener("click", () => showView(false));
el("results-tab").addEventListener("click", () => showView(true));
init();
