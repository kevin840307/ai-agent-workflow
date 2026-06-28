export function createArtifacts(ctx) {
  const { api, state, ui } = ctx;
  const byId = (id) => document.getElementById(id);

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

    async preview(artifactId, { activateArtifactsTab = false } = {}) {
      const data = await api.request(`/api/artifacts/${encodeURIComponent(artifactId)}`);
      const content = `# ${data.path}\n\n${data.content}`;
      const stepContent = byId("stepArtifactContent");
      const stepTitle = byId("stepArtifactTitle");
      const openButton = byId("openArtifactTab");
      if (stepContent) {
        stepContent.textContent = content;
        stepContent.scrollTop = 0;
      }
      if (stepTitle) stepTitle.textContent = data.path;
      if (openButton) {
        openButton.disabled = false;
        openButton.onclick = () => artifacts.open(artifactId);
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

      if (!step) {
        title.textContent = "Select a step";
        content.textContent = "Click a step to inspect its prompt, output, and related artifacts.";
        if (openButton) openButton.disabled = true;
        return;
      }

      const related = artifacts.artifactsForStep(step, run.artifacts || []);
      title.textContent = step.title || step.key;

      if (!related.length) {
        content.textContent = "No artifacts have been created for this step yet.";
        if (openButton) openButton.disabled = true;
        const empty = document.createElement("div");
        empty.className = "step-artifact-empty";
        empty.textContent = "No files yet";
        list.appendChild(empty);
        return;
      }

      related.forEach((artifact, index) => {
        const button = document.createElement("button");
        button.className = `step-artifact-chip${index === 0 ? " active" : ""}`;
        button.textContent = artifact.path.replace(/^output\//, "");
        button.title = artifact.path;
        button.onclick = async () => {
          list.querySelectorAll(".step-artifact-chip").forEach((chip) => chip.classList.remove("active"));
          button.classList.add("active");
          await artifacts.preview(artifact.id);
        };
        list.appendChild(button);
      });

      artifacts.preview((related.find((artifact) => artifact.id === state.selectedStepArtifactId) || related[0]).id);
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
      await artifacts.preview(artifactId, { activateArtifactsTab: true });
    },
  };

  return artifacts;
}
