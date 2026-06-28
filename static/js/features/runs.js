export function createRuns(ctx) {
  const { api, state, ui } = ctx;

  const runs = {
    clearPanels() {
      ui.byKey("currentStep").textContent = "Idle";
      ui.byKey("progressText").textContent = "0 / 0";
      ui.byKey("resultText").textContent = "Waiting";
      ctx.features.interactions.hide();
      runs.renderStepSkeleton([]);
      ui.byKey("qwenLive").textContent = "No Qwen output yet.";
      ui.byKey("logs").textContent = "";
      ui.byKey("artifacts").innerHTML = "";
      ui.byKey("artifactContent").textContent = "";
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
      ctx.features.layout.applyRunStatus(run.status);

      const session = state.sessions.find((item) => item.id === run.session_id);
      const passed = run.steps.filter((step) => step.status === "passed").length;
      const running = run.steps.find((step) => step.status === "running");
      const failed = run.steps.find((step) => step.status === "failed" || step.status === "waiting_input");

      const workflowName = run.workflow_name ? ` · ${run.workflow_name}` : "";
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
      ctx.features.artifacts.render(run.artifacts || []);
      ctx.features.interactions.render(run);
    },

    renderSteps(run) {
      const steps = ui.byKey("steps");
      steps.innerHTML = "";
      run.steps.forEach((step) => {
        const row = document.createElement("div");
        row.className = `step${state.selectedStepKey === step.key ? " selected" : ""}`;
        const retry = step.retry_count ? `<span class="retry-count">retry ${step.retry_count}</span>` : "";
        const error = step.error ? `<small>${ui.escapeHtml(step.error)}</small>` : "";
        const relatedArtifacts = ctx.features.artifacts.artifactsForStep(step, run.artifacts || []);
        row.innerHTML = `
          <div class="step-title"><span>${ui.escapeHtml(step.title)}</span>${retry}</div>
          <div class="step-message">${error}</div>
          <div class="step-actions">
            ${relatedArtifacts.length ? `<button class="mini-button inspect-step" data-step-key="${ui.escapeHtml(step.key)}">Files ${relatedArtifacts.length}</button>` : ""}
            <button class="mini-button guide-step" data-step-key="${ui.escapeHtml(step.key)}">Guide</button>
            <button class="mini-button retry-step" data-step-key="${ui.escapeHtml(step.key)}">Retry</button>
            <span class="badge ${step.status}">${step.status}</span>
          </div>
        `;
        row.onclick = (event) => {
          if (event.target.closest("button")) return;
          runs.selectStep(run, step.key);
        };
        const inspect = row.querySelector(".inspect-step");
        if (inspect) inspect.onclick = (event) => {
          event.stopPropagation();
          ctx.features.artifacts.openStepFilesModal(run, step);
        };
        row.querySelector(".guide-step").onclick = () => runs.addGuidance(step.key);
        row.querySelector(".retry-step").onclick = () => runs.retry(step.key);
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
        ctx.features.composer.updatePrimaryAction();
        ui.byKey("runWorkflow").disabled = true;
        ui.byKey("logs").textContent = "Starting workflow...\n";
        ui.byKey("qwenLive").textContent = "Waiting for Qwen process...\n";
        const run = await api.request(`/api/sessions/${state.activeSessionId}/workflow-runs`, {
          method: "POST",
          body: JSON.stringify({ workflow_id: state.selectedWorkflowId }),
        });
        if (["queued", "running", "waiting_input"].includes(run.status)) {
          ui.byKey("logs").textContent += `Attached to run ${run.id}\n`;
        }
        await runs.follow(run.id);
      } catch (err) {
        state.activeRunStatus = null;
        ui.byKey("logs").textContent += `Run failed to start: ${err.message}\n`;
        ctx.features.workflowNotification?.showStartFailure(err);
      } finally {
        ui.byKey("runWorkflow").disabled = false;
        ctx.features.composer.updatePrimaryAction();
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
      if (failed) return failed.closest(".step")?.querySelector(".guide-step")?.dataset.stepKey || null;
      return document.querySelector(".step .guide-step")?.dataset.stepKey || null;
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
