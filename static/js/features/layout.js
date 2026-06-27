import { LocalStore, StorageKeys } from "../core/storage.js";

function updateProjectsButton(ui, collapsed) {
  const button = ui.byKey("toggleProjects");
  if (!button) return;
  button.classList.toggle("active", collapsed);
  button.textContent = collapsed ? ">" : "<";
  button.title = collapsed ? "Expand projects" : "Collapse projects";
  button.setAttribute("aria-label", button.title);
  button.setAttribute("aria-pressed", String(collapsed));
}

function updateDetailsButton(ui, collapsed) {
  const button = ui.byKey("toggleDetails");
  if (!button) return;
  button.classList.toggle("active", collapsed);
  const mark = button.querySelector(".icon-mark");
  if (mark) mark.textContent = collapsed ? "<" : ">";
  button.title = collapsed ? "Expand details" : "Collapse details";
  button.setAttribute("aria-label", button.title);
  button.setAttribute("aria-pressed", String(collapsed));
}

export function createLayout(ctx) {
  const { ui } = ctx;

  const layout = {
    restorePreferences() {
      layout.setProjectsCollapsed(LocalStore.getBoolean(StorageKeys.projectsCollapsed, false), false);
      layout.setDetailsCollapsed(LocalStore.getBoolean(StorageKeys.detailsCollapsed, false), false);
    },

    applyRunStatus(status = "") {
      document.body.classList.remove("run-running", "run-waiting", "run-failed");
      if (["running", "queued"].includes(status)) document.body.classList.add("run-running");
      if (status === "waiting_input") document.body.classList.add("run-waiting");
      if (status === "failed") document.body.classList.add("run-failed");
    },

    setProjectsCollapsed(collapsed, persist = true) {
      document.body.classList.toggle("projects-collapsed", collapsed);
      updateProjectsButton(ui, collapsed);
      if (persist) LocalStore.setBoolean(StorageKeys.projectsCollapsed, collapsed);
    },

    toggleProjects() {
      layout.setProjectsCollapsed(!document.body.classList.contains("projects-collapsed"));
    },

    toggleSettings(force = null) {
      const header = document.querySelector(".header");
      const button = ui.byKey("toggleSettings");
      if (!header || !button) return;
      const open = force === null ? !header.classList.contains("settings-open") : force;
      header.classList.toggle("settings-open", open);
      button.classList.toggle("active", open);
      button.setAttribute("aria-expanded", String(open));
    },

    setDetailsCollapsed(collapsed, persist = true) {
      document.body.classList.toggle("details-collapsed", collapsed);
      updateDetailsButton(ui, collapsed);
      if (persist) LocalStore.setBoolean(StorageKeys.detailsCollapsed, collapsed);
    },

    toggleDetails() {
      layout.setDetailsCollapsed(!document.body.classList.contains("details-collapsed"));
    },

    activateTab(panelId) {
      if (document.body.classList.contains("details-collapsed")) layout.setDetailsCollapsed(false);
      document.querySelectorAll(".tab").forEach((tab) => {
        tab.classList.toggle("active", tab.dataset.tab === panelId);
      });
      document.querySelectorAll(".panel").forEach((panel) => {
        panel.classList.toggle("active", panel.id === panelId);
      });
    },
  };

  return layout;
}
