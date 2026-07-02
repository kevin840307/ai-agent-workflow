import { Api } from "./api.js?v=20260702-assets-bugfix1";
import { UI } from "./dom.js?v=20260702-assets-bugfix1";
import { AppState } from "./state.js?v=20260702-assets-bugfix1";

export function createAppContext() {
  return {
    api: Api,
    ui: UI,
    state: AppState,
    constants: {},
    features: {},
  };
}
