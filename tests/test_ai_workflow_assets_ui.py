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
        css = (ROOT / "static/css/workflow-designer.css").read_text(encoding="utf-8")
        self.assertIn(".assets-page-manager .designer-asset-editor", css)
        self.assertIn("min-height: 420px", css)
        self.assertIn('body[data-page="ai-workflow-assets"]', css)
        self.assertIn("overflow: auto", css)
        self.assertIn("position: sticky", css)

    def test_removed_legacy_python_asset_terms_do_not_reappear(self) -> None:
        source = (ROOT / "app/services/workflow_asset_service.py").read_text(encoding="utf-8")
        self.assertNotIn('startswith(("validators/", "tools/"))', source)
        self.assertNotIn('item.get("validator")', source)


if __name__ == "__main__":
    unittest.main()
