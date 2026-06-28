export function createInteractions(ctx) {
  const { api, state, ui } = ctx;

  const interactions = {
    hide() {
      state.questionArtifactId = null;
      state.interactionLoadToken += 1;
      ctx.features.composer.setWaiting(false);
    },

    render(run) {
      const waitingStep = run.steps.find((step) => step.status === "waiting_input");
      if (run.status !== "waiting_input" || !waitingStep) {
        interactions.hide();
        return;
      }

      ctx.features.composer.setWaiting(true);
      ctx.features.messages.renderAsk(waitingStep.error || "Qwen needs more information before continuing.");
      setTimeout(() => {
        ui.byKey("messages").scrollTop = ui.byKey("messages").scrollHeight;
        ui.byKey("messageInput").focus();
      }, 0);

      const artifact = (run.artifacts || []).find((item) => item.path === "input/questions.md");
      state.questionArtifactId = artifact?.id || null;
      const token = ++state.interactionLoadToken;
      if (!state.questionArtifactId) return;

      api.request(`/api/artifacts/${encodeURIComponent(state.questionArtifactId)}`)
        .then((data) => {
          if (token === state.interactionLoadToken && state.activeRunId === run.id) {
            ctx.features.messages.renderAsk(data.content);
            ui.byKey("messageInput").focus();
          }
        })
        .catch((err) => {
          if (token === state.interactionLoadToken) {
            ctx.features.console.append("logs", `Question file could not be loaded: ${err.message}`);
          }
        });
    },

    async submitAnswers() {
      if (!state.activeRunId) return;
      const content = ui.byKey("messageInput").value.trim();
      if (!content) {
        ctx.features.console.append("logs", "Please enter a reply before continuing.");
        return;
      }
      ctx.features.composer.clearInput();
      ui.byKey("runWorkflow").disabled = true;
      try {
        ctx.features.console.append("logs", "Submitting reply and continuing workflow...");
        const run = await api.request(`/api/workflow-runs/${state.activeRunId}/answers`, {
          method: "POST",
          body: JSON.stringify({ content }),
        });
        await ctx.features.messages.load({ hydrateInput: false });
        interactions.hide();
        await ctx.features.runs.follow(run.id);
      } catch (err) {
        ctx.features.console.append("logs", `Continue failed: ${err.message}`);
        ctx.features.layout.activateTab("logsPanel");
      } finally {
        ui.byKey("runWorkflow").disabled = false;
      }
    },
  };

  return interactions;
}
