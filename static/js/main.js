import { initWorkflowDesignerPage } from "./pages/workflow-designer.js?v=20260628-designer-prevnext1";
import { initWorkflowRunnerPage } from "./pages/workflow-runner.js?v=20260628-artifacts3";

const page = document.body?.dataset.page || "workflow-runner";

if (page === "workflow-designer") {
  initWorkflowDesignerPage();
} else {
  initWorkflowRunnerPage();
}
