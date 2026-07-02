const WORKFLOW_ASSET_API = "/api/workflow-assets";

export function installWorkflowAssetTools(ctx) {
  const { defaultTemplateContent, designerApi, getSelectedStep, isReadonly, markWorkflowDirty, renderSettings, renderWorkflowViewOnly, toast } = ctx;
  const refresh = () => { markWorkflowDirty(); renderSettings(); renderWorkflowViewOnly(); };
  const putFile = (path, content) => designerApi(`${WORKFLOW_ASSET_API}/file`, {
    method: "PUT",
    body: JSON.stringify({ path, content, scope: "global", overwrite: true }),
  });

  async function saveSkillAssetForSelectedStep() {
    const step = getSelectedStep();
    if (!step || isReadonly()) return;
    const path = normalizeAssetPath(step.skillPath || step.templatePath || `steps/${step.key || "step"}.md`, "steps");
    if (!path.startsWith("steps/")) return toast("Skill Path must start with steps/ or .ai-workflow/steps/.");
    const content = String(step.templateContent || "").trim() ? step.templateContent : defaultTemplateContent(step);
    try {
      await putFile(path, content);
      step.skillPath = path;
      step.templatePath = path;
      refresh();
      toast(`Skill saved: ${path}`);
    } catch (error) { toast(`Could not save skill: ${error.message}`); }
  }

  async function saveMetadataAssetForSelectedStep() {
    const step = getSelectedStep();
    if (!step || isReadonly()) return;
    const id = slug(step.contractId || step.key || "step");
    const path = normalizeAssetPath(step.metadataPath || step.contractPath || `contracts/${id}.yaml`, "contracts");
    if (!path.startsWith("contracts/")) return toast("Metadata Path must start with contracts/.");
    try {
      await putFile(path, metadataYaml(step, id, path));
      step.contractId = id;
      step.contractPath = path;
      step.metadataPath = path;
      refresh();
      toast(`Metadata saved: ${path}`);
    } catch (error) { toast(`Could not save metadata: ${error.message}`); }
  }

  function uploadPythonAssetForSelectedStep() {
    const step = getSelectedStep();
    if (!step || isReadonly()) return;
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".py";
    input.addEventListener("change", async () => {
      const file = input.files?.[0];
      if (!file) return;
      const path = normalizeAssetPath(`functions/${file.name}`, "functions");
      try {
        await putFile(path, await file.text());
        step.functions = [path];
        step.function = path;
        if (step.type === "ai") step.type = "python";
        refresh();
        toast(`Python asset uploaded: ${path}`);
      } catch (error) { toast(`Could not upload Python asset: ${error.message}`); }
    }, { once: true });
    input.click();
  }

  async function editPythonAssetForSelectedStep() {
    const step = getSelectedStep();
    if (!step || isReadonly()) return;
    const firstFunction = (Array.isArray(step.functions) && step.functions[0]) || step.function || "";
    const path = normalizeAssetPath(firstFunction || `functions/${step.key || "step"}.py`, "functions");
    let content = defaultPython();
    try {
      const file = await designerApi(`${WORKFLOW_ASSET_API}/file?path=${encodeURIComponent(path)}`);
      content = file.content ?? content;
    } catch (_) {}
    openPythonEditor(path, content, async (nextContent) => {
      try {
        await putFile(path, nextContent);
        step.functions = [path];
        step.function = path;
        if (step.type === "ai") step.type = "python";
        refresh();
        toast(`Python asset saved: ${path}`);
      } catch (error) { toast(`Could not save Python asset: ${error.message}`); }
    });
  }

  return { editPythonAssetForSelectedStep, saveMetadataAssetForSelectedStep, saveSkillAssetForSelectedStep, uploadPythonAssetForSelectedStep };
}

function openPythonEditor(path, content, onSave) {
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  const modal = document.createElement("div");
  modal.className = "modal-card designer-template-modal";
  modal.innerHTML = `<div class="modal-header"><h3>Edit Python Asset</h3><button type="button" class="mini-button" data-close>Close</button></div><p class="designer-form-hint"></p><textarea class="designer-textarea designer-template-editor-large" spellcheck="false"></textarea><div class="designer-footer-actions"><button type="button" class="secondary-button" data-close>Cancel</button><button type="button" class="primary-button" data-save>Save Python</button></div>`;
  modal.querySelector("p").textContent = path;
  modal.querySelector("textarea").value = content;
  backdrop.appendChild(modal);
  document.body.appendChild(backdrop);
  backdrop.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => backdrop.remove()));
  backdrop.querySelector("[data-save]").addEventListener("click", async () => {
    await onSave(backdrop.querySelector("textarea").value);
    backdrop.remove();
  });
}

function metadataYaml(step, id, path) {
  const lines = [`id: ${id}`, `name: ${cleanValue(step.name || id)}`, `skill: ${cleanValue(step.skillPath || step.templatePath || `steps/${id}.md`)}`, `type: ${cleanValue(step.type || "ai")}`];
  if (step.description) lines.push(`description: ${cleanValue(step.description)}`);
  if (step.command) lines.push(`command: ${cleanValue(step.command)}`);
  if (step.agent || step.provider) lines.push(`agent: ${cleanValue(step.agent || step.provider)}`);
  lines.push(`retry: ${Number(step.maxRetries || 0)}`);
  const outputs = Array.isArray(step.expectedFiles) && step.expectedFiles.length ? step.expectedFiles : [step.outputFile || step.filename].filter(Boolean);
  if (outputs.length) lines.push("outputs:", ...outputs.map((file) => `  - ${cleanValue(file)}`));
  const functions = Array.isArray(step.functions) && step.functions.length ? step.functions : [step.function].filter(Boolean);
  if (functions.length === 1) {
    lines.push(`function: ${cleanValue(functions[0])}`);
  } else if (functions.length > 1) {
    lines.push("functions:", ...functions.map((item) => `  - ${cleanValue(item)}`));
  }
  if (step.timeoutEnabled && step.timeoutMinutes) lines.push(`timeout: ${Math.round(Number(step.timeoutMinutes) * 60)}`);
  lines.push(`allowInteraction: ${Boolean(step.allowInteraction)}`);
  lines.push(`thinking: ${Boolean(step.thinking)}`);
  lines.push(`confidenceThreshold: ${Number(step.confidenceThreshold ?? 0.75)}`);
  if (step.passKeywords) lines.push(`passKeywords: ${cleanValue(step.passKeywords)}`);
  if (step.failKeywords) lines.push(`failKeywords: ${cleanValue(step.failKeywords)}`);
  if (step.aggregatorFunction) lines.push(`aggregatorFunction: ${cleanValue(step.aggregatorFunction)}`);
  lines.push(`failAction: ${cleanValue(step.failAction || "same_step")}`);
  if (step.retryFromStepKey) lines.push(`retryFromStepKey: ${cleanValue(step.retryFromStepKey)}`);
  lines.push(`keepSameSession: ${Boolean(step.keepSameSession)}`);
  lines.push(`injectFailureFeedback: ${Boolean(step.injectFailureFeedback)}`);
  lines.push(`stopAfterFailures: ${Number(step.stopAfterFailures || 1)}`);
  lines.push(`approvalRequired: ${Boolean(step.approvalRequired)}`);
  lines.push(`pauseAfterStep: ${Boolean(step.pauseAfterStep)}`);
  if (step.approvalMessage) lines.push(`approvalMessage: ${cleanValue(step.approvalMessage)}`);
  lines.push(`path: ${cleanValue(path)}`);
  return `${lines.join("\n")}\n`;
}

function defaultPython() {
  return `def run(context, artifact=None):\n    context.write_text(context.output_dir / "function-result.md", "Status: PASS\\n")\n    return "Status: PASS\\n"\n`;
}

function normalizeAssetPath(value = "", defaultDir = "steps") {
  const cleanedName = (name) => String(name || "asset").replace(/\\/g, "/").split("/").filter(Boolean).pop()?.replace(/[^a-zA-Z0-9._-]+/g, "-").replace(/^-+|-+$/g, "") || "asset";
  let normalized = String(value || "").trim().replace(/\\/g, "/");
  if (normalized.startsWith(".ai-workflow/")) normalized = normalized.slice(".ai-workflow/".length);
  if (!normalized || !/^(steps|functions|contracts)\//.test(normalized)) {
    const ext = defaultDir === "steps" ? "md" : defaultDir === "contracts" ? "yaml" : "py";
    normalized = `${defaultDir}/${cleanedName(normalized || `asset.${ext}`)}`;
  }
  const [dir, ...rest] = normalized.split("/");
  return `${dir}/${rest.map(cleanedName).join("/")}`;
}

function slug(value) { return String(value || "step").trim().toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "") || "step"; }
function cleanValue(value) { return String(value || "").replace(/[\r\n]+/g, " ").trim(); }
