export const AppState = {
  sessions: [],
  activeSessionId: null,
  activeRunId: null,
  eventSource: null,
  questionArtifactId: null,
  interactionLoadToken: 0,
  waitingForInput: false,
  activeRunStatus: null,
  lastAskText: "",
  currentArtifacts: [],
};

export const WORKFLOW_STEPS = [
  "Prepare Project",
  "Generate Spec",
  "Validate Spec",
  "Review Spec",
  "Spec Gate",
  "Generate Todo",
  "Validate Todo",
  "Review Todo",
  "Todo Gate",
  "Generate Tests",
  "Build",
  "Run Test",
  "Final Review",
  "Final Gate",
];
