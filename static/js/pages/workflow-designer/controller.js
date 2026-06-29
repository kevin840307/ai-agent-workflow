import {
  FailActions,
  ReviewModes,
  SourceTypes,
  StepTypes,
  TemplatePresets,
} from "../workflow-designer-constants.js?v=20260629-static-modules16";
import {
  clone,
  el,
  escapeAttr,
  escapeHtml,
  formatReviewMode,
  formatStepType,
  makeId,
  on,
  options,
  readInputValue,
  setText,
  toast,
} from "./utils.js?v=20260629-static-modules16";
import {
  createStep,
  createWorkflow,
  defaultFilename,
  defaultTemplateContent,
  defaultTemplatePath,
  inferStepType,
  normalizeFilename,
  normalizeFunctionId,
  normalizeStep,
  normalizeWorkflow,
} from "./model.js?v=20260629-static-modules16";
import {
  availablePromptParamsFor,
  functionHelpFor,
  functionMetaFor,
  functionOptionsFor,
  stepUiCapabilitiesFor,
  workflowFunctionCountsFor,
} from "./function-catalog.js?v=20260629-static-modules16";
import { installLayoutRenderer } from "./layout-renderer.js?v=20260629-static-modules16";
import { installStepSettingsRenderer } from "./step-settings-renderer.js?v=20260629-static-modules16";
import { installTemplateEditor } from "./template-editor.js?v=20260629-static-modules16";
import { installImportExportTools } from "./import-export.js?v=20260629-static-modules16";

const STORAGE_KEY = "qwenWorkflow.workflowDesigner.ui.v1";
const SIDEBAR_COLLAPSED_KEY = "qwenWorkflow.layout.projectsCollapsed";
const WORKFLOW_API = "/api/workflows";

function functionOptions(groupName, fallbackItems, selected) {
  return functionOptionsFor(availableWorkflowFunctions, groupName, fallbackItems, selected);
}

function functionMeta(groupName, selected) {
  return functionMetaFor(availableWorkflowFunctions, groupName, selected);
}

function functionHelp(groupName, selected, emptyText = "Select a backend function.") {
  return functionHelpFor(availableWorkflowFunctions, groupName, selected, emptyText);
}

function workflowFunctionCounts() {
  return workflowFunctionCountsFor(availableWorkflowFunctions);
}

function availablePromptParams() {
  return availablePromptParamsFor(availableWorkflowFunctions);
}

function stepUiCapabilities(step) {
  return stepUiCapabilitiesFor(availableWorkflowFunctions, step);
}

let systemWorkflow = Object.freeze({
  id: "system-controlled-qwen",
  kind: "system",
  name: "Controlled Agent Workflow",
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
  designerMode: "simple",
  stepActionMenuExpanded: false,
  apiLoaded: false,
  apiError: "",
};

let workflowDirty = false;
let pendingWorkflowAction = null;
let availableWorkflowFunctions = { validators: [], reviewStrategies: [], aggregators: [], promptParams: [] };

async function initWorkflowDesignerPage() {
  restoreDesignerSidebar();
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
  state.designerMode = ["simple", "advanced", "json"].includes(saved.designerMode) ? saved.designerMode : "simple";
  state.stepActionMenuExpanded = Boolean(saved.stepActionMenuExpanded);
  workflowDirty = false;
}

function readDesignerSidebarCollapsed() {
  try {
    return window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "true";
  } catch {
    return false;
  }
}

function writeDesignerSidebarCollapsed(collapsed) {
  try {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(Boolean(collapsed)));
  } catch {
    // localStorage may be disabled in private / restricted browser modes.
  }
}

function updateDesignerSidebarButton(collapsed) {
  const button = el("toggleProjects");
  if (!button) return;
  button.classList.toggle("active", collapsed);
  button.textContent = collapsed ? ">" : "<";
  button.title = collapsed ? "Expand workflows" : "Collapse workflows";
  button.setAttribute("aria-label", button.title);
  button.setAttribute("aria-pressed", String(collapsed));
}

function setDesignerSidebarCollapsed(collapsed, persist = true) {
  document.body.classList.toggle("projects-collapsed", collapsed);
  updateDesignerSidebarButton(collapsed);
  if (persist) writeDesignerSidebarCollapsed(collapsed);
}

function restoreDesignerSidebar() {
  setDesignerSidebarCollapsed(readDesignerSidebarCollapsed(), false);
}

function toggleDesignerSidebar() {
  setDesignerSidebarCollapsed(!document.body.classList.contains("projects-collapsed"));
}

function bindEvents() {
  on("toggleProjects", "click", toggleDesignerSidebar);
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

  if (isStepEditorModalOpen() && event.altKey && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
    event.preventDefault();
    switchStepEditor(event.key === "ArrowLeft" ? -1 : 1);
    return;
  }

  if (event.key !== "Escape") return;
  if (isStepContextMenuOpen()) {
    closeStepContextMenu();
    return;
  }
  if (isStepEditorModalOpen()) {
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
  "set-designer-mode": (action) => setDesignerMode(action.dataset.mode),
  "apply-json-editor": () => applyJsonEditor(),
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
    const field = input.dataset.stepField;
    step[field] = value;

    if (field === "type") {
      handleStepTypeChange(step);
      markWorkflowDirty();
      return;
    }

    if (["validator", "reviewMode"].includes(field)) {
      handleStepCapabilityChange(step);
      markWorkflowDirty();
      return;
    }

    if (field === "templateContent") {
      renderPromptDiagnostics(step);
    }
    if (["name", "templatePath", "filename", "outputFile", "aggregatorFunction", "agent", "provider", "maxRetries", "failAction", "retryFromStepKey", "keepSameSession", "injectFailureFeedback", "timeoutEnabled", "timeoutMinutes"].includes(field)) renderWorkflowViewOnly();
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

function handleStepTypeChange(step) {
  applyStepTypeDefaults(step);
  handleStepCapabilityChange(step);
}

function handleStepCapabilityChange(step) {
  hydratePromptDefaultsForStepType(step);
  ensureActiveTabForStep(step);
  saveUiState();
  renderWorkflowViewOnly();
  renderStepEditorHeader();
  renderTabs();
  renderSettings();
}

function hydratePromptDefaultsForStepType(step) {
  if (!step) return;
  const capabilities = stepUiCapabilities(step);
  if (capabilities.supportsAgent) {
    step.agent = step.agent || step.provider || "qwen";
    step.provider = step.provider || step.agent || "qwen";
  }
  if (!isPromptCapableStep(step)) return;
  step.templatePath = step.templatePath || defaultTemplatePath(step);
  step.filename = step.filename || defaultFilename(step);
  step.templateContent = step.templateContent || defaultTemplateContent(step);
  if ((!Array.isArray(step.expectedFiles) || !step.expectedFiles.length) && step.filename) {
    step.expectedFiles = [step.filename];
  }
}

function isPromptCapableStep(step) {
  const capabilities = stepUiCapabilities(step);
  return Boolean(capabilities.promptDefaults || capabilities.supportsPrompt);
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
      designerMode: state.designerMode,
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

function setDesignerMode(mode) {
  if (!["simple", "advanced", "json"].includes(mode)) return;
  state.designerMode = mode;
  if (mode === "simple" && !["basic", "sources"].includes(state.activeTab)) state.activeTab = "basic";
  saveUiState();
  render();
}

function applyJsonEditor() {
  const wf = getSelectedWorkflow();
  const editor = el("designerJsonEditor");
  if (!wf || !editor) return;
  if (isReadonly()) {
    toast("System workflow is read-only. Duplicate it before editing JSON.");
    render();
    return;
  }
  try {
    const parsed = normalizeWorkflow(JSON.parse(editor.value || "{}"));
    Object.assign(wf, parsed, { id: wf.id, kind: "custom" });
    state.selectedStepId = wf.steps?.[0]?.id || null;
    markWorkflowDirty();
    render();
    toast("JSON applied. Save Draft to keep it.");
  } catch (error) {
    toast(`Invalid workflow JSON: ${error.message}`);
  }
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

function uniqueWorkflowName(base) {
  const names = new Set(state.workflows.map((item) => item.name));
  if (!names.has(base)) return base;
  let index = 2;
  while (names.has(`${base} ${index}`)) index += 1;
  return `${base} ${index}`;
}

const templateEditor = installTemplateEditor({
  TemplatePresets,
  clone,
  closeConfirm,
  el,
  escapeAttr,
  escapeHtml,
  availablePromptParams,
  closeStepContextMenu,
  ensureActiveTabForStep,
  formatStepType,
  getSelectedStep,
  getSelectedWorkflow,
  isReadonly,
  markWorkflowDirty,
  normalizeFilename,
  options,
  readInputValue,
  render: () => render(),
  renderSettings: () => renderSettings(),
  renderTabs: (step) => renderTabs(step),
  renderWorkflowViewOnly: () => renderWorkflowViewOnly(),
  saveUiState,
  state,
  toast,
});

const importExportTools = installImportExportTools({
  clone,
  closeConfirm,
  detectFilename: (content = "") => templateEditor.detectFilename(content),
  el,
  escapeHtml,
  extractTemplateParams: (content = "") => templateEditor.extractTemplateParams(content),
  getSelectedWorkflow,
  getTemplateDiagnostics: (step) => templateEditor.getTemplateDiagnostics(step),
  guardedWorkflowAction,
  isWorkflowDirty,
  makeId,
  markWorkflowDirty,
  normalizeFilename,
  normalizeStep,
  normalizeWorkflow,
  render: () => render(),
  state,
  toast,
  uniqueWorkflowName,
});

const stepSettingsRenderer = installStepSettingsRenderer({
  FailActions,
  ReviewModes,
  SourceTypes,
  StepTypes,
  el,
  escapeAttr,
  escapeHtml,
  formatStepType,
  functionHelp,
  functionOptions,
  getSelectedStep,
  getSelectedWorkflow,
  getTemplateDiagnostics: (step) => templateEditor.getTemplateDiagnostics(step),
  isReadonly,
  normalizeFilename,
  options,
  state,
  stepUiCapabilities,
});

const layoutRenderer = installLayoutRenderer({
  el,
  escapeAttr,
  escapeHtml,
  formatReviewMode,
  formatStepType,
  functionMeta,
  getSelectedStep,
  getSelectedWorkflow,
  getSystemWorkflow: () => systemWorkflow,
  isReadonly,
  markWorkflowDirty,
  moveStep,
  normalizeFilename,
  options,
  renderSettings: () => stepSettingsRenderer.renderSettings(),
  renderStepEditorHeader,
  renderStepEditorModal,
  renderWorkflowDirtyState,
  saveUiState,
  setText,
  summarizeStep,
  state,
  stepUiCapabilities,
  toast,
  workflowFunctionCounts,
});

function getAvailableParamKeys() { return templateEditor.getAvailableParamKeys(); }
function getTemplateDiagnostics(step) { return templateEditor.getTemplateDiagnostics(step); }
function renderPromptDiagnostics(step) { return templateEditor.renderPromptDiagnostics(step); }
function renderDraftPromptDiagnostics() { return templateEditor.renderDraftPromptDiagnostics(); }
function loadSelectedTemplatePreset() { return templateEditor.loadSelectedTemplatePreset(); }
function performLoadSelectedTemplatePreset(templatePath = "") { return templateEditor.performLoadSelectedTemplatePreset(templatePath); }
function insertTemplateParam(paramKey) { return templateEditor.insertTemplateParam(paramKey); }
function updateTemplateDraft(input) { return templateEditor.updateTemplateDraft(input); }
function openStepEditor(stepId = state.selectedStepId) { return templateEditor.openStepEditor(stepId); }
function switchStepEditor(direction) { return templateEditor.switchStepEditor(direction); }
function closeStepEditor() { return templateEditor.closeStepEditor(); }
function renderStepEditorModal() { return templateEditor.renderStepEditorModal(); }
function renderStepEditorHeader() { return templateEditor.renderStepEditorHeader(); }
function openTemplateEditor() { return templateEditor.openTemplateEditor(); }
function saveTemplateEditor() { return templateEditor.saveTemplateEditor(); }
function requestCloseTemplateEditor() { return templateEditor.requestCloseTemplateEditor(); }
function closeTemplateEditor(options = {}) { return templateEditor.closeTemplateEditor(options); }
function isTemplateDraftDirty() { return templateEditor.isTemplateDraftDirty(); }
function renderTemplateDirtyState() { return templateEditor.renderTemplateDirtyState(); }
function openTemplateUnsavedConfirm(options = {}) { return templateEditor.openTemplateUnsavedConfirm(options); }
function openPromptPreview() { return templateEditor.openPromptPreview(); }
function closePromptPreview() { return templateEditor.closePromptPreview(); }
function openImportWorkflow() { return importExportTools.openImportWorkflow(); }
function readImportFile(input) { return importExportTools.readImportFile(input); }
function validateImportWorkflowFromUi() { return importExportTools.validateImportWorkflowFromUi(); }
function performImportWorkflow() { return importExportTools.performImportWorkflow(); }
function closeImportWorkflow() { return importExportTools.closeImportWorkflow(); }
function exportWorkflow() { return importExportTools.exportWorkflow(); }
function closeExport() { return importExportTools.closeExport(); }
function isStepEditorModalOpen() { return templateEditor.isStepEditorModalOpen(); }
function render() { return layoutRenderer.render(); }
function renderSettings() { return stepSettingsRenderer.renderSettings(); }
function renderWorkflowLabels() { return layoutRenderer.renderWorkflowLabels(); }
function renderWorkflowViewOnly() { return layoutRenderer.renderWorkflowViewOnly(); }
function renderTabs(step) { return layoutRenderer.renderTabs(step); }
function openStepContextMenu(stepId, options = {}) { return layoutRenderer.openStepContextMenu(stepId, options); }
function closeStepContextMenu() { return layoutRenderer.closeStepContextMenu(); }
function isStepContextMenuOpen() { return layoutRenderer.isStepContextMenuOpen(); }
function updateStepFilter(input) { return layoutRenderer.updateStepFilter(input); }
function clearStepFilter() { return layoutRenderer.clearStepFilter(); }
function setStepDensity(density) { return layoutRenderer.setStepDensity(density); }
function toggleStepActionMenu() { return layoutRenderer.toggleStepActionMenu(); }
function handleStepDragStart(event) { return layoutRenderer.handleStepDragStart(event); }
function handleStepDragOver(event) { return layoutRenderer.handleStepDragOver(event); }
function handleStepDragLeave(event) { return layoutRenderer.handleStepDragLeave(event); }
function handleStepDrop(event) { return layoutRenderer.handleStepDrop(event); }
function handleStepDragEnd() { return layoutRenderer.handleStepDragEnd(); }
function syncStepFilterControls() { return layoutRenderer.syncStepFilterControls(); }
function getVisibleSteps(wf) { return layoutRenderer.getVisibleSteps(wf); }
function applyStepTypeDefaults(step) { return layoutRenderer.applyStepTypeDefaults(step); }
function ensureActiveTabForStep(step) { return layoutRenderer.ensureActiveTabForStep(step); }


export { initWorkflowDesignerPage };
