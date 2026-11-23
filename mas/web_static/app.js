"use strict";

const el = (id) => document.getElementById(id);
const storageKey = "mas.workspace.v1";
const languageKey = "mas.workspace.language";
let language = "zh";
try { if (localStorage.getItem(languageKey) === "en") language = "en"; } catch { /* Storage is optional. */ }
const t = (zh, en) => language === "en" ? en : zh;
const stateLabels = {
  idle: ["待启动", "Ready"], queued: ["排队中", "Queued"], running: ["运行中", "Running"],
  waiting: ["等待回复", "Waiting for a reply"], completed: ["已结束", "Completed"], failed: ["运行失败", "Failed"],
};
const eventLabels = {
  chat: ["消息", "Message"], task_assign: ["任务委派", "Assignment"], task_result: ["任务反馈", "Task result"],
  hitl_request: ["向你提问", "Question"], hitl_response: ["人工回复", "Manual reply"], status: ["状态更新", "Status update"],
  tool: ["工具调用", "Tool call"], tool_call: ["工具调用", "Tool call"], round: ["任务轮次", "Round"],
  final: ["最终答复", "Final response"], error: ["运行错误", "Run error"],
};
const taskStates = {
  assigned: ["已分配", "Assigned"], running: ["执行中", "Running"], waiting_human: ["等待人工回复", "Waiting for a reply"],
  done: ["已完成", "Done"], failed: ["失败", "Failed"], declined: ["已拒绝", "Declined"], cancelled: ["已取消", "Cancelled"],
};
const exampleNames = {
  "scenario_1_software_engineering 2": "Software development team",
  "scenario_2_newsroom 2": "Newsroom",
  "scenario_3_securities_fund 2": "Investment fund team",
};
const presetNames = {fast: "Fast", full: "Full", environment: "Environment defaults", custom: "Custom"};
const notices = new Map();
let lastRun = null;
let configLoadFailed = false;
const staticTranslations = [];
for (const attribute of ["textContent", "placeholder", "title", "aria-label"]) {
  const source = attribute === "textContent" ? "data-en" : "data-en-" + attribute;
  for (const element of document.querySelectorAll("[" + source + "]")) {
    const zh = attribute === "textContent" ? element.textContent : element.getAttribute(attribute);
    staticTranslations.push({element, attribute, zh, en: element.getAttribute(source)});
  }
}
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

function setLanguage(next, persist = true) {
  language = next;
  if (persist) {
    try { localStorage.setItem(languageKey, next); } catch { /* Keep the choice for this page. */ }
  }
  document.documentElement.lang = t("zh-CN", "en");
  for (const {element, attribute, zh, en} of staticTranslations) {
    if (attribute === "textContent") element.textContent = t(zh, en);
    else element.setAttribute(attribute, t(zh, en));
  }
  for (const lang of ["zh", "en"]) el("lang-" + lang).setAttribute("aria-pressed", String(next === lang));
  for (const option of el("example").options) {
    const example = examples.find((item) => item.id === option.value);
    if (example) option.textContent = t(example.name, exampleNames[example.id] || example.name);
  }
  updateRoundLabels();
  if (configMenu) updateSettingsSummary();
  else if (configLoadFailed) el("config-summary").textContent = t("配置加载失败", "Could not load settings");
  el("start-label").textContent = busy ? t("运行中", "Running") : t("启动运行", "Start run");
  if (lastRun) {
    renderStatus(lastRun.status);
    renderEvents(lastRun.events || [], true);
    renderResults(lastRun.results || [], lastRun.files || []);
    if (questionId && lastRun.question) renderQuestionHeading(lastRun.question);
  }
  for (const [id, message] of notices) el(id).textContent = noticeText(message);
}

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
  let presetName = t(configMenu.presets[preset]?.name || "自定义", presetNames[preset]);
  if (preset === "environment") {
    const defaults = configMenu.presets.environment;
    const match = ["fast", "full"].find((id) =>
      Object.keys(limitFields).every((key) => configMenu.presets[id][key] === defaults[key]));
    presetName = t("环境默认", "Environment defaults") + " · " + (match
      ? t(configMenu.presets[match].name, presetNames[match]) : t("自定义参数", "Custom limits"));
  }
  const keyStatus = custom ? (busy && runId ? t("本次密钥", "One-time key") : el("api-key").value.trim()
    ? t("本次密钥已填", "One-time key entered") : t("待输入密钥", "Key needed"))
    : provider.has_key ? t("服务端密钥已配置", "Local key configured") : t("服务端密钥未配置", "No local key");
  const lockHint = busy && runId ? t("。本次运行结束后可更改配置。", ". Settings unlock when this run ends.") : "";
  const interactionName = choice("interaction") === "auto" ? t("自动回复", "Automatic replies") : t("人工回复", "Manual replies");
  el("server-key-option").textContent = provider.has_key
    ? t("本机 Key（已配置）", "Local key (configured)") : t("本机 Key（未配置）", "Local key (missing)");
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

function settingsError(id, zh, en) {
  el(id).focus();
  const error = new Error(zh);
  error.label = () => t(zh, en);
  throw error;
}

function runSettings() {
  const options = publicSettings();
  if (!configMenu.interaction) {
    if (options.interaction === "auto") {
      settingsError("start", "当前服务版本仅支持人工回复。请使用新版服务启动自动模式，或选择人工回复。",
        "This server supports manual replies only. Use an updated server for automatic replies, or select manual replies.");
    }
    delete options.interaction;
  }
  options.model ||= configMenu.providers[options.provider].model;
  if (options.key_source === "custom") {
    options.api_key = el("api-key").value.trim();
    if (!options.api_key) settingsError("api-key", "请输入本次运行的 API 密钥。", "Enter an API key for this run.");
  } else if (!configMenu.providers[options.provider].has_key) {
    settingsError("custom-key-choice", "该服务尚未配置密钥。请选择「输入本次 Key」并填写密钥。",
      "No local key is configured for this provider. Select the one-time key option and enter a key.");
  }
  if (options.preset === "custom") {
    if (!Number.isFinite(options.budget) || options.budget < 0) settingsError("budget", "每轮时限应为大于或等于 0 的秒数。", "Enter a time limit of zero seconds or more.");
    if (!Number.isInteger(options.research) || options.research < 0) settingsError("research", "检索次数应为大于或等于 0 的整数。", "Enter a whole number of research calls, zero or more.");
    if (!Number.isFinite(options.min_use) || options.min_use < 0 || options.min_use >= 1) settingsError("min-use", "最早交付比例应大于或等于 0 且小于 1。", "Enter a minimum budget fraction from 0 up to but excluding 1.");
  }
  return options;
}

function node(tag, className, content) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (content !== undefined) item.textContent = content;
  return item;
}

function noticeText(message) {
  if (typeof message === "function") return message();
  if (message?.label) return message.label();
  return masErrorText(message?.message || message || "", language);
}

function withError(zh, en, error) {
  return () => t(zh, en) + " " + noticeText(error);
}

function notice(id, message) {
  if (message) notices.set(id, message);
  else notices.delete(id);
  el(id).textContent = message ? noticeText(message) : "";
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
    const error = new Error(data.error || data.detail || "HTTP " + response.status);
    error.status = response.status;
    if (!data.error && !data.detail) error.label = () => t("服务请求失败（HTTP " + response.status + "）", "Request failed (HTTP " + response.status + ").");
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

function updateRoundLabels() {
  Array.from(el("rounds").children).forEach((button, index) => {
    button.textContent = t("第 " + (index + 1) + " 轮", "Round " + (index + 1));
  });
  el("task-count").textContent = t("共 " + tasks.length + " 轮 · 按顺序执行",
    tasks.length + (tasks.length === 1 ? " round" : " rounds") + " · Runs in order");
}

function renderTasks() {
  const buttons = tasks.map((_, index) => {
    const button = node("button", "round");
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
  updateRoundLabels();
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
  el("start-label").textContent = value ? t("运行中", "Running") : t("启动运行", "Start run");
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

function formatElapsed(seconds) {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600), minutes = Math.floor(total % 3600 / 60), rest = total % 60;
  const two = (value) => String(value).padStart(2, "0");
  return hours ? hours + ":" + two(minutes) + ":" + two(rest) : two(minutes) + ":" + two(rest);
}

// Seconds since epoch when the run began: the server says so; an older run falls back to its first event.
function runOrigin(events) {
  if (Number.isFinite(lastRun?.started)) return lastRun.started;
  const first = events.length ? events[0].ts ?? events[0].time : null;
  const value = typeof first === "number" ? first : Date.parse(first) / 1000;
  return Number.isFinite(value) ? value : null;
}

function renderElapsed() {
  const label = el("elapsed");
  const started = lastRun?.started;
  if (!Number.isFinite(started)) { label.hidden = true; return; }
  const end = Number.isFinite(lastRun.finished) ? lastRun.finished : Date.now() / 1000;
  label.textContent = t("已用时 ", "Elapsed ") + formatElapsed(end - started);
  label.hidden = false;
}
setInterval(renderElapsed, 1000);

function renderEvents(events, relabel = false) {
  const list = el("events");
  const nearEnd = list.scrollHeight - list.clientHeight - list.scrollTop < 60;
  const scrollTop = list.scrollTop;
  // Run events are append-only. Preserve scroll position and text selection while polling.
  if (relabel || events.length < list.children.length) list.replaceChildren();
  const fragment = document.createDocumentFragment();
  for (const event of events.slice(list.children.length)) {
    const item = node("li", "event");
    const heading = node("div", "event-head");
    const label = event.automatic ? t("自动回复", "Automatic reply")
      : Object.hasOwn(eventLabels, event.kind) ? t(...eventLabels[event.kind]) : event.kind || t("进度", "Progress");
    let speaker = event.sender;
    if (speaker === "human") speaker = event.automatic ? null : t("你", "You");
    if (speaker === "orchestrator") speaker = t("系统", "System");
    heading.append(node("strong", "", speaker ? speaker + " · " + label : label));
    const stamp = event.ts ?? event.time;
    if (stamp) {
      const date = new Date(typeof stamp === "number" ? stamp * 1000 : stamp);
      if (!Number.isNaN(date.valueOf())) {
        // How long into the run, not the time of day: what matters while following a run is how many minutes it has taken.
        const origin = runOrigin(events);
        const seconds = origin === null ? null : date.valueOf() / 1000 - origin;
        const time = node("time", "", seconds === null ? date.toLocaleTimeString(t("zh-CN", "en-US"), {hourCycle: "h23"})
          : formatElapsed(seconds));
        time.dateTime = date.toISOString();
        time.title = date.toLocaleTimeString(t("zh-CN", "en-US"), {hourCycle: "h23"});
        heading.append(time);
      }
    }
    const text = event.kind === "status" && Object.hasOwn(taskStates, event.text) ? t(...taskStates[event.text]) : event.text;
    item.append(heading, node("p", "message", text));
    fragment.append(item);
  }
  list.append(fragment);
  list.hidden = !events.length;
  el("events-empty").hidden = Boolean(events.length);
  el("event-count").textContent = events.length;
  if (nearEnd && !el("events-view").hidden) list.scrollTop = list.scrollHeight;
  else if (relabel) list.scrollTop = scrollTop;
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
  const signature = JSON.stringify([language, results, files]);
  if (signature === renderedResults) return;
  renderedResults = signature;
  const listed = new Set();
  el("results").replaceChildren(...results.map((result, index) => {
    const card = node("article", "result");
    const round = index + 1;
    const title = result.default_title || !result.title ? t("第 " + round + " 轮结果", "Round " + round + " result") : result.title;
    card.append(node("h3", "", title));
    if (result.success === false) card.append(node("p", "result-failed", t("本轮未完成", "Round did not complete")));
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
    block.append(node("h3", "", t("交付文件", "Deliverables")), fileList(extra));
    el("extra-files").append(block);
  }
  el("result-count").textContent = results.length;
  el("results-empty").hidden = Boolean(results.length || files.length);
}

function renderQuestionHeading(question) {
  const sender = question.sender || t("团队", "The team");
  el("question-heading").textContent = t(sender + " 需要你的回复", sender + " needs your reply");
}

function renderQuestion(question) {
  el("question-form").hidden = !question;
  if (questionId === (question?.id ?? null)) return;
  questionId = question?.id ?? null;
  el("answer").value = "";
  notice("answer-error", "");
  if (!question) return;
  renderQuestionHeading(question);
  el("question-text").textContent = question.text;
  el("question-options").replaceChildren(...(question.options || []).map((option) => {
    const button = node("button", "", option);
    button.type = "button";
    button.addEventListener("click", () => { el("answer").value = option; el("answer").focus(); });
    return button;
  }));
}

function renderStatus(status) {
  const active = ["queued", "running", "waiting"].includes(status);
  el("status").dataset.state = status;
  el("status").textContent = Object.hasOwn(stateLabels, status) ? t(...stateLabels[status]) : status;
  el("empty-title").textContent = active ? t("等待团队消息", "Waiting for team activity") : t("暂无协作记录", "No activity recorded");
  el("empty-note").textContent = active ? t("收到第一条事件后将自动显示。", "The first event will appear here automatically.")
    : t("本次运行没有产生协作事件。", "This run produced no activity.");
}

function renderRun(run) {
  lastRun = run;
  const status = run.status;
  const active = ["queued", "running", "waiting"].includes(status);
  if (active && ["auto", "manual"].includes(run.interaction)) runInteraction = run.interaction;
  setBusy(active);
  if (runInteraction !== "manual") notice("switch-error", "");
  renderStatus(status);
  renderElapsed();
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
      renderRun({status: "failed", error: () => t("找不到上次运行。可以用当前配置重新启动。", "The previous run could not be found. Start again with the current settings.")});
      runId = null;
      save();
    } else {
      notice("run-error", withError("暂时无法读取运行进度，将自动重试。", "Could not load progress. Retrying automatically.", error));
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
    notice("setup-error", () => t("请填写角色定义，或选择场景模板。", "Enter team roles or choose a scenario template."));
    el("roles").focus();
    return;
  }
  const emptyRound = tasks.findIndex((task) => !task.trim());
  if (emptyRound !== -1) {
    activeTask = emptyRound;
    renderTasks();
    notice("setup-error", () => t("请先填写第 " + (emptyRound + 1) + " 轮任务。", "Enter a task for round " + (emptyRound + 1) + "."));
    el("task").focus();
    return;
  }
  notice("setup-error", "");
  try {
    if (!configMenu) {
      await loadSettings();
      notice("setup-error", () => t("已重新读取配置，请核对模型与运行参数后启动。", "Settings reloaded. Check the model and run settings, then start the run."));
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
      catch (resumeError) { notice("run-error", resumeError); }
    }
    setBusy(false);
    notice("setup-error", error);
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
  } catch (error) { notice("setup-error", withError("文件读取失败。", "Could not read the file.", error)); }
}

async function answer(event) {
  event.preventDefault();
  if (!questionId || sendingAnswer || switchingMode) return;
  const reply = el("answer").value.trim();
  if (!reply) { notice("answer-error", () => t("请先输入回复。", "Enter a reply first.")); el("answer").focus(); return; }
  sendingAnswer = true;
  el("switch-mode").disabled = true;
  el("send-answer").disabled = true;
  try {
    await api("/api/runs/" + encodeURIComponent(runId) + "/answer", {id: questionId, answer: reply});
    await refresh(runId);
  } catch (error) { notice("answer-error", error); }
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
      ? () => t("当前服务版本尚未支持运行中切换，仍可在此人工回复。", "This server cannot switch modes during a run. You can still reply manually.") : error;
    notice("switch-error", message);
  } finally {
    switchingMode = false;
    el("switch-mode").disabled = el("send-answer").disabled = false;
    if (runId === id) await refresh(id);
  }
}

async function init() {
  const draft = loadDraft();
  const loadErrors = [];
  setBusy(true);
  try {
    const data = await api("/api/examples");
    examples = data.examples;
    for (const example of examples) el("example").add(new Option(t(example.name, exampleNames[example.id] || example.name), example.id));
  } catch (error) { loadErrors.push(withError("场景模板加载失败，可手动粘贴或导入文件。", "Could not load templates. You can still paste or import files.", error)); }
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
    configLoadFailed = true;
    el("config-summary").textContent = t("配置加载失败", "Could not load settings");
    loadErrors.push(withError("未能读取模型配置，点击启动运行可重试。", "Could not load model settings. Select Start run to retry.", error));
  }
  if (loadErrors.length) notice("setup-error", () => loadErrors.map(noticeText).join(" "));
  try { if (await resumeActive()) return; }
  catch (error) { notice("run-error", withError("未能恢复当前运行。", "Could not reconnect to the active run.", error)); }
  if (runId) await refresh(runId);
  else setBusy(false);
}

for (const lang of ["zh", "en"]) el("lang-" + lang).addEventListener("click", () => setLanguage(lang));
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
setLanguage(language, false);
init();

// Localize known server diagnostics at display time, including those from older workspaces.
function masErrorText(message, lang) {
  if (!message) return "";
  const text = String(message);
  if (lang === "en" || lang?.startsWith("en-")) {
    const translations = {
      "仅允许从本机访问。": "Open this workspace on the machine running the server.",
      "请从工作台页面发起请求。": "Send this request from the workspace page.",
      "找不到这个页面。": "Page not found.",
      "请求需要使用 JSON 格式。": "Send the request as JSON.",
      "请输入角色和任务，总大小限 1 MiB。": "Provide roles and tasks with a combined size of up to 1 MiB.",
      "需要一个包含角色和任务的 JSON 对象。": "Provide a JSON object with roles and tasks.",
      "请输入角色 Markdown 和任务列表。": "Provide the role definitions in Markdown and a list of tasks.",
      "请选择问题并填写答复。": "Select a question and enter your answer.",
      "找不到这个接口。": "The requested API endpoint could not be found.",
      "找不到这次运行、问题或文件。": "The requested run, question, or file could not be found.",
      "服务发生错误，详情请查看终端。": "The server encountered an error. Check the terminal for details.",
      "模型服务调用失败，请检查配置。": "The model request failed. Check the model settings.",
      "模型服务调用失败，请检查模型和连接。": "The model request failed. Check the model and network connection.",
      "请填写角色 Markdown。": "Enter the role definitions in Markdown.",
      "角色 ID 不能仅有大小写差异。": "Role IDs must be unique regardless of capitalization.",
      "角色 ID 不能使用系统保留文件名。": "Choose a role ID other than a reserved system filename.",
      "请至少填写一个任务。": "Enter at least one task.",
      "运行提前结束。": "The run ended early.",
      "有任务未成功完成，请查看各任务结果。": "One or more tasks failed. Review each task’s result for details.",
      "本地服务已停止，运行中断。": "The local server stopped and interrupted this run.",
      "这次运行已经结束。": "This run has already ended.",
      "请输入回复。": "Enter an answer.",
      "这个问题已经结束。": "This question is already closed.",
      "当前已有任务正在运行。": "Another run is already in progress.",
      "时间预算必须是非负的有限秒数。": "Enter a finite time budget of zero or more seconds.",
      "研究次数必须是非负整数。": "Enter a whole number of research calls, zero or greater.",
      "最低时间使用比例必须大于等于 0 且小于 1。": "Enter a minimum time share of at least 0 and less than 1.",
      "运行配置格式或字段无效。": "The run configuration contains an invalid field or format.",
      "请选择 HKGAI 或 DeepSeek。": "Select HKGAI or DeepSeek.",
      "请输入有效的模型 ID。": "Enter a valid model ID.",
      "请选择自动答复或手动答复。": "Select automatic or manual replies.",
      "请输入有效的 API Key，不能包含空格或换行。": "Enter an API key without spaces or line breaks.",
      "请选择有效的密钥来源。只有本次输入模式可以提交 API Key。": "Choose a key source. To enter an API key, select the option for this run.",
      "运行预设无效。": "Select a valid run preset.",
      "只有自定义预设可以更改运行参数。": "Select the custom preset to change run parameters.",
    };
    if (Object.hasOwn(translations, text)) return translations[text];
    return text
      .replace(/^任务 (\d+) 的内容为空。$/, "Task $1 is empty.")
      .replace(/^任务 (\d+) 的代码块中没有任务内容。$/, "Enter the prompt inside the fenced block for task $1.")
      .replace(/^任务 (\d+) 以 \/ 开头，会被系统当作聊天命令。请填写任务指令。$/,
        "Task $1 starts with a slash, which the team reads as a chat command. Enter a task instruction.");
  }

  const translations = {
    "no members found: expected '## <Role name> (<agent id>)' headings, each followed by a fenced prompt":
      "未找到角色。请使用“## 角色名称 (角色ID)”作为二级标题，并将角色指令写在标题下的 Markdown 代码块中。",
    "a team needs at least one role": "团队至少需要一个角色。",
    "thinking must be 'off' or 'default'": "请将 DeepSeek 的思考模式设为 off 或 default。",
    "Failed to fetch": "无法连接到本地服务，请检查服务是否正在运行。",
    "Load failed": "无法连接到本地服务，请检查服务是否正在运行。",
    "NetworkError when attempting to fetch resource.": "无法连接到本地服务，请检查服务是否正在运行。",
  };
  if (Object.hasOwn(translations, text)) return translations[text];
  return text
    .replace(/^agent (.+) is defined twice$/, "角色 $1 重复定义。请给每个角色使用不同的 ID。")
    .replace(/^(.+) cannot be an agent id$/, "$1 不是有效的角色 ID。请以英文字母开头，并避开系统保留名称。")
    .replace(/^(HKGAI|DEEPSEEK)_API_KEY is not set\. Copy \.env\.example to \.env and fill it in, or try .+ which needs no key\.$/,
      "服务端未配置 $1_API_KEY。请在工作台输入本次运行的密钥，或在服务端 .env 中配置后重启。")
    .replace(/^(HKGAI|DEEPSEEK)_MODEL is not set\. Set it to a model ID available to your .+ account\.$/,
      "服务端未配置 $1_MODEL。请输入该账户可用的模型 ID。")
    .replace(/^(HKGAI|DeepSeek) API key, base URL and model are required$/, "$1 需要 API 密钥、服务地址和模型 ID。")
    .replace(/^(HKGAI|DeepSeek) base URL must be an absolute HTTP\(S\) URL without credentials, query or fragment, and with a valid port$/,
      "$1 需要有效的 HTTP(S) 服务地址和端口，地址中不能包含凭据、查询参数或片段。");
}
