import { LocalStore } from "../core/storage.js?v=20260702-assets-bugfix1";

const COLLAPSED_PROJECTS_KEY = "ui.collapsedProjectKeys";

export function createSessions(ctx) {
  const { api, state, ui } = ctx;
  let menuDismissBound = false;

  function projectKey(session) {
    return (session.project_path || session.id || "").toLowerCase();
  }

  function isGeneratedChatTitle(title) {
    return !title || title === "Main chat" || /^Chat \d+$/i.test(title);
  }

  function groupSessions() {
    const groups = [];
    const byPath = new Map();
    state.sessions.forEach((session) => {
      const key = projectKey(session);
      if (!byPath.has(key)) {
        const group = {
          key,
          title: session.title || "Project",
          projectPath: session.project_path || "",
          sessions: [],
        };
        byPath.set(key, group);
        groups.push(group);
      }
      const group = byPath.get(key);
      if (isGeneratedChatTitle(group.title) && !isGeneratedChatTitle(session.title || "")) {
        group.title = session.title;
      }
      group.sessions.push(session);
    });
    return groups;
  }

  function collapsedProjects() {
    try {
      const value = JSON.parse(LocalStore.getString(COLLAPSED_PROJECTS_KEY, "[]"));
      return new Set(Array.isArray(value) ? value : []);
    } catch {
      return new Set();
    }
  }

  function storeCollapsedProjects(keys) {
    LocalStore.setString(COLLAPSED_PROJECTS_KEY, JSON.stringify([...keys]));
  }

  function chatLabel(session, group, index) {
    const title = session.title || "";
    if (title === group.title) return "Main chat";
    if (!title) return index === 0 ? "Main chat" : `Chat ${index + 1}`;
    return title;
  }

  function closeProjectMenus(except = null) {
    const list = ui.byKey("projectList");
    if (!list) return;
    list.querySelectorAll(".project-action-menu").forEach((node) => {
      if (node !== except) node.hidden = true;
    });
  }

  function ensureMenuDismissHandlers() {
    if (menuDismissBound) return;
    menuDismissBound = true;
    document.addEventListener("pointerdown", (event) => {
      if (event.target.closest?.(".project-root-row")) return;
      closeProjectMenus();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeProjectMenus();
    });
  }

  const sessions = {
    renderList() {
      const list = ui.byKey("projectList");
      if (!list) return;
      ensureMenuDismissHandlers();
      list.innerHTML = "";
      groupSessions().forEach((group) => {
        const activeInProject = group.sessions.some((session) => session.id === state.activeSessionId);
        const collapsedKeys = collapsedProjects();
        const collapsed = collapsedKeys.has(group.key);
        const project = document.createElement("section");
        project.className = `project-tree ${activeInProject ? "active" : ""} ${collapsed ? "collapsed" : ""}`;
        project.innerHTML = `
          <div class="project-root-row">
            <button class="project-root" title="${ui.escapeHtml(group.projectPath || group.title)}" aria-expanded="${collapsed ? "false" : "true"}">
              <span class="project-caret" aria-hidden="true">${collapsed ? ">" : "v"}</span>
              <strong>${ui.escapeHtml(group.title)}</strong>
            </button>
            <button class="project-menu-button" title="Project actions" aria-label="Project actions">
              <span aria-hidden="true"></span>
            </button>
            <div class="project-action-menu" hidden>
              <button data-action="new-chat">New chat</button>
              <button data-action="delete-project" class="danger-text">Delete project</button>
            </div>
          </div>
          <div class="project-children" ${collapsed ? "hidden" : ""}></div>
        `;
        project.querySelector(".project-root").onclick = () => sessions.toggleProject(group);
        project.querySelector(".project-menu-button").onclick = (event) => {
          event.stopPropagation();
          const menu = project.querySelector(".project-action-menu");
          const shouldOpen = menu.hidden;
          closeProjectMenus(menu);
          menu.hidden = !shouldOpen;
        };
        project.querySelector("[data-action='new-chat']").onclick = (event) => sessions.createChat(event, group);
        project.querySelector("[data-action='delete-project']").onclick = (event) => sessions.deleteProject(event, group);

        const children = project.querySelector(".project-children");
        group.sessions.forEach((session, index) => {
          const row = document.createElement("div");
          row.className = `project-row child-row ${session.id === state.activeSessionId ? "active" : ""}`;
          row.innerHTML = `
            <button class="project-item">
              <span class="chat-dot" aria-hidden="true"></span>
              <strong>${ui.escapeHtml(chatLabel(session, group, index))}</strong>
            </button>
            <button class="icon-button danger" title="Delete chat">x</button>
          `;
          row.querySelector(".project-item").onclick = () => sessions.select(session.id);
          row.querySelector(".danger").onclick = (event) => sessions.delete(event, session.id);
          children.appendChild(row);
        });
        list.appendChild(project);
      });
    },

    toggleProject(group) {
      const keys = collapsedProjects();
      if (keys.has(group.key)) {
        keys.delete(group.key);
      } else {
        keys.add(group.key);
      }
      storeCollapsedProjects(keys);
      sessions.renderList();
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
      ctx.features.composer.updatePrimaryAction();
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
      state.activeRunStatus = null;
      state.waitingForInput = false;
      ctx.features.eventStream.close();
      sessions.renderList();
      const session = state.sessions.find((item) => item.id === sessionId);
      sessions.renderHeader(session);
      ctx.features.composer.updatePrimaryAction();
      await ctx.features.messages.load();
      await ctx.features.runs.loadLatest();
      ctx.features.composer.updatePrimaryAction();
    },

    async delete(event, sessionId) {
      event.stopPropagation();
      const session = state.sessions.find((item) => item.id === sessionId);
      if (!confirm(`Delete "${session?.title || "Chat"}"?`)) return;
      await api.request(`/api/sessions/${sessionId}`, { method: "DELETE" });
      if (state.activeSessionId === sessionId) {
        state.activeSessionId = null;
        state.activeRunId = null;
        ctx.features.eventStream.close();
      }
      await sessions.load();
    },

    async deleteProject(event, group) {
      event.stopPropagation();
      if (!confirm(`Delete project "${group.title}" and all ${group.sessions.length} chat session(s)?`)) return;
      const activeDeleted = group.sessions.some((session) => session.id === state.activeSessionId);
      for (const session of group.sessions) {
        await api.request(`/api/sessions/${session.id}`, { method: "DELETE" });
      }
      if (activeDeleted) {
        state.activeSessionId = null;
        state.activeRunId = null;
        ctx.features.eventStream.close();
      }
      await sessions.load();
    },

    async createChat(event, group) {
      event.stopPropagation();
      const keys = collapsedProjects();
      keys.delete(group.key);
      storeCollapsedProjects(keys);
      const title = `Chat ${group.sessions.length + 1}`;
      const session = await api.request("/api/sessions", {
        method: "POST",
        body: JSON.stringify({ project_path: group.projectPath, title }),
      });
      state.sessions.unshift(session);
      await sessions.select(session.id);
    },

    async create() {
      const title = await ctx.features.modal.openInput({
        title: "New Project",
        description: "Name this project so it is easy to find later.",
        label: "Project title",
        defaultValue: "",
        placeholder: "Example: Bubble Sort",
        hint: "You can rename by creating a new project with a clearer title.",
        confirmText: "Next",
      });
      if (!title) return;
      const projectPath = await ctx.features.modal.openInput({
        title: "New Project",
        description: "Create a project session by selecting the source folder the agent should work with.",
        label: "Project folder path",
        defaultValue: "C:\\Users\\kevin\\sort",
        placeholder: "C:\\Users\\kevin\\sort",
        hint: "Use an absolute local path. Example: C:\\Users\\kevin\\sort",
        confirmText: "Create",
      });
      if (!projectPath) return;
      const session = await api.request("/api/sessions", {
        method: "POST",
        body: JSON.stringify({ project_path: projectPath, title }),
      });
      state.sessions.unshift(session);
      await sessions.select(session.id);
    },

    async resetActive() {
      if (!state.activeSessionId) return;
      const session = state.sessions.find((item) => item.id === state.activeSessionId);
      if (!session) return;
      if (!confirm(`Reset "${session.title || "Project"}"? This clears messages, runs, retry state, artifacts, and starts a new agent session without creating a new project.`)) return;

      ctx.features.eventStream.close();
      const resetSession = await api.request(`/api/sessions/${state.activeSessionId}/reset`, {
        method: "POST",
        body: JSON.stringify({}),
      });

      state.activeRunId = null;
      state.activeRunStatus = null;
      state.waitingForInput = false;
      state.lastAskText = "";
      state.currentArtifacts = [];
      state.selectedStepKey = null;
      state.selectedStepArtifactId = null;
      state.sessions = state.sessions.map((item) => (item.id === resetSession.id ? resetSession : item));
      await sessions.select(resetSession.id);
    },
  };

  return sessions;
}
