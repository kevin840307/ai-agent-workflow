const WORKFLOW_ASSET_API = "/api/workflow-assets";
const TYPE_DEFAULTS = {
  steps: { path: "steps/new-skill.md", content: "FILENAME: result.md\n\nRequirement:\n{{requirement}}\n" },
  contracts: { path: "contracts/new-step.yaml", content: "id: new-step\nskill: steps/new-skill.md\ntype: ai\nagent: qwen\nretry: 2\nallowInteraction: false\nthinking: false\noutputs:\n  - result.md\n" },
  functions: { path: "functions/check.py", content: "FUNCTION_META = {'id': 'check', 'label': 'Check', 'description': 'Example Python function.'}\n\ndef run(context, artifact=None):\n    return 'Status: PASS\\n'\n" },
  workflows: { path: "workflows/demo.workflow", content: "contract: new-step\n" },
};

export function installWorkflowAssetManager(ctx) {
  const { designerApi, el, escapeAttr, escapeHtml, getSelectedStep, isReadonly, markWorkflowDirty, renderSettings, renderWorkflowViewOnly, toast } = ctx;
  const state = { assets: [], selected: null, loading: false };

  function bindEvents() {
    ["designerAssetProjectPath", "designerAssetScope", "designerAssetType", "designerAssetPath", "designerAssetContent"].forEach((id) => {
      el(id)?.addEventListener("input", syncSelectedFromInputs);
      el(id)?.addEventListener("change", syncSelectedFromInputs);
    });
    el("designerAssetList")?.addEventListener("click", (event) => {
      const item = event.target.closest("[data-asset-key]");
      if (item) selectAsset(item.dataset.assetKey);
    });
    document.addEventListener("click", (event) => {
      const action = event.target.closest("[data-asset-manager-action]");
      if (!action) return;
      event.preventDefault();
      dispatch(action.dataset.assetManagerAction);
    });
  }

  async function refreshAssetList() {
    state.loading = true;
    renderAssetList();
    try {
      const projectPath = el("designerAssetProjectPath")?.value || "";
      const query = projectPath ? `?project_path=${encodeURIComponent(projectPath)}` : "";
      const payload = await designerApi(`${WORKFLOW_ASSET_API}${query}`);
      state.assets = Array.isArray(payload.assets) ? payload.assets : [];
      state.selected = keepSelectedOrFirst();
      state.loading = false;
      renderAll();
    } catch (error) {
      state.loading = false;
      toast(`Could not load assets: ${error.message}`);
      renderAssetList(`<div class="designer-empty-state">${escapeHtml(error.message)}</div>`);
    }
  }

  function keepSelectedOrFirst() {
    if (!state.assets.length) return null;
    const key = state.selected ? assetKey(state.selected) : "";
    return state.assets.find((item) => assetKey(item) === key) || state.assets[0];
  }

  async function selectAsset(key) {
    const asset = state.assets.find((item) => assetKey(item) === key);
    if (!asset) return;
    state.selected = asset;
    syncInputsFromSelected();
    await readSelectedAsset();
    renderAssetList();
  }

  async function readSelectedAsset() {
    const selected = state.selected;
    if (!selected) return;
    try {
      const file = await designerApi(`${WORKFLOW_ASSET_API}/file?path=${encodeURIComponent(selected.path)}&scope=${encodeURIComponent(selected.scope)}${projectQuery()}`);
      el("designerAssetContent").value = file.content || "";
    } catch (error) {
      toast(`Could not read asset: ${error.message}`);
    }
  }

  async function saveAsset() {
    const path = normalizeAssetPath(el("designerAssetPath")?.value || "", el("designerAssetType")?.value || "steps");
    const body = { path, content: el("designerAssetContent")?.value || "", scope: el("designerAssetScope")?.value || "global", project_path: projectPath() || null, overwrite: true };
    try {
      const saved = await designerApi(`${WORKFLOW_ASSET_API}/file`, { method: "PUT", body: JSON.stringify(body) });
      state.selected = { ...saved, type: path.split("/")[0], name: path.split("/").pop() };
      await refreshAssetList();
      toast(`Asset saved: ${path}`);
    } catch (error) { toast(`Could not save asset: ${error.message}`); }
  }

  async function deleteAsset() {
    const path = el("designerAssetPath")?.value || "";
    if (!path || !confirm(`Delete ${path}?`)) return;
    try {
      await designerApi(`${WORKFLOW_ASSET_API}/file?path=${encodeURIComponent(path)}&scope=${encodeURIComponent(el("designerAssetScope")?.value || "global")}${projectQuery()}`, { method: "DELETE" });
      state.selected = null;
      el("designerAssetContent").value = "";
      await refreshAssetList();
      toast(`Asset deleted: ${path}`);
    } catch (error) { toast(`Could not delete asset: ${error.message}`); }
  }

  async function renameAsset() {
    const oldPath = state.selected?.path || "";
    const newPath = normalizeAssetPath(el("designerAssetPath")?.value || "", state.selected?.type || el("designerAssetType")?.value || "steps");
    if (!oldPath || oldPath === newPath) return;
    try {
      const renamed = await designerApi(`${WORKFLOW_ASSET_API}/rename`, { method: "POST", body: JSON.stringify({ old_path: oldPath, new_path: newPath, scope: el("designerAssetScope")?.value || state.selected.scope || "global", project_path: projectPath() || null, overwrite: false }) });
      state.selected = { ...renamed, type: newPath.split("/")[0], name: newPath.split("/").pop() };
      await refreshAssetList();
      toast(`Asset renamed: ${newPath}`);
    } catch (error) { toast(`Could not rename asset: ${error.message}`); }
  }

  function newAsset() {
    const type = el("designerAssetType")?.value || "steps";
    const sample = TYPE_DEFAULTS[type] || TYPE_DEFAULTS.steps;
    state.selected = { scope: el("designerAssetScope")?.value || "global", type, path: sample.path, name: sample.path.split("/").pop() };
    syncInputsFromSelected();
    el("designerAssetContent").value = sample.content;
    renderAssetList();
  }

  function uploadAsset() {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".md,.markdown,.txt,.yaml,.yml,.json,.py,.workflow";
    input.addEventListener("change", async () => {
      const file = input.files?.[0];
      if (!file) return;
      const type = typeFromFilename(file.name, el("designerAssetType")?.value || "steps");
      el("designerAssetType").value = type;
      el("designerAssetPath").value = normalizeAssetPath(`${type}/${file.name}`, type);
      el("designerAssetContent").value = await file.text();
      await saveAsset();
    }, { once: true });
    input.click();
  }

  function applySelectedToStep() {
    const step = getSelectedStep();
    const path = el("designerAssetPath")?.value || state.selected?.path || "";
    const type = path.split("/")[0];
    if (!step || isReadonly() || !path) return;
    if (type === "steps") {
      step.skillPath = path;
      step.templatePath = path;
      step.templateContent = el("designerAssetContent")?.value || step.templateContent || "";
    } else if (type === "contracts") {
      step.contractPath = path;
      step.metadataPath = path;
      step.contractId = path.split("/").pop().replace(/\.(ya?ml|json)$/i, "");
    } else if (type === "functions") {
      step.function = path;
      if (step.type === "ai") step.type = "python";
    } else if (type === "workflows") {
      toast("Workflow assets appear in the workflow list after Refresh; select them from the sidebar.");
      return;
    }
    markWorkflowDirty();
    renderSettings();
    renderWorkflowViewOnly();
    toast(`Applied ${path} to selected step.`);
  }

  function dispatch(name) {
    ({ refresh: refreshAssetList, new: newAsset, save: saveAsset, delete: deleteAsset, rename: renameAsset, upload: uploadAsset, apply: applySelectedToStep }[name] || (() => {}))();
  }

  function renderAll() { syncInputsFromSelected(); renderAssetList(); }
  function renderAssetList(errorHtml = "") {
    const target = el("designerAssetList");
    if (!target) return;
    if (errorHtml) { target.innerHTML = errorHtml; return; }
    if (state.loading) { target.innerHTML = `<div class="designer-empty-state">Loading assets...</div>`; return; }
    if (!state.assets.length) { target.innerHTML = `<div class="designer-empty-state">No assets found. Create one or put files under .ai-workflow.</div>`; return; }
    const selectedKey = state.selected ? assetKey(state.selected) : "";
    target.innerHTML = state.assets.map((item) => `<button type="button" class="designer-asset-item ${assetKey(item) === selectedKey ? "active" : ""}" data-asset-key="${escapeAttr(assetKey(item))}"><strong>${escapeHtml(item.path)}</strong><span>${escapeHtml(item.scope)} · ${escapeHtml(item.type)} · ${Number(item.size || 0)} bytes</span></button>`).join("");
  }

  function syncInputsFromSelected() {
    const selected = state.selected || { scope: "global", type: "steps", path: "steps/new-skill.md" };
    if (el("designerAssetScope")) el("designerAssetScope").value = selected.scope || "global";
    if (el("designerAssetType")) el("designerAssetType").value = selected.type || selected.path?.split("/")[0] || "steps";
    if (el("designerAssetPath")) el("designerAssetPath").value = selected.path || "";
  }

  function syncSelectedFromInputs() {
    const path = el("designerAssetPath")?.value || "";
    state.selected = { ...(state.selected || {}), scope: el("designerAssetScope")?.value || "global", type: el("designerAssetType")?.value || path.split("/")[0] || "steps", path, name: path.split("/").pop() || "" };
  }

  function projectPath() { return el("designerAssetProjectPath")?.value?.trim() || ""; }
  function projectQuery() { const value = projectPath(); return value ? `&project_path=${encodeURIComponent(value)}` : ""; }
  function assetKey(item) { return `${item.scope}:${item.path}`; }
  return { bindEvents, refreshAssetList };
}

function typeFromFilename(filename, fallback) {
  const ext = filename.toLowerCase().split(".").pop();
  if (["md", "markdown", "txt"].includes(ext)) return "steps";
  if (["yaml", "yml", "json"].includes(ext)) return "contracts";
  if (ext === "py") return "functions";
  if (ext === "workflow") return "workflows";
  return fallback;
}

function normalizeAssetPath(value = "", defaultDir = "steps") {
  let normalized = String(value || "").trim().replace(/\\/g, "/");
  if (normalized.startsWith(".ai-workflow/")) normalized = normalized.slice(".ai-workflow/".length);
  if (!/^(steps|contracts|functions|workflows)\//.test(normalized)) {
    const ext = defaultDir === "steps" ? "md" : defaultDir === "contracts" ? "yaml" : defaultDir === "workflows" ? "workflow" : "py";
    normalized = `${defaultDir}/${cleanName(normalized || `asset.${ext}`)}`;
  }
  const [dir, ...parts] = normalized.split("/").filter(Boolean);
  return `${dir}/${parts.map(cleanName).join("/")}`;
}

function cleanName(value) {
  return String(value || "asset").replace(/[^a-zA-Z0-9._-]+/g, "-").replace(/^-+|-+$/g, "") || "asset";
}
