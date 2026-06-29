// Shared step-tab helpers for workflow designer renderers.
// Capability calculation is config-driven in function-catalog.js; this module
// only applies the resolved capabilities to state/tab UI.

export function tabsForStep(step, capabilities = null) {
  if (!step) return ["basic"];
  if (Array.isArray(capabilities?.tabs) && capabilities.tabs.length) return capabilities.tabs;
  return ["basic", "advanced"];
}

export function ensureActiveTabForStep(state, step, capabilities = null) {
  const tabs = tabsForStep(step, capabilities);
  if (!tabs.includes(state.activeTab)) state.activeTab = tabs[0] || "basic";
}
