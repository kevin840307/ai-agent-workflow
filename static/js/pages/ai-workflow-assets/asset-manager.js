import { renderMarkdownPreview } from "./markdown-preview.js?v=20260711-ui-v12";

const WORKFLOW_ASSET_API = "/api/workflow-assets";
const TYPE_DEFAULTS = {
  steps: { path: "steps/new-skill.md", content: "FILENAME: result.md\n\nRequirement:\n{{requirement}}\n" },
  contracts: { path: "contracts/new-step.yaml", content: "id: new-step\nskill: steps/new-skill.md\ntype: ai\nagent: qwen\nretry: 2\nallowInteraction: false\nthinking: false\noutputs:\n  - result.md\n" },
  functions: { path: "functions/check.py", content: "FUNCTION_META = {'id': 'check', 'label': 'Check', 'description': 'Example Python function.'}\n\ndef run(context, artifact=None):\n    return 'Status: PASS\\n'\n" },
  workflows: { path: "workflows/demo.workflow", content: "contract: new-step\n" },
};

export function installWorkflowAssetManager(ctx) {
  const designerApi = ctx.designerApi;
  const el = ctx.el;
  const escapeAttr = ctx.escapeAttr || escapeHtml;
  const escapeHtmlFn = ctx.escapeHtml || escapeHtml;
  const toast = ctx.toast || ((message) => console.info(message));
  const getSelectedStep = ctx.getSelectedStep || (() => null);
  const isReadonly = ctx.isReadonly || (() => true);
  const markWorkflowDirty = ctx.markWorkflowDirty || (() => {});
  const renderSettings = ctx.renderSettings || (() => {});
  const renderWorkflowViewOnly = ctx.renderWorkflowViewOnly || (() => {});
  const state = { assets: [], selected: null, loading: false, view: "edit" };

  function bindEvents() {
    el("designerAssetProjectPath")?.addEventListener("change", refreshAssetList);
    el("designerAssetProjectPath")?.addEventListener("keydown", (event) => { if (event.key === "Enter") refreshAssetList(); });
    el("designerAssetScope")?.addEventListener("change", handleFilterChange);
    el("designerAssetType")?.addEventListener("change", handleFilterChange);
    ["designerAssetPath", "designerAssetContent"].forEach((id) => {
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
      const query = projectPath() ? `?project_path=${encodeURIComponent(projectPath())}` : "";
      const payload = await designerApi(`${WORKFLOW_ASSET_API}${query}`);
      state.assets = Array.isArray(payload.assets) ? payload.assets : [];
      state.selected = keepSelectedOrFirst();
      state.loading = false;
      renderAll();
      if (state.selected) await readSelectedAsset();
      return true;
    } catch (error) {
      state.loading = false;
      renderAssetList(`<div class="designer-empty-state">${escapeHtmlFn(error.message)}</div>`);
      toast(`Could not load assets: ${error.message}`);
      return false;
    }
  }

  function handleFilterChange() {
    state.selected = keepSelectedOrFirst();
    if (state.selected) {
      syncInputsFromSelected();
      readSelectedAsset();
    } else {
      newAsset({ keepContent: false });
    }
    renderAssetList();
  }

  function filteredAssets() {
    const scope = filterScope();
    const type = filterType();
    return state.assets.filter((item) => item.scope === scope && item.type === type);
  }

  function keepSelectedOrFirst() {
    const filtered = filteredAssets();
    if (!filtered.length) return null;
    const key = state.selected ? assetKey(state.selected) : "";
    return filtered.find((item) => assetKey(item) === key) || filtered[0];
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
    if (!state.selected) return;
    try {
      const file = await designerApi(`${WORKFLOW_ASSET_API}/file?path=${encodeURIComponent(state.selected.path)}&scope=${encodeURIComponent(state.selected.scope)}${projectQuery("&")}`);
      setValue("designerAssetContent", file.content || "");
      renderEditorView();
    } catch (error) {
      toast(`Could not read asset: ${error.message}`);
    }
  }

  async function saveAsset() {
    const type = filterType();
    const path = normalizeAssetPath(el("designerAssetPath")?.value || "", type);
    const scope = filterScope();
    if (scope === "project" && !projectPath()) return toast("Project scope requires a Project Path.");
    const body = { path, content: el("designerAssetContent")?.value || "", scope, project_path: projectPath() || null, overwrite: true };
    try {
      const saved = await designerApi(`${WORKFLOW_ASSET_API}/file`, { method: "PUT", body: JSON.stringify(body) });
      state.selected = { ...saved, scope, type: path.split("/")[0], name: path.split("/").pop() };
      await refreshAssetList();
      toast(`Asset saved: ${path}`);
    } catch (error) { toast(`Could not save asset: ${error.message}`); }
  }

  async function deleteAsset() {
    const path = el("designerAssetPath")?.value || state.selected?.path || "";
    if (!path || !confirm(`Delete ${path}?`)) return;
    try {
      await designerApi(`${WORKFLOW_ASSET_API}/file?path=${encodeURIComponent(path)}&scope=${encodeURIComponent(filterScope())}${projectQuery("&")}`, { method: "DELETE" });
      state.selected = null;
      setValue("designerAssetContent", "");
      await refreshAssetList();
      toast(`Asset deleted: ${path}`);
    } catch (error) { toast(`Could not delete asset: ${error.message}`); }
  }

  async function renameAsset() {
    const oldPath = state.selected?.path || "";
    const newPath = normalizeAssetPath(el("designerAssetPath")?.value || "", state.selected?.type || filterType());
    if (!oldPath || oldPath === newPath) return;
    try {
      const renamed = await designerApi(`${WORKFLOW_ASSET_API}/rename`, { method: "POST", body: JSON.stringify({ old_path: oldPath, new_path: newPath, scope: filterScope(), project_path: projectPath() || null, overwrite: false }) });
      state.selected = { ...renamed, scope: filterScope(), type: newPath.split("/")[0], name: newPath.split("/").pop() };
      await refreshAssetList();
      toast(`Asset renamed: ${newPath}`);
    } catch (error) { toast(`Could not rename asset: ${error.message}`); }
  }

  function newAsset() {
    const type = filterType();
    const sample = TYPE_DEFAULTS[type] || TYPE_DEFAULTS.steps;
    state.selected = { scope: filterScope(), type, path: sample.path, name: sample.path.split("/").pop(), size: 0 };
    syncInputsFromSelected();
    setValue("designerAssetContent", sample.content);
    state.view = "edit";
    renderEditorView();
    renderAssetList();
  }

  function uploadAsset() {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".md,.markdown,.txt,.yaml,.yml,.json,.py,.workflow";
    input.addEventListener("change", async () => {
      const file = input.files?.[0];
      if (!file) return;
      const type = typeFromFilename(file.name, filterType());
      setValue("designerAssetType", type);
      setValue("designerAssetPath", normalizeAssetPath(`${type}/${file.name}`, type));
      setValue("designerAssetContent", await file.text());
      renderEditorView();
      await saveAsset();
    }, { once: true });
    input.click();
  }

  function applySelectedToStep() {
    const step = getSelectedStep();
    const path = el("designerAssetPath")?.value || state.selected?.path || "";
    const type = path.split("/")[0];
    if (!step || isReadonly() || !path) return toast("Open this from Workflow Designer and select an editable step first.");
    if (type === "steps") {
      step.skillPath = path;
      step.templatePath = path;
      step.templateContent = el("designerAssetContent")?.value || step.templateContent || "";
    } else if (type === "contracts") {
      step.contractPath = path;
      step.metadataPath = path;
      step.contractId = path.split("/").pop().replace(/\.(ya?ml|json)$/i, "");
    } else if (type === "functions") {
      step.functions = [path];
      step.function = path;
      if (step.type === "ai") step.type = "python";
    } else return toast("Workflow assets appear in the workflow list after Refresh.");
    markWorkflowDirty();
    renderSettings();
    renderWorkflowViewOnly();
    toast(`Applied ${path} to selected step.`);
  }

  function dispatch(name) {
    ({
      refresh: refreshAssetList,
      new: newAsset,
      save: saveAsset,
      delete: deleteAsset,
      rename: renameAsset,
      upload: uploadAsset,
      apply: applySelectedToStep,
      "view-edit": () => setEditorView("edit"),
      "view-preview": () => setEditorView("preview"),
    }[name] || (() => {}))();
  }

  function renderAll() { syncInputsFromSelected(); renderAssetList(); }
  function renderAssetList(errorHtml = "") {
    const target = el("designerAssetList");
    const summary = el("designerAssetSummary");
    if (!target) return;
    if (errorHtml) { target.innerHTML = errorHtml; return; }
    if (state.loading) { target.innerHTML = `<div class="designer-empty-state">Loading assets...</div>`; return; }
    const filtered = filteredAssets();
    if (summary) summary.innerHTML = `${filtered.length} shown / ${state.assets.length} total · ${escapeHtmlFn(filterScope())} · ${escapeHtmlFn(filterTypeLabel(filterType()))}`;
    if (!filtered.length) { target.innerHTML = `<div class="designer-empty-state">No ${escapeHtmlFn(filterTypeLabel(filterType()))} assets in ${escapeHtmlFn(filterScope())} scope. Click New or put files under ${filterScope() === "project" ? ".ai-workflow" : "data/ai-workflow"}.</div>`; return; }
    const selectedKey = state.selected ? assetKey(state.selected) : "";
    target.innerHTML = filtered.map((item) => `<button type="button" class="designer-asset-item ${assetKey(item) === selectedKey ? "active" : ""}" data-asset-key="${escapeAttr(assetKey(item))}"><strong>${escapeHtmlFn(item.path)}</strong><span>${escapeHtmlFn(item.scope)} · ${escapeHtmlFn(item.type)} · ${Number(item.size || 0)} bytes</span></button>`).join("");
  }

  function syncInputsFromSelected() {
    const selected = state.selected || { scope: filterScope(), type: filterType(), path: TYPE_DEFAULTS[filterType()]?.path || "steps/new-skill.md" };
    setValue("designerAssetScope", selected.scope || "global");
    setValue("designerAssetType", selected.type || selected.path?.split("/")[0] || "steps");
    setValue("designerAssetPath", selected.path || "");
    renderEditorView();
  }

  function syncSelectedFromInputs() {
    const path = el("designerAssetPath")?.value || "";
    state.selected = { ...(state.selected || {}), scope: filterScope(), type: filterType(), path, name: path.split("/").pop() || "" };
    renderEditorView();
  }

  function setEditorView(view) {
    state.view = view === "preview" ? "preview" : "edit";
    renderEditorView();
  }

  function renderEditorView() {
    const edit = el("designerAssetContent");
    const preview = el("designerAssetPreview");
    const editTab = el("designerAssetEditTab");
    const previewTab = el("designerAssetPreviewTab");
    if (!edit || !preview) return;
    const previewMode = state.view === "preview";
    edit.hidden = previewMode;
    preview.hidden = !previewMode;
    editTab?.classList.toggle("active", !previewMode);
    previewTab?.classList.toggle("active", previewMode);
    previewTab?.toggleAttribute("disabled", !isMarkdownAsset());
    if (previewMode) preview.innerHTML = renderMarkdownPreview(edit.value || "", isMarkdownAsset());
  }

  function isMarkdownAsset() {
    const path = el("designerAssetPath")?.value || state.selected?.path || "";
    return /\.(md|markdown|txt)$/i.test(path);
  }

  function filterScope() { return el("designerAssetScope")?.value || "global"; }
  function filterType() { return el("designerAssetType")?.value || "steps"; }
  function projectPath() { return el("designerAssetProjectPath")?.value?.trim() || ""; }
  function projectQuery(prefix = "?") { const value = projectPath(); return value ? `${prefix}project_path=${encodeURIComponent(value)}` : ""; }
  function setValue(id, value) { const target = el(id); if (target) target.value = value; }
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

function filterTypeLabel(type) {
  return { steps: "skill", contracts: "metadata", functions: "Python function", workflows: "workflow" }[type] || type;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}
