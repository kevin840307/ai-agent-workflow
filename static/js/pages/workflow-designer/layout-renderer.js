import { ensureActiveTabForStep as ensureStepTab, tabsForStep } from "./step-tabs.js?v=20260629-static-modules15";

export function installLayoutRenderer(ctx) {
  const {
    el,
    escapeAttr,
    escapeHtml,
    formatReviewMode,
    formatStepType,
    functionMeta,
    getSelectedStep,
    getSelectedWorkflow,
    getSystemWorkflow,
    isReadonly,
    markWorkflowDirty,
    moveStep,
    normalizeFilename,
    options,
    renderSettings,
    renderStepEditorHeader,
    renderStepEditorModal,
    renderWorkflowDirtyState,
    saveUiState,
    setText,
    state,
    summarizeStep,
    toast,
    stepUiCapabilities,
    workflowFunctionCounts,
  } = ctx;

  let draggedStepId = null;
  let stepContextMenuOpen = false;

function render() {
  document.body.dataset.designerMode = state.designerMode || "simple";
  renderSidebar();
  renderBackendStatus();
  renderWorkflowLabels();
  renderWorkflowDirtyState();
  renderWorkflowEditor();
  renderWorkflowViewOnly();
  renderTabs();
  renderSettings();
  renderStepEditorModal();
  renderJsonPanel();
}

function renderBackendStatus() {
  const target = el("designerBackendStatus");
  if (!target) return;
  const counts = workflowFunctionCounts();
  if (!state.apiLoaded) {
    target.textContent = "API Error";
    target.title = state.apiError || "Workflow API unavailable";
    target.classList.add("error");
    return;
  }
  target.classList.remove("error");
  target.textContent = "API Ready";
  target.title = `${counts.validators} validators, ${counts.reviewStrategies} review strategies, ${counts.aggregators} aggregators, ${counts.promptParams} prompt params loaded`;
}

function renderSidebar() {
  const customList = el("designerCustomList");
  if (!customList) return;

  el("designerSystemWorkflow")?.classList.toggle("active", state.selectedWorkflowId === getSystemWorkflow().id);
  customList.innerHTML = state.workflows.map((workflow) => `
    <div class="designer-workflow-pill ${workflow.id === state.selectedWorkflowId ? "active" : ""}" data-workflow-id="${escapeHtml(workflow.id)}">
      <strong>${escapeHtml(workflow.name)}</strong>
      <span>${workflow.steps.length} steps · ${workflow.active ? "active" : "draft"}</span>
      <span class="designer-workflow-pill-description">${escapeHtml(workflow.description || "No description.")}</span>
    </div>
  `).join("");
}

function renderWorkflowLabels() {
  const wf = getSelectedWorkflow();
  if (!wf) return;
  const readonly = isReadonly();

  setText("designerActiveWorkflowName", wf.name);
  setText(
    "designerActiveWorkflowMeta",
    readonly
      ? "System · read only · runner default"
      : `${wf.steps.length} steps · editable API workflow · ${wf.folderName || "new folder"} · runner selection not wired yet`
  );
  setText("designerEditableBadge", readonly ? "READ ONLY" : "EDITABLE");
  el("designerEditableBadge")?.classList.toggle("passed", !readonly);
  el("designerEditableBadge")?.classList.toggle("cancelled", readonly);
  setText("designerActiveWorkflowDescription", wf.description || "No description.");
  const input = el("workflowNameInput");
  if (input && input.value !== wf.name) input.value = wf.name;
  if (input) input.disabled = readonly;
  const descriptionInput = el("workflowDescriptionInput");
  if (descriptionInput && descriptionInput.value !== (wf.description || "")) descriptionInput.value = wf.description || "";
  if (descriptionInput) descriptionInput.disabled = readonly;
  const skillRootInput = el("workflowSkillRootInput");
  if (skillRootInput && skillRootInput.value !== (wf.skillRoot || "")) skillRootInput.value = wf.skillRoot || "";
  if (skillRootInput) skillRootInput.disabled = readonly;
  setText("designerWorkflowLockHint", readonly ? "Read only" : "Editable");
  el("designerWorkflowLockHint")?.classList.toggle("locked", readonly);

  if (el("designerSaveDraft")) el("designerSaveDraft").disabled = readonly;
  if (el("designerResetDraft")) el("designerResetDraft").disabled = readonly;
  if (el("designerDuplicateCustomWorkflow")) el("designerDuplicateCustomWorkflow").disabled = readonly;
  if (el("designerDeleteWorkflow")) el("designerDeleteWorkflow").disabled = readonly;
  renderSidebar();
}

function renderStepFloatingActions(wf) {
  const step = getSelectedStep();
  if (!wf || !step) return "";
  const readonly = isReadonly();
  const index = wf.steps.findIndex((item) => item.id === step.id);
  if (index < 0) return "";
  const disabled = readonly ? "disabled" : "";
  const moveUpDisabled = readonly || index <= 0 ? "disabled" : "";
  const moveDownDisabled = readonly || index >= wf.steps.length - 1 ? "disabled" : "";
  const expanded = state.stepActionMenuExpanded;
  const editLabel = readonly ? "View step" : "Edit step";
  const expandLabel = expanded ? "Collapse step actions" : "Expand step actions";
  return `
    <aside class="designer-step-floating-actions ${expanded ? "expanded" : "collapsed"}" aria-label="Selected step actions">
      <button type="button" class="designer-action-fab designer-action-toggle" data-designer-action="toggle-step-actions" aria-expanded="${expanded ? "true" : "false"}" title="${expandLabel}" aria-label="${expandLabel}">
        <span aria-hidden="true">${expanded ? "-" : "+"}</span>
      </button>
      <div class="designer-floating-panel" aria-hidden="${expanded ? "false" : "true"}">
        <span class="designer-floating-step-context" title="${escapeAttr(step.name || "Selected step")}">
          <strong>${escapeHtml(index + 1)} / ${escapeHtml(wf.steps.length)}</strong>
          <span>${escapeHtml(step.name || "Selected step")}</span>
        </span>
        <span class="designer-floating-action-buttons">
          <button type="button" class="designer-action-fab designer-floating-primary" data-designer-action="open-step-editor" data-step-id="${escapeHtml(step.id)}" title="${editLabel}" aria-label="${editLabel}"><span aria-hidden="true">✎</span></button>
          <button type="button" class="designer-action-fab" data-designer-action="move-step-up" data-step-id="${escapeHtml(step.id)}" title="Move up" aria-label="Move up" ${moveUpDisabled}><span aria-hidden="true">↑</span></button>
          <button type="button" class="designer-action-fab" data-designer-action="move-step-down" data-step-id="${escapeHtml(step.id)}" title="Move down" aria-label="Move down" ${moveDownDisabled}><span aria-hidden="true">↓</span></button>
          <button type="button" class="designer-action-fab" data-designer-action="duplicate-step" data-step-id="${escapeHtml(step.id)}" title="Duplicate" aria-label="Duplicate" ${disabled}><span aria-hidden="true">⧉</span></button>
          <button type="button" class="designer-action-fab designer-danger" data-designer-action="delete-step" data-step-id="${escapeHtml(step.id)}" title="Delete" aria-label="Delete" ${disabled}><span aria-hidden="true">×</span></button>
        </span>
      </div>
    </aside>
  `;
}

function openStepContextMenu(stepId, options = {}) {
  const wf = getSelectedWorkflow();
  const step = wf?.steps?.find((item) => item.id === stepId);
  if (!wf || !step) return;

  const anchorRect = options.anchor?.getBoundingClientRect?.();
  const x = Number.isFinite(options.x) ? options.x : (anchorRect ? anchorRect.right - 4 : window.innerWidth - 260);
  const y = Number.isFinite(options.y) ? options.y : (anchorRect ? anchorRect.bottom + 6 : window.innerHeight - 260);

  state.selectedStepId = step.id;
  ensureActiveTabForStep(step);
  saveUiState();
  renderWorkflowViewOnly();
  renderTabs();
  renderSettings();

  closeStepContextMenu();
  const readonly = isReadonly();
  const index = wf.steps.findIndex((item) => item.id === step.id);
  const moveUpDisabled = readonly || index <= 0 ? "disabled" : "";
  const moveDownDisabled = readonly || index >= wf.steps.length - 1 ? "disabled" : "";
  const editLabel = readonly ? "View step" : "Edit step";

  const menu = document.createElement("div");
  menu.className = "designer-step-context-menu";
  menu.setAttribute("role", "menu");
  menu.setAttribute("aria-label", `Actions for ${step.name || "selected step"}`);
  menu.innerHTML = `
    <div class="designer-step-context-head">
      <strong>${escapeHtml(index + 1)} / ${escapeHtml(wf.steps.length)}</strong>
      <span title="${escapeAttr(step.name || "Selected step")}">${escapeHtml(step.name || "Selected step")}</span>
    </div>
    <button type="button" role="menuitem" data-designer-action="open-step-editor" data-step-id="${escapeHtml(step.id)}">
      <span aria-hidden="true">✎</span><span>${escapeHtml(editLabel)}</span>
    </button>
    <button type="button" role="menuitem" data-designer-action="move-step-up" data-step-id="${escapeHtml(step.id)}" ${moveUpDisabled}>
      <span aria-hidden="true">↑</span><span>Move Up</span>
    </button>
    <button type="button" role="menuitem" data-designer-action="move-step-down" data-step-id="${escapeHtml(step.id)}" ${moveDownDisabled}>
      <span aria-hidden="true">↓</span><span>Move Down</span>
    </button>
    <button type="button" role="menuitem" data-designer-action="duplicate-step" data-step-id="${escapeHtml(step.id)}" ${readonly ? "disabled" : ""}>
      <span aria-hidden="true">⧉</span><span>Duplicate</span>
    </button>
    <button type="button" role="menuitem" class="designer-context-danger" data-designer-action="delete-step" data-step-id="${escapeHtml(step.id)}" ${readonly ? "disabled" : ""}>
      <span aria-hidden="true">×</span><span>Delete</span>
    </button>
  `;
  document.body.appendChild(menu);
  positionStepContextMenu(menu, x, y);
  stepContextMenuOpen = true;
}

function positionStepContextMenu(menu, x, y) {
  const margin = 10;
  const rect = menu.getBoundingClientRect();
  const left = Math.min(Math.max(margin, x), Math.max(margin, window.innerWidth - rect.width - margin));
  const top = Math.min(Math.max(margin, y), Math.max(margin, window.innerHeight - rect.height - margin));
  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;
}

function closeStepContextMenu() {
  const menus = document.querySelectorAll(".designer-step-context-menu");
  if (!menus.length && !stepContextMenuOpen) return;
  menus.forEach((node) => node.remove());
  stepContextMenuOpen = false;
}

function getVisibleSteps(wf) {
  const typeFilter = state.stepTypeFilter || "all";
  const term = normalizeStepFilter(state.stepFilter);
  return wf.steps
    .map((step, index) => ({ step, index }))
    .filter(({ step }) => {
      if (typeFilter !== "all" && step.type !== typeFilter) return false;
      if (!term) return true;
      return stepSearchText(step).includes(term);
    });
}

function normalizeStepFilter(value) {
  return String(value || "").trim().toLowerCase();
}

function stepSearchText(step) {
  return [
    step.name,
    step.key,
    step.type,
    formatStepType(step.type),
    step.description,
    step.command,
    step.templatePath,
    step.filename,
    step.validator,
    step.reviewMode,
    step.aggregatorFunction,
    ...(step.expectedFiles || []),
    ...(step.sources || []).map((source) => `${source.type} ${source.value}`),
  ].filter(Boolean).join(" ").toLowerCase();
}

function syncStepFilterControls() {
  const search = el("designerStepSearch");
  if (search && search.value !== state.stepFilter) search.value = state.stepFilter;
  const type = el("designerStepTypeFilter");
  if (type && type.value !== state.stepTypeFilter) type.value = state.stepTypeFilter;
  document.querySelectorAll("[data-designer-action='set-step-density']").forEach((button) => {
    button.classList.toggle("active", button.dataset.density === state.stepDensity);
  });
}

function updateStepFilter(input) {
  const field = input.dataset.stepFilterField;
  if (field === "search") state.stepFilter = input.value || "";
  if (field === "type") state.stepTypeFilter = input.value || "all";
  saveUiState();
  renderWorkflowViewOnly();
}

function clearStepFilter() {
  state.stepFilter = "";
  state.stepTypeFilter = "all";
  saveUiState();
  renderWorkflowViewOnly();
}

function setStepDensity(density) {
  if (!["dense", "compact", "detail"].includes(density)) return;
  state.stepDensity = density;
  saveUiState();
  renderWorkflowViewOnly();
}

function toggleStepActionMenu() {
  state.stepActionMenuExpanded = !state.stepActionMenuExpanded;
  saveUiState();
  renderWorkflowViewOnly();
}

function clearStepDropTargets() {
  document.querySelectorAll(".designer-step-card.drag-over-top, .designer-step-card.drag-over-bottom, .designer-step-card.dragging").forEach((node) => {
    node.classList.remove("drag-over-top", "drag-over-bottom", "dragging");
  });
}

function isStepGridLayout(card) {
  const list = card?.closest?.(".designer-step-list");
  if (!list?.classList?.contains("designer-step-density-dense")) return false;
  const columnCount = getComputedStyle(list).gridTemplateColumns.split(" ").filter(Boolean).length;
  return columnCount > 1;
}

function isDropBefore(event, card) {
  const rect = card.getBoundingClientRect();
  if (isStepGridLayout(card)) {
    return event.clientX < rect.left + rect.width / 2;
  }
  return event.clientY < rect.top + rect.height / 2;
}

function handleStepDragStart(event) {
  const card = event.target.closest(".designer-step-card[data-step-id]");
  if (!card || isReadonly()) return;
  draggedStepId = card.dataset.stepId;
  card.classList.add("dragging");
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", draggedStepId);
  }
}

function handleStepDragOver(event) {
  if (!draggedStepId || isReadonly()) return;
  const card = event.target.closest(".designer-step-card[data-step-id]");
  if (!card || card.dataset.stepId === draggedStepId) return;
  event.preventDefault();
  clearStepDropTargets();
  card.classList.add(isDropBefore(event, card) ? "drag-over-top" : "drag-over-bottom");
}

function handleStepDragLeave(event) {
  const card = event.target.closest(".designer-step-card[data-step-id]");
  if (!card || card.contains(event.relatedTarget)) return;
  card.classList.remove("drag-over-top", "drag-over-bottom");
}

function handleStepDrop(event) {
  if (!draggedStepId || isReadonly()) return;
  const targetCard = event.target.closest(".designer-step-card[data-step-id]");
  if (!targetCard || targetCard.dataset.stepId === draggedStepId) return;
  event.preventDefault();

  const wf = getSelectedWorkflow();
  if (!wf) return;
  const fromIndex = wf.steps.findIndex((item) => item.id === draggedStepId);
  const targetIndex = wf.steps.findIndex((item) => item.id === targetCard.dataset.stepId);
  if (fromIndex < 0 || targetIndex < 0) return;

  let insertIndex = isDropBefore(event, targetCard) ? targetIndex : targetIndex + 1;
  const [step] = wf.steps.splice(fromIndex, 1);
  if (fromIndex < insertIndex) insertIndex -= 1;
  wf.steps.splice(insertIndex, 0, step);
  state.selectedStepId = step.id;
  draggedStepId = null;
  clearStepDropTargets();
  markWorkflowDirty();
  renderWorkflowViewOnly();
  renderTabs();
  renderSettings();
  renderStepEditorModal();
  toast("Step reordered. Save Draft to keep it.");
}

function handleStepDragEnd() {
  draggedStepId = null;
  clearStepDropTargets();
}


function renderWorkflowEditor() {
  const wf = getSelectedWorkflow();
  if (!wf) return;
  setText("designerStepCount", `${wf.steps.length} steps`);
}

function renderWorkflowViewOnly() {
  renderStepList();
  renderCanvas();
  const step = getSelectedStep();
  setText("designerSelectedStepTitle", step ? step.name : "Step Settings");
  setText("designerSelectedStepType", step ? formatStepType(step.type) : "Select a step");
  renderStepEditorHeader();
}

function renderJsonPanel() {
  document.querySelectorAll("[data-designer-action='set-designer-mode']").forEach((button) => {
    button.classList.toggle("active", button.dataset.mode === (state.designerMode || "simple"));
  });
  const panel = el("designerJsonPanel");
  const editor = el("designerJsonEditor");
  const grid = document.querySelector(".designer-grid");
  const isJson = state.designerMode === "json";
  if (grid) grid.hidden = isJson;
  if (panel) panel.hidden = !isJson;
  if (!isJson || !editor) return;
  const wf = getSelectedWorkflow();
  const nextValue = JSON.stringify(wf || {}, null, 2);
  if (document.activeElement !== editor && editor.value !== nextValue) editor.value = nextValue;
  editor.disabled = isReadonly();
}

function renderStepList() {
  const wf = getSelectedWorkflow();
  const list = el("designerStepList");
  if (!wf || !list) return;
  const readonly = isReadonly();
  syncStepFilterControls();

  if (!wf.steps.length) {
    setText("designerStepCount", "0 steps");
    list.innerHTML = `<div class="designer-empty-state">No steps yet. Add a step to start designing.</div>`;
    return;
  }

  const visibleSteps = getVisibleSteps(wf);
  setText(
    "designerStepCount",
    visibleSteps.length === wf.steps.length
      ? `${wf.steps.length} steps`
      : `${visibleSteps.length} / ${wf.steps.length} steps`
  );

  if (!visibleSteps.length) {
    list.innerHTML = `
      <div class="designer-empty-state designer-filter-empty">
        <strong>No matching steps</strong>
        <span>Try another keyword or type filter.</span>
        <button type="button" data-designer-action="clear-step-filter">Clear Filter</button>
      </div>
    `;
    return;
  }

  list.classList.toggle("designer-step-density-dense", state.stepDensity === "dense");
  list.classList.toggle("designer-step-density-compact", state.stepDensity === "compact");
  list.classList.toggle("designer-step-density-detail", state.stepDensity === "detail");

  list.innerHTML = visibleSteps.map(({ step, index }) => {
    const disabled = readonly ? "disabled" : "";
    const badges = [
      step.timeoutEnabled ? `<span class="badge running">${step.timeoutMinutes || 0}m</span>` : "",
      step.pauseAfterStep ? `<span class="badge waiting_input">human</span>` : "",
      step.validator ? `<span class="badge passed">${escapeHtml(functionMeta("validators", step.validator)?.label || step.validator)}</span>` : "",
      step.reviewMode !== "none" ? `<span class="badge passed">${escapeHtml(formatReviewMode(step.reviewMode))}</span>` : "",
    ].filter(Boolean).join("");
    const detailItems = [
      ["Key", step.key || "-"],
      ["Template", step.templatePath || "-"],
      ["File", step.filename || normalizeFilename(step.outputFile || "-")],
      ["Retry", `${step.maxRetries ?? 0}${step.retryFromStepKey ? ` → ${step.retryFromStepKey}` : ""}`],
      ["Agent", step.agent || step.provider || "default"],
      ["Expected", (step.expectedFiles || []).length ? step.expectedFiles.join(", ") : "-"],
    ];

    return `
      <article class="designer-step-card designer-step-card-compact designer-step-card-${escapeHtml(state.stepDensity)} ${escapeHtml(step.type)}-card ${step.id === state.selectedStepId ? "active" : ""} ${step.enabled ? "" : "disabled-step"}" data-step-id="${escapeHtml(step.id)}" draggable="${readonly ? "false" : "true"}" tabindex="0" title="Click to select. Double-click to edit ${escapeHtml(step.name)}">
        <span class="designer-step-card-main">
          <span class="designer-step-primary">
            <span class="designer-step-index">${index + 1}</span>
            <span class="designer-step-card-title">
              <strong>${escapeHtml(step.name)}</strong>
            </span>
            <span class="designer-step-type ${escapeHtml(step.type)}">${escapeHtml(formatStepType(step.type))}</span>
          </span>
          <button type="button" class="designer-step-card-menu" data-designer-action="open-step-context-menu" data-step-id="${escapeHtml(step.id)}" title="Step actions" aria-label="Step actions for ${escapeAttr(step.name || "step")}">⋯</button>
        </span>
        <span class="designer-step-card-sub">
          <span class="designer-step-summary">${escapeHtml(summarizeStep(step))}</span>
          ${badges ? `<span class="designer-chip-row designer-step-badges">${badges}</span>` : ""}
        </span>
        ${state.stepDensity === "detail" ? `
          <dl class="designer-step-detail-grid">
            ${detailItems.map(([label, value]) => `
              <div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(String(value))}</dd></div>
            `).join("")}
          </dl>
        ` : ""}
      </article>
    `;
  }).join("") + renderStepFloatingActions(wf);
}

function renderCanvas() {
  const wf = getSelectedWorkflow();
  const canvas = el("designerCanvas");
  if (!wf || !canvas) return;

  if (!wf.steps.length) {
    canvas.innerHTML = `<div class="designer-empty-state">Flow preview will appear here.</div>`;
    return;
  }

  canvas.innerHTML = wf.steps.map((step, index) => `
    <article class="designer-flow-node ${step.id === state.selectedStepId ? "active" : ""}" data-step-id="${escapeHtml(step.id)}">
      <div class="designer-step-card-title">
        <h4>${index + 1}. ${escapeHtml(step.name)}</h4>
        <span class="designer-step-type ${escapeHtml(step.type)}">${escapeHtml(formatStepType(step.type))}</span>
      </div>
      <p>${escapeHtml(step.description || summarizeStep(step))}</p>
      <div class="designer-chip-row" style="margin-top: 8px;">
        ${step.enabled ? `<span class="badge passed">enabled</span>` : `<span class="badge cancelled">disabled</span>`}
        <span class="badge">retry ${step.maxRetries}${step.retryFromStepKey ? ` → ${escapeHtml(step.retryFromStepKey)}` : ""}</span>
        ${step.agent || step.provider ? `<span class="badge">agent ${escapeHtml(step.agent || step.provider)}</span>` : ""}
        ${step.allowInteraction ? `<span class="badge waiting_input">interaction</span>` : `<span class="badge">auto</span>`}
        ${step.pauseAfterStep ? `<span class="badge running">pause</span>` : ""}
      </div>
    </article>
  `).join("");
}

function renderTabs() {
  const step = getSelectedStep();
  const validTabs = new Set(tabsForStep(step, stepUiCapabilities(step)));
  document.querySelectorAll(".designer-tab").forEach((tab) => {
    tab.hidden = false;
    tab.classList.toggle("irrelevant", !validTabs.has(tab.dataset.designerTab));
    tab.classList.toggle("active", tab.dataset.designerTab === state.activeTab);
  });
}

function ensureActiveTabForStep(step) {
  ensureStepTab(state, step, stepUiCapabilities(step));
}

function applyStepTypeDefaults(step) {
  if (!step) return;
  if (step.type === "validation") {
    step.validator = step.validator || "validate_spec";
    step.reviewMode = "none";
    step.command = "";
    step.pauseAfterStep = false;
    step.approvalRequired = false;
  }
  if (step.type === "python") {
    step.validator = step.validator || "run_pytest";
    step.reviewMode = "none";
    step.command = "";
  }
  if (step.type === "review") {
    step.agent = step.agent || step.provider || "qwen";
    step.provider = step.provider || step.agent || "qwen";
    step.reviewMode = step.reviewMode === "none" ? "current_session" : step.reviewMode;
    step.aggregatorFunction = step.aggregatorFunction || "keyword_confidence";
  }
  if (step.type === "gate" || step.type === "manual") {
    step.pauseAfterStep = true;
    step.approvalRequired = true;
    step.reviewMode = "none";
    step.command = "";
  }
  if (step.type === "ai") {
    step.agent = step.agent || step.provider || "qwen";
    step.provider = step.provider || step.agent || "qwen";
    step.validator = "";
    step.reviewMode = "none";
    step.command = step.command || "";
  }
  if (step.type === "command") {
    step.agent = step.agent || step.provider || "qwen";
    step.provider = step.provider || step.agent || "qwen";
    step.validator = "";
    step.reviewMode = "none";
    step.command = step.command || "custom";
  }
}


  function isStepContextMenuOpen() {
    return stepContextMenuOpen;
  }

  return {
    applyStepTypeDefaults,
    clearStepDropTargets,
    clearStepFilter,
    closeStepContextMenu,
    getVisibleSteps,
    handleStepDragEnd,
    handleStepDragLeave,
    handleStepDragOver,
    handleStepDragStart,
    handleStepDrop,
    ensureActiveTabForStep,
    isStepContextMenuOpen,
    openStepContextMenu,
    render,
    renderTabs,
    renderWorkflowLabels,
    renderWorkflowViewOnly,
    setStepDensity,
    syncStepFilterControls,
    toggleStepActionMenu,
    updateStepFilter,
  };
}
