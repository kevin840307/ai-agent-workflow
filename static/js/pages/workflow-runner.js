import { createAppContext } from "../core/context.js?v=20260628-step-files-preview1";
import { createArtifacts } from "../features/artifacts.js?v=20260628-step-files-preview1";
import { createChat } from "../features/chat.js?v=20260628-step-files-preview1";
import { createComposer } from "../features/composer.js?v=20260628-step-files-preview1";
import { createConfig } from "../features/config.js?v=20260628-step-files-preview1";
import { createConsole } from "../features/console.js?v=20260628-step-files-preview1";
import { createEvents } from "../features/events.js?v=20260628-step-files-preview1";
import { createEventStream } from "../features/event-stream.js?v=20260628-step-files-preview1";
import { createInteractions } from "../features/interactions.js?v=20260628-step-files-preview1";
import { createLayout } from "../features/layout.js?v=20260628-step-files-preview1";
import { createMessages } from "../features/messages.js?v=20260628-step-files-preview1";
import { createModal } from "../features/modal.js?v=20260628-step-files-preview1";
import { createRequirements } from "../features/requirements.js?v=20260628-step-files-preview1";
import { createRuns } from "../features/runs.js?v=20260628-security-enum-preview1";
import { createSessions } from "../features/sessions.js?v=20260628-reset1";
import { createWorkflows } from "../features/workflows.js?v=20260628-security-enum-preview1";
import { createWorkflowNotification } from "../features/workflow-notification.js?v=20260628-step-files-preview1";

function registerWorkflowRunnerFeatures(ctx) {
  ctx.features.layout = createLayout(ctx);
  ctx.features.modal = createModal(ctx);
  ctx.features.chat = createChat(ctx);
  ctx.features.composer = createComposer(ctx);
  ctx.features.console = createConsole(ctx);
  ctx.features.messages = createMessages(ctx);
  ctx.features.artifacts = createArtifacts(ctx);
  ctx.features.interactions = createInteractions(ctx);
  ctx.features.runs = createRuns(ctx);
  ctx.features.workflowNotification = createWorkflowNotification(ctx);
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

  ctx.features.modal.bind();
  ctx.features.events.bind();
  ctx.features.layout.restorePreferences();
  ctx.features.config.load().catch((err) => {
    ctx.ui.byKey("qwenMeta").textContent = err.message;
  });
  ctx.features.workflows.load().catch((err) => {
    ctx.ui.byKey("runMeta").textContent = err.message;
  });
  ctx.features.sessions.load().catch((err) => {
    ctx.ui.byKey("runMeta").textContent = err.message;
    ctx.ui.byKey("runStatusMeta").textContent = "Load failed";
  });
  ctx.features.composer.autoResize();
  ctx.features.chat.setMode("workflow");
  ctx.features.composer.updateModeLabel();

  return ctx;
}
