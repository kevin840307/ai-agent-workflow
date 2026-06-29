import { TemplatePresets } from "../workflow-designer-constants.js?v=20260628-designer-desc1";
import { clone, makeId } from "./utils.js?v=20260629-static-architecture1";

function createStep(overrides = {}
function createWorkflow(overrides = {}
function normalizeWorkflow(workflow) {
  const normalized = {
    id: workflow.id || makeId("workflow"),
    kind: workflow.kind || "custom",
    name: workflow.name || "Untitled Workflow",
    description: workflow.description || "Custom workflow draft.",
    active: Boolean(workflow.active),
    skillRoot: workflow.skillRoot || "skills/",
    promptRoot: workflow.promptRoot || "prompts/",
    steps: Array.isArray(workflow.steps) ? workflow.steps.map(normalizeStep) : [],
  };
  return normalized;
}


function normalizeStep(step) {
  const base = createStep(step || {});
  const type = inferStepType(step || base);
  return {
    ...base,
    ...step,
    type,
    sources: clone(step?.sources || base.sources || []),
    reviewers: clone(step?.reviewers || base.reviewers || []),
    expectedFiles: clone(step?.expectedFiles || base.expectedFiles || []),
    templatePath: step?.templatePath || base.templatePath,
    filename: step?.filename || normalizeFilename(step?.outputFile || base.filename || base.outputFile),
    outputFile: step?.outputFile || base.outputFile || "",
    agent: step?.agent || step?.provider || base.agent || "qwen",
    provider: step?.provider || step?.agent || base.provider || "qwen",
    templateContent: step?.templateContent || base.templateContent,
    validator: normalizeFunctionId(step?.validator || base.validator || ""),
  };
}


function inferStepType(step) {
  if (!step) return "ai";
  if (step.type === "ai" && step.reviewMode && step.reviewMode !== "none") return "review";
  if (step.type === "ai" && String(step.key || "").includes("review")) return "review";
  return step.type || "ai";
}


function normalizeFunctionId(value = "") {
  const raw = String(value || "").trim();
  const aliases = {
    "functions/validate_spec.py": "validate_spec",
    "functions/validate_todo.py": "validate_todo",
    "functions/run_tests.py": "run_pytest",
    "functions/run_pytest.py": "run_pytest",
    "functions/validate.py": "validate_spec",
  };
  return aliases[raw] || raw;
}


function defaultTemplatePath(overrides = {}
function defaultFilename(overrides = {}
function defaultTemplateContent(overrides = {}
function normalizeFilename(value = "") {
  const raw = String(value || "").trim().replace(/\\/g, "/");
  if (!raw) return "";
  return raw.split("/").filter(Boolean).pop() || raw;
}



export {
  createStep,
  createWorkflow,
  normalizeWorkflow,
  normalizeStep,
  inferStepType,
  normalizeFunctionId,
  defaultTemplatePath,
  defaultFilename,
  defaultTemplateContent,
  normalizeFilename
};
