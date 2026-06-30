import { Api } from "./api.js?v=20260630-resize1";
import { UI } from "./dom.js?v=20260630-resize1";
import { AppState } from "./state.js?v=20260630-resize1";

export function createAppContext() {
  return {
    api: Api,
    ui: UI,
    state: AppState,
    constants: {},
    features: {},
  };
}
