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
      ui.on("artifactSearch", "input", () => ctx.features.artifacts.renderList());
      ui.on("messageInput", "input", () => ctx.features.composer.autoResize());
      ui.on("messageInput", "keydown", (event) => {
        if (event.key === "Enter" && event.ctrlKey && !ui.byKey("runWorkflow").disabled) {
          event.preventDefault();
          ctx.features.chat.submit();
        }
      });
      ui.on("qwenAuthType", "change", () => ctx.features.config.saveAgentConfig());
      ui.on("qwenReuseSession", "change", () => ctx.features.config.saveAgentConfig());
      ui.on("maxRetries", "change", () => ctx.features.config.saveAgentConfig());
      ui.on("defaultAgent", "change", () => ctx.features.config.saveAgentConfig());
      ui.on("workflowSelect", "change", (event) => ctx.features.workflows.select(event.target.value));
      ui.on("thinkingLevel", "change", (event) => {
        ctx.features.workflows.selectThinkingLevel(event.target.value || "medium");
      });
      ui.on("thinkingDropdownButton", "click", (event) => {
        event.stopPropagation();
        ctx.features.workflows.toggleThinkingDropdown();
      });
      ui.on("thinkingDropdownMenu", "click", (event) => {
        const option = event.target.closest(".thinking-dropdown-option");
        if (!option || option.disabled || option.getAttribute("aria-disabled") === "true") return;
        event.stopPropagation();
        ctx.features.workflows.selectThinkingLevel(option.dataset.thinkingLevel);
      });
      ui.on("workflowDropdownButton", "click", (event) => {
        event.stopPropagation();
        ctx.features.workflows.toggleDropdown();
      });
      ui.on("workflowDropdownMenu", "click", (event) => {
        const option = event.target.closest(".workflow-dropdown-option");
        if (!option || option.disabled || option.getAttribute("aria-disabled") === "true") return;
        event.stopPropagation();
        ctx.features.workflows.select(option.dataset.workflowId);
      });
      document.addEventListener("input", (event) => {
        if (event.target?.id === "validationScript") {
          ctx.state.validationScript = event.target.value || "";
        }
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
        const thinkingPicker = ui.byKey("thinkingPicker");
        if (thinkingPicker && !thinkingPicker.contains(event.target)) ctx.features.workflows.closeThinkingDropdown();
      });

      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          ctx.features.workflows.closeDropdown();
          ctx.features.workflows.closeThinkingDropdown();
        }
      });

      document.querySelectorAll(".tab").forEach((tab) => {
        tab.onclick = () => ctx.features.layout.activateTab(tab.dataset.tab);
      });
    },
  };
}
