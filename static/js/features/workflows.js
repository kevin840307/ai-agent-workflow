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

  const workflows = {
    async load() {
      const payload = await api.request("/api/workflows");
      state.workflows = flattenWorkflows(payload);
      if (!state.workflows.some((workflow) => workflow.id === state.selectedWorkflowId)) {
        state.selectedWorkflowId = state.workflows[0]?.id || "system-controlled-qwen";
      }
      workflows.render();
    },

    render() {
      const select = ui.byKey("workflowSelect");
      const button = ui.byKey("workflowDropdownButton");
      const selectedLabel = ui.byKey("workflowSelectedLabel");
      const menu = ui.byKey("workflowDropdownMenu");
      if (!select) return;

      select.innerHTML = state.workflows.map((workflow) => {
        const label = workflowLabel(workflow);
        return `<option value="${ui.escapeHtml(workflow.id)}">${ui.escapeHtml(label)}</option>`;
      }).join("");
      select.value = state.selectedWorkflowId;

      if (menu) {
        menu.innerHTML = state.workflows.map((workflow) => {
          const label = workflowLabel(workflow);
          const badge = workflowBadge(workflow);
          const active = workflow.id === state.selectedWorkflowId ? " active" : "";
          return `
            <button class="workflow-dropdown-option${active}" type="button" role="option" aria-selected="${workflow.id === state.selectedWorkflowId}" data-workflow-id="${ui.escapeHtml(workflow.id)}">
              <span class="workflow-option-main">
                <strong>${ui.escapeHtml(label)}</strong>
                <small>${ui.escapeHtml(workflow.description || workflow.id || "")}</small>
              </span>
              <span class="workflow-option-badge">${ui.escapeHtml(badge)}</span>
            </button>
          `;
        }).join("");
      }

      const selected = state.workflows.find((workflow) => workflow.id === state.selectedWorkflowId);
      if (selectedLabel) selectedLabel.textContent = workflowLabel(selected);
      if (button) button.title = workflowLabel(selected);
    },

    select(workflowId) {
      state.selectedWorkflowId = workflowId || "system-controlled-qwen";
      workflows.render();
      workflows.toggleDropdown(false);
    },

    toggleDropdown(force = null) {
      const button = ui.byKey("workflowDropdownButton");
      const menu = ui.byKey("workflowDropdownMenu");
      if (!button || !menu) return;
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
