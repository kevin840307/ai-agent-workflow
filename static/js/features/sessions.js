export function createSessions(ctx) {
  const { api, state, ui } = ctx;

  const sessions = {
    renderList() {
      const list = ui.byKey("projectList");
      if (!list) return;
      list.innerHTML = "";
      state.sessions.forEach((session) => {
        const row = document.createElement("div");
        row.className = `project-row ${session.id === state.activeSessionId ? "active" : ""}`;
        row.innerHTML = `
          <button class="project-item">
            <strong>${ui.escapeHtml(session.title || "Project")}</strong>
            <span>${ui.escapeHtml(ui.shortPath(session.project_path || ""))}</span>
          </button>
          <button class="icon-button danger" title="Delete project">×</button>
        `;
        row.querySelector(".project-item").onclick = () => sessions.select(session.id);
        row.querySelector(".danger").onclick = (event) => sessions.delete(event, session.id);
        list.appendChild(row);
      });
    },

    async load() {
      state.sessions = await api.request("/api/sessions");
      if (state.activeSessionId && !state.sessions.some((session) => session.id === state.activeSessionId)) {
        state.activeSessionId = state.sessions[0]?.id || null;
      }
      if (!state.activeSessionId && state.sessions.length) {
        state.activeSessionId = state.sessions[0].id;
      }
      sessions.renderList();
      if (state.activeSessionId) await sessions.select(state.activeSessionId);
      if (!state.activeSessionId) sessions.clearProject();
    },

    clearProject() {
      ui.byKey("sessionTitle").textContent = "Select a project";
      ui.byKey("runMeta").textContent = "No active run";
      ui.byKey("runStatusMeta").textContent = "No active run";
      ui.byKey("messageInput").value = "";
      ui.byKey("runWorkflow").disabled = true;
      ui.byKey("retryRun").disabled = true;
      ui.byKey("addGuidance").disabled = true;
      ui.byKey("messages").innerHTML = "";
      ctx.features.runs.clearPanels();
      ctx.features.layout.applyRunStatus("");
    },

    async refreshList() {
      state.sessions = await api.request("/api/sessions");
      sessions.renderList();
      const session = state.sessions.find((item) => item.id === state.activeSessionId);
      if (session) sessions.renderHeader(session);
    },

    renderHeader(session) {
      ui.byKey("sessionTitle").textContent = session?.title || "Project";
      ui.byKey("runMeta").textContent = ui.shortPath(session?.project_path || "");
      ui.byKey("runStatusMeta").textContent = "No active run";
    },

    async select(sessionId) {
      state.activeSessionId = sessionId;
      state.activeRunId = null;
      ctx.features.eventStream.close();
      sessions.renderList();
      const session = state.sessions.find((item) => item.id === sessionId);
      sessions.renderHeader(session);
      ui.byKey("runWorkflow").disabled = false;
      await ctx.features.messages.load();
      await ctx.features.runs.loadLatest();
    },

    async delete(event, sessionId) {
      event.stopPropagation();
      const session = state.sessions.find((item) => item.id === sessionId);
      if (!confirm(`Delete "${session?.title || "Project"}"?`)) return;
      await api.request(`/api/sessions/${sessionId}`, { method: "DELETE" });
      if (state.activeSessionId === sessionId) {
        state.activeSessionId = null;
        state.activeRunId = null;
        ctx.features.eventStream.close();
      }
      await sessions.load();
    },

    async create() {
      const projectPath = await ctx.features.modal.openInput({
        title: "New Project",
        description: "Create a project session by selecting the source folder Qwen should work with.",
        label: "Project folder path",
        defaultValue: "C:\\Users\\kevin\\sort",
        placeholder: "C:\\Users\\kevin\\sort",
        hint: "Use an absolute local path. Example: C:\\Users\\kevin\\sort",
        confirmText: "Create",
      });
      if (!projectPath) return;
      const session = await api.request("/api/sessions", {
        method: "POST",
        body: JSON.stringify({ project_path: projectPath }),
      });
      state.sessions.unshift(session);
      await sessions.select(session.id);
    },
  };

  return sessions;
}
