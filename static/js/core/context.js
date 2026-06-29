import { Api } from "./api.js?v=20260629-static-modules6";
import { UI } from "./dom.js?v=20260629-static-modules6";
import { AppState } from "./state.js?v=20260629-static-modules6";

export function createAppContext() {
  return {
    api: Api,
    ui: UI,
    state: AppState,
    constants: {},
    features: {},
  };
}
