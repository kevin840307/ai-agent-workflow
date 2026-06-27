export function createConsole(ctx) {
  const { ui } = ctx;

  return {
    append(id, line) {
      const target = ui.el(id);
      if (!target) return;
      if (target.textContent === "No Qwen output yet.") target.textContent = "";
      target.textContent += `${line}\n`;
      target.scrollTop = target.scrollHeight;
    },
  };
}
