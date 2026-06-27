let sessions = [];
let activeSessionId = null;
let activeRunId = null;
let source = null;
let questionArtifactId = null;
let interactionLoadToken = 0;
let waitingForInput = false;
let activeRunStatus = null;
let lastAskText = "";

const el = (id) => document.getElementById(id);
const on = (id, event, handler) => {
  const target = el(id);
  if (target) target.addEventListener(event, handler);
};

const workflowSteps = [
  "Prepare Project",
  "Generate Spec",
  "Validate Spec",
  "Review Spec",
  "Spec Gate",
  "Generate Todo",
  "Validate Todo",
  "Review Todo",
  "Todo Gate",
  "Generate Tests",
  "Build",
  "Run Test",
  "Final Review",
  "Final Gate",
];

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || res.statusText);
  }
  return res.json();
}

function escapeHtml(value = "") {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#039;",
  })[char]);
}

function shortPath(path = "") {
  return path.replace(/^C:\\Users\\kevin\\/i, "~/");
}

function renderSessions() {
  const list = el("projectList");
  list.innerHTML = "";
  sessions.forEach((session) => {
    const row = document.createElement("div");
    row.className = `project-row ${session.id === activeSessionId ? "active" : ""}`;
    row.innerHTML = `
      <button class="project-item">
        <strong>${escapeHtml(session.title || "Project")}</strong>
        <span>${escapeHtml(shortPath(session.project_path || ""))}</span>
      </button>
      <button class="icon-button danger" title="Delete project">×</button>
    `;
    row.querySelector(".project-item").onclick = () => selectSession(session.id);
    row.querySelector(".danger").onclick = (event) => deleteSession(event, session.id);
    list.appendChild(row);
  });
}

async function loadSessions() {
  sessions = await api("/api/sessions");
  if (activeSessionId && !sessions.some((session) => session.id === activeSessionId)) {
    activeSessionId = sessions[0]?.id || null;
  }
  if (!activeSessionId && sessions.length) activeSessionId = sessions[0].id;
  renderSessions();
  if (activeSessionId) await selectSession(activeSessionId);
  if (!activeSessionId) clearProject();
}

function clearProject() {
  el("sessionTitle").textContent = "Select a project";
  el("runMeta").textContent = "No active run";
  el("messageInput").value = "";
  el("runWorkflow").disabled = true;
  el("retryRun").disabled = true;
  el("addGuidance").disabled = true;
  el("messages").innerHTML = "";
  clearRunPanels();
}

function setComposerWaiting(waiting) {
  const wasWaiting = waitingForInput;
  waitingForInput = waiting;
  if (waiting && !wasWaiting) el("messageInput").value = "";
  el("messageInput").placeholder = waiting ? "Reply to Qwen here..." : "Describe what to build...";
  el("runWorkflow").textContent = activeRunStatus === "running" ? "Terminate" : (waiting ? "Reply & Continue" : "Run");
  el("saveRequirement").disabled = waiting;
}

function updatePrimaryAction(run = null) {
  activeRunStatus = run?.status || activeRunStatus;
  const running = activeRunStatus === "running" || activeRunStatus === "queued";
  if (running) {
    el("runWorkflow").textContent = "Terminate";
    el("runWorkflow").disabled = false;
    el("messageInput").placeholder = "Workflow is running. Add Guidance stays available.";
    el("saveRequirement").disabled = true;
    return;
  }
  setComposerWaiting(waitingForInput);
  el("runWorkflow").disabled = !activeSessionId;
}

async function refreshSessionsList() {
  sessions = await api("/api/sessions");
  renderSessions();
  const session = sessions.find((item) => item.id === activeSessionId);
  if (session) renderProjectHeader(session);
}

function renderProjectHeader(session) {
  el("sessionTitle").textContent = session?.title || "Project";
  el("runMeta").textContent = shortPath(session?.project_path || "");
}

async function selectSession(sessionId) {
  activeSessionId = sessionId;
  activeRunId = null;
  if (source) source.close();
  renderSessions();
  const session = sessions.find((item) => item.id === sessionId);
  renderProjectHeader(session);
  el("runWorkflow").disabled = false;
  await loadMessages();
  await loadLatestRun();
}

async function loadLatestRun() {
  clearRunPanels();
  if (!activeSessionId) return;
  const run = await api(`/api/sessions/${activeSessionId}/workflow-runs/latest`);
  if (!run) return;
  renderRun(run);
  if (["queued", "running", "waiting_input"].includes(run.status)) {
    await followRun(run.id);
  }
}

async function loadMessages() {
  const messages = await api(`/api/sessions/${activeSessionId}/messages`);
  const list = el("messages");
  list.innerHTML = "";
  lastAskText = "";
  messages.forEach((msg) => {
    const div = document.createElement("div");
    const isAsk = msg.role !== "user" && msg.content.startsWith("Qwen asks:");
    div.className = `message ${msg.role === "user" ? "user" : "assistant"}${isAsk ? " ask" : ""}`;
    if (isAsk) {
      const title = document.createElement("strong");
      title.textContent = "Qwen asks";
      const body = document.createElement("div");
      body.textContent = msg.content.replace(/^Qwen asks:\s*/i, "");
      div.appendChild(title);
      div.appendChild(body);
    } else {
      div.textContent = msg.content;
    }
    list.appendChild(div);
  });
  if (!messages.length) {
    const div = document.createElement("div");
    div.className = "message system";
    div.textContent = "Describe what you want to build, then run the workflow.";
    list.appendChild(div);
  }
  const latest = [...messages].reverse().find((msg) => msg.role === "user");
  el("messageInput").value = latest?.content || "";
  list.scrollTop = list.scrollHeight;
}

function addLocalMessage(content, role = "user") {
  const list = el("messages");
  const div = document.createElement("div");
  div.className = `message ${role === "user" ? "user" : "assistant"}`;
  div.textContent = content;
  list.appendChild(div);
  list.scrollTop = list.scrollHeight;
}

function clearRunPanels() {
  el("currentStep").textContent = "Idle";
  el("progressText").textContent = `0 / ${workflowSteps.length}`;
  el("resultText").textContent = "Waiting";
  hideInteraction();
  renderStepSkeleton();
  el("qwenLive").textContent = "No Qwen output yet.";
  el("logs").textContent = "";
  el("artifacts").innerHTML = "";
  el("artifactContent").textContent = "";
}

function renderStepSkeleton() {
  const steps = el("steps");
  steps.innerHTML = "";
  workflowSteps.forEach((title) => {
    const row = document.createElement("div");
    row.className = "step";
    row.innerHTML = `<div><span>${title}</span></div><div class="step-actions"><span class="badge pending">pending</span></div>`;
    steps.appendChild(row);
  });
}

function renderRun(run) {
  activeRunId = run.id;
  activeRunStatus = run.status;
  const session = sessions.find((item) => item.id === run.session_id);
  const passed = run.steps.filter((step) => step.status === "passed").length;
  el("runMeta").textContent = `${run.status.toUpperCase()} - ${shortPath(run.project_path || session?.project_path || "")}`;
  const running = run.steps.find((step) => step.status === "running");
  const failed = run.steps.find((step) => step.status === "failed" || step.status === "waiting_input");
  el("currentStep").textContent = running?.title || failed?.title || (run.status === "done" ? "Complete" : "Idle");
  el("progressText").textContent = `${passed} / ${run.steps.length}`;
  el("resultText").textContent = run.status.toUpperCase();
  el("retryRun").disabled = run.status === "running";
  el("addGuidance").disabled = false;
  updatePrimaryAction(run);

  const steps = el("steps");
  steps.innerHTML = "";
  run.steps.forEach((step) => {
    const row = document.createElement("div");
    row.className = "step";
    const retry = step.retry_count ? `<span class="retry-count">retry ${step.retry_count}</span>` : "";
    const error = step.error ? `<small>${escapeHtml(step.error)}</small>` : "";
    const promptArtifact = (run.artifacts || []).find((artifact) => artifact.path === `prompts/${step.key}.md`);
    const promptButton = promptArtifact ? `<button class="mini-button" data-artifact-id="${escapeHtml(promptArtifact.id)}">Prompt</button>` : "";
    row.innerHTML = `
      <div><span>${escapeHtml(step.title)}</span>${retry}${error}</div>
      <div class="step-actions">
        ${promptButton}
        <button class="mini-button guide-step" data-step-key="${escapeHtml(step.key)}">Guide</button>
        <button class="mini-button retry-step" data-step-key="${escapeHtml(step.key)}">Retry</button>
        <span class="badge ${step.status}">${step.status}</span>
      </div>
    `;
    const prompt = row.querySelector("[data-artifact-id]");
    if (prompt) prompt.onclick = () => openArtifact(prompt.dataset.artifactId);
    row.querySelector(".guide-step").onclick = () => addGuidance(step.key);
    row.querySelector(".retry-step").onclick = () => retryRun(step.key);
    steps.appendChild(row);
  });
  renderArtifacts(run.artifacts || []);
  renderInteraction(run);
}

function renderArtifacts(artifacts) {
  const target = el("artifacts");
  target.innerHTML = "";
  artifacts.forEach((artifact) => {
    const button = document.createElement("button");
    button.className = "artifact-button";
    button.textContent = artifact.path;
    button.title = artifact.path;
    button.onclick = () => openArtifact(artifact.id);
    target.appendChild(button);
  });
}

async function openArtifact(artifactId) {
  const data = await api(`/api/artifacts/${encodeURIComponent(artifactId)}`);
  el("artifactContent").textContent = `# ${data.path}\n\n${data.content}`;
  el("artifactContent").scrollTop = 0;
  activateTab("artifactsPanel");
}

function hideInteraction() {
  questionArtifactId = null;
  interactionLoadToken += 1;
  setComposerWaiting(false);
}

function renderAskMessage(text) {
  const content = text || "Qwen needs more information before continuing.";
  if (content === lastAskText) return;
  const existing = Array.from(el("messages").querySelectorAll(".message"))
    .some((node) => node.textContent.includes(content));
  if (existing) {
    lastAskText = content;
    el("messages").scrollTop = el("messages").scrollHeight;
    return;
  }
  lastAskText = content;
  const list = el("messages");
  const ask = document.createElement("div");
  ask.className = "message assistant ask";
  ask.innerHTML = "";
  const title = document.createElement("strong");
  title.textContent = "Qwen asks";
  const body = document.createElement("div");
  body.textContent = content;
  ask.appendChild(title);
  ask.appendChild(body);
  list.appendChild(ask);
  list.scrollTop = list.scrollHeight;
}

function renderInteraction(run) {
  const waitingStep = run.steps.find((step) => step.status === "waiting_input");
  if (run.status !== "waiting_input" || !waitingStep) {
    hideInteraction();
    return;
  }

  setComposerWaiting(true);
  renderAskMessage(waitingStep.error || "Qwen needs more information before continuing.");
  setTimeout(() => {
    el("messages").scrollTop = el("messages").scrollHeight;
    el("messageInput").focus();
  }, 0);
  const artifact = (run.artifacts || []).find((item) => item.path === "input/questions.md");
  questionArtifactId = artifact?.id || null;
  const token = ++interactionLoadToken;
  if (!questionArtifactId) return;

  api(`/api/artifacts/${encodeURIComponent(questionArtifactId)}`)
    .then((data) => {
      if (token === interactionLoadToken && activeRunId === run.id) {
        renderAskMessage(data.content);
        el("messageInput").focus();
      }
    })
    .catch((err) => {
      if (token === interactionLoadToken) appendPre("logs", `Question file could not be loaded: ${err.message}`);
    });
}

async function submitAnswers() {
  if (!activeRunId) return;
  const content = el("messageInput").value.trim();
  if (!content) {
    appendPre("logs", "Please enter a reply before continuing.");
    return;
  }
  el("runWorkflow").disabled = true;
  try {
    appendPre("logs", "Submitting reply and continuing workflow...");
    const run = await api(`/api/workflow-runs/${activeRunId}/answers`, {
      method: "POST",
      body: JSON.stringify({ content }),
    });
    el("messageInput").value = "";
    await loadMessages();
    hideInteraction();
    await followRun(run.id);
  } catch (err) {
    appendPre("logs", `Continue failed: ${err.message}`);
    activateTab("logsPanel");
  } finally {
    el("runWorkflow").disabled = false;
  }
}

async function followRun(runId) {
  if (source) source.close();
  const run = await api(`/api/workflow-runs/${runId}`);
  renderRun(run);
  source = new EventSource(`/api/workflow-runs/${runId}/events`);
  source.onmessage = (message) => {
    const event = JSON.parse(message.data);
    if (event.type === "log") appendPre("logs", event.message);
    if (event.type === "qwen_status") appendPre("qwenLive", `[${event.step}] ${event.message}`);
    if (event.type === "qwen_output") appendPre("qwenLive", `[${event.step}:${event.stream}] ${event.text}`);
    if (event.type === "run") renderRun(event.run);
    if (["done", "failed", "waiting_input", "cancelled"].includes(event.type)) source.close();
  };
}

function appendPre(id, line) {
  const target = el(id);
  if (target.textContent === "No Qwen output yet.") target.textContent = "";
  target.textContent += line + "\n";
  target.scrollTop = target.scrollHeight;
}

async function deleteSession(event, sessionId) {
  event.stopPropagation();
  const session = sessions.find((item) => item.id === sessionId);
  if (!confirm(`Delete "${session?.title || "Project"}"?`)) return;
  await api(`/api/sessions/${sessionId}`, { method: "DELETE" });
  if (activeSessionId === sessionId) {
    activeSessionId = null;
    activeRunId = null;
    if (source) source.close();
  }
  await loadSessions();
}

async function loadConfig() {
  const config = await api("/api/config");
  const qwen = config.qwen;
  el("qwenAuthType").value = qwen.auth_type || "";
  el("qwenReuseSession").checked = Boolean(qwen.reuse_session);
  el("maxRetries").value = qwen.max_retries ?? 2;
  renderQwenMeta(qwen);
}

function renderQwenMeta(qwen) {
  const mode = qwen.mock ? "MOCK" : "REAL";
  const exists = qwen.exists ? "ready" : "missing";
  const skills = qwen.skills_ready ? `${qwen.skill_count} skills` : "no skills";
  el("qwenMeta").textContent = `${mode} - ${qwen.bin} - ${exists} - ${skills}`;
}

async function saveQwenConfig() {
  const config = await api("/api/config/qwen", {
    method: "POST",
    body: JSON.stringify({
      auth_type: el("qwenAuthType").value,
      reuse_session: el("qwenReuseSession").checked,
      max_retries: Number(el("maxRetries").value || 0),
    }),
  });
  renderQwenMeta(config.qwen);
}

async function saveRequirement() {
  const content = el("messageInput").value.trim();
  if (!content || !activeSessionId) return;
  await api(`/api/sessions/${activeSessionId}/messages`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
  await loadMessages();
  await refreshSessionsList();
  el("messages").scrollTop = el("messages").scrollHeight;
}

async function startRun() {
  if (activeRunId && ["running", "queued"].includes(activeRunStatus)) {
    await terminateRun();
    return;
  }
  if (waitingForInput) {
    await submitAnswers();
    return;
  }
  if (!activeSessionId) return;
  const content = el("messageInput").value.trim();
  if (content) await saveRequirement();
  el("runWorkflow").disabled = true;
  try {
    el("logs").textContent = "Starting workflow...\n";
    el("qwenLive").textContent = "Waiting for Qwen process...\n";
    const run = await api(`/api/sessions/${activeSessionId}/workflow-runs`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    if (run.status === "queued" || run.status === "running" || run.status === "waiting_input") {
      el("logs").textContent += `Attached to run ${run.id}\n`;
    }
    await followRun(run.id);
  } catch (err) {
    el("logs").textContent += `Run failed to start: ${err.message}\n`;
  } finally {
    el("runWorkflow").disabled = false;
  }
}

async function retryRun(stepKey = null) {
  if (!activeRunId) {
    appendPre("logs", "No run selected to retry.");
    activateTab("logsPanel");
    return;
  }
  el("retryRun").disabled = true;
  try {
    appendPre("logs", stepKey ? `Retry requested from ${stepKey}...` : "Retry requested...");
    const run = await api(`/api/workflow-runs/${activeRunId}/retry`, {
      method: "POST",
      body: JSON.stringify({ step_key: stepKey }),
    });
    appendPre("logs", `Retry started: ${run.id}`);
    await followRun(run.id);
  } catch (err) {
    appendPre("logs", `Retry failed: ${err.message}`);
    activateTab("logsPanel");
    if (activeRunId) {
      const run = await api(`/api/workflow-runs/${activeRunId}`).catch(() => null);
      if (run) renderRun(run);
    }
  } finally {
    el("retryRun").disabled = false;
  }
}

function defaultGuidanceStepKey() {
  const failed = document.querySelector(".step .badge.failed, .step .badge.waiting_input, .step .badge.running");
  if (failed) return failed.closest(".step")?.querySelector(".guide-step")?.dataset.stepKey || null;
  return document.querySelector(".step .guide-step")?.dataset.stepKey || null;
}

async function addGuidance(stepKey = null) {
  if (!activeRunId) {
    appendPre("logs", "No run selected for guidance.");
    activateTab("logsPanel");
    return;
  }
  const targetStep = stepKey || defaultGuidanceStepKey();
  if (!targetStep) {
    appendPre("logs", "No step selected for guidance.");
    activateTab("logsPanel");
    return;
  }
  const content = prompt(`Add guidance for ${targetStep}`, "");
  if (!content || !content.trim()) return;
  el("addGuidance").disabled = true;
  try {
    appendPre("logs", `Adding guidance for ${targetStep}...`);
    const run = await api(`/api/workflow-runs/${activeRunId}/guidance`, {
      method: "POST",
      body: JSON.stringify({ step_key: targetStep, content }),
    });
    appendPre("logs", run.status === "running"
      ? `Guidance saved for ${targetStep}. It will be included in later prompts.`
      : `Guidance saved. Retrying from ${targetStep}.`);
    await followRun(run.id);
  } catch (err) {
    appendPre("logs", `Add Guidance failed: ${err.message}`);
    activateTab("logsPanel");
  } finally {
    el("addGuidance").disabled = false;
  }
}

async function terminateRun() {
  if (!activeRunId) return;
  el("runWorkflow").disabled = true;
  try {
    appendPre("logs", "Terminating workflow...");
    const run = await api(`/api/workflow-runs/${activeRunId}/terminate`, {
      method: "POST",
      body: JSON.stringify({}),
    });
    renderRun(run);
    appendPre("logs", "Workflow terminated.");
  } catch (err) {
    appendPre("logs", `Terminate failed: ${err.message}`);
    activateTab("logsPanel");
  } finally {
    el("runWorkflow").disabled = false;
  }
}

function activateTab(panelId) {
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === panelId));
  document.querySelectorAll(".panel").forEach((panel) => panel.classList.toggle("active", panel.id === panelId));
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.onclick = () => activateTab(tab.dataset.tab);
});

on("qwenAuthType", "change", saveQwenConfig);
on("qwenReuseSession", "change", saveQwenConfig);
on("maxRetries", "change", saveQwenConfig);
on("saveRequirement", "click", saveRequirement);
on("runWorkflow", "click", startRun);
on("retryRun", "click", () => retryRun());
on("addGuidance", "click", () => addGuidance());

on("newProject", "click", async () => {
  const projectPath = prompt("Project folder path", "C:\\Users\\kevin\\sort");
  if (!projectPath) return;
  const session = await api("/api/sessions", {
    method: "POST",
    body: JSON.stringify({ project_path: projectPath }),
  });
  sessions.unshift(session);
  await selectSession(session.id);
});

loadConfig().catch((err) => {
  el("qwenMeta").textContent = err.message;
});

loadSessions().catch((err) => {
  el("runMeta").textContent = err.message;
});
