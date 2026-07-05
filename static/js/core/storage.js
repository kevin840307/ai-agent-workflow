const STORAGE_PREFIX = "qwenWorkflow.";

export const StorageKeys = Object.freeze({
  projectsCollapsed: "layout.projectsCollapsed",
  detailsCollapsed: "layout.detailsCollapsed",
  detailsWidth: "layout.detailsWidth",
  projectsWidth: "layout.projectsWidth",
  qwenReuseSession: "qwen.reuseSession",
  runMode: "ui.runMode",
  selectedWorkflowId: "ui.selectedWorkflowId",
  thinkingLevel: "ui.thinkingLevel",
});

export const LocalStore = {
  getBoolean(key, fallback = false) {
    try {
      const value = window.localStorage.getItem(`${STORAGE_PREFIX}${key}`);
      if (value === null) return fallback;
      return value === "true";
    } catch {
      return fallback;
    }
  },

  setBoolean(key, value) {
    try {
      window.localStorage.setItem(`${STORAGE_PREFIX}${key}`, String(Boolean(value)));
    } catch {
      // localStorage may be disabled in private / restricted browser modes.
    }
  },

  getString(key, fallback = "") {
    try {
      const value = window.localStorage.getItem(`${STORAGE_PREFIX}${key}`);
      return value === null ? fallback : value;
    } catch {
      return fallback;
    }
  },

  setString(key, value) {
    try {
      window.localStorage.setItem(`${STORAGE_PREFIX}${key}`, String(value ?? ""));
    } catch {
      // localStorage may be disabled in private / restricted browser modes.
    }
  },
};
