import { LocalStore, StorageKeys } from "../core/storage.js";

export function createConfig(ctx) {
  const { api, state, ui } = ctx;

  const configFeature = {
    async load() {
      const cachedReuse = LocalStore.getBoolean(StorageKeys.qwenReuseSession, null);
      if (cachedReuse !== null) ui.byKey("qwenReuseSession").checked = cachedReuse;

      const config = await api.request("/api/config");
      const qwen = config.qwen;
      ui.byKey("qwenAuthType").value = qwen.auth_type || "";
      ui.byKey("qwenReuseSession").checked = Boolean(qwen.reuse_session);
      LocalStore.setBoolean(StorageKeys.qwenReuseSession, qwen.reuse_session);
      ui.byKey("maxRetries").value = qwen.max_retries ?? 2;
      const agents = qwen.agents || {};
      const providers = agents.providers || {};
      if (ui.byKey("defaultAgent")) ui.byKey("defaultAgent").value = agents.default || "qwen";
      state.defaultAgent = agents.default || "qwen";
      configFeature.renderAgentMeta(qwen);
      ctx.features.setup?.refreshConnectivity?.({ force: true });
    },

    renderAgentMeta(qwen) {
      const mode = qwen.mock ? "MOCK" : "REAL";
      const exists = qwen.exists ? "ready" : "missing";
      const skills = qwen.skills_ready ? `${qwen.skill_count} skills` : "no skills";
      const agents = qwen.agents || {};
      const providers = agents.providers || {};
      const defaultAgent = agents.default || "qwen";
      state.defaultAgent = defaultAgent;
      const selected = providers[defaultAgent];
      const selectedStatus = selected ? `${defaultAgent} ${selected.exists ? "ready" : "missing"}` : `${defaultAgent} unavailable`;
      ui.byKey("qwenMeta").textContent = `${mode} - default ${defaultAgent} - ${selectedStatus} - ${skills}`;
    },

    async saveAgentConfig() {
      LocalStore.setBoolean(StorageKeys.qwenReuseSession, ui.byKey("qwenReuseSession").checked);
      const config = await api.request("/api/config/agents", {
        method: "POST",
        body: JSON.stringify({
          auth_type: ui.byKey("qwenAuthType").value,
          reuse_session: ui.byKey("qwenReuseSession").checked,
          max_retries: Number(ui.byKey("maxRetries").value || 0),
          default_agent: ui.byKey("defaultAgent")?.value || "qwen",
        }),
      });
      state.defaultAgent = config.qwen?.agents?.default || ui.byKey("defaultAgent")?.value || "qwen";
      configFeature.renderAgentMeta(config.qwen);
      ctx.features.setup?.refreshConnectivity?.({ force: true });
    },
  };

  return configFeature;
}
