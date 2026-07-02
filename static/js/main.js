import { initSharedSidebar } from "./shared/sidebar.js?v=20260702-assets-bugfix3";
import { initWorkflowAssetsPage } from "./pages/ai-workflow-assets.js?v=20260702-assets-bugfix3";
import { initWorkflowDesignerPage } from "./pages/workflow-designer.js?v=20260702-assets-bugfix3";
import { initWorkflowRunnerPage } from "./pages/workflow-runner.js?v=20260702-assets-bugfix3";

const page = document.body?.dataset.page || "workflow-runner";
initSharedSidebar();

if (page === "workflow-designer") {
  initWorkflowDesignerPage();
} else if (page === "ai-workflow-assets") {
  initWorkflowAssetsPage();
} else {
  initWorkflowRunnerPage();
}
