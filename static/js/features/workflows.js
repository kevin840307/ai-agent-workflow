import { LocalStore, StorageKeys } from "../core/storage.js?v=20260701-step-detail-polish1";

export function createWorkflows(ctx) {
  const { api, state, ui } = ctx;

  function flattenWorkflows(payload) {
    const items = [];
    if (payload?.system) items.push(payload.system);
    if (Array.isArray(payload?.custom)) items.push(...payload.custom);
    return items;
  }

  function workflowLabel(workflow) {
    if (!workflow) return "Select workflow";
    return workflow.kind === "system" ? `${workflow.name} (System)` : workflow.name;
  }

  function workflowBadge(workflow) {
    if (!workflow) return "";
    return workflow.kind === "system" ? "System" : "Custom";
  }

  function isLocked() {
    return ["queued", "running", "waiting_input"].includes(state.activeRunStatus);
  }

  function selectedWorkflow() {
    return state.workflows.find((workflow) => workflow.id === state.selectedWorkflowId) || null;
  }

  function enabledSteps(workflow) {
    return (workflow?.steps || []).filter((step) => step.enabled !== false);
  }

  function hasLoadedRunForWorkflow(workflowId) {
    return Boolean(state.activeRunId && state.activeRunWorkflowId && state.activeRunWorkflowId === workflowId);
  }

  function outputLabel(step) {
    const output = step.outputFile || step.filename || "";
    if (output) return output;
    if (step.function) return `function: ${step.function}`;
    if (step.validator) return `legacy function: ${step.validator}`;
    if (step.command) return "command";
    return step.type || "step";
  }

  function ensurePreviewContainer() {
    let preview = document.getElementById("workflowPreview");
    if (preview) return preview;
    const steps = ui.byKey("steps");
    const layout = steps?.closest(".step-panel-layout");
    if (!steps || !layout) return null;
    preview = document.createElement("div");
    preview.id = "workflowPreview";
    preview.className = "workflow-preview";
    layout.insertBefore(preview, steps);
    return preview;
  }

  const workflows = {
    async load() {
      const payload = await api.request("/api/workflows");
      state.workflows = flattenWorkflows(payload);
      if (!state.workflows.some((workflow) => workflow.id === state.selectedWorkflowId)) {
        state.selectedWorkflowId = state.workflows[0]?.id || "system-controlled-qwen";
        LocalStore.setString(StorageKeys.selectedWorkflowId, state.selectedWorkflowId);
      }
      workflows.render();
    },

    render() {
      const select = ui.byKey("workflowSelect");
      const button = ui.byKey("workflowDropdownButton");
      const selectedLabel = ui.byKey("workflowSelectedLabel");
      const menu = ui.byKey("workflowDropdownMenu");
      const locked = isLocked();
      if (!select) return;

      select.innerHTML = state.workflows.map((workflow) => {
        const label = workflowLabel(workflow);
        return `<option value="${ui.escapeHtml(workflow.id)}">${ui.escapeHtml(label)}</option>`;
      }).join("");
      select.value = state.selectedWorkflowId;
      select.disabled = locked;

      if (menu) {
        menu.innerHTML = state.workflows.map((workflow) => {
          const label = workflowLabel(workflow);
          const badge = workflowBadge(workflow);
          const active = workflow.id === state.selectedWorkflowId ? " active" : "";
          const disabled = locked ? " disabled" : "";
          const ariaDisabled = locked ? "true" : "false";
          return `
            <button class="workflow-dropdown-option${active}" type="button" role="option" aria-selected="${workflow.id === state.selectedWorkflowId}" aria-disabled="${ariaDisabled}" data-workflow-id="${ui.escapeHtml(workflow.id)}"${disabled}>
              <span class="workflow-option-main">
                <strong>${ui.escapeHtml(label)}</strong>
                <small>${ui.escapeHtml(workflow.description || workflow.id || "")}</small>
              </span>
              <span class="workflow-option-badge">${ui.escapeHtml(badge)}</span>
            </button>
          `;
        }).join("");
      }

      const selected = selectedWorkflow();
      if (selectedLabel) selectedLabel.textContent = workflowLabel(selected);
      if (button) {
        button.title = locked
          ? `Workflow is locked while the current run is ${state.activeRunStatus}.`
          : workflowLabel(selected);
        button.disabled = locked;
        button.setAttribute("aria-disabled", String(locked));
      }
      ui.byKey("workflowPicker")?.classList.toggle("locked", locked);
      if (locked) workflows.toggleDropdown(false);
      workflows.renderPreview();
    },

    renderLockState() {
      const select = ui.byKey("workflowSelect");
      const button = ui.byKey("workflowDropdownButton");
      const picker = ui.byKey("workflowPicker");
      const locked = isLocked();
      if (select) select.disabled = locked;
      if (button) {
        button.disabled = locked;
        button.setAttribute("aria-disabled", String(locked));
        button.title = locked
          ? `Workflow is locked while the current run is ${state.activeRunStatus}.`
          : workflowLabel(selectedWorkflow());
      }
      picker?.classList.toggle("locked", locked);
      ui.byKey("workflowDropdownMenu")?.querySelectorAll(".workflow-dropdown-option").forEach((option) => {
        option.disabled = locked;
        option.setAttribute("aria-disabled", String(locked));
      });
      if (locked) workflows.toggleDropdown(false);
      workflows.renderPreview();
    },

    renderPreview() {
      const preview = ensurePreviewContainer();
      if (!preview) return;
      const workflow = selectedWorkflow();
      if (!workflow) {
        preview.innerHTML = `
          <div class="workflow-preview-empty">
            <strong>No workflow selected</strong>
            <span>Select a workflow from Run with to preview its steps.</span>
          </div>
        `;
        return;
      }

      const allSteps = workflow.steps || [];
      const steps = enabledSteps(workflow);
      const locked = isLocked();
      const hasLoadedRun = hasLoadedRunForWorkflow(workflow.id);
      const compact = locked || hasLoadedRun;
      const compactLabel = locked ? "Running" : "Run loaded";
      const description = workflow.description || "This workflow will be used for the next run.";
      const descriptionHtml = compact ? "" : `<p>${ui.escapeHtml(description)}</p>`;
      const stepsHtml = compact ? "" : `
          <div class="workflow-preview-steps" aria-label="Selected workflow steps">
            ${steps.map((step, index) => `
              <div class="workflow-preview-step">
                <span class="workflow-preview-step-no">${index + 1}</span>
                <span class="workflow-preview-step-main">
                  <strong>${ui.escapeHtml(step.name || step.key || `Step ${index + 1}`)}</strong>
                  <small>${ui.escapeHtml(step.key || "")}${step.type ? ` - ${ui.escapeHtml(step.type)}` : ""}</small>
                </span>
                <span class="workflow-preview-step-output">${ui.escapeHtml(outputLabel(step))}</span>
              </div>
            `).join("")}
          </div>`;
      preview.innerHTML = `
        <div class="workflow-preview-card${compact ? " locked compact" : ""}">
          <div class="workflow-preview-head">
            <div class="workflow-preview-title-wrap">
              <span class="workflow-preview-eyebrow">Run with preview</span>
              <strong>${ui.escapeHtml(workflowLabel(workflow))}</strong>
              ${descriptionHtml}
            </div>
            <div class="workflow-preview-meta">
              <span>${steps.length} enabled</span>
              <span>${allSteps.length} total</span>
              ${compact ? `<span class="workflow-preview-lock">${ui.escapeHtml(compactLabel)}</span>` : ""}
            </div>
          </div>
          ${stepsHtml}
        </div>
      `;
    },

    select(workflowId) {
      if (isLocked()) {
        workflows.renderLockState();
        return;
      }
      state.selectedWorkflowId = workflowId || "system-controlled-qwen";
      LocalStore.setString(StorageKeys.selectedWorkflowId, state.selectedWorkflowId);
      workflows.render();
      workflows.toggleDropdown(false);
    },

    toggleDropdown(force = null) {
      const button = ui.byKey("workflowDropdownButton");
      const menu = ui.byKey("workflowDropdownMenu");
      if (!button || !menu) return;
      if (isLocked()) {
        menu.hidden = true;
        button.setAttribute("aria-expanded", "false");
        ui.byKey("workflowPicker")?.classList.remove("open");
        return;
      }
      const nextOpen = force === null ? menu.hidden : Boolean(force);
      menu.hidden = !nextOpen;
      button.setAttribute("aria-expanded", String(nextOpen));
      ui.byKey("workflowPicker")?.classList.toggle("open", nextOpen);
    },

    closeDropdown() {
      workflows.toggleDropdown(false);
    },
  };

  return workflows;
}
