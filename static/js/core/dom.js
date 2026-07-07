export const UI = {
  ids: {

    appModalBackdrop: "appModalBackdrop",
    modalCancel: "modalCancel",
    modalClose: "modalClose",
    modalConfirm: "modalConfirm",
    modalDescription: "modalDescription",
    modalHint: "modalHint",
    modalInput: "modalInput",
    modalLabel: "modalLabel",
    modalTextarea: "modalTextarea",
    modalTitle: "modalTitle",
    addGuidance: "addGuidance",
    artifactContent: "artifactContent",
    artifacts: "artifacts",
    advancedMode: "advancedMode",
    artifactSearch: "artifactSearch",
    composerMode: "composerMode",
    currentStep: "currentStep",
    logs: "logs",
    maxRetries: "maxRetries",
    defaultAgent: "defaultAgent",
    messageInput: "messageInput",
    messages: "messages",
    modeChat: "modeChat",
    modeWorkflow: "modeWorkflow",
    newProject: "newProject",
    progressText: "progressText",
    projectList: "projectList",
    qwenAuthType: "qwenAuthType",
    qwenLive: "qwenLive",
    qwenMeta: "qwenMeta",
    qwenReuseSession: "qwenReuseSession",
    resultText: "resultText",
    resetSession: "resetSession",
    resizeDetails: "resizeDetails",
    resizeProjects: "resizeProjects",
    retryRun: "retryRun",
    runMeta: "runMeta",
    runResultPanel: "runResultPanel",
    runProfile: "runProfile",
    runDetail: "runDetail",
    runStatusMeta: "runStatusMeta",
    runWorkflow: "runWorkflow",
    saveRequirement: "saveRequirement",
    sessionTitle: "sessionTitle",
    settingsMenu: "settingsMenu",
    steps: "steps",
    stepDetails: "stepDetails",
    toggleDetails: "toggleDetails",
    toggleProjects: "toggleProjects",
    toggleSettings: "toggleSettings",
    thinkingLevel: "thinkingLevel",
    thinkingDropdownButton: "thinkingDropdownButton",
    thinkingDropdownMenu: "thinkingDropdownMenu",
    thinkingPicker: "thinkingPicker",
    thinkingSelectedLabel: "thinkingSelectedLabel",
    workflowDropdownButton: "workflowDropdownButton",
    workflowDropdownMenu: "workflowDropdownMenu",
    workflowPicker: "workflowPicker",
    workflowSelectedLabel: "workflowSelectedLabel",
    workflowSelect: "workflowSelect",
    validationScript: "validationScript",
    validationScriptField: "validationScriptField",
  },

  el(id) {
    return document.getElementById(id);
  },

  byKey(key) {
    return UI.el(UI.ids[key]);
  },

  on(idOrKey, event, handler) {
    const id = UI.ids[idOrKey] || idOrKey;
    const target = UI.el(id);
    if (target) target.addEventListener(event, handler);
  },

  escapeHtml(value = "") {
    return String(value).replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "\"": "&quot;",
      "'": "&#039;",
    })[char]);
  },

  shortPath(path = "") {
    return path.replace(/^C:\\Users\\kevin\\/i, "~/");
  },

  emptyState(title = "Nothing to show", message = "No data is available yet.", level = "info") {
    return `<div class="ui-empty-state ${UI.escapeHtml(level)}"><strong>${UI.escapeHtml(title)}</strong><span>${UI.escapeHtml(message)}</span></div>`;
  },

  safeText(value, fallback = "-") {
    if (value === null || value === undefined || value === "") return fallback;
    if (typeof value === "object") {
      try { return JSON.stringify(value); } catch (_err) { return fallback; }
    }
    return String(value);
  },
};
