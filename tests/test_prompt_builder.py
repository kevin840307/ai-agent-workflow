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


if __name__ == "__main__":
    unittest.main()
