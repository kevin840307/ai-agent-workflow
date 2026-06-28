export function createEvents(ctx) {
  const { ui } = ctx;

  return {
    bind() {
      ui.on("toggleSettings", "click", (event) => {
        event.stopPropagation();
        ctx.features.layout.toggleSettings();
      });
      ui.on("settingsMenu", "click", (event) => event.stopPropagation());
      ui.on("toggleDetails", "click", () => ctx.features.layout.toggleDetails());
      ui.on("toggleProjects", "click", () => ctx.features.layout.toggleProjects());
      ui.on("artifactSearch", "input", () => ctx.features.artifacts.renderList());
      ui.on("messageInput", "input", () => ctx.features.composer.autoResize());
      ui.on("messageInput", "keydown", (event) => {
        if (event.key === "Enter" && event.ctrlKey && !ui.byKey("runWorkflow").disabled) {
          event.preventDefault();
          ctx.features.chat.submit();
        }
      });
      ui.on("qwenAuthType", "change", () => ctx.features.config.saveQwenConfig());
      ui.on("qwenReuseSession", "change", () => ctx.features.config.saveQwenConfig());
      ui.on("maxRetries", "change", () => ctx.features.config.saveQwenConfig());
      ui.on("workflowSelect", "change", (event) => ctx.features.workflows.select(event.target.value));
      ui.on("workflowDropdownButton", "click", (event) => {
        event.stopPropagation();
        ctx.features.workflows.toggleDropdown();
      });
      ui.on("workflowDropdownMenu", "click", (event) => {
        const option = event.target.closest(".workflow-dropdown-option");
        if (!option) return;
        event.stopPropagation();
        ctx.features.workflows.select(option.dataset.workflowId);
      });
      ui.on("saveRequirement", "click", () => ctx.features.requirements.save());
      ui.on("runWorkflow", "click", () => ctx.features.chat.submit());
      ui.on("modeWorkflow", "click", () => ctx.features.chat.setMode("workflow"));
      ui.on("modeChat", "click", () => ctx.features.chat.setMode("chat"));
      ui.on("retryRun", "click", () => ctx.features.runs.retry());
      ui.on("addGuidance", "click", () => ctx.features.runs.addGuidance());
      ui.on("newProject", "click", () => ctx.features.sessions.create());
      ui.on("resetSession", "click", () => ctx.features.sessions.resetActive());

      document.addEventListener("click", (event) => {
        const header = document.querySelector(".header");
        if (header && !header.contains(event.target)) ctx.features.layout.toggleSettings(false);
        const picker = ui.byKey("workflowPicker");
        if (picker && !picker.contains(event.target)) ctx.features.workflows.closeDropdown();
      });

      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") ctx.features.workflows.closeDropdown();
      });

      document.querySelectorAll(".tab").forEach((tab) => {
        tab.onclick = () => ctx.features.layout.activateTab(tab.dataset.tab);
      });
    },
  };
}
