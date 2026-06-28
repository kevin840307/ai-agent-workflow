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
    artifactSearch: "artifactSearch",
    composerMode: "composerMode",
    currentStep: "currentStep",
    logs: "logs",
    maxRetries: "maxRetries",
    messageInput: "messageInput",
    messages: "messages",
    modeChat: "modeChat",
    modeWorkflow: "modeWorkflow",
    newProject: "newProject",
    openArtifactTab: "openArtifactTab",
    progressText: "progressText",
    projectList: "projectList",
    qwenAuthType: "qwenAuthType",
    qwenLive: "qwenLive",
    qwenMeta: "qwenMeta",
    qwenReuseSession: "qwenReuseSession",
    resultText: "resultText",
    resetSession: "resetSession",
    retryRun: "retryRun",
    runMeta: "runMeta",
    runStatusMeta: "runStatusMeta",
    runWorkflow: "runWorkflow",
    saveRequirement: "saveRequirement",
    sessionTitle: "sessionTitle",
    settingsMenu: "settingsMenu",
    stepArtifactContent: "stepArtifactContent",
    stepArtifactList: "stepArtifactList",
    stepArtifactTitle: "stepArtifactTitle",
    steps: "steps",
    toggleDetails: "toggleDetails",
    toggleProjects: "toggleProjects",
    toggleSettings: "toggleSettings",
    workflowPicker: "workflowPicker",
    workflowSelect: "workflowSelect",
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
};
