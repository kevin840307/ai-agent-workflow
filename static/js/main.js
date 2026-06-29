import { initWorkflowDesignerPage } from "./pages/workflow-designer.js?v=20260629-static-modules9";
import { initWorkflowRunnerPage } from "./pages/workflow-runner.js?v=20260629-static-modules9";

const page = document.body?.dataset.page || "workflow-runner";

if (page === "workflow-designer") {
  initWorkflowDesignerPage();
} else {
  initWorkflowRunnerPage();
}
