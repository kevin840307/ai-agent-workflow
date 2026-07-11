import { LocalStore, StorageKeys } from "../core/storage.js?v=20260711-ui-v12";
export function createSetup(ctx) {
  const { api, ui } = ctx;
  let lastStatus = null;

  const setup = {
    async check(projectPath = null) {
      const query = projectPath ? `?projectPath=${encodeURIComponent(projectPath)}` : "";
      try {
        lastStatus = await api.request(`/api/setup/status${query}`);
        const card = ui.byKey("setupStatusCard");
        const text = ui.byKey("setupStatusText");
        const blocking = !lastStatus.ready;
        const dismissed = LocalStore.getBoolean(StorageKeys.setupNoticeDismissed, false);
        if (card) card.hidden = !blocking || dismissed;
        if (text) {
          const recommendation = (lastStatus.recommendations || [])[0] || "開啟檢查查看完整環境狀態。";
          text.textContent = recommendation.length > 72 ? `${recommendation.slice(0, 69)}…` : recommendation;
          text.title = (lastStatus.recommendations || []).join(" ");
        }
        return lastStatus;
      } catch (err) {
        const card = ui.byKey("setupStatusCard");
        if (card && !LocalStore.getBoolean(StorageKeys.setupNoticeDismissed, false)) card.hidden = false;
        if (ui.byKey("setupStatusText")) ui.byKey("setupStatusText").textContent = err.message;
        return null;
      }
    },

    dismissNotice() {
      LocalStore.setBoolean(StorageKeys.setupNoticeDismissed, true);
      const card = ui.byKey("setupStatusCard");
      if (card) card.hidden = true;
    },

    async openWizard() {
      const status = lastStatus || await setup.check();
      if (!status) return;
      const icon = (step) => step.status === "ready" ? "✓" : step.status === "warning" ? "△" : "✕";
      const label = (step) => step.status === "ready" ? "Ready" : step.status === "warning" ? "建議確認" : "Needs attention";
      const lines = [
        ...(status.steps || []).map((step, index) => `${index + 1}. ${icon(step)} ${step.title}: ${label(step)}${step.detail ? ` · ${step.detail}` : ""}`),
        "",
        status.fully_ready ? "所有檢查皆已就緒。" : status.ready ? "必要條件已就緒；建議完成警告項目後再執行長時間 Workflow。" : "請先修正阻擋項目。",
        "",
        ...(status.recommendations || ["環境已可執行 Workflow。"]),
      ];
      const action = await ctx.features.modal.openInput({
        title: "環境檢查",
        description: "七項環境 readiness 檢查；警告不會阻擋短任務，但可能影響長時間 Workflow。",
        label: "Status",
        hint: "Smoke Test 會在暫存 Project 驗證模型、Session 與工具寫檔，不會修改正式專案。",
        confirmText: "執行 Smoke Test",
        cancelText: "關閉",
        required: false,
        multiline: true,
        initialValue: lines.join("\n"),
        readOnly: true,
      });
      if (action !== null) await setup.runSmoke();
    },

    async runSmoke() {
      const active = ctx.state.sessions.find((item) => item.id === ctx.state.activeSessionId);
      const agent = ctx.state.defaultAgent && ctx.state.defaultAgent !== "agent" ? ctx.state.defaultAgent : "qwen";
      let result;
      try {
        result = await api.request("/api/setup/smoke", {
          method: "POST",
          body: JSON.stringify({ project_path: active?.project_path || null, agent, run_agent: true }),
        });
      } catch (err) {
        result = { ready: false, steps: [{ id: "request", status: "failed", detail: err.message }], recommendations: [err.message] };
      }
      const icon = (step) => step.status === "passed" ? "✓" : step.status === "skipped" ? "–" : "✕";
      const lines = [
        `Agent: ${result.agent || agent}`,
        `Result: ${result.ready ? "READY" : "NEEDS ATTENTION"}`,
        "",
        ...(result.steps || []).map((step, index) => `${index + 1}. ${icon(step)} ${step.id}: ${step.status}${step.detail ? ` · ${step.detail}` : ""}`),
        "",
        ...(result.recommendations || []),
      ];
      await ctx.features.modal.openInput({
        title: "環境 Smoke Test",
        description: "模型與工具測試使用隔離暫存目錄。",
        label: "Result",
        hint: result.ready ? "所有 smoke checks 已通過。" : "請依失敗項目修正 Agent、模型或 Tool Calling 設定。",
        confirmText: "完成",
        cancelText: "關閉",
        required: false,
        multiline: true,
        initialValue: lines.join("\n"),
        readOnly: true,
      });
      await setup.check(active?.project_path || null);
      return result;
    },
  };
  return setup;
}
