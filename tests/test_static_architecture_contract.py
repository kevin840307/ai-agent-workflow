import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class StaticArchitectureContractTests(unittest.TestCase):
    def test_workflow_designer_entry_stays_thin(self):
        source = (ROOT / "static/js/pages/workflow-designer.js").read_text(encoding="utf-8")
        lines = [line for line in source.splitlines() if line.strip()]
        self.assertLessEqual(len(lines), 8, "workflow-designer.js should stay a thin page entry facade")
        self.assertIn('./workflow-designer/controller.js', source)
        self.assertRegex(source, r"export\s*\{\s*initWorkflowDesignerPage\s*\}")

    def test_workflow_designer_modules_exist(self):
        expected = [
            "static/js/pages/workflow-designer/controller.js",
            "static/js/pages/workflow-designer/asset-tools.js",
            "static/js/pages/ai-workflow-assets/asset-manager.js",
            "static/js/pages/ai-workflow-assets.js",
            "static/js/pages/workflow-designer/function-catalog.js",
            "static/js/pages/workflow-designer/import-export.js",
            "static/js/pages/workflow-designer/layout-renderer.js",
            "static/js/pages/workflow-designer/model.js",
            "static/js/pages/workflow-designer/step-tabs.js",
            "static/js/pages/workflow-designer/step-settings-renderer.js",
            "static/js/pages/workflow-designer/template-editor.js",
            "static/js/pages/workflow-designer/utils.js",
            "static/js/shared/sidebar.js",
            "static/css/sidebar.css",
        ]
        for rel_path in expected:
            with self.subTest(rel_path=rel_path):
                path = ROOT / rel_path
                self.assertTrue(path.exists(), f"{rel_path} should exist")
                self.assertGreater(path.stat().st_size, 0, f"{rel_path} should not be empty")

    def test_controller_uses_focused_modules(self):
        source = (ROOT / "static/js/pages/workflow-designer/controller.js").read_text(encoding="utf-8")
        self.assertIn('from "./model.js', source)
        self.assertIn('from "./utils.js', source)
        self.assertIn('from "./layout-renderer.js', source)
        self.assertIn('from "./step-settings-renderer.js', source)
        self.assertIn('from "./template-editor.js', source)
        self.assertIn('from "./import-export.js', source)
        self.assertIn('from "./function-catalog.js', source)
        self.assertIn('from "./asset-tools.js', source)
        self.assertNotIn('installWorkflowAssetManager', source)
        self.assertNotRegex(source, r"\nfunction\s+createWorkflow\s*\(")
        self.assertNotRegex(source, r"\nfunction\s+createStep\s*\(")
        self.assertNotRegex(source, r"\nfunction\s+escapeHtml\s*\(")
        self.assertNotRegex(source, r"\nfunction\s+toast\s*\(")

    def test_workflow_designer_files_stay_small_enough(self):
        limits = {
            "static/js/pages/workflow-designer/controller.js": 1200,
            "static/js/pages/workflow-designer/asset-tools.js": 180,
            "static/js/pages/ai-workflow-assets/asset-manager.js": 320,
            "static/js/pages/ai-workflow-assets.js": 80,
            "static/js/pages/workflow-designer/layout-renderer.js": 700,
            "static/js/pages/workflow-designer/step-tabs.js": 80,
            "static/js/pages/workflow-designer/step-settings-renderer.js": 700,
            "static/js/pages/workflow-designer/template-editor.js": 700,
            "static/js/pages/workflow-designer/import-export.js": 400,
            "static/js/pages/workflow-designer/function-catalog.js": 200,
            "static/js/pages/workflow-designer/model.js": 200,
            "static/js/pages/workflow-designer/utils.js": 200,
            "static/js/shared/sidebar.js": 120,
        }
        for rel_path, max_lines in limits.items():
            with self.subTest(rel_path=rel_path):
                path = ROOT / rel_path
                line_count = len(path.read_text(encoding="utf-8").splitlines())
                self.assertLessEqual(line_count, max_lines, f"{rel_path} has {line_count} lines; split it before it grows past {max_lines}")

    def test_assets_page_is_separate_from_workflow_designer(self):
        designer = (ROOT / "static/workflow-designer.html").read_text(encoding="utf-8")
        assets = (ROOT / "static/ai-workflow-assets.html").read_text(encoding="utf-8")
        self.assertIn('/ai-workflow-assets', designer)
        self.assertNotIn('designerAssetList', designer, "Asset CRUD list belongs on the dedicated assets page, not in the workflow designer layout")
        self.assertIn('designerAssetList', assets)
        self.assertIn('data-page="ai-workflow-assets"', assets)

    def test_static_cache_version_is_consistent(self):
        versions = set()
        for path in (ROOT / "static").rglob("*"):
            if path.suffix.lower() not in {".html", ".css", ".js"}:
                continue
            source = path.read_text(encoding="utf-8")
            versions.update(re.findall(r"\?v=([A-Za-z0-9_-]+)", source))
        self.assertEqual(versions, {"20260702-assets-bugfix1"})

    def test_static_structure_document_mentions_designer_modules(self):
        source = (ROOT / "static/FRONTEND_STRUCTURE.md").read_text(encoding="utf-8")
        for text in [
            "workflow-designer.js             # thin page entry",
            "workflow-designer/",
            "controller.js",
            "asset-tools.js",
            "asset-manager.js",
            "ai-workflow-assets.js",
            "layout-renderer.js",
            "step-settings-renderer.js",
            "template-editor.js",
            "import-export.js",
            "function-catalog.js",
            "model.js",
            "utils.js",
        ]:
            with self.subTest(text=text):
                self.assertIn(text, source)


if __name__ == "__main__":
    unittest.main()
