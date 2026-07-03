import { Api } from "./api.js?v=20260703-wf-wstep1";
import { UI } from "./dom.js?v=20260703-wf-wstep1";
import { AppState } from "./state.js?v=20260703-wf-wstep1";

export function createAppContext() {
  return {
    api: Api,
    ui: UI,
    state: AppState,
    constants: {},
    features: {},
  };
}
