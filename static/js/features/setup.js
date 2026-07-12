import { LocalStore, StorageKeys } from "../core/storage.js?v=20260712-ui-v22";
export function createSetup(ctx) {
  const { api, ui, state } = ctx;
  let lastStatus = null;
  let connectivityTimer = null;
  let connectivityInFlight = false;
  let connectivityBound = false;

  function activeProjectPath() {
    return state.sessions.find((item) => item.id === state.activeSessionId)?.project_path || null;
  }

  function connectivityDelay(status) {
    if (document.hidden) return 30000;
    if (!status || status.state === "offline") return 2500;
    if (["unknown", "unavailable"].includes(status.state)) return 6000;
    return 15000;
  }

  function renderConnectivity(status, { announce = true } = {}) {
    const button = ui.byKey("modelConnectivity");
    if (!button) return;
    const previous = state.providerConnectivity;
    state.providerConnectivity = status;
    const nextState = status?.state || "unknown";
    const labels = {
      online: "模型已連線",
      offline: "模型離線，重試中",
      unknown: "Agent 可用，模型待確認",
      unavailable: "Agent 不可用",
      checking: "檢查模型",
    };
    button.className = `model-connectivity state-${nextState}`;
    const text = button.querySelector(".model-connectivity-text");
    if (text) text.textContent = labels[nextState] || labels.unknown;
    const endpoint = (status?.endpoints || []).find((item) => item.reachable) || (status?.endpoints || [])[0];
    button.title = [
      labels[nextState] || labels.unknown,
      endpoint?.base_url || "未偵測到模型 Endpoint",
      endpoint?.latency_ms != null ? `${endpoint.latency_ms} ms` : "",
      status?.checked_at || "",
      "點擊立即重新檢查",
    ].filter(Boolean).join(" · ");

    if (!announce || !previous || previous.state === nextState) return;
    if (nextState === "online" && previous.state !== "online") {
      ctx.features.console?.append("logs", "Model endpoint is online again. Workflow recovery can continue automatically.");
      ctx.features.messages?.updateWorkflowActivity({ message: "Model connection restored. Continuing workflow recovery." });
    } else if (nextState === "offline" && previous.state !== "offline") {
      ctx.features.console?.append("logs", "Model endpoint is offline. The UI will keep checking and the workflow recovery policy will retry.");
      ctx.features.messages?.updateWorkflowActivity({ message: "Model temporarily offline. Waiting for automatic reconnection." });
    }
  }

  function scheduleConnectivity(status = state.providerConnectivity) {
    if (connectivityTimer) window.clearTimeout(connectivityTimer);
    connectivityTimer = window.setTimeout(() => setup.refreshConnectivity(), connectivityDelay(status));
  }

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

    async refreshConnectivity({ force = false } = {}) {
      if (connectivityInFlight) return state.providerConnectivity;
      connectivityInFlight = true;
      const button = ui.byKey("modelConnectivity");
      if (button && !state.providerConnectivity) button.className = "model-connectivity state-checking";
      try {
        const projectPath = activeProjectPath();
        const params = new URLSearchParams();
        if (projectPath) params.set("projectPath", projectPath);
        if (state.defaultAgent && state.defaultAgent !== "agent") params.set("agent", state.defaultAgent);
        const query = params.toString() ? `?${params.toString()}` : "";
        const status = await api.request(`/api/setup/connectivity${query}`);
        renderConnectivity(status);
        scheduleConnectivity(status);
        return status;
      } catch (err) {
        const status = { state: "offline", online: false, error: err.message, endpoints: [], checked_at: new Date().toISOString() };
        renderConnectivity(status);
        scheduleConnectivity(status);
        return status;
      } finally {
        connectivityInFlight = false;
      }
    },

    startConnectivityMonitor() {
      if (!connectivityBound) {
        connectivityBound = true;
        ui.byKey("modelConnectivity")?.addEventListener("click", () => setup.refreshConnectivity({ force: true }));
        document.addEventListener("visibilitychange", () => {
          if (!document.hidden) setup.refreshConnectivity({ force: true });
          else scheduleConnectivity();
        });
        window.addEventListener("online", () => setup.refreshConnectivity({ force: true }));
      }
      setup.refreshConnectivity({ force: true });
    },

    stopConnectivityMonitor() {
      if (connectivityTimer) window.clearTimeout(connectivityTimer);
      connectivityTimer = null;
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
