from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import unittest
import urllib.request
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestingDocumentationContractTests(unittest.TestCase):
    def test_testing_documentation_lists_daily_and_manual_commands(self) -> None:
        text = (ROOT / "doc/TESTING.md").read_text(encoding="utf-8")
        required = [
            "python -m unittest discover -s tests -v",
            "RUN_REAL_QWEN=1",
            "RUN_REAL_QWEN_FULL=1",
            "RUN_REAL_QWEN_STABILITY=1",
            "RUN_CLEAN_REPO_SMOKE=1",
            "RUN_PLAYWRIGHT_UI=1",
            "Run all 8 opt-in actual scenarios once",
            "unset RUN_REAL_QWEN RUN_REAL_QWEN_FULL RUN_REAL_QWEN_STABILITY",
            "Remove-Item Env:RUN_CLEAN_REPO_SMOKE",
            "QWEN_MOCK_SCENARIO=fail_final_review_once",
            "QWEN_MOCK_SCENARIO=generate_tests_no_files",
        ]
        for marker in required:
            with self.subTest(marker=marker):
                self.assertIn(marker, text)


class CleanRepoPatchApplyManualTests(unittest.TestCase):
    def test_clean_repo_smoke_is_opt_in(self) -> None:
        if os.environ.get("RUN_CLEAN_REPO_SMOKE") != "1":
            self.skipTest("Set RUN_CLEAN_REPO_SMOKE=1 to copy the repo to a clean temp directory and run smoke checks.")
        if os.environ.get("WORKFLOW_CLEAN_REPO_CHILD") == "1":
            self.skipTest("Avoid recursive clean repo smoke execution inside the copied repo.")

        with tempfile.TemporaryDirectory() as tmp:
            clean_root = Path(tmp) / "repo"
            ignore = shutil.ignore_patterns("__pycache__", ".pytest_cache", ".mypy_cache", ".qwen-workflow", "workspaces")
            shutil.copytree(ROOT, clean_root, ignore=ignore)
            env = dict(os.environ)
            env.update({"WORKFLOW_CLEAN_REPO_CHILD": "1", "QWEN_MOCK": "1", "QWEN_USE_SERVE": "0"})
            commands = [
                [sys.executable, "-m", "compileall", "app", "tests"],
                [sys.executable, "-m", "unittest", "tests.test_runtime_safety", "tests.test_workflow_non_e2e_contracts", "-v"],
            ]
            for command in commands:
                with self.subTest(command=" ".join(command)):
                    proc = subprocess.run(command, cwd=str(clean_root), env=env, capture_output=True, text=True, timeout=120)
                    self.assertEqual(
                        proc.returncode,
                        0,
                        f"command failed: {' '.join(command)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
                    )


class PlaywrightUiManualTests(unittest.TestCase):
    def test_playwright_ui_e2e_is_opt_in(self) -> None:
        self._run_with_server(self._run_basic_workflow_script)

    def test_playwright_reset_and_preview_regression_is_opt_in(self) -> None:
        def scenario(base_url: str) -> None:
            workflow_id = f"ui-preview-{uuid.uuid4().hex[:8]}"
            self._create_custom_workflow(base_url, workflow_id)
            self._run_reset_and_preview_script(base_url, workflow_id)

        self._run_with_server(scenario)

    def test_playwright_retry_failed_review_is_opt_in(self) -> None:
        self._run_with_server(self._run_retry_failed_review_script, {"QWEN_MOCK_SCENARIO": "fail_final_review_once"})

    def test_playwright_gate_failed_ui_is_opt_in(self) -> None:
        self._run_with_server(self._run_gate_failed_script, {"QWEN_MOCK_SCENARIO": "generate_tests_no_files"})

    def _ensure_enabled(self) -> None:
        if os.environ.get("RUN_PLAYWRIGHT_UI") != "1":
            self.skipTest("Set RUN_PLAYWRIGHT_UI=1 after installing Playwright to run UI E2E.")
        try:
            import playwright  # noqa: F401
        except ImportError as exc:
            raise AssertionError("Playwright is not installed. Run: python -m pip install playwright && python -m playwright install chromium") from exc

    def _free_port(self) -> str:
        configured = os.environ.get("PLAYWRIGHT_TEST_PORT")
        if configured:
            return configured
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return str(sock.getsockname()[1])

    def _run_with_server(self, script_runner, extra_env: dict[str, str] | None = None) -> None:
        self._ensure_enabled()
        port = self._free_port()
        base_url = f"http://127.0.0.1:{port}"
        env = dict(os.environ)
        env.update({"QWEN_MOCK": "1", "QWEN_USE_SERVE": "0", "QWEN_WORKFLOW_SHOW_AGENT_STDOUT": "0"})
        if extra_env:
            env.update(extra_env)
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", port],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        try:
            self._wait_for_server(base_url)
            script_runner(base_url)
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()

    def _wait_for_server(self, base_url: str) -> None:
        import time

        deadline = time.time() + 30
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(base_url, timeout=2) as response:
                    if response.status == 200:
                        return
            except Exception as exc:  # pragma: no cover - diagnostic only for manual test
                last_error = exc
                time.sleep(0.5)
        raise AssertionError(f"UI server did not start at {base_url}: {last_error}")

    def _create_custom_workflow(self, base_url: str, workflow_id: str) -> None:
        payload = {
            "id": workflow_id,
            "name": f"UI Preview {workflow_id}",
            "description": "Custom workflow used by Playwright preview switching test.",
            "steps": [
                {
                    "id": f"{workflow_id}-step",
                    "key": "preview_step",
                    "name": "Preview Step",
                    "type": "ai",
                    "enabled": True,
                    "templatePath": "prompts/preview.md",
                    "templateContent": "Produce output/preview.md for preview switching test.",
                    "outputFile": "preview.md",
                    "filename": "preview.md",
                    "expectedFiles": ["preview.md"],
                    "allowInteraction": False,
                    "reviewMode": "none",
                }
            ],
        }
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{base_url}/api/workflows",
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status != 200:
                raise AssertionError(f"failed to create custom workflow: {response.status}")

    def _run_playwright(self, script: str) -> None:
        proc = subprocess.run([sys.executable, "-c", script], cwd=str(ROOT), capture_output=True, text=True, timeout=240)
        self.assertEqual(proc.returncode, 0, f"Playwright UI E2E failed\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")

    def _common_script(self, base_url: str, body: str, *, title_prefix: str = "UI E2E Project") -> str:
        title = f"{title_prefix} {uuid.uuid4().hex[:8]}"
        return textwrap.dedent(
            f'''
            import re
            import tempfile
            from pathlib import Path
            from playwright.sync_api import sync_playwright, expect

            base_url = {base_url!r}
            title = {title!r}
            project_dir = Path(tempfile.mkdtemp(prefix='qwen-ui-e2e-'))
            (project_dir / 'README.md').write_text('# UI E2E Fixture\\n', encoding='utf-8')

            def create_project(page):
                page.goto(base_url, wait_until='domcontentloaded', timeout=15000)
                expect(page.locator('#newProject')).to_be_visible(timeout=10000)
                page.click('#newProject')
                expect(page.locator('#modalInput')).to_be_visible(timeout=5000)
                page.fill('#modalInput', title)
                page.click('#modalConfirm')
                expect(page.locator('#modalInput')).to_be_visible(timeout=5000)
                page.fill('#modalInput', str(project_dir))
                page.click('#modalConfirm')

                project_item = page.locator('#projectList .project-item').filter(has_text=title).first
                expect(project_item).to_be_visible(timeout=10000)
                project_item.click()
                expect(page.locator('#sessionTitle')).to_contain_text(title, timeout=10000)
                run_meta = page.locator('#runMeta')
                expect(run_meta).to_be_visible(timeout=10000)
                run_meta_text = run_meta.inner_text(timeout=10000)
                if project_dir.name not in run_meta_text:
                    raise AssertionError('#runMeta should contain project folder name ' + repr(project_dir.name) + ', actual=' + repr(run_meta_text))

            def run_workflow(page, requirement='Add a deterministic helper and tests.'):
                page.fill('#messageInput', requirement)
                expect(page.locator('#runWorkflow')).to_be_enabled(timeout=10000)
                page.click('#runWorkflow')

            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page()
                page.on('dialog', lambda dialog: dialog.accept())
                create_project(page)
            {textwrap.indent(body, '    ')}
                browser.close()
            '''
        )

    def _run_basic_workflow_script(self, base_url: str) -> None:
        script = self._common_script(
            base_url,
            """
            run_workflow(page)
            expect(page.locator('#resultText')).to_contain_text('DONE', timeout=90000)
            page.click('#resetSession')
            expect(page.locator('#sessionTitle')).to_contain_text(title, timeout=10000)
            expect(page.locator('#steps')).to_contain_text('No workflow run loaded.', timeout=10000)

            page.goto(base_url + '/ai-workflow-assets', wait_until='domcontentloaded', timeout=15000)
            expect(page.locator('.designer-asset-manager')).to_be_visible(timeout=10000)
            expect(page.locator('#designerAssetScope')).to_have_value('global', timeout=10000)
            page.select_option('#designerAssetType', 'functions')
            expect(page.locator('#designerAssetSummary')).to_contain_text('Python function', timeout=10000)
            page.select_option('#designerAssetType', 'steps')
            expect(page.locator('#designerAssetSummary')).to_contain_text('skill', timeout=10000)
            """,
        )
        self._run_playwright(script)

    def _run_reset_and_preview_script(self, base_url: str, custom_workflow_id: str) -> None:
        script = self._common_script(
            base_url,
            f"""
            initial_project_rows = page.locator('#projectList .project-item').filter(has_text=title).count()
            expect(page.locator('#workflowPreview .workflow-preview-step').first).to_be_visible(timeout=10000)
            expect(page.locator('#workflowPreview')).to_contain_text('Run with preview', timeout=10000)
            run_workflow(page, 'Verify reset and workflow preview behavior.')
            expect(page.locator('#resultText')).to_contain_text('DONE', timeout=90000)
            expect(page.locator('#workflowPreview .workflow-preview-step')).to_have_count(0, timeout=10000)

            page.click('#resetSession')
            expect(page.locator('#sessionTitle')).to_contain_text(title, timeout=10000)
            expect(page.locator('#steps')).to_contain_text('No workflow run loaded.', timeout=10000)

            page.goto(base_url + '/ai-workflow-assets', wait_until='domcontentloaded', timeout=15000)
            expect(page.locator('.designer-asset-manager')).to_be_visible(timeout=10000)
            expect(page.locator('#designerAssetScope')).to_have_value('global', timeout=10000)
            page.select_option('#designerAssetType', 'functions')
            expect(page.locator('#designerAssetSummary')).to_contain_text('Python function', timeout=10000)
            page.select_option('#designerAssetType', 'steps')
            expect(page.locator('#designerAssetSummary')).to_contain_text('skill', timeout=10000)
            after_reset_project_rows = page.locator('#projectList .project-item').filter(has_text=title).count()
            if after_reset_project_rows != initial_project_rows:
                raise AssertionError('Reset changed project row count: before=' + str(initial_project_rows) + ' after=' + str(after_reset_project_rows))

            page.click('#workflowDropdownButton')
            option = page.locator('.workflow-dropdown-option[data-workflow-id="{custom_workflow_id}"]').first
            expect(option).to_be_visible(timeout=10000)
            option.click()
            expect(page.locator('#workflowPreview')).to_contain_text('Custom workflow used by Playwright preview switching test.', timeout=10000)
            expect(page.locator('#workflowPreview .workflow-preview-step').first).to_be_visible(timeout=10000)
            """,
            title_prefix="UI Reset Preview Project",
        )
        self._run_playwright(script)

    def _run_retry_failed_review_script(self, base_url: str) -> None:
        script = self._common_script(
            base_url,
            """
            run_workflow(page, 'Verify retry after intentional final review failure.')
            expect(page.locator('#resultText')).to_contain_text('FAILED', timeout=90000)
            expect(page.locator('#steps')).to_contain_text('Intentional mock failure for Playwright retry coverage', timeout=10000)
            expect(page.locator('#retryRun')).to_be_enabled(timeout=10000)
            page.click('#retryRun')
            expect(page.locator('#resultText')).to_contain_text('DONE', timeout=90000)
            expect(page.locator('#steps .badge.failed')).to_have_count(0, timeout=10000)
            """,
            title_prefix="UI Retry Project",
        )
        self._run_playwright(script)

    def _run_gate_failed_script(self, base_url: str) -> None:
        script = self._common_script(
            base_url,
            """
            run_workflow(page, 'Verify gate failure is visible when generated test files are missing.')
            expect(page.locator('#resultText')).to_contain_text('FAILED', timeout=90000)
            expect(page.locator('#steps')).to_contain_text('generate_tests', timeout=10000)
            expect(page.locator('#steps')).to_contain_text('did not create any test files', timeout=10000)
            expect(page.locator('#steps .badge.failed').first).to_be_visible(timeout=10000)
            expect(page.locator('#retryRun')).to_be_enabled(timeout=10000)
            """,
            title_prefix="UI Gate Failed Project",
        )
        self._run_playwright(script)


if __name__ == "__main__":
    unittest.main()
