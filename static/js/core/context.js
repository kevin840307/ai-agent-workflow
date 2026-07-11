import { Api } from "./api.js?v=20260711-ui-v12";
import { UI } from "./dom.js?v=20260711-ui-v12";
import { AppState } from "./state.js?v=20260711-ui-v12";

export function createAppContext() {
  return {
    api: Api,
    ui: UI,
    state: AppState,
    constants: {},
    features: {},
  };
}
