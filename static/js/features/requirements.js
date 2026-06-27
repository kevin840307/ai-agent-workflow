export function createRequirements(ctx) {
  const { api, state, ui } = ctx;

  return {
    async save() {
      const content = ui.byKey("messageInput").value.trim();
      if (!content || !state.activeSessionId) return;
      await api.request(`/api/sessions/${state.activeSessionId}/messages`, {
        method: "POST",
        body: JSON.stringify({ content }),
      });
      await ctx.features.messages.load();
      await ctx.features.sessions.refreshList();
      ui.byKey("messages").scrollTop = ui.byKey("messages").scrollHeight;
    },
  };
}
