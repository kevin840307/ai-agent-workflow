export function createArtifacts(ctx) {
  const { api, state, ui } = ctx;
  const byId = (id) => document.getElementById(id);

  const escapeHtml = (value = "") => String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

  const sanitizeDownloadName = (path = "artifact.md") => {
    const name = String(path || "artifact.md").split(/[\\/]/).filter(Boolean).pop() || "artifact.md";
    return name.replace(/[^a-zA-Z0-9._-]/g, "_");
  };

  const inlineMarkdown = (value = "") => escapeHtml(value)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

  const renderMarkdownTable = (lines) => {
    if (lines.length < 2) return "";
    const split = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
    const headers = split(lines[0]);
    const rows = lines.slice(2).map(split).filter((row) => row.length);
    const head = headers.map((cell) => `<th>${inlineMarkdown(cell)}</th>`).join("");
    const body = rows.map((row) => `<tr>${headers.map((_, index) => `<td>${inlineMarkdown(row[index] || "")}</td>`).join("")}</tr>`).join("");
    return `<div class="markdown-table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  };

  const renderMarkdown = (markdown = "") => {
    const lines = String(markdown || "").replace(/\r\n/g, "\n").split("\n");
    const html = [];
    let paragraph = [];
    let list = [];
    let table = [];

    const flushParagraph = () => {
      if (!paragraph.length) return;
      html.push(`<p>${inlineMarkdown(paragraph.join(" "))}</p>`);
      paragraph = [];
    };
    const flushList = () => {
      if (!list.length) return;
      html.push(`<ul>${list.map((item) => `<li>${inlineMarkdown(item)}</li>`).join("")}</ul>`);
      list = [];
    };
    const flushTable = () => {
      if (!table.length) return;
      html.push(renderMarkdownTable(table));
      table = [];
    };

    for (const line of lines) {
      const trimmed = line.trim();
      const isTableLine = /^\|.+\|$/.test(trimmed);
      if (isTableLine) {
        flushParagraph();
        flushList();
        table.push(trimmed);
        continue;
      }
      flushTable();

      if (!trimmed) {
        flushParagraph();
        flushList();
        continue;
      }
      const heading = trimmed.match(/^(#{1,6})\s+(.+)$/);
      if (heading) {
        flushParagraph();
        flushList();
        const level = Math.min(6, heading[1].length);
        html.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
        continue;
      }
      const bullet = trimmed.match(/^[-*+]\s+(.+)$/);
      if (bullet) {
        flushParagraph();
        list.push(bullet[1]);
        continue;
      }
      paragraph.push(trimmed);
    }
    flushTable();
    flushParagraph();
    flushList();
    return html.join("\n") || '<p class="muted">Empty Markdown file.</p>';
  };

  const stepFilesModal = {
    files: [],
    activeIndex: 0,
    loadToken: 0,
    viewMode: "source",
    lastFocusedElement: null,
  };

  const artifacts = {
    stepArtifactPaths(step = {}) {
      const config = step.config || {};
      const output = config.outputFile || config.filename || "";
      const paths = [
        ...(config.contextArtifacts || []),
        ...(config.dependsOnArtifacts || []),
        ...(config.expectedFiles || []),
        output ? `output/${output}` : "",
        `prompts/${step.key}.md`,
        "input/failure-feedback.md",
      ].filter(Boolean);
      return [...new Set(paths.map((path) => {
        const value = String(path || "").replace(/\\/g, "/");
        if (value.startsWith("output/") || value.startsWith("input/") || value.startsWith("prompts/") || value.startsWith(".workflow/")) return value;
        return `output/${value}`;
      }))];
    },

    artifactsForStep(step = {}, artifactList = state.currentArtifacts) {
      const paths = artifacts.stepArtifactPaths(step);
      const direct = paths
        .map((path) => artifactList.find((artifact) => artifact.path === path))
        .filter(Boolean);
      const key = String(step.key || "").toLowerCase();
      const inferred = artifactList.filter((artifact) => {
        const path = String(artifact.path || "").toLowerCase();
        return key && (path === `prompts/${key}.md` || path.includes(`/${key}`) || path.includes(key.replace(/_/g, "-")));
      });
      return [...new Map([...direct, ...inferred].map((artifact) => [artifact.id, artifact])).values()];
    },

    async load(artifactId) {
      return api.request(`/api/artifacts/${encodeURIComponent(artifactId)}`);
    },

    format(data = {}) {
      return `# ${data.path || "Artifact"}\n\n${data.content || ""}`;
    },

    async preview(artifactId, { activateArtifactsTab = false } = {}) {
      const data = await artifacts.load(artifactId);
      const content = artifacts.format(data);

      if (ui.byKey("artifactContent")) {
        ui.byKey("artifactContent").textContent = content;
        ui.byKey("artifactContent").scrollTop = 0;
      }
      state.selectedStepArtifactId = artifactId;
      if (activateArtifactsTab) ctx.features.layout.activateTab("artifactsPanel");
    },

    renderStepPreview(_run, step) {
      state.selectedStepKey = step?.key || null;
    },

    ensureStepFilesModal() {
      let backdrop = byId("stepFilesModalBackdrop");
      if (!backdrop) {
        backdrop = document.createElement("div");
        backdrop.id = "stepFilesModalBackdrop";
        backdrop.className = "step-files-modal-backdrop";
        backdrop.hidden = true;
        backdrop.innerHTML = `
          <div class="step-files-modal-card" role="dialog" aria-modal="true" aria-labelledby="stepFilesModalTitle">
            <div class="step-files-modal-head">
              <div class="step-files-modal-title-wrap">
                <span>Step Files</span>
                <h2 id="stepFilesModalTitle">Files</h2>
                <p id="stepFilesModalMeta"></p>
              </div>
              <button id="stepFilesModalClose" class="step-files-modal-close" type="button" aria-label="Close files dialog">×</button>
            </div>
            <div id="stepFilesTabs" class="step-files-tabs" role="tablist" aria-label="Step files"></div>
            <div class="step-files-active-head">
              <strong id="stepFilesActiveName">Select a file</strong>
              <div class="step-files-actions">
                <button id="stepFilesOpenArtifactTab" class="mini-button" type="button">Open in Artifacts</button>
                <button id="stepFilesPreviewToggle" class="mini-button" type="button">Preview</button>
                <button id="stepFilesCopy" class="mini-button" type="button">Copy</button>
                <button id="stepFilesDownload" class="mini-button" type="button">Download</button>
              </div>
            </div>
            <pre id="stepFilesContent" class="step-files-content">Loading...</pre>
            <div id="stepFilesMarkdownPreview" class="step-files-markdown-preview" hidden></div>
          </div>
        `;
        document.body.appendChild(backdrop);

        const closeButton = byId("stepFilesModalClose");
        closeButton.onclick = () => artifacts.closeStepFilesModal();
        backdrop.addEventListener("click", (event) => {
          if (event.target === backdrop) artifacts.closeStepFilesModal();
        });
        document.addEventListener("keydown", (event) => {
          if (backdrop.hidden) return;
          if (event.key === "Escape") {
            event.preventDefault();
            artifacts.closeStepFilesModal();
          }
        });
      }

      return {
        backdrop,
        title: byId("stepFilesModalTitle"),
        meta: byId("stepFilesModalMeta"),
        tabs: byId("stepFilesTabs"),
        activeName: byId("stepFilesActiveName"),
        content: byId("stepFilesContent"),
        markdownPreview: byId("stepFilesMarkdownPreview"),
        openArtifactTab: byId("stepFilesOpenArtifactTab"),
        previewToggle: byId("stepFilesPreviewToggle"),
        copy: byId("stepFilesCopy"),
        download: byId("stepFilesDownload"),
        close: byId("stepFilesModalClose"),
      };
    },

    closeStepFilesModal() {
      const els = artifacts.ensureStepFilesModal();
      els.backdrop.hidden = true;
      document.body.classList.remove("artifact-modal-open");
      if (stepFilesModal.lastFocusedElement?.focus) stepFilesModal.lastFocusedElement.focus();
      stepFilesModal.lastFocusedElement = null;
    },

    setStepFilesModalActive(index) {
      const els = artifacts.ensureStepFilesModal();
      const file = stepFilesModal.files[index];
      if (!file) return;

      stepFilesModal.activeIndex = index;
      els.tabs.querySelectorAll(".step-files-tab").forEach((tab, tabIndex) => {
        tab.classList.toggle("active", tabIndex === index);
        tab.setAttribute("aria-selected", tabIndex === index ? "true" : "false");
      });
      els.activeName.textContent = file.path || "Artifact";
      artifacts.renderStepFileContent(file);
      if (els.openArtifactTab) {
        els.openArtifactTab.disabled = !file.id;
        els.openArtifactTab.onclick = () => file.id && artifacts.open(file.id);
      }
      if (els.copy) {
        els.copy.disabled = Boolean(file.error);
        els.copy.textContent = "Copy";
        els.copy.classList.remove("active");
        els.copy.onclick = () => artifacts.copyStepFile(file);
      }
      if (els.download) {
        els.download.disabled = Boolean(file.error);
        els.download.onclick = () => artifacts.downloadStepFile(file);
      }
      if (els.previewToggle) {
        els.previewToggle.disabled = Boolean(file.error);
        els.previewToggle.onclick = () => {
          stepFilesModal.viewMode = stepFilesModal.viewMode === "preview" ? "source" : "preview";
          artifacts.renderStepFileContent(file);
        };
      }
      state.selectedStepArtifactId = file.id || null;
    },

    renderStepFileContent(file) {
      const els = artifacts.ensureStepFilesModal();
      const content = file.error
        ? `Unable to load ${file.path}:\n\n${file.error}`
        : (file.content || "");
      const previewMode = stepFilesModal.viewMode === "preview" && !file.error;
      els.content.hidden = previewMode;
      if (els.markdownPreview) {
        els.markdownPreview.hidden = !previewMode;
        els.markdownPreview.innerHTML = previewMode ? renderMarkdown(content) : "";
        els.markdownPreview.scrollTop = 0;
      }
      els.content.textContent = content;
      els.content.scrollTop = 0;
      if (els.previewToggle) {
        els.previewToggle.textContent = previewMode ? "Source" : "Preview";
        els.previewToggle.classList.toggle("active", previewMode);
      }
    },

    async copyStepFile(file) {
      if (!file || file.error) return;
      const els = artifacts.ensureStepFilesModal();
      const content = file.content || "";
      try {
        if (navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(content);
        } else {
          const textarea = document.createElement("textarea");
          textarea.value = content;
          textarea.setAttribute("readonly", "");
          textarea.style.position = "fixed";
          textarea.style.opacity = "0";
          document.body.appendChild(textarea);
          textarea.select();
          document.execCommand("copy");
          textarea.remove();
        }
        if (els.copy) {
          els.copy.textContent = "Copied";
          els.copy.classList.add("active");
          window.setTimeout(() => {
            if (!els.backdrop.hidden && stepFilesModal.files[stepFilesModal.activeIndex] === file) {
              els.copy.textContent = "Copy";
              els.copy.classList.remove("active");
            }
          }, 1200);
        }
      } catch (err) {
        console.warn("Failed to copy step file", err);
        if (els.copy) els.copy.textContent = "Copy failed";
      }
    },

    downloadStepFile(file) {
      if (!file || file.error) return;
      const blob = new Blob([file.content || ""], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = sanitizeDownloadName(file.path || "artifact.md");
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    },

    async openStepFilesModal(run, step) {
      const related = artifacts.artifactsForStep(step, run.artifacts || []);
      if (!related.length) return;

      const els = artifacts.ensureStepFilesModal();
      const token = stepFilesModal.loadToken + 1;
      stepFilesModal.loadToken = token;
      stepFilesModal.files = [];
      stepFilesModal.activeIndex = 0;
      stepFilesModal.lastFocusedElement = document.activeElement;

      els.title.textContent = step.title || step.key || "Step Files";
      els.meta.textContent = `${related.length} file${related.length > 1 ? "s" : ""}`;
      els.tabs.innerHTML = "";
      els.activeName.textContent = "Loading files...";
      els.content.textContent = "Loading files...";
      if (els.openArtifactTab) els.openArtifactTab.disabled = true;
      if (els.previewToggle) {
        els.previewToggle.disabled = true;
        els.previewToggle.textContent = "Preview";
        els.previewToggle.classList.remove("active");
      }
      if (els.copy) {
        els.copy.disabled = true;
        els.copy.textContent = "Copy";
        els.copy.classList.remove("active");
      }
      if (els.download) els.download.disabled = true;
      if (els.markdownPreview) {
        els.markdownPreview.hidden = true;
        els.markdownPreview.innerHTML = "";
      }
      stepFilesModal.viewMode = "source";
      els.backdrop.hidden = false;
      document.body.classList.add("artifact-modal-open");

      const loaded = await Promise.all(related.map(async (artifact) => {
        try {
          const data = await artifacts.load(artifact.id);
          return {
            id: artifact.id,
            path: data.path || artifact.path,
            content: data.content || "",
          };
        } catch (err) {
          return {
            id: artifact.id,
            path: artifact.path,
            content: "",
            error: err.message,
          };
        }
      }));

      if (stepFilesModal.loadToken !== token || els.backdrop.hidden) return;
      stepFilesModal.files = loaded;
      els.tabs.innerHTML = "";

      loaded.forEach((file, index) => {
        const tab = document.createElement("button");
        tab.type = "button";
        tab.className = "step-files-tab";
        tab.role = "tab";
        tab.title = file.path;
        tab.textContent = file.path;
        tab.onclick = () => artifacts.setStepFilesModalActive(index);
        els.tabs.appendChild(tab);
      });

      const preferredIndex = Math.max(0, loaded.findIndex((file) => file.id === state.selectedStepArtifactId));
      artifacts.setStepFilesModalActive(preferredIndex);
      els.close.focus();
    },

    priority(path = "") {
      const name = path.toLowerCase();
      if (name.endsWith("spec.md")) return 1;
      if (name.endsWith("todo.md")) return 2;
      if (name.includes("test") || name.includes("result")) return 3;
      if (name.includes("review")) return 4;
      if (name.startsWith("prompts/")) return 8;
      if (name.includes("log")) return 9;
      return 6;
    },

    render(artifactList) {
      state.currentArtifacts = [...artifactList].sort((a, b) => {
        const pa = artifacts.priority(a.path || "");
        const pb = artifacts.priority(b.path || "");
        if (pa !== pb) return pa - pb;
        return String(a.path || "").localeCompare(String(b.path || ""));
      });
      artifacts.renderList();
    },

    renderList() {
      const target = ui.byKey("artifacts");
      if (!target) return;
      const query = (ui.byKey("artifactSearch")?.value || "").trim().toLowerCase();
      target.innerHTML = "";

      state.currentArtifacts
        .filter((artifact) => !query || String(artifact.path || "").toLowerCase().includes(query))
        .forEach((artifact) => {
          const button = document.createElement("button");
          const priority = artifacts.priority(artifact.path || "") <= 4;
          button.className = `artifact-button${priority ? " priority" : ""}`;
          button.textContent = artifact.path;
          button.title = artifact.path;
          button.onclick = () => artifacts.open(artifact.id);
          target.appendChild(button);
        });

      if (!target.children.length) {
        const empty = document.createElement("div");
        empty.className = "message system";
        empty.textContent = query ? "No artifacts matched your search." : "No artifacts yet.";
        target.appendChild(empty);
      }
    },

    async open(artifactId) {
      await artifacts.preview(artifactId, { activateArtifactsTab: true, updateStepPreview: false });
    },
  };

  return artifacts;
}
