export function renderMarkdownPreview(markdown, enabled) {
  if (!enabled) return `<div class="designer-empty-state">Preview is available for Markdown and text assets.</div>`;
  const text = String(markdown || "").trim();
  if (!text) return `<div class="designer-empty-state">No Markdown content to preview.</div>`;
  const html = [];
  let inCode = false;
  let inList = false;
  text.split(/\r?\n/).forEach((line) => {
    if (line.trim().startsWith("```")) {
      if (inList) {
        html.push("</ul>");
        inList = false;
      }
      html.push(inCode ? "</code></pre>" : "<pre><code>");
      inCode = !inCode;
      return;
    }
    if (inCode) {
      html.push(`${escapeHtml(line)}\n`);
      return;
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      if (inList) {
        html.push("</ul>");
        inList = false;
      }
      const level = heading[1].length;
      html.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      return;
    }
    const item = /^[-*]\s+(.*)$/.exec(line);
    if (item) {
      if (!inList) {
        html.push("<ul>");
        inList = true;
      }
      html.push(`<li>${inlineMarkdown(item[1])}</li>`);
      return;
    }
    if (inList) {
      html.push("</ul>");
      inList = false;
    }
    html.push(line.trim() ? `<p>${inlineMarkdown(line)}</p>` : "");
  });
  if (inCode) html.push("</code></pre>");
  if (inList) html.push("</ul>");
  return html.join("");
}

function inlineMarkdown(value) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}
