export function createEventStream(ctx) {
  const { api, state } = ctx;

  const eventStream = {
    close() {
      if (state.eventSource) {
        state.eventSource.close();
        state.eventSource = null;
      }
    },

    async handleTerminal(runId, event) {
      eventStream.close();
      const run = await api.request(`/api/workflow-runs/${encodeURIComponent(runId)}`).catch(() => null);
      if (run) {
        ctx.features.runs.render(run);
        ctx.features.workflowNotification.show(run, event);
        return;
      }
      ctx.features.workflowNotification.show({
        id: runId,
        status: event.type,
        error: event.error,
        steps: [],
        artifacts: [],
      }, event);
    },

    open(runId) {
      eventStream.close();
      state.eventSource = new EventSource(`/api/workflow-runs/${runId}/events`);
      state.eventSource.onmessage = (message) => {
        const event = JSON.parse(message.data);
        if (event.type === "log") ctx.features.console.append("logs", event.message);
        if (event.type === "agent_status" || event.type === "qwen_status") {
          const agent = event.agent || state.defaultAgent || "agent";
          ctx.features.console.append("qwenLive", `[${agent}:${event.step}] ${event.message}`);
        }
        if (event.type === "agent_output" || event.type === "qwen_output") {
          const agent = event.agent || state.defaultAgent || "agent";
          ctx.features.console.append("qwenLive", `[${agent}:${event.step}:${event.stream}] ${event.text}`);
        }
        if (event.type === "run") ctx.features.runs.render(event.run);
        if (["done", "failed", "cancelled"].includes(event.type)) {
          eventStream.handleTerminal(runId, event);
          return;
        }
        if (event.type === "waiting_input") eventStream.close();
      };
      state.eventSource.onerror = () => {
        ctx.features.console.append("logs", "Workflow event stream disconnected.");
        eventStream.close();
      };
    },
  };

  return eventStream;
}
