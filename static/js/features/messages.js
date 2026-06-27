export function createMessages(ctx) {
  const { api, state, ui } = ctx;

  const messagesFeature = {
    renderMessage(msg) {
      const div = document.createElement("div");
      const isAsk = msg.role !== "user" && msg.content.startsWith("Qwen asks:");
      div.className = `message ${msg.role === "user" ? "user" : "assistant"}${isAsk ? " ask" : ""}`;

      if (isAsk) {
        const title = document.createElement("strong");
        title.textContent = "Qwen asks";
        const body = document.createElement("div");
        body.textContent = msg.content.replace(/^Qwen asks:\s*/i, "");
        div.appendChild(title);
        div.appendChild(body);
        return div;
      }

      div.textContent = msg.content;
      return div;
    },

    async load() {
      const messages = await api.request(`/api/sessions/${state.activeSessionId}/messages`);
      const list = ui.byKey("messages");
      list.innerHTML = "";
      state.lastAskText = "";

      messages.forEach((msg) => list.appendChild(messagesFeature.renderMessage(msg)));

      if (!messages.length) {
        const div = document.createElement("div");
        div.className = "message system";
        div.textContent = "Describe what you want to build, then run the workflow.";
        list.appendChild(div);
      }

      const latest = [...messages].reverse().find((msg) => msg.role === "user");
      ui.byKey("messageInput").value = latest?.content || "";
      ctx.features.composer.autoResize();
      list.scrollTop = list.scrollHeight;
    },

    addLocal(content, role = "user") {
      const list = ui.byKey("messages");
      const div = document.createElement("div");
      div.className = `message ${role === "user" ? "user" : "assistant"}`;
      div.textContent = content;
      list.appendChild(div);
      list.scrollTop = list.scrollHeight;
    },

    renderAsk(text) {
      const content = text || "Qwen needs more information before continuing.";
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
      title.textContent = "Qwen asks";
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
