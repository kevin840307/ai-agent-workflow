import { LocalStore, StorageKeys } from "../core/storage.js?v=20260712-ui-v22";

function normalizePath(value = "") {
  return String(value || "").replaceAll("\\", "/").replace(/^\.\//, "").split("/").filter((part) => part && part !== ".").join("/");
}

function statusLabel(status = "modified") {
  return ({ added: "新增", new: "新增", modified: "修改", changed: "修改", deleted: "刪除", removed: "刪除" })[status] || "變更";
}

function patchFor(diff, path) {
  const exact = (diff?.files || []).find((item) => normalizePath(item.path) === normalizePath(path));
  if (exact?.patch) return exact.patch;
  const chunks = String(diff?.patch || "").split(/(?=--- a\/)/g);
  return chunks.find((chunk) => chunk.includes(`+++ b/${path}`) || chunk.startsWith(`--- a/${path}`)) || "";
}

function parseUnifiedPatch(chunk = "") {
  const rows = [];
  let oldLine = 0;
  let newLine = 0;
  let hunkIndex = -1;
  for (const raw of String(chunk || "").split("\n")) {
    if (raw.startsWith("---") || raw.startsWith("+++")) continue;
    const match = raw.match(/^@@\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@(.*)$/);
    if (match) {
      oldLine = Number(match[1]);
      newLine = Number(match[2]);
      hunkIndex += 1;
      rows.push({ kind: "hunk", oldNo: "", newNo: "", text: String(match[3] || "").trim() || `變更區段 ${hunkIndex + 1}`, hunkIndex });
      continue;
    }
    if (raw.startsWith("+")) {
      rows.push({ kind: "added", oldNo: "", newNo: newLine, text: raw.slice(1), hunkIndex });
      newLine += 1;
    } else if (raw.startsWith("-")) {
      rows.push({ kind: "removed", oldNo: oldLine, newNo: "", text: raw.slice(1), hunkIndex });
      oldLine += 1;
    } else {
      rows.push({ kind: "context", oldNo: oldLine, newNo: newLine, text: raw.startsWith(" ") ? raw.slice(1) : raw, hunkIndex });
      oldLine += 1;
      newLine += 1;
    }
  }
  return rows;
}

function parseTestCounts(text = "") {
  const value = String(text || "");
  const numbers = {};
  for (const [key, pattern] of Object.entries({ passed: /(\d+)\s+passed/i, failed: /(\d+)\s+failed/i, skipped: /(\d+)\s+skipped/i })) {
    const match = value.match(pattern);
    if (match) numbers[key] = Number(match[1]);
  }
  return numbers;
}

export function createPatchReview(ctx) {
  const { api, state, ui } = ctx;
  const DIFF_PAGE_ROWS = 1500;
  let model = null;
  let overview = null;
  let selectedPath = null;
  let selectedFiles = new Set();
  let viewedFiles = new Set();
  let viewMode = LocalStore.getString(StorageKeys.patchViewMode, "unified") || "unified";
  let fontScale = Number(LocalStore.getString(StorageKeys.patchFontScale, "100")) || 100;
  let sidebarWidth = Math.min(520, Math.max(240, Number(LocalStore.getString(StorageKeys.patchSidebarWidth, "280")) || 280));
  const rowLimitByFile = new Map();
  let filter = "all";
  let search = "";
  let validationInFlight = false;
  let decisionInFlight = false;
  let loadedRunId = null;
  let loadedPatchHash = null;

  const els = () => ({
    backdrop: ui.byKey("diffDialogBackdrop"),
    dialog: ui.byKey("diffDialog"),
    title: ui.byKey("diffDialogTitle"),
    subtitle: ui.byKey("diffDialogSubtitle"),
    summary: ui.byKey("diffDialogSummary"),
    files: ui.byKey("diffDialogFileList"),
    content: ui.byKey("diffDialogContent"),
    footer: ui.byKey("patchReviewFooter"),
    selection: ui.byKey("patchReviewSelection"),
    validation: ui.byKey("patchReviewValidation"),
    approve: ui.byKey("approvePatch"),
    approveApply: ui.byKey("approveApplyPatch"),
    reject: ui.byKey("rejectPatch"),
    validate: ui.byKey("validatePatchSelection"),
    sidebar: ui.byKey("diffDialogFiles"),
    sidebarToggle: ui.byKey("togglePatchFiles"),
    focusToggle: ui.byKey("togglePatchFocus"),
    search: ui.byKey("patchFileSearch"),
    rejectPanel: ui.byKey("patchRejectPanel"),
    rejectStep: ui.byKey("patchRejectStep"),
    rejectReason: ui.byKey("patchRejectReason"),
    rejectComment: ui.byKey("patchRejectComment"),
    confirmReject: ui.byKey("confirmRejectPatch"),
    cancelReject: ui.byKey("cancelRejectPatch"),
  });

  function normalizedFiles() {
    const diffFiles = model?.diff?.files || [];
    const metadata = new Map((model?.files || []).map((row) => [normalizePath(row.path), row]));
    return (model?.changed_files || diffFiles.map((row) => row.path) || []).map((raw) => {
      const path = normalizePath(typeof raw === "string" ? raw : raw.path);
      const diff = diffFiles.find((row) => normalizePath(row.path) === path) || {};
      const meta = metadata.get(path) || {};
      return {
        ...diff,
        ...meta,
        path,
        status: diff.status || meta.status || (meta.operation === "delete" ? "deleted" : "modified"),
        added: Number(diff.added ?? diff.added_lines ?? 0),
        removed: Number(diff.removed ?? diff.deleted_lines ?? 0),
      };
    }).filter((row) => row.path);
  }

  function selectedList() {
    return normalizedFiles().map((row) => row.path).filter((path) => selectedFiles.has(path));
  }

  function currentSelectionHash() {
    const selected = selectedList();
    if (!model?.patch_hash || !selected.length) return "";
    const validation = model.partial_validations || {};
    return Object.keys(validation).find((key) => {
      const row = validation[key] || {};
      return row.patch_hash === model.patch_hash && JSON.stringify([...(row.files || [])].sort()) === JSON.stringify([...selected].sort());
    }) || (model.approval?.files && JSON.stringify([...model.approval.files].sort()) === JSON.stringify([...selected].sort()) ? model.approval.selection_hash || "" : "");
  }

  function isFullSelection() {
    const all = normalizedFiles().map((row) => row.path);
    return all.length > 0 && selectedFiles.size === all.length && all.every((path) => selectedFiles.has(path));
  }

  function validationState() {
    if (!selectedFiles.size) return { valid: false, label: "尚未選擇檔案", detail: "至少選擇一個檔案。" };
    if (isFullSelection()) {
      const rows = overview?.validation || [];
      const required = rows.filter((row) => row.required !== false);
      const passed = required.length > 0 && required.every((row) => ["passed", "passed_with_baseline"].includes(row.status) && row.executed !== false);
      return {
        valid: passed,
        label: passed ? "完整 Patch 驗證通過" : "完整 Patch 尚未通過必要驗證",
        detail: passed ? `${required.length} 項 Required Evidence 可用。` : "請先完成驗證，或查看驗證 Tab。",
      };
    }
    const hash = currentSelectionHash();
    const record = hash ? model?.partial_validations?.[hash] : null;
    const passed = record && ["passed", "passed_with_baseline"].includes(record.status) && Number(record.executed || 0) > 0;
    return {
      valid: Boolean(passed),
      label: passed ? "Partial Patch 已重新驗證" : "選取範圍已改變，原驗證失效",
      detail: passed ? `${record.executed} 個驗證階段已執行。` : "重新組合選取檔案並通過 Required Validation 後才能核准。",
    };
  }

  function approvalState() {
    const selected = selectedList();
    const approval = model?.approval || {};
    const sameSelection = JSON.stringify([...(approval.files || [])].sort()) === JSON.stringify([...selected].sort());
    const selectionEvidenceHash = isFullSelection()
      ? model?.validation_evidence_hash
      : (currentSelectionHash() ? model?.partial_validations?.[currentSelectionHash()]?.evidence_hash : null);
    const approved = approval.state === "approved"
      && approval.patch_hash === model?.patch_hash
      && approval.validation_evidence_hash === selectionEvidenceHash
      && sameSelection;
    return { approved, state: approved ? "approved" : approval.state || "pending" };
  }

  function renderSummary() {
    const files = normalizedFiles();
    const added = files.reduce((sum, row) => sum + row.added, 0);
    const removed = files.reduce((sum, row) => sum + row.removed, 0);
    const approval = approvalState();
    const e = els();
    if (e.title) e.title.textContent = "Patch 審核";
    if (e.subtitle) e.subtitle.textContent = `${files.length} files · Patch ${String(model?.patch_hash || "-").slice(0, 12)} · ${approval.state}`;
    if (e.summary) e.summary.innerHTML = `<span>${files.length} files</span><span class="added">+${added}</span><span class="removed">-${removed}</span><span>${viewedFiles.size}/${files.length} 已查看</span>`;
  }

  function renderFileList() {
    const e = els();
    if (!e.files) return;
    const files = normalizedFiles().filter((row) => {
      if (filter !== "all" && row.status !== filter) return false;
      return !search || row.path.toLowerCase().includes(search.toLowerCase());
    });
    e.files.innerHTML = files.map((row) => `
      <div class="patch-workbench-file ${row.path === selectedPath ? "active" : ""} ${viewedFiles.has(row.path) ? "viewed" : "unviewed"}" data-patch-path="${ui.escapeHtml(row.path)}">
        <label class="patch-file-checkbox" title="選擇是否納入 Patch"><input type="checkbox" data-patch-check="${ui.escapeHtml(row.path)}" ${selectedFiles.has(row.path) ? "checked" : ""} /><span></span></label>
        <button type="button" data-patch-open="${ui.escapeHtml(row.path)}"><span class="change-kind ${ui.escapeHtml(row.status)}">${ui.escapeHtml(statusLabel(row.status))}</span><span class="patch-file-name"><strong>${ui.escapeHtml(row.path)}</strong><small>+${row.added} / -${row.removed}${row.producer_step_key ? ` · ${ui.escapeHtml(row.producer_step_key)}` : ""}</small></span><i aria-label="${viewedFiles.has(row.path) ? "已查看" : "未查看"}"></i></button>
      </div>`).join("") || ui.emptyState("沒有符合條件的檔案", "調整搜尋或篩選條件。");
    e.files.querySelectorAll("[data-patch-open]").forEach((button) => button.addEventListener("click", () => selectFile(button.dataset.patchOpen)));
    e.files.querySelectorAll("[data-patch-check]").forEach((input) => input.addEventListener("change", () => {
      const path = input.dataset.patchCheck;
      if (input.checked) selectedFiles.add(path); else selectedFiles.delete(path);
      invalidateVisibleApproval();
      renderRejectTargets();
      render();
    }));
  }

  function invalidateVisibleApproval() {
    const approval = model?.approval || {};
    const sameSelection = JSON.stringify([...(approval.files || [])].sort()) === JSON.stringify(selectedList().sort());
    if (!sameSelection && approval.state === "approved") approval.state = "stale";
  }

  function loadMoreControl(total, limit) {
    if (limit >= total) return "";
    return `<button class="diff-load-more" data-diff-load-more type="button">載入更多差異 · 已顯示 ${limit.toLocaleString()} / ${total.toLocaleString()} 行</button>`;
  }

  function renderUnified(rows, limit) {
    if (!rows.length) return `<div class="diff-empty"><strong>沒有文字差異</strong><span>可能是二進位檔、重新命名或刪除項目。</span></div>`;
    const visible = rows.slice(0, limit);
    return `<div class="diff-code unified" style="--diff-font-scale:${fontScale / 100}" role="region">${visible.map((row) => `<div class="diff-code-row ${row.kind}" ${row.kind === "hunk" ? `data-diff-hunk="${row.hunkIndex}"` : ""}><span>${row.oldNo}</span><span>${row.newNo}</span><code>${ui.escapeHtml(row.text || " ")}</code></div>`).join("")}${loadMoreControl(rows.length, visible.length)}</div>`;
  }

  function renderSplit(rows, limit) {
    if (!rows.length) return `<div class="diff-empty"><strong>沒有文字差異</strong><span>可能是二進位檔、重新命名或刪除項目。</span></div>`;
    const visible = rows.slice(0, limit);
    const longestLine = visible.reduce((max, row) => Math.max(max, String(row.text || "").length), 0);
    const sideMinWidth = Math.max(620, Math.min(1400, 92 + Math.min(longestLine, 180) * 7.2));
    const pairs = visible.map((row) => {
      if (row.kind === "hunk") return `<div class="split-diff-hunk" data-diff-hunk="${row.hunkIndex}">${ui.escapeHtml(row.text)}</div>`;
      const left = row.kind === "added" ? { no: "", text: "", kind: "empty" } : { no: row.oldNo, text: row.text, kind: row.kind };
      const right = row.kind === "removed" ? { no: "", text: "", kind: "empty" } : { no: row.newNo, text: row.text, kind: row.kind };
      return `<div class="split-diff-row"><div class="split-diff-cell ${left.kind}"><span>${left.no}</span><code>${ui.escapeHtml(left.text || " ")}</code></div><div class="split-diff-cell ${right.kind}"><span>${right.no}</span><code>${ui.escapeHtml(right.text || " ")}</code></div></div>`;
    }).join("");
    return `<div class="split-diff" style="--diff-font-scale:${fontScale / 100};--split-side-min:${sideMinWidth}px"><div class="split-diff-grid"><div class="split-diff-labels"><span>Before</span><span>After</span></div>${pairs}${loadMoreControl(rows.length, visible.length)}</div></div>`;
  }

  function renderContent() {
    const e = els();
    if (!e.content) return;
    const file = normalizedFiles().find((row) => row.path === selectedPath) || normalizedFiles()[0];
    if (!file) { e.content.innerHTML = ui.emptyState("沒有 Patch", "目前沒有檔案差異。"); return; }
    selectedPath = file.path;
    viewedFiles.add(file.path);
    const rows = parseUnifiedPatch(patchFor(model?.diff, file.path));
    const limit = Math.min(rows.length, rowLimitByFile.get(file.path) || DIFF_PAGE_ROWS);
    e.content.innerHTML = `<article class="patch-workbench-review"><header><div><span class="change-kind ${ui.escapeHtml(file.status)}">${ui.escapeHtml(statusLabel(file.status))}</span><div><h3>${ui.escapeHtml(file.path)}</h3><small>${ui.escapeHtml(file.producer_step_key || "Workflow")}</small></div></div><div class="change-review-stats"><span class="added">+${file.added}</span><span class="removed">-${file.removed}</span></div></header>${viewMode === "split" ? renderSplit(rows, limit) : renderUnified(rows, limit)}</article>`;
    e.content.querySelector("[data-diff-load-more]")?.addEventListener("click", () => {
      rowLimitByFile.set(file.path, Math.min(rows.length, limit + DIFF_PAGE_ROWS));
      renderContent();
    });
  }

  function renderFooter() {
    const e = els();
    const validation = validationState();
    const approval = approvalState();
    const files = normalizedFiles();
    const selectionHash = currentSelectionHash();
    if (e.selection) e.selection.innerHTML = `<strong>${selectedFiles.size}/${files.length} 個檔案</strong><span>${isFullSelection() ? "完整 Patch" : "Partial Patch"}</span>`;
    if (e.validation) e.validation.innerHTML = `<span class="patch-validation-state ${validation.valid ? "passed" : "blocked"}">${validation.valid ? "✓" : "!"}</span><div><strong>${ui.escapeHtml(validation.label)}</strong><small>${ui.escapeHtml(validation.detail)}</small></div>`;
    if (e.validate) {
      e.validate.hidden = isFullSelection();
      e.validate.disabled = validationInFlight || !selectedFiles.size || validation.valid;
      e.validate.textContent = validationInFlight ? "重新驗證中…" : validation.valid ? "已重新驗證" : "重新驗證選取範圍";
    }
    const canApprove = validation.valid && selectedFiles.size > 0 && !decisionInFlight;
    if (e.approve) { e.approve.disabled = !canApprove || approval.approved; e.approve.textContent = approval.approved ? "已核准" : "僅核准"; }
    if (e.approveApply) { e.approveApply.disabled = !canApprove && !approval.approved || !selectionHash && approval.approved || decisionInFlight; }
    if (e.reject) e.reject.disabled = decisionInFlight || !selectedFiles.size;
  }

  function renderToolbarState() {
    document.querySelectorAll("[data-patch-view]").forEach((button) => button.classList.toggle("active", button.dataset.patchView === viewMode));
    const e = els();
    if (e.dialog) e.dialog.style.setProperty("--patch-font-scale", String(fontScale / 100));
    if (e.sidebar && !e.dialog?.classList.contains("files-collapsed")) e.sidebar.style.width = `${sidebarWidth}px`;
    if (e.focusToggle) e.focusToggle.setAttribute("aria-pressed", String(e.dialog?.classList.contains("focus-mode")));
    if (e.sidebarToggle) e.sidebarToggle.setAttribute("aria-pressed", String(e.dialog?.classList.contains("files-collapsed")));
  }

  function render() {
    const active = normalizedFiles().find((row) => row.path === selectedPath) || normalizedFiles()[0];
    if (active) {
      selectedPath = active.path;
      viewedFiles.add(active.path);
    }
    renderSummary();
    renderFileList();
    renderContent();
    renderFooter();
    renderToolbarState();
  }

  function selectFile(path) {
    selectedPath = normalizePath(path);
    viewedFiles.add(selectedPath);
    render();
  }

  async function reload() {
    if (!state.activeRunId) return;
    const [patch, overviewPayload] = await Promise.all([
      api.request(`/api/workflow-runs/${state.activeRunId}/patch`),
      api.request(`/api/workflow-runs/${state.activeRunId}/overview`).catch(() => overview || {}),
    ]);
    const nextRunId = state.activeRunId;
    const nextPatchHash = patch?.patch_hash || null;
    if (loadedRunId !== nextRunId || loadedPatchHash !== nextPatchHash) {
      selectedFiles = new Set();
      viewedFiles = new Set();
      rowLimitByFile.clear();
      selectedPath = null;
    }
    loadedRunId = nextRunId;
    loadedPatchHash = nextPatchHash;
    model = patch;
    overview = overviewPayload;
    const files = normalizedFiles();
    if (!selectedFiles.size) selectedFiles = new Set(model.approval?.files?.length ? model.approval.files : files.map((row) => row.path));
    selectedFiles = new Set([...selectedFiles].filter((path) => files.some((row) => row.path === path)));
    selectedPath = files.some((row) => row.path === selectedPath) ? selectedPath : files[0]?.path || null;
    render();
  }

  async function approve({ apply = false } = {}) {
    if (!state.activeRunId || !model || decisionInFlight) return;
    decisionInFlight = true;
    renderFooter();
    try {
      const files = selectedList();
      await api.request(`/api/workflow-runs/${state.activeRunId}/actions`, {
        method: "POST",
        body: JSON.stringify({ action: "approve", files, patch_hash: model.patch_hash }),
      });
      await reload();
      if (apply) await applyApproved();
    } catch (err) {
      ctx.features.console.append("logs", `Patch approval failed: ${err.message}`);
      ctx.features.diagnostics.open("diagnosticLogs");
    } finally {
      decisionInFlight = false;
      renderFooter();
    }
  }

  async function applyApproved() {
    if (!state.activeRunId || !model || decisionInFlight) return;
    decisionInFlight = true;
    renderFooter();
    try {
      const files = selectedList();
      const selectionHash = model.approval?.selection_hash || currentSelectionHash();
      await api.request(`/api/workflow-runs/${state.activeRunId}/patch/apply`, {
        method: "POST",
        body: JSON.stringify({ files, patch_hash: model.patch_hash, selection_hash: selectionHash }),
      });
      await ctx.features.runs.follow(state.activeRunId);
      await reload();
    } catch (err) {
      ctx.features.console.append("logs", `Patch apply failed: ${err.message}`);
      ctx.features.diagnostics.open("diagnosticLogs");
    } finally {
      decisionInFlight = false;
      renderFooter();
    }
  }

  async function validateSelection() {
    if (!state.activeRunId || !model || validationInFlight || !selectedFiles.size) return;
    validationInFlight = true;
    renderFooter();
    try {
      await api.request(`/api/workflow-runs/${state.activeRunId}/patch/validate-selection`, {
        method: "POST",
        body: JSON.stringify({ files: selectedList(), patch_hash: model.patch_hash }),
      });
      await reload();
    } catch (err) {
      ctx.features.console.append("logs", `Partial patch validation failed: ${err.message}`);
      ctx.features.diagnostics.open("diagnosticLogs");
    } finally {
      validationInFlight = false;
      renderFooter();
    }
  }

  function renderRejectTargets() {
    const e = els();
    if (!e.rejectStep) return;
    const previous = e.rejectStep.value;
    const producers = [...new Set(normalizedFiles()
      .filter((row) => selectedFiles.has(row.path))
      .map((row) => String(row.producer_step_key || "").trim())
      .filter(Boolean))];
    e.rejectStep.innerHTML = `<option value="">僅記錄拒絕，不自動重試</option>${producers.map((stepKey) => `<option value="${ui.escapeHtml(stepKey)}">${ui.escapeHtml(stepKey)}</option>`).join("")}`;
    if ([...e.rejectStep.options].some((option) => option.value === previous)) e.rejectStep.value = previous;
  }

  async function reject() {
    const e = els();
    if (!state.activeRunId || !model || decisionInFlight) return;
    const reasonCode = e.rejectReason?.value || "other";
    const comment = e.rejectComment?.value?.trim() || "";
    const targetStep = e.rejectStep?.value || null;
    decisionInFlight = true;
    renderFooter();
    try {
      await api.request(`/api/workflow-runs/${state.activeRunId}/actions`, {
        method: "POST",
        body: JSON.stringify({ action: "reject", reason_code: reasonCode, comment, files: selectedList(), patch_hash: model.patch_hash, step_key: targetStep }),
      });
      if (e.rejectPanel) e.rejectPanel.hidden = true;
      close();
      await ctx.features.runs.follow(state.activeRunId);
    } catch (err) {
      ctx.features.console.append("logs", `Patch rejection failed: ${err.message}`);
    } finally {
      decisionInFlight = false;
      renderFooter();
    }
  }

  function nextFile(delta) {
    const files = normalizedFiles();
    if (!files.length) return;
    const current = Math.max(0, files.findIndex((row) => row.path === selectedPath));
    selectFile(files[(current + delta + files.length) % files.length].path);
  }

  function nextHunk(delta) {
    const e = els();
    const scrollRoot = e.content?.querySelector(".diff-code, .split-diff") || e.content;
    const hunks = [...(scrollRoot?.querySelectorAll("[data-diff-hunk]") || [])];
    if (!hunks.length || !scrollRoot) return;
    const rootTop = scrollRoot.getBoundingClientRect().top;
    const current = hunks.findIndex((node) => node.getBoundingClientRect().top > rootTop + 24);
    const targetIndex = delta > 0
      ? (current < 0 ? 0 : current)
      : (current < 0 ? hunks.length - 1 : Math.max(0, current - 2));
    hunks[targetIndex]?.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  function close() {
    const e = els();
    if (e.backdrop) e.backdrop.hidden = true;
    document.body.classList.remove("diff-dialog-open");
  }

  function bindOnce() {
    const e = els();
    if (!e.dialog || e.dialog.dataset.bound === "true") return;
    e.dialog.dataset.bound = "true";
    ui.byKey("closeDiffDialog")?.addEventListener("click", close);
    e.backdrop?.addEventListener("click", (event) => { if (event.target === e.backdrop) close(); });
    e.search?.addEventListener("input", (event) => { search = String(event.target.value || ""); renderFileList(); });
    document.querySelectorAll("[data-patch-filter]").forEach((button) => button.addEventListener("click", () => {
      filter = button.dataset.patchFilter || "all";
      document.querySelectorAll("[data-patch-filter]").forEach((item) => item.classList.toggle("active", item === button));
      renderFileList();
    }));
    document.querySelectorAll("[data-patch-view]").forEach((button) => button.addEventListener("click", () => {
      viewMode = button.dataset.patchView || "unified";
      LocalStore.setString(StorageKeys.patchViewMode, viewMode);
      render();
    }));
    document.querySelectorAll("[data-patch-font]").forEach((button) => button.addEventListener("click", () => {
      const direction = button.dataset.patchFont;
      fontScale = direction === "reset" ? 100 : Math.min(150, Math.max(80, fontScale + (direction === "up" ? 10 : -10)));
      LocalStore.setString(StorageKeys.patchFontScale, String(fontScale));
      render();
    }));
    if (LocalStore.getBoolean(StorageKeys.patchFilesCollapsed, false)) e.dialog.classList.add("files-collapsed");
    if (e.sidebar) e.sidebar.style.width = `${sidebarWidth}px`;
    e.sidebarToggle?.addEventListener("click", () => {
      e.dialog.classList.toggle("files-collapsed");
      LocalStore.setBoolean(StorageKeys.patchFilesCollapsed, e.dialog.classList.contains("files-collapsed"));
      renderToolbarState();
    });
    e.sidebar?.addEventListener("pointerup", () => {
      const width = Math.round(e.sidebar.getBoundingClientRect().width);
      if (width >= 240 && width <= 520) { sidebarWidth = width; LocalStore.setString(StorageKeys.patchSidebarWidth, String(width)); }
    });
    e.focusToggle?.addEventListener("click", () => { e.dialog.classList.toggle("focus-mode"); renderToolbarState(); });
    e.validate?.addEventListener("click", validateSelection);
    e.approve?.addEventListener("click", () => approve({ apply: false }));
    e.approveApply?.addEventListener("click", async () => {
      if (approvalState().approved) await applyApproved(); else await approve({ apply: true });
    });
    e.reject?.addEventListener("click", () => { renderRejectTargets(); if (e.rejectPanel) e.rejectPanel.hidden = false; e.rejectStep?.focus(); });
    e.cancelReject?.addEventListener("click", () => { if (e.rejectPanel) e.rejectPanel.hidden = true; });
    e.confirmReject?.addEventListener("click", reject);
    document.addEventListener("keydown", (event) => {
      if (e.backdrop?.hidden) return;
      if (event.target?.matches("input, textarea, select")) return;
      if (event.key === "Escape") { event.preventDefault(); close(); }
      else if (event.key.toLowerCase() === "f") { event.preventDefault(); e.dialog.classList.toggle("focus-mode"); renderToolbarState(); }
      else if (event.key.toLowerCase() === "j") { event.preventDefault(); nextFile(1); }
      else if (event.key.toLowerCase() === "k") { event.preventDefault(); nextFile(-1); }
      else if (event.key.toLowerCase() === "n") { event.preventDefault(); nextHunk(1); }
      else if (event.key.toLowerCase() === "p") { event.preventDefault(); nextHunk(-1); }
    });
  }

  async function open(path = null, suppliedOverview = null) {
    if (!state.activeRunId) return;
    bindOnce();
    overview = suppliedOverview || state.activeRunOverview || overview;
    const e = els();
    if (!e.backdrop) return;
    e.backdrop.hidden = false;
    document.body.classList.add("diff-dialog-open");
    try {
      await reload();
      if (path) selectFile(path);
      ui.byKey("closeDiffDialog")?.focus();
    } catch (err) {
      if (e.content) e.content.innerHTML = ui.emptyState("無法載入 Patch", err.message, "error");
    }
  }

  return { open, close, reload, render, validateSelection, approve, applyApproved };
}
