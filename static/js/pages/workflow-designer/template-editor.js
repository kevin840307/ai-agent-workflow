export function installTemplateEditor(ctx) {
  const {
    TemplatePresets,
    clone,
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
    saveUiState,
    state,
    toast,
  } = ctx;

  let templateEditorDraft = null;
  let templateEditorOriginal = null;
  let stepEditorModalOpen = false;

  function render() { return ctx.render(); }
  function renderWorkflowViewOnly() { return ctx.renderWorkflowViewOnly(); }
  function renderTabs(step) { return ctx.renderTabs(step); }
  function renderSettings() { return ctx.renderSettings(); }
  function closeConfirm() { return ctx.closeConfirm(); }

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
  return `steps/${withExtension}`;
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
            <button type="button" data-designer-action="step-editor-prev" data-step-editor-nav="prev" title="Previous step: Alt + <-"><- Prev</button>
            <span data-step-editor-position>1 / 1</span>
            <button type="button" data-designer-action="step-editor-next" data-step-editor-nav="next" title="Next step: Alt + ->">Next -></button>
          </div>
          <button type="button" data-designer-action="close-step-editor" aria-label="Close">x</button>
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
          <button type="button" data-designer-action="step-editor-prev" data-step-editor-nav="prev"><- Previous Step</button>
          <button type="button" data-designer-action="step-editor-next" data-step-editor-nav="next">Next Step -></button>
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
  meta.textContent = `${step.key || "no key"} - ${step.enabled ? "enabled" : "disabled"} - retry ${step.maxRetries ?? 0}`;

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
          <p class="designer-form-hint">Backend saves this prompt under data/ai-workflow/steps and stores step metadata under data/ai-workflow/contracts.</p>
        </div>
        <button data-designer-action="close-template-editor" aria-label="Close">x</button>
      </div>
      <div class="designer-template-modal-meta designer-template-modal-meta-inline">
        <label class="designer-form-row designer-template-meta-field">
          <span class="designer-label">Template File Name</span>
          <input class="designer-input" value="${escapeAttr(templateFileNameFromPath(templateEditorDraft.templatePath))}" placeholder="my-step.md" data-template-draft-field="templateName" ${disabled} />
        </label>
        <label class="designer-form-row designer-template-meta-field">
          <span class="designer-label">Output File Name</span>
          <input class="designer-input" value="${escapeAttr(templateEditorDraft.filename)}" placeholder="spec.md" data-template-draft-field="filename" ${disabled} />
        </label>
        <label class="designer-form-row designer-template-meta-field designer-template-preset-field">
          <span class="designer-label">Load Preset</span>
          <div class="designer-template-picker-row">
            <select class="designer-select" data-template-preset-path ${disabled}>
              ${templatePresetOptions(templateEditorDraft.templatePath)}
            </select>
            <button type="button" data-designer-action="load-template-preset" ${disabled}>Load</button>
          </div>
        </label>
        <div class="designer-form-hint designer-template-modal-meta-hint">Template files are saved as workflow step assets under steps/. Subfolders are managed by the backend.</div>
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
        <button data-designer-action="close-confirm" aria-label="Close">x</button>
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
        <button data-designer-action="close-preview" aria-label="Close">x</button>
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

  function isStepEditorModalOpen() {
    return stepEditorModalOpen;
  }

  return {
    closePromptPreview,
    detectFilename,
    closeStepEditor,
    closeTemplateEditor,
    extractTemplateParams,
    getAvailableParamKeys,
    getTemplateDiagnostics,
    insertTemplateParam,
    isStepEditorModalOpen,
    isTemplateDraftDirty,
    loadSelectedTemplatePreset,
    openPromptPreview,
    openStepEditor,
    openTemplateEditor,
    openTemplateUnsavedConfirm,
    performLoadSelectedTemplatePreset,
    renderDraftPromptDiagnostics,
    renderPromptDiagnostics,
    renderPromptWithSamples,
    renderStepEditorHeader,
    renderStepEditorModal,
    renderTemplateDirtyState,
    requestCloseTemplateEditor,
    saveTemplateEditor,
    switchStepEditor,
    templateFileNameFromPath,
    templatePathFromFileName,
    templatePresetOptions,
    updateTemplateDraft,
  };
}
