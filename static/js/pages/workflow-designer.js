import {
  BuiltInPromptParams,
  FailActions,
  ReviewModes,
  SourceTypes,
  StepTypes,
  TemplatePresets,
} from "./workflow-designer-constants.js?v=20260628-designer-desc1";

const STORAGE_KEY = "qwenWorkflow.workflowDesigner.ui.v1";
const WORKFLOW_API = "/api/workflows";

function functionOptions(groupName, fallbackItems, selected) {
  const items = availableWorkflowFunctions[groupName] || [];
  if (!items.length) return options(fallbackItems, selected);
  const normalized = items.map((item) => [item.id, item.label || item.id]);
  if (selected && !normalized.some(([value]) => String(value) === String(selected))) {
    normalized.unshift([selected, `${selected} (custom)`]);
  }
  return options(groupName === "validators" || groupName === "aggregators" ? [["", "None"], ...normalized] : normalized, selected);
}

function functionMeta(groupName, selected) {
  const items = availableWorkflowFunctions[groupName] || [];
  return items.find((item) => String(item.id) === String(selected)) || null;
}

function functionHelp(groupName, selected, emptyText = "Select a backend function.") {
  const meta = functionMeta(groupName, selected);
  if (!selected) {
    return `<div class="designer-function-help"><strong>No function selected</strong><span>${escapeHtml(emptyText)}</span></div>`;
  }
  if (!meta) {
    return `<div class="designer-function-help"><strong>${escapeHtml(selected)}</strong><span>Custom function id. Make sure the backend knows how to execute it.</span></div>`;
  }
  return `
    <div class="designer-function-help">
      <strong>${escapeHtml(meta.label || meta.id)}</strong>
      <span>${escapeHtml(meta.description || "No description provided by backend.")}</span>
    </div>
  `;
}

function workflowFunctionCounts() {
  return {
    validators: (availableWorkflowFunctions.validators || []).length,
    reviewStrategies: (availableWorkflowFunctions.reviewStrategies || []).length,
    aggregators: (availableWorkflowFunctions.aggregators || []).length,
    promptParams: availablePromptParams().length,
  };
}

function availablePromptParams() {
  const merged = [];
  const seen = new Set();
  const add = (param) => {
    const key = String(param?.key || param?.id || "").trim();
    if (!key || seen.has(key)) return;
    seen.add(key);
    merged.push({
      key,
      label: param.label || key,
      description: param.description || "Provided by backend runtime context.",
      sample: param.sample ?? param.example ?? `[${key}]`,
    });
  };
  BuiltInPromptParams.forEach(add);
  (availableWorkflowFunctions.promptParams || []).forEach(add);
  return merged;
}

let systemWorkflow = Object.freeze({
  id: "system-controlled-qwen",
  kind: "system",
  name: "Controlled Qwen Workflow",
  description: "Built-in workflow loaded from backend configuration.",
  active: true,
  skillRoot: "",
  promptRoot: "prompts/",
  steps: [],
});

let state = {
  workflows: [],
  selectedWorkflowId: systemWorkflow.id,
  selectedStepId: null,
  activeTab: "basic",
  stepFilter: "",
  stepTypeFilter: "all",
  stepDensity: "compact",
  stepActionMenuExpanded: false,
  apiLoaded: false,
  apiError: "",
};

let templateEditorDraft = null;
let templateEditorOriginal = null;
let importWorkflowDraft = null;
let stepEditorModalOpen = false;
let draggedStepId = null;
let stepContextMenuOpen = false;
let workflowDirty = false;
let pendingWorkflowAction = null;
let availableWorkflowFunctions = { validators: [], reviewStrategies: [], aggregators: [], promptParams: [] };

function createStep(overrides = {}) {
  const id = overrides.id || makeId("step");
  return {
    id,
    name: overrides.name || "New Step",
    key: overrides.key || id.replace(/^step-/, "step_"),
    type: overrides.type || "ai",
    enabled: overrides.enabled ?? true,
    description: overrides.description || "",
    command: overrides.command || "",
    templatePath: overrides.templatePath || defaultTemplatePath(overrides),
    filename: overrides.filename || defaultFilename(overrides),
    outputFile: overrides.outputFile || "", // backward compatibility for older localStorage drafts
    agent: overrides.agent || overrides.provider || "qwen",
    provider: overrides.provider || overrides.agent || "qwen",
    templateContent: overrides.templateContent || defaultTemplateContent(overrides),
    sources: clone(overrides.sources || []),
    reviewMode: overrides.reviewMode || "none",
    reviewers: clone(overrides.reviewers || []),
    confidenceThreshold: overrides.confidenceThreshold ?? 0.75,
    passKeywords: overrides.passKeywords || "PASS, APPROVED",
    failKeywords: overrides.failKeywords || "FAIL, BLOCKED",
    aggregatorFunction: overrides.aggregatorFunction || "",
    maxRetries: overrides.maxRetries ?? 2,
    failAction: overrides.failAction || "same_step",
    retryFromStepKey: overrides.retryFromStepKey || "",
    keepSameSession: overrides.keepSameSession ?? true,
    injectFailureFeedback: overrides.injectFailureFeedback ?? true,
    stopAfterFailures: overrides.stopAfterFailures ?? 3,
    pauseAfterStep: overrides.pauseAfterStep ?? false,
    approvalRequired: overrides.approvalRequired ?? false,
    approvalMessage: overrides.approvalMessage || "",
    timeoutEnabled: overrides.timeoutEnabled ?? false,
    timeoutMinutes: overrides.timeoutMinutes ?? 0,
    allowInteraction: overrides.allowInteraction ?? true,
    expectedFiles: clone(overrides.expectedFiles || []),
    validator: overrides.validator || "",
  };
}

function createWorkflow(overrides = {}) {
  const id = overrides.id || makeId("workflow");
  return {
    id,
    kind: "custom",
    name: overrides.name || "Untitled Workflow",
    description: overrides.description || "Custom workflow draft.",
    active: overrides.active ?? false,
    skillRoot: overrides.skillRoot || "skills/",
    promptRoot: overrides.promptRoot || "prompts/",
    steps: clone(overrides.steps || [
      createStep({ name: "Generate", key: "generate", type: "ai", command: "/spec", templatePath: "prompts/new_step.md", filename: "result.md", sources: [{ type: "command", value: "/spec" }] }),
      createStep({ name: "Validate", key: "validate", type: "validation", validator: "functions/validate.py" }),
      createStep({ name: "Review", key: "review", type: "review", reviewMode: "current_session" }),
    ]),
  };
}

async function initWorkflowDesignerPage() {
  await loadState();
  bindEvents();
  render();
}

async function loadState() {
  const saved = readStorage();
  let payload = null;
  try {
    payload = await designerApi(WORKFLOW_API);
    state.apiLoaded = true;
    state.apiError = "";
  } catch (error) {
    state.apiLoaded = false;
    state.apiError = error.message;
    toast(`Could not load workflows from API: ${error.message}`);
  }
  if (payload?.system) {
    systemWorkflow = Object.freeze(normalizeWorkflow(payload.system));
  }
  availableWorkflowFunctions = payload?.functions || availableWorkflowFunctions;
  state.workflows = Array.isArray(payload?.custom) ? payload.custom.map(normalizeWorkflow) : [];
  if (!state.workflows.length) {
    state.workflows = [];
  }
  state.selectedWorkflowId = saved.selectedWorkflowId || state.workflows[0]?.id || systemWorkflow.id;
  const selected = getSelectedWorkflow();
  state.selectedStepId = saved.selectedStepId || selected?.steps?.[0]?.id || null;
  state.activeTab = saved.activeTab || "basic";
  state.stepFilter = saved.stepFilter || "";
  state.stepTypeFilter = saved.stepTypeFilter || "all";
  state.stepDensity = ["dense", "compact", "detail"].includes(saved.stepDensity) ? saved.stepDensity : "compact";
  state.stepActionMenuExpanded = Boolean(saved.stepActionMenuExpanded);
  workflowDirty = false;
}

function bindEvents() {
  on("designerSystemWorkflow", "click", () => selectWorkflow(systemWorkflow.id));
  on("designerViewSystem", "click", () => selectWorkflow(systemWorkflow.id));
  on("designerDuplicateWorkflow", "click", () => guardedWorkflowAction(() => {
    const copy = duplicateSystemWorkflow("Custom Controlled Workflow");
    state.workflows.unshift(copy);
    doSelectWorkflow(copy.id, copy.steps[0]?.id);
    markWorkflowDirty();
    render();
    toast("System workflow duplicated. Save Draft when you are ready.");
  }));
  on("designerNewWorkflow", "click", createNewWorkflow);
  on("designerNewWorkflowMini", "click", createNewWorkflow);
  on("designerAddStep", "click", addStep);
  on("designerSaveDraft", "click", () => {
    saveState().then(() => toast("Workflow saved to API."));
  });
  on("designerResetDraft", "click", () => {
    const wf = getSelectedWorkflow();
    if (!wf || isReadonly()) return toast("System workflow is read-only.");
    const fresh = createWorkflow({ name: wf.name, description: wf.description });
    Object.assign(wf, fresh, { id: wf.id, name: wf.name });
    state.selectedStepId = wf.steps[0]?.id || null;
    markWorkflowDirty();
    render();
    toast("Current workflow reset. Save Draft to keep it.");
  });
  on("designerImportWorkflow", "click", openImportWorkflow);
  on("designerDuplicateCustomWorkflow", "click", duplicateCurrentWorkflow);
  on("designerExportWorkflow", "click", exportWorkflow);
  on("designerDeleteWorkflow", "click", () => deleteWorkflow(state.selectedWorkflowId));

  const nameInput = el("workflowNameInput");
  if (nameInput) {
    nameInput.addEventListener("input", () => {
      const wf = getSelectedWorkflow();
      if (!wf || isReadonly()) return;
      wf.name = nameInput.value;
      markWorkflowDirty();
      renderWorkflowLabels();
    });
  }

  const descriptionInput = el("workflowDescriptionInput");
  if (descriptionInput) {
    descriptionInput.addEventListener("input", () => {
      const wf = getSelectedWorkflow();
      if (!wf || isReadonly()) return;
      wf.description = descriptionInput.value;
      markWorkflowDirty();
      renderWorkflowLabels();
    });
  }

  document.addEventListener("click", handleDocumentClick);
  document.addEventListener("contextmenu", handleDocumentContextMenu);
  document.addEventListener("input", handleDocumentInput);
  document.addEventListener("change", handleDocumentChange);
  document.addEventListener("keydown", handleDocumentKeydown);
  document.addEventListener("dragstart", handleStepDragStart);
  document.addEventListener("dragover", handleStepDragOver);
  document.addEventListener("dragleave", handleStepDragLeave);
  document.addEventListener("drop", handleStepDrop);
  document.addEventListener("dragend", handleStepDragEnd);
  window.addEventListener("beforeunload", handleBeforeUnload);
}

function handleBeforeUnload(event) {
  if (!isTemplateDraftDirty() && !isWorkflowDirty()) return;
  event.preventDefault();
  event.returnValue = "";
}

function handleDocumentKeydown(event) {
  if (document.querySelector(".designer-confirm-box, .designer-template-modal-box, .designer-preview-box")) return;

  if (stepEditorModalOpen && event.altKey && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
    event.preventDefault();
    switchStepEditor(event.key === "ArrowLeft" ? -1 : 1);
    return;
  }

  if (event.key !== "Escape") return;
  if (stepContextMenuOpen) {
    closeStepContextMenu();
    return;
  }
  if (stepEditorModalOpen) {
    closeStepEditor();
  }
}

const DesignerActionHandlers = Object.freeze({
  "delete-workflow": (action) => deleteWorkflow(action.dataset.workflowId),
  "confirm-delete-workflow": (action) => performDeleteWorkflow(action.dataset.workflowId),
  "delete-step": (action) => deleteStep(action.dataset.stepId),
  "confirm-delete-step": (action) => performDeleteStep(action.dataset.stepId),
  "duplicate-step": (action) => duplicateStep(action.dataset.stepId),
  "move-step-up": (action) => moveStep(action.dataset.stepId, -1),
  "move-step-down": (action) => moveStep(action.dataset.stepId, 1),
  "set-step-density": (action) => setStepDensity(action.dataset.density),
  "toggle-step-actions": () => toggleStepActionMenu(),
  "clear-step-filter": () => clearStepFilter(),
  "open-step-editor": (action) => openStepEditor(action.dataset.stepId),
  "step-editor-prev": () => switchStepEditor(-1),
  "step-editor-next": () => switchStepEditor(1),
  "close-step-editor": () => closeStepEditor(),
  "open-template-editor": () => openTemplateEditor(),
  "save-template-editor": () => saveTemplateEditor(),
  "close-template-editor": () => requestCloseTemplateEditor(),
  "confirm-close-template-editor": () => closeTemplateEditor({ force: true }),
  "confirm-load-template-preset": (action) => performLoadSelectedTemplatePreset(action.dataset.templatePath || ""),
  "insert-param": (action) => insertTemplateParam(action.dataset.param),
  "load-template-preset": () => loadSelectedTemplatePreset(),
  "preview-prompt": () => openPromptPreview(),
  "close-preview": () => closePromptPreview(),
  "add-source": () => addSource(),
  "remove-source": (action) => removeArrayItem("sources", Number(action.dataset.index)),
  "add-reviewer": () => addReviewer(),
  "remove-reviewer": (action) => removeArrayItem("reviewers", Number(action.dataset.index)),
  "add-expected-file": () => addExpectedFile(),
  "remove-expected-file": (action) => removeArrayItem("expectedFiles", Number(action.dataset.index)),
  "open-import": () => openImportWorkflow(),
  "validate-import": () => validateImportWorkflowFromUi(),
  "perform-import": () => performImportWorkflow(),
  "close-import": () => closeImportWorkflow(),
  "close-export": () => closeExport(),
  "confirm-discard-workflow-changes": () => confirmDiscardWorkflowChanges(),
  "close-confirm": () => closeConfirm(),
});

function dispatchDesignerAction(action) {
  const handler = DesignerActionHandlers[action.dataset.designerAction];
  if (!handler) return false;
  handler(action);
  return true;
}

function handleDocumentClick(event) {
  const navLink = event.target.closest("a.designer-nav-link");
  if (navLink && isWorkflowDirty()) {
    event.preventDefault();
    guardedWorkflowAction(() => { window.location.href = navLink.href; });
    return;
  }

  const tab = event.target.closest("[data-designer-tab]");
  if (tab) {
    if (tab.hidden) return;
    state.activeTab = tab.dataset.designerTab;
    saveUiState();
    renderSettings();
    renderTabs();
    return;
  }

  // Action buttons may also contain data-step-id, so handle actions before
  // generic step selection. Otherwise Move Up / Duplicate / Delete only selects
  // the step and never executes the intended action.
  const action = event.target.closest("[data-designer-action]");
  if (action) {
    const name = action.dataset.designerAction;
    if (name === "open-step-context-menu") {
      event.preventDefault();
      openStepContextMenu(action.dataset.stepId, { anchor: action });
      return;
    }
    closeStepContextMenu();
    dispatchDesignerAction(action);
    return;
  }

  if (!event.target.closest(".designer-step-context-menu")) {
    closeStepContextMenu();
  }

  const workflowButton = event.target.closest("[data-workflow-id]");
  if (workflowButton) {
    selectWorkflow(workflowButton.dataset.workflowId);
    return;
  }

  const stepButton = event.target.closest(".designer-step-card[data-step-id]");
  if (stepButton) {
    selectStep(stepButton.dataset.stepId, { openModal: event.detail >= 2 });
  }
}

function handleDocumentContextMenu(event) {
  const stepCard = event.target.closest(".designer-step-card[data-step-id]");
  if (!stepCard) {
    closeStepContextMenu();
    return;
  }

  event.preventDefault();
  openStepContextMenu(stepCard.dataset.stepId, { x: event.clientX, y: event.clientY });
}

function handleDocumentInput(event) {
  const filterInput = event.target.closest("[data-step-filter-field]");
  if (filterInput) {
    updateStepFilter(filterInput);
    return;
  }

  const draftInput = event.target.closest("[data-template-draft-field]");
  if (draftInput) {
    updateTemplateDraft(draftInput);
    return;
  }
  const input = event.target.closest("[data-step-field], [data-workflow-field], [data-array-field]");
  if (!input) return;
  updateFromInput(input);
}

function handleDocumentChange(event) {
  const filterInput = event.target.closest("[data-step-filter-field]");
  if (filterInput) {
    updateStepFilter(filterInput);
    return;
  }

  const importFile = event.target.closest("#designerImportFile");
  if (importFile) {
    readImportFile(importFile);
    return;
  }

  const draftInput = event.target.closest("[data-template-draft-field]");
  if (draftInput) {
    updateTemplateDraft(draftInput);
    return;
  }
  const input = event.target.closest("[data-step-field], [data-workflow-field], [data-array-field]");
  if (!input) return;
  updateFromInput(input);
}

function updateFromInput(input) {
  if (isReadonly()) {
    renderSettings();
    return;
  }

  const wf = getSelectedWorkflow();
  const step = getSelectedStep();
  const value = readInputValue(input);

  if (input.dataset.workflowField && wf) {
    wf[input.dataset.workflowField] = value;
    markWorkflowDirty();
    renderWorkflowLabels();
    renderSettings();
    return;
  }

  if (input.dataset.stepField && step) {
    step[input.dataset.stepField] = value;
    if (input.dataset.stepField === "type") {
      applyStepTypeDefaults(step);
      renderWorkflowViewOnly();
      renderSettings();
      renderTabs();
    }
    if (input.dataset.stepField === "templateContent") {
      renderPromptDiagnostics(step);
    }
    if (["name", "templatePath", "filename", "outputFile", "validator", "reviewMode", "aggregatorFunction", "agent", "provider", "maxRetries", "failAction", "retryFromStepKey", "keepSameSession", "injectFailureFeedback", "timeoutEnabled", "timeoutMinutes"].includes(input.dataset.stepField)) renderWorkflowViewOnly();
    renderStepEditorHeader();
    markWorkflowDirty();
    return;
  }

  if (input.dataset.arrayField && step) {
    const collection = input.dataset.arrayCollection;
    const index = Number(input.dataset.index);
    const field = input.dataset.arrayField;
    if (!Array.isArray(step[collection]) || !step[collection][index]) return;
    if (typeof step[collection][index] === "string") {
      step[collection][index] = value;
    } else {
      step[collection][index][field] = value;
    }
    markWorkflowDirty();
    renderWorkflowViewOnly();
  }
}

function render() {
  renderSidebar();
  renderBackendStatus();
  renderWorkflowLabels();
  renderWorkflowDirtyState();
  renderWorkflowEditor();
  renderWorkflowViewOnly();
  renderTabs();
  renderSettings();
  renderStepEditorModal();
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

  el("designerSystemWorkflow")?.classList.toggle("active", state.selectedWorkflowId === systemWorkflow.id);
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
  const promptRootInput = el("workflowPromptRootInput");
  if (promptRootInput && promptRootInput.value !== (wf.promptRoot || "")) promptRootInput.value = wf.promptRoot || "";
  if (promptRootInput) promptRootInput.disabled = readonly;
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
        <span aria-hidden="true">${expanded ? "×" : "⋯"}</span>
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
          <button type="button" class="designer-step-card-menu" data-designer-action="open-step-context-menu" data-step-id="${escapeHtml(step.id)}" title="Step actions" aria-label="Step actions for ${escapeAttr(step.name || "step")}">⋮</button>
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
  const validTabs = new Set(tabsForStep(step));
  document.querySelectorAll(".designer-tab").forEach((tab) => {
    tab.hidden = false;
    tab.classList.toggle("irrelevant", !validTabs.has(tab.dataset.designerTab));
    tab.classList.toggle("active", tab.dataset.designerTab === state.activeTab);
  });
}

function tabsForStep(step) {
  if (!step) return ["basic"];
  const byType = {
    ai: ["basic", "sources", "retry", "advanced"],
    command: ["basic", "sources", "retry", "advanced"],
    validation: ["basic", "retry", "advanced"],
    python: ["basic", "retry", "advanced"],
    review: ["basic", "review", "retry", "advanced"],
    gate: ["basic", "gate", "retry", "advanced"],
    manual: ["basic", "gate", "retry", "advanced"],
  };
  return byType[step.type] || ["basic", "advanced"];
}

function ensureActiveTabForStep(step) {
  const tabs = tabsForStep(step);
  if (!tabs.includes(state.activeTab)) state.activeTab = tabs[0] || "basic";
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
    step.validator = "";
    step.reviewMode = "none";
    step.command = step.command || "";
  }
  if (step.type === "command") {
    step.validator = "";
    step.reviewMode = "none";
    step.command = step.command || "custom";
  }
}

function renderSettings() {
  const target = el("designerStepSettingsModal") || el("designerStepSettings");
  const step = getSelectedStep();
  if (!target) return;
  if (!step) {
    target.innerHTML = `<div class="designer-empty-state">Select a step to edit its configuration.</div>`;
    return;
  }

  const readonly = isReadonly();
  const disabled = readonly ? "disabled" : "";
  const tab = state.activeTab;
  if (!tabsForStep(step).includes(tab)) {
    target.innerHTML = renderIrrelevantTab(step, tab);
    return;
  }

  if (tab === "basic") target.innerHTML = renderBasic(step, disabled, readonly);
  if (tab === "sources") target.innerHTML = renderSources(step, disabled, readonly);
  if (tab === "review") target.innerHTML = renderReview(step, disabled, readonly);
  if (tab === "retry") target.innerHTML = renderRetry(step, disabled, readonly);
  if (tab === "gate") target.innerHTML = renderGate(step, disabled, readonly);
  if (tab === "advanced") target.innerHTML = renderAdvanced(step, disabled, readonly);
}

function renderIrrelevantTab(step, tab) {
  const tabLabel = {
    sources: "Prompt",
    review: "Review",
    retry: "Retry",
    gate: "Gate",
    advanced: "Advanced",
    basic: "Basic",
  }[tab] || tab;
  return `
    <div class="designer-runner-note">
      <strong>${escapeHtml(tabLabel)} is not typical for ${escapeHtml(formatStepType(step.type))}</strong>
      <span>Use Basic for the main ${escapeHtml(formatStepType(step.type))} settings. The tabs stay visible so the layout does not jump while you move between steps.</span>
    </div>
  `;
}

function renderBasic(step, disabled, readonly) {
  return `
    <div class="designer-form-grid">
      ${readonly ? readonlyNotice() : ""}
      ${inputRow("Step Name", "name", step.name, disabled)}
      ${inputRow("Step Key", "key", step.key, disabled)}
      <label class="designer-form-row">
        <span class="designer-label">Step Type</span>
        <select class="designer-select" data-step-field="type" ${disabled}>
          ${options(StepTypes, step.type)}
        </select>
      </label>
      ${renderAgentConfig(step, disabled)}
      ${renderBasicTypeConfig(step, disabled)}
      ${textareaRow("Description", "description", step.description, disabled)}
      ${switchRow("Enabled", "Turn this step on/off without deleting it.", "enabled", step.enabled, disabled)}
      <div class="designer-runner-note">
        <strong>Step actions stay on the main screen</strong>
        <span>Use the floating action bar on the step list for Edit, Move, Duplicate, and Delete.</span>
      </div>
    </div>
  `;
}

function renderAgentConfig(step, disabled) {
  if (!["ai", "review", "command"].includes(step.type)) return "";
  return `
    <div class="designer-template-summary-grid compact">
      ${inputRow("Agent Provider", "agent", step.agent || step.provider || "qwen", disabled, "qwen / opencode")}
      ${inputRow("Provider Alias", "provider", step.provider || step.agent || "qwen", disabled, "optional")}
    </div>
  `;
}

function renderBasicTypeConfig(step, disabled) {
  if (step.type === "validation" || step.type === "python") {
    return `
      <label class="designer-form-row">
        <span class="designer-label">${step.type === "python" ? "Python Function" : "Validation Function"}</span>
        <select class="designer-select" data-step-field="validator" ${disabled}>
          ${functionOptions("validators", [["", "None"], ["validate_spec", "Validate Spec"], ["validate_todo", "Validate Todo"], ["run_pytest", "Run Pytest"]], step.validator)}
        </select>
      </label>
      ${functionHelp("validators", step.validator, "Choose the Python function this step should run.")}
      ${expectedFilesPreview(step)}
    `;
  }
  if (step.type === "review") {
    return `
      <label class="designer-form-row">
        <span class="designer-label">Review Strategy</span>
        <select class="designer-select" data-step-field="reviewMode" ${disabled}>
          ${functionOptions("reviewStrategies", ReviewModes, step.reviewMode)}
        </select>
      </label>
      ${functionHelp("reviewStrategies", step.reviewMode, "Choose how this review step should run.")}
    `;
  }
  if (step.type === "gate" || step.type === "manual") {
    return `
      <div class="designer-runner-note">
        <strong>Human gate</strong>
        <span>This step pauses the workflow and waits for a user decision before continuing.</span>
      </div>
    `;
  }
  if (step.type === "ai" || step.type === "command") {
    return `
      <div class="designer-runner-note">
        <strong>${step.type === "ai" ? "AI prompt step" : "Command step"}</strong>
        <span>Use the Prompt tab to choose slash commands, skills, prompt files, and output filename.</span>
      </div>
    `;
  }
  return "";
}

function expectedFilesPreview(step) {
  const files = Array.isArray(step.expectedFiles) ? step.expectedFiles.filter(Boolean) : [];
  return `
    <div class="designer-function-help">
      <strong>Expected files</strong>
      <span>${files.length ? files.map(escapeHtml).join(", ") : "No expected files configured."}</span>
    </div>
  `;
}

function isAbsoluteLikePath(value = "") {
  const text = String(value || "").trim();
  return /^[a-zA-Z]:[\\/]/.test(text) || text.startsWith("/") || text.startsWith("~/") || text.startsWith("\\\\");
}

function sourcePathSummary() {
  const wf = getSelectedWorkflow();
  const skillRoot = wf?.skillRoot || "~/.qwen/skills";
  return `Skill Path accepts absolute paths. Relative skill paths resolve from Skill Root (${skillRoot}), then Project Path. Prompt File resolves inside this workflow bundle.`;
}

function describeSourcePath(source = {}) {
  const type = String(source.type || "").trim();
  const value = String(source.value || "").trim();
  if (!value) return "No path/value set.";
  const wf = getSelectedWorkflow();
  if (type === "skill_path") {
    if (isAbsoluteLikePath(value)) return "Skill path: absolute path, used directly.";
    return `Skill path: relative to Skill Root (${wf?.skillRoot || "~/.qwen/skills"}), with Project Path fallback.`;
  }
  if (type === "prompt_file") {
    return "Prompt file: resolved inside this workflow folder, usually under prompts/.";
  }
  if (type === "context_file") {
    if (isAbsoluteLikePath(value)) return "Context file: absolute path, used directly when available.";
    return "Context file: checked under Project Path, workflow workspace, then app root.";
  }
  if (type === "artifact") {
    return "Artifact: checked under workflow output/ and workspace.";
  }
  if (type === "command") return "Command source: prepended as a slash command when configured.";
  if (type === "inline_prompt") return "Inline prompt: inserted as text context.";
  return "Source value passed to backend workflow context.";
}

function describeExpectedFilePath(value = "") {
  const text = String(value || "").trim();
  if (!text) return "No expected file path set.";
  const normalized = text.replace(/\\/g, "/");
  if (isAbsoluteLikePath(text)) return "Absolute path: checked exactly at this file location.";
  if (normalized.startsWith("output/")) return "Workflow output path: checked under this run workspace.";
  if (normalized.startsWith("input/") || normalized.startsWith("prompts/") || normalized.startsWith(".workflow/")) {
    return "Workflow workspace path: checked under this run workspace.";
  }
  return "Relative artifact: checked in output/, workspace, then Project Path.";
}

function renderSources(step, disabled, readonly) {
  const diagnostics = getTemplateDiagnostics(step);
  const unknown = diagnostics.unknown.length ? `
    <div class="designer-warning-box">
      <strong>Unknown params</strong>
      <span>${diagnostics.unknown.map((name) => `{{${escapeHtml(name)}}}`).join(", ")}</span>
    </div>
  ` : "";
  const filename = step.filename || normalizeFilename(step.outputFile || diagnostics.filename || "");
  return `
    <div class="designer-form-grid">
      ${readonly ? readonlyNotice() : ""}
      <label class="designer-form-row">
        <span class="designer-label">Command</span>
        <select class="designer-select" data-step-field="command" ${disabled}>
          ${options([["", "None"], ["/spec", "/spec"], ["/plan", "/plan"], ["/todo", "/todo"], ["/build", "/build"], ["custom", "Custom command"]], step.command)}
        </select>
      </label>

      <section class="designer-template-summary-card">
        <div class="designer-section-row">
          <div>
            <span class="designer-label">Prompt Template</span>
            <h4>${escapeHtml(step.templatePath || "No template file")}</h4>
          </div>
          <button data-designer-action="open-template-editor" ${disabled}>Edit Template</button>
        </div>
        <div class="designer-template-summary-grid compact">
          <div>
            <span class="designer-label">Filename</span>
            <div class="designer-form-hint">${escapeHtml(filename || "No filename set")}</div>
          </div>
          <div>
            <span class="designer-label">Template Size</span>
            <div class="designer-form-hint">${escapeHtml(String((step.templateContent || "").length))} chars</div>
          </div>
        </div>
        ${unknown}
        <div class="designer-template-excerpt">${escapeHtml((step.templateContent || "").slice(0, 520) || "No prompt content yet.")}</div>
        <div class="designer-form-hint">Backend creates a folder from the workflow name, then saves this step output using Filename.</div>
      </section>

      <div class="designer-list-editor">
        <div class="designer-section-row">
          <span class="designer-label">Extra Context Sources</span>
          <button class="mini-button" data-designer-action="add-source" ${disabled}>＋ Add Source</button>
        </div>
        ${step.sources.length ? step.sources.map((source, index) => `
          <div class="designer-source-row">
            <select class="designer-select" data-array-collection="sources" data-index="${index}" data-array-field="type" ${disabled}>
              ${options(SourceTypes, source.type)}
            </select>
            <input class="designer-input" value="${escapeAttr(source.value || "")}" data-array-collection="sources" data-index="${index}" data-array-field="value" ${disabled} />
            <button class="designer-danger" data-designer-action="remove-source" data-index="${index}" ${disabled}>×</button>
            <div class="designer-path-help">${escapeHtml(describeSourcePath(source))}</div>
          </div>
        `).join("") : `<div class="designer-empty-state">No extra sources. Template params are provided by backend runtime context.</div>`}
        <div class="designer-form-hint">${escapeHtml(sourcePathSummary())}</div>
      </div>
      <div class="designer-footer-actions">
        <button data-designer-action="preview-prompt">Preview Rendered Prompt</button>
      </div>
      <div class="designer-form-hint">Params are fixed by backend. Open the template editor, then click a param chip to insert {{param}} placeholders.</div>
    </div>
  `;
}

function renderReview(step, disabled, readonly) {
  return `
    <div class="designer-form-grid">
      ${readonly ? readonlyNotice() : ""}
      <label class="designer-form-row">
        <span class="designer-label">Review Strategy</span>
        <select class="designer-select" data-step-field="reviewMode" ${disabled}>
          ${functionOptions("reviewStrategies", ReviewModes, step.reviewMode)}
        </select>
      </label>
      <div class="designer-list-editor">
        <div class="designer-section-row">
          <span class="designer-label">Review Agents</span>
          <button class="mini-button" data-designer-action="add-reviewer" ${disabled}>＋ Add Reviewer</button>
        </div>
        ${step.reviewers.length ? step.reviewers.map((reviewer, index) => `
          <div class="designer-reviewer-row">
            <div class="designer-form-grid">
              <input class="designer-input" placeholder="Agent profile" value="${escapeAttr(reviewer.agent || "")}" data-array-collection="reviewers" data-index="${index}" data-array-field="agent" ${disabled} />
              <input class="designer-input" placeholder="Review prompt path" value="${escapeAttr(reviewer.prompt || "")}" data-array-collection="reviewers" data-index="${index}" data-array-field="prompt" ${disabled} />
            </div>
            <input class="designer-input" type="number" step="0.1" value="${escapeAttr(reviewer.weight ?? 1)}" data-array-collection="reviewers" data-index="${index}" data-array-field="weight" ${disabled} />
            <button class="designer-danger" data-designer-action="remove-reviewer" data-index="${index}" ${disabled}>×</button>
          </div>
        `).join("") : `<div class="designer-empty-state">No extra reviewers. Current session review can still be used without reviewer rows.</div>`}
      </div>
      ${numberRow("Confidence Threshold", "confidenceThreshold", step.confidenceThreshold, disabled, "0", "1", "0.01")}
      ${inputRow("Pass Keywords", "passKeywords", step.passKeywords, disabled)}
      ${inputRow("Fail Keywords", "failKeywords", step.failKeywords, disabled)}
      <label class="designer-form-row">
        <span class="designer-label">Python Aggregator</span>
        <select class="designer-select" data-step-field="aggregatorFunction" ${disabled}>
          ${functionOptions("aggregators", [["", "None"], ["keyword_confidence", "Keyword + Confidence"]], step.aggregatorFunction)}
        </select>
      </label>
      ${functionHelp("aggregators", step.aggregatorFunction, "Optional aggregation function for multi-agent or keyword-based review results.")}
      <div class="designer-form-hint">Use confidence, keywords, pass count, and Python aggregator to make the final pass/fail decision.</div>
    </div>
  `;
}

function renderRetry(step, disabled, readonly) {
  const wf = getSelectedWorkflow();
  return `
    <div class="designer-form-grid">
      ${readonly ? readonlyNotice() : ""}
      ${numberRow("Max Retry", "maxRetries", step.maxRetries, disabled, "0", "20", "1")}
      <label class="designer-form-row">
        <span class="designer-label">On Fail</span>
        <select class="designer-select" data-step-field="failAction" ${disabled}>
          ${options(FailActions, step.failAction)}
        </select>
      </label>
      <label class="designer-form-row">
        <span class="designer-label">Retry From Step</span>
        <select class="designer-select" data-step-field="retryFromStepKey" ${disabled}>
          ${options([["", "Current / automatic"], ...(wf?.steps || []).map((item) => [item.key, item.name])], step.retryFromStepKey)}
        </select>
      </label>
      ${switchRow("Keep Same Session", "Continue in the same agent session when retrying.", "keepSameSession", step.keepSameSession, disabled)}
      ${switchRow("Inject Failure Feedback", "Pass validation/review error back into the retry prompt.", "injectFailureFeedback", step.injectFailureFeedback, disabled)}
      <div class="designer-function-help"><strong>Backend retry target</strong><span>${escapeHtml(step.retryFromStepKey || "Current / automatic")} · On fail: ${escapeHtml(step.failAction || "same_step")}</span></div>
      ${numberRow("Stop After Continuous Failures", "stopAfterFailures", step.stopAfterFailures, disabled, "1", "20", "1")}
    </div>
  `;
}

function renderGate(step, disabled, readonly) {
  return `
    <div class="designer-form-grid">
      ${readonly ? readonlyNotice() : ""}
      ${switchRow("Pause After This Step", "Stop workflow after this step and wait for user action.", "pauseAfterStep", step.pauseAfterStep, disabled)}
      ${switchRow("Approval Required", "User must approve before continuing.", "approvalRequired", step.approvalRequired, disabled)}
      ${textareaRow("Approval Message", "approvalMessage", step.approvalMessage, disabled, "Please review the artifact before continuing.")}
      <div class="designer-form-hint">Runner page can later show Approve, Reject with Guidance, and Retry from selected step actions.</div>
    </div>
  `;
}

function renderAdvanced(step, disabled, readonly) {
  return `
    <div class="designer-form-grid">
      ${readonly ? readonlyNotice() : ""}
      ${switchRow("Enable Timeout", "Timeout counts as failure and follows retry policy.", "timeoutEnabled", step.timeoutEnabled, disabled)}
      ${numberRow("Timeout Minutes", "timeoutMinutes", step.timeoutMinutes, disabled, "0", "1440", "1")}
      ${switchRow("Allow Interaction", "Qwen can pause and ask the user questions.", "allowInteraction", step.allowInteraction, disabled)}
      <label class="designer-form-row">
        <span class="designer-label">Python Validator</span>
        <select class="designer-select" data-step-field="validator" ${disabled}>
          ${functionOptions("validators", [["", "None"], ["validate_spec", "Validate Spec"], ["validate_todo", "Validate Todo"], ["run_pytest", "Run Pytest"]], step.validator)}
        </select>
      </label>
      ${functionHelp("validators", step.validator, "Optional validator used by validation and Python function steps.")}
      <div class="designer-list-editor">
        <div class="designer-section-row">
          <span class="designer-label">Expected Files</span>
          <button class="mini-button" data-designer-action="add-expected-file" ${disabled}>＋ Add File</button>
        </div>
        ${step.expectedFiles.length ? step.expectedFiles.map((file, index) => `
          <div class="designer-expected-row">
            <input class="designer-input" value="${escapeAttr(file)}" placeholder="output/report.md, report.md, or C:\\path\\report.md" data-array-collection="expectedFiles" data-index="${index}" data-array-field="value" ${disabled} />
            <button class="designer-danger" data-designer-action="remove-expected-file" data-index="${index}" ${disabled}>×</button>
            <div class="designer-path-help">${escapeHtml(describeExpectedFilePath(file))}</div>
          </div>
        `).join("") : `<div class="designer-empty-state">No expected files configured.</div>`}
        <div class="designer-form-hint">Relative names are checked in output/, workspace, then Project Path. Use output/, input/, prompts/, or an absolute path when you need an exact location.</div>
      </div>
    </div>
  `;
}

function inputRow(label, field, value, disabled, placeholder = "") {
  return `
    <label class="designer-form-row">
      <span class="designer-label">${escapeHtml(label)}</span>
      <input class="designer-input" value="${escapeAttr(value || "")}" placeholder="${escapeAttr(placeholder)}" data-step-field="${escapeAttr(field)}" ${disabled} />
    </label>
  `;
}

function numberRow(label, field, value, disabled, min, max, step) {
  return `
    <label class="designer-form-row">
      <span class="designer-label">${escapeHtml(label)}</span>
      <input class="designer-input" type="number" min="${escapeAttr(min)}" max="${escapeAttr(max)}" step="${escapeAttr(step)}" value="${escapeAttr(value)}" data-step-field="${escapeAttr(field)}" ${disabled} />
    </label>
  `;
}

function textareaRow(label, field, value, disabled, placeholder = "") {
  return `
    <label class="designer-form-row">
      <span class="designer-label">${escapeHtml(label)}</span>
      <textarea class="designer-textarea" placeholder="${escapeAttr(placeholder)}" data-step-field="${escapeAttr(field)}" ${disabled}>${escapeHtml(value || "")}</textarea>
    </label>
  `;
}

function switchRow(title, description, field, checked, disabled) {
  return `
    <label class="designer-form-row inline">
      <span class="designer-switch-label">
        <strong>${escapeHtml(title)}</strong>
        <span>${escapeHtml(description)}</span>
      </span>
      <input type="checkbox" data-step-field="${escapeAttr(field)}" ${checked ? "checked" : ""} ${disabled} />
    </label>
  `;
}

function readonlyNotice() {
  return `<div class="designer-empty-state">This is a system workflow. Duplicate it to edit settings.</div>`;
}

function options(items, selected) {
  return items.map(([value, label]) => `
    <option value="${escapeAttr(value)}" ${String(value) === String(selected) ? "selected" : ""}>${escapeHtml(label)}</option>
  `).join("");
}

function normalizeWorkflow(workflow) {
  const normalized = {
    id: workflow.id || makeId("workflow"),
    kind: workflow.kind || "custom",
    name: workflow.name || "Untitled Workflow",
    description: workflow.description || "Custom workflow draft.",
    active: Boolean(workflow.active),
    skillRoot: workflow.skillRoot || "skills/",
    promptRoot: workflow.promptRoot || "prompts/",
    steps: Array.isArray(workflow.steps) ? workflow.steps.map(normalizeStep) : [],
  };
  return normalized;
}

function normalizeStep(step) {
  const base = createStep(step || {});
  const type = inferStepType(step || base);
  return {
    ...base,
    ...step,
    type,
    sources: clone(step?.sources || base.sources || []),
    reviewers: clone(step?.reviewers || base.reviewers || []),
    expectedFiles: clone(step?.expectedFiles || base.expectedFiles || []),
    templatePath: step?.templatePath || base.templatePath,
    filename: step?.filename || normalizeFilename(step?.outputFile || base.filename || base.outputFile),
    outputFile: step?.outputFile || base.outputFile || "",
    agent: step?.agent || step?.provider || base.agent || "qwen",
    provider: step?.provider || step?.agent || base.provider || "qwen",
    templateContent: step?.templateContent || base.templateContent,
    validator: normalizeFunctionId(step?.validator || base.validator || ""),
  };
}

function inferStepType(step) {
  if (!step) return "ai";
  if (step.type === "ai" && step.reviewMode && step.reviewMode !== "none") return "review";
  if (step.type === "ai" && String(step.key || "").includes("review")) return "review";
  return step.type || "ai";
}

function normalizeFunctionId(value = "") {
  const raw = String(value || "").trim();
  const aliases = {
    "functions/validate_spec.py": "validate_spec",
    "functions/validate_todo.py": "validate_todo",
    "functions/run_tests.py": "run_pytest",
    "functions/run_pytest.py": "run_pytest",
    "functions/validate.py": "validate_spec",
  };
  return aliases[raw] || raw;
}

function defaultTemplatePath(overrides = {}) {
  const preset = TemplatePresets[overrides.key];
  if (preset?.path) return preset.path;
  const promptSource = (overrides.sources || []).find((source) => source.type === "prompt_file");
  return promptSource?.value || "";
}

function defaultFilename(overrides = {}) {
  const preset = TemplatePresets[overrides.key];
  if (preset?.filename) return preset.filename;
  if (overrides.filename) return normalizeFilename(overrides.filename);
  if (overrides.outputFile) return normalizeFilename(overrides.outputFile);
  const expected = Array.isArray(overrides.expectedFiles) ? overrides.expectedFiles[0] : "";
  return normalizeFilename(expected || "result.md");
}

function defaultTemplateContent(overrides = {}) {
  const preset = TemplatePresets[overrides.key];
  if (preset?.content) return preset.content;
  if (overrides.type === "review") {
    return "FILENAME: review.md\n\nRequirement:\n{{requirement}}\n\nArtifact:\n{{step_output}}";
  }
  if (overrides.type === "validation" || overrides.type === "python") return "";
  return "FILENAME: result.md\n\nProject Context:\n- Project Path: {{project_path}}\n- Workflow Workspace: {{workspace_path}}\n\nRequirement:\n{{requirement}}";
}

function normalizeFilename(value = "") {
  const raw = String(value || "").trim().replace(/\\/g, "/");
  if (!raw) return "";
  return raw.split("/").filter(Boolean).pop() || raw;
}

function getAvailableParamKeys() {
  return new Set(availablePromptParams().map((param) => param.key));
}

function extractTemplateParams(content = "") {
  const params = [];
  const seen = new Set();
  String(content).replace(/{{\s*([a-zA-Z0-9_.-]+)\s*}}/g, (_match, name) => {
    if (!seen.has(name)) {
      seen.add(name);
      params.push(name);
    }
    return _match;
  });
  return params;
}

function detectFilename(content = "") {
  const filenameMatch = String(content).match(/^\s*FILENAME\s*:\s*(.+?)\s*$/im);
  const outputMatch = String(content).match(/^\s*OUTPUT_FILE\s*:\s*(.+?)\s*$/im);
  return normalizeFilename((filenameMatch || outputMatch)?.[1] || "");
}

function getTemplateDiagnostics(step) {
  const used = extractTemplateParams(step.templateContent || "");
  const allowed = getAvailableParamKeys();
  return {
    used,
    unknown: used.filter((name) => !allowed.has(name)),
    filename: detectFilename(step.templateContent || ""),
  };
}

function promptDiagnosticsHtml({ unknown }) {
  if (!unknown.length) return "";
  return `
    <div class="designer-warning-box designer-template-warning-box">
      <strong>Unknown params</strong>
      <span>${unknown.map((name) => `{{${escapeHtml(name)}}}`).join(", ")}</span>
    </div>
  `;
}

function renderPromptDiagnostics(step) {
  const diagnostics = getTemplateDiagnostics(step);
  document.querySelectorAll("[data-template-diagnostics]").forEach((target) => {
    target.innerHTML = promptDiagnosticsHtml({ unknown: diagnostics.unknown });
  });
}

function renderDraftPromptDiagnostics() {
  if (!templateEditorDraft) return;
  const used = extractTemplateParams(templateEditorDraft.templateContent || "");
  const allowed = getAvailableParamKeys();
  const unknown = used.filter((name) => !allowed.has(name));
  document.querySelectorAll("[data-template-diagnostics]").forEach((target) => {
    target.innerHTML = promptDiagnosticsHtml({ unknown });
  });
}

function templatePresetOptions(selectedPath = "") {
  const items = Object.values(TemplatePresets).map((preset) => [preset.path, preset.path]);
  if (selectedPath && !items.some(([value]) => value === selectedPath)) {
    items.unshift([selectedPath, `${selectedPath} (current)`]);
  }
  items.unshift(["", "Select a template..."]);
  return options(items, selectedPath);
}

function findTemplatePreset(path = "") {
  return Object.values(TemplatePresets).find((preset) => preset.path === path) || null;
}

function templateFileNameFromPath(path = "") {
  const normalized = String(path || "").replace(/\\/g, "/").trim();
  return normalized.split("/").filter(Boolean).pop() || "";
}

function templatePathFromFileName(name = "") {
  const cleaned = String(name || "")
    .replace(/\\/g, "/")
    .split("/")
    .filter(Boolean)
    .pop()
    ?.replace(/[<>:"|?*]/g, "")
    .trim() || "";
  if (!cleaned) return "";
  const withExtension = /\.[a-z0-9]+$/i.test(cleaned) ? cleaned : `${cleaned}.md`;
  return `prompts/${withExtension}`;
}

function loadSelectedTemplatePreset() {
  if (!templateEditorDraft || isReadonly()) return;
  const presetSelect = document.querySelector("[data-template-preset-path]");
  const selectedPresetPath = presetSelect?.value || templateEditorDraft.templatePath;
  if (isTemplateDraftDirty()) {
    openTemplateUnsavedConfirm({
      title: "Replace current edits?",
      message: "Loading a template will replace the unsaved prompt content in this editor.",
      confirmLabel: "Load Template",
      action: "confirm-load-template-preset",
      templatePath: selectedPresetPath,
    });
    return;
  }
  performLoadSelectedTemplatePreset(selectedPresetPath);
}

function performLoadSelectedTemplatePreset(templatePath = "") {
  if (!templateEditorDraft || isReadonly()) return closeConfirm();
  const nextPath = templatePath || templateEditorDraft.templatePath;
  const preset = findTemplatePreset(nextPath);
  if (!preset) {
    closeConfirm();
    toast("No template preset found for this path.");
    return;
  }
  templateEditorDraft.templatePath = preset.path || nextPath;
  templateEditorDraft.filename = preset.filename || templateEditorDraft.filename || "result.md";
  templateEditorDraft.templateContent = preset.content || templateEditorDraft.templateContent || "";
  const pathInput = document.querySelector('[data-template-draft-field="templateName"]');
  const presetSelect = document.querySelector("[data-template-preset-path]");
  const filenameInput = document.querySelector('[data-template-draft-field="filename"]');
  const editor = el("designerTemplateEditor");
  if (pathInput) pathInput.value = templateFileNameFromPath(templateEditorDraft.templatePath);
  if (presetSelect) presetSelect.value = templateEditorDraft.templatePath;
  if (filenameInput) filenameInput.value = templateEditorDraft.filename;
  if (editor) editor.value = templateEditorDraft.templateContent;
  closeConfirm();
  renderDraftPromptDiagnostics();
  renderTemplateDirtyState();
  toast("Template loaded.");
}

function insertTemplateParam(paramKey) {
  const editor = el("designerTemplateEditor");
  if (!editor || isReadonly()) return;
  const token = `{{${paramKey}}}`;
  const start = editor.selectionStart ?? editor.value.length;
  const end = editor.selectionEnd ?? editor.value.length;
  editor.value = `${editor.value.slice(0, start)}${token}${editor.value.slice(end)}`;
  editor.focus();
  editor.selectionStart = editor.selectionEnd = start + token.length;
  if (templateEditorDraft) {
    templateEditorDraft.templateContent = editor.value;
    renderDraftPromptDiagnostics();
    renderTemplateDirtyState();
  }
  toast(`${token} inserted.`);
}

function updateTemplateDraft(input) {
  if (!templateEditorDraft || isReadonly()) return;
  const field = input.dataset.templateDraftField;
  const value = readInputValue(input);

  if (field === "templateName") {
    templateEditorDraft.templatePath = templatePathFromFileName(value);
    renderDraftPromptDiagnostics();
    renderTemplateDirtyState();
    return;
  }

  if (field === "templatePath" && input.dataset.templateAutoload === "true") {
    const previousPath = templateEditorDraft.templatePath || "";
    if (value === previousPath) return;
    if (isTemplateDraftDirty()) {
      input.value = previousPath;
      openTemplateUnsavedConfirm({
        title: "Replace current edits?",
        message: "Selecting another template will replace the unsaved prompt content in this editor.",
        confirmLabel: "Load Template",
        action: "confirm-load-template-preset",
        templatePath: value,
      });
      return;
    }
    templateEditorDraft.templatePath = value;
    performLoadSelectedTemplatePreset(value);
    return;
  }

  templateEditorDraft[field] = value;
  renderDraftPromptDiagnostics();
  renderTemplateDirtyState();
}


function openStepEditor(stepId = state.selectedStepId) {
  if (stepId) state.selectedStepId = stepId;
  const step = getSelectedStep();
  if (!step) return;
  ensureActiveTabForStep(step);
  closeStepEditor();
  stepEditorModalOpen = true;

  const box = document.createElement("div");
  box.className = "designer-export-box designer-step-modal-box";
  box.innerHTML = `
    <div class="designer-export-card designer-step-modal-card" role="dialog" aria-modal="true" aria-labelledby="designerStepModalTitle">
      <div class="designer-step-modal-head">
        <div class="designer-step-modal-title-wrap">
          <div class="designer-step-modal-title-line">
            <h2 id="designerStepModalTitle" style="margin:0;"></h2>
            <span id="designerStepModalType" class="designer-step-type"></span>
          </div>
          <p id="designerStepModalMeta" class="designer-form-hint"></p>
        </div>
        <div class="designer-step-modal-tools">
          <div class="designer-step-modal-nav" aria-label="Switch step">
            <button type="button" data-designer-action="step-editor-prev" data-step-editor-nav="prev" title="Previous step: Alt + ←">← Prev</button>
            <span data-step-editor-position>1 / 1</span>
            <button type="button" data-designer-action="step-editor-next" data-step-editor-nav="next" title="Next step: Alt + →">Next →</button>
          </div>
          <button type="button" data-designer-action="close-step-editor" aria-label="Close">×</button>
        </div>
      </div>

      <div class="designer-tabs designer-step-modal-tabs" role="tablist">
        <button type="button" class="designer-tab active" data-designer-tab="basic">Basic</button>
        <button type="button" class="designer-tab" data-designer-tab="sources">Prompt</button>
        <button type="button" class="designer-tab" data-designer-tab="review">Review</button>
        <button type="button" class="designer-tab" data-designer-tab="retry">Retry</button>
        <button type="button" class="designer-tab" data-designer-tab="gate">Gate</button>
        <button type="button" class="designer-tab" data-designer-tab="advanced">Advanced</button>
      </div>

      <div id="designerStepSettingsModal" class="designer-step-settings designer-step-modal-settings"></div>

      <div class="designer-footer-actions designer-step-modal-footer">
        <div class="designer-step-modal-footer-nav" aria-label="Switch step">
          <button type="button" data-designer-action="step-editor-prev" data-step-editor-nav="prev">← Previous Step</button>
          <button type="button" data-designer-action="step-editor-next" data-step-editor-nav="next">Next Step →</button>
        </div>
        <span class="designer-form-hint">Changes are kept in this draft. Use Save Draft on the main screen to persist.</span>
        <button type="button" data-designer-action="close-step-editor">Close</button>
      </div>
    </div>
  `;
  document.body.appendChild(box);
  renderStepEditorModal();
  box.querySelector("input, textarea, select, button")?.focus();
}

function switchStepEditor(direction) {
  const wf = getSelectedWorkflow();
  if (!wf?.steps?.length) return;

  const currentIndex = wf.steps.findIndex((item) => item.id === state.selectedStepId);
  if (currentIndex < 0) return;

  const nextIndex = Math.max(0, Math.min(wf.steps.length - 1, currentIndex + direction));
  if (nextIndex === currentIndex) return;

  const nextStep = wf.steps[nextIndex];
  state.selectedStepId = nextStep.id;
  ensureActiveTabForStep(nextStep);
  saveUiState();
  renderWorkflowViewOnly();
  renderStepEditorModal();
  const settings = el("designerStepSettingsModal");
  if (settings) settings.scrollTop = 0;
}

function closeStepEditor() {
  document.querySelectorAll(".designer-step-modal-box").forEach((node) => node.remove());
  stepEditorModalOpen = false;
}

function renderStepEditorModal() {
  if (!stepEditorModalOpen || !document.querySelector(".designer-step-modal-box")) return;
  renderStepEditorHeader();
  renderTabs();
  renderSettings();
}

function renderStepEditorHeader() {
  const step = getSelectedStep();
  const title = el("designerStepModalTitle");
  const type = el("designerStepModalType");
  const meta = el("designerStepModalMeta");
  if (!title || !type || !meta || !step) return;
  const wf = getSelectedWorkflow();
  const index = wf?.steps?.findIndex((item) => item.id === step.id) ?? -1;
  const total = wf?.steps?.length || 0;
  title.textContent = `${index >= 0 ? index + 1 + ". " : ""}${step.name || "Step Settings"}`;
  type.textContent = formatStepType(step.type);
  type.className = `designer-step-type ${step.type || ""}`;
  meta.textContent = `${step.key || "no key"} · ${step.enabled ? "enabled" : "disabled"} · retry ${step.maxRetries ?? 0}`;

  document.querySelectorAll("[data-step-editor-position]").forEach((node) => {
    node.textContent = index >= 0 && total ? `${index + 1} / ${total}` : "- / -";
  });

  document.querySelectorAll('[data-step-editor-nav="prev"]').forEach((button) => {
    button.disabled = index <= 0;
    button.title = index > 0 ? `Previous: ${wf.steps[index - 1].name}` : "Already first step";
  });
  document.querySelectorAll('[data-step-editor-nav="next"]').forEach((button) => {
    button.disabled = index < 0 || index >= total - 1;
    button.title = index >= 0 && index < total - 1 ? `Next: ${wf.steps[index + 1].name}` : "Already last step";
  });
}

function openTemplateEditor() {
  const step = getSelectedStep();
  if (!step) return;
  closeStepContextMenu();
  closePromptPreview();
  closeTemplateEditor();
  const readonly = isReadonly();
  templateEditorDraft = {
    stepId: step.id,
    templatePath: step.templatePath || "",
    filename: step.filename || normalizeFilename(step.outputFile || detectFilename(step.templateContent || "")),
    templateContent: step.templateContent || "",
  };
  templateEditorOriginal = clone(templateEditorDraft);
  const disabled = readonly ? "disabled" : "";
  const box = document.createElement("div");
  box.className = "designer-export-box designer-template-modal-box";
  box.innerHTML = `
    <div class="designer-export-card designer-template-modal-card">
      <div class="designer-template-modal-head">
        <div>
          <div class="designer-step-card-title">
            <h2 style="margin:0;">Edit Prompt Template</h2>
            <span id="designerTemplateDirtyBadge" class="badge passed">Saved</span>
          </div>
          <p class="designer-form-hint">Backend creates a workflow folder, then saves this step output using Filename.</p>
        </div>
        <button data-designer-action="close-template-editor" aria-label="Close">×</button>
      </div>
      <div class="designer-template-modal-meta">
        <label class="designer-form-row">
          <span class="designer-label">Template File Name</span>
          <input class="designer-input" value="${escapeAttr(templateFileNameFromPath(templateEditorDraft.templatePath))}" placeholder="my-step.md" data-template-draft-field="templateName" ${disabled} />
          <span class="designer-form-hint">Saved in this workflow's prompts/ folder. Subfolders and absolute paths are not used here.</span>
        </label>
        <label class="designer-form-row">
          <span class="designer-label">Load Preset</span>
          <div class="designer-template-picker-row">
            <select class="designer-select" data-template-preset-path ${disabled}>
              ${templatePresetOptions(templateEditorDraft.templatePath)}
            </select>
            <button type="button" data-designer-action="load-template-preset" ${disabled}>Load</button>
          </div>
        </label>
        <label class="designer-form-row">
          <span class="designer-label">Filename</span>
          <input class="designer-input" value="${escapeAttr(templateEditorDraft.filename)}" placeholder="spec.md" data-template-draft-field="filename" ${disabled} />
        </label>
      </div>
      <div class="designer-template-modal-grid">
        <label class="designer-form-row designer-template-editor-wrap">
          <span class="designer-label">Markdown Prompt Template</span>
          <textarea id="designerTemplateEditor" class="designer-textarea designer-template-editor designer-template-editor-large" placeholder="Write markdown prompt template. Use params like {{requirement}}." data-template-draft-field="templateContent" ${disabled}>${escapeHtml(templateEditorDraft.templateContent)}</textarea>
        </label>
        <aside class="designer-param-panel designer-param-panel-large">
          <div class="designer-section-row">
            <span class="designer-label">Available Params</span>
            <span class="designer-mini-muted">Click to insert</span>
          </div>
          <div class="designer-param-list">
            ${availablePromptParams().map((param) => `
              <button type="button" class="designer-param-chip" data-designer-action="insert-param" data-param="${escapeAttr(param.key)}" title="${escapeAttr(param.description)}" ${disabled}>
                {{${escapeHtml(param.key)}}}
              </button>
            `).join("")}
          </div>
          <div class="designer-form-hint">Params are supplied by backend runtime context. Unknown params are warned before publish.</div>
        </aside>
      </div>
      <div data-template-diagnostics class="designer-template-diagnostics designer-template-diagnostics-full"></div>
      <div class="designer-footer-actions">
        <button data-designer-action="preview-prompt">Preview Rendered Prompt</button>
        <button data-designer-action="close-template-editor">Cancel</button>
        <button class="primary" data-designer-action="save-template-editor" ${disabled}>Save Template</button>
      </div>
    </div>
  `;
  document.body.appendChild(box);
  renderDraftPromptDiagnostics();
  renderTemplateDirtyState();
  el("designerTemplateEditor")?.focus();
}

function saveTemplateEditor() {
  if (!templateEditorDraft || isReadonly()) return closeTemplateEditor();
  const step = getSelectedStep();
  if (!step || step.id !== templateEditorDraft.stepId) return closeTemplateEditor();
  step.templatePath = templateEditorDraft.templatePath || templatePathFromFileName(step.key || "step");
  step.filename = normalizeFilename(templateEditorDraft.filename || detectFilename(templateEditorDraft.templateContent || ""));
  step.templateContent = templateEditorDraft.templateContent || "";
  markWorkflowDirty();
  closeTemplateEditor({ force: true });
  renderSettings();
  renderWorkflowViewOnly();
  renderStepEditorModal();
  toast("Template saved.");
}

function requestCloseTemplateEditor() {
  if (isTemplateDraftDirty()) {
    openTemplateUnsavedConfirm({
      title: "Discard unsaved template changes?",
      message: "You changed this prompt template but have not saved it yet.",
      confirmLabel: "Discard Changes",
      action: "confirm-close-template-editor",
    });
    return;
  }
  closeTemplateEditor({ force: true });
}

function closeTemplateEditor({ force = false } = {}) {
  if (!force && isTemplateDraftDirty()) return requestCloseTemplateEditor();
  closeConfirm();
  document.querySelectorAll(".designer-template-modal-box").forEach((node) => node.remove());
  templateEditorDraft = null;
  templateEditorOriginal = null;
}

function isTemplateDraftDirty() {
  if (!templateEditorDraft || !templateEditorOriginal) return false;
  return ["templatePath", "filename", "templateContent"].some((field) =>
    String(templateEditorDraft[field] || "") !== String(templateEditorOriginal[field] || "")
  );
}

function renderTemplateDirtyState() {
  const badge = el("designerTemplateDirtyBadge");
  if (!badge) return;
  const dirty = isTemplateDraftDirty();
  badge.textContent = dirty ? "Unsaved changes" : "Saved";
  badge.classList.toggle("running", dirty);
  badge.classList.toggle("passed", !dirty);
}

function openTemplateUnsavedConfirm({ title, message, confirmLabel, action, templatePath = "" }) {
  closeConfirm();
  const box = document.createElement("div");
  box.className = "designer-export-box designer-confirm-box designer-template-unsaved-box";
  box.innerHTML = `
    <div class="designer-export-card" style="width:min(480px, 96vw);">
      <div class="designer-step-card-title">
        <h2 style="margin:0;">${escapeHtml(title)}</h2>
        <button data-designer-action="close-confirm" aria-label="Close">×</button>
      </div>
      <p class="designer-form-hint" style="font-size:14px;">${escapeHtml(message)}</p>
      <div class="designer-footer-actions">
        <button data-designer-action="close-confirm">Keep Editing</button>
        <button class="designer-danger-button" data-designer-action="${escapeAttr(action)}" data-template-path="${escapeAttr(templatePath)}">${escapeHtml(confirmLabel)}</button>
      </div>
    </div>
  `;
  document.body.appendChild(box);
  box.querySelector("[data-designer-action='close-confirm']")?.focus();
}

function openPromptPreview() {
  const step = getSelectedStep();
  if (!step) return;
  closePromptPreview();
  const box = document.createElement("div");
  box.className = "designer-export-box designer-preview-box";
  box.innerHTML = `
    <div class="designer-export-card">
      <div class="designer-step-card-title">
        <h2 style="margin:0;">Rendered Prompt Preview</h2>
        <button data-designer-action="close-preview" aria-label="Close">×</button>
      </div>
      <p class="designer-form-hint">Preview uses sample values. Backend will replace params with real runtime values.</p>
      <pre>${escapeHtml(renderPromptWithSamples(templateEditorDraft?.templateContent ?? step.templateContent ?? ""))}</pre>
      <div class="designer-footer-actions">
        <button data-designer-action="close-preview">Close</button>
      </div>
    </div>
  `;
  document.body.appendChild(box);
}

function closePromptPreview() {
  document.querySelectorAll(".designer-preview-box").forEach((node) => node.remove());
}

function renderPromptWithSamples(content = "") {
  const samples = Object.fromEntries(availablePromptParams().map((param) => [param.key, param.sample]));
  return String(content).replace(/{{\s*([a-zA-Z0-9_.-]+)\s*}}/g, (_match, name) => samples[name] ?? `[UNKNOWN_PARAM:${name}]`);
}

function selectWorkflow(workflowId, stepId = null) {
  if (workflowId !== state.selectedWorkflowId && isWorkflowDirty()) {
    guardedWorkflowAction(() => doSelectWorkflow(workflowId, stepId));
    return;
  }
  doSelectWorkflow(workflowId, stepId);
}

function doSelectWorkflow(workflowId, stepId = null) {
  state.selectedWorkflowId = workflowId;
  const wf = getSelectedWorkflow();
  state.selectedStepId = stepId || wf?.steps?.[0]?.id || null;
  saveUiState();
  render();
}

function selectStep(stepId, options = {}) {
  state.selectedStepId = stepId;
  ensureActiveTabForStep(getSelectedStep());
  saveUiState();
  renderWorkflowViewOnly();
  renderTabs();
  renderSettings();
  if (options.openModal) openStepEditor(stepId);
}

function createNewWorkflow() {
  guardedWorkflowAction(() => {
    const workflow = createWorkflow({ name: uniqueWorkflowName("New Workflow") });
    state.workflows.unshift(workflow);
    doSelectWorkflow(workflow.id, workflow.steps[0]?.id);
    markWorkflowDirty();
    render();
    toast("New workflow created. Save Draft to keep it.");
  });
}

function duplicateSystemWorkflow(name = null) {
  const copy = createWorkflow({
    name: uniqueWorkflowName(name || `${systemWorkflow.name} Copy`),
    description: "Duplicated from system workflow.",
    active: false,
    skillRoot: systemWorkflow.skillRoot,
    promptRoot: systemWorkflow.promptRoot,
    steps: systemWorkflow.steps.map((step) => ({ ...clone(step), id: makeId("step") })),
  });
  return copy;
}

function duplicateCurrentWorkflow() {
  const workflow = getSelectedWorkflow();
  if (!workflow) return;
  if (isReadonly()) {
    toast("Use Duplicate as Custom for the system workflow.");
    return;
  }

  const copy = createWorkflow({
    ...clone(workflow),
    id: makeId("workflow"),
    kind: "custom",
    active: false,
    name: uniqueWorkflowName(`${workflow.name} Copy`),
    description: workflow.description || `Duplicated from ${workflow.name}.`,
    steps: (workflow.steps || []).map((step) => ({ ...clone(step), id: makeId("step") })),
  });

  const currentIndex = state.workflows.findIndex((item) => item.id === workflow.id);
  const insertAt = currentIndex >= 0 ? currentIndex + 1 : 0;
  state.workflows.splice(insertAt, 0, copy);
  doSelectWorkflow(copy.id, copy.steps[0]?.id);
  markWorkflowDirty();
  render();
  toast("Workflow duplicated. Save Draft to keep it.");
}

function addStep() {
  const wf = getSelectedWorkflow();
  if (!wf || isReadonly()) return toast("Duplicate the system workflow before editing steps.");
  const step = createStep({ name: `New Step ${wf.steps.length + 1}`, key: `new_step_${wf.steps.length + 1}` });
  wf.steps.push(step);
  state.selectedStepId = step.id;
  state.activeTab = "basic";
  markWorkflowDirty();
  render();
  openStepEditor(step.id);
  toast("Step added. Save Draft to keep it.");
}

function deleteWorkflow(workflowId) {
  if (workflowId === systemWorkflow.id) {
    toast("System workflow cannot be deleted.");
    return;
  }
  const workflow = state.workflows.find((item) => item.id === workflowId);
  if (!workflow) return;
  openDeleteConfirm({
    title: "Delete workflow?",
    message: `${workflow.name} will be removed from the workflow config API and its workflow folder. This action cannot be undone.`,
    confirmLabel: "Delete Workflow",
    action: "confirm-delete-workflow",
    workflowId,
  });
}

async function performDeleteWorkflow(workflowId) {
  const index = state.workflows.findIndex((item) => item.id === workflowId);
  if (index < 0) return closeConfirm();
  try {
    await designerApi(`${WORKFLOW_API}/${encodeURIComponent(workflowId)}`, { method: "DELETE" });
    state.workflows.splice(index, 1);
    if (state.selectedWorkflowId === workflowId) {
      const next = state.workflows[0] || systemWorkflow;
      state.selectedWorkflowId = next.id;
      state.selectedStepId = next.steps?.[0]?.id || null;
    }
    closeConfirm();
    saveUiState();
    render();
    toast("Workflow deleted.");
  } catch (error) {
    toast(`Could not delete workflow: ${error.message}`);
  }
}

function deleteStep(stepId) {
  const wf = getSelectedWorkflow();
  if (!wf || isReadonly()) return;
  const step = wf.steps.find((item) => item.id === stepId);
  if (!step) return;
  openDeleteConfirm({
    title: "Delete step?",
    message: `${step.name} will be removed from this workflow. This action cannot be undone.`,
    confirmLabel: "Delete Step",
    action: "confirm-delete-step",
    stepId,
  });
}

function performDeleteStep(stepId) {
  const wf = getSelectedWorkflow();
  if (!wf || isReadonly()) return closeConfirm();
  const index = wf.steps.findIndex((item) => item.id === stepId);
  if (index < 0) return closeConfirm();
  wf.steps.splice(index, 1);
  const deletedSelectedStep = state.selectedStepId === stepId;
  state.selectedStepId = wf.steps[Math.max(0, index - 1)]?.id || wf.steps[0]?.id || null;
  if (deletedSelectedStep) closeStepEditor();
  closeConfirm();
  markWorkflowDirty();
  render();
  toast("Step deleted. Save Draft to keep it.");
}

function duplicateStep(stepId) {
  const wf = getSelectedWorkflow();
  if (!wf || isReadonly()) return;
  const index = wf.steps.findIndex((item) => item.id === stepId);
  if (index < 0) return;
  const copy = { ...clone(wf.steps[index]), id: makeId("step"), name: `${wf.steps[index].name} Copy`, key: `${wf.steps[index].key}_copy` };
  wf.steps.splice(index + 1, 0, copy);
  state.selectedStepId = copy.id;
  markWorkflowDirty();
  render();
  openStepEditor(copy.id);
  toast("Step duplicated. Save Draft to keep it.");
}

function moveStep(stepId, offset) {
  const wf = getSelectedWorkflow();
  if (!wf || isReadonly()) return;
  const index = wf.steps.findIndex((item) => item.id === stepId);
  const target = index + offset;
  if (index < 0 || target < 0 || target >= wf.steps.length) return;
  const [step] = wf.steps.splice(index, 1);
  wf.steps.splice(target, 0, step);
  markWorkflowDirty();
  renderWorkflowViewOnly();
  renderTabs();
  renderSettings();
  renderStepEditorModal();
}

function addSource() {
  const step = getSelectedStep();
  if (!step || isReadonly()) return;
  step.sources.push({ type: "skill_path", value: "skills/domain.md" });
  markWorkflowDirty();
  renderSettings();
  renderWorkflowViewOnly();
}

function addReviewer() {
  const step = getSelectedStep();
  if (!step || isReadonly()) return;
  step.reviewers.push({ agent: "qwen-reviewer", prompt: "prompts/review.md", weight: 1 });
  if (step.reviewMode === "none") step.reviewMode = "multi_agent";
  markWorkflowDirty();
  renderSettings();
  renderWorkflowViewOnly();
}

function addExpectedFile() {
  const step = getSelectedStep();
  if (!step || isReadonly()) return;
  step.expectedFiles.push("artifact.md");
  markWorkflowDirty();
  renderSettings();
  renderWorkflowViewOnly();
}

function removeArrayItem(collection, index) {
  const step = getSelectedStep();
  if (!step || isReadonly() || !Array.isArray(step[collection])) return;
  step[collection].splice(index, 1);
  markWorkflowDirty();
  renderSettings();
  renderWorkflowViewOnly();
}


function openImportWorkflow() {
  closeImportWorkflow();
  closeExport();
  importWorkflowDraft = null;
  const box = document.createElement("div");
  box.className = "designer-export-box designer-import-box";
  box.innerHTML = `
    <div class="designer-export-card designer-import-card">
      <div class="designer-step-card-title">
        <div>
          <h2 style="margin:0;">Import Workflow JSON</h2>
          <p class="designer-form-hint">Paste exported JSON or choose a file. Imported workflows become custom drafts.</p>
        </div>
        <button data-designer-action="close-import" aria-label="Close">×</button>
      </div>
      <div class="designer-import-grid">
        <section class="designer-form-grid">
          <label class="designer-form-row">
            <span class="designer-label">Choose File</span>
            <input id="designerImportFile" class="designer-input" type="file" accept=".json,application/json" />
          </label>
          <label class="designer-form-row designer-import-json-wrap">
            <span class="designer-label">Workflow JSON</span>
            <textarea id="designerImportJsonInput" class="designer-textarea designer-import-json" placeholder="Paste workflow JSON here"></textarea>
          </label>
        </section>
        <aside class="designer-import-preview">
          <span class="designer-label">Validation Preview</span>
          <div id="designerImportPreview" class="designer-empty-state">Paste JSON, choose a file, then validate.</div>
        </aside>
      </div>
      <div class="designer-footer-actions">
        <button data-designer-action="validate-import">Validate</button>
        <button data-designer-action="close-import">Cancel</button>
        <button id="designerImportSubmit" class="primary" data-designer-action="perform-import" disabled>Import as Draft</button>
      </div>
    </div>
  `;
  document.body.appendChild(box);
  el("designerImportJsonInput")?.focus();
}

function readImportFile(input) {
  const file = input.files?.[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    const textarea = el("designerImportJsonInput");
    if (textarea) textarea.value = String(reader.result || "");
    validateImportWorkflowFromUi();
  };
  reader.onerror = () => renderImportValidation({ errors: ["Could not read selected file."], warnings: [], workflow: null });
  reader.readAsText(file);
}

function validateImportWorkflowFromUi() {
  const raw = el("designerImportJsonInput")?.value || "";
  const result = parseImportWorkflow(raw);
  importWorkflowDraft = result.workflow ? result : null;
  renderImportValidation(result);
}

function parseImportWorkflow(raw) {
  const errors = [];
  const warnings = [];
  let parsed = null;
  const text = String(raw || "").trim();
  if (!text) {
    return { errors: ["Workflow JSON is empty."], warnings, workflow: null };
  }
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    return { errors: [`Invalid JSON: ${error.message}`], warnings, workflow: null };
  }

  const source = parsed.workflow && typeof parsed.workflow === "object" ? parsed.workflow : parsed;
  if (!source || typeof source !== "object" || Array.isArray(source)) {
    errors.push("Root JSON must be a workflow object or { workflow: {...} }.");
  }
  if (!source?.name || typeof source.name !== "string") {
    errors.push("Missing required field: name.");
  }
  if (!Array.isArray(source?.steps)) {
    errors.push("Missing required field: steps[].");
  }
  if (errors.length) return { errors, warnings, workflow: null };

  const existingNames = new Set(state.workflows.map((item) => item.name));
  if (source.kind === "system") warnings.push("System workflow import will be converted to a custom draft.");
  if (existingNames.has(source.name)) warnings.push(`Workflow name already exists. It will be imported as "${uniqueWorkflowName(source.name)}".`);
  if (!source.steps.length) warnings.push("Workflow has no steps.");

  const workflow = normalizeImportedWorkflow(source);
  const usedUnknownParams = workflow.steps.flatMap((step) => getTemplateDiagnostics(step).unknown.map((name) => `${step.name}: {{${name}}}`));
  if (usedUnknownParams.length) warnings.push(`Unknown params found: ${usedUnknownParams.slice(0, 6).join(", ")}${usedUnknownParams.length > 6 ? "..." : ""}`);

  return { errors, warnings, workflow };
}

function normalizeImportedWorkflow(source) {
  const workflow = normalizeWorkflow({
    ...clone(source),
    id: makeId("workflow"),
    kind: "custom",
    active: false,
    name: uniqueWorkflowName(source.name || "Imported Workflow"),
  });
  workflow.steps = (workflow.steps || []).map((step) => normalizeImportedStep(step));
  return workflow;
}

function normalizeImportedStep(step) {
  return normalizeStep({
    ...clone(step || {}),
    id: makeId("step"),
    filename: step?.filename || normalizeFilename(step?.detected_filename || step?.outputFile || "result.md"),
    templateContent: step?.templateContent || step?.template?.content || step?.content || "",
    templatePath: step?.templatePath || step?.template?.path || "",
  });
}

function renderImportValidation({ errors = [], warnings = [], workflow = null }) {
  const preview = el("designerImportPreview");
  const submit = el("designerImportSubmit");
  if (submit) submit.disabled = Boolean(errors.length || !workflow);
  if (!preview) return;

  if (errors.length) {
    preview.innerHTML = `
      <div class="designer-warning-box">
        <strong>Import blocked</strong>
        <span>${errors.map(escapeHtml).join("<br>")}</span>
      </div>
    `;
    return;
  }

  if (!workflow) {
    preview.innerHTML = `<div class="designer-empty-state">Paste JSON, choose a file, then validate.</div>`;
    return;
  }

  preview.innerHTML = `
    <div class="designer-import-summary">
      <span class="badge passed">VALID</span>
      <h3>${escapeHtml(workflow.name)}</h3>
      <p>${escapeHtml(workflow.description || "No description.")}</p>
      <div class="designer-chip-row">
        <span class="badge">custom draft</span>
        <span class="badge">${workflow.steps.length} steps</span>
        <span class="badge">active: off</span>
      </div>
      ${warnings.length ? `
        <div class="designer-warning-box">
          <strong>Warnings</strong>
          <span>${warnings.map(escapeHtml).join("<br>")}</span>
        </div>
      ` : ""}
      <div class="designer-import-step-list">
        ${workflow.steps.slice(0, 12).map((step, index) => `
          <div>${index + 1}. ${escapeHtml(step.name)} <span>${escapeHtml(step.type)}</span></div>
        `).join("")}
        ${workflow.steps.length > 12 ? `<div>...and ${workflow.steps.length - 12} more steps</div>` : ""}
      </div>
    </div>
  `;
}

function performImportWorkflow() {
  if (!importWorkflowDraft?.workflow) {
    validateImportWorkflowFromUi();
    if (!importWorkflowDraft?.workflow) return;
  }
  const doImport = () => {
    const workflow = importWorkflowDraft.workflow;
    state.workflows.unshift(workflow);
    state.selectedWorkflowId = workflow.id;
    state.selectedStepId = workflow.steps[0]?.id || null;
    state.activeTab = "basic";
    closeImportWorkflow();
    markWorkflowDirty();
    render();
    toast("Workflow imported as a custom draft. Save Draft to keep it.");
  };
  if (isWorkflowDirty()) return guardedWorkflowAction(doImport);
  doImport();
}

function closeImportWorkflow() {
  document.querySelectorAll(".designer-import-box").forEach((node) => node.remove());
  importWorkflowDraft = null;
}

function exportWorkflow() {
  const wf = getSelectedWorkflow();
  if (!wf) return;
  closeExport();
  const box = document.createElement("div");
  box.className = "designer-export-box designer-export-modal-box";
  box.innerHTML = `
    <div class="designer-export-card">
      <div class="designer-step-card-title">
        <h2 style="margin:0;">Export Workflow JSON</h2>
        <button data-designer-action="close-export">×</button>
      </div>
      <p class="designer-form-hint">This is the backend workflow.json payload. Runtime execution uses these values directly.</p>
      <pre>${escapeHtml(JSON.stringify(toExportWorkflow(wf), null, 2))}</pre>
      <div class="designer-footer-actions">
        <button data-designer-action="close-export">Close</button>
      </div>
    </div>
  `;
  document.body.appendChild(box);
}

function toExportWorkflow(workflow) {
  const exported = clone(workflow);
  exported.steps = (exported.steps || []).map((step) => ({
    ...step,
    used_params: extractTemplateParams(step.templateContent || ""),
    detected_filename: detectFilename(step.templateContent || ""),
    filename: step.filename || normalizeFilename(step.outputFile || ""),
  }));
  return exported;
}

function closeExport() {
  document.querySelectorAll(".designer-export-modal-box").forEach((node) => node.remove());
}

function openDeleteConfirm({ title, message, confirmLabel, action, workflowId = "", stepId = "" }) {
  closeConfirm();
  const box = document.createElement("div");
  box.className = "designer-export-box designer-confirm-box";
  box.innerHTML = `
    <div class="designer-export-card" style="width:min(460px, 96vw);">
      <div class="designer-step-card-title">
        <h2 style="margin:0;">${escapeHtml(title)}</h2>
        <button data-designer-action="close-confirm" aria-label="Close">×</button>
      </div>
      <p class="designer-form-hint" style="font-size:14px;">${escapeHtml(message)}</p>
      <div class="designer-footer-actions">
        <button data-designer-action="close-confirm">Cancel</button>
        <button class="designer-danger-button" data-designer-action="${escapeAttr(action)}" data-workflow-id="${escapeAttr(workflowId)}" data-step-id="${escapeAttr(stepId)}">${escapeHtml(confirmLabel)}</button>
      </div>
    </div>
  `;
  document.body.appendChild(box);
  box.querySelector("[data-designer-action='close-confirm']")?.focus();
}

function closeConfirm() {
  document.querySelectorAll(".designer-confirm-box").forEach((node) => node.remove());
}

function getSelectedWorkflow() {
  if (state.selectedWorkflowId === systemWorkflow.id) return clone(systemWorkflow);
  return state.workflows.find((workflow) => workflow.id === state.selectedWorkflowId) || state.workflows[0] || clone(systemWorkflow);
}

function getSelectedStep() {
  const wf = getSelectedWorkflow();
  return wf?.steps?.find((step) => step.id === state.selectedStepId) || wf?.steps?.[0] || null;
}

function isReadonly() {
  return state.selectedWorkflowId === systemWorkflow.id;
}

async function saveState(options = {}) {
  try {
    const workflow = getSelectedWorkflow();
    if (workflow && !isReadonly()) {
      const saved = await designerApi(`${WORKFLOW_API}/${encodeURIComponent(workflow.id)}`, {
        method: "PUT",
        body: JSON.stringify(workflow),
      });
      const index = state.workflows.findIndex((item) => item.id === saved.id);
      if (index >= 0) state.workflows[index] = normalizeWorkflow(saved);
      state.selectedWorkflowId = saved.id;
    }
    saveUiState();
    workflowDirty = false;
    renderWorkflowDirtyState();
  } catch {
    if (!options.quiet) toast("Could not save workflow to API.");
  }
}

function saveUiState() {
  try {
    const saved = readStorage();
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({
      ...saved,
      selectedStepId: state.selectedStepId,
      activeTab: state.activeTab,
      selectedWorkflowId: state.selectedWorkflowId,
      stepFilter: state.stepFilter,
      stepTypeFilter: state.stepTypeFilter,
      stepDensity: state.stepDensity,
      stepActionMenuExpanded: state.stepActionMenuExpanded,
    }));
  } catch {
    // UI state persistence is best effort only.
  }
}

function markWorkflowDirty() {
  if (isReadonly()) return;
  workflowDirty = true;
  renderWorkflowDirtyState();
}

function isWorkflowDirty() {
  return Boolean(workflowDirty);
}

function renderWorkflowDirtyState() {
  const badge = el("designerWorkflowDirtyBadge");
  if (!badge) return;
  const dirty = isWorkflowDirty();
  badge.textContent = dirty ? "Unsaved changes" : "Saved";
  badge.classList.toggle("running", dirty);
  badge.classList.toggle("passed", !dirty);
  const saveButton = el("designerSaveDraft");
  if (saveButton) saveButton.classList.toggle("designer-save-attention", dirty);
}

function guardedWorkflowAction(action) {
  if (!isWorkflowDirty()) {
    action();
    return;
  }
  pendingWorkflowAction = action;
  openWorkflowUnsavedConfirm();
}

function openWorkflowUnsavedConfirm() {
  closeConfirm();
  const box = document.createElement("div");
  box.className = "designer-export-box designer-confirm-box designer-workflow-unsaved-box";
  box.innerHTML = `
    <div class="designer-export-card" style="width:min(500px, 96vw);">
      <div class="designer-step-card-title">
        <h2 style="margin:0;">Discard unsaved workflow changes?</h2>
        <button data-designer-action="close-confirm" aria-label="Close">×</button>
      </div>
      <p class="designer-form-hint" style="font-size:14px;">You changed this workflow but have not saved the draft yet.</p>
      <div class="designer-footer-actions">
        <button data-designer-action="close-confirm">Keep Editing</button>
        <button class="designer-danger-button" data-designer-action="confirm-discard-workflow-changes">Discard Changes</button>
      </div>
    </div>
  `;
  document.body.appendChild(box);
  box.querySelector("[data-designer-action='close-confirm']")?.focus();
}

function confirmDiscardWorkflowChanges() {
  const action = pendingWorkflowAction;
  pendingWorkflowAction = null;
  reloadSavedWorkflowState();
  closeConfirm();
  if (typeof action === "function") action();
}

function reloadSavedWorkflowState() {
  loadState().then(() => render());
}

function readStorage() {
  try {
    return JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "{}");
  } catch {
    return {};
  }
}

async function designerApi(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(body.detail || response.statusText);
  }
  return response.json();
}

function readInputValue(input) {
  if (input.type === "checkbox") return input.checked;
  if (input.type === "number") return Number(input.value || 0);
  return input.value;
}

function summarizeStep(step) {
  if (step.type === "review") return `${formatReviewMode(step.reviewMode)} · confidence >= ${step.confidenceThreshold} · retry ${step.maxRetries}${step.retryFromStepKey ? ` → ${step.retryFromStepKey}` : ""}`;
  if (step.type === "validation" || step.type === "python") {
    const meta = functionMeta("validators", step.validator);
    return `${step.type === "python" ? "Python function" : "Validation function"}: ${meta?.label || step.validator || "not set"}`;
  }
  if (step.type === "gate" || step.type === "manual") return step.pauseAfterStep ? "Pause and wait for human approval." : "Gate decision step.";
  if (step.command) return `Command ${step.command} · template ${step.templatePath || "not set"} · retry ${step.maxRetries}${step.retryFromStepKey ? ` → ${step.retryFromStepKey}` : ""}.`;
  return `${step.templatePath || "no template"} · retry ${step.maxRetries}${step.retryFromStepKey ? ` → ${step.retryFromStepKey}` : ""} · ${step.allowInteraction ? "interactive" : "fully automatic"}`;
}

function formatStepType(type) {
  return StepTypes.find(([value]) => value === type)?.[1] || type;
}

function formatReviewMode(mode) {
  return ReviewModes.find(([value]) => value === mode)?.[1] || mode;
}

function uniqueWorkflowName(base) {
  const names = new Set(state.workflows.map((item) => item.name));
  if (!names.has(base)) return base;
  let index = 2;
  while (names.has(`${base} ${index}`)) index += 1;
  return `${base} ${index}`;
}

function makeId(prefix) {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
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

function escapeAttr(value = "") {
  return escapeHtml(value);
}

function el(id) {
  return document.getElementById(id);
}

function on(id, event, handler) {
  const target = el(id);
  if (target) target.addEventListener(event, handler);
}

function setText(id, value) {
  const target = el(id);
  if (target) target.textContent = value;
}

function toast(message) {
  document.querySelectorAll(".designer-toast").forEach((node) => node.remove());
  const node = document.createElement("div");
  node.className = "designer-toast";
  node.textContent = message;
  document.body.appendChild(node);
  setTimeout(() => node.remove(), 2200);
}

export { initWorkflowDesignerPage };
