export function createArtifacts(ctx) {
  const { api, state, ui } = ctx;
  const PREVIEW_CHUNK_CHARS = 500_000;
  let previewLimit = PREVIEW_CHUNK_CHARS;
  let currentView = "essential";
  let stepFilter = null;
  let selectedArtifact = null;
  let selectedData = null;
  let previewMode = true;
  let bound = false;
  let stepDialog = { run: null, step: null, rows: [], selectedId: null, data: null, preview: true };
  const categoryLabels = Object.freeze({
    validation: "驗證",
    report: "報告",
    diff: "變更",
    patch: "Patch",
    step: "Step",
    console: "Console",
    metadata: "Metadata",
    prompt: "Prompt",
    debug: "診斷",
    unclassified: "未分類",
  });

  const escapeHtml = (value = "") => ui.escapeHtml(value);
  const sanitizeDownloadName = (path = "artifact.txt") => {
    const name = String(path || "artifact.txt").split(/[\\/]/).filter(Boolean).pop() || "artifact.txt";
    return name.replace(/[^a-zA-Z0-9._-]/g, "_");
  };
  const inlineMarkdown = (value = "") => escapeHtml(value)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

  function renderMarkdownTable(lines) {
    if (lines.length < 2) return "";
    const split = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
    const headers = split(lines[0]);
    const rows = lines.slice(2).map(split).filter((row) => row.length);
    return `<div class="markdown-table-wrap"><table><thead><tr>${headers.map((cell) => `<th>${inlineMarkdown(cell)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${headers.map((_, index) => `<td>${inlineMarkdown(row[index] || "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }

  function renderMarkdown(markdown = "") {
    const lines = String(markdown || "").replace(/\r\n/g, "\n").split("\n");
    const html = [];
    let paragraph = [];
    let list = [];
    let table = [];
    let code = [];
    let inCode = false;
    const flushParagraph = () => { if (paragraph.length) { html.push(`<p>${inlineMarkdown(paragraph.join(" "))}</p>`); paragraph = []; } };
    const flushList = () => { if (list.length) { html.push(`<ul>${list.map((item) => `<li>${inlineMarkdown(item)}</li>`).join("")}</ul>`); list = []; } };
    const flushTable = () => { if (table.length) { html.push(renderMarkdownTable(table)); table = []; } };
    const flushCode = () => { if (code.length) { html.push(`<pre><code>${escapeHtml(code.join("\n"))}</code></pre>`); code = []; } };
    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed.startsWith("```")) {
        flushParagraph(); flushList(); flushTable();
        if (inCode) flushCode();
        inCode = !inCode;
        continue;
      }
      if (inCode) { code.push(line); continue; }
      if (/^\|.+\|$/.test(trimmed)) { flushParagraph(); flushList(); table.push(trimmed); continue; }
      flushTable();
      if (!trimmed) { flushParagraph(); flushList(); continue; }
      const heading = trimmed.match(/^(#{1,6})\s+(.+)$/);
      if (heading) { flushParagraph(); flushList(); const level = Math.min(6, heading[1].length); html.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`); continue; }
      const bullet = trimmed.match(/^[-*+]\s+(.+)$/);
      if (bullet) { flushParagraph(); list.push(bullet[1]); continue; }
      paragraph.push(trimmed);
    }
    flushCode(); flushTable(); flushParagraph(); flushList();
    return html.join("\n") || '<p class="muted">Empty artifact.</p>';
  }

  function renderJsonNode(value, key = null, depth = 0) {
    const label = key === null ? "" : `<span class="json-key">${escapeHtml(key)}</span><span class="json-colon">: </span>`;
    if (value === null || typeof value !== "object") {
      const klass = value === null ? "null" : typeof value;
      return `<div class="json-leaf depth-${Math.min(depth, 8)}">${label}<span class="json-${klass}">${escapeHtml(JSON.stringify(value))}</span></div>`;
    }
    const entries = Array.isArray(value) ? value.map((item, index) => [String(index), item]) : Object.entries(value);
    return `<details class="json-node depth-${Math.min(depth, 8)}" ${depth < 2 ? "open" : ""}><summary>${label}<span>${Array.isArray(value) ? `[${entries.length}]` : `{${entries.length}}`}</span></summary><div>${entries.map(([childKey, child]) => renderJsonNode(child, childKey, depth + 1)).join("")}</div></details>`;
  }

  function renderLog(content = "") {
    const lines = String(content || "").split("\n");
    return `<div class="artifact-log-view">${lines.slice(0, 10000).map((line, index) => `<div><span>${index + 1}</span><code>${escapeHtml(line || " ")}</code></div>`).join("")}${lines.length > 10000 ? `<div class="artifact-truncated">僅顯示前 10,000 行。</div>` : ""}</div>`;
  }

  function previewKind(row = {}) {
    if (row.preview_kind) return String(row.preview_kind);
    const media = String(row.media_type || "").split(";", 1)[0].toLowerCase();
    const role = String(row.role || "").toLowerCase();
    if (["application/json", "application/ld+json"].includes(media) || media.endsWith("+json") || ["state", "events", "debug-bundle", "version", "artifact-index"].includes(role)) return "json";
    if (media === "text/markdown") return "markdown";
    if (["log", "timeline"].includes(role)) return "log";
    if (!media || media.startsWith("text/") || ["application/xml", "application/yaml", "application/x-yaml", "application/toml", "application/sql", "application/javascript", "application/x-javascript", "application/x-sh", "application/x-shellscript", "image/svg+xml"].includes(media) || media.endsWith("+xml")) return "text";
    return "binary";
  }

  function renderPreviewHtml(data, content) {
    const kind = previewKind(data);
    if (kind === "json") {
      try { return `<div class="artifact-json-tree">${renderJsonNode(JSON.parse(content))}</div>`; }
      catch { return `<pre>${escapeHtml(content)}</pre>`; }
    }
    if (kind === "markdown") return `<article class="artifact-markdown-preview step-files-markdown-preview">${renderMarkdown(content)}</article>`;
    if (kind === "log") return renderLog(content);
    if (kind === "binary") return '<div class="artifact-preview-unavailable"><strong>此格式不支援文字預覽</strong><span>請下載原始檔案查看。</span></div>';
    return `<pre>${escapeHtml(content)}</pre>`;
  }

  function normalizedArtifact(row = {}) {
    const path = String(row.path || row.storage_path || "").replaceAll("\\", "/");
    const runId = row.run_id || state.activeRunId;
    return {
      ...row,
      id: row.id || (runId && path ? `${runId}:${path.replaceAll("/", "|")}` : null),
      path,
      category: row.category || "unclassified",
      role: row.role || "unclassified",
      visibility: row.visibility || "supporting",
      display_name: row.display_name || "未分類產物",
      display_order: Number(row.display_order ?? 900),
      producer_step_key: row.producer_step_key || null,
      media_type: row.media_type || "text/plain",
      preview_kind: previewKind(row),
    };
  }

  function filterRows() {
    const query = (ui.byKey("artifactSearch")?.value || "").trim().toLowerCase();
    return state.currentArtifacts.filter((row) => {
      if (stepFilter && row.producer_step_key !== stepFilter) return false;
      if (currentView === "essential" && row.visibility !== "essential") return false;
      if (currentView === "validation" && row.category !== "validation") return false;
      if (currentView === "report" && row.category !== "report") return false;
      if (currentView === "diagnostic" && row.visibility !== "diagnostic") return false;
      if (query && !`${row.display_name} ${row.path} ${row.category} ${row.role}`.toLowerCase().includes(query)) return false;
      return true;
    });
  }

  function renderList() {
    const target = ui.byKey("artifacts");
    if (!target) return;
    const rows = filterRows();
    target.innerHTML = "";
    let lastCategory = null;
    for (const row of rows) {
      if (row.category !== lastCategory) {
        const heading = document.createElement("div");
        heading.className = "artifact-category-heading";
      heading.textContent = categoryLabels[row.category] || row.category;
        target.appendChild(heading);
        lastCategory = row.category;
      }
      const button = document.createElement("button");
      button.type = "button";
      button.className = `artifact-list-item${selectedArtifact?.id === row.id ? " active" : ""}`;
      button.innerHTML = `<span class="artifact-role-icon">${escapeHtml(String(row.role || "A").slice(0, 1).toUpperCase())}</span><span><strong>${escapeHtml(row.display_name)}</strong><small>${escapeHtml(row.role)} · ${formatBytes(row.size || 0)}</small><em>${escapeHtml(row.path || "")}</em></span>`;
      button.title = row.path || row.display_name;
      button.onclick = () => open(row.id, { activateArtifactsTab: false });
      target.appendChild(button);
    }
    if (!rows.length) target.innerHTML = ui.emptyState(stepFilter ? "此 Step 尚無執行產物" : "沒有符合條件的執行產物", "調整分類或搜尋條件。");
  }

  function formatBytes(value) {
    const bytes = Number(value || 0);
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  }

  function renderSelected() {
    const data = selectedData;
    const source = ui.byKey("artifactContent");
    const rendered = ui.byKey("artifactRenderedContent");
    const title = ui.byKey("artifactDisplayName");
    const meta = ui.byKey("artifactMeta");
    const openStep = ui.byKey("artifactOpenStep");
    if (!source || !rendered || !data) return;
    const content = String(data.content || "");
    const truncated = content.length > previewLimit;
    const visibleContent = truncated ? content.slice(0, previewLimit) : content;
    if (title) title.textContent = data.display_name || "未分類產物";
    if (meta) meta.textContent = `${data.category || "unclassified"} · ${data.role || "unclassified"} · ${formatBytes(data.size || content.length)}${data.producer_step_key ? ` · ${data.producer_step_key}` : ""}${data.content_hash ? ` · ${String(data.content_hash).slice(0, 12)}` : ""}`;
    if (openStep) {
      openStep.hidden = !data.producer_step_key;
      openStep.onclick = () => openProducerStep(data.producer_step_key);
    }
    source.textContent = visibleContent + (truncated ? "\n\n[尚有內容未顯示；可載入更多或下載完整檔案。]" : "");
    source.hidden = previewMode;
    rendered.hidden = !previewMode;
    if (previewMode) {
      rendered.innerHTML = renderPreviewHtml(data, visibleContent);
      if (truncated) rendered.insertAdjacentHTML("beforeend", '<div class="artifact-truncated">尚有內容未顯示；可載入更多或下載完整檔案。</div>');
    }
    const toggle = ui.byKey("artifactPreviewToggle");
    if (toggle) toggle.textContent = previewMode ? "原始內容" : "預覽";
    const loadMore = ui.byKey("artifactLoadMore");
    if (loadMore) {
      loadMore.hidden = !truncated;
      loadMore.textContent = truncated ? `載入更多 · ${formatBytes(previewLimit)} / ${formatBytes(content.length)}` : "已載入完整內容";
    }
    renderList();
  }

  async function openProducerStep(stepKey) {
    if (!stepKey || !state.activeRunId) return;
    try {
      const run = await api.request(`/api/workflow-runs/${state.activeRunId}`);
      const step = (run.steps || []).find((item) => item.key === stepKey);
      if (step) ctx.features.runs.openStepDetailModal(run, step);
    } catch (err) {
      ctx.features.console.append("logs", `Unable to open producer step: ${err.message}`);
    }
  }

  async function load(artifactId) {
    return api.request(`/api/artifacts/${encodeURIComponent(artifactId)}`);
  }

  async function open(artifactId, { activateArtifactsTab = true } = {}) {
    if (activateArtifactsTab) await ctx.features.diagnostics.open("diagnosticArtifacts");
    const previousId = selectedArtifact?.id;
    selectedArtifact = state.currentArtifacts.find((row) => row.id === artifactId) || selectedArtifact;
    if (previousId !== artifactId) previewLimit = PREVIEW_CHUNK_CHARS;
    try {
      selectedData = normalizedArtifact({ ...(selectedArtifact || {}), ...(await load(artifactId)) });
      state.selectedStepArtifactId = artifactId;
      renderSelected();
    } catch (err) {
      const rendered = ui.byKey("artifactRenderedContent");
      const source = ui.byKey("artifactContent");
      if (rendered) { rendered.hidden = false; rendered.innerHTML = `<div class="artifact-preview-unavailable"><strong>預覽載入失敗</strong><span>${escapeHtml(err.message)}</span></div>`; }
      if (source) source.hidden = true;
      throw err;
    }
  }

  async function preview(artifactId, options = {}) {
    return open(artifactId, options);
  }

  function stepArtifactPaths(step = {}) {
    const config = step.config || {};
    const list = (value) => value == null ? [] : Array.isArray(value) ? value : [value];
    const contracts = config.artifactContracts || config.artifact_contracts || [];
    const contractPaths = Array.isArray(contracts)
      ? contracts.map((item) => item?.path || item?.file || item?.output)
      : Object.keys(contracts || {});
    const values = [
      ...list(config.contextArtifacts),
      ...list(config.dependsOnArtifacts),
      ...list(config.expectedFiles),
      ...list(config.outputs),
      ...contractPaths,
      config.outputFile || config.filename || "",
      step.key ? `prompts/${step.key}.md` : "",
      step.key ? `prompts/${step.key}.effective.md` : "",
      step.key ? `prompts/${step.key}.prompt-meta.json` : "",
    ].filter(Boolean);
    return [...new Set(values.map((value) => {
      const path = String(value).replaceAll("\\", "/");
      return path.startsWith("output/") || path.startsWith("input/") || path.startsWith("prompts/") || path.startsWith(".workflow/") ? path : `output/${path}`;
    }))];
  }

  function artifactsForStep(step = {}, artifactList = state.currentArtifacts) {
    const exactPaths = new Set(stepArtifactPaths(step));
    return artifactList.filter((row) => row.producer_step_key === step.key || exactPaths.has(row.path));
  }

  function ensureStepFilesModal() {
    let backdrop = document.getElementById("stepFilesModalBackdrop");
    if (backdrop) return backdrop;
    backdrop = document.createElement("div");
    backdrop.id = "stepFilesModalBackdrop";
    backdrop.className = "step-files-modal-backdrop";
    backdrop.tabIndex = -1;
    backdrop.hidden = true;
    backdrop.innerHTML = `
      <section class="step-files-modal-card" role="dialog" aria-modal="true" aria-labelledby="stepFilesModalTitle">
        <header class="step-files-modal-head">
          <div class="step-files-modal-title-wrap"><span>STEP ARTIFACTS</span><h2 id="stepFilesModalTitle">對應文件</h2><p id="stepFilesModalMeta"></p></div>
          <button class="step-files-modal-close" type="button" aria-label="關閉對應文件">×</button>
        </header>
        <nav id="stepFilesTabs" class="step-files-tabs" aria-label="Step 對應文件"></nav>
        <div class="step-files-active-head"><strong id="stepFilesActiveName">選擇文件</strong><div class="step-files-actions"><button data-step-preview-toggle class="mini-button active" type="button">預覽</button><button data-step-copy class="mini-button" type="button">複製</button><button data-step-download class="mini-button" type="button">下載</button></div></div>
        <div class="step-files-preview-host"><div id="stepFilesRendered" class="artifact-rendered-content step-files-rendered"></div><pre id="stepFilesContent" class="step-files-content" hidden></pre></div>
      </section>`;
    document.body.appendChild(backdrop);
    const close = () => closeStepFilesModal();
    backdrop.querySelector(".step-files-modal-close")?.addEventListener("click", close);
    backdrop.addEventListener("click", (event) => { if (event.target === backdrop) close(); });
    backdrop.addEventListener("keydown", (event) => { if (event.key === "Escape") close(); });
    backdrop.querySelector("[data-step-preview-toggle]")?.addEventListener("click", () => {
      stepDialog.preview = !stepDialog.preview;
      renderStepDialogContent();
    });
    backdrop.querySelector("[data-step-copy]")?.addEventListener("click", async (event) => {
      if (!stepDialog.data) return;
      try {
        await navigator.clipboard.writeText(String(stepDialog.data.content || ""));
        event.currentTarget.textContent = "已複製";
        setTimeout(() => { if (event.currentTarget) event.currentTarget.textContent = "複製"; }, 1000);
      } catch (err) { ctx.features.console.append("logs", `Artifact copy failed: ${err.message}`); }
    });
    backdrop.querySelector("[data-step-download]")?.addEventListener("click", () => downloadArtifact(stepDialog.data));
    return backdrop;
  }

  function downloadArtifact(data) {
    if (!data) return;
    if (previewKind(data) === "binary" && data.id) {
      const anchor = document.createElement("a");
      anchor.href = `/api/artifacts/${encodeURIComponent(data.id)}/download`;
      anchor.download = sanitizeDownloadName(data.path);
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      return;
    }
    const blob = new Blob([String(data.content || "")], { type: `${data.media_type || "text/plain"};charset=utf-8` });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = sanitizeDownloadName(data.path);
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
  }

  function closeStepFilesModal() {
    const backdrop = document.getElementById("stepFilesModalBackdrop");
    if (backdrop) backdrop.hidden = true;
    document.body.classList.remove("artifact-modal-open");
  }

  function renderStepDialogTabs() {
    const tabs = document.getElementById("stepFilesTabs");
    if (!tabs) return;
    tabs.innerHTML = stepDialog.rows.map((row) => `<button class="step-files-tab${row.id === stepDialog.selectedId ? " active" : ""}" type="button" data-step-dialog-artifact="${escapeHtml(row.id)}" title="${escapeHtml(row.path || row.display_name)}">${escapeHtml(row.display_name || row.path)}</button>`).join("");
    tabs.querySelectorAll("[data-step-dialog-artifact]").forEach((button) => button.addEventListener("click", () => openStepDialogArtifact(button.dataset.stepDialogArtifact)));
  }

  function renderStepDialogContent() {
    const data = stepDialog.data;
    const rendered = document.getElementById("stepFilesRendered");
    const source = document.getElementById("stepFilesContent");
    const name = document.getElementById("stepFilesActiveName");
    const toggle = document.querySelector("#stepFilesModalBackdrop [data-step-preview-toggle]");
    if (!rendered || !source || !data) return;
    const content = String(data.content || "");
    if (name) name.textContent = `${data.display_name || "Step 產物"} · ${data.path || data.name || ""}`;
    source.textContent = content;
    source.hidden = stepDialog.preview;
    rendered.hidden = !stepDialog.preview;
    if (stepDialog.preview) rendered.innerHTML = renderPreviewHtml(data, content);
    if (toggle) {
      toggle.textContent = stepDialog.preview ? "原始內容" : "預覽";
      toggle.classList.toggle("active", stepDialog.preview);
    }
    renderStepDialogTabs();
  }

  async function openStepDialogArtifact(artifactId) {
    stepDialog.selectedId = artifactId;
    stepDialog.data = null;
    renderStepDialogTabs();
    const rendered = document.getElementById("stepFilesRendered");
    if (rendered) rendered.innerHTML = '<div class="artifact-preview-loading">載入文件中…</div>';
    try {
      const base = stepDialog.rows.find((row) => row.id === artifactId) || {};
      stepDialog.data = normalizedArtifact({ ...base, ...(await load(artifactId)) });
      state.selectedStepArtifactId = artifactId;
      renderStepDialogContent();
    } catch (err) {
      if (rendered) rendered.innerHTML = `<div class="artifact-preview-unavailable"><strong>預覽載入失敗</strong><span>${escapeHtml(err.message)}</span></div>`;
    }
  }

  async function openStepFilesModal(run, step, { preview: shouldPreview = true, artifactId = null } = {}) {
    const merged = new Map();
    for (const row of [...(run.artifacts || []), ...(state.currentArtifacts || [])]) {
      const normalized = normalizedArtifact(row);
      const key = normalized.id || normalized.path;
      if (key) merged.set(key, { ...(merged.get(key) || {}), ...normalized });
    }
    const related = artifactsForStep(step, [...merged.values()]);
    if (!related.length) return;
    const backdrop = ensureStepFilesModal();
    stepDialog = {
      run,
      step,
      rows: related.sort((a, b) => a.display_order - b.display_order || a.display_name.localeCompare(b.display_name)),
      selectedId: artifactId && related.some((row) => row.id === artifactId) ? artifactId : (state.selectedStepArtifactId && related.some((row) => row.id === state.selectedStepArtifactId) ? state.selectedStepArtifactId : related[0].id),
      data: null,
      preview: Boolean(shouldPreview),
    };
    const title = document.getElementById("stepFilesModalTitle");
    const meta = document.getElementById("stepFilesModalMeta");
    if (title) title.textContent = `${step.title || step.key || "Step"} · 對應文件`;
    if (meta) meta.textContent = `${related.length} 個文件 · 僅顯示此 Step 的 Prompt、輸出與明確相依 Artifact`;
    renderStepDialogTabs();
    backdrop.hidden = false;
    document.body.classList.add("artifact-modal-open");
    backdrop.querySelector(".step-files-modal-close")?.focus();
    await openStepDialogArtifact(stepDialog.selectedId);
  }


  function clearStepFilter() {
    stepFilter = null;
    renderList();
  }

  function renderTabs() {
    document.querySelectorAll("[data-artifact-view]").forEach((button) => button.classList.toggle("active", button.dataset.artifactView === currentView));
  }

  function bind() {
    if (bound) return;
    bound = true;
    document.querySelectorAll("[data-artifact-view]").forEach((button) => button.addEventListener("click", () => {
      currentView = button.dataset.artifactView || "essential";
      stepFilter = null;
      renderTabs();
      renderList();
    }));
    ui.byKey("artifactSearch")?.addEventListener("input", renderList);
    ui.byKey("artifactPreviewToggle")?.addEventListener("click", () => { previewMode = !previewMode; renderSelected(); });
    ui.byKey("artifactLoadMore")?.addEventListener("click", () => { previewLimit += PREVIEW_CHUNK_CHARS; renderSelected(); });
    ui.byKey("artifactCopy")?.addEventListener("click", async () => {
      if (!selectedData) return;
      try { await navigator.clipboard.writeText(String(selectedData.content || "")); ui.byKey("artifactCopy").textContent = "已複製"; setTimeout(() => { if (ui.byKey("artifactCopy")) ui.byKey("artifactCopy").textContent = "複製"; }, 1000); }
      catch (err) { ctx.features.console.append("logs", `Artifact copy failed: ${err.message}`); }
    });
    ui.byKey("artifactDownload")?.addEventListener("click", () => downloadArtifact(selectedData));
  }

  function render(artifactList) {
    bind();
    state.currentArtifacts = (artifactList || []).map(normalizedArtifact).sort((a, b) => a.display_order - b.display_order || a.display_name.localeCompare(b.display_name) || String(a.path).localeCompare(String(b.path)));
    const totalBytes = state.currentArtifacts.reduce((sum, row) => sum + Number(row.size || 0), 0);
    const diagnosticRows = state.currentArtifacts.filter((row) => row.visibility === "diagnostic");
    const diagnosticBytes = diagnosticRows.reduce((sum, row) => sum + Number(row.size || 0), 0);
    const storage = ui.byKey("artifactStorageSummary");
    if (storage) {
      const archive = state.lastArtifactCompaction;
      storage.textContent = `${state.currentArtifacts.length} 個 · ${formatBytes(totalBytes)} · 診斷 ${diagnosticRows.length}/${formatBytes(diagnosticBytes)}${archive?.compacted ? ` · ZIP ${formatBytes(archive.size_bytes || 0)}` : ""}`;
      storage.title = "目前 Run 的 Artifact 數量、估計大小與診斷產物占用；封存不會刪除原始檔，除非明確啟用 Prune Policy。";
    }
    if (selectedArtifact && !state.currentArtifacts.some((row) => row.id === selectedArtifact.id)) { selectedArtifact = null; selectedData = null; }
    renderTabs();
    renderList();
    if (!selectedData) {
      const first = filterRows()[0];
      if (first) open(first.id, { activateArtifactsTab: false }).catch((err) => ctx.features.console.append("logs", `Artifact preview failed: ${err.message}`));
    }
  }

  return {
    stepArtifactPaths,
    artifactsForStep,
    load,
    preview,
    render,
    renderList,
    open,
    openStepFilesModal,
    closeStepFilesModal,
    clearStepFilter,
  };
}
