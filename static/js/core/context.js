import { Api } from "./api.js?v=20260704-metadata1";
import { UI } from "./dom.js?v=20260704-metadata1";
import { AppState } from "./state.js?v=20260704-metadata1";

export function createAppContext() {
  return {
    api: Api,
    ui: UI,
    state: AppState,
    constants: {},
    features: {},
  };
}
