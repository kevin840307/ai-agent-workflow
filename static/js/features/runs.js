export function createRuns(ctx) {
  const { api, state, ui } = ctx;

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
      if (ui.byKey("runResultPanel")) {
        ui.byKey("runResultPanel").hidden = true;
        ui.byKey("runResultPanel").innerHTML = "";
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
      state.activeRunId = run.id;
      state.activeRunStatus = run.status;
      state.activeRunWorkflowId = run.workflow_id || state.activeRunWorkflowId || state.selectedWorkflowId || null;
      ctx.features.layout.applyRunStatus(run.status);

      const session = state.sessions.find((item) => item.id === run.session_id);
      const passed = run.steps.filter((step) => step.status === "passed").length;
      const running = run.steps.find((step) => step.status === "running");
      const failed = run.steps.find((step) => step.status === "failed" || step.status === "waiting_input");

      const workflowName = run.workflow_name ? ` - ${run.workflow_name}` : "";
      ui.byKey("runMeta").textContent = `${ui.shortPath(run.project_path || session?.project_path || "")}${workflowName}`;
      ui.byKey("runStatusMeta").textContent = run.status.toUpperCase();
      ui.byKey("currentStep").textContent = running?.title || failed?.title || (run.status === "done" ? "Complete" : "Idle");
      ui.byKey("progressText").textContent = `${passed} / ${run.steps.length}`;
      ui.byKey("resultText").textContent = run.status.toUpperCase();
      ui.byKey("retryRun").disabled = ["queued", "running"].includes(run.status);
      ui.byKey("addGuidance").disabled = false;
      ctx.features.composer.updatePrimaryAction(run);

      const selectedStep = run.steps.find((step) => step.key === state.selectedStepKey)
        || run.steps.find((step) => step.status === "running" || step.status === "failed" || step.status === "waiting_input")
        || run.steps.find((step) => step.status === "passed")
        || run.steps[0];
      state.selectedStepKey = selectedStep?.key || null;
      runs.renderSteps(run);
      runs.renderStepDetails(run, selectedStep);
      ctx.features.artifacts.render(run.artifacts || []);
      runs.renderResultPanel(run);
      ctx.features.interactions.render(run);
      ctx.features.workflows?.renderPreview?.();
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
      if (!step) {
        target.innerHTML = `<div class="step-detail-empty">Select a step to inspect prompt, files, retry, and errors.</div>`;
        return;
      }

      const config = step.config || {};
      const relatedArtifacts = ctx.features.artifacts.artifactsForStep(step, run.artifacts || []);
      const promptArtifact = relatedArtifacts.find((artifact) => String(artifact.path || "") === `prompts/${step.key}.md`);
      const retryPolicy = [
        `max ${Number(step.max_retries ?? config.maxRetries ?? 0)}`,
        `from ${step.retry_from_step_key || config.retryFromStepKey || "auto"}`,
        `on fail ${step.fail_action || config.failAction || "same_step"}`,
      ].join(" - ");
      const events = (step.events || []).slice(-5).reverse();
      const files = relatedArtifacts.slice(0, 6);
      target.innerHTML = `
        <article class="step-detail-card">
          <div class="step-detail-head">
            <div>
              <span class="step-detail-eyebrow">${ui.escapeHtml(step.key || "step")}</span>
              <h3>${ui.escapeHtml(step.title || step.key || "Step")}</h3>
            </div>
            <span class="badge ${step.status}">${step.status}</span>
          </div>
          <div class="step-detail-grid">
            <div><span>Retry</span><strong>${ui.escapeHtml(String(step.retry_count || 0))}</strong><small>${ui.escapeHtml(retryPolicy)}</small></div>
            <div><span>Agent</span><strong>${ui.escapeHtml(step.agent || config.agent || config.provider || state.defaultAgent || "default")}</strong><small>${config.allowInteraction ? "interactive" : "automatic"}</small></div>
            <div><span>Output</span><strong>${ui.escapeHtml(config.outputFile || config.filename || "-")}</strong><small>${files.length} related file${files.length === 1 ? "" : "s"}</small></div>
          </div>
          ${step.error ? `<div class="step-detail-error"><strong>Failure</strong><span>${ui.escapeHtml(step.error)}</span></div>` : ""}
          <div class="step-detail-actions">
            ${promptArtifact ? `<button class="mini-button step-detail-open-prompt" type="button">Prompt</button>` : ""}
            <button class="mini-button step-detail-open-drawer" type="button">Details</button>
            ${relatedArtifacts.length ? `<button class="mini-button step-detail-open-files" type="button">Files ${relatedArtifacts.length}</button>` : ""}
            <button class="mini-button step-detail-guide" type="button">Guide</button>
            <button class="mini-button step-detail-retry" type="button">Retry from here</button>
          </div>
          <div class="step-detail-section">
            <strong>Recent Events</strong>
            ${events.length ? `
              <ol class="step-detail-events">
                ${events.map((event) => `<li><span>${ui.escapeHtml(event.kind || "event")}</span>${ui.escapeHtml(event.message || "")}</li>`).join("")}
              </ol>
            ` : `<p>No step events yet.</p>`}
          </div>
          <div class="step-detail-section">
            <strong>Files</strong>
            ${files.length ? `
              <div class="step-detail-files">
                ${files.map((artifact) => `<button class="step-detail-file" data-artifact-id="${ui.escapeHtml(artifact.id)}" title="${ui.escapeHtml(artifact.path)}">${ui.escapeHtml(artifact.path)}</button>`).join("")}
              </div>
            ` : `<p>No files found for this step yet.</p>`}
          </div>
        </article>
      `;

      target.querySelector(".step-detail-open-files")?.addEventListener("click", () => ctx.features.artifacts.openStepFilesModal(run, step));
      target.querySelector(".step-detail-open-drawer")?.addEventListener("click", () => runs.openStepDetailModal(run, step));
      target.querySelector(".step-detail-open-prompt")?.addEventListener("click", () => ctx.features.artifacts.open(promptArtifact.id));
      target.querySelector(".step-detail-guide")?.addEventListener("click", () => runs.addGuidance(step.key));
      target.querySelector(".step-detail-retry")?.addEventListener("click", () => runs.retry(step.key));
      target.querySelectorAll("[data-artifact-id]").forEach((button) => {
        button.addEventListener("click", () => ctx.features.artifacts.open(button.dataset.artifactId));
      });
    },

    renderResultPanel(run) {
      const panel = ui.byKey("runResultPanel");
      if (!panel) return;
      if (!["done", "failed", "cancelled", "waiting_input"].includes(run.status)) {
        panel.hidden = true;
        panel.innerHTML = "";
        return;
      }
      const summary = (run.artifacts || []).find((artifact) => artifact.path === ".workflow/run-summary.md");
      const trace = (run.artifacts || []).find((artifact) => artifact.path === ".workflow/run-trace.json");
      const failed = (run.steps || []).find((step) => ["failed", "waiting_input", "cancelled"].includes(step.status));
      const passed = (run.steps || []).filter((step) => step.status === "passed").length;
      const retries = (run.steps || []).reduce((total, step) => total + Number(step.retry_count || 0), 0);
      panel.hidden = false;
      panel.innerHTML = `
        <div class="run-result-head">
          <div>
            <span class="run-result-eyebrow">${ui.escapeHtml(String(run.status || "").toUpperCase())}</span>
            <h2>${ui.escapeHtml(run.status === "done" ? "Workflow complete" : "Workflow needs attention")}</h2>
            <p>${ui.escapeHtml(failed?.error || run.error || (run.status === "done" ? "All enabled steps finished." : "Inspect the failed step for details."))}</p>
          </div>
          <div class="run-result-actions">
            ${summary ? `<button class="mini-button" data-result-artifact="${ui.escapeHtml(summary.id)}">Summary</button>` : ""}
            ${trace ? `<button class="mini-button" data-result-artifact="${ui.escapeHtml(trace.id)}">Trace</button>` : ""}
            <button class="mini-button" data-result-tab="logsPanel">Logs</button>
          </div>
        </div>
        <div class="run-result-grid">
          <div><span>Steps</span><strong>${passed} / ${(run.steps || []).length}</strong></div>
          <div><span>Retries</span><strong>${retries}</strong></div>
          <div><span>Error Code</span><strong>${ui.escapeHtml(failed?.error_code || run.error_code || "-")}</strong></div>
        </div>
      `;
      panel.querySelectorAll("[data-result-artifact]").forEach((button) => {
        button.addEventListener("click", () => ctx.features.artifacts.open(button.dataset.resultArtifact));
      });
      panel.querySelector("[data-result-tab]")?.addEventListener("click", () => ctx.features.layout.activateTab("logsPanel"));
    },

    async openStepDetailModal(run, step) {
      const modal = runs.ensureStepDetailModal();
      const related = ctx.features.artifacts.artifactsForStep(step, run.artifacts || []);
      const promptArtifact = related.find((artifact) => artifact.path === `prompts/${step.key}.md`);
      const outputArtifact = related.find((artifact) => artifact.path === `output/${step.config?.outputFile || step.config?.filename || ""}`);
      const traceArtifact = (run.artifacts || []).find((artifact) => artifact.path === ".workflow/run-trace.json");
      modal.title.textContent = step.title || step.key || "Step Details";
      modal.meta.textContent = `${step.status} · retry ${step.retry_count || 0}`;
      modal.body.innerHTML = `
        <div class="step-drawer-grid">
          <div><span>Agent</span><strong>${ui.escapeHtml(step.agent || step.config?.agent || step.config?.provider || "-")}</strong></div>
          <div><span>Output</span><strong>${ui.escapeHtml(step.config?.outputFile || step.config?.filename || "-")}</strong></div>
          <div><span>Error Code</span><strong>${ui.escapeHtml(step.error_code || "-")}</strong></div>
        </div>
        ${step.error ? `<div class="step-detail-error"><strong>Error</strong><span>${ui.escapeHtml(step.error)}</span></div>` : ""}
        <div class="step-detail-section"><strong>Recent Events</strong>${
          (step.events || []).length
            ? `<ol class="step-detail-events">${(step.events || []).slice(-8).reverse().map((event) => `<li><span>${ui.escapeHtml(event.kind || "event")}</span>${ui.escapeHtml(event.message || "")}</li>`).join("")}</ol>`
            : "<p>No events recorded.</p>"
        }</div>
        <div class="step-detail-actions">
          ${promptArtifact ? `<button class="mini-button" data-artifact-id="${ui.escapeHtml(promptArtifact.id)}">Prompt</button>` : ""}
          ${outputArtifact ? `<button class="mini-button" data-artifact-id="${ui.escapeHtml(outputArtifact.id)}">Output</button>` : ""}
          ${traceArtifact ? `<button class="mini-button" data-artifact-id="${ui.escapeHtml(traceArtifact.id)}">Trace</button>` : ""}
          ${related.length ? `<button class="mini-button" data-open-files="1">Files ${related.length}</button>` : ""}
          <button class="mini-button" data-guide="1">Guide</button>
          <button class="mini-button" data-retry="1">Retry</button>
        </div>
      `;
      modal.body.querySelectorAll("[data-artifact-id]").forEach((button) => {
        button.addEventListener("click", () => {
          runs.closeStepDetailModal();
          ctx.features.artifacts.open(button.dataset.artifactId);
        });
      });
      modal.body.querySelector("[data-open-files]")?.addEventListener("click", () => {
        runs.closeStepDetailModal();
        ctx.features.artifacts.openStepFilesModal(run, step);
      });
      modal.body.querySelector("[data-guide]")?.addEventListener("click", () => {
        runs.closeStepDetailModal();
        runs.addGuidance(step.key);
      });
      modal.body.querySelector("[data-retry]")?.addEventListener("click", () => {
        runs.closeStepDetailModal();
        runs.retry(step.key);
      });
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
        const run = await api.request(`/api/sessions/${state.activeSessionId}/workflow-runs`, {
          method: "POST",
          body: JSON.stringify({ workflow_id: state.selectedWorkflowId }),
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
        ctx.features.layout.activateTab("logsPanel");
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
        ctx.features.layout.activateTab("logsPanel");
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
        ctx.features.layout.activateTab("logsPanel");
        return;
      }
      const targetStep = stepKey || runs.defaultGuidanceStepKey();
      if (!targetStep) {
        ctx.features.console.append("logs", "No step selected for guidance.");
        ctx.features.layout.activateTab("logsPanel");
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
        ctx.features.layout.activateTab("logsPanel");
      } finally {
        ui.byKey("addGuidance").disabled = false;
      }
    },

    async terminate() {
      if (!state.activeRunId) return;
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
        ctx.features.layout.activateTab("logsPanel");
      } finally {
        ui.byKey("runWorkflow").disabled = false;
      }
    },
  };

  return runs;
}
