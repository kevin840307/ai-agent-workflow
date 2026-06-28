import { Api } from "./api.js?v=20260628-artifacts3";
import { UI } from "./dom.js?v=20260628-index-nav-dropdown1";
import { AppState } from "./state.js?v=20260628-workflow-config1";

export function createAppContext() {
  return {
    api: Api,
    ui: UI,
    state: AppState,
    constants: {},
    features: {},
  };
}
