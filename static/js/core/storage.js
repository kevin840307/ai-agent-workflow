const STORAGE_PREFIX = "qwenWorkflow.";

export const StorageKeys = Object.freeze({
  projectsCollapsed: "layout.projectsCollapsed",
  detailsCollapsed: "layout.detailsCollapsed",
  qwenReuseSession: "qwen.reuseSession",
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
};
