export function createChat(ctx) {
  const { api, state, ui } = ctx;

  const chat = {
    setMode(mode) {
      state.runMode = mode === "chat" ? "chat" : "workflow";
      document.body.classList.toggle("chat-mode", state.runMode === "chat");
      document.body.classList.toggle("workflow-mode", state.runMode === "workflow");

      const workflowButton = ui.byKey("modeWorkflow");
      const chatButton = ui.byKey("modeChat");
      if (workflowButton) workflowButton.classList.toggle("active", state.runMode === "workflow");
      if (chatButton) chatButton.classList.toggle("active", state.runMode === "chat");

      ctx.features.composer.updatePrimaryAction();
      ctx.features.messages.renderEmptyState();
      if (state.activeSessionId) {
        ctx.features.messages.load().catch((err) => ctx.features.messages.addLocal(`Load failed: ${err.message}`, "assistant"));
      }
    },

    async submit() {
      if (state.runMode !== "chat") {
        await ctx.features.runs.start();
        return;
      }
      if (!state.activeSessionId || state.chatBusy) return;

      const input = ui.byKey("messageInput");
      const content = input.value.trim();
      if (!content) return;

      state.chatBusy = true;
      ctx.features.composer.updatePrimaryAction();
      input.value = "";
      ctx.features.composer.autoResize();
      ctx.features.messages.addLocal(content, "user");
      ctx.features.messages.addLocal("Qwen is thinking...", "assistant", { temporary: true });

      try {
        await api.request(`/api/sessions/${state.activeSessionId}/chat`, {
          method: "POST",
          body: JSON.stringify({ content }),
        });
        await ctx.features.messages.load({ keepDraft: true });
        await ctx.features.sessions.refreshList();
      } catch (err) {
        ctx.features.messages.removeTemporary();
        ctx.features.messages.addLocal(`Chat failed: ${err.message}`, "assistant");
      } finally {
        state.chatBusy = false;
        ctx.features.composer.updatePrimaryAction();
      }
    },
  };

  return chat;
}
