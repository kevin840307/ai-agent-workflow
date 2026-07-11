function safeJson(value) {
  try { return JSON.stringify(value, null, 2); } catch (_err) { return String(value ?? ""); }
}

export function createDiagnostics(ctx) {
  const { api, state, ui } = ctx;
  const loaded = new Set();
  let currentPatch = null;
  let selectedPatchFiles = new Set();
  let patchView = "split";

  function patchChunkFor(path) {
    const fileDiff = (currentPatch?.diff?.files || []).find((item) => item.path === path);
    if (fileDiff?.patch) return fileDiff.patch;
    const chunks = String(currentPatch?.diff?.patch || "").split(/(?=--- a\/)/g);
    return chunks.find((chunk) => chunk.includes(`+++ b/${path}`) || chunk.startsWith(`--- a/${path}`)) || `${path} has no text diff preview.`;
  }

  function splitPatch(chunk) {
    const before = []; const after = [];
    String(chunk || "").split("\n").forEach((line) => {
      if (line.startsWith("---") || line.startsWith("+++") || line.startsWith("@@")) return;
      if (line.startsWith("-")) before.push(line.slice(1));
      else if (line.startsWith("+")) after.push(line.slice(1));
      else { const value = line.startsWith(" ") ? line.slice(1) : line; before.push(value); after.push(value); }
    });
    return { before: before.join("\n"), after: after.join("\n") };
  }

  const diagnostics = {
    open(section = "diagnosticConsole") {
      const backdrop = ui.byKey("diagnosticsBackdrop");
      if (!backdrop) return;
      backdrop.hidden = false;
      document.body.classList.add("diagnostics-open");
      diagnostics.activate(section);
    },

    close() {
      const backdrop = ui.byKey("diagnosticsBackdrop");
      if (!backdrop) return;
      backdrop.hidden = true;
      document.body.classList.remove("diagnostics-open");
    },

    async activate(sectionId) {
      document.querySelectorAll(".diagnostic-nav-button").forEach((button) => {
        button.classList.toggle("active", button.dataset.diagnostic === sectionId);
      });
      document.querySelectorAll(".diagnostic-section").forEach((section) => {
        const active = section.id === sectionId;
        section.classList.toggle("active", active);
        section.hidden = !active;
      });
      ui.byKey("diagnosticsDrawer")?.classList.toggle("patch-review-mode", sectionId === "diagnosticPatch");
      await diagnostics.load(sectionId);
    },

    async load(sectionId) {
      const runId = state.activeRunId;
      if (!runId || loaded.has(`${runId}:${sectionId}`)) return;
      try {
        if (sectionId === "diagnosticConsole") {
          const data = await api.request(`/api/workflow-runs/${runId}/console`);
          ui.byKey("diagnosticConsoleContent").innerHTML = diagnostics.renderConsole(data);
        } else if (sectionId === "diagnosticArtifacts") {
          const records = await api.request(`/api/workflow-runs/${runId}/artifacts?view=all`);
          ctx.features.artifacts.render(records || []);
        } else if (sectionId === "diagnosticPatch") {
          const patch = await api.request(`/api/workflow-runs/${runId}/patch`);
          currentPatch = patch;
          selectedPatchFiles = new Set(patch.changed_files || []);
          ui.byKey("diagnosticPatchContent").innerHTML = diagnostics.renderPatch(patch);
          diagnostics.bindPatchReview();
        } else if (sectionId === "diagnosticRepair") {
          const policy = await api.request(`/api/workflow-runs/${runId}/repair-policy`);
          ui.byKey("diagnosticRepairContent").innerHTML = diagnostics.renderRepair(policy);
        } else if (sectionId === "diagnosticHealth") {
          const [setup, analytics, store, benchmarks, version] = await Promise.all([
            api.request("/api/setup/status"),
            api.request("/api/analytics/summary"),
            api.request("/api/maintenance/store/status"),
            api.request("/api/benchmarks/summary"),
            api.request("/api/productization/version"),
          ]);
          ui.byKey("diagnosticHealthContent").innerHTML = diagnostics.renderHealth(setup, analytics, store, benchmarks, version);
        }
        loaded.add(`${runId}:${sectionId}`);
      } catch (err) {
        const target = {
          diagnosticConsole: ui.byKey("diagnosticConsoleContent"),
          diagnosticPatch: ui.byKey("diagnosticPatchContent"),
          diagnosticRepair: ui.byKey("diagnosticRepairContent"),
          diagnosticHealth: ui.byKey("diagnosticHealthContent"),
        }[sectionId];
        if (target) target.innerHTML = ui.emptyState("無法載入", err.message, "error");
        ctx.features.console.append("logs", `Diagnostics failed: ${err.message}`);
      }
    },

    reset(runId = null) {
      if (!runId) loaded.clear();
      else [...loaded].filter((key) => key.startsWith(`${runId}:`)).forEach((key) => loaded.delete(key));
    },

    renderConsole(data) {
      const summary = data.summary || {};
      return `
        <div class="diagnostic-summary-grid">
          <div><span>Status</span><strong>${ui.escapeHtml(data.status || "-")}</strong></div>
          <div><span>Steps</span><strong>${summary.steps_passed || 0} / ${summary.steps_total || 0}</strong></div>
          <div><span>Retries</span><strong>${summary.retry_total || 0}</strong></div>
          <div><span>Duration</span><strong>${Math.round(data.duration_sec || 0)}s</strong></div>
        </div>
        <details open><summary>Timeline</summary><pre>${ui.escapeHtml(safeJson((data.timeline || []).slice(-50)))}</pre></details>
        <details><summary>Step diagnostics</summary><pre>${ui.escapeHtml(safeJson(data.steps || []))}</pre></details>`;
    },

    renderPatch(patch) {
      const diffFiles = patch.diff?.files || [];
      const files = (patch.changed_files || patch.files || diffFiles.map((item) => item.path) || []).map((item) => typeof item === "string" ? item : item.path).filter(Boolean);
      const first = files[0] || null;
      const approval = patch.approval || {};
      const approved = !approval.required || approval.state === "approved";
      const canApply = ["review", "dry_run"].includes(patch.mode) && patch.status !== "applied" && approved;
      return `
        <div class="diagnostic-summary-grid"><div><span>Mode</span><strong>${ui.escapeHtml(patch.mode || "auto_apply")}</strong></div><div><span>Status</span><strong>${ui.escapeHtml(patch.status || "preview")}</strong></div><div><span>Files</span><strong>${files.length}</strong></div><div><span>Approval</span><strong>${ui.escapeHtml(approval.state || "not_required")}</strong></div></div>
        ${approval.required && approval.state !== "approved" ? `<div class="patch-approval-callout"><div><strong>套用前需要核准</strong><span>先檢查檔案差異；核准後才會啟用「套用所選檔案」。</span></div><button class="mini-button primary-action" data-approve-patch="1" type="button">核准此 Patch</button></div>` : ""}
        <div class="patch-review-layout">
          <div class="patch-file-column">
            <div class="patch-file-toolbar"><input data-patch-search type="search" placeholder="搜尋檔案…" aria-label="搜尋 Patch 檔案" /><button class="mini-button" data-patch-select="all" type="button">全選</button><button class="mini-button" data-patch-select="none" type="button">清除</button></div>
            <div class="patch-file-list">${files.map((file, index) => { const meta = (patch.diff?.files || []).find((item) => item.path === file) || {}; const status = meta.status || "modified"; return `<label class="patch-file-option ${index === 0 ? "active" : ""}" data-patch-file="${ui.escapeHtml(file)}" data-patch-status="${ui.escapeHtml(status)}"><input type="checkbox" ${selectedPatchFiles.has(file) ? "checked" : ""} /><span><strong>${ui.escapeHtml(file)}</strong><small>${ui.escapeHtml(status)} · +${Number(meta.added ?? meta.added_lines ?? 0)} / -${Number(meta.removed ?? meta.deleted_lines ?? 0)}</small></span></label>`; }).join("") || ui.emptyState("No changes", "This run has no text file changes.")}</div>
          </div>
          <div class="patch-preview-pane patch-view-${patchView}" data-patch-preview>${first ? diagnostics.renderPatchPreview(first) : `<pre>No file selected.</pre>`}</div>
        </div>
        ${canApply ? "" : `<div class="ui-empty-state"><strong>不需要套用</strong><span>此 Run 直接修改正式 Project Path；Patch 僅供閱讀。</span></div>`}`;
    },

    renderPatchPreview(path) {
      const chunk = patchChunkFor(path);
      if (patchView === "unified") return `<pre>${ui.escapeHtml(chunk)}</pre>`;
      const pair = splitPatch(chunk);
      return `<div class="patch-split"><section><header>Before</header><pre>${ui.escapeHtml(pair.before || "(new file)")}</pre></section><section><header>After</header><pre>${ui.escapeHtml(pair.after || "(deleted)")}</pre></section></div>`;
    },

    bindPatchReview() {
      const root = ui.byKey("diagnosticPatchContent");
      if (!root) return;
      const updateSummary = () => {
        const target = ui.byKey("patchSelectionSummary");
        if (target) target.textContent = `已選 ${selectedPatchFiles.size} / ${(currentPatch?.changed_files || []).length} 個檔案`;
        const apply = ui.byKey("applyDiagnosticPatch");
        if (apply) apply.disabled = !selectedPatchFiles.size || !["review", "dry_run"].includes(currentPatch?.mode) || currentPatch?.status === "applied";
      };
      root.querySelector("[data-approve-patch]")?.addEventListener("click", async () => {
        try {
          await api.request(`/api/workflow-runs/${state.activeRunId}/actions`, { method: "POST", body: JSON.stringify({ action: "approve", reason: "Patch reviewed in diagnostics." }) });
          loaded.delete(`${state.activeRunId}:diagnosticPatch`);
          await diagnostics.load("diagnosticPatch");
        } catch (err) {
          ctx.features.console.append("logs", `Patch approval failed: ${err.message}`);
        }
      });
      const patchRows = [...root.querySelectorAll("[data-patch-file]")];
      root.querySelector("[data-patch-search]")?.addEventListener("input", (event) => {
        const query = String(event.target.value || "").trim().toLowerCase();
        patchRows.forEach((row) => { row.hidden = Boolean(query) && !String(row.dataset.patchFile || "").toLowerCase().includes(query); });
      });
      root.querySelectorAll("[data-patch-select]").forEach((button) => button.addEventListener("click", () => {
        const checked = button.dataset.patchSelect === "all";
        patchRows.filter((row) => !row.hidden).forEach((row) => {
          const input = row.querySelector("input");
          if (input) input.checked = checked;
          const path = row.dataset.patchFile;
          if (checked) selectedPatchFiles.add(path); else selectedPatchFiles.delete(path);
        });
        updateSummary();
      }));
      patchRows.forEach((row) => {
        const path = row.dataset.patchFile;
        row.addEventListener("click", (event) => {
          if (event.target.matches('input')) return;
          root.querySelectorAll("[data-patch-file]").forEach((item) => item.classList.toggle("active", item === row));
          const preview = root.querySelector("[data-patch-preview]");
          if (preview) preview.innerHTML = diagnostics.renderPatchPreview(path);
        });
        row.querySelector("input")?.addEventListener("change", (event) => {
          if (event.target.checked) selectedPatchFiles.add(path); else selectedPatchFiles.delete(path);
          updateSummary();
        });
      });
      document.querySelectorAll("[data-patch-view]").forEach((button) => {
        button.onclick = () => {
          patchView = button.dataset.patchView || "split";
          document.querySelectorAll("[data-patch-view]").forEach((item) => item.classList.toggle("active", item === button));
          const active = root.querySelector("[data-patch-file].active")?.dataset.patchFile || (currentPatch?.changed_files || [])[0];
          const preview = root.querySelector("[data-patch-preview]");
          if (preview) {
            preview.classList.toggle("patch-view-unified", patchView === "unified");
            preview.classList.toggle("patch-view-split", patchView === "split");
          }
          if (preview && active) preview.innerHTML = diagnostics.renderPatchPreview(active);
        };
      });
      updateSummary();
    },

    async applySelectedPatch() {
      if (!state.activeRunId || !selectedPatchFiles.size) return;
      await ctx.features.runs.applyRunPatch(null, [...selectedPatchFiles]);
      diagnostics.reset(state.activeRunId);
    },


    renderRepair(policy) {
      const policies = policy.policies || [];
      if (!policies.length) return ui.emptyState("目前不需要 Repair", "沒有可分類的失敗或修復策略。");
      return `<div class="repair-policy-list">${policies.map((item) => `<article><strong>${ui.escapeHtml(item.title || item.code || "Repair")}</strong><p>${ui.escapeHtml(item.description || "")}</p><small>${ui.escapeHtml(item.repair_prompt_hint || item.recommended_action || "")}</small></article>`).join("")}</div>`;
    },

    renderHealth(setup, analytics, store, benchmarks = {}, version = {}) {
      const failureRows = (analytics.failure_distribution || []).slice(0, 6);
      return `
        <div class="diagnostic-summary-grid">
          <div><span>環境</span><strong>${setup.ready ? "READY" : "CHECK"}</strong></div>
          <div><span>成功率</span><strong>${analytics.success_rate ?? "-"}%</strong></div>
          <div><span>平均 Retry</span><strong>${analytics.avg_retry_count ?? 0}</strong></div>
          <div><span>資料庫</span><strong>${ui.escapeHtml(store.backend || "-")}</strong></div>
        </div>
        <details open><summary>環境檢查</summary><pre>${ui.escapeHtml(safeJson({ checks: setup.checks, project: setup.project, agents: setup.agents, model: setup.model, recommendations: setup.recommendations }))}</pre></details>
        <details><summary>Workflow 指標</summary><pre>${ui.escapeHtml(safeJson({ workflow_comparison: analytics.workflow_comparison, slowest_steps: analytics.slowest_steps, failures: failureRows }))}</pre></details>
        <details><summary>Regression Benchmark</summary><pre>${ui.escapeHtml(safeJson(benchmarks))}</pre></details>
        <details><summary>版本與 SQLite Projection</summary><pre>${ui.escapeHtml(safeJson({ version, store }))}</pre></details>`;
    },

    async compactArtifacts() {
      if (!state.activeRunId) return;
      try {
        const result = await api.request(`/api/workflow-runs/${state.activeRunId}/artifacts/compact`, { method: "POST", body: "{}" });
        ctx.features.console.append("logs", `Diagnostics compacted: ${result.file_count || 0} file(s), ${result.size_bytes || 0} bytes.`);
        diagnostics.reset(state.activeRunId);
        await diagnostics.activate("diagnosticArtifacts");
      } catch (err) {
        ctx.features.console.append("logs", `Artifact compaction failed: ${err.message}`);
      }
    },

    async downloadDebugBundle() {
      if (!state.activeRunId) return;
      try {
        const payload = await api.request(`/api/workflow-runs/${state.activeRunId}/debug-bundle`);
        const blob = new Blob([safeJson(payload)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = url;
        anchor.download = `aiwf-debug-${state.activeRunId}.json`;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(url);
      } catch (err) {
        ctx.features.console.append("logs", `Debug bundle failed: ${err.message}`);
      }
    },
  };

  return diagnostics;
}
