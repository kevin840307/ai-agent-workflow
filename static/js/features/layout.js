import { LocalStore, StorageKeys } from "../core/storage.js?v=20260712-ui-v22";

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

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function numberFromStore(key) {
  const value = Number(LocalStore.getString(key, ""));
  return Number.isFinite(value) && value > 0 ? value : null;
}

export function createLayout(ctx) {
  const { ui } = ctx;
  let resizeBound = false;

  function setRailWidth(side, width, persist = true) {
    const viewport = window.innerWidth || 1280;
    const limits = side === "projects"
      ? { min: 180, max: Math.min(440, Math.max(220, viewport * 0.45)) }
      : { min: 300, max: Math.min(760, Math.max(360, viewport * 0.58)) };
    const next = Math.round(clamp(width, limits.min, limits.max));
    const property = side === "projects" ? "--rail-left" : "--rail-right";
    const key = side === "projects" ? StorageKeys.projectsWidth : StorageKeys.detailsWidth;
    document.documentElement.style.setProperty(property, `${next}px`);
    if (persist) LocalStore.setString(key, String(next));
  }

  function restoreRailWidths() {
    const projectsWidth = numberFromStore(StorageKeys.projectsWidth);
    const detailsWidth = numberFromStore(StorageKeys.detailsWidth);
    if (projectsWidth) setRailWidth("projects", projectsWidth, false);
    if (detailsWidth) setRailWidth("details", detailsWidth, false);
  }

  function beginResize(side, event) {
    event.preventDefault();
    if (side === "projects" && document.body.classList.contains("projects-collapsed")) return;
    if (side === "details" && document.body.classList.contains("details-collapsed")) return;
    document.body.classList.add("rail-resizing");

    const onMove = (moveEvent) => {
      const width = side === "projects"
        ? moveEvent.clientX
        : window.innerWidth - moveEvent.clientX;
      setRailWidth(side, width, false);
    };

    const onUp = (upEvent) => {
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", onUp);
      document.body.classList.remove("rail-resizing");
      const width = side === "projects"
        ? upEvent.clientX
        : window.innerWidth - upEvent.clientX;
      setRailWidth(side, width, true);
    };

    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp, { once: true });
  }

  function nudgeRail(side, delta) {
    const current = side === "projects"
      ? document.querySelector(".projects")?.getBoundingClientRect().width
      : document.querySelector(".details")?.getBoundingClientRect().width;
    if (!current) return;
    setRailWidth(side, current + delta, true);
  }

  function bindRailResize() {
    if (resizeBound) return;
    resizeBound = true;
    ui.byKey("resizeProjects")?.addEventListener("pointerdown", (event) => beginResize("projects", event));
    ui.byKey("resizeDetails")?.addEventListener("pointerdown", (event) => beginResize("details", event));
    ui.byKey("resizeProjects")?.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      event.preventDefault();
      if (event.key === "ArrowLeft") nudgeRail("projects", -16);
      if (event.key === "ArrowRight") nudgeRail("projects", 16);
    });
    ui.byKey("resizeDetails")?.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      event.preventDefault();
      if (event.key === "ArrowLeft") nudgeRail("details", 16);
      if (event.key === "ArrowRight") nudgeRail("details", -16);
    });
  }

  const layout = {
    restorePreferences() {
      restoreRailWidths();
      bindRailResize();
      layout.setProjectsCollapsed(LocalStore.getBoolean(StorageKeys.projectsCollapsed, false), false);
      layout.setDetailsCollapsed(LocalStore.getBoolean(StorageKeys.detailsCollapsed, false), false);
      layout.setAdvancedMode(ctx.state.advancedMode, false);
      const unattended = ui.byKey("unattendedMode");
      if (unattended) unattended.checked = Boolean(ctx.state.unattendedMode);
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



    setAdvancedMode(enabled, persist = true) {
      ctx.state.advancedMode = Boolean(enabled);
      document.body.classList.toggle("advanced-mode", ctx.state.advancedMode);
      document.body.classList.toggle("novice-mode", !ctx.state.advancedMode);
      const checkbox = ui.byKey("advancedMode");
      if (checkbox) checkbox.checked = ctx.state.advancedMode;
      if (persist) LocalStore.setBoolean(StorageKeys.advancedMode, ctx.state.advancedMode);
      if (ctx.features.workflows?.renderPreview) ctx.features.workflows.renderPreview();
    },

    activateTab(panelId) {
      if (document.body.classList.contains("details-collapsed")) layout.setDetailsCollapsed(false);
      document.querySelectorAll(".tab").forEach((tab) => {
        tab.classList.toggle("active", tab.dataset.tab === panelId);
      });
      document.querySelectorAll(".panel").forEach((panel) => {
        const active = panel.id === panelId;
        panel.classList.toggle("active", active);
        panel.hidden = !active;
      });
      document.body.classList.remove("details-focus-mode");
    },
  };

  return layout;
}
