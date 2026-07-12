import { LocalStore, StorageKeys } from "./storage.js?v=20260712-ui-v22";

export const AppState = {
  sessions: [],
  activeSessionId: null,
  activeRunId: null,
  eventSource: null,
  eventStreamRunId: null,
  eventStreamConnected: false,
  eventStreamLastErrorAt: 0,
  chatEventSource: null,
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
  selectedWorkflowId: LocalStore.getString(StorageKeys.selectedWorkflowId, "general-auto-development") || "general-auto-development",
  thinkingLevel: LocalStore.getString(StorageKeys.thinkingLevel, "medium") || "medium",
  runProfile: LocalStore.getString(StorageKeys.runProfile, "normal") || "normal",
  advancedMode: LocalStore.getBoolean(StorageKeys.advancedMode, false),
  validationScript: "",
  workflowActivity: null,
  activeRunOverview: null,
  runStateVersions: {},
  diagnosticsLoadedRunId: null,
  executionRecommendation: null,
  appliedExecutionRecommendation: null,
  providerConnectivity: null,
  projectValidationProfile: null,
  unattendedMode: LocalStore.getBoolean(StorageKeys.unattendedMode, true),
};

export function acceptRunSnapshot(state, run) {
  if (!run?.id) return false;
  const version = Number(run.state_version ?? -1);
  if (!Number.isFinite(version) || version < 0) return true;
  const known = Number(state.runStateVersions?.[run.id] ?? -1);
  if (version < known) return false;
  state.runStateVersions ||= {};
  state.runStateVersions[run.id] = version;
  return true;
}
