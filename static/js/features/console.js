export function createConsole(ctx) {
  const { ui } = ctx;
  const limits = {
    qwenLive: { maxBufferedLines: 1200, renderLines: 360 },
    logs: { maxBufferedLines: 6000, renderLines: 900 },
  };
  const buffers = new Map();
  const pending = new Map();
  let flushTimer = null;

  function config(id) {
    return limits[id] || { maxBufferedLines: 2500, renderLines: 600 };
  }

  function trimConsoleText(id, text) {
    const { maxBufferedLines } = config(id);
    return String(text || "").split("\n").slice(-maxBufferedLines).join("\n");
  }

  function isNearBottom(target) {
    return target.scrollHeight - target.scrollTop - target.clientHeight < 72;
  }

  function existingLines(id, target) {
    if (buffers.has(id)) return buffers.get(id);
    const initial = trimConsoleText(id, target?.textContent || "");
    const rows = initial ? initial.split("\n") : [];
    buffers.set(id, rows);
    return rows;
  }

  function render(id, target, { forceTop = false } = {}) {
    const rows = buffers.get(id) || [];
    const { renderLines } = config(id);
    const hidden = Math.max(0, rows.length - renderLines);
    const visible = rows.slice(-renderLines);
    target.textContent = hidden
      ? [`... ${hidden} earlier lines kept outside the DOM ...`, ...visible].join("\n")
      : visible.join("\n");
    target.dataset.bufferedLines = String(rows.length);
    target.dataset.hiddenLines = String(hidden);
    if (forceTop) target.scrollTop = 0;
  }

  function flush() {
    flushTimer = null;
    pending.forEach((newRows, id) => {
      const target = ui.el(id);
      if (!target || !newRows.length) return;
      const follow = isNearBottom(target);
      const rows = existingLines(id, target);
      if (rows.length === 1 && rows[0] === "No agent output yet.") rows.length = 0;
      rows.push(...newRows);
      const { maxBufferedLines } = config(id);
      if (rows.length > maxBufferedLines) rows.splice(0, rows.length - maxBufferedLines);
      render(id, target);
      if (follow) target.scrollTop = target.scrollHeight;
      else target.dataset.pendingLines = String(Number(target.dataset.pendingLines || 0) + newRows.length);
    });
    pending.clear();
  }

  function scheduleFlush() {
    if (flushTimer) return;
    flushTimer = window.setTimeout(flush, 80);
  }

  return {
    append(id, line) {
      if (!ui.el(id)) return;
      const rows = pending.get(id) || [];
      rows.push(String(line ?? ""));
      pending.set(id, rows);
      scheduleFlush();
    },

    setLiveStatus(id, text) {
      const target = ui.el(id);
      if (!target) return;
      pending.delete(id);
      buffers.set(id, String(text ?? "").split("\n"));
      target.dataset.pendingLines = "0";
      render(id, target, { forceTop: true });
    },

    markFollowing(id) {
      const target = ui.el(id);
      if (!target) return;
      target.dataset.pendingLines = "0";
      target.scrollTop = target.scrollHeight;
    },

    flush,
  };
}
