import { LocalStore, StorageKeys } from "../core/storage.js?v=20260712-ui-v22";
import { acceptRunSnapshot } from "../core/state.js?v=20260712-ui-v22";
export function createRuns(ctx) {
  const { api, state, ui } = ctx;
  let latestResultRun = null;
  let lastOpenedResultKey = "";
  let terminateInFlight = false;
  let currentRun = null;

  const normalizedFiles = (overview) => {
    const seen = new Map();
    for (const raw of (overview?.changes?.files || [])) {
      const path = String(raw?.path || "").replaceAll("\\", "/").replace(/^\.\//, "").split("/").filter((part) => part && part !== ".").join("/").trim();
      if (!path) continue;
      const key = path.toLocaleLowerCase();
      if (!seen.has(key)) { seen.set(key, { ...raw, path }); continue; }
      const current = seen.get(key);
      current.added = Math.max(Number(current.added ?? current.added_lines ?? 0), Number(raw.added ?? raw.added_lines ?? 0));
      current.removed = Math.max(Number(current.removed ?? current.deleted_lines ?? 0), Number(raw.removed ?? raw.deleted_lines ?? 0));
    }
    return [...seen.values()];
  };

  const patchFor = (diff, path) => {
    const fileDiff = (diff?.files || []).find((item) => item.path === path);
    if (fileDiff?.patch) return fileDiff.patch;
    const chunks = String(diff?.patch || "").split(/(?=--- a\/)/g);
    return chunks.find((chunk) => chunk.includes(`+++ b/${path}`) || chunk.startsWith(`--- a/${path}`)) || "";
  };

  const statusLabel = (status) => ({ added: "新增", new: "新增", modified: "修改", changed: "修改", deleted: "刪除", removed: "刪除" }[status] || "變更");

  const renderDiffRows = (chunk) => {
    if (!chunk) return `<div class="diff-empty"><strong>沒有文字差異</strong><span>可能是二進位檔、重新命名，或尚未建立 Patch。</span></div>`;
    let oldLine = 0; let newLine = 0; let rendered = 0;
    const rows = [];
    for (const raw of String(chunk).split("\n")) {
      if (raw.startsWith("---") || raw.startsWith("+++")) continue;
      const hunk = raw.match(/^@@\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@(.*)$/);
      if (hunk) {
        oldLine = Number(hunk[1]); newLine = Number(hunk[2]);
        rows.push(`<div class="diff-code-row hunk"><span></span><span></span><code>${ui.escapeHtml(`@@ ${String(hunk[3] || "").trim() || "變更區段"}`)}</code></div>`);
        continue;
      }
      if (rendered >= 1500) { rows.push(`<div class="diff-code-row truncated"><span></span><span></span><code>差異過長，已截斷顯示。</code></div>`); break; }
      let kind = "context"; let oldNo = oldLine; let newNo = newLine; let content = raw;
      if (raw.startsWith("+")) { kind = "added"; oldNo = ""; content = raw.slice(1); newLine += 1; }
      else if (raw.startsWith("-")) { kind = "removed"; newNo = ""; content = raw.slice(1); oldLine += 1; }
      else { content = raw.startsWith(" ") ? raw.slice(1) : raw; oldLine += 1; newLine += 1; }
      rows.push(`<div class="diff-code-row ${kind}"><span>${oldNo}</span><span>${newNo}</span><code>${ui.escapeHtml(content || " ")}</code></div>`);
      rendered += 1;
    }
    return rows.join("");
  };

  const runs = {
    clearPanels() {
      ui.byKey("currentStep").textContent = "Idle";
      ui.byKey("progressText").textContent = "0 / 0";
      ui.byKey("resultText").textContent = "Waiting";
      ctx.features.interactions.hide();
      runs.renderStepSkeleton([]);
      ui.byKey("qwenLive").textContent = "No agent output yet.";
      ui.byKey("logs").textContent = "";
      ui.byKey("artifacts").innerHTML = "";
      ui.byKey("artifactContent").textContent = "";
      if (ui.byKey("stepDetails")) ui.byKey("stepDetails").innerHTML = "";
      if (ui.byKey("runDetail")) ui.byKey("runDetail").innerHTML = ui.emptyState("No run selected", "Start or select a workflow run to inspect details.");
      runs.renderProductFlow({}, null);
      if (ui.byKey("currentActionCard")) ui.byKey("currentActionCard").innerHTML = `<span class="current-action-phase">準備中</span><h2>尚未開始執行</h2><p>選擇專案、輸入需求並開始 Workflow。</p><small>完成後會自動整理變更與驗證結果。</small>`;
      if (ui.byKey("overviewMetrics")) ui.byKey("overviewMetrics").innerHTML = "";
      if (ui.byKey("runTimeline")) ui.byKey("runTimeline").innerHTML = "";
      if (ui.byKey("runTimelineCount")) ui.byKey("runTimelineCount").textContent = "0 events";
      if (ui.byKey("overviewChangeCard")) ui.byKey("overviewChangeCard").innerHTML = ui.emptyState("尚無變更", "Workflow 開始修改專案後會顯示在這裡。");
      if (ui.byKey("validationSummary")) ui.byKey("validationSummary").innerHTML = "";
      if (ui.byKey("validationList")) ui.byKey("validationList").innerHTML = ui.emptyState("尚無驗證", "測試與驗證執行後會顯示結果。");
      state.activeRunOverview = null;
      runs.closeDiffDialog();
      latestResultRun = null;
      if (ui.byKey("openRunResult")) ui.byKey("openRunResult").hidden = true;
      if (ui.byKey("runResultPanel")) {
        ui.byKey("runResultPanel").hidden = true;
        ui.byKey("runResultPanel").innerHTML = "";
        document.body.classList.remove("run-result-modal-open");
      }
    },

    renderStepSkeleton(stepTitles = []) {
      const steps = ui.byKey("steps");
      steps.innerHTML = "";
      if (!stepTitles.length) {
        steps.innerHTML = `<div class="message system">No workflow run loaded.</div>`;
        return;
      }
      stepTitles.forEach((title) => {
        const row = document.createElement("div");
        row.className = "step";
        row.innerHTML = `
          <div class="step-title"><span>${title}</span></div>
          <div class="step-message"></div>
          <div class="step-actions"><span class="badge pending">pending</span></div>
        `;
        steps.appendChild(row);
      });
    },

    render(run) {
      if (!acceptRunSnapshot(state, run)) return;
      currentRun = run;
      state.activeRunId = run.id;
      state.activeRunStatus = run.status;
      state.activeRunWorkflowId = run.workflow_id || state.activeRunWorkflowId || state.selectedWorkflowId || null;
      ctx.features.layout.applyRunStatus(run.status);
      ctx.features.diagnostics?.reset(run.id);

      const session = state.sessions.find((item) => item.id === run.session_id);
      const steps = run.steps || [];
      const passed = steps.filter((step) => step.status === "passed").length;
      const running = steps.find((step) => step.status === "running");
      const failed = steps.find((step) => step.status === "failed" || step.status === "waiting_input");

      const workflowName = run.workflow_name ? ` - ${run.workflow_name}` : "";
      ui.byKey("runMeta").textContent = `${ui.shortPath(run.original_project_path || run.project_path || session?.project_path || "")}${workflowName}`;
      ui.byKey("runStatusMeta").textContent = String(run.status || "waiting").toUpperCase();
      ui.byKey("currentStep").textContent = running?.title || failed?.title || (run.status === "done" ? "Complete" : "Idle");
      ui.byKey("progressText").textContent = `${passed} / ${steps.length}`;
      ui.byKey("resultText").textContent = String(run.status || "waiting").toUpperCase();
      if (ui.byKey("overviewProgressLabel")) ui.byKey("overviewProgressLabel").textContent = `${passed} / ${steps.length}`;
      ui.byKey("retryRun").disabled = ["queued", "running"].includes(run.status);
      ui.byKey("addGuidance").disabled = false;
      ctx.features.composer.updatePrimaryAction(run);

      const selectedStep = steps.find((step) => step.key === state.selectedStepKey)
        || steps.find((step) => step.status === "running" || step.status === "failed" || step.status === "waiting_input")
        || steps.find((step) => step.status === "passed")
        || steps[0];
      state.selectedStepKey = selectedStep?.key || null;
      runs.renderSteps(run);
      runs.renderStepDetails(run, selectedStep);
      runs.renderResultPanel(run);
      runs.renderRunDetail(run);
      runs.loadOverview(run).catch((err) => ctx.features.console.append("logs", `Overview failed: ${err.message}`));
      ctx.features.interactions.render(run);
      ctx.features.workflows?.renderPreview?.();
    },

    async loadOverview(run) {
      if (!run?.id) return;
      const [overview, diff] = await Promise.all([
        api.request(`/api/workflow-runs/${run.id}/overview`),
        api.request(`/api/workflow-runs/${run.id}/diff`).catch(() => ({ files: [], patch: "" })),
      ]);
      if (state.activeRunId !== run.id) return;
      overview.diff = diff;
      state.activeRunOverview = overview;
      runs.renderOverview(overview, run);
      runs.renderChanges(overview);
      runs.renderValidation(overview);
      runs.renderRunDetail(run, overview);
    },

    renderOverview(overview, run) {
      runs.renderProductFlow(overview, run);
      const autopilot = overview.autopilot_state || null;
      const action = autopilot ? {
        title: ({ discovering: "正在理解專案", executing: "正在自動開發", finalizing: "正在完成最終驗證", verified: "變更已安全套用", completed: "任務完成" })[autopilot.state] || overview.current_action?.title,
        detail: autopilot.detail || overview.current_action?.detail,
        next: autopilot.state === "completed" ? "所有確定性完成條件皆已通過。" : "平台會自動繼續，不需要操作。",
      } : (overview.current_action || {});
      const retry = overview.retry_explanation || {};
      const card = ui.byKey("currentActionCard");
      if (card) {
        const retryHtml = Number(retry.attempt || 0) > 0
          ? `<div class="human-retry"><strong>第 ${Number(retry.attempt)} 次修復</strong><span>${ui.escapeHtml(retry.reason || "正在修復目前問題")}</span><small>${ui.escapeHtml(retry.strategy || "從最近有效狀態繼續")}</small></div>`
          : "";
        card.className = `current-action-card phase-${ui.escapeHtml(overview.phase || "queued")}`;
        const recovery = overview.recovery || null;
        const recoveryHtml = recovery ? `
          <div class="inline-recovery-notice" role="status">
            <span class="recovery-icon" aria-hidden="true">↻</span>
            <div><strong>服務已重新啟動，進度已保留</strong><span>可從最近的 Checkpoint 繼續，不需要重新執行已完成任務。</span></div>
            <button class="mini-button primary-action" data-inline-resume="1" type="button">繼續</button>
          </div>` : "";
        card.innerHTML = `
          ${recoveryHtml}
          <span class="current-action-phase">${ui.escapeHtml(String(overview.phase || "queued").replaceAll("_", " "))}</span>
          <h2>${ui.escapeHtml(action.title || "準備中")}</h2>
          <p>${ui.escapeHtml(action.detail || "系統正在準備目前步驟。")}</p>
          <small>${ui.escapeHtml(action.next || "完成後會整理結果。")}</small>
          ${retryHtml}`;
        card.querySelector("[data-inline-resume]")?.addEventListener("click", () => runs.handleOverviewAction("resume", run));
      }
      const summary = overview.summary || {};
      const metrics = ui.byKey("overviewMetrics");
      if (metrics) metrics.innerHTML = `
        <div><span>進度</span><strong>${overview.progress?.percent || 0}%</strong></div>
        <div><span>變更</span><strong>${summary.changed_file_count || 0} files</strong></div>
        <div><span>測試</span><strong>${summary.validation_passed ? "PASS" : (run.status === "done" ? "CHECK" : "PENDING")}</strong></div>
        <div><span>風險 / 品質</span><strong>${ui.escapeHtml(summary.risk || "low")} · ${summary.quality_score ?? "-"}</strong></div>`;
      if (ui.byKey("overviewProgressLabel")) ui.byKey("overviewProgressLabel").textContent = `${overview.progress?.completed || 0} / ${overview.progress?.total || 0}`;
      runs.renderTimeline(overview.timeline || []);
    },

    renderProductFlow(overview = {}, run = null) {
      const root = ui.byKey("productFlow");
      if (!root) return;
      const status = String(run?.status || "");
      const summary = overview.summary || {};
      const changed = Number(summary.changed_file_count || overview.changes?.files?.length || 0);
      const validationPassed = Boolean(summary.validation_passed);
      const terminal = ["done", "failed", "cancelled"].includes(status);
      const stages = {
        requirement: run ? "done" : "pending",
        progress: ["queued", "running", "waiting_input", "cancelling"].includes(status) ? "active" : (terminal ? "done" : "pending"),
        changes: changed > 0 ? "done" : (status === "done" ? "done" : "pending"),
        validation: validationPassed ? "done" : (status === "failed" ? "error" : "pending"),
        complete: status === "done" ? "done" : (["failed", "cancelled"].includes(status) ? "error" : "pending"),
      };
      root.querySelectorAll("[data-flow-stage]").forEach((item) => {
        const value = stages[item.dataset.flowStage] || "pending";
        item.classList.remove("pending", "active", "done", "error");
        item.classList.add(value);
        item.setAttribute("aria-current", value === "active" ? "step" : "false");
      });
    },

    renderTimeline(events) {
      const target = ui.byKey("runTimeline");
      const count = ui.byKey("runTimelineCount");
      if (!target) return;
      const rows = (events || []).slice(-30).reverse();
      if (count) count.textContent = `${rows.length} event${rows.length === 1 ? "" : "s"}`;
      if (!rows.length) {
        target.innerHTML = `<li class="timeline-empty">尚無執行事件。</li>`;
        return;
      }
      const formatTime = (value) => {
        if (!value) return "";
        try { return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }); } catch { return ""; }
      };
      target.innerHTML = rows.map((event) => `
        <li>
          <time>${ui.escapeHtml(formatTime(event.at || event.timestamp || event.created_at))}</time>
          <span class="timeline-dot status-${ui.escapeHtml(event.status || event.type || event.kind || "event")}"></span>
          <div><strong>${ui.escapeHtml(event.title || event.step_title || event.step_key || event.step || event.type || "Workflow")}</strong><p>${ui.escapeHtml(event.message || event.detail || event.reason || "")}</p></div>
        </li>`).join("");
    },

    renderChanges(overview) {
      const files = normalizedFiles(overview);
      const target = ui.byKey("overviewChangeCard");
      if (!target) return;
      const added = files.reduce((sum, file) => sum + Number(file.added ?? file.added_lines ?? 0), 0);
      const removed = files.reduce((sum, file) => sum + Number(file.removed ?? file.deleted_lines ?? 0), 0);
      const approval = overview.approval || {};
      if (!files.length) {
        target.innerHTML = ui.emptyState("尚無檔案變更", "Agent 產生實際 Project Diff 後會顯示在這裡。");
        return;
      }
      const validationRows = overview.validation || [];
      const required = validationRows.filter((row) => row.required !== false);
      const validationPassed = required.length > 0 && required.every((row) => ["passed", "passed_with_baseline"].includes(row.status) && row.executed !== false);
      target.innerHTML = `
        <div class="overview-change-summary">
          <div><span class="eyebrow">PROJECT CHANGES</span><strong>${files.length} 個檔案變更</strong><small><span class="added">+${added}</span> / <span class="removed">-${removed}</span> · ${ui.escapeHtml(approval.state || "not_required")}</small></div>
          <div class="overview-change-evidence"><span class="${validationPassed ? "passed" : "pending"}">${validationPassed ? "✓ 驗證通過" : "! 等待必要驗證"}</span><button class="mini-button primary-action" data-open-patch-review type="button">查看並審核變更</button></div>
        </div>`;
      target.querySelector("[data-open-patch-review]")?.addEventListener("click", () => runs.openDiffDialog());
    },

    openDiffDialog(path = null) {
      return ctx.features.patchReview?.open(path, state.activeRunOverview);
    },

    closeDiffDialog() {
      return ctx.features.patchReview?.close();
    },


    renderValidation(overview) {
      const rows = overview.validation || [];
      const passed = rows.filter((item) => ["passed", "passed_with_baseline"].includes(item.status)).length;
      const failed = rows.filter((item) => item.status === "failed").length;
      const skipped = rows.filter((item) => ["skipped", "unavailable"].includes(item.status)).length;
      const pending = rows.length - passed - failed - skipped;
      const summary = ui.byKey("validationSummary");
      if (summary) summary.innerHTML = `
        <div><span>PASS</span><strong>${passed}</strong></div>
        <div><span>FAILED</span><strong>${failed}</strong></div>
        <div><span>SKIPPED</span><strong>${skipped}</strong></div>
        <div><span>PENDING</span><strong>${pending}</strong></div>`;
      const list = ui.byKey("validationList");
      if (!list) return;
      if (!rows.length) { list.innerHTML = ui.emptyState("尚無驗證結果", "執行測試、Validation 或 Review 後會顯示證據。"); return; }
      list.innerHTML = rows.map((item) => {
        const artifacts = item.artifacts || [];
        const status = item.status || "pending";
        const duration = item.duration_sec === null || item.duration_sec === undefined ? "-" : `${Number(item.duration_sec).toFixed(1)}s`;
        const executed = item.executed === false ? "未執行" : item.exit_code === null || item.exit_code === undefined ? "已執行" : `Exit ${item.exit_code}`;
        const summaryText = item.error || item.summary || (["passed", "passed_with_baseline"].includes(status) ? "已取得可重現的通過證據。" : "等待執行。");
        return `<article class="validation-row status-${ui.escapeHtml(status)}">
          <span class="validation-status">${ui.escapeHtml(String(status).toUpperCase())}</span>
          <div>
            <h3>${ui.escapeHtml(item.label || item.key || "Validation")}</h3>
            <p>${ui.escapeHtml(summaryText)}</p>
            <div class="validation-evidence-grid"><span>${item.required === false ? "Optional" : "Required"}</span><span class="${item.blocks_apply ? "validation-blocks-apply" : ""}">${item.blocks_apply ? "Blocks Apply" : "Does not block"}</span><span>${ui.escapeHtml(executed)}</span><span>${duration}</span>${item.retry_count ? `<span>Retry ${item.retry_count}</span>` : ""}${item.baseline ? `<span>Baseline Evidence</span>` : ""}</div>
            ${item.command ? `<code class="validation-command">${ui.escapeHtml(Array.isArray(item.command) ? item.command.join(" ") : item.command)}</code>` : ""}
            <div class="validation-row-actions">${artifacts.map((artifact) => `<button class="mini-button" data-validation-artifact="${ui.escapeHtml(artifact.id)}" type="button">查看 ${ui.escapeHtml(artifact.display_name || artifact.role || "Evidence")}</button>`).join("")}<button class="mini-button" data-validation-step="${ui.escapeHtml(item.key || "")}" type="button">查看相關 Step</button></div>
          </div>
          <small>${ui.escapeHtml(item.category || "validation")}</small>
        </article>`;
      }).join("");
      list.querySelectorAll("[data-validation-artifact]").forEach((button) => button.addEventListener("click", () => ctx.features.artifacts.open(button.dataset.validationArtifact)));
      list.querySelectorAll("[data-validation-step]").forEach((button) => button.addEventListener("click", () => {
        const step = currentRun?.steps?.find((row) => row.key === button.dataset.validationStep);
        if (step) runs.openStepDetailModal(currentRun, step);
      }));
    },


    renderSteps(run) {
      const steps = ui.byKey("steps");
      steps.innerHTML = "";
      run.steps.forEach((step) => {
        const row = document.createElement("div");
        row.className = `step${state.selectedStepKey === step.key ? " selected" : ""}`;
        const retry = step.retry_count ? `<span class="retry-count">retry ${step.retry_count}</span>` : "";
        const error = step.error ? `<small>${ui.escapeHtml(step.error)}</small>` : "";
        row.innerHTML = `
          <div class="step-title"><span>${ui.escapeHtml(step.title)}</span>${retry}</div>
          <div class="step-message">${error}</div>
          <div class="step-actions">
            <span class="badge ${step.status}">${step.status}</span>
            <button class="step-more-button detail-step" data-step-key="${ui.escapeHtml(step.key)}" title="Step details" aria-label="Step details">
              <span aria-hidden="true"></span>
            </button>
          </div>
        `;
        row.onclick = (event) => {
          if (event.target.closest("button")) return;
          runs.selectStep(run, step.key);
        };
        row.querySelector(".detail-step").onclick = (event) => {
          event.stopPropagation();
          runs.openStepDetailModal(run, step);
        };
        steps.appendChild(row);
      });
    },

    selectStep(run, stepKey) {
      const step = run.steps.find((item) => item.key === stepKey);
      if (!step) return;
      state.selectedStepKey = step.key;
      document.querySelectorAll(".step").forEach((row) => row.classList.remove("selected"));
      const rows = [...document.querySelectorAll(".step")];
      const index = run.steps.findIndex((item) => item.key === step.key);
      if (rows[index]) rows[index].classList.add("selected");
      runs.renderStepDetails(run, step);
    },

    renderStepDetails(run, step) {
      const target = ui.byKey("stepDetails");
      if (!target) return;
      if (!step) { target.innerHTML = `<div class="step-detail-empty">選擇步驟查看目前結果。</div>`; return; }
      const events = (step.events || []).slice(-3).reverse();
      const changed = Array.isArray(step.changed_files) ? step.changed_files : [];
      target.innerHTML = `
        <article class="step-detail-card simplified-step-detail">
          <div class="step-detail-head"><div><span class="step-detail-eyebrow">${ui.escapeHtml(step.key || "step")}</span><h3>${ui.escapeHtml(step.title || step.key || "Step")}</h3></div><span class="badge ${ui.escapeHtml(step.status || "pending")}">${ui.escapeHtml(step.status || "pending")}</span></div>
          ${step.error ? `<div class="step-detail-error"><strong>${ui.escapeHtml(step.error_code || "需要處理")}</strong><span>${ui.escapeHtml(step.error)}</span></div>` : ""}
          <div class="simple-step-facts"><div><span>Retry</span><strong>${Number(step.retry_count || 0)}</strong></div><div><span>Changed</span><strong>${changed.length}</strong></div><div><span>Events</span><strong>${(step.events || []).length}</strong></div></div>
          ${changed.length ? `<div class="step-detail-section"><strong>本步驟變更</strong><div class="step-detail-files">${changed.slice(0, 8).map((file) => `<span class="step-detail-file passive">${ui.escapeHtml(file)}</span>`).join("")}</div></div>` : ""}
          <div class="step-detail-section"><strong>最近狀態</strong>${events.length ? `<ol class="step-detail-events">${events.map((event) => `<li><span class="event-kind">${ui.escapeHtml(event.kind || event.type || "event")}</span><span class="event-message">${ui.escapeHtml(event.message || "")}</span></li>`).join("")}</ol>` : `<p>尚無事件。</p>`}</div>
          <div class="step-detail-actions"><button class="mini-button detail-step" type="button">完整步驟資訊</button>${step.status === "failed" ? `<button class="mini-button primary-action step-detail-retry" type="button">重試此步驟</button>` : ""}</div>
        </article>`;
      target.querySelector(".detail-step")?.addEventListener("click", () => runs.openStepDetailModal(run, step));
      target.querySelector(".step-detail-retry")?.addEventListener("click", () => runs.retry(step.key));
    },

    renderResultPanel(run) {
      const panel = ui.byKey("runResultPanel");
      const openButton = ui.byKey("openRunResult");
      if (!panel) return;
      const terminal = ["done", "failed", "cancelled", "waiting_input"].includes(run.status);
      const restartRecovery = Boolean(run.restart_recoverable)
        || run.error_code === "INTERRUPTED"
        || String(run.error || "").includes("Workflow server restarted");
      if (!terminal || restartRecovery) {
        latestResultRun = null;
        panel.hidden = true;
        panel.innerHTML = "";
        document.body.classList.remove("run-result-modal-open");
        if (openButton) openButton.hidden = true;
        return;
      }
      latestResultRun = run;
      if (openButton) openButton.hidden = false;
      const dismissedRun = LocalStore.getString(StorageKeys.resultDockDismissedRun, "");
      if (dismissedRun === run.id) {
        panel.hidden = true;
        panel.innerHTML = "";
        document.body.classList.remove("run-result-modal-open");
        return;
      }
      if (run.status === "cancelled") {
        panel.hidden = true;
        panel.innerHTML = "";
        document.body.classList.remove("run-result-modal-open");
        return;
      }
      runs.openResultModal(run, { automatic: true });
    },

    openResultModal(run = latestResultRun, { automatic = false } = {}) {
      const panel = ui.byKey("runResultPanel");
      if (!panel || !run) return;
      latestResultRun = run;
      const resultKey = `${run.id}:${run.status}:${run.updated_at || ""}`;
      if (automatic && resultKey === lastOpenedResultKey && !panel.hidden) return;
      lastOpenedResultKey = resultKey;
      const failed = (run.steps || []).find((step) => ["failed", "waiting_input", "cancelled"].includes(step.status));
      const passed = (run.steps || []).filter((step) => step.status === "passed").length;
      const retries = (run.steps || []).reduce((total, step) => total + Number(step.retry_count || 0), 0);
      const done = run.status === "done";
      const title = done ? "Workflow 已完成" : run.status === "waiting_input" ? "Workflow 等待處理" : "Workflow 未完成";
      const message = failed?.error || run.error || (done
        ? "結果已整理完成。你可以先查看驗證，再確認本次變更。"
        : "請查看失敗原因與建議動作；目前成果仍保留在 Run Center。"
      );
      panel.hidden = false;
      document.body.classList.add("run-result-modal-open");
      panel.innerHTML = `
        <article class="run-result-modal status-${ui.escapeHtml(run.status || "done")}" role="dialog" aria-modal="true" aria-labelledby="runResultTitle">
          <header class="run-result-modal-head">
            <span class="run-result-modal-icon" aria-hidden="true">${done ? "✓" : "!"}</span>
            <div><span class="eyebrow">RUN RESULT</span><h2 id="runResultTitle">${ui.escapeHtml(title)}</h2><p>${ui.escapeHtml(message)}</p></div>
            <button class="modal-close run-result-modal-close" type="button" aria-label="關閉 Workflow 結果">×</button>
          </header>
          <div class="run-result-modal-metrics">
            <div><span>Steps</span><strong>${passed} / ${(run.steps || []).length}</strong></div>
            <div><span>Retries</span><strong>${retries}</strong></div>
            <div><span>Status</span><strong>${ui.escapeHtml(String(run.status || "-").toUpperCase())}</strong></div>
          </div>
          ${failed ? `<div class="run-result-modal-error"><strong>${ui.escapeHtml(failed.error_code || run.error_code || "需要處理")}</strong><span>${ui.escapeHtml(failed.error || run.error || "請查看驗證與技術診斷。")}</span></div>` : ""}
          <footer class="run-result-modal-actions">
            <button class="mini-button" data-result-tab="overviewPanel" type="button">查看總覽</button>
            <button class="mini-button" data-result-patch="1" type="button">查看變更</button>
            <button class="mini-button primary-action" data-result-tab="validationPanel" type="button">查看驗證</button>
            ${done ? "" : `<button class="mini-button" data-result-diagnostics="diagnosticLogs" type="button">技術診斷</button>`}
          </footer>
        </article>`;
      const close = () => runs.closeResultModal({ remember: true });
      panel.querySelector(".run-result-modal-close")?.addEventListener("click", close);
      panel.querySelectorAll("[data-result-tab]").forEach((button) => button.addEventListener("click", () => {
        ctx.features.layout.activateTab(button.dataset.resultTab);
        runs.closeResultModal({ remember: true });
      }));
      panel.querySelector("[data-result-patch]")?.addEventListener("click", () => {
        runs.closeResultModal({ remember: true });
        runs.openDiffDialog();
      });
      panel.querySelector("[data-result-diagnostics]")?.addEventListener("click", () => {
        runs.closeResultModal({ remember: true });
        ctx.features.diagnostics.open("diagnosticLogs");
      });
      if (!automatic) LocalStore.setString(StorageKeys.resultDockDismissedRun, "");
      panel.querySelector(".run-result-modal-close")?.focus({ preventScroll: true });
    },

    closeResultModal({ remember = false } = {}) {
      const panel = ui.byKey("runResultPanel");
      if (!panel) return;
      if (remember && latestResultRun?.id) LocalStore.setString(StorageKeys.resultDockDismissedRun, latestResultRun.id);
      panel.hidden = true;
      panel.innerHTML = "";
      document.body.classList.remove("run-result-modal-open");
    },


    renderRunDetail(run, overview = state.activeRunOverview) {
      const target = ui.byKey("runDetail");
      if (!target) return;
      if (!run || !run.id) { target.innerHTML = ui.emptyState("No run selected", "Start or select a workflow run to inspect details."); return; }
      const summary = overview?.summary || {};
      const actions = overview?.recommended_actions || [];
      const error = overview?.error || {};
      if (overview?.restart_recoverable || overview?.recovery) {
        // The recovery action already lives in Current Action where users look
        // first. Do not repeat a large "Workflow needs attention" error card at
        // the bottom of the panel.
        target.hidden = true;
        target.innerHTML = "";
        return;
      }
      target.hidden = false;
      const title = run.status === "done" ? "Workflow 完成" : run.status === "failed" ? "Workflow 需要處理" : "Workflow 執行中";
      target.innerHTML = `
        <article class="run-detail-card user-run-summary status-${ui.escapeHtml(run.status || "queued")}">
          <div class="run-result-head"><div><span class="run-result-eyebrow">${ui.escapeHtml(String(run.status || "queued").toUpperCase())}</span><h2>${title}</h2><p>${ui.escapeHtml(error.message || (run.status === "done" ? "正式檔案、測試與驗證結果已整理完成。" : "系統會持續更新目前動作與下一步。"))}</p></div></div>
          <div class="run-result-grid"><div><span>Files</span><strong>${summary.changed_file_count ?? "-"}</strong></div><div><span>Tests</span><strong>${summary.validation_passed ? "PASS" : "-"}</strong></div><div><span>Retries</span><strong>${summary.retry_total ?? 0}</strong></div><div><span>Risk</span><strong>${ui.escapeHtml(summary.risk || "-")}</strong></div></div>
          <div class="run-result-actions user-actions">${actions.map((action) => `<button class="mini-button ${action.kind === "primary" ? "primary-action" : action.kind === "danger" ? "danger-action" : ""}" data-overview-action="${ui.escapeHtml(action.id)}" type="button">${ui.escapeHtml(action.label)}</button>`).join("")}</div>
        </article>`;
      target.querySelectorAll("[data-overview-action]").forEach((button) => button.addEventListener("click", () => runs.handleOverviewAction(button.dataset.overviewAction, run)));
    },

    async handleOverviewAction(action, run) {
      if (action === "diagnostics") return ctx.features.diagnostics.open();
      if (action === "view_changes") return runs.openDiffDialog();
      if (action === "run_again") return runs.replayRun();
      if (action === "open_project") {
        ctx.features.console.append("logs", `Project Path: ${run.original_project_path || run.project_path}`);
        return runs.openDiffDialog();
      }
      if (action === "answer") return ctx.features.interactions.render(run);
      if (["retry_current", "retry_fresh_session", "resume", "stop", "keep_changes", "approve", "reject"].includes(action)) {
        try {
          const result = await api.request(`/api/workflow-runs/${run.id}/actions`, {
            method: "POST",
            body: JSON.stringify({ action, step_key: state.selectedStepKey || null }),
          });
          if (action === "keep_changes") return runs.openDiffDialog();
          if (action === "approve") {
            await runs.follow(result.id || run.id);
            return runs.openDiffDialog();
          }
          await runs.follow(result.id || run.id);
        } catch (err) {
          ctx.features.console.append("logs", `Action failed: ${err.message}`);
          ctx.features.diagnostics.open("diagnosticLogs");
        }
      }
    },

    openSelectedStepDetail() {
      const run = currentRun;
      const step = run?.steps?.find((item) => item.key === state.selectedStepKey)
        || run?.steps?.find((item) => ["running", "failed", "waiting_input"].includes(item.status))
        || run?.steps?.[0];
      if (run && step) runs.openStepDetailModal(run, step);
    },

    async openStepDetailModal(run, step) {
      const modal = runs.ensureStepDetailModal();
      const relatedArtifacts = ctx.features.artifacts.artifactsForStep(step, run.artifacts || []);
      const artifactLabel = (artifact) => artifact.display_name || artifact.role || artifact.category || "Artifact";
      modal.title.textContent = step.title || step.key || "步驟摘要";
      modal.meta.textContent = `${step.status} · retry ${step.retry_count || 0}`;
      modal.body.innerHTML = `
        <div class="step-drawer-grid">
          <div><span>狀態</span><strong>${ui.escapeHtml(step.status || "pending")}</strong></div>
          <div><span>執行者</span><strong>${ui.escapeHtml(step.agent || step.config?.agent || step.config?.provider || "自動")}</strong></div>
          <div><span>錯誤代碼</span><strong>${ui.escapeHtml(step.error_code || "-")}</strong></div>
        </div>
        ${step.error ? `<div class="step-detail-error"><strong>目前問題</strong><span>${ui.escapeHtml(step.error)}</span></div>` : `<p class="step-detail-success">此步驟目前沒有需要處理的錯誤。</p>`}
        <div class="step-detail-section"><strong>最近進度</strong>${
          (step.events || []).length
            ? `<ol class="step-detail-events">${(step.events || []).slice(-5).reverse().map((event) => `<li><span>${ui.escapeHtml(event.kind || "event")}</span>${ui.escapeHtml(event.message || "")}</li>`).join("")}</ol>`
            : "<p>尚無進度事件。</p>"
        }</div>
        <div class="step-detail-section step-detail-artifacts">
          <div class="step-detail-section-head"><strong>Prompt 與輸出</strong><span>${relatedArtifacts.length} files</span></div>
          ${relatedArtifacts.length
            ? `<div class="step-detail-artifact-list">${relatedArtifacts.map((artifact) => `<button class="step-detail-artifact-button" type="button" data-step-artifact-id="${ui.escapeHtml(artifact.id)}" title="${ui.escapeHtml(artifact.path || "Artifact")}"><span>${artifactLabel(artifact)}</span><strong>${ui.escapeHtml(String(artifact.path || "Artifact").split("/").pop())}</strong></button>`).join("")}</div>`
            : `<p>這個步驟目前尚無 Prompt 或輸出檔案。</p>`}
        </div>
        <div class="step-detail-actions">
          ${relatedArtifacts.length ? `<button class="mini-button primary-action" data-step-files="1">預覽對應文件</button>` : ""}
          <button class="mini-button" data-guide="1">補充指示</button>
          <button class="mini-button" data-retry="1">從此步驟重試</button>
          <button class="mini-button" data-diagnostics="1">開啟技術診斷</button>
        </div>`;
      const openArtifacts = async (artifactId = null) => {
        if (artifactId) state.selectedStepArtifactId = artifactId;
        await ctx.features.artifacts.openStepFilesModal(run, step, { preview: true, artifactId });
      };
      modal.body.querySelector("[data-step-files]")?.addEventListener("click", () => openArtifacts());
      modal.body.querySelectorAll("[data-step-artifact-id]").forEach((button) => {
        button.addEventListener("click", () => openArtifacts(button.dataset.stepArtifactId));
      });
      modal.body.querySelector("[data-guide]")?.addEventListener("click", () => { runs.closeStepDetailModal(); runs.addGuidance(step.key); });
      modal.body.querySelector("[data-retry]")?.addEventListener("click", () => { runs.closeStepDetailModal(); runs.retry(step.key); });
      modal.body.querySelector("[data-diagnostics]")?.addEventListener("click", () => { runs.closeStepDetailModal(); ctx.features.diagnostics.open("diagnosticConsole"); });
      modal.backdrop.hidden = false;
      document.body.classList.add("step-detail-modal-open");
      modal.close.focus();
    },

    ensureStepDetailModal() {
      let backdrop = document.getElementById("stepDetailModalBackdrop");
      if (!backdrop) {
        backdrop = document.createElement("div");
        backdrop.id = "stepDetailModalBackdrop";
        backdrop.className = "step-detail-modal-backdrop";
        backdrop.hidden = true;
        backdrop.innerHTML = `
          <div class="step-detail-modal" role="dialog" aria-modal="true" aria-labelledby="stepDetailModalTitle">
            <div class="step-detail-modal-head">
              <div>
                <h2 id="stepDetailModalTitle">Step Details</h2>
                <p id="stepDetailModalMeta"></p>
              </div>
              <button id="stepDetailModalClose" class="modal-close" type="button" aria-label="Close step details">x</button>
            </div>
            <div id="stepDetailModalBody" class="step-detail-modal-body"></div>
          </div>
        `;
        document.body.appendChild(backdrop);
        backdrop.addEventListener("click", (event) => {
          if (event.target === backdrop) runs.closeStepDetailModal();
        });
        document.addEventListener("keydown", (event) => {
          if (!backdrop.hidden && event.key === "Escape") runs.closeStepDetailModal();
        });
      }
      const close = document.getElementById("stepDetailModalClose");
      close.onclick = () => runs.closeStepDetailModal();
      return {
        backdrop,
        close,
        title: document.getElementById("stepDetailModalTitle"),
        meta: document.getElementById("stepDetailModalMeta"),
        body: document.getElementById("stepDetailModalBody"),
      };
    },

    closeStepDetailModal() {
      const backdrop = document.getElementById("stepDetailModalBackdrop");
      if (backdrop) backdrop.hidden = true;
      document.body.classList.remove("step-detail-modal-open");
    },

    async loadLatest() {
      runs.clearPanels();
      if (!state.activeSessionId) return;
      const run = await api.request(`/api/sessions/${state.activeSessionId}/workflow-runs/latest`);
      if (!run) return;
      runs.render(run);
      if (["queued", "running", "waiting_input"].includes(run.status)) {
        await runs.follow(run.id);
      }
    },

    async follow(runId) {
      ctx.features.eventStream.close();
      const run = await api.request(`/api/workflow-runs/${runId}`);
      runs.render(run);
      if (["done", "failed", "cancelled"].includes(run.status)) {
        ctx.features.messages.finishWorkflowActivity({ type: run.status });
        return;
      }
      ctx.features.eventStream.open(runId);
    },

    async start() {
      if (state.activeRunId && ["running", "queued"].includes(state.activeRunStatus)) {
        await runs.terminate();
        return;
      }
      if (state.activeRunId && state.activeRunStatus === "failed") {
        await runs.retry();
        return;
      }
      if (state.waitingForInput) {
        await ctx.features.interactions.submitAnswers();
        return;
      }
      if (!state.activeSessionId) return;

      const content = ui.byKey("messageInput").value.trim();
      if (content) {
        ctx.features.composer.clearInput();
        await ctx.features.requirements.saveContent(content);
      }
      ui.byKey("runWorkflow").disabled = true;

      try {
        state.activeRunStatus = "queued";
        state.activeRunWorkflowId = state.selectedWorkflowId || state.activeRunWorkflowId || null;
        ctx.features.workflows?.renderPreview?.();
        ctx.features.composer.updatePrimaryAction();
        ui.byKey("runWorkflow").disabled = true;
        ui.byKey("logs").textContent = "Starting workflow...\n";
        ui.byKey("qwenLive").textContent = `Waiting for ${state.defaultAgent || "agent"} process...\n`;
        const acceptsValidationScript = ctx.features.workflows?.acceptsValidationScriptForSelected?.()
          || ctx.features.workflows?.requiresValidationScriptForSelected?.()
          || false;
        const validationScript = acceptsValidationScript
          ? (ui.byKey("validationScript")?.value?.trim() || state.validationScript?.trim() || null)
          : null;
        const payload = {
          workflow_id: state.selectedWorkflowId,
          thinkingLevel: state.thinkingLevel || "medium",
          runProfile: state.runProfile || "normal",
          unattended: state.advancedMode ? Boolean(state.unattendedMode) : true,
        };
        const applied = state.appliedExecutionRecommendation;
        if (applied?.approval_mode) payload.approvalMode = applied.approval_mode;
        if (applied?.patch_mode) payload.patchMode = applied.patch_mode;
        if (validationScript) payload.validation_script = validationScript;
        const run = await api.request(`/api/sessions/${state.activeSessionId}/workflow-runs`, {
          method: "POST",
          body: JSON.stringify(payload),
        });
        if (["queued", "running", "waiting_input"].includes(run.status)) {
          ui.byKey("logs").textContent += `Attached to run ${run.id}\n`;
        }
        await runs.follow(run.id);
      } catch (err) {
        ui.byKey("logs").textContent += `Run failed to start: ${err.message}\n`;
      } finally {
        ui.byKey("runWorkflow").disabled = false;
      }
    },

    async retry(stepKey = null) {
      if (!state.activeRunId) {
        ctx.features.console.append("logs", "No run selected to retry.");
        ctx.features.diagnostics.open("diagnosticLogs");
        return;
      }
      ui.byKey("retryRun").disabled = true;
      try {
        state.activeRunStatus = "queued";
        ctx.features.layout.applyRunStatus("queued");
        ctx.features.composer.updatePrimaryAction();
        ctx.features.console.append("logs", stepKey ? `Retry requested from ${stepKey}...` : "Retry requested...");
        const run = await api.request(`/api/workflow-runs/${state.activeRunId}/retry`, {
          method: "POST",
          body: JSON.stringify({ step_key: stepKey }),
        });
        ctx.features.console.append("logs", `Retry started: ${run.id}`);
        await runs.follow(run.id);
      } catch (err) {
        ctx.features.console.append("logs", `Retry failed: ${err.message}`);
        ctx.features.diagnostics.open("diagnosticLogs");
        if (state.activeRunId) {
          const run = await api.request(`/api/workflow-runs/${state.activeRunId}`).catch(() => null);
          if (run) runs.render(run);
        }
      } finally {
        ui.byKey("retryRun").disabled = ["queued", "running"].includes(state.activeRunStatus);
        ctx.features.composer.updatePrimaryAction();
      }
    },

    defaultGuidanceStepKey() {
      const failed = document.querySelector(".step .badge.failed, .step .badge.waiting_input, .step .badge.running");
      if (failed) return failed.closest(".step")?.querySelector(".detail-step")?.dataset.stepKey || null;
      return state.selectedStepKey || document.querySelector(".step .detail-step")?.dataset.stepKey || null;
    },

    async addGuidance(stepKey = null) {
      if (!state.activeRunId) {
        ctx.features.console.append("logs", "No run selected for guidance.");
        ctx.features.diagnostics.open("diagnosticLogs");
        return;
      }
      const targetStep = stepKey || runs.defaultGuidanceStepKey();
      if (!targetStep) {
        ctx.features.console.append("logs", "No step selected for guidance.");
        ctx.features.diagnostics.open("diagnosticLogs");
        return;
      }
      const content = await ctx.features.modal.openInput({
        title: "Add Guidance",
        description: `Guidance will be attached to step: ${targetStep}`,
        label: "Guidance",
        placeholder: "Example: Do not guess SQL. Search source code and schema first.",
        hint: "Ctrl + Enter to confirm. This will not change the API flow.",
        confirmText: "Save Guidance",
        multiline: true,
      });
      if (!content || !content.trim()) return;
      ui.byKey("addGuidance").disabled = true;
      try {
        ctx.features.console.append("logs", `Adding guidance for ${targetStep}...`);
        const run = await api.request(`/api/workflow-runs/${state.activeRunId}/guidance`, {
          method: "POST",
          body: JSON.stringify({ step_key: targetStep, content }),
        });
        ctx.features.console.append("logs", run.status === "running"
          ? `Guidance saved for ${targetStep}. It will be included in later prompts.`
          : `Guidance saved. Retrying from ${targetStep}.`);
        await runs.follow(run.id);
      } catch (err) {
        ctx.features.console.append("logs", `Add Guidance failed: ${err.message}`);
        ctx.features.diagnostics.open("diagnosticLogs");
      } finally {
        ui.byKey("addGuidance").disabled = false;
      }
    },


    async manualStepControl(action, stepKey) {
      if (!state.activeRunId || !stepKey) return;
      const title = action === "skip" ? "Skip Step" : "Mark Step Passed";
      const reason = await ctx.features.modal.openInput({
        title,
        description: `${title}: ${stepKey}`,
        label: "Reason",
        placeholder: action === "skip" ? "Why is this safe to skip?" : "Why is this safe to mark passed?",
        hint: "This is a manual controller action. Use it only when you have inspected the artifacts.",
        confirmText: title,
        multiline: true,
      });
      if (reason === null || reason === undefined) return;
      try {
        const endpoint = action === "skip" ? "skip" : "pass";
        const run = await api.request(`/api/workflow-runs/${state.activeRunId}/steps/${endpoint}`, {
          method: "POST",
          body: JSON.stringify({ step_key: stepKey, reason }),
        });
        ctx.features.console.append("logs", `${title} applied to ${stepKey}.`);
        runs.render(run);
      } catch (err) {
        ctx.features.console.append("logs", `${title} failed: ${err.message}`);
        ctx.features.diagnostics.open("diagnosticLogs");
      }
    },

    async resume(stepKey = null) {
      if (!state.activeRunId) return;
      try {
        ctx.features.console.append("logs", stepKey ? `Resume requested from ${stepKey}...` : "Resume requested...");
        const run = await api.request(`/api/workflow-runs/${state.activeRunId}/resume`, {
          method: "POST",
          body: JSON.stringify({ step_key: stepKey || state.selectedStepKey || "" }),
        });
        await runs.follow(run.id);
      } catch (err) {
        ctx.features.console.append("logs", `Resume failed: ${err.message}`);
        ctx.features.diagnostics.open("diagnosticLogs");
      }
    },


    async openRunConsole(run = null) {
      if (!state.activeRunId && !run?.id) return;
      const runId = run?.id || state.activeRunId;
      try {
        const consoleView = await api.request(`/api/workflow-runs/${runId}/console`);
        ctx.features.console.append("logs", `Console: ${consoleView.summary?.steps_passed || 0}/${consoleView.summary?.steps_total || 0} passed, retries ${consoleView.summary?.retry_total || 0}.`);
        ctx.features.diagnostics.open("diagnosticConsole");
      } catch (err) {
        ctx.features.console.append("logs", `Console failed: ${err.message}`);
      }
    },

    async openPatchPreview(run = null) {
      if (!state.activeRunId && !run?.id) return;
      const runId = run?.id || state.activeRunId;
      try {
        const patch = await api.request(`/api/workflow-runs/${runId}/patch`);
        ctx.features.console.append("logs", `Patch ${patch.status || "preview"}: ${(patch.changed_files || []).length} changed file(s).`);
        await ctx.features.patchReview.open(null, state.activeRunOverview);
      } catch (err) {
        ctx.features.console.append("logs", `Patch preview failed: ${err.message}`);
      }
    },

    async applyRunPatch(run = null, files = null) {
      if (!state.activeRunId && !run?.id) return;
      const runId = run?.id || state.activeRunId;
      try {
        const result = await api.request(`/api/workflow-runs/${runId}/patch/apply`, {
          method: "POST",
          body: JSON.stringify({ files: Array.isArray(files) ? files : null }),
        });
        ctx.features.console.append("logs", `Applied ${(result.written_files || []).length} generated file(s) to the selected project.`);
        const latest = await api.request(`/api/workflow-runs/${runId}`);
        runs.render(latest);
        ctx.features.diagnostics.open("diagnosticLogs");
      } catch (err) {
        ctx.features.console.append("logs", `Patch apply failed: ${err.message}`);
        ctx.features.diagnostics.open("diagnosticLogs");
      }
    },

    async openVersionMeta(run = null) {
      if (!state.activeRunId && !run?.id) return;
      const runId = run?.id || state.activeRunId;
      try {
        const meta = await api.request(`/api/workflow-runs/${runId}/version-meta`);
        ctx.features.console.append("logs", `Version: workflow=${meta.workflow_version || "current"}, prompt=${meta.prompt_version || "current"}, contract=${meta.contract_version || "current"}.`);
        ctx.features.diagnostics.open("diagnosticLogs");
      } catch (err) {
        ctx.features.console.append("logs", `Version meta failed: ${err.message}`);
      }
    },

    async openRunDiff(run = null) {
      const source = run || (state.activeRunId ? await api.request(`/api/workflow-runs/${state.activeRunId}`).catch(() => null) : null);
      const artifact = (source?.artifacts || []).find((item) => item.path === ".workflow/run-diff.md");
      if (artifact) {
        ctx.features.artifacts.open(artifact.id);
        return;
      }
      if (!state.activeRunId) return;
      try {
        const diff = await api.request(`/api/workflow-runs/${state.activeRunId}/diff`);
        ctx.features.console.append("logs", `Run diff: ${diff.file_count || 0} changed text file(s).`);
        runs.openDiffDialog();
      } catch (err) {
        ctx.features.console.append("logs", `Run diff failed: ${err.message}`);
      }
    },

    async exportRun() {
      if (!state.activeRunId) return;
      window.open(`/api/workflow-runs/${state.activeRunId}/export`, "_blank", "noopener");
    },

    async replayRun() {
      if (!state.activeRunId) return;
      const confirmText = await ctx.features.modal.openInput({
        title: "Replay Run",
        description: "Create a new run using the same requirement, workflow, project, validation script, and run profile.",
        label: "Reason",
        placeholder: "Optional replay note",
        hint: "This starts a fresh run. Existing artifacts stay unchanged.",
        confirmText: "Replay",
        multiline: true,
      });
      if (confirmText === null || confirmText === undefined) return;
      try {
        ctx.features.console.append("logs", "Replay requested...");
        const run = await api.request(`/api/workflow-runs/${state.activeRunId}/replay`, { method: "POST", body: JSON.stringify({}) });
        ctx.features.console.append("logs", `Replay started: ${run.id}`);
        await runs.follow(run.id);
      } catch (err) {
        ctx.features.console.append("logs", `Replay failed: ${err.message}`);
        ctx.features.diagnostics.open("diagnosticLogs");
      }
    },

    async terminate() {
      if (!state.activeRunId || terminateInFlight) return;
      terminateInFlight = true;
      runs.closeResultModal({ remember: false });
      ui.byKey("runWorkflow").disabled = true;
      try {
        ctx.features.console.append("logs", "Terminating workflow...");
        const run = await api.request(`/api/workflow-runs/${state.activeRunId}/terminate`, {
          method: "POST",
          body: JSON.stringify({}),
        });
        runs.render(run);
        ctx.features.console.append("logs", "Workflow terminated.");
      } catch (err) {
        ctx.features.console.append("logs", `Terminate failed: ${err.message}`);
        ctx.features.diagnostics.open("diagnosticLogs");
      } finally {
        terminateInFlight = false;
        ui.byKey("runWorkflow").disabled = false;
      }
    },
  };

  return runs;
}
