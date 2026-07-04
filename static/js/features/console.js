export function createConsole(ctx) {
  const { ui } = ctx;
  const limits = {
    qwenLive: { maxChars: 8000, maxLines: 120 },
    logs: { maxChars: 50000, maxLines: 800 },
  };

  function trimConsoleText(id, text) {
    const limit = limits[id] || { maxChars: 50000, maxLines: 800 };
    let value = String(text || "");
    if (value.length > limit.maxChars) {
      value = `... trimmed ${value.length - limit.maxChars} chars ...\n${value.slice(-limit.maxChars)}`;
    }
    const lines = value.split("\n");
    if (lines.length > limit.maxLines) {
      value = [`... trimmed ${lines.length - limit.maxLines} lines ...`, ...lines.slice(-limit.maxLines)].join("\n");
    }
    return value;
  }

  return {
    append(id, line) {
      const target = ui.el(id);
      if (!target) return;
      if (target.textContent === "No agent output yet.") target.textContent = "";
      target.textContent = trimConsoleText(id, `${target.textContent || ""}${line}\n`);
      target.scrollTop = target.scrollHeight;
    },

    setLiveStatus(id, text) {
      const target = ui.el(id);
      if (!target) return;
      target.textContent = `${text}\n`;
      target.scrollTop = 0;
    },
  };
}
