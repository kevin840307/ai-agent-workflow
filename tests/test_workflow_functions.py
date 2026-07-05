from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.workflow_runtime.builtin_functions.base import WorkflowFunctionContext, WorkflowFunctionError
from app.workflow_runtime.builtin_functions.core import require_status_pass, validate_spec, validate_todo
from app.workflow_runtime.builtin_functions.security_context import collect_security_context
from app.workflow_runtime.builtin_functions.security_validation import combine_security_candidates


def _context(workspace: Path, project: Path) -> WorkflowFunctionContext:
    async def log(_run, _message):
        return None

    async def refresh(_run_id):
        return None

    return WorkflowFunctionContext(
        run={"id": "run-1", "workspace": str(workspace), "project_path": str(project)},
        output_dir=workspace / "output",
        project_dir=project,
        root_dir=project,
        read_text=lambda path: path.read_text(encoding="utf-8") if path.exists() else "",
        write_text=lambda path, content: _write(path, content),
        log=log,
        refresh_artifacts=refresh,
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class WorkflowFunctionTests(unittest.TestCase):
    def test_validate_spec_and_todo_pass_and_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "run"
            project = Path(tmp) / "project"
            output = workspace / "output"
            output.mkdir(parents=True)
            project.mkdir()
            ctx = _context(workspace, project)

            (output / "spec.md").write_text(
                """## Goal
- Build it.

## Scope
- One feature.

## Out of Scope
- Everything else.

## Input
- Requirement.

## Output
- Code.

## Rules
- Keep tests separate.

## Acceptance Criteria
- AC-001: Works.

## Unknowns
- None.
""",
                encoding="utf-8",
            )
            validate_spec(ctx)

            (output / "todo.md").write_text(
                """## Todo List
- TODO-001: Implement AC-001.

## Test Plan
- TEST-001: Verify AC-001.

## Done Criteria
- AC-001 is done.
""",
                encoding="utf-8",
            )
            validate_todo(ctx)

            (output / "bad-review.md").write_text("Status: FAIL\n", encoding="utf-8")
            with self.assertRaises(WorkflowFunctionError):
                require_status_pass(ctx, "bad-review.md")

    def test_collect_security_context_writes_bounded_inventory_and_excerpts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "run"
            project = Path(tmp) / "project"
            workspace.mkdir()
            (workspace / "output").mkdir()
            project.mkdir()
            (project / "config.py").write_text('API_TOKEN = "Bearer abc"\n', encoding="utf-8")
            (project / "SGOAuto.csproj").write_text("<Project></Project>\n", encoding="utf-8")
            (project / "Map").mkdir()
            (project / "Map" / "area.dat").write_bytes(b"\x00\x01\x02BinaryFormatter\x00")
            (project / "image.tga").write_bytes(b"\x00" * 100)
            (project / "node_modules").mkdir()
            (project / "node_modules" / "ignored.js").write_text("secret = 1\n", encoding="utf-8")

            ctx = _context(workspace, project)
            collect_security_context(ctx)
            text = (workspace / "output" / "security-context.md").read_text(encoding="utf-8")

            self.assertIn("Status: DONE", text)
            self.assertIn("config.py", text)
            self.assertIn("SGOAuto.csproj", text)
            self.assertNotIn("ignored.js", text)
            self.assertNotIn("area.dat", text)
            self.assertNotIn("image.tga", text)
            self.assertIn("Bearer", text)

    def test_combine_security_candidates_accepts_heuristic_findings_from_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "run"
            project = Path(tmp) / "project"
            output = workspace / "output"
            output.mkdir(parents=True)
            project.mkdir()
            (output / "security-context.md").write_text(
                """Status: DONE

## Security-Relevant Excerpts

### app/config.py
```text
1: API_TOKEN = "Bearer abc"
```
""",
                encoding="utf-8",
            )
            (output / "security-candidates-agent-1.md").write_text(
                "Status: DONE\n\n## Scan Summary\n- No model candidates in this minimal test fixture.\n",
                encoding="utf-8",
            )

            ctx = _context(workspace, project)
            combine_security_candidates(ctx)
            findings = (output / "security-findings.md").read_text(encoding="utf-8")

            self.assertIn("Status: DONE", findings)
            self.assertIn("SEC-001", findings)
            self.assertIn("app/config.py", findings)


if __name__ == "__main__":
    unittest.main()
