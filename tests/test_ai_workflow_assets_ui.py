from __future__ import annotations

import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parents[1]


class AiWorkflowAssetsUiTests(unittest.TestCase):
    def test_assets_page_route_is_available(self) -> None:
        with TestClient(app) as client:
            response = client.get("/ai-workflow-assets")
        self.assertEqual(response.status_code, 200)
        self.assertIn("AI Workflow Assets", response.text)
        self.assertIn("designerAssetScope", response.text)
        self.assertIn("designerAssetType", response.text)

    def test_asset_manager_filters_scope_and_type_instead_of_only_syncing_inputs(self) -> None:
        source = (ROOT / "static/js/pages/ai-workflow-assets/asset-manager.js").read_text(encoding="utf-8")
        for marker in [
            "function handleFilterChange()",
            "function filteredAssets()",
            "item.scope === scope && item.type === type",
            "Project scope requires a Project Path",
            "designerAssetSummary",
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, source)

    def test_navigation_links_include_assets_page(self) -> None:
        for rel_path in ["static/index.html", "static/workflow-designer.html", "static/ai-workflow-assets.html"]:
            with self.subTest(rel_path=rel_path):
                self.assertIn("/ai-workflow-assets", (ROOT / rel_path).read_text(encoding="utf-8"))

    def test_workflow_designer_uses_short_assets_link_and_unified_function_ui(self) -> None:
        html = (ROOT / "static/workflow-designer.html").read_text(encoding="utf-8")
        settings = (ROOT / "static/js/pages/workflow-designer/step-settings-renderer.js").read_text(encoding="utf-8")

        self.assertNotIn("Open Assets Library", html)
        self.assertIn("/ai-workflow-assets", html)
        self.assertIn("Python Functions", settings)
        self.assertIn('data-step-field="functionsText"', settings)
        self.assertIn("Python functions moved to Basic", settings)

    def test_assets_page_editor_keeps_save_actions_visible(self) -> None:
        html = (ROOT / "static/ai-workflow-assets.html").read_text(encoding="utf-8")
        css = (ROOT / "static/css/workflow-designer.css").read_text(encoding="utf-8")
        manager = (ROOT / "static/js/pages/ai-workflow-assets/asset-manager.js").read_text(encoding="utf-8")
        preview = (ROOT / "static/js/pages/ai-workflow-assets/markdown-preview.js").read_text(encoding="utf-8")

        self.assertIn("designerAssetPreview", html)
        self.assertIn("designer-asset-editor-tabs", html)
        self.assertIn("renderMarkdownPreview", manager)
        self.assertIn("export function renderMarkdownPreview", preview)
        self.assertIn(".assets-page-manager .designer-asset-editor", css)
        self.assertIn(".designer-asset-editor-surface", css)
        self.assertIn(".designer-asset-preview", css)
        self.assertIn("min-height: 420px", css)
        self.assertIn('body[data-page="ai-workflow-assets"]', css)
        self.assertIn("height: 100vh", css)
        self.assertIn("grid-template-rows: auto minmax(0, 1fr)", css)
        self.assertIn("overflow: hidden", css)
        self.assertIn("minmax(680px, 1.66fr)", css)
        self.assertIn("font-size: 13px", css)

    def test_removed_legacy_python_asset_terms_do_not_reappear(self) -> None:
        source = (ROOT / "app/services/workflow_asset_service.py").read_text(encoding="utf-8")
        self.assertNotIn('startswith(("validators/", "tools/"))', source)
        self.assertNotIn('item.get("validator")', source)

    def test_runner_supports_run_specific_validation_script_field(self) -> None:
        html = (ROOT / "static/index.html").read_text(encoding="utf-8")
        dom = (ROOT / "static/js/core/dom.js").read_text(encoding="utf-8")
        runs = (ROOT / "static/js/features/runs.js").read_text(encoding="utf-8")
        workflows = (ROOT / "static/js/features/workflows.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/workflow-runner.css").read_text(encoding="utf-8")

        self.assertNotIn('id="validationScript"', html)
        self.assertIn('validationScript: "validationScript"', dom)
        self.assertIn("validation_script: validationScript", runs)
        self.assertIn("requiresValidationScript(workflow)", workflows)
        self.assertIn('id="validationScript"', workflows)
        self.assertIn("workflow-step-validation", workflows)
        self.assertIn("body.chat-mode .validation-script-field", css)

    def test_workflow_designer_shows_copyable_cli_commands_without_ok_lint_copy(self) -> None:
        html = (ROOT / "static/workflow-designer.html").read_text(encoding="utf-8")
        controller = (ROOT / "static/js/pages/workflow-designer/controller.js").read_text(encoding="utf-8")
        utils = (ROOT / "static/js/pages/workflow-designer/utils.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/workflow-designer.css").read_text(encoding="utf-8")

        self.assertIn("designer-cli-card", html)
        self.assertIn('python -m app.cli.aiwf wf workflow-id "需求"', html)
        self.assertIn('/wf workflow-id "需求"', html)
        self.assertIn('/wstep xxx.md build.yaml "需求"', html)
        self.assertIn('/wstep /build build.yaml "需求"', html)
        self.assertNotIn('/wf --engine qwen', html)
        self.assertNotIn('/wf --engine opencode', html)
        self.assertNotIn('/wf xxx.md build.yaml', html)
        self.assertIn('data-designer-action="copy-cli-command"', html)
        self.assertIn('"copy-cli-command"', controller)
        self.assertIn("copyTextToClipboard", controller)
        self.assertIn("navigator.clipboard", utils)
        self.assertIn("designerCliWorkflowName", html)
        layout = (ROOT / "static/js/pages/workflow-designer/layout-renderer.js").read_text(encoding="utf-8")
        self.assertIn("renderCliCommands", layout)
        self.assertIn("python -m app.cli.aiwf wf", layout)
        self.assertIn("/wf ${workflowId}", layout)
        self.assertIn("/wstep xxx.md build.yaml", layout)
        self.assertIn("/wstep /build build.yaml", layout)
        self.assertNotIn("/wf --workflow", layout)
        self.assertNotIn("/wf --engine qwen", layout)
        self.assertNotIn("/wf --engine opencode", layout)
        self.assertNotIn("Ready to save", controller)
        self.assertNotIn("No workflow config issues detected", controller)
        self.assertIn(".designer-lint-panel.is-hidden", css)


if __name__ == "__main__":
    unittest.main()
