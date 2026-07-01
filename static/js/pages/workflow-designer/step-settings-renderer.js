import { tabsForStep } from "./step-tabs.js?v=20260701-step-detail-polish1";

export function installStepSettingsRenderer(ctx) {
  const {
    FailActions,
    ReviewModes,
    SourceTypes,
    StepTypes,
    el,
    escapeAttr,
    escapeHtml,
    formatStepType,
    functionHelp,
    functionOptions,
    getSelectedStep,
    getSelectedWorkflow,
    getTemplateDiagnostics,
    isReadonly,
    normalizeFilename,
    options,
    state,
    stepUiCapabilities,
  } = ctx;

function renderSettings() {
  const targets = [el("designerStepSettingsModal"), el("designerStepSettings")].filter(Boolean);
  if (!targets.length) return;

  const html = renderSettingsHtml();
  targets.forEach((target) => {
    target.innerHTML = html;
  });
}

function renderSettingsHtml() {
  const step = getSelectedStep();
  if (!step) {
    return `<div class="designer-empty-state">Select a step to edit its configuration.</div>`;
  }

  const readonly = isReadonly();
  const disabled = readonly ? "disabled" : "";
  const tab = state.activeTab;
  const capabilities = stepUiCapabilities(step);
  if (!tabsForStep(step, capabilities).includes(tab)) {
    return renderIrrelevantTab(step, tab);
  }

  if (tab === "basic") return renderBasic(step, disabled, readonly, capabilities);
  if (tab === "sources") return renderSources(step, disabled, readonly);
  if (tab === "review") return renderReview(step, disabled, readonly);
  if (tab === "retry") return renderRetry(step, disabled, readonly);
  if (tab === "gate") return renderGate(step, disabled, readonly);
  if (tab === "advanced") return renderAdvanced(step, disabled, readonly);
  return renderBasic(step, disabled, readonly);
}

function renderIrrelevantTab(step, tab) {
  const tabLabel = {
    sources: "Prompt",
    review: "Review",
    retry: "Retry",
    gate: "Gate",
    advanced: "Advanced",
    basic: "Basic",
  }[tab] || tab;
  return `
    <div class="designer-runner-note">
      <strong>${escapeHtml(tabLabel)} is not typical for ${escapeHtml(formatStepType(step.type))}</strong>
      <span>Use Basic for the main ${escapeHtml(formatStepType(step.type))} settings. The tabs stay visible so the layout does not jump while you move between steps.</span>
    </div>
  `;
}

function renderBasic(step, disabled, readonly, capabilities) {
  return `
    <div class="designer-form-grid">
      ${readonly ? readonlyNotice() : ""}
      ${inputRow("Step Name", "name", step.name, disabled)}
      ${inputRow("Step Key", "key", step.key, disabled)}
      <label class="designer-form-row">
        <span class="designer-label">Step Type</span>
        <select class="designer-select" data-step-field="type" ${disabled}>
          ${options(StepTypes, step.type)}
        </select>
      </label>
      ${renderAgentConfig(step, disabled, capabilities)}
      ${renderBasicTypeConfig(step, disabled, capabilities)}
      ${textareaRow("Description", "description", step.description, disabled)}
      ${switchRow("Enabled", "Turn this step on/off without deleting it.", "enabled", step.enabled, disabled)}
      <div class="designer-runner-note">
        <strong>Step actions stay on the main screen</strong>
        <span>Use the floating action bar on the step list for Edit, Move, Duplicate, and Delete.</span>
      </div>
    </div>
  `;
}

function renderAgentConfig(step, disabled, capabilities) {
  if (!capabilities?.supportsAgent) return "";
  return `
    <div class="designer-template-summary-grid compact">
      ${inputRow("Agent Provider", "agent", step.agent || step.provider || "qwen", disabled, "qwen / opencode")}
      ${inputRow("Provider Alias", "provider", step.provider || step.agent || "qwen", disabled, "optional")}
    </div>
  `;
}

function renderBasicTypeConfig(step, disabled, capabilities) {
  if (step.type === "validation" || step.type === "python") {
    const promptHint = capabilities?.supportsPrompt
      ? `<div class="designer-runner-note"><strong>Prompt-enabled function</strong><span>This function enables the Prompt tab through backend catalog UI metadata.</span></div>`
      : "";
    return `
      <label class="designer-form-row">
        <span class="designer-label">${step.type === "python" ? "Python Function" : "Check Function"}</span>
        <select class="designer-select" data-step-field="function" ${disabled}>
          ${functionOptions("functions", [["", "None"], ["validate_spec", "Validate Spec"], ["validate_todo", "Validate Todo"], ["run_pytest", "Run Pytest"]], step.function)}
        </select>
      </label>
      ${functionHelp("functions", step.function, "Choose the Python function this step should run.")}
      ${promptHint}
      ${expectedFilesPreview(step)}
    `;
  }
  if (step.type === "review") {
    return `
      <label class="designer-form-row">
        <span class="designer-label">Review Strategy</span>
        <select class="designer-select" data-step-field="reviewMode" ${disabled}>
          ${functionOptions("reviewStrategies", ReviewModes, step.reviewMode)}
        </select>
      </label>
      ${functionHelp("reviewStrategies", step.reviewMode, "Choose how this review step should run.")}
    `;
  }
  if (step.type === "gate" || step.type === "manual") {
    return `
      <div class="designer-runner-note">
        <strong>Human gate</strong>
        <span>This step pauses the workflow and waits for a user decision before continuing.</span>
      </div>
    `;
  }
  if (step.type === "ai" || step.type === "command") {
    return `
      <div class="designer-runner-note">
        <strong>${step.type === "ai" ? "AI prompt step" : "Command step"}</strong>
        <span>Use the Prompt tab to choose slash commands, skills, prompt files, and output filename.</span>
      </div>
    `;
  }
  return "";
}

function expectedFilesPreview(step) {
  const files = Array.isArray(step.expectedFiles) ? step.expectedFiles.filter(Boolean) : [];
  return `
    <div class="designer-function-help">
      <strong>Expected files</strong>
      <span>${files.length ? files.map(escapeHtml).join(", ") : "No expected files configured."}</span>
    </div>
  `;
}

function isAbsoluteLikePath(value = "") {
  const text = String(value || "").trim();
  return /^[a-zA-Z]:[\\/]/.test(text) || text.startsWith("/") || text.startsWith("~/") || text.startsWith("\\\\");
}

function sourcePathSummary() {
  const wf = getSelectedWorkflow();
  const skillRoot = wf?.skillRoot || "~/.qwen/skills";
  return `Skill Path accepts absolute paths. Relative skill paths resolve from Skill Root (${skillRoot}), then Project Path. Prompt File resolves from data/ai-workflow/steps or project .ai-workflow/steps.`;
}

function describeSourcePath(source = {}) {
  const type = String(source.type || "").trim();
  const value = String(source.value || "").trim();
  if (!value) return "No path/value set.";
  const wf = getSelectedWorkflow();
  if (type === "skill_path") {
    if (isAbsoluteLikePath(value)) return "Skill path: absolute path, used directly.";
    return `Skill path: relative to Skill Root (${wf?.skillRoot || "~/.qwen/skills"}), with Project Path fallback.`;
  }
  if (type === "prompt_file") {
    return "Prompt file: resolved from data/ai-workflow/steps or project .ai-workflow/steps.";
  }
  if (type === "context_file") {
    if (isAbsoluteLikePath(value)) return "Context file: absolute path, used directly when available.";
    return "Context file: checked under Project Path, workflow workspace, then app root.";
  }
  if (type === "artifact") {
    return "Artifact: checked under workflow output/ and workspace.";
  }
  if (type === "command") return "Command source: prepended as a slash command when configured.";
  if (type === "inline_prompt") return "Inline prompt: inserted as text context.";
  return "Source value passed to backend workflow context.";
}

function describeExpectedFilePath(value = "") {
  const text = String(value || "").trim();
  if (!text) return "No expected file path set.";
  const normalized = text.replace(/\\/g, "/");
  if (isAbsoluteLikePath(text)) return "Absolute path: checked exactly at this file location.";
  if (normalized.startsWith("output/")) return "Workflow output path: checked under this run workspace.";
  if (normalized.startsWith("input/") || normalized.startsWith("prompts/") || normalized.startsWith(".workflow/")) {
    return "Workflow workspace path: checked under this run workspace.";
  }
  return "Relative artifact: checked in output/, workspace, then Project Path.";
}

function renderSources(step, disabled, readonly) {
  const diagnostics = getTemplateDiagnostics(step);
  const unknown = diagnostics.unknown.length ? `
    <div class="designer-warning-box">
      <strong>Unknown params</strong>
      <span>${diagnostics.unknown.map((name) => `{{${escapeHtml(name)}}}`).join(", ")}</span>
    </div>
  ` : "";
  const filename = step.filename || normalizeFilename(step.outputFile || diagnostics.filename || "");
  return `
    <div class="designer-form-grid">
      ${readonly ? readonlyNotice() : ""}
      <section class="designer-template-summary-card">
        <div>
          <span class="designer-label">Separated Skill / Metadata</span>
          <h4>.ai-workflow compatible step assets</h4>
        </div>
        <div class="designer-template-summary-grid compact">
          ${inputRow("Contract ID", "contractId", step.contractId || "", disabled, "my-step")}
          ${inputRow("Metadata Path", "metadataPath", step.metadataPath || step.contractPath || "", disabled, "contracts/my-step.yaml")}
          ${inputRow("Skill Path", "skillPath", step.skillPath || "", disabled, "steps/my-step.md")}
        </div>
        <div class="designer-footer-actions compact">
          <button type="button" data-designer-action="save-skill-asset" ${disabled}>Save Skill</button>
          <button type="button" data-designer-action="save-metadata-asset" ${disabled}>Save Metadata</button>
          <button type="button" data-designer-action="edit-python-asset" ${disabled}>Edit Python</button>
          <button type="button" data-designer-action="upload-python-asset" ${disabled}>Upload Python</button>
        </div>
        <div class="designer-form-hint">Runtime applies contract metadata first. Skill Path points to pure prompt markdown and can also be used as Template Path.</div>
      </section>
      <label class="designer-form-row">
        <span class="designer-label">Command</span>
        <select class="designer-select" data-step-field="command" ${disabled}>
          ${options([["", "None"], ["/spec", "/spec"], ["/plan", "/plan"], ["/todo", "/todo"], ["/build", "/build"], ["/ship", "/ship"], ["/review", "/review"], ["/test", "/test"]], step.command)}
        </select>
        <span class="designer-form-hint">Selected slash command is prepended to the rendered prompt before the agent runs.</span>
      </label>

      <section class="designer-template-summary-card">
        <div class="designer-section-row">
          <div>
            <span class="designer-label">Prompt Template</span>
            <h4>${escapeHtml(step.templatePath || "No template file")}</h4>
          </div>
          <button data-designer-action="open-template-editor" ${disabled}>Edit Template</button>
        </div>
        <div class="designer-template-summary-grid compact">
          <div>
            <span class="designer-label">Filename</span>
            <div class="designer-form-hint">${escapeHtml(filename || "No filename set")}</div>
          </div>
          <div>
            <span class="designer-label">Template Size</span>
            <div class="designer-form-hint">${escapeHtml(String((step.templateContent || "").length))} chars</div>
          </div>
        </div>
        ${unknown}
        <div class="designer-template-excerpt">${escapeHtml((step.templateContent || "").slice(0, 520) || "No prompt content yet.")}</div>
        <div class="designer-form-hint">Backend creates a folder from the workflow name, then saves this step output using Filename.</div>
      </section>

      <div class="designer-list-editor">
        <div class="designer-section-row">
          <span class="designer-label">Extra Context Sources</span>
          <button class="mini-button" data-designer-action="add-source" ${disabled}>+ Add Source</button>
        </div>
        ${step.sources.length ? step.sources.map((source, index) => `
          <div class="designer-source-row">
            <select class="designer-select" data-array-collection="sources" data-index="${index}" data-array-field="type" ${disabled}>
              ${options(SourceTypes, source.type)}
            </select>
            <input class="designer-input" value="${escapeAttr(source.value || "")}" data-array-collection="sources" data-index="${index}" data-array-field="value" ${disabled} />
            <button class="designer-danger" data-designer-action="remove-source" data-index="${index}" ${disabled}>x</button>
            <div class="designer-path-help">${escapeHtml(describeSourcePath(source))}</div>
          </div>
        `).join("") : `<div class="designer-empty-state">No extra sources. Template params are provided by backend runtime context.</div>`}
        <div class="designer-form-hint">${escapeHtml(sourcePathSummary())}</div>
      </div>
      <div class="designer-footer-actions">
        <button data-designer-action="preview-prompt">Preview Rendered Prompt</button>
      </div>
      <div class="designer-form-hint">Params are fixed by backend. Open the template editor, then click a param chip to insert {{param}} placeholders.</div>
    </div>
  `;
}

function renderReview(step, disabled, readonly) {
  return `
    <div class="designer-form-grid">
      ${readonly ? readonlyNotice() : ""}
      <label class="designer-form-row">
        <span class="designer-label">Review Strategy</span>
        <select class="designer-select" data-step-field="reviewMode" ${disabled}>
          ${functionOptions("reviewStrategies", ReviewModes, step.reviewMode)}
        </select>
      </label>
      <div class="designer-list-editor">
        <div class="designer-section-row">
          <span class="designer-label">Review Agents</span>
          <button class="mini-button" data-designer-action="add-reviewer" ${disabled}>+ Add Reviewer</button>
        </div>
        ${step.reviewers.length ? step.reviewers.map((reviewer, index) => `
          <div class="designer-reviewer-row">
            <div class="designer-form-grid">
              <input class="designer-input" placeholder="Agent profile" value="${escapeAttr(reviewer.agent || "")}" data-array-collection="reviewers" data-index="${index}" data-array-field="agent" ${disabled} />
              <input class="designer-input" placeholder="Review prompt path" value="${escapeAttr(reviewer.prompt || "")}" data-array-collection="reviewers" data-index="${index}" data-array-field="prompt" ${disabled} />
            </div>
            <input class="designer-input" type="number" step="0.1" value="${escapeAttr(reviewer.weight ?? 1)}" data-array-collection="reviewers" data-index="${index}" data-array-field="weight" ${disabled} />
            <button class="designer-danger" data-designer-action="remove-reviewer" data-index="${index}" ${disabled}>x</button>
          </div>
        `).join("") : `<div class="designer-empty-state">No extra reviewers. Current session review can still be used without reviewer rows.</div>`}
      </div>
      ${numberRow("Confidence Threshold", "confidenceThreshold", step.confidenceThreshold, disabled, "0", "1", "0.01")}
      ${inputRow("Pass Keywords", "passKeywords", step.passKeywords, disabled)}
      ${inputRow("Fail Keywords", "failKeywords", step.failKeywords, disabled)}
      <label class="designer-form-row">
        <span class="designer-label">Python Aggregator</span>
        <select class="designer-select" data-step-field="aggregatorFunction" ${disabled}>
          ${functionOptions("aggregators", [["", "None"], ["keyword_confidence", "Keyword + Confidence"]], step.aggregatorFunction)}
        </select>
      </label>
      ${functionHelp("aggregators", step.aggregatorFunction, "Optional aggregation function for multi-agent or keyword-based review results.")}
      <div class="designer-form-hint">Use confidence, keywords, pass count, and Python aggregator to make the final pass/fail decision.</div>
    </div>
  `;
}

function renderRetry(step, disabled, readonly) {
  const wf = getSelectedWorkflow();
  return `
    <div class="designer-form-grid">
      ${readonly ? readonlyNotice() : ""}
      ${numberRow("Max Retry", "maxRetries", step.maxRetries, disabled, "0", "20", "1")}
      <label class="designer-form-row">
        <span class="designer-label">On Fail</span>
        <select class="designer-select" data-step-field="failAction" ${disabled}>
          ${options(FailActions, step.failAction)}
        </select>
      </label>
      <label class="designer-form-row">
        <span class="designer-label">Retry From Step</span>
        <select class="designer-select" data-step-field="retryFromStepKey" ${disabled}>
          ${options([["", "Current / automatic"], ...(wf?.steps || []).map((item) => [item.key, item.name])], step.retryFromStepKey)}
        </select>
      </label>
      ${switchRow("Keep Same Session", "Continue in the same agent session when retrying.", "keepSameSession", step.keepSameSession, disabled)}
      ${switchRow("Inject Failure Feedback", "Pass validation/review error back into the retry prompt.", "injectFailureFeedback", step.injectFailureFeedback, disabled)}
      <div class="designer-function-help"><strong>Backend retry target</strong><span>${escapeHtml(step.retryFromStepKey || "Current / automatic")} - On fail: ${escapeHtml(step.failAction || "same_step")}</span></div>
      ${numberRow("Stop After Continuous Failures", "stopAfterFailures", step.stopAfterFailures, disabled, "1", "20", "1")}
    </div>
  `;
}

function renderGate(step, disabled, readonly) {
  return `
    <div class="designer-form-grid">
      ${readonly ? readonlyNotice() : ""}
      ${switchRow("Pause After This Step", "Stop workflow after this step and wait for user action.", "pauseAfterStep", step.pauseAfterStep, disabled)}
      ${switchRow("Approval Required", "User must approve before continuing.", "approvalRequired", step.approvalRequired, disabled)}
      ${textareaRow("Approval Message", "approvalMessage", step.approvalMessage, disabled, "Please review the artifact before continuing.")}
      <div class="designer-form-hint">Runner page can later show Approve, Reject with Guidance, and Retry from selected step actions.</div>
    </div>
  `;
}

function renderAdvanced(step, disabled, readonly) {
  const showConsensus = stepUiCapabilities(step).functionId === "consensus_agent" || step.key === "consensus_agent" || step.key === "consensus_security_scan";
  return `
    <div class="designer-form-grid">
      ${readonly ? readonlyNotice() : ""}
      ${switchRow("Enable Timeout", "Timeout counts as failure and follows retry policy.", "timeoutEnabled", step.timeoutEnabled, disabled)}
      ${numberRow("Timeout Minutes", "timeoutMinutes", step.timeoutMinutes, disabled, "0", "1440", "1")}
      ${switchRow("Allow Interaction", "The selected agent can pause and ask the user questions.", "allowInteraction", step.allowInteraction, disabled)}
      ${switchRow("Thinking", "Pass a thinking/reasoning flag to compatible agents such as OpenCode.", "thinking", step.thinking, disabled)}
      <label class="designer-form-row">
        <span class="designer-label">Python Function</span>
        <input class="designer-input" list="designerFunctionOptions" value="${escapeAttr(step.function || "")}" placeholder="validate_spec or functions/check.py" data-step-field="function" ${disabled} />
        <datalist id="designerFunctionOptions">
          ${functionOptions("functions", [["", "None"], ["validate_spec", "Validate Spec"], ["validate_todo", "Validate Todo"], ["run_pytest", "Run Pytest"]], step.function)
            .replace(/<option value="([^"]*)">([^<]*)<\/option>/g, '<option value="$1">$2</option>')}
        </datalist>
      </label>
      <div class="designer-footer-actions compact">
        <button type="button" data-designer-action="edit-python-asset" ${disabled}>Edit Python Function</button>
        <button type="button" data-designer-action="upload-python-asset" ${disabled}>Upload Python Function</button>
      </div>
      ${functionHelp("functions", step.function, "Optional Python function used by check and Python steps.")}
      ${showConsensus ? renderConsensusSettings(step, disabled) : ""}
      <div class="designer-list-editor">
        <div class="designer-section-row">
          <span class="designer-label">Expected Files</span>
          <button class="mini-button" data-designer-action="add-expected-file" ${disabled}>+ Add File</button>
        </div>
        ${step.expectedFiles.length ? step.expectedFiles.map((file, index) => `
          <div class="designer-expected-row">
            <input class="designer-input" value="${escapeAttr(file)}" placeholder="output/report.md, report.md, or C:\\path\\report.md" data-array-collection="expectedFiles" data-index="${index}" data-array-field="value" ${disabled} />
            <button class="designer-danger" data-designer-action="remove-expected-file" data-index="${index}" ${disabled}>x</button>
            <div class="designer-path-help">${escapeHtml(describeExpectedFilePath(file))}</div>
          </div>
        `).join("") : `<div class="designer-empty-state">No expected files configured.</div>`}
        <div class="designer-form-hint">Relative names are checked in output/, workspace, then Project Path. Use output/, input/, prompts/, or an absolute path when you need an exact location.</div>
      </div>
    </div>
  `;
}

function renderConsensusSettings(step, disabled) {
  return `
    <section class="designer-list-editor">
      <div class="designer-section-row">
        <span class="designer-label">Consensus Agent</span>
      </div>
      <div class="designer-form-grid">
        ${numberRow("Agent Count", "agentCount", step.agentCount ?? 3, disabled, "1", "10", "1")}
        ${numberRow("Retry Per Agent", "agentMaxRetries", step.agentMaxRetries ?? 3, disabled, "0", "20", "1")}
        ${switchRow("Fresh Session Per Agent", "Run each internal agent in a separate session for independent answers.", "freshSessionPerAgent", step.freshSessionPerAgent ?? true, disabled)}
        ${inputRow("Artifact Pattern", "artifactPattern", step.artifactPattern || step.filename || "", disabled, "result-agent-{index}.md")}
        <label class="designer-form-row">
          <span class="designer-label">Inner Function</span>
          <select class="designer-select" data-step-field="candidateValidator" ${disabled}>
            ${functionOptions("functions", [["", "None"], ["validate_security_candidates", "Validate Security Candidates"]], step.candidateValidator)}
          </select>
        </label>
      </div>
      <div class="designer-form-hint">Use {index} or * in Artifact Pattern. Example: candidate-{index}.md creates candidate-1.md, candidate-2.md, ...</div>
    </section>
  `;
}

function inputRow(label, field, value, disabled, placeholder = "") {
  return `
    <label class="designer-form-row">
      <span class="designer-label">${escapeHtml(label)}</span>
      <input class="designer-input" value="${escapeAttr(value || "")}" placeholder="${escapeAttr(placeholder)}" data-step-field="${escapeAttr(field)}" ${disabled} />
    </label>
  `;
}

function numberRow(label, field, value, disabled, min, max, step) {
  return `
    <label class="designer-form-row">
      <span class="designer-label">${escapeHtml(label)}</span>
      <input class="designer-input" type="number" min="${escapeAttr(min)}" max="${escapeAttr(max)}" step="${escapeAttr(step)}" value="${escapeAttr(value)}" data-step-field="${escapeAttr(field)}" ${disabled} />
    </label>
  `;
}

function textareaRow(label, field, value, disabled, placeholder = "") {
  return `
    <label class="designer-form-row">
      <span class="designer-label">${escapeHtml(label)}</span>
      <textarea class="designer-textarea" placeholder="${escapeAttr(placeholder)}" data-step-field="${escapeAttr(field)}" ${disabled}>${escapeHtml(value || "")}</textarea>
    </label>
  `;
}

function switchRow(title, description, field, checked, disabled) {
  return `
    <label class="designer-form-row inline">
      <span class="designer-switch-label">
        <strong>${escapeHtml(title)}</strong>
        <span>${escapeHtml(description)}</span>
      </span>
      <input type="checkbox" data-step-field="${escapeAttr(field)}" ${checked ? "checked" : ""} ${disabled} />
    </label>
  `;
}

function readonlyNotice() {
  return `<div class="designer-empty-state">This is a system workflow. Duplicate it to edit settings.</div>`;
}

  return {
    renderSettings,
  };
}
