import { Api } from "./api.js";
import { UI } from "./dom.js";
import { AppState, WORKFLOW_STEPS } from "./state.js";

export function createAppContext() {
  return {
    api: Api,
    ui: UI,
    state: AppState,
    constants: { WORKFLOW_STEPS },
    features: {},
  };
}
