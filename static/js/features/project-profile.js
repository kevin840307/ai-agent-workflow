import { LocalStore, StorageKeys } from "../core/storage.js?v=20260712-ui-v22";

function statusLabel(profile) {
  const status = String(profile?.status || "draft").toLowerCase();
  return {
    trusted: "已信任，可自動重用",
    verified: "已驗證，可自動重用",
    stale: "專案設定已變更，需重新驗證",
    draft: "已偵測，尚未驗證",
  }[status] || "等待偵測";
}

function phaseLines(profile) {
  const phases = Array.isArray(profile?.phases) ? profile.phases : [];
  if (!phases.length) return ["尚未偵測到 Build／Test／Validation 命令。"];
  return phases.map((phase, index) => {
    const command = Array.isArray(phase.command) ? phase.command.join(" ") : String(phase.command || "");
    const required = phase.required === false ? "建議" : "必要";
    return `${index + 1}. [${required}] ${phase.title || phase.id || "Validation"}\n   ${command || "未設定命令"}`;
  });
}

export function createProjectProfile(ctx) {
  const { api, state, ui } = ctx;
  let inFlight = false;

  function activeProjectPath() {
    return state.sessions.find((item) => item.id === state.activeSessionId)?.project_path || null;
  }

  function render(_profile, _error = "") {
    // The persistent Project Validation Profile remains available to the
    // controller, but the always-visible status badge was intentionally
    // removed to keep Simple Mode focused.
  }

  const feature = {
    render,

    async load(projectPath = activeProjectPath(), { force = false } = {}) {
      if (!projectPath) {
        state.projectValidationProfile = null;
        render(null);
        return null;
      }
      if (inFlight && !force) return state.projectValidationProfile;
      inFlight = true;
      try {
        const profile = await api.request(`/api/project-validation-profile?projectPath=${encodeURIComponent(projectPath)}`);
        state.projectValidationProfile = profile;
        render(profile);
        return profile;
      } catch (err) {
        render(null, err.message);
        return null;
      } finally {
        inFlight = false;
      }
    },

    async open() {
      const projectPath = activeProjectPath();
      if (!projectPath) return;
      const profile = state.projectValidationProfile || await feature.load(projectPath, { force: true });
      if (!profile) return;
      const editable = Boolean(state.advancedMode);
      const summary = [
        `狀態：${statusLabel(profile)}`,
        `來源：${profile.source || "auto_detected"}`,
        `主要驗證器：${profile.primary_validator || "未辨識"}`,
        `成功驗證次數：${Number(profile.successful_verifications || 0)}`,
        "",
        ...phaseLines(profile),
      ].join("\n");
      const content = editable ? JSON.stringify({
        phases: profile.phases || [],
        baseline_categories: profile.baseline_categories || [],
        fast_categories: profile.fast_categories || [],
        full_categories: profile.full_categories || [],
        environment: profile.environment || {},
        artifacts: profile.artifacts || {},
        scope: profile.scope || {},
      }, null, 2) : summary;
      const result = await ctx.features.modal.openInput({
        title: editable ? "Project Validation Profile" : "專案驗證設定",
        description: editable
          ? "編輯後會先保存為 Draft，再執行實際驗證；命令在 Project Path 執行。"
          : "平台會保存並重用這份 Build／Test／Validation 設定。",
        label: editable ? "Profile JSON" : "偵測結果",
        hint: "驗證只執行專案既有命令；不會替 Qwen／OpenCode 產生或修改專案檔案。",
        confirmText: profile.status === "stale" ? "重新驗證" : "驗證並保存",
        cancelText: "關閉",
        required: false,
        multiline: true,
        initialValue: content,
        readOnly: !editable,
      });
      if (result === null || result === undefined) return;
      try {
        if (editable) {
          let patch;
          try { patch = JSON.parse(result || "{}"); }
          catch (err) { throw new Error(`Profile JSON 格式錯誤：${err.message}`); }
          await api.request("/api/project-validation-profile", {
            method: "POST",
            body: JSON.stringify({ project_path: projectPath, profile: patch }),
          });
        }
        render({ ...profile, status: "loading" });
        const verified = await api.request("/api/project-validation-profile/verify", {
          method: "POST",
          body: JSON.stringify({ project_path: projectPath, timeout_sec: 900 }),
        });
        state.projectValidationProfile = verified.profile;
        render(verified.profile);
        ctx.features.console.append("logs", `Project Validation Profile: ${verified.profile?.status || "draft"}.`);
      } catch (err) {
        render(profile, err.message);
        ctx.features.console.append("logs", `Project Validation Profile failed: ${err.message}`);
      }
    },

    setUnattended(enabled, { persist = true } = {}) {
      state.unattendedMode = Boolean(enabled);
      const checkbox = ui.byKey("unattendedMode");
      if (checkbox) checkbox.checked = state.unattendedMode;
      if (persist) LocalStore.setBoolean(StorageKeys.unattendedMode, state.unattendedMode);
    },
  };

  return feature;
}
