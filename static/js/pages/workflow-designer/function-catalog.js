import { BuiltInPromptParams } from "../workflow-designer-constants.js?v=20260704-metadata1";
import { escapeHtml, options } from "./utils.js?v=20260704-metadata1";

const STEP_TYPE_UI_DEFAULTS = Object.freeze({
  ai: { supportsPrompt: true, supportsAgent: true, promptDefaults: true, tabs: ["basic", "sources", "retry", "advanced"] },
  command: { supportsPrompt: true, supportsAgent: true, promptDefaults: true, tabs: ["basic", "sources", "retry", "advanced"] },
  review: { supportsPrompt: false, supportsAgent: true, promptDefaults: false, tabs: ["basic", "review", "retry", "advanced"] },
  validation: { supportsPrompt: false, supportsAgent: false, promptDefaults: false, tabs: ["basic", "retry", "advanced"] },
  python: { supportsPrompt: false, supportsAgent: false, promptDefaults: false, tabs: ["basic", "retry", "advanced"] },
  gate: { supportsPrompt: false, supportsAgent: false, promptDefaults: false, tabs: ["basic", "gate", "retry", "advanced"] },
  manual: { supportsPrompt: false, supportsAgent: false, promptDefaults: false, tabs: ["basic", "gate", "retry", "advanced"] },
});

function functionOptionsFor(catalog, groupName, fallbackItems, selected) {
  const items = catalog[groupName] || [];
  if (!items.length) return options(fallbackItems, selected);
  const normalized = items.map((item) => [item.id, item.label || item.id]);
  if (selected && !normalized.some(([value]) => String(value) === String(selected))) {
    normalized.unshift([selected, `${selected} (custom)`]);
  }
  return options(groupName === "functions" || groupName === "aggregators" ? [["", "None"], ...normalized] : normalized, selected);
}

function functionMetaFor(catalog, groupName, selected) {
  const items = catalog[groupName] || [];
  return items.find((item) => String(item.id) === String(selected)) || null;
}

function functionHelpFor(catalog, groupName, selected, emptyText = "Select a backend function.") {
  const meta = functionMetaFor(catalog, groupName, selected);
  if (!selected) {
    return `<div class="designer-function-help"><strong>No function selected</strong><span>${escapeHtml(emptyText)}</span></div>`;
  }
  if (!meta) {
    return `<div class="designer-function-help"><strong>${escapeHtml(selected)}</strong><span>Custom function id. Make sure the backend knows how to execute it.</span></div>`;
  }
  const uiNote = meta.ui?.note ? `<span>${escapeHtml(meta.ui.note)}</span>` : "";
  return `
    <div class="designer-function-help">
      <strong>${escapeHtml(meta.label || meta.id)}</strong>
      <span>${escapeHtml(meta.description || "No description provided by backend.")}</span>
      ${uiNote}
    </div>
  `;
}

function workflowFunctionCountsFor(catalog) {
  return {
    functions: (catalog.functions || []).length,
    reviewStrategies: (catalog.reviewStrategies || []).length,
    aggregators: (catalog.aggregators || []).length,
    promptParams: availablePromptParamsFor(catalog).length,
  };
}

function availablePromptParamsFor(catalog) {
  const merged = [];
  const seen = new Set();
  const add = (param) => {
    const key = String(param?.key || param?.id || "").trim();
    if (!key || seen.has(key)) return;
    seen.add(key);
    merged.push({
      key,
      label: param.label || key,
      description: param.description || "Provided by backend runtime context.",
      sample: param.sample ?? param.example ?? `[${key}]`,
    });
  };
  BuiltInPromptParams.forEach(add);
  (catalog.promptParams || []).forEach(add);
  return merged;
}

function stepFunctionSelection(step = {}) {
  const type = String(step?.type || "ai");
  if (type === "validation" || type === "python") {
    return { groupName: "functions", id: step.function || "" };
  }
  if (type === "review") {
    return { groupName: "reviewStrategies", id: step.reviewMode || "" };
  }
  if (type === "gate" || type === "manual") {
    return { groupName: "functions", id: step.function || "" };
  }
  return { groupName: "", id: "" };
}

function defaultStepUiFor(step = {}) {
  const type = String(step?.type || "ai");
  const defaults = STEP_TYPE_UI_DEFAULTS[type] || { supportsPrompt: false, supportsAgent: false, promptDefaults: false, tabs: ["basic", "advanced"] };
  return {
    ...defaults,
    tabs: [...defaults.tabs],
    source: "step-type",
    groupName: "",
    functionId: "",
    functionMeta: null,
  };
}

function normalizedFunctionUi(meta) {
  if (!meta) return {};
  const ui = meta.ui && typeof meta.ui === "object" ? meta.ui : {};
  return {
    ...(typeof meta.supportsPrompt === "boolean" ? { supportsPrompt: meta.supportsPrompt } : {}),
    ...(typeof meta.supportsAgent === "boolean" ? { supportsAgent: meta.supportsAgent } : {}),
    ...(Array.isArray(meta.tabs) ? { tabs: meta.tabs } : {}),
    ...(typeof meta.promptDefaults === "boolean" ? { promptDefaults: meta.promptDefaults } : {}),
    ...(typeof ui.supportsPrompt === "boolean" ? { supportsPrompt: ui.supportsPrompt } : {}),
    ...(typeof ui.supportsAgent === "boolean" ? { supportsAgent: ui.supportsAgent } : {}),
    ...(Array.isArray(ui.tabs) ? { tabs: ui.tabs } : {}),
    ...(typeof ui.promptDefaults === "boolean" ? { promptDefaults: ui.promptDefaults } : {}),
    ...(ui.note ? { note: ui.note } : {}),
  };
}

function isLegacyConsensusAgentStep(step) {
  return Boolean(
    step &&
      ((step.function === "consensus_agent") ||
        step.key === "consensus_agent" ||
        step.key === "consensus_security_scan")
  );
}

function stepUiCapabilitiesFor(catalog, step = {}) {
  const capabilities = defaultStepUiFor(step);
  const selection = stepFunctionSelection(step);
  const meta = selection.groupName ? functionMetaFor(catalog, selection.groupName, selection.id) : null;
  const ui = normalizedFunctionUi(meta);
  Object.assign(capabilities, ui);
  capabilities.tabs = Array.isArray(ui.tabs) ? [...ui.tabs] : capabilities.tabs;
  capabilities.groupName = selection.groupName;
  capabilities.functionId = selection.id;
  capabilities.functionMeta = meta;
  capabilities.source = meta ? "function-catalog" : capabilities.source;

  // Backward compatibility for old saved workflow JSON while the catalog is loading
  // or when a user imports a legacy consensus step with only a special key.
  if (!meta && isLegacyConsensusAgentStep(step)) {
    capabilities.supportsPrompt = true;
    capabilities.supportsAgent = true;
    capabilities.promptDefaults = true;
    capabilities.tabs = ["basic", "sources", "retry", "advanced"];
    capabilities.source = "legacy-consensus";
  }

  return capabilities;
}

function tabsForStepCapabilities(capabilities) {
  return Array.isArray(capabilities?.tabs) && capabilities.tabs.length ? capabilities.tabs : ["basic", "advanced"];
}

export {
  availablePromptParamsFor,
  functionHelpFor,
  functionMetaFor,
  functionOptionsFor,
  stepUiCapabilitiesFor,
  tabsForStepCapabilities,
  workflowFunctionCountsFor,
};
