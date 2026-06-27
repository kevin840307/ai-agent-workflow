export function createRuns(ctx) {
  const { api, constants, state, ui } = ctx;
  const { WORKFLOW_STEPS } = constants;

  const runs = {
    clearPanels() {
      ui.byKey("currentStep").textContent = "Idle";
      ui.byKey("progressText").textContent = `0 / ${WORKFLOW_STEPS.length}`;
      ui.byKey("resultText").textContent = "Waiting";
      ctx.features.interactions.hide();
      runs.renderStepSkeleton();
      ui.byKey("qwenLive").textContent = "No Qwen output yet.";
      ui.byKey("logs").textContent = "";
      ui.byKey("artifacts").innerHTML = "";
      ui.byKey("artifactContent").textContent = "";
    },

    renderStepSkeleton() {
      const steps = ui.byKey("steps");
      steps.innerHTML = "";
      WORKFLOW_STEPS.forEach((title) => {
        const row = document.createElement("div");
        row.className = "step";
        row.innerHTML = `<div><span>${title}</span></div><div class="step-actions"><span class="badge pending">pending</span></div>`;
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

      ui.byKey("runMeta").textContent = ui.shortPath(run.project_path || session?.project_path || "");
      ui.byKey("runStatusMeta").textContent = run.status.toUpperCase();
      ui.byKey("currentStep").textContent = running?.title || failed?.title || (run.status === "done" ? "Complete" : "Idle");
      ui.byKey("progressText").textContent = `${passed} / ${run.steps.length}`;
      ui.byKey("resultText").textContent = run.status.toUpperCase();
      ui.byKey("retryRun").disabled = run.status === "running";
      ui.byKey("addGuidance").disabled = false;
      ctx.features.composer.updatePrimaryAction(run);

      runs.renderSteps(run);
      ctx.features.artifacts.render(run.artifacts || []);
      ctx.features.interactions.render(run);
    },

    renderSteps(run) {
      const steps = ui.byKey("steps");
      steps.innerHTML = "";
      run.steps.forEach((step) => {
        const row = document.createElement("div");
        row.className = "step";
        const retry = step.retry_count ? `<span class="retry-count">retry ${step.retry_count}</span>` : "";
        const error = step.error ? `<small>${ui.escapeHtml(step.error)}</small>` : "";
        const promptArtifact = (run.artifacts || []).find((artifact) => artifact.path === `prompts/${step.key}.md`);
        const promptButton = promptArtifact ? `<button class="mini-button" data-artifact-id="${ui.escapeHtml(promptArtifact.id)}">Prompt</button>` : "";
        row.innerHTML = `
          <div><span>${ui.escapeHtml(step.title)}</span>${retry}${error}</div>
          <div class="step-actions">
            ${promptButton}
            <button class="mini-button guide-step" data-step-key="${ui.escapeHtml(step.key)}">Guide</button>
            <button class="mini-button retry-step" data-step-key="${ui.escapeHtml(step.key)}">Retry</button>
            <span class="badge ${step.status}">${step.status}</span>
          </div>
        `;
        const prompt = row.querySelector("[data-artifact-id]");
        if (prompt) prompt.onclick = () => ctx.features.artifacts.open(prompt.dataset.artifactId);
        row.querySelector(".guide-step").onclick = () => runs.addGuidance(step.key);
        row.querySelector(".retry-step").onclick = () => runs.retry(step.key);
        steps.appendChild(row);
      });
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
      if (content) await ctx.features.requirements.save();
      ui.byKey("runWorkflow").disabled = true;

      try {
        ui.byKey("logs").textContent = "Starting workflow...\n";
        ui.byKey("qwenLive").textContent = "Waiting for Qwen process...\n";
        const run = await api.request(`/api/sessions/${state.activeSessionId}/workflow-runs`, {
          method: "POST",
          body: JSON.stringify({}),
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
        ui.byKey("retryRun").disabled = false;
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
      const content = prompt(`Add guidance for ${targetStep}`, "");
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
