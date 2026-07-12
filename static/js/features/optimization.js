import { LocalStore, StorageKeys } from "../core/storage.js?v=20260712-ui-v22";
export function createOptimization(ctx) {
  const { api, state, ui } = ctx;
  let timer = null;
  let requestToken = 0;

  function activeProjectPath() {
    return state.sessions.find((item) => item.id === state.activeSessionId)?.project_path || null;
  }

  function durationLabel(range = []) {
    const [low = 0, high = 0] = range;
    const format = (seconds) => seconds >= 3600 ? `${Math.round(seconds / 3600)}h` : `${Math.max(1, Math.round(seconds / 60))}m`;
    return `${format(low)}–${format(high)}`;
  }

  const optimization = {
    schedule(requirement = null) {
      clearTimeout(timer);
      const text = (requirement ?? ui.byKey("messageInput")?.value ?? "").trim();
      if (text.length < 8 || state.runMode !== "workflow") {
        optimization.clear();
        return;
      }
      timer = setTimeout(() => optimization.load(text), 650);
    },

    async load(requirement) {
      const token = ++requestToken;
      try {
        const result = await api.request("/api/optimization/recommend", {
          method: "POST",
          body: JSON.stringify({
            requirement,
            project_path: activeProjectPath(),
            agent: state.defaultAgent && state.defaultAgent !== "agent" ? state.defaultAgent : null,
          }),
        });
        if (token !== requestToken) return;
        state.executionRecommendation = result;
        optimization.render(result);
      } catch (_err) {
        if (token === requestToken) optimization.clear();
      }
    },

    render(result) {
      const target = ui.byKey("planningRecommendation");
      if (!target || !result?.ready) return optimization.clear();
      const recommendation = result.recommendation || {};
      const estimate = result.estimate || {};
      const taskRange = estimate.task_range || [1, 2];
      if (LocalStore.getBoolean(StorageKeys.recommendationNoticeDismissed, false)) return optimization.clear(false);
      const risk = result.risk || {};
      target.hidden = false;
      target.innerHTML = `
        <details class="recommendation-details">
          <summary title="查看執行建議">
            <span class="recommendation-icon" aria-hidden="true">✦</span>
            <span class="recommendation-summary"><strong>${ui.escapeHtml(recommendation.workflow_id || "workflow")}</strong><small>${ui.escapeHtml(recommendation.agent || "qwen")} · ${ui.escapeHtml(recommendation.run_profile || "normal")} · ${taskRange[0]}–${taskRange[1]} tasks · ${durationLabel(estimate.duration_sec_range)}</small></span>
          </summary>
          <div class="recommendation-popover">
            <div><span>建議原因</span><p>${ui.escapeHtml(recommendation.workflow_reason || "依任務複雜度與歷史結果建議。")}</p></div>
            <div class="recommendation-facts"><span>Risk <strong>${ui.escapeHtml(risk.level || "low")}</strong></span><span>Confidence <strong>${Math.round(Number(recommendation.confidence || 0) * 100)}%</strong></span></div>
            <div class="recommendation-actions"><button id="applyExecutionRecommendation" class="mini-button primary-action" type="button">套用建議</button><button id="dismissExecutionRecommendation" class="mini-button" type="button">不再顯示</button></div>
          </div>
        </details>`;
      target.querySelector("#applyExecutionRecommendation")?.addEventListener("click", (event) => { event.preventDefault(); optimization.apply(); });
      target.querySelector("#dismissExecutionRecommendation")?.addEventListener("click", (event) => { event.preventDefault(); optimization.dismiss(); });
    },

    apply() {
      const recommendation = state.executionRecommendation?.recommendation;
      if (!recommendation) return;
      if (recommendation.workflow_id) ctx.features.workflows.select(recommendation.workflow_id);
      if (recommendation.run_profile) ctx.features.workflows.selectRunProfile(recommendation.run_profile);
      if (recommendation.thinking_level) ctx.features.workflows.selectThinkingLevel(recommendation.thinking_level);
      if (recommendation.agent && ui.byKey("defaultAgent")) {
        ui.byKey("defaultAgent").value = recommendation.agent;
        state.defaultAgent = recommendation.agent;
      }
      const risk = state.executionRecommendation?.risk || {};
      state.appliedExecutionRecommendation = {
        workflow_id: recommendation.workflow_id,
        run_profile: recommendation.run_profile,
        approval_mode: risk.recommended?.approval_mode || "fully_automatic",
        patch_mode: risk.recommended?.patch_mode || "auto_apply",
      };
      const button = ui.byKey("planningRecommendation")?.querySelector("#applyExecutionRecommendation");
      if (button) {
        button.textContent = "已套用";
        button.disabled = true;
      }
    },

    dismiss() {
      LocalStore.setBoolean(StorageKeys.recommendationNoticeDismissed, true);
      optimization.clear();
    },

    clear(resetState = true) {
      if (resetState) state.executionRecommendation = null;
      const target = ui.byKey("planningRecommendation");
      if (target) {
        target.hidden = true;
        target.innerHTML = "";
      }
    },
  };
  return optimization;
}
