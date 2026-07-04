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
      ctx.features.messages.finishWorkflowActivity(event);
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
      ctx.features.messages.resetWorkflowActivity(runId);
      ctx.features.console.setLiveStatus("qwenLive", "Agent output is shown in the chat timeline. Raw token streaming is not printed here.");
      state.eventSource = new EventSource(`/api/workflow-runs/${runId}/events`);
      state.eventSource.onmessage = (message) => {
        const event = JSON.parse(message.data);
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
        // qwen_status is kept for legacy listeners. The modern UI uses the
        // provider-neutral agent_status event to avoid duplicate status rows.
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
        // qwen_output is a legacy duplicate of agent_output. Ignoring it avoids
        // double-printing every token and prevents the Agent panel from growing
        // until the browser becomes unresponsive.
        if (event.type === "run") ctx.features.runs.render(event.run);
        if (["done", "failed", "cancelled"].includes(event.type)) {
          eventStream.handleTerminal(runId, event);
          return;
        }
        if (event.type === "waiting_input") {
          ctx.features.messages.finishWorkflowActivity({ type: "waiting_input" });
          eventStream.close();
        }
      };
      state.eventSource.onerror = () => {
        ctx.features.console.append("logs", "Workflow event stream disconnected.");
        ctx.features.messages.finishWorkflowActivity({ type: "disconnected" });
        eventStream.close();
      };
    },
  };

  return eventStream;
}
