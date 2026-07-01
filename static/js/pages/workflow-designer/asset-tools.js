const WORKFLOW_ASSET_API = "/api/workflow-assets";

export function installWorkflowAssetTools(ctx) {
  const {
    defaultTemplateContent,
    designerApi,
    getSelectedStep,
    isReadonly,
    markWorkflowDirty,
    renderSettings,
    renderWorkflowViewOnly,
    toast,
  } = ctx;

  async function saveSkillAssetForSelectedStep() {
    const step = getSelectedStep();
    if (!step || isReadonly()) return;
    const path = normalizeAssetPath(step.skillPath || step.templatePath || `steps/${step.key || "step"}.md`, "steps");
    if (!path.startsWith("steps/")) {
      toast("Skill Path must start with steps/ or .ai-workflow/steps/.");
      return;
    }
    const content = String(step.templateContent || "").trim() ? step.templateContent : defaultTemplateContent(step);
    try {
      await designerApi(`${WORKFLOW_ASSET_API}/file`, {
        method: "PUT",
        body: JSON.stringify({ path, content, scope: "global", overwrite: true }),
      });
      step.skillPath = path;
      step.templatePath = path;
      markWorkflowDirty();
      renderSettings();
      renderWorkflowViewOnly();
      toast(`Skill saved: ${path}`);
    } catch (error) {
      toast(`Could not save skill: ${error.message}`);
    }
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
      const content = await file.text();
      const path = normalizeAssetPath(`validators/${file.name}`, "validators");
      try {
        await designerApi(`${WORKFLOW_ASSET_API}/file`, {
          method: "PUT",
          body: JSON.stringify({ path, content, scope: "global", overwrite: true }),
        });
        step.validator = path;
        if (step.type === "ai") step.type = "python";
        markWorkflowDirty();
        renderSettings();
        renderWorkflowViewOnly();
        toast(`Python asset uploaded: ${path}`);
      } catch (error) {
        toast(`Could not upload Python asset: ${error.message}`);
      }
    }, { once: true });
    input.click();
  }

  return {
    saveSkillAssetForSelectedStep,
    uploadPythonAssetForSelectedStep,
  };
}

function normalizeAssetPath(value = "", defaultDir = "steps") {
  const cleanedName = (name) => String(name || "asset")
    .replace(/\\/g, "/")
    .split("/")
    .filter(Boolean)
    .pop()
    ?.replace(/[^a-zA-Z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "") || "asset";
  let normalized = String(value || "").trim().replace(/\\/g, "/");
  if (normalized.startsWith(".ai-workflow/")) normalized = normalized.slice(".ai-workflow/".length);
  if (!normalized || !/^(steps|validators|tools|contracts)\//.test(normalized)) {
    normalized = `${defaultDir}/${cleanedName(normalized || `asset.${defaultDir === "steps" ? "md" : "py"}`)}`;
  }
  const [dir, ...rest] = normalized.split("/");
  return `${dir}/${rest.map(cleanedName).join("/")}`;
}
