import { initSharedSidebar } from "./shared/sidebar.js?v=20260704-metadata1";
import { initWorkflowAssetsPage } from "./pages/ai-workflow-assets.js?v=20260704-metadata1";
import { initWorkflowDesignerPage } from "./pages/workflow-designer.js?v=20260704-metadata1";
import { initWorkflowRunnerPage } from "./pages/workflow-runner.js?v=20260704-metadata1";

const page = document.body?.dataset.page || "workflow-runner";
initSharedSidebar();

if (page === "workflow-designer") {
  initWorkflowDesignerPage();
} else if (page === "ai-workflow-assets") {
  initWorkflowAssetsPage();
} else {
  initWorkflowRunnerPage();
}
