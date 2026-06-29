import { LocalStore, StorageKeys } from "../core/storage.js";

export function createConfig(ctx) {
  const { api, ui } = ctx;

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
      if (ui.byKey("opencodeBin")) ui.byKey("opencodeBin").value = providers.opencode?.bin || "opencode.cmd";
      if (ui.byKey("opencodeMode")) ui.byKey("opencodeMode").value = providers.opencode?.mode || "run";
      if (ui.byKey("opencodeReuseSession")) ui.byKey("opencodeReuseSession").checked = providers.opencode?.reuse_session ?? providers.opencode?.reuseSession ?? true;
      if (ui.byKey("opencodeTimeout")) ui.byKey("opencodeTimeout").value = providers.opencode?.timeout_sec ?? providers.opencode?.timeoutSec ?? 1200;
      if (ui.byKey("opencodeModel")) ui.byKey("opencodeModel").value = providers.opencode?.model || "";
      if (ui.byKey("opencodeAgent")) ui.byKey("opencodeAgent").value = providers.opencode?.agent || "";
      configFeature.renderAgentMeta(qwen);
    },

    renderAgentMeta(qwen) {
      const mode = qwen.mock ? "MOCK" : "REAL";
      const exists = qwen.exists ? "ready" : "missing";
      const skills = qwen.skills_ready ? `${qwen.skill_count} skills` : "no skills";
      const agents = qwen.agents || {};
      const providers = agents.providers || {};
      const defaultAgent = agents.default || "qwen";
      const opencode = providers.opencode;
      const opencodeStatus = opencode
        ? `opencode ${opencode.exists ? "ready" : "missing"} ${opencode.reuse_session ? "reuse" : "fresh"} ${opencode.timeout_sec || 1200}s`
        : "opencode unavailable";
      ui.byKey("qwenMeta").textContent = `${mode} - default ${defaultAgent} - qwen ${exists} - ${opencodeStatus} - ${skills}`;
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
          opencode_bin: ui.byKey("opencodeBin")?.value || "opencode.cmd",
          opencode_mode: ui.byKey("opencodeMode")?.value || "run",
          opencode_reuse_session: ui.byKey("opencodeReuseSession")?.checked ?? true,
          opencode_timeout_sec: Number(ui.byKey("opencodeTimeout")?.value || 1200),
          opencode_model: ui.byKey("opencodeModel")?.value || "",
          opencode_agent: ui.byKey("opencodeAgent")?.value || "",
        }),
      });
      configFeature.renderAgentMeta(config.qwen);
    },
  };

  return configFeature;
}
