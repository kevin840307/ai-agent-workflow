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

      const status = msg.status && !["completed"].includes(msg.status) ? ` [${msg.status}]` : "";
      const content = document.createElement("div");
      content.textContent = `${msg.content || ""}${status}`;
      div.appendChild(content);
      if (msg.role !== "user" && msg.trace) {
        const trace = document.createElement("div");
        trace.className = "message-trace";
        const bits = [
          msg.trace.agent ? `Agent ${msg.trace.agent}` : "",
          Number.isFinite(msg.trace.duration_ms) ? `${(msg.trace.duration_ms / 1000).toFixed(1)}s` : "",
          Number.isFinite(msg.trace.prompt_chars) ? `Prompt ${msg.trace.prompt_chars} chars` : "",
          msg.trace.session_reused ? "reused session" : "fresh session",
        ].filter(Boolean);
        trace.textContent = bits.join(" · ");
        div.appendChild(trace);
      }
      return div;
    },

    renderEmptyState() {
      const list = ui.byKey("messages");
      if (!list || list.querySelector(".message:not(.system)")) return;
      const empty = list.querySelector(".message.system");
      if (empty) {
        empty.textContent = state.runMode === "chat"
          ? "Chat uses the current project session. Send a question or follow-up."
          : "Describe the next change you want the workflow to make.";
      }
    },

    async load(options = {}) {
      const messages = await api.request(`/api/sessions/${state.activeSessionId}/messages`);
      const visibleMessages = messages.filter((msg) => (
        state.runMode === "chat"
          ? msg.kind === "chat"
          : msg.kind !== "chat"
      ));
      const list = ui.byKey("messages");
      list.innerHTML = "";
      state.lastAskText = "";

      visibleMessages.forEach((msg) => list.appendChild(messagesFeature.renderMessage(msg)));

      if (!visibleMessages.length) {
        const div = document.createElement("div");
        div.className = "message system";
        div.textContent = state.runMode === "chat"
          ? `Chat uses the current project session. Send a question or follow-up.`
          : "Describe the next change you want the workflow to make.";
        list.appendChild(div);
      }

      const latest = [...visibleMessages].reverse().find((msg) => msg.role === "user");
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
