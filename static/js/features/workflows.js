import { LocalStore, StorageKeys } from "../core/storage.js?v=20260704-direct-edit-gad";

export function createWorkflows(ctx) {
  const { api, state, ui } = ctx;

  function flattenWorkflows(payload) {
    const items = [];
    if (payload?.system) items.push(payload.system);
    if (Array.isArray(payload?.systems)) items.push(...payload.systems);
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

  const THINKING_LABELS = Object.freeze({
    none: "無",
    medium: "中",
    high: "高",
    extreme: "極高",
  });

  function isLocked() {
    return ["queued", "running", "waiting_input"].includes(state.activeRunStatus);
  }

  function normalizeThinkingLevel(level) {
    return ["none", "medium", "high", "extreme"].includes(level) ? level : "medium";
  }

  function thinkingLabel(level) {
    return THINKING_LABELS[normalizeThinkingLevel(level)] || THINKING_LABELS.medium;
  }

  function renderThinkingPicker(locked = isLocked()) {
    const level = normalizeThinkingLevel(state.thinkingLevel || "medium");
    state.thinkingLevel = level;

    const select = ui.byKey("thinkingLevel");
    const picker = ui.byKey("thinkingPicker") || select?.closest(".thinking-picker");
    const button = ui.byKey("thinkingDropdownButton");
    const selectedLabel = ui.byKey("thinkingSelectedLabel");
    const menu = ui.byKey("thinkingDropdownMenu");

    if (select) {
      select.value = level;
      select.disabled = locked;
    }
    if (selectedLabel) selectedLabel.textContent = thinkingLabel(level);
    if (button) {
      button.disabled = locked;
      button.title = locked
        ? `Thinking is locked while the current run is ${state.activeRunStatus}.`
        : `Thinking: ${thinkingLabel(level)}`;
      button.setAttribute("aria-disabled", String(locked));
    }
    picker?.classList.toggle("locked", locked);
    if (menu) {
      menu.querySelectorAll(".thinking-dropdown-option").forEach((option) => {
        const active = option.dataset.thinkingLevel === level;
        option.classList.toggle("active", active);
        option.setAttribute("aria-selected", String(active));
        option.disabled = locked;
        option.setAttribute("aria-disabled", String(locked));
      });
    }
    if (locked) workflows.toggleThinkingDropdown(false);
  }

  function renderThinkingLockState(locked) {
    renderThinkingPicker(locked);
  }

  function selectedWorkflow() {
    return state.workflows.find((workflow) => workflow.id === state.selectedWorkflowId) || null;
  }

  function enabledSteps(workflow) {
    return (workflow?.steps || []).filter((step) => step.enabled !== false);
  }

  function stepAcceptsValidationScript(step = {}) {
    const fallbackScripts = Array.isArray(step.fallbackValidationScripts)
      ? step.fallbackValidationScripts
      : Array.isArray(step.fallback_validation_scripts)
        ? step.fallback_validation_scripts
        : [];
    const functions = Array.isArray(step.functions) ? step.functions : [];
    return Boolean(
      step.requiresValidationScript
        || step.function === "run_external_validation"
        || step.function === "adaptive_python_gate"
        || functions.includes("run_external_validation")
        || functions.includes("adaptive_python_gate")
        || fallbackScripts.length > 0
    );
  }

  function acceptsValidationScript(workflow) {
    return enabledSteps(workflow).some(stepAcceptsValidationScript);
  }

  function requiresValidationScript(workflow) {
    return enabledSteps(workflow).some((step) => step.requiresValidationScript);
  }

  function hasLoadedRunForWorkflow(workflowId) {
    return Boolean(state.activeRunId && state.activeRunWorkflowId && state.activeRunWorkflowId === workflowId);
  }

  function outputLabel(step) {
    const output = step.outputFile || step.filename || "";
    if (output) return output;
    if (step.function) return `function: ${step.function}`;
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

      const profileSelect = ui.byKey("runProfile");
      if (profileSelect) {
        profileSelect.value = ["small", "normal", "strong"].includes(state.runProfile) ? state.runProfile : "normal";
        profileSelect.disabled = locked;
      }
      const advancedToggle = ui.byKey("advancedMode");
      if (advancedToggle) advancedToggle.checked = Boolean(state.advancedMode);

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
      renderThinkingLockState(locked);
      if (locked) workflows.toggleDropdown(false);
      renderThinkingPicker(locked);
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
      renderThinkingLockState(locked);
      const profileSelect = ui.byKey("runProfile");
      if (profileSelect) profileSelect.disabled = locked;
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
              <div class="workflow-preview-step${stepAcceptsValidationScript(step) ? " accepts-validation" : ""}${step.requiresValidationScript ? " requires-validation" : ""}">
                <span class="workflow-preview-step-no">${index + 1}</span>
                <span class="workflow-preview-step-main">
                  <strong>${ui.escapeHtml(step.name || step.key || `Step ${index + 1}`)}</strong>
                  <small>${ui.escapeHtml(step.key || "")}${step.type ? ` - ${ui.escapeHtml(step.type)}` : ""}</small>
                </span>
                <span class="workflow-preview-step-output">${ui.escapeHtml(stepAcceptsValidationScript(step) ? "Validation / Gate" : outputLabel(step))}</span>
              </div>
            `).join("")}
          </div>`;
      const validationValue = state.validationScript || "";
      const validationHtml = !compact && acceptsValidationScript(workflow) ? `
          <div class="workflow-validation-note workflow-step-validation">
            <label class="validation-script-field workflow-step-validation-script" id="validationScriptField" title="Optional run-specific Python validation script path">
              <span>Validation Script <em>optional</em></span>
              <input id="validationScript" type="text" value="${ui.escapeHtml(validationValue)}" placeholder="Optional: tools/check_config.py or C:\path\validate.py" autocomplete="off" />
            </label>
            <small>Optional. If empty, the workflow auto-detects validation.py / validate.py / verify.py / check.py, or skips validation as PASS.</small>
          </div>` : "";
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
              <span>model: ${ui.escapeHtml(state.runProfile || "normal")}</span>
              ${compact ? `<span class="workflow-preview-lock">${ui.escapeHtml(compactLabel)}</span>` : ""}
            </div>
          </div>
          ${stepsHtml}
          ${validationHtml}
        </div>
      `;
    },

    acceptsValidationScriptForSelected() {
      return acceptsValidationScript(selectedWorkflow());
    },

    requiresValidationScriptForSelected() {
      return requiresValidationScript(selectedWorkflow());
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

    selectRunProfile(profile) {
      const normalized = ["small", "normal", "strong"].includes(profile) ? profile : "normal";
      state.runProfile = normalized;
      LocalStore.setString(StorageKeys.runProfile, normalized);
      const select = ui.byKey("runProfile");
      if (select) select.value = normalized;
      workflows.renderPreview();
    },

    selectThinkingLevel(level) {
      if (isLocked()) {
        workflows.renderLockState();
        return;
      }
      state.thinkingLevel = normalizeThinkingLevel(level);
      LocalStore.setString(StorageKeys.thinkingLevel, state.thinkingLevel);
      renderThinkingPicker(false);
      workflows.toggleThinkingDropdown(false);
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
      if (nextOpen) workflows.toggleThinkingDropdown(false);
      menu.hidden = !nextOpen;
      button.setAttribute("aria-expanded", String(nextOpen));
      ui.byKey("workflowPicker")?.classList.toggle("open", nextOpen);
    },

    toggleThinkingDropdown(force = null) {
      const button = ui.byKey("thinkingDropdownButton");
      const menu = ui.byKey("thinkingDropdownMenu");
      if (!button || !menu) return;
      if (isLocked()) {
        menu.hidden = true;
        button.setAttribute("aria-expanded", "false");
        ui.byKey("thinkingPicker")?.classList.remove("open");
        return;
      }
      const nextOpen = force === null ? menu.hidden : Boolean(force);
      if (nextOpen) workflows.toggleDropdown(false);
      menu.hidden = !nextOpen;
      button.setAttribute("aria-expanded", String(nextOpen));
      ui.byKey("thinkingPicker")?.classList.toggle("open", nextOpen);
    },

    closeDropdown() {
      workflows.toggleDropdown(false);
    },

    closeThinkingDropdown() {
      workflows.toggleThinkingDropdown(false);
    },
  };

  return workflows;
}
