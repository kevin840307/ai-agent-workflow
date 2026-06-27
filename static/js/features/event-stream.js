export function createEventStream(ctx) {
  const { state } = ctx;

  const eventStream = {
    close() {
      if (state.eventSource) {
        state.eventSource.close();
        state.eventSource = null;
      }
    },

    open(runId) {
      state.eventSource = new EventSource(`/api/workflow-runs/${runId}/events`);
      state.eventSource.onmessage = (message) => {
        const event = JSON.parse(message.data);
        if (event.type === "log") ctx.features.console.append("logs", event.message);
        if (event.type === "qwen_status") ctx.features.console.append("qwenLive", `[${event.step}] ${event.message}`);
        if (event.type === "qwen_output") ctx.features.console.append("qwenLive", `[${event.step}:${event.stream}] ${event.text}`);
        if (event.type === "run") ctx.features.runs.render(event.run);
        if (["done", "failed", "waiting_input", "cancelled"].includes(event.type)) eventStream.close();
      };
    },
  };

  return eventStream;
}
