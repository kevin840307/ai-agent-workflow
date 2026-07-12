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
      ui.on("collapseRunCenter", "click", () => ctx.features.layout.setDetailsCollapsed(true));
      ui.on("expandRunCenter", "click", () => ctx.features.layout.setDetailsCollapsed(false));
      ui.on("openDiagnostics", "click", () => ctx.features.diagnostics.open());
      ui.on("openRunResult", "click", () => ctx.features.runs.openResultModal());
      ui.on("openSelectedStepDetail", "click", () => ctx.features.runs.openSelectedStepDetail());
      ui.on("closeDiagnostics", "click", () => ctx.features.diagnostics.close());
      ui.on("closeDiffDialog", "click", () => ctx.features.runs.closeDiffDialog());
      ui.on("toggleDiagnosticsSize", "click", () => ctx.features.diagnostics.toggleSize());
      ui.on("compactArtifacts", "click", () => ctx.features.diagnostics.compactArtifacts());
      ui.on("downloadDebugBundle", "click", () => ctx.features.diagnostics.downloadDebugBundle());
      ui.on("exportRunBundle", "click", () => ctx.features.runs.exportRun());
      ui.on("openSetupWizard", "click", () => ctx.features.setup.openWizard());
      ui.on("dismissSetupStatus", "click", (event) => { event.stopPropagation(); ctx.features.setup.dismissNotice(); });
      ui.on("composerAdvancedToggle", "click", () => {
        const panel = ui.byKey("composerAdvancedSettings");
        const button = ui.byKey("composerAdvancedToggle");
        if (!panel || !button) return;
        const open = panel.hidden;
        panel.hidden = !open;
        button.setAttribute("aria-expanded", String(open));
        button.classList.toggle("active", open);
      });
      ui.on("messageInput", "input", () => { ctx.features.composer.autoResize(); ctx.features.optimization.schedule(); });
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
      ui.on("runProfile", "change", (event) => ctx.features.workflows.selectRunProfile(event.target.value || "normal"));
      ui.on("advancedMode", "change", (event) => ctx.features.layout.setAdvancedMode(Boolean(event.target.checked)));
      ui.on("unattendedMode", "change", (event) => ctx.features.projectProfile.setUnattended(Boolean(event.target.checked)));
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

      document.querySelectorAll(".diagnostic-nav-button").forEach((button) => {
        button.addEventListener("click", () => ctx.features.diagnostics.activate(button.dataset.diagnostic));
      });
      ui.byKey("diagnosticsBackdrop")?.addEventListener("click", (event) => {
        if (event.target === ui.byKey("diagnosticsBackdrop")) ctx.features.diagnostics.close();
      });
      ui.byKey("diffDialogBackdrop")?.addEventListener("click", (event) => {
        if (event.target === ui.byKey("diffDialogBackdrop")) ctx.features.runs.closeDiffDialog();
      });
      ui.byKey("runResultPanel")?.addEventListener("click", (event) => {
        if (event.target === ui.byKey("runResultPanel")) ctx.features.runs.closeResultModal({ remember: true });
      });

      document.addEventListener("click", (event) => {
        const header = document.querySelector(".header");
        if (header && !header.contains(event.target)) ctx.features.layout.toggleSettings(false);
        const picker = ui.byKey("workflowPicker");
        if (picker && !picker.contains(event.target)) ctx.features.workflows.closeDropdown();
        const thinkingPicker = ui.byKey("thinkingPicker");
        if (thinkingPicker && !thinkingPicker.contains(event.target)) ctx.features.workflows.closeThinkingDropdown();
        const recommendation = ui.byKey("planningRecommendation")?.querySelector("details");
        if (recommendation?.open && !recommendation.contains(event.target)) recommendation.open = false;
      });

      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
          ctx.features.workflows.closeDropdown();
          ctx.features.workflows.closeThinkingDropdown();
          ctx.features.diagnostics.close();
          ctx.features.runs.closeDiffDialog();
          ctx.features.runs.closeResultModal({ remember: true });
          const recommendation = ui.byKey("planningRecommendation")?.querySelector("details");
          if (recommendation) recommendation.open = false;
        }
      });

      document.querySelectorAll(".tab").forEach((tab) => {
        tab.onclick = () => ctx.features.layout.activateTab(tab.dataset.tab);
      });
    },
  };
}
