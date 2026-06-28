export function createWorkflows(ctx) {
  const { api, state, ui } = ctx;

  function flattenWorkflows(payload) {
    const items = [];
    if (payload?.system) items.push(payload.system);
    if (Array.isArray(payload?.custom)) items.push(...payload.custom);
    return items;
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
      if (!select) return;
      select.innerHTML = state.workflows.map((workflow) => {
        const label = workflow.kind === "system" ? `${workflow.name} (System)` : workflow.name;
        return `<option value="${ui.escapeHtml(workflow.id)}">${ui.escapeHtml(label)}</option>`;
      }).join("");
      select.value = state.selectedWorkflowId;
    },

    select(workflowId) {
      state.selectedWorkflowId = workflowId || "system-controlled-qwen";
    },
  };

  return workflows;
}
