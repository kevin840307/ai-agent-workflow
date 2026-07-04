from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.workflow_runtime.prompt_builder import PromptBuilder


class PromptBuilderTests(unittest.TestCase):
    def test_prompt_includes_failure_feedback_and_project_context_when_template_omits_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "run"
            project = root / "project"
            workflow = root / "workflow"
            (workspace / "input").mkdir(parents=True)
            (workspace / "output").mkdir(parents=True)
            (workspace / "prompts").mkdir(parents=True)
            (project).mkdir()
            (workflow / "prompts").mkdir(parents=True)

            (workspace / "requirement.md").write_text("Build something", encoding="utf-8")
            (workspace / "input" / "failure-feedback.md").write_text(
                "## Retry Feedback for build\n\nError message to fix:\n\nNameError: missing function\n",
                encoding="utf-8",
            )
            (project / "architecture.md").write_text("# Architecture\nUse existing layout.", encoding="utf-8")
            (project / "app.py").write_text("def existing():\n    return True\n", encoding="utf-8")
            (workflow / "prompts" / "build.md").write_text("Build now.", encoding="utf-8")

            run = {
                "id": "run-1",
                "workspace": str(workspace),
                "project_path": str(project),
                "workflow_folder": "workflow",
                "steps": [
                    {
                        "key": "build",
                        "allow_interaction": False,
                        "config": {
                            "templatePath": "prompts/build.md",
                            "injectFailureFeedback": True,
                        },
                    }
                ],
            }

            builder = PromptBuilder()
            with patch("app.workflow_runtime.prompt_builder.WORKFLOW_BUNDLES_DIR", root):
                result = builder.build(run, "build", "prompts/build.md", allow_interaction=False)

            self.assertIn("NameError: missing function", result.prompt)
            self.assertIn("Current project architecture context", result.prompt)
            self.assertIn("Detected project profile", result.prompt)
            self.assertTrue((workspace / "prompts" / "build.md").exists())

    def test_prompt_can_include_validation_script_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "run"
            project = root / "project"
            workflow = root / "workflow"
            (workspace / "input").mkdir(parents=True)
            (workspace / "output").mkdir(parents=True)
            (workspace / "prompts").mkdir(parents=True)
            project.mkdir()
            (workflow / "prompts").mkdir(parents=True)

            (workspace / "requirement.md").write_text("Build a tool", encoding="utf-8")
            (project / "validation.py").write_text("assert True\n", encoding="utf-8")
            (workflow / "prompts" / "build.md").write_text("Validator:\n{{validation_script_content}}", encoding="utf-8")

            run = {
                "id": "run-1",
                "workspace": str(workspace),
                "project_path": str(project),
                "workflow_folder": "workflow",
                "validation_script": "validation.py",
                "steps": [{"key": "build", "allow_interaction": False, "config": {"templatePath": "prompts/build.md"}}],
            }

            with patch("app.workflow_runtime.prompt_builder.WORKFLOW_BUNDLES_DIR", root):
                result = PromptBuilder().build(run, "build", "prompts/build.md", allow_interaction=False)

            self.assertIn("read-only external validation script", result.prompt)
            self.assertIn("validation.py", result.prompt)
            self.assertNotIn("assert True", result.prompt)

    def test_current_task_feedback_is_scoped_and_full_feedback_not_appended(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "run"
            project = root / "project"
            workflow = root / "workflow"
            (workspace / "input").mkdir(parents=True)
            (workspace / "output" / "todos").mkdir(parents=True)
            (workspace / "output" / "task-prompts").mkdir(parents=True)
            (workspace / "prompts").mkdir(parents=True)
            project.mkdir()
            (workflow / "prompts").mkdir(parents=True)

            (workspace / "requirement.md").write_text("Build A and B", encoding="utf-8")
            (workspace / "input" / "failure-feedback.md").write_text(
                "## Retry Feedback for build\n\nError: build task TASK-001 failed.\n\n"
                "## Retry Feedback for build\n\nError: build task TASK-002 failed with wrong direction.\n",
                encoding="utf-8",
            )
            (workspace / "output" / "todos" / "TASK-002.md").write_text("# TASK-002\n", encoding="utf-8")
            (workspace / "output" / "task-prompts" / "TASK-002.md").write_text("# Prompt TASK-002\n", encoding="utf-8")
            (project / "architecture.md").write_text("# Architecture\n", encoding="utf-8")
            (project / "app.py").write_text("", encoding="utf-8")
            (workflow / "prompts" / "build.md").write_text("Feedback:\n{{current_task_failure_feedback}}", encoding="utf-8")

            run = {
                "id": "run-1",
                "workspace": str(workspace),
                "project_path": str(project),
                "workflow_folder": "workflow",
                "_current_task": {"id": "TASK-002", "title": "B", "owner": "build", "index": 2, "total": 2, "phase": "build"},
                "steps": [{"key": "build", "allow_interaction": False, "config": {"templatePath": "prompts/build.md", "injectFailureFeedback": True}}],
            }

            with patch("app.workflow_runtime.prompt_builder.WORKFLOW_BUNDLES_DIR", root):
                result = PromptBuilder().build(run, "build", "prompts/build.md", allow_interaction=False)

            self.assertIn("TASK-002 failed", result.prompt)
            self.assertNotIn("TASK-001 failed", result.prompt)
            self.assertNotIn("Failure feedback from previous retry attempts", result.prompt)

    def test_current_task_file_context_includes_previous_task_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "run"
            project = root / "project"
            workflow = root / "workflow"
            (workspace / "input").mkdir(parents=True)
            (workspace / "output" / "todos").mkdir(parents=True)
            (workspace / "output" / "task-prompts").mkdir(parents=True)
            (workspace / "output" / "tasks" / "TASK-001").mkdir(parents=True)
            (workspace / "prompts").mkdir(parents=True)
            project.mkdir()
            (workflow / "prompts").mkdir(parents=True)

            (workspace / "requirement.md").write_text("Build two functions", encoding="utf-8")
            (workspace / "output" / "todos" / "TASK-002.md").write_text("# TASK-002\n", encoding="utf-8")
            (workspace / "output" / "task-prompts" / "TASK-002.md").write_text("# Prompt TASK-002\n", encoding="utf-8")
            (workspace / "output" / "tasks" / "TASK-001" / "build-result.md").write_text(
                "FILE: sort.py\nCONTENT:\ndef bubble_sort(items):\n    return items\nEND_FILE\n",
                encoding="utf-8",
            )
            (project / "architecture.md").write_text("# Architecture\n", encoding="utf-8")
            (project / "sort.py").write_text("def bubble_sort(items):\n    return items\n", encoding="utf-8")
            (workflow / "prompts" / "build.md").write_text("Files:\n{{current_task_file_context}}", encoding="utf-8")

            run = {
                "id": "run-1",
                "workspace": str(workspace),
                "project_path": str(project),
                "workflow_folder": "workflow",
                "_current_task": {"id": "TASK-002", "title": "B", "owner": "build", "index": 2, "total": 2, "phase": "build"},
                "steps": [{"key": "build", "allow_interaction": False, "config": {"templatePath": "prompts/build.md"}}],
            }

            with patch("app.workflow_runtime.prompt_builder.WORKFLOW_BUNDLES_DIR", root):
                result = PromptBuilder().build(run, "build", "prompts/build.md", allow_interaction=False)

            self.assertIn("### sort.py", result.prompt)
            self.assertIn("def bubble_sort", result.prompt)
            self.assertIn("preserve existing behavior", result.prompt)

    def test_global_step_skill_path_loads_from_asset_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "run"
            project = root / "project"
            assets = root / "ai-workflow"
            (workspace / "input").mkdir(parents=True)
            (workspace / "output").mkdir(parents=True)
            (workspace / "prompts").mkdir(parents=True)
            (project).mkdir()
            (assets / "steps" / "general-auto-development").mkdir(parents=True)
            (assets / "steps" / "general-auto-development" / "03_build.md").write_text(
                "Loaded global build skill.",
                encoding="utf-8",
            )

            (workspace / "requirement.md").write_text("Build something", encoding="utf-8")
            run = {
                "id": "run-1",
                "workspace": str(workspace),
                "project_path": str(project),
                "workflow_folder": "general-auto-development",
                "skill_root": ".ai-workflow",
                "steps": [
                    {
                        "key": "build",
                        "allow_interaction": False,
                        "config": {
                            "templatePath": "steps/general-auto-development/03_build.md",
                            "skillPath": "steps/general-auto-development/03_build.md",
                        },
                    }
                ],
            }

            with patch("app.workflow_runtime.prompt_builder.AI_WORKFLOW_DIR", assets):
                result = PromptBuilder().build(run, "build", "steps/general-auto-development/03_build.md", allow_interaction=False)

            self.assertIn("Loaded global build skill.", result.prompt)
            self.assertIn("Loaded global build skill.", (workspace / "prompts" / "skill-context.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
