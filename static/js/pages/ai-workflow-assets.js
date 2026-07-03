import { installWorkflowAssetManager } from "./ai-workflow-assets/asset-manager.js?v=20260703-wf-wstep1";
import { el, escapeAttr, escapeHtml, toast } from "./workflow-designer/utils.js?v=20260703-wf-wstep1";

async function designerApi(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return response.status === 204 ? {} : response.json();
}

export function initWorkflowAssetsPage() {
  const status = el("designerBackendStatus");
  const manager = installWorkflowAssetManager({
    designerApi,
    el,
    escapeAttr,
    escapeHtml,
    toast,
    getSelectedStep: () => null,
    isReadonly: () => true,
    markWorkflowDirty: () => {},
    renderSettings: () => {},
    renderWorkflowViewOnly: () => {},
  });
  manager.bindEvents();
  manager.refreshAssetList().then((ok) => {
    if (status) status.textContent = ok === false ? "API Error" : "API OK";
  });
}
