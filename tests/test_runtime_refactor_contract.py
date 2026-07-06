from __future__ import annotations

import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class RuntimeRefactorContractTests(unittest.TestCase):
    def test_new_runtime_modules_import_paths_are_available(self) -> None:
        modules = [
            "app.runtime_modules.api",
            "app.runtime_modules.errors",
            "app.runtime_modules.events",
            "app.runtime_modules.files",
            "app.core.paths",
            "app.core.locks",
            "app.core.metrics",
            "app.api.errors",
            "app.api.routes.artifacts",
            "app.api.routes.config",
            "app.api.routes.maintenance",
            "app.api.routes.projects",
            "app.api.routes.workflow_runs",
            "app.api.routes.workflows",
            "app.testing.mock_agent",
            "app.runtime_modules.qwen",
            "app.runtime_modules.run_state",
            "app.runtime_modules.skills",
            "app.persistence.json_store",
        ]
        for module_name in modules:
            with self.subTest(module_name=module_name):
                module = importlib.import_module(module_name)
                self.assertIsNotNone(module)

    def test_runtime_api_keeps_public_contract(self) -> None:
        runtime_api = importlib.import_module("app.runtime_modules.api")
        expected = [
            "Store",
            "RunState",
            "WorkflowError",
            "WorkflowCancelled",
            "ValidationError",
            "UserInputRequired",
            "AgentSettingsRequest",
            "CreateRunRequest",
            "CreateSessionRequest",
            "ROOT",
            "STORE_FILE",
            "WORKSPACES_DIR",
            "store",
            "run_state",
            "bus",
            "refresh_artifacts",
            "execute_workflow",
            "qwen_runtime_config",
        ]
        for name in expected:
            self.assertTrue(hasattr(runtime_api, name), f"runtime api missing export: {name}")

    def test_runtime_paths_keep_project_root_after_module_move(self) -> None:
        paths = importlib.import_module("app.core.paths")
        self.assertEqual(Path(paths.ROOT), Path(__file__).resolve().parents[1])
        self.assertEqual(paths.WORKSPACES_DIR, paths.ROOT / "workspaces")
        self.assertEqual(paths.STORE_FILE, paths.ROOT / "data" / "store.json")

    def test_runtime_api_allows_store_file_override_for_cli_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store_path = Path(tmp) / "isolated-store.json"
            env = os.environ.copy()
            env["AIWF_STORE_FILE"] = str(store_path)
            repo = Path(__file__).resolve().parents[1]
            env["PYTHONPATH"] = str(repo)
            env.pop("PYTEST_CURRENT_TEST", None)
            completed = subprocess.run(
                [sys.executable, "-c", "from app.runtime_modules import api; print(api.store.path)"],
                cwd=repo,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
                check=True,
            )
            self.assertEqual(Path(completed.stdout.strip()), store_path)

    def test_compatibility_facades_point_to_new_core_modules(self) -> None:
        checks = [
            ("app.runtime_modules.paths", "app.core.paths", "ROOT"),
            ("app.runtime_modules.locks", "app.core.locks", "project_run_creation_lock"),
            ("app.runtime_modules.metrics", "app.core.metrics", "metrics"),
            ("app.runtime_modules.api_errors", "app.api.errors", "error_payload"),
            ("app.mock_qwen", "app.testing.mock_agent", "mock_qwen_response"),
        ]
        for old_name, new_name, attr in checks:
            with self.subTest(old_name=old_name, new_name=new_name):
                old_module = importlib.import_module(old_name)
                new_module = importlib.import_module(new_name)
                self.assertIs(getattr(old_module, attr), getattr(new_module, attr))

    def test_legacy_runtime_files_are_removed_or_empty_deletion_markers(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        legacy_files = [
            "app/runtime.py",
            "app/runtime_errors.py",
            "app/runtime_events.py",
            "app/runtime_files.py",
            "app/runtime_paths.py",
            "app/runtime_qwen.py",
            "app/runtime_run_state.py",
            "app/runtime_skills.py",
            "app/runtime_store.py",
        ]
        for rel_path in legacy_files:
            with self.subTest(rel_path=rel_path):
                path = repo / rel_path
                if not path.exists():
                    continue
                self.assertEqual(path.read_text(encoding="utf-8"), "")

    def test_application_code_uses_runtime_modules_not_legacy_runtime_paths(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        legacy_patterns = [
            "from app import runtime",
            "import app.runtime\n",
            "import app.runtime as",
            "from app.runtime import",
            "from app.runtime_errors",
            "from app.runtime_events",
            "from app.runtime_files",
            "from app.runtime_paths",
            "from app.runtime_qwen",
            "from app.runtime_run_state",
            "from app.runtime_skills",
            "from app.runtime_store",
            "app.runtime_qwen.",
            "app.runtime_files.",
            "app.runtime_paths.",
            "app.runtime_store.",
            "app.runtime_run_state.",
            "app.runtime_errors.",
            "app.runtime_skills.",
            "app.runtime_events.",
        ]
        ignored = {
            Path("app/runtime.py"),
            Path("app/runtime_errors.py"),
            Path("app/runtime_events.py"),
            Path("app/runtime_files.py"),
            Path("app/runtime_paths.py"),
            Path("app/runtime_qwen.py"),
            Path("app/runtime_run_state.py"),
            Path("app/runtime_skills.py"),
            Path("app/runtime_store.py"),
            Path("tests/test_runtime_refactor_contract.py"),
        }
        violations: list[str] = []
        for base in (repo / "app", repo / "tests"):
            for path in base.rglob("*.py"):
                rel_path = path.relative_to(repo)
                if "__pycache__" in path.parts or rel_path in ignored:
                    continue
                text = path.read_text(encoding="utf-8")
                for pattern in legacy_patterns:
                    if pattern in text:
                        violations.append(f"{rel_path}: contains {pattern!r}")
        self.assertEqual(violations, [])

    def test_services_use_new_persistence_repository_imports(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        violations: list[str] = []
        for path in (repo / "app" / "services").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "from app.repositories import store_repository" in text:
                violations.append(str(path.relative_to(repo)))
        self.assertEqual(violations, [])

    def test_source_files_do_not_contain_replacement_mojibake(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        extensions = {".py", ".js", ".css", ".html", ".md", ".json"}
        ignored_parts = {".git", "__pycache__", ".pytest_cache", ".venv", "venv", "env", "node_modules"}
        bad_markers = ["\ufffd"]
        violations: list[str] = []

        for path in repo.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in extensions:
                continue
            if any(part in ignored_parts for part in path.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if any(marker in text for marker in bad_markers):
                violations.append(str(path.relative_to(repo)))

        self.assertEqual(violations, [])

    def test_agent_provider_code_is_split_by_adapter(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        adapter_dir = repo / "app" / "workflow" / "agents"
        provider_dir = adapter_dir / "providers"
        expected_files = [
            adapter_dir / "base.py",
            provider_dir / "qwen.py",
            provider_dir / "opencode.py",
        ]
        for path in expected_files:
            with self.subTest(path=path.name):
                self.assertTrue(path.exists(), f"missing agent adapter: {path}")

        qwen_source = (provider_dir / "qwen.py").read_text(encoding="utf-8")
        opencode_source = (provider_dir / "opencode.py").read_text(encoding="utf-8")
        schema_source = (repo / "app" / "domain" / "schemas.py").read_text(encoding="utf-8")

        self.assertNotIn("OpenCode", qwen_source)
        self.assertNotIn("opencode", qwen_source.lower())
        self.assertIn("OpenCodeCliAdapter", opencode_source)
        self.assertIn("class AgentSettingsRequest", schema_source)
        self.assertNotIn("class QwenSettingsRequest", schema_source)


if __name__ == "__main__":
    unittest.main()
