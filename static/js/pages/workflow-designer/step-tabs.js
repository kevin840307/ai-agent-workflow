// Shared step-tab rules for workflow designer renderers.
// Keep this logic outside individual renderers so split modules stay in sync.

export function tabsForStep(step) {
  if (!step) return ["basic"];
  if (isConsensusAgentStep(step)) return ["basic", "sources", "retry", "advanced"];
  const byType = {
    ai: ["basic", "sources", "retry", "advanced"],
    command: ["basic", "sources", "retry", "advanced"],
    validation: ["basic", "retry", "advanced"],
    python: ["basic", "retry", "advanced"],
    review: ["basic", "review", "retry", "advanced"],
    gate: ["basic", "gate", "retry", "advanced"],
    manual: ["basic", "gate", "retry", "advanced"],
  };
  return byType[step.type] || ["basic", "advanced"];
}

export function isConsensusAgentStep(step) {
  return Boolean(
    step &&
      (step.validator === "consensus_agent" ||
        step.key === "consensus_agent" ||
        step.key === "consensus_security_scan")
  );
}

export function ensureActiveTabForStep(state, step) {
  const tabs = tabsForStep(step);
  if (!tabs.includes(state.activeTab)) state.activeTab = tabs[0] || "basic";
}
