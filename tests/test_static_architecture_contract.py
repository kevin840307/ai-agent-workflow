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


    def test_workflow_runner_ui_keys_are_registered(self):
        ids_source = (ROOT / "static/js/core/dom.js").read_text(encoding="utf-8")
        registered = set(re.findall(r"\n\s*([A-Za-z0-9_]+):\s*\"[^\"]+\"", ids_source))
        refs = set()
        for path in (ROOT / "static/js").rglob("*.js"):
            refs.update(re.findall(r"ui\.byKey\(\"([A-Za-z0-9_]+)\"\)", path.read_text(encoding="utf-8")))
        self.assertFalse(refs - registered, f"Missing UI.ids entries: {sorted(refs - registered)}")

    def test_workflow_runner_tabs_and_tokens_fit_current_ui(self):
        css = (ROOT / "static/css/workflow-runner.css").read_text(encoding="utf-8")
        styles = (ROOT / "static/styles.css").read_text(encoding="utf-8")
        html = (ROOT / "static/index.html").read_text(encoding="utf-8")
        tab_count = len(re.findall(r'class="tab(?: active)?" data-tab=', html))
        self.assertEqual(tab_count, 3)
        self.assertNotIn("grid-template-columns: repeat(4, 1fr)", css)
        self.assertIn(".run-center-tabs", css)
        self.assertNotIn("var(--border)", css + styles)
        self.assertIn("Run detail stability / overflow hardening", css)

    def test_workflow_console_tabs_do_not_consume_panel_space(self):
        layout_css = (ROOT / "static/css/layout.css").read_text(encoding="utf-8")
        self.assertIn("grid-template-rows: auto auto minmax(0, 1fr)", layout_css)
        self.assertNotIn("grid-template-rows: auto 1fr", layout_css)
        self.assertRegex(layout_css, r"\.details\s*\{[^}]*overflow:\s*hidden;")


    def test_workflow_runner_inactive_panels_are_hidden_before_js_loads(self):
        html = (ROOT / "static/index.html").read_text(encoding="utf-8")
        for panel_id in ["changesPanel", "validationPanel"]:
            with self.subTest(panel_id=panel_id):
                self.assertRegex(html, rf'<section id="{panel_id}" class="panel" hidden>')
        for panel_id in ["diagnosticAgent", "diagnosticLogs", "diagnosticArtifacts", "diagnosticPatch", "diagnosticRepair"]:
            with self.subTest(panel_id=panel_id):
                self.assertRegex(html, rf'<section id="{panel_id}" class="diagnostic-section" hidden>')

        layout = (ROOT / "static/js/features/layout.js").read_text(encoding="utf-8")
        self.assertIn("panel.hidden = !active;", layout)

    def test_static_cache_version_is_consistent(self):
        versions = set()
        for path in (ROOT / "static").rglob("*"):
            if path.suffix.lower() not in {".html", ".css", ".js"}:
                continue
            source = path.read_text(encoding="utf-8")
            versions.update(re.findall(r"\?v=([A-Za-z0-9_-]+)", source))
        self.assertEqual(versions, {"20260711-ui-v12"})


    def test_workflow_designer_sidebar_uses_shared_workflow_scroll(self):
        html = (ROOT / "static/workflow-designer.html").read_text(encoding="utf-8")
        css = (ROOT / "static/css/workflow-designer.css").read_text(encoding="utf-8")
        self.assertIn('class="designer-workflow-list-scroll"', html)
        self.assertIn('.designer-workflow-list-scroll', css)
        self.assertRegex(css, r"\.designer-workflow-list-scroll\s*\{[^}]*overflow-y:\s*auto")
        self.assertRegex(css, r"\.designer-workflow-list-scroll\s*\{[^}]*overflow-x:\s*hidden")
        self.assertRegex(css, r"\.designer-sidebar\s*\{[^}]*display:\s*flex")
        self.assertRegex(css, r"\.designer-sidebar\s*\{[^}]*flex-direction:\s*column")
        self.assertIn("flex: 1 1 0", css)
        self.assertRegex(css, r"\.designer-workflow-list-scroll\s*\{[^}]*display:\s*block")
        self.assertRegex(css, r"\.designer-custom-list,\s*\nbody\[data-page=\"workflow-designer\"\] \.designer-system-list\s*\{[^}]*overflow:\s*visible")

    def test_workflow_designer_sidebar_workflow_items_show_name_only(self):
        source = (ROOT / "static/js/pages/workflow-designer/layout-renderer.js").read_text(encoding="utf-8")
        sidebar_renderer = source[source.index("function renderSidebar") : source.index("function renderWorkflowLabels")]
        self.assertNotIn('designer-workflow-pill-description', sidebar_renderer)
        self.assertNotIn('steps -', sidebar_renderer)
        self.assertNotIn('${(workflow.steps || []).length}', sidebar_renderer)
        self.assertIn('<strong>${escapeHtml(workflow.name)}</strong>', sidebar_renderer)


    def test_workflow_designer_sidebar_names_use_ellipsis_without_horizontal_scroll(self):
        css = (ROOT / "static/css/workflow-designer.css").read_text(encoding="utf-8")
        self.assertIn("text-overflow: ellipsis", css)
        self.assertIn("white-space: nowrap", css)
        self.assertIn("overflow-x: hidden", css)

    def test_workflow_designer_assets_action_is_part_of_group(self):
        html = (ROOT / "static/workflow-designer.html").read_text(encoding="utf-8")
        css = (ROOT / "static/css/workflow-designer.css").read_text(encoding="utf-8")
        self.assertIn('<div class="designer-action-group" aria-label="Workflow actions">', html)
        self.assertIn('<a class="designer-button-link" href="/ai-workflow-assets">Assets</a>', html)
        self.assertIn('.designer-topbar-actions .designer-action-group .designer-button-link', css)
        self.assertIn('box-shadow: inset 0 0 0 1px var(--line)', css)

    def test_bilingual_documentation_entrypoints_exist(self):
        expected = [
            "README.md",
            "AGENT_INSTALLATION.md",
            "ADAPTIVE_AUTO_WORKFLOW.md",
            "WORKFLOW_METADATA.md",
            "FRONTEND_STRUCTURE.md",
            "TESTING.md",
        ]
        for rel in expected:
            with self.subTest(rel=rel):
                self.assertTrue((ROOT / "doc" / "en" / rel).exists())
                self.assertTrue((ROOT / "doc" / "zh-TW" / rel).exists())
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertLess(readme.index("# Qwen Workflow Web"), readme.index("# 中文簡介"))


    def test_workflow_designer_floating_panel_uses_icon_only_actions(self):
        source = (ROOT / "static/js/pages/workflow-designer/layout-renderer.js").read_text(encoding="utf-8")
        floating_renderer = source[source.index("function renderStepFloatingActions") : source.index("function openStepContextMenu")]
        self.assertIn('class="designer-action-icon"', floating_renderer)
        for label in [">Edit<", ">Up<", ">Down<", ">Copy<", ">Del<"]:
            with self.subTest(label=label):
                self.assertNotIn(label, floating_renderer)
        for icon in ["✎", "↑", "↓", "⧉", "×"]:
            with self.subTest(icon=icon):
                self.assertIn(icon, floating_renderer)

    def test_workflow_runner_routes_agent_stream_to_chat_not_raw_console(self):
        event_stream = (ROOT / "static/js/features/event-stream.js").read_text(encoding="utf-8")
        messages = (ROOT / "static/js/features/messages.js").read_text(encoding="utf-8")
        console = (ROOT / "static/js/features/console.js").read_text(encoding="utf-8")
        css = (ROOT / "static/css/workflow-runner.css").read_text(encoding="utf-8")
        runner = (ROOT / "app/workflow_runtime/agent_step_runner.py").read_text(encoding="utf-8")

        self.assertIn("updateWorkflowActivity", event_stream)
        self.assertIn("finishWorkflowActivity", event_stream)
        self.assertIn("resetWorkflowActivity", event_stream)
        self.assertNotIn("ctx.features.console.append(\"qwenLive\", `[${agent}:${event.step}:${event.stream}] ${event.text}`)", event_stream)
        self.assertIn("qwen_output is a legacy duplicate", event_stream)
        self.assertIn("workflow-activity", messages)
        self.assertIn("generatedChars", messages)
        self.assertIn("extractActivityMarkers", messages)
        self.assertIn("workflow-live-work", messages)
        self.assertIn("What it is doing", messages)
        self.assertIn("setLiveStatus", console)
        self.assertIn("trimConsoleText", console)
        self.assertIn(".message.workflow-activity", css)
        self.assertIn(".workflow-live-work", css)
        self.assertIn("_running_status", runner)
        self.assertIn("QWEN_WORKFLOW_EMIT_LEGACY_QWEN_OUTPUT", runner)

    def test_workflow_designer_knows_runtime_task_prompt_params(self):
        source = (ROOT / "static/js/pages/workflow-designer-constants.js").read_text(encoding="utf-8")
        self.assertIn('key: "task_manifest"', source)
        self.assertIn('key: "current_task"', source)

    def test_static_structure_document_mentions_designer_modules(self):
        source = (ROOT / "doc/FRONTEND_STRUCTURE.md").read_text(encoding="utf-8")
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
