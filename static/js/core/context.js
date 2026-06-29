import { Api } from "./api.js?v=20260629-static-modules9";
import { UI } from "./dom.js?v=20260629-static-modules9";
import { AppState } from "./state.js?v=20260629-static-modules9";

export function createAppContext() {
  return {
    api: Api,
    ui: UI,
    state: AppState,
    constants: {},
    features: {},
  };
}
