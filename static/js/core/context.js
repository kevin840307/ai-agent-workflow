import { Api } from "./api.js?v=20260704-direct-edit-gad";
import { UI } from "./dom.js?v=20260704-direct-edit-gad";
import { AppState } from "./state.js?v=20260704-direct-edit-gad";

export function createAppContext() {
  return {
    api: Api,
    ui: UI,
    state: AppState,
    constants: {},
    features: {},
  };
}
