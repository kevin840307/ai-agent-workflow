import { LocalStore, StorageKeys } from "./storage.js?v=20260630-stability1";

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
  selectedStepKey: null,
  selectedStepArtifactId: null,
  runMode: LocalStore.getString(StorageKeys.runMode, "workflow") === "chat" ? "chat" : "workflow",
  chatBusy: false,
  defaultAgent: "agent",
  workflows: [],
  selectedWorkflowId: LocalStore.getString(StorageKeys.selectedWorkflowId, "system-controlled-qwen") || "system-controlled-qwen",
};
