export function createComposer(ctx) {
  const { state, ui } = ctx;

  const composer = {
    setMode(label = "Requirement") {
      const mode = ui.byKey("composerMode");
      if (mode) mode.textContent = label;
    },

    updateModeLabel() {
      if (["running", "queued"].includes(state.activeRunStatus)) {
        composer.setMode("Running");
        return;
      }
      if (state.waitingForInput || state.activeRunStatus === "waiting_input") {
        composer.setMode("Qwen waiting");
        return;
      }
      if (state.activeRunStatus === "failed") {
        composer.setMode("Failed");
        return;
      }
      composer.setMode("Requirement");
    },

    autoResize() {
      const input = ui.byKey("messageInput");
      if (!input) return;
      input.style.height = "auto";
      input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
      input.style.overflowY = input.scrollHeight > 180 ? "auto" : "hidden";
    },

    setWaiting(waiting) {
      const wasWaiting = state.waitingForInput;
      state.waitingForInput = waiting;
      const input = ui.byKey("messageInput");
      const runButton = ui.byKey("runWorkflow");
      const saveButton = ui.byKey("saveRequirement");

      if (waiting && !wasWaiting && input) input.value = "";
      if (input) input.placeholder = waiting ? "Reply to Qwen and continue..." : "Describe what to build...";
      if (runButton) {
        runButton.textContent = state.activeRunStatus === "running"
          ? "Stop"
          : (waiting ? "Reply" : "Run");
      }
      if (saveButton) saveButton.disabled = waiting;

      composer.updateModeLabel();
      composer.autoResize();
    },

    updatePrimaryAction(run = null) {
      state.activeRunStatus = run?.status || state.activeRunStatus;
      const running = state.activeRunStatus === "running" || state.activeRunStatus === "queued";
      const input = ui.byKey("messageInput");
      const runButton = ui.byKey("runWorkflow");
      const saveButton = ui.byKey("saveRequirement");

      if (running) {
        if (runButton) {
          runButton.textContent = "Stop";
          runButton.disabled = false;
        }
        if (input) input.placeholder = "Workflow is running. You can still add guidance.";
        if (saveButton) saveButton.disabled = true;
        composer.updateModeLabel();
        composer.autoResize();
        return;
      }

      if (state.activeRunStatus === "failed" && state.activeRunId) {
        if (runButton) {
          runButton.textContent = "Retry";
          runButton.disabled = false;
        }
        if (input) input.placeholder = "Add guidance, then retry if needed...";
        if (saveButton) saveButton.disabled = false;
        composer.updateModeLabel();
        composer.autoResize();
        return;
      }

      composer.setWaiting(state.waitingForInput);
      if (runButton) runButton.disabled = !state.activeSessionId;
    },
  };

  return composer;
}
