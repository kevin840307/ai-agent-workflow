import { initWorkflowDesignerPage } from "./pages/workflow-designer.js?v=20260628-designer-desc1";
import { initWorkflowRunnerPage } from "./pages/workflow-runner.js?v=20260628-selection-persist1";

const page = document.body?.dataset.page || "workflow-runner";

if (page === "workflow-designer") {
  initWorkflowDesignerPage();
} else {
  initWorkflowRunnerPage();
}
