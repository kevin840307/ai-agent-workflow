import { Api } from "./api.js?v=20260704-designer-layout1";
import { UI } from "./dom.js?v=20260704-designer-layout1";
import { AppState } from "./state.js?v=20260704-designer-layout1";

export function createAppContext() {
  return {
    api: Api,
    ui: UI,
    state: AppState,
    constants: {},
    features: {},
  };
}
