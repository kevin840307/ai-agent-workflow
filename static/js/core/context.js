import { Api } from "./api.js?v=20260629-static-modules15";
import { UI } from "./dom.js?v=20260629-static-modules15";
import { AppState } from "./state.js?v=20260629-static-modules15";

export function createAppContext() {
  return {
    api: Api,
    ui: UI,
    state: AppState,
    constants: {},
    features: {},
  };
}
