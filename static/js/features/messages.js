export function createMessages(ctx) {
  const { api, state, ui } = ctx;

  const messagesFeature = {
    renderMessage(msg) {
      const div = document.createElement("div");
      const askMatch = msg.role !== "user" ? msg.content.match(/^(.+?) asks:\s*/i) : null;
      const isAsk = Boolean(askMatch);
      div.className = `message ${msg.role === "user" ? "user" : "assistant"}${isAsk ? " ask" : ""}`;

      if (isAsk) {
        const agent = askMatch?.[1] || state.defaultAgent || "Agent";
        const title = document.createElement("strong");
        title.textContent = `${agent} asks`;
        const body = document.createElement("div");
        body.textContent = msg.content.replace(/^(.+?) asks:\s*/i, "");
        div.appendChild(title);
        div.appendChild(body);
        return div;
      }

      div.textContent = msg.content;
      return div;
    },

    renderEmptyState() {
      const list = ui.byKey("messages");
      if (!list || list.querySelector(".message:not(.system)")) return;
      const empty = list.querySelector(".message.system");
      if (empty) {
        empty.textContent = state.runMode === "chat"
          ? `Ask ${state.defaultAgent || "the agent"} anything about this project.`
          : "Describe what you want to build, then run the workflow.";
      }
    },

    async load(options = {}) {
      const messages = await api.request(`/api/sessions/${state.activeSessionId}/messages`);
      const list = ui.byKey("messages");
      list.innerHTML = "";
      state.lastAskText = "";

      messages.forEach((msg) => list.appendChild(messagesFeature.renderMessage(msg)));

      if (!messages.length) {
        const div = document.createElement("div");
        div.className = "message system";
        div.textContent = state.runMode === "chat"
          ? `Ask ${state.defaultAgent || "the agent"} anything about this project.`
          : "Describe what you want to build, then run the workflow.";
        list.appendChild(div);
      }

      const latest = [...messages].reverse().find((msg) => (
        msg.role === "user" && (state.runMode === "chat" || msg.kind !== "chat")
      ));
      if (!options.keepDraft) ui.byKey("messageInput").value = state.runMode === "chat" ? "" : (latest?.content || "");
      ctx.features.composer.autoResize();
      list.scrollTop = list.scrollHeight;
    },

    addLocal(content, role = "user", options = {}) {
      const list = ui.byKey("messages");
      list.querySelector(".message.system")?.remove();
      const div = document.createElement("div");
      div.className = `message ${role === "user" ? "user" : "assistant"}`;
      if (options.temporary) div.dataset.temporary = "true";
      div.textContent = content;
      list.appendChild(div);
      list.scrollTop = list.scrollHeight;
    },

    removeTemporary() {
      ui.byKey("messages").querySelectorAll("[data-temporary='true']").forEach((node) => node.remove());
    },

    renderAsk(text) {
      const content = text || `${state.defaultAgent || "Agent"} needs more information before continuing.`;
      if (content === state.lastAskText) return;

      const existing = Array.from(ui.byKey("messages").querySelectorAll(".message"))
        .some((node) => node.textContent.includes(content));
      if (existing) {
        state.lastAskText = content;
        ui.byKey("messages").scrollTop = ui.byKey("messages").scrollHeight;
        return;
      }

      state.lastAskText = content;
      const ask = document.createElement("div");
      ask.className = "message assistant ask";
      const title = document.createElement("strong");
      title.textContent = `${state.defaultAgent || "Agent"} asks`;
      const body = document.createElement("div");
      body.textContent = content;
      ask.appendChild(title);
      ask.appendChild(body);
      ui.byKey("messages").appendChild(ask);
      ui.byKey("messages").scrollTop = ui.byKey("messages").scrollHeight;
    },
  };

  return messagesFeature;
}
