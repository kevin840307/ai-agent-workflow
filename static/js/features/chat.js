import { LocalStore, StorageKeys } from "../core/storage.js?v=20260704-metadata1";

export function createChat(ctx) {
  const { api, state, ui } = ctx;

  const chat = {
    closeStream() {
      if (state.chatEventSource) {
        state.chatEventSource.close();
        state.chatEventSource = null;
      }
    },

    openStream(sessionId) {
      chat.closeStream();
      let hasOutput = false;
      state.chatEventSource = new EventSource(`/api/sessions/${encodeURIComponent(sessionId)}/chat-events`);
      state.chatEventSource.onmessage = (message) => {
        const event = JSON.parse(message.data);
        const agent = event.agent || state.defaultAgent || "Agent";
        if (event.type === "agent_status") {
          ctx.features.messages.updateTemporary(`[${agent}] ${event.message || "thinking..."}`);
          return;
        }
        if (event.type === "agent_output") {
          const text = event.stream === "thinking"
            ? `\n[thinking] ${event.text}`
            : event.text;
          ctx.features.messages.updateTemporary(hasOutput ? text : `${agent}:\n${text}`, { append: hasOutput });
          hasOutput = true;
          return;
        }
        if (["done", "failed", "cancelled"].includes(event.type)) {
          chat.closeStream();
        }
      };
      state.chatEventSource.onerror = () => chat.closeStream();
    },

    setMode(mode) {
      state.runMode = mode === "chat" ? "chat" : "workflow";
      LocalStore.setString(StorageKeys.runMode, state.runMode);
      document.body.classList.toggle("chat-mode", state.runMode === "chat");
      document.body.classList.toggle("workflow-mode", state.runMode === "workflow");

      const workflowButton = ui.byKey("modeWorkflow");
      const chatButton = ui.byKey("modeChat");
      const workflowPicker = ui.byKey("workflowPicker");
      if (workflowButton) workflowButton.classList.toggle("active", state.runMode === "workflow");
      if (chatButton) chatButton.classList.toggle("active", state.runMode === "chat");
      if (workflowPicker) workflowPicker.hidden = state.runMode !== "workflow";

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
      const clientRequestId = crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;

      state.chatBusy = true;
      ctx.features.composer.updatePrimaryAction();
      input.value = "";
      ctx.features.composer.autoResize();
      ctx.features.messages.addLocal(content, "user");
      ctx.features.messages.addLocal(`${state.defaultAgent || "Agent"} is thinking...`, "assistant", { temporary: true });
      chat.openStream(state.activeSessionId);

      try {
        await api.request(`/api/sessions/${state.activeSessionId}/chat`, {
          method: "POST",
          body: JSON.stringify({ content, clientRequestId }),
        });
        await ctx.features.messages.load({ keepDraft: true });
        await ctx.features.sessions.refreshList();
      } catch (err) {
        ctx.features.messages.removeTemporary();
        ctx.features.messages.addLocal(`Chat failed: ${err.message}`, "assistant");
      } finally {
        chat.closeStream();
        state.chatBusy = false;
        ctx.features.composer.updatePrimaryAction();
      }
    },
  };

  return chat;
}
