import { initWorkflowDesignerPage } from "./pages/workflow-designer.js";
import { initWorkflowRunnerPage } from "./pages/workflow-runner.js";

const page = document.body?.dataset.page || "workflow-runner";

if (page === "workflow-designer") {
  initWorkflowDesignerPage();
} else {
  initWorkflowRunnerPage();
}
