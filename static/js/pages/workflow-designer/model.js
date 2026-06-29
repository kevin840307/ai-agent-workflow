import { TemplatePresets } from "../workflow-designer-constants.js?v=20260628-designer-desc1";
import { clone, makeId } from "./utils.js?v=20260629-static-architecture1";

function createStep(overrides = {}) {
  const key = overrides.key || makeId("step");
  const type = inferStepType(overrides);
  const filename = defaultFilename({ ...overrides, key });
  const templatePath = defaultTemplatePath({ ...overrides, key });
  return {
    id: overrides.id || makeId("step"),
    key,
    name: overrides.name || "New Step",
    description: overrides.description || "",
    type,
    enabled: overrides.enabled ?? true,
    agent: overrides.agent || overrides.provider || "qwen",
    provider: overrides.provider || overrides.agent || "qwen",
    command: overrides.command || "",
    sources: clone(overrides.sources || []),
    templatePath,
    templateContent: defaultTemplateContent({ ...overrides, key, type }),
    filename,
    outputFile: overrides.outputFile || "",
    validator: normalizeFunctionId(overrides.validator || ""),
    expectedFiles: clone(overrides.expectedFiles || (filename ? [filename] : [])),
    reviewMode: overrides.reviewMode || "none",
    reviewers: clone(overrides.reviewers || []),
    confidenceThreshold: overrides.confidenceThreshold ?? 0.8,
    passKeywords: overrides.passKeywords || "",
    failKeywords: overrides.failKeywords || "",
    aggregatorFunction: overrides.aggregatorFunction || "",
    maxRetries: overrides.maxRetries ?? 2,
    failAction: overrides.failAction || "same_step",
    retryFromStepKey: overrides.retryFromStepKey || "",
    keepSameSession: overrides.keepSameSession ?? true,
    injectFailureFeedback: overrides.injectFailureFeedback ?? true,
    stopAfterFailures: overrides.stopAfterFailures ?? 1,
    pauseAfterStep: overrides.pauseAfterStep ?? false,
    approvalRequired: overrides.approvalRequired ?? false,
    approvalMessage: overrides.approvalMessage || "",
    timeoutEnabled: overrides.timeoutEnabled ?? false,
    timeoutMinutes: overrides.timeoutMinutes ?? 0,
    allowInteraction: overrides.allowInteraction ?? false,
    agentCount: overrides.agentCount ?? 3,
    agentMaxRetries: overrides.agentMaxRetries ?? 3,
    freshSessionPerAgent: overrides.freshSessionPerAgent ?? true,
    artifactPattern: overrides.artifactPattern || "",
    candidateValidator: overrides.candidateValidator || "",
  };
}

function createWorkflow(overrides = {}) {
  const workflow = {
    id: overrides.id || makeId("workflow"),
    kind: overrides.kind || "custom",
    name: overrides.name || "Untitled Workflow",
    description: overrides.description || "Custom workflow draft.",
    active: overrides.active ?? true,
    skillRoot: overrides.skillRoot || "skills/",
    promptRoot: overrides.promptRoot || "prompts/",
    steps: Array.isArray(overrides.steps) ? overrides.steps.map(normalizeStep) : [],
  };
  if (!workflow.steps.length) {
    workflow.steps.push(createStep({ name: "Generate Spec", key: "generate_spec" }));
  }
  return workflow;
}

function normalizeWorkflow(workflow = {}) {
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

function normalizeStep(step = {}) {
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

function defaultTemplatePath(overrides = {}) {
  const preset = TemplatePresets[overrides.key];
  if (preset?.path) return preset.path;
  const promptSource = (overrides.sources || []).find((source) => source.type === "prompt_file");
  if (promptSource?.value) return promptSource.value;
  return `prompts/${String(overrides.key || "step").replace(/[^a-zA-Z0-9_-]+/g, "_")}.md`;
}

function defaultFilename(overrides = {}) {
  const preset = TemplatePresets[overrides.key];
  if (preset?.filename) return preset.filename;
  if (overrides.filename) return normalizeFilename(overrides.filename);
  if (overrides.outputFile) return normalizeFilename(overrides.outputFile);
  const expected = Array.isArray(overrides.expectedFiles) ? overrides.expectedFiles[0] : "";
  return normalizeFilename(expected || "result.md");
}

function defaultTemplateContent(overrides = {}) {
  const preset = TemplatePresets[overrides.key];
  if (preset?.content) return preset.content;
  if (overrides.templateContent) return overrides.templateContent;
  if (overrides.type === "review") {
    return "FILENAME: review.md\n\nRequirement:\n{{requirement}}\n\nArtifact:\n{{step_output}}";
  }
  if (overrides.type === "validation" || overrides.type === "python") return "";
  return "FILENAME: result.md\n\nProject Context:\n- Project Path: {{project_path}}\n- Workflow Workspace: {{workspace_path}}\n\nRequirement:\n{{requirement}}";
}

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
  normalizeFilename,
};
