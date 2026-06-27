export function createConfig(ctx) {
  const { api, ui } = ctx;

  const configFeature = {
    async load() {
      const config = await api.request("/api/config");
      const qwen = config.qwen;
      ui.byKey("qwenAuthType").value = qwen.auth_type || "";
      ui.byKey("qwenReuseSession").checked = Boolean(qwen.reuse_session);
      ui.byKey("maxRetries").value = qwen.max_retries ?? 2;
      configFeature.renderQwenMeta(qwen);
    },

    renderQwenMeta(qwen) {
      const mode = qwen.mock ? "MOCK" : "REAL";
      const exists = qwen.exists ? "ready" : "missing";
      const skills = qwen.skills_ready ? `${qwen.skill_count} skills` : "no skills";
      ui.byKey("qwenMeta").textContent = `${mode} - ${qwen.bin} - ${exists} - ${skills}`;
    },

    async saveQwenConfig() {
      const config = await api.request("/api/config/qwen", {
        method: "POST",
        body: JSON.stringify({
          auth_type: ui.byKey("qwenAuthType").value,
          reuse_session: ui.byKey("qwenReuseSession").checked,
          max_retries: Number(ui.byKey("maxRetries").value || 0),
        }),
      });
      configFeature.renderQwenMeta(config.qwen);
    },
  };

  return configFeature;
}
