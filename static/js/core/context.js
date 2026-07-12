import { Api } from "./api.js?v=20260712-ui-v22";
import { UI } from "./dom.js?v=20260712-ui-v22";
import { AppState } from "./state.js?v=20260712-ui-v22";

export function createAppContext() {
  return {
    api: Api,
    ui: UI,
    state: AppState,
    constants: {},
    features: {},
  };
}
