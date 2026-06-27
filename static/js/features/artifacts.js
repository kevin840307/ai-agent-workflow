export function createArtifacts(ctx) {
  const { api, state, ui } = ctx;

  const artifacts = {
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
      const data = await api.request(`/api/artifacts/${encodeURIComponent(artifactId)}`);
      ui.byKey("artifactContent").textContent = `# ${data.path}\n\n${data.content}`;
      ui.byKey("artifactContent").scrollTop = 0;
      ctx.features.layout.activateTab("artifactsPanel");
    },
  };

  return artifacts;
}
