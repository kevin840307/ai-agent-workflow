export function installImportExportTools(ctx) {
  const {
    clone,
    closeConfirm,
    el,
    escapeHtml,
    extractTemplateParams,
    detectFilename,
    getSelectedWorkflow,
    getTemplateDiagnostics,
    guardedWorkflowAction,
    isWorkflowDirty,
    makeId,
    markWorkflowDirty,
    normalizeFilename,
    normalizeStep,
    normalizeWorkflow,
    render,
    state,
    toast,
    uniqueWorkflowName,
  } = ctx;

  let importWorkflowDraft = null;

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
        <button data-designer-action="close-import" aria-label="Close">x</button>
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
        <button data-designer-action="close-export">x</button>
      </div>
      <p class="designer-form-hint">This is the backend .workflow asset payload. Runtime execution uses these values directly.</p>
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

  return {
    closeExport,
    closeImportWorkflow,
    exportWorkflow,
    openImportWorkflow,
    parseImportWorkflow,
    performImportWorkflow,
    readImportFile,
    renderImportValidation,
    toExportWorkflow,
    validateImportWorkflowFromUi,
  };
}
