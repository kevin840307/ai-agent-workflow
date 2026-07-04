export function createMessages(ctx) {
  const { api, state, ui } = ctx;

  function limitTail(value, maxChars) {
    const text = String(value || "");
    if (text.length <= maxChars) return text;
    return `... trimmed ${text.length - maxChars} chars ...\n${text.slice(-maxChars)}`;
  }

  function appendLimited(current, next, maxChars) {
    if (!next) return current || "";
    const value = `${current || ""}${next}`;
    return limitTail(value, maxChars);
  }

  function cleanMarker(value) {
    return String(value || "")
      .replace(/[`*_>#|]/g, "")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 180);
  }

  function pushActivityMarker(activity, marker) {
    const text = cleanMarker(marker);
    if (!text || text.length < 3) return;
    const exists = activity.currentWork.some((item) => item.toLowerCase() === text.toLowerCase());
    if (exists) return;
    activity.currentWork.push(text);
    if (activity.currentWork.length > 8) activity.currentWork = activity.currentWork.slice(-8);
  }

  function extractActivityMarkers(activity, text) {
    if (!text) return;
    activity.outputPreview = appendLimited(activity.outputPreview, text, 4000);
    const lines = activity.outputPreview.split(/\r?\n/).slice(-80);
    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line) continue;
      const heading = line.match(/^#{1,4}\s+(.{3,120})$/);
      if (heading) {
        pushActivityMarker(activity, `Working on section: ${heading[1]}`);
        continue;
      }
      const task = line.match(/^(?:#{2,4}\s*)?(TASK-\d{3})\s*:?\s*(.{3,140})$/i);
      if (task) {
        pushActivityMarker(activity, `Planning task ${task[1]}: ${task[2]}`);
        continue;
      }
      const tableTask = line.match(/^\|\s*(TASK-\d{3})\s*\|\s*([^|]{3,140})\|/i);
      if (tableTask) {
        pushActivityMarker(activity, `Planning task ${tableTask[1]}: ${tableTask[2]}`);
        continue;
      }
      const file = line.match(/^FILE\s*:\s*(.+)$/i);
      if (file) {
        pushActivityMarker(activity, `Preparing file: ${file[1]}`);
        continue;
      }
      const content = line.match(/^CONTENT\s*:\s*$/i);
      if (content) {
        pushActivityMarker(activity, "Writing file content");
        continue;
      }
      const status = line.match(/^Status\s*:\s*(.+)$/i);
      if (status) {
        pushActivityMarker(activity, `Status reported: ${status[1]}`);
      }
    }
  }

  function workflowActivityState() {
    if (!state.workflowActivity) {
      state.workflowActivity = {
        runId: null,
        agent: state.defaultAgent || "Agent",
        step: "",
        status: "Starting workflow...",
        thinking: "",
        diagnostics: "",
        generatedChars: 0,
        currentWork: [],
        outputPreview: "",
        renderTimer: null,
      };
    }
    return state.workflowActivity;
  }

  function renderWorkflowActivity() {
    const activity = workflowActivityState();
    const list = ui.byKey("messages");
    if (!list) return;
    list.querySelector(".message.system")?.remove();

    let node = list.querySelector("[data-workflow-activity='true']");
    if (!node) {
      node = document.createElement("div");
      node.className = "message assistant workflow-activity";
      node.dataset.workflowActivity = "true";
      list.appendChild(node);
    }
    node.textContent = "";

    const title = document.createElement("div");
    title.className = "workflow-live-title";
    const spinner = document.createElement("span");
    spinner.className = "workflow-live-spinner";
    spinner.textContent = "●";
    const strong = document.createElement("strong");
    strong.textContent = `${activity.agent || state.defaultAgent || "Agent"} is working`;
    title.appendChild(spinner);
    title.appendChild(strong);

    const meta = document.createElement("div");
    meta.className = "workflow-live-meta";
    meta.textContent = [activity.step ? `Step: ${activity.step}` : "Workflow running", activity.status || "Thinking..."]
      .filter(Boolean)
      .join(" · ");

    node.appendChild(title);
    node.appendChild(meta);

    if (activity.currentWork?.length) {
      const work = document.createElement("div");
      work.className = "workflow-live-work";
      const label = document.createElement("span");
      label.textContent = "What it is doing";
      const listNode = document.createElement("ul");
      activity.currentWork.slice(-5).forEach((item) => {
        const li = document.createElement("li");
        li.textContent = item;
        listNode.appendChild(li);
      });
      work.appendChild(label);
      work.appendChild(listNode);
      node.appendChild(work);
    }

    if (activity.generatedChars > 0) {
      const generated = document.createElement("div");
      generated.className = "workflow-live-note";
      generated.textContent = `Generating artifact output... ${activity.generatedChars.toLocaleString()} chars streamed. Full content will be available in Artifacts.`;
      node.appendChild(generated);
    }

    if (activity.thinking) {
      const thinking = document.createElement("div");
      thinking.className = "workflow-live-thinking";
      const label = document.createElement("span");
      label.textContent = "Live thinking";
      const body = document.createElement("pre");
      body.textContent = activity.thinking;
      thinking.appendChild(label);
      thinking.appendChild(body);
      node.appendChild(thinking);
    }

    if (activity.diagnostics) {
      const diagnostics = document.createElement("div");
      diagnostics.className = "workflow-live-diagnostics";
      const label = document.createElement("span");
      label.textContent = "Diagnostics";
      const body = document.createElement("pre");
      body.textContent = activity.diagnostics;
      diagnostics.appendChild(label);
      diagnostics.appendChild(body);
      node.appendChild(diagnostics);
    }

    list.scrollTop = list.scrollHeight;
  }

  function scheduleWorkflowActivityRender() {
    const activity = workflowActivityState();
    if (activity.renderTimer) return;
    activity.renderTimer = window.setTimeout(() => {
      activity.renderTimer = null;
      renderWorkflowActivity();
    }, 160);
  }

  const messagesFeature = {
    renderMessage(msg) {
      const div = document.createElement("div");
      const askMatch = msg.role !== "user" ? msg.content.match(/^(.+?) asks:\s*/i) : null;
      const isAsk = Boolean(askMatch);
      div.className = `message ${msg.role === "user" ? "user" : "assistant"}${isAsk ? " ask" : ""}`;

      if (isAsk) {
        const agent = askMatch?.[1] || state.defaultAgent || "Agent";
        const title = document.createElement("strong");
        title.textContent = `${agent} asks`;
        const body = document.createElement("div");
        body.textContent = msg.content.replace(/^(.+?) asks:\s*/i, "");
        div.appendChild(title);
        div.appendChild(body);
        return div;
      }

      const status = msg.status && !["completed"].includes(msg.status) ? ` [${msg.status}]` : "";
      const content = document.createElement("div");
      content.textContent = `${msg.content || ""}${status}`;
      div.appendChild(content);
      if (msg.role !== "user" && msg.trace) {
        const trace = document.createElement("div");
        trace.className = "message-trace";
        const bits = [
          msg.trace.agent ? `Agent ${msg.trace.agent}` : "",
          Number.isFinite(msg.trace.duration_ms) ? `${(msg.trace.duration_ms / 1000).toFixed(1)}s` : "",
          Number.isFinite(msg.trace.prompt_chars) ? `Prompt ${msg.trace.prompt_chars} chars` : "",
          msg.trace.session_reused ? "reused session" : "fresh session",
        ].filter(Boolean);
        trace.textContent = bits.join(" · ");
        div.appendChild(trace);
      }
      return div;
    },

    renderEmptyState() {
      const list = ui.byKey("messages");
      if (!list || list.querySelector(".message:not(.system)")) return;
      const empty = list.querySelector(".message.system");
      if (empty) {
        empty.textContent = state.runMode === "chat"
          ? "Chat uses the current project session. Send a question or follow-up."
          : "Describe the next change you want the workflow to make.";
      }
    },

    async load(options = {}) {
      const messages = await api.request(`/api/sessions/${state.activeSessionId}/messages`);
      const visibleMessages = messages.filter((msg) => (
        state.runMode === "chat"
          ? msg.kind === "chat"
          : msg.kind !== "chat"
      ));
      const list = ui.byKey("messages");
      list.innerHTML = "";
      state.lastAskText = "";
      state.workflowActivity = null;

      visibleMessages.forEach((msg) => list.appendChild(messagesFeature.renderMessage(msg)));

      if (!visibleMessages.length) {
        const div = document.createElement("div");
        div.className = "message system";
        div.textContent = state.runMode === "chat"
          ? `Chat uses the current project session. Send a question or follow-up.`
          : "Describe the next change you want the workflow to make.";
        list.appendChild(div);
      }

      const latestRequirement = [...visibleMessages].reverse().find((msg) => msg.role === "user" && (msg.kind || "requirement") === "requirement");
      if (!options.keepDraft) {
        ui.byKey("messageInput").value = options.hydrateInput === false
          ? ""
          : (state.runMode === "chat" ? "" : (latestRequirement?.content || ""));
      }
      ctx.features.composer.autoResize();
      list.scrollTop = list.scrollHeight;
    },

    addLocal(content, role = "user", options = {}) {
      const list = ui.byKey("messages");
      list.querySelector(".message.system")?.remove();
      const div = document.createElement("div");
      div.className = `message ${role === "user" ? "user" : "assistant"}`;
      if (options.temporary) div.dataset.temporary = "true";
      div.textContent = content;
      list.appendChild(div);
      list.scrollTop = list.scrollHeight;
    },

    updateTemporary(content, options = {}) {
      const list = ui.byKey("messages");
      let node = list.querySelector("[data-temporary='true']");
      if (!node) {
        messagesFeature.addLocal("", "assistant", { temporary: true });
        node = list.querySelector("[data-temporary='true']");
      }
      if (!node) return;
      if (options.append) {
        node.textContent = `${node.textContent || ""}${content}`;
      } else {
        node.textContent = content;
      }
      list.scrollTop = list.scrollHeight;
    },

    removeTemporary() {
      ui.byKey("messages").querySelectorAll("[data-temporary='true']").forEach((node) => node.remove());
    },

    resetWorkflowActivity(runId) {
      const previous = state.workflowActivity;
      if (previous?.renderTimer) window.clearTimeout(previous.renderTimer);
      state.workflowActivity = {
        runId,
        agent: state.defaultAgent || "Agent",
        step: "",
        status: "Starting workflow...",
        thinking: "",
        diagnostics: "",
        generatedChars: 0,
        currentWork: [],
        outputPreview: "",
        renderTimer: null,
      };
      renderWorkflowActivity();
    },

    updateWorkflowActivity(event = {}) {
      const activity = workflowActivityState();
      if (event.agent) activity.agent = event.agent;
      if (event.step) activity.step = event.step;
      if (event.message) {
        activity.status = event.message;
        pushActivityMarker(activity, event.message);
      }

      if (event.type === "output" && event.text) {
        const stream = String(event.stream || "display").toLowerCase();
        if (["thinking", "reasoning", "thought"].includes(stream)) {
          activity.thinking = appendLimited(activity.thinking, event.text, 3000);
          activity.status = "Thinking...";
        } else if (["stderr", "error", "diagnostic"].includes(stream)) {
          activity.diagnostics = appendLimited(activity.diagnostics, event.text, 1600);
          activity.status = "Received diagnostics from agent.";
        } else {
          activity.generatedChars += String(event.text).length;
          extractActivityMarkers(activity, event.text);
          activity.status = activity.currentWork?.length ? "Generating structured output..." : "Generating output...";
        }
      }
      scheduleWorkflowActivityRender();
    },

    finishWorkflowActivity(event = {}) {
      const activity = state.workflowActivity;
      if (!activity) return;
      if (activity.renderTimer) {
        window.clearTimeout(activity.renderTimer);
        activity.renderTimer = null;
      }
      const type = event.type || "done";
      const labels = {
        done: "Workflow completed.",
        failed: "Workflow failed.",
        cancelled: "Workflow cancelled.",
        waiting_input: "Waiting for your input.",
        disconnected: "Event stream disconnected.",
      };
      activity.status = labels[type] || "Workflow stopped.";
      renderWorkflowActivity();
    },

    renderAsk(text) {
      const content = text || `${state.defaultAgent || "Agent"} needs more information before continuing.`;
      if (content === state.lastAskText) return;

      const existing = Array.from(ui.byKey("messages").querySelectorAll(".message"))
        .some((node) => node.textContent.includes(content));
      if (existing) {
        state.lastAskText = content;
        ui.byKey("messages").scrollTop = ui.byKey("messages").scrollHeight;
        return;
      }

      state.lastAskText = content;
      const ask = document.createElement("div");
      ask.className = "message assistant ask";
      const title = document.createElement("strong");
      title.textContent = `${state.defaultAgent || "Agent"} asks`;
      const body = document.createElement("div");
      body.textContent = content;
      ask.appendChild(title);
      ask.appendChild(body);
      ui.byKey("messages").appendChild(ask);
      ui.byKey("messages").scrollTop = ui.byKey("messages").scrollHeight;
    },
  };

  return messagesFeature;
}
