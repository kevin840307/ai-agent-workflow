import { initWorkflowDesignerPage } from "./pages/workflow-designer.js?v=20260628-workflow-json1";
import { initWorkflowRunnerPage } from "./pages/workflow-runner.js?v=20260628-index-nav-dropdown1";

const page = document.body?.dataset.page || "workflow-runner";

if (page === "workflow-designer") {
  initWorkflowDesignerPage();
} else {
  initWorkflowRunnerPage();
}
