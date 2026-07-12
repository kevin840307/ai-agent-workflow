export function createEventStream(ctx) {
  const { api, state } = ctx;
  let renderTimer = null;
  let latestRun = null;

  function flushRunRender() {
    if (renderTimer) window.clearTimeout(renderTimer);
    renderTimer = null;
    const run = latestRun;
    latestRun = null;
    if (run) ctx.features.runs.render(run);
  }

  function scheduleRunRender(run) {
    latestRun = run;
    if (renderTimer) return;
    renderTimer = window.setTimeout(flushRunRender, 220);
  }

  const eventStream = {
    close() {
      if (renderTimer) window.clearTimeout(renderTimer);
      renderTimer = null;
      latestRun = null;
      if (state.eventSource) {
        state.eventSource.close();
        state.eventSource = null;
      }
      state.eventStreamRunId = null;
      state.eventStreamConnected = false;
    },

    async handleTerminal(runId, event) {
      eventStream.close();
      ctx.features.messages.finishWorkflowActivity(event);
      const run = await api.request(`/api/workflow-runs/${encodeURIComponent(runId)}`).catch(() => null);
      if (run) {
        // runs.render owns the single result dialog. Keeping terminal display in
        // one place prevents Stop/Cancel from opening two overlapping modals.
        ctx.features.runs.render(run);
        return;
      }
      ctx.features.console.append("logs", `Workflow ended with ${event.type}${event.error ? `: ${event.error}` : "."}`);
    },

    async reconcileAfterReconnect(runId) {
      const run = await api.request(`/api/workflow-runs/${encodeURIComponent(runId)}`).catch(() => null);
      if (!run) return;
      ctx.features.runs.render(run);
      if (["done", "failed", "cancelled"].includes(run.status)) {
        eventStream.close();
        ctx.features.messages.finishWorkflowActivity({ type: run.status });
      }
    },

    open(runId) {
      eventStream.close();
      ctx.features.messages.resetWorkflowActivity(runId);
      ctx.features.console.setLiveStatus("qwenLive", "Agent output is summarized in the chat timeline. Open this panel for provider status and diagnostics.");
      state.eventStreamRunId = runId;
      const source = new EventSource(`/api/workflow-runs/${encodeURIComponent(runId)}/events`);
      state.eventSource = source;

      source.onopen = () => {
        const recovered = !state.eventStreamConnected && state.eventStreamLastErrorAt > 0;
        state.eventStreamConnected = true;
        if (recovered) {
          ctx.features.console.append("logs", "Workflow event stream reconnected.");
          ctx.features.messages.updateWorkflowActivity({ message: "Controller connection restored. Synchronizing workflow state." });
          eventStream.reconcileAfterReconnect(runId);
        }
      };

      source.onmessage = (message) => {
        let event;
        try {
          event = JSON.parse(message.data);
        } catch (_err) {
          ctx.features.console.append("logs", "Ignored malformed workflow event.");
          return;
        }
        if (event.type === "log") ctx.features.console.append("logs", event.message);
        if (event.type === "agent_status") {
          const agent = event.agent || state.defaultAgent || "agent";
          ctx.features.console.append("qwenLive", `[${agent}:${event.step}] ${event.message}`);
          ctx.features.messages.updateWorkflowActivity({
            agent,
            step: event.step,
            message: event.message,
            type: "status",
          });
        }
        // qwen_output is a legacy duplicate; qwen_status is also ignored intentionally.
        if (event.type === "agent_output") {
          const agent = event.agent || state.defaultAgent || "agent";
          ctx.features.messages.updateWorkflowActivity({
            agent,
            step: event.step,
            stream: event.stream,
            text: event.text,
            type: "output",
          });
        }
        if (event.type === "run") scheduleRunRender(event.run);
        if (["done", "failed", "cancelled"].includes(event.type)) {
          flushRunRender();
          eventStream.handleTerminal(runId, event);
          return;
        }
        if (event.type === "waiting_input") {
          flushRunRender();
          ctx.features.messages.finishWorkflowActivity({ type: "waiting_input" });
          eventStream.close();
        }
      };

      source.onerror = () => {
        // EventSource reconnects automatically. Closing it here made an offline
        // model/controller look permanently disconnected after it came back.
        const now = Date.now();
        state.eventStreamConnected = false;
        if (now - Number(state.eventStreamLastErrorAt || 0) > 2000) {
          state.eventStreamLastErrorAt = now;
          ctx.features.console.append("logs", "Workflow event stream disconnected; reconnecting automatically...");
          ctx.features.messages.updateWorkflowActivity({ message: "Connection interrupted. Waiting for automatic reconnection." });
          ctx.features.setup?.refreshConnectivity?.({ force: true });
        }
      };
    },
  };

  return eventStream;
}
