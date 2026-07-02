import { Api } from "./api.js?v=20260702-assets-bugfix3";
import { UI } from "./dom.js?v=20260702-assets-bugfix3";
import { AppState } from "./state.js?v=20260702-assets-bugfix3";

export function createAppContext() {
  return {
    api: Api,
    ui: UI,
    state: AppState,
    constants: {},
    features: {},
  };
}
