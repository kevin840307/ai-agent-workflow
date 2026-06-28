export function createArtifacts(ctx) {
  const { api, state, ui } = ctx;
  const byId = (id) => document.getElementById(id);

  const stepFilesModal = {
    files: [],
    activeIndex: 0,
    loadToken: 0,
    lastFocusedElement: null,
  };

  const artifacts = {
    stepArtifactPaths(step = {}) {
      const config = step.config || {};
      const output = config.outputFile || config.filename || "";
      const byKey = {
        prepare_project: ["output/architecture.md", "prompts/prepare_project.md"],
        generate_spec: ["output/spec.md", "output/spec.raw.md", "prompts/generate_spec.md", "prompts/repair_spec.md"],
        validate_spec: ["output/spec.md", "output/spec.raw.md", "prompts/repair_spec.md", "input/failure-feedback.md"],
        review_spec: ["output/spec-review.md", "prompts/review_spec.md"],
        spec_gate: ["output/spec-review.md"],
        generate_todo: ["output/todo.md", "output/todo.raw.md", "prompts/generate_todo.md", "prompts/repair_todo.md"],
        validate_todo: ["output/todo.md", "output/todo.raw.md", "prompts/repair_todo.md", "input/failure-feedback.md"],
        review_todo: ["output/todo-review.md", "prompts/review_todo.md"],
        todo_gate: ["output/todo-review.md"],
        generate_tests: ["output/test-plan.md", "prompts/generate_tests.md"],
        build: ["output/build-result.md", "prompts/build.md", "output/test-result.md"],
        run_test: ["output/test-result.md", "input/failure-feedback.md"],
        final_review: ["output/final-review.md", "prompts/final_review.md", "output/test-result.md"],
        final_gate: ["output/final-review.md"],
      };
      const paths = [
        ...(byKey[step.key] || []),
        output ? `output/${output}` : "",
        `prompts/${step.key}.md`,
      ].filter(Boolean);
      return [...new Set(paths)];
    },

    artifactsForStep(step = {}, artifactList = state.currentArtifacts) {
      const paths = artifacts.stepArtifactPaths(step);
      return paths
        .map((path) => artifactList.find((artifact) => artifact.path === path))
        .filter(Boolean);
    },

    async load(artifactId) {
      return api.request(`/api/artifacts/${encodeURIComponent(artifactId)}`);
    },

    format(data = {}) {
      return `# ${data.path || "Artifact"}\n\n${data.content || ""}`;
    },

    async preview(artifactId, { activateArtifactsTab = false, updateStepPreview = true } = {}) {
      const data = await artifacts.load(artifactId);
      const content = artifacts.format(data);

      if (updateStepPreview) {
        const stepContent = byId("stepArtifactContent");
        const stepTitle = byId("stepArtifactTitle");
        if (stepContent) {
          stepContent.textContent = content;
          stepContent.scrollTop = 0;
        }
        if (stepTitle) stepTitle.textContent = data.path;
      }

      if (ui.byKey("artifactContent")) {
        ui.byKey("artifactContent").textContent = content;
        ui.byKey("artifactContent").scrollTop = 0;
      }
      state.selectedStepArtifactId = artifactId;
      if (activateArtifactsTab) ctx.features.layout.activateTab("artifactsPanel");
    },

    renderStepPreview(run, step) {
      const list = byId("stepArtifactList");
      const title = byId("stepArtifactTitle");
      const content = byId("stepArtifactContent");
      const openButton = byId("openArtifactTab");
      if (!list || !title || !content) return;

      state.selectedStepKey = step?.key || null;
      list.innerHTML = "";
      list.hidden = true;

      if (!step) {
        title.textContent = "Select a step";
        content.textContent = "Click a step, then use Step Files to inspect its files.";
        if (openButton) {
          openButton.textContent = "Step Files";
          openButton.disabled = true;
          openButton.onclick = null;
        }
        return;
      }

      const related = artifacts.artifactsForStep(step, run.artifacts || []);
      title.textContent = step.title || step.key;

      if (!related.length) {
        content.textContent = "No files have been created for this step yet.";
        if (openButton) {
          openButton.textContent = "Step Files";
          openButton.disabled = true;
          openButton.onclick = null;
        }
        return;
      }

      if (openButton) {
        openButton.textContent = `Step Files ${related.length}`;
        openButton.disabled = false;
        openButton.onclick = () => artifacts.openStepFilesModal(run, step);
      }

      content.textContent = "Loading preview...";
      const previewArtifact = related.find((artifact) => artifact.id === state.selectedStepArtifactId) || related[0];
      const selectedStepKey = step.key;
      artifacts.load(previewArtifact.id)
        .then((data) => {
          if (state.selectedStepKey !== selectedStepKey) return;
          title.textContent = step.title || step.key;
          content.textContent = artifacts.format(data);
          content.scrollTop = 0;
          state.selectedStepArtifactId = previewArtifact.id;
        })
        .catch((err) => {
          if (state.selectedStepKey !== selectedStepKey) return;
          content.textContent = `Unable to load preview: ${err.message}`;
        });
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
              <button id="stepFilesOpenArtifactTab" class="mini-button" type="button">Open in Artifacts</button>
            </div>
            <pre id="stepFilesContent" class="step-files-content">Loading...</pre>
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
        openArtifactTab: byId("stepFilesOpenArtifactTab"),
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
      els.content.textContent = file.error
        ? `Unable to load ${file.path}:\n\n${file.error}`
        : (file.content || "");
      els.content.scrollTop = 0;
      if (els.openArtifactTab) {
        els.openArtifactTab.disabled = !file.id;
        els.openArtifactTab.onclick = () => file.id && artifacts.open(file.id);
      }
      state.selectedStepArtifactId = file.id || null;
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
