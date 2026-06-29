export function createWorkflowNotification(ctx) {
  const { state, ui } = ctx;

  const notification = {
    lastShownKey: null,
    lastFocusedElement: null,

    ensure() {
      let backdrop = document.getElementById("workflowResultModalBackdrop");
      if (!backdrop) {
        backdrop = document.createElement("div");
        backdrop.id = "workflowResultModalBackdrop";
        backdrop.className = "workflow-result-backdrop";
        backdrop.hidden = true;
        backdrop.innerHTML = `
          <div id="workflowResultCard" class="workflow-result-card" role="dialog" aria-modal="true" aria-labelledby="workflowResultTitle">
            <div class="workflow-result-glow" aria-hidden="true"></div>
            <div class="workflow-result-head">
              <div id="workflowResultIcon" class="workflow-result-icon" aria-hidden="true">✓</div>
              <div class="workflow-result-copy">
                <span id="workflowResultEyebrow" class="workflow-result-eyebrow">Workflow Complete</span>
                <h2 id="workflowResultTitle">Workflow finished</h2>
                <p id="workflowResultDescription">The workflow has completed.</p>
              </div>
              <button id="workflowResultClose" class="workflow-result-close" type="button" aria-label="Close result dialog">x</button>
            </div>
            <div class="workflow-result-stats" aria-label="Workflow summary">
              <div class="workflow-result-stat">
                <span>Progress</span>
                <strong id="workflowResultProgress">0 / 0</strong>
              </div>
              <div class="workflow-result-stat">
                <span>Status</span>
                <strong id="workflowResultStatus">DONE</strong>
              </div>
              <div class="workflow-result-stat">
                <span>Duration</span>
                <strong id="workflowResultDuration">—</strong>
              </div>
            </div>
            <div id="workflowResultError" class="workflow-result-error" hidden></div>
            <div class="workflow-result-actions">
              <button id="workflowResultSecondary" class="workflow-result-button secondary" type="button">Close</button>
              <button id="workflowResultLogs" class="workflow-result-button secondary" type="button">View Logs</button>
              <button id="workflowResultArtifacts" class="workflow-result-button secondary" type="button">View Artifacts</button>
              <button id="workflowResultRetry" class="workflow-result-button primary" type="button">Retry</button>
            </div>
          </div>
        `;
        document.body.appendChild(backdrop);

        backdrop.addEventListener("click", (event) => {
          if (event.target === backdrop) notification.close();
        });
        document.addEventListener("keydown", (event) => {
          if (backdrop.hidden || event.key !== "Escape") return;
          event.preventDefault();
          notification.close();
        });
      }

      return {
        backdrop,
        card: document.getElementById("workflowResultCard"),
        icon: document.getElementById("workflowResultIcon"),
        eyebrow: document.getElementById("workflowResultEyebrow"),
        title: document.getElementById("workflowResultTitle"),
        description: document.getElementById("workflowResultDescription"),
        close: document.getElementById("workflowResultClose"),
        secondary: document.getElementById("workflowResultSecondary"),
        logs: document.getElementById("workflowResultLogs"),
        artifacts: document.getElementById("workflowResultArtifacts"),
        retry: document.getElementById("workflowResultRetry"),
        progress: document.getElementById("workflowResultProgress"),
        status: document.getElementById("workflowResultStatus"),
        duration: document.getElementById("workflowResultDuration"),
        error: document.getElementById("workflowResultError"),
      };
    },

    durationText(run = {}) {
      const started = Date.parse(run.started_at || "");
      const ended = Date.parse(run.ended_at || "");
      if (!Number.isFinite(started) || !Number.isFinite(ended) || ended < started) return "—";
      const totalSeconds = Math.max(0, Math.round((ended - started) / 1000));
      if (totalSeconds < 60) return `${totalSeconds}s`;
      const minutes = Math.floor(totalSeconds / 60);
      const seconds = totalSeconds % 60;
      if (minutes < 60) return seconds ? `${minutes}m ${seconds}s` : `${minutes}m`;
      const hours = Math.floor(minutes / 60);
      const restMinutes = minutes % 60;
      return restMinutes ? `${hours}h ${restMinutes}m` : `${hours}h`;
    },

    progressText(run = {}) {
      const steps = run.steps || [];
      const passed = steps.filter((step) => step.status === "passed").length;
      return `${passed} / ${steps.length}`;
    },

    failedStep(run = {}) {
      return (run.steps || []).find((step) => ["failed", "cancelled", "waiting_input"].includes(step.status)) || null;
    },

    copyFor(run = {}, event = {}) {
      const status = run.status || event.type || "done";
      const failedStep = notification.failedStep(run);
      const workflowName = run.workflow_name || "Workflow";
      const projectPath = ui.shortPath(run.project_path || "");
      const location = projectPath ? ` in ${projectPath}` : "";

      if (status === "done") {
        return {
          variant: "success",
          icon: "✓",
          eyebrow: "Workflow Complete",
          title: `${workflowName} completed`,
          description: `All enabled steps finished successfully${location}.`,
          error: "",
          showRetry: false,
          primaryAction: "artifacts",
        };
      }

      if (status === "cancelled") {
        return {
          variant: "cancelled",
          icon: "■",
          eyebrow: "Workflow Stopped",
          title: `${workflowName} was cancelled`,
          description: `The workflow stopped before completion${location}.`,
          error: run.error || event.error || "Workflow cancelled by user.",
          showRetry: true,
          primaryAction: "logs",
        };
      }

      const failedTitle = failedStep?.title || failedStep?.key || "a workflow step";
      return {
        variant: "failed",
        icon: "!",
        eyebrow: "Workflow Failed",
        title: `${workflowName} stopped`,
        description: `The workflow stopped at ${failedTitle}${location}.`,
        error: failedStep?.error || run.error || event.error || "Workflow failed. Check logs for details.",
        showRetry: true,
        primaryAction: "logs",
      };
    },

    bindActions(els, run, copy) {
      els.close.onclick = () => notification.close();
      els.secondary.onclick = () => notification.close();
      els.logs.onclick = () => {
        notification.close();
        ctx.features.layout.activateTab("logsPanel");
      };
      els.artifacts.onclick = () => {
        notification.close();
        ctx.features.layout.activateTab("artifactsPanel");
      };
      els.retry.onclick = () => {
        notification.close();
        ctx.features.runs.retry();
      };

      els.artifacts.hidden = copy.primaryAction !== "artifacts" && !(run.artifacts || []).length;
      els.logs.hidden = false;
      els.retry.hidden = !copy.showRetry;
    },

    show(run = {}, event = {}) {
      const status = run.status || event.type;
      if (!["done", "failed", "cancelled"].includes(status)) return;

      const shownKey = `${run.id || state.activeRunId || "unknown"}:${status}:${run.ended_at || event.error || "terminal"}`;
      if (notification.lastShownKey === shownKey) return;
      notification.lastShownKey = shownKey;

      const els = notification.ensure();
      const copy = notification.copyFor(run, event);
      els.card.className = `workflow-result-card ${copy.variant}`;
      els.icon.textContent = copy.icon;
      els.eyebrow.textContent = copy.eyebrow;
      els.title.textContent = copy.title;
      els.description.textContent = copy.description;
      els.progress.textContent = notification.progressText(run);
      els.status.textContent = String(status || "done").toUpperCase();
      els.duration.textContent = notification.durationText(run);

      if (copy.error) {
        els.error.hidden = false;
        els.error.textContent = copy.error;
      } else {
        els.error.hidden = true;
        els.error.textContent = "";
      }

      notification.bindActions(els, run, copy);
      notification.lastFocusedElement = document.activeElement;
      els.backdrop.hidden = false;
      document.body.classList.add("workflow-result-open");
      setTimeout(() => {
        const focusTarget = copy.showRetry ? els.retry : (copy.primaryAction === "artifacts" ? els.artifacts : els.logs);
        if (focusTarget && !focusTarget.hidden) focusTarget.focus();
      }, 0);
    },

    showStartFailure(error) {
      const run = {
        id: state.activeRunId || "start-failure",
        status: "failed",
        workflow_name: "Workflow",
        project_path: state.sessions.find((item) => item.id === state.activeSessionId)?.project_path || "",
        started_at: new Date().toISOString(),
        ended_at: new Date().toISOString(),
        error: error?.message || String(error || "Workflow failed to start."),
        steps: [],
        artifacts: [],
      };
      notification.show(run, { type: "failed", error: run.error });
    },

    close() {
      const els = notification.ensure();
      els.backdrop.hidden = true;
      document.body.classList.remove("workflow-result-open");
      if (notification.lastFocusedElement?.focus) notification.lastFocusedElement.focus();
      notification.lastFocusedElement = null;
    },
  };

  return notification;
}
