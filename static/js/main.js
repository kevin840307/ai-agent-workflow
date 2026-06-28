import { initWorkflowDesignerPage } from "./pages/workflow-designer.js?v=20260628-workflow-config1";
import { initWorkflowRunnerPage } from "./pages/workflow-runner.js?v=20260628-result-modal1";

const page = document.body?.dataset.page || "workflow-runner";

if (page === "workflow-designer") {
  initWorkflowDesignerPage();
} else {
  initWorkflowRunnerPage();
}
