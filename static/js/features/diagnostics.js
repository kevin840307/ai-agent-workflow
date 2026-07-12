function safeJson(value) {
  try { return JSON.stringify(value, null, 2); } catch (_err) { return String(value ?? ""); }
}

export function createDiagnostics(ctx) {
  const { api, state, ui } = ctx;
  const loaded = new Set();
  let currentRepairPolicy = null;
  const diagnosticsSizeKey = "aiwf.ui.diagnosticsMaximized";



  const diagnostics = {
    open(section = "diagnosticConsole") {
      const backdrop = ui.byKey("diagnosticsBackdrop");
      if (!backdrop) return;
      backdrop.hidden = false;
      document.body.classList.add("diagnostics-open");
      diagnostics.setMaximized(window.localStorage.getItem(diagnosticsSizeKey) === "true", { persist: false });
      diagnostics.activate(section);
    },

    close() {
      const backdrop = ui.byKey("diagnosticsBackdrop");
      if (!backdrop) return;
      backdrop.hidden = true;
      document.body.classList.remove("diagnostics-open");
    },

    setMaximized(enabled, { persist = true } = {}) {
      const drawer = ui.byKey("diagnosticsDrawer");
      const button = ui.byKey("toggleDiagnosticsSize");
      if (!drawer) return;
      drawer.classList.toggle("maximized", Boolean(enabled));
      if (button) {
        button.setAttribute("aria-pressed", String(Boolean(enabled)));
        button.textContent = enabled ? "還原" : "放大";
        button.title = enabled ? "還原技術診斷大小" : "放大技術診斷";
      }
      if (persist) window.localStorage.setItem(diagnosticsSizeKey, String(Boolean(enabled)));
    },

    toggleSize() {
      const drawer = ui.byKey("diagnosticsDrawer");
      diagnostics.setMaximized(!drawer?.classList.contains("maximized"));
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
      ui.byKey("diagnosticsDrawer")?.classList.remove("patch-review-mode");
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
        } else if (sectionId === "diagnosticRepair") {
          const policy = await api.request(`/api/workflow-runs/${runId}/repair-policy`);
          currentRepairPolicy = policy;
          ui.byKey("diagnosticRepairContent").innerHTML = diagnostics.renderRepair(policy);
          diagnostics.bindRepair();
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



    renderRepair(policy) {
      const policies = policy.policies || [];
      if (!policies.length) return ui.emptyState("目前不需要 Repair", "沒有可分類的失敗或修復策略。");
      const first = policies[0];
      return `
        <div class="repair-policy-layout">
          <nav class="repair-policy-list" aria-label="修復策略清單">
            ${policies.map((item, index) => `<button class="repair-policy-item ${index === 0 ? "active" : ""}" data-repair-index="${index}" type="button"><strong>${ui.escapeHtml(item.title || item.code || "Repair")}</strong><span>${ui.escapeHtml(item.code || item.failure_class || "自動修復")}</span></button>`).join("")}
          </nav>
          <section class="repair-policy-detail" data-repair-detail>${diagnostics.renderRepairDetail(first)}</section>
        </div>`;
    },

    renderRepairDetail(item = {}) {
      const actions = Array.isArray(item.actions) ? item.actions : [];
      const evidence = item.evidence || item.context || null;
      return `
        <header><div><span class="eyebrow">REPAIR STRATEGY</span><h3>${ui.escapeHtml(item.title || item.code || "Repair")}</h3></div><span class="badge ${ui.escapeHtml(item.severity || "running")}">${ui.escapeHtml(item.code || item.failure_class || "AUTO")}</span></header>
        <div class="repair-detail-scroll">
          <section><strong>問題</strong><p>${ui.escapeHtml(item.description || "沒有額外說明。")}</p></section>
          <section><strong>建議動作</strong><p>${ui.escapeHtml(item.recommended_action || item.repair_prompt_hint || "平台會依 Recovery Policy 自動處理。")}</p></section>
          ${item.repair_prompt_hint ? `<section><strong>Agent 修復提示</strong><pre>${ui.escapeHtml(item.repair_prompt_hint)}</pre></section>` : ""}
          ${actions.length ? `<section><strong>執行順序</strong><ol>${actions.map((action) => `<li>${ui.escapeHtml(typeof action === "string" ? action : safeJson(action))}</li>`).join("")}</ol></section>` : ""}
          ${evidence ? `<details><summary>Evidence</summary><pre>${ui.escapeHtml(safeJson(evidence))}</pre></details>` : ""}
        </div>`;
    },

    bindRepair() {
      const root = ui.byKey("diagnosticRepairContent");
      const policies = currentRepairPolicy?.policies || [];
      if (!root || !policies.length) return;
      root.querySelectorAll("[data-repair-index]").forEach((button) => {
        button.addEventListener("click", () => {
          const index = Number(button.dataset.repairIndex || 0);
          root.querySelectorAll("[data-repair-index]").forEach((item) => item.classList.toggle("active", item === button));
          const detail = root.querySelector("[data-repair-detail]");
          if (detail) detail.innerHTML = diagnostics.renderRepairDetail(policies[index] || policies[0]);
        });
      });
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
        state.lastArtifactCompaction = result;
        ctx.features.console.append("logs", `Diagnostics archived: ${result.file_count || 0} file(s), ${result.size_bytes || 0} bytes; originals ${result.pruned ? "pruned by policy" : "retained"}.`);
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
