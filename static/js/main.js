import { initWorkflowDesignerPage } from "./pages/workflow-designer.js?v=20260628-artifacts3";
import { initWorkflowRunnerPage } from "./pages/workflow-runner.js?v=20260628-index-nav-dropdown1";

const page = document.body?.dataset.page || "workflow-runner";

if (page === "workflow-designer") {
  initWorkflowDesignerPage();
} else {
  initWorkflowRunnerPage();
}
