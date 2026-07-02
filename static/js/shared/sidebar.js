import { LocalStore, StorageKeys } from "../core/storage.js?v=20260702-assets-bugfix3";

function applyActiveNav() {
  const page = document.body?.dataset.page || "";
  document.querySelectorAll(".project-nav-link, .designer-nav-link").forEach((link) => {
    const href = link.getAttribute("href") || "";
    const active = page === "workflow-designer"
      ? href.includes("workflow-designer")
      : page === "ai-workflow-assets"
        ? href.includes("ai-workflow-assets")
        : href === "/" || href.endsWith("/index.html");
    link.classList.toggle("active", active);
  });
}

function updateToggle(collapsed) {
  const button = document.getElementById("toggleProjects");
  if (!button) return;
  button.classList.toggle("active", collapsed);
  button.textContent = collapsed ? ">" : "<";
  button.title = collapsed ? "Expand sidebar" : "Collapse sidebar";
  button.setAttribute("aria-label", button.title);
  button.setAttribute("aria-pressed", String(collapsed));
}

export function initSharedSidebar() {
  applyActiveNav();
  const collapsed = LocalStore.getBoolean(StorageKeys.projectsCollapsed, false);
  document.body.classList.toggle("projects-collapsed", collapsed);
  updateToggle(collapsed);

  const button = document.getElementById("toggleProjects");
  if (button && !button.dataset.sharedSidebarBound) {
    button.dataset.sharedSidebarBound = "true";
    button.addEventListener("click", () => {
      const next = !document.body.classList.contains("projects-collapsed");
      document.body.classList.toggle("projects-collapsed", next);
      LocalStore.setBoolean(StorageKeys.projectsCollapsed, next);
      updateToggle(next);
    });
  }
}
