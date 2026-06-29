import { BuiltInPromptParams } from "../workflow-designer-constants.js?v=20260628-designer-desc1";
import { escapeHtml, options } from "./utils.js?v=20260629-static-modules2";

function functionOptionsFor(catalog, groupName, fallbackItems, selected) {
  const items = catalog[groupName] || [];
  if (!items.length) return options(fallbackItems, selected);
  const normalized = items.map((item) => [item.id, item.label || item.id]);
  if (selected && !normalized.some(([value]) => String(value) === String(selected))) {
    normalized.unshift([selected, `${selected} (custom)`]);
  }
  return options(groupName === "validators" || groupName === "aggregators" ? [["", "None"], ...normalized] : normalized, selected);
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
  return `
    <div class="designer-function-help">
      <strong>${escapeHtml(meta.label || meta.id)}</strong>
      <span>${escapeHtml(meta.description || "No description provided by backend.")}</span>
    </div>
  `;
}

function workflowFunctionCountsFor(catalog) {
  return {
    validators: (catalog.validators || []).length,
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

export {
  availablePromptParamsFor,
  functionHelpFor,
  functionMetaFor,
  functionOptionsFor,
  workflowFunctionCountsFor,
};
