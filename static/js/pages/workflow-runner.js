import { createAppContext } from "../core/context.js?v=20260712-ui-v22";
import { createArtifacts } from "../features/artifacts.js?v=20260712-ui-v22";
import { createChat } from "../features/chat.js?v=20260712-ui-v22";
import { createComposer } from "../features/composer.js?v=20260712-ui-v22";
import { createConfig } from "../features/config.js?v=20260712-ui-v22";
import { createConsole } from "../features/console.js?v=20260712-ui-v22";
import { createEvents } from "../features/events.js?v=20260712-ui-v22";
import { createDiagnostics } from "../features/diagnostics.js?v=20260712-ui-v22";
import { createSetup } from "../features/setup.js?v=20260712-ui-v22";
import { createProjectProfile } from "../features/project-profile.js?v=20260712-ui-v22";
import { createOptimization } from "../features/optimization.js?v=20260712-ui-v22";
import { createPatchReview } from "../features/patch-review.js?v=20260712-ui-v22";
import { createEventStream } from "../features/event-stream.js?v=20260712-ui-v22";
import { createInteractions } from "../features/interactions.js?v=20260712-ui-v22";
import { createLayout } from "../features/layout.js?v=20260712-ui-v22";
import { createMessages } from "../features/messages.js?v=20260712-ui-v22";
import { createModal } from "../features/modal.js?v=20260712-ui-v22";
import { createRequirements } from "../features/requirements.js?v=20260712-ui-v22";
import { createRuns } from "../features/runs.js?v=20260712-ui-v22";
import { createSessions } from "../features/sessions.js?v=20260712-ui-v22";
import { createWorkflows } from "../features/workflows.js?v=20260712-ui-v22";

function registerWorkflowRunnerFeatures(ctx) {
  ctx.features.layout = createLayout(ctx);
  ctx.features.modal = createModal(ctx);
  ctx.features.chat = createChat(ctx);
  ctx.features.composer = createComposer(ctx);
  ctx.features.console = createConsole(ctx);
  ctx.features.diagnostics = createDiagnostics(ctx);
  ctx.features.setup = createSetup(ctx);
  ctx.features.projectProfile = createProjectProfile(ctx);
  ctx.features.optimization = createOptimization(ctx);
  ctx.features.messages = createMessages(ctx);
  ctx.features.artifacts = createArtifacts(ctx);
  ctx.features.interactions = createInteractions(ctx);
  ctx.features.patchReview = createPatchReview(ctx);
  ctx.features.runs = createRuns(ctx);
  ctx.features.eventStream = createEventStream(ctx);
  ctx.features.sessions = createSessions(ctx);
  ctx.features.requirements = createRequirements(ctx);
  ctx.features.workflows = createWorkflows(ctx);
  ctx.features.config = createConfig(ctx);
  ctx.features.events = createEvents(ctx);
  return ctx;
}

export function initWorkflowRunnerPage() {
  const ctx = registerWorkflowRunnerFeatures(createAppContext());

  const thinkingSelect = ctx.ui.byKey("thinkingLevel");
  if (thinkingSelect) thinkingSelect.value = ctx.state.thinkingLevel || "medium";

  ctx.features.modal.bind();
  ctx.features.events.bind();
  ctx.features.layout.restorePreferences();
  ctx.features.config.load().catch((err) => {
    ctx.ui.byKey("qwenMeta").textContent = err.message;
  });
  ctx.features.workflows.load().catch((err) => {
    ctx.ui.byKey("runMeta").textContent = err.message;
  });
  ctx.features.setup.check().catch(() => null);
  ctx.features.setup.startConnectivityMonitor();
  ctx.features.sessions.load().catch((err) => {
    ctx.ui.byKey("runMeta").textContent = err.message;
    ctx.ui.byKey("runStatusMeta").textContent = "Load failed";
  });
  ctx.features.composer.autoResize();
  ctx.features.chat.setMode("workflow");
  ctx.features.composer.updateModeLabel();

  return ctx;
}
