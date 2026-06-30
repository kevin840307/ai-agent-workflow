import { Api } from "./api.js?v=20260701-step-actions1";
import { UI } from "./dom.js?v=20260701-step-actions1";
import { AppState } from "./state.js?v=20260701-step-actions1";

export function createAppContext() {
  return {
    api: Api,
    ui: UI,
    state: AppState,
    constants: {},
    features: {},
  };
}
