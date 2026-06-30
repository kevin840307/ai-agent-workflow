import { initSharedSidebar } from "./shared/sidebar.js?v=20260701-step-actions1";
import { initWorkflowDesignerPage } from "./pages/workflow-designer.js?v=20260701-step-actions1";
import { initWorkflowRunnerPage } from "./pages/workflow-runner.js?v=20260701-step-actions1";

const page = document.body?.dataset.page || "workflow-runner";
initSharedSidebar();

if (page === "workflow-designer") {
  initWorkflowDesignerPage();
} else {
  initWorkflowRunnerPage();
}
