from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.runtime_modules.errors import WorkflowError
from app.runtime_modules.files import (
    apply_extracted_files,
    extract_build_files,
    files_from_changed_snapshot,
    project_content_snapshot,
    project_profile,
    restore_project_content_snapshot,
    requirement_has_actionable_signal,
    should_ask_for_spec_input,
    spec_input_questions,
    build_generic_python_import_smoke_test,
    build_validation_script_pytest_wrapper,
    validate_build_files_are_not_tests,
    validate_build_files_do_not_overwrite_validation_scripts,
    validate_generated_code_files_are_clean,
    validate_generated_test_files,
    validate_test_code_is_separate,
)
from app.runtime_modules.qwen import QwenCliClient
from app.workflow_runtime.agents import AgentRequest, OpenCodeCliAdapter, QwenAdapter, run_process_stream
from app.workflow_runtime.agent_stream_events import AgentJsonStreamParser
from app.workflow_runtime.qwen_serve import qwen_serve_disabled


class RuntimeFilesAndQwenTests(unittest.TestCase):
    def test_extract_build_files_and_test_file_validation(self) -> None:
        text = """FILE: app/main.py
CONTENT:
print("hi")
END_FILE
FILE: tests/test_main.py
CONTENT:
def test_hi():
    assert True
END_FILE
"""
        files = extract_build_files(text)
        self.assertEqual([path for path, _content in files], ["app/main.py", "tests/test_main.py"])

        validate_generated_test_files([("tests/test_main.py", "def test_x(): pass\n")])
        with self.assertRaises(WorkflowError):
            validate_generated_test_files([("app/test_main.py", "def test_x(): pass\n")])
        with self.assertRaises(WorkflowError):
            validate_build_files_are_not_tests([("tests/test_main.py", "def test_x(): pass\n")])

    def test_project_content_snapshot_restores_modified_and_new_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "src").mkdir()
            (project / "src" / "tool.py").write_text("VALUE = 1\n", encoding="utf-8")

            snapshot = project_content_snapshot(project)
            (project / "src" / "tool.py").write_text("VALUE = 2\n", encoding="utf-8")
            (project / "src" / "bad.py").write_text("BROKEN = True\n", encoding="utf-8")

            restore_project_content_snapshot(project, snapshot)

            self.assertEqual((project / "src" / "tool.py").read_text(encoding="utf-8"), "VALUE = 1\n")
            self.assertFalse((project / "src" / "bad.py").exists())

    def test_extract_build_files_strips_wrapping_code_fences_for_code_files(self) -> None:
        text = """FILE: tests/test_sort.py
CONTENT:
```python
def test_sort():
    assert True
```
END_FILE
FILE: docs/example.md
CONTENT:
```python
print("keep markdown fences")
```
END_FILE
"""
        files = dict(extract_build_files(text))
        self.assertEqual(files["tests/test_sort.py"], "def test_sort():\n    assert True\n")
        self.assertIn("```python", files["docs/example.md"])

    def test_extract_build_files_splits_when_agent_omits_end_file_between_blocks(self) -> None:
        text = """```content
FILE: a.py
CONTENT:
print("a")
FILE: b.py
CONTENT:
print("b")
END_FILE
```
"""
        files = extract_build_files(text)
        self.assertEqual(files, [("a.py", "print(\"a\")\n"), ("b.py", "print(\"b\")\n")])

    def test_extract_build_files_accepts_explicit_json_file_content_shape(self) -> None:
        text = '''```json
{"FILE": "src/tool.py", "CONTENT": "print(\\"ok\\")\\n"}
```'''
        self.assertEqual(extract_build_files(text), [("src/tool.py", "print(\"ok\")\n")])

    def test_extract_build_files_accepts_file_block_without_content_marker(self) -> None:
        text = """FILE: src/tool.py
```python
print("ok")
```
END_FILE
"""
        self.assertEqual(extract_build_files(text), [("src/tool.py", "print(\"ok\")\n")])

    def test_extract_build_files_accepts_markdown_file_headings(self) -> None:
        text = """# Adaptive Generation Result

### FILE/bubble_sort.py BEGIN_FILE
```python
def bubble_sort(values):
    return sorted(values)
```

### FILE/tests/test_bubble_sort.py BEGIN_FILE
```python
from bubble_sort import bubble_sort

def test_bubble_sort():
    assert bubble_sort([2, 1]) == [1, 2]
```

### END_FILE
"""
        files = dict(extract_build_files(text))
        self.assertEqual(files["bubble_sort.py"], "def bubble_sort(values):\n    return sorted(values)\n")
        self.assertIn("def test_bubble_sort", files["tests/test_bubble_sort.py"])

    def test_extract_build_files_accepts_start_end_file_blocks(self) -> None:
        text = """FILE/CONTENT/START_FILE sorting_sorting.py
```python
def selection_sort(values):
    return sorted(values)
```

FILE/CONTENT/END_FILE sorting_sorting.py
"""
        self.assertEqual(extract_build_files(text), [("sorting_sorting.py", "def selection_sort(values):\n    return sorted(values)\n")])

    def test_extract_build_files_strips_end_file_from_heading_path(self) -> None:
        text = """### FILE/calculate_bubble_sort.py/END_FILE
```python
def bubble_sort(values):
    return values
```
"""
        self.assertEqual(extract_build_files(text), [("calculate_bubble_sort.py", "def bubble_sort(values):\n    return values\n")])

    def test_extract_build_files_strips_trailing_fence_line_for_code_files(self) -> None:
        text = """FILE: src/tool.py
CONTENT:
print("ok")
```
END_FILE
"""
        self.assertEqual(extract_build_files(text), [("src/tool.py", "print(\"ok\")\n")])

    def test_file_block_marker_path_is_rejected(self) -> None:
        files = extract_build_files("""FILE: CONTENT/END_FILE sorting_algorithms.py
CONTENT:
def bubble_sort(values):
    return values
END_FILE
""")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(WorkflowError, "file block marker leaked into path"):
                apply_extracted_files(Path(tmp), files)

    def test_project_absolute_file_block_paths_are_normalized_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            outside = Path(tmp) / "outside.py"
            project.mkdir()
            inside = (project / "src" / "tool.py").resolve()

            written = apply_extracted_files(project, [(str(inside), "def run():\n    return 1\n")])

            self.assertEqual(written, [inside])
            self.assertTrue((project / "src" / "tool.py").is_file())
            with self.assertRaisesRegex(WorkflowError, "outside Project Path"):
                apply_extracted_files(project, [(str(outside.resolve()), "print('bad')\n")])

    def test_direct_edit_marker_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            bad_file = project / "CONTENT" / "END_FILE sorting_algorithms.py"
            bad_file.parent.mkdir(parents=True)
            bad_file.write_text("def bubble_sort(values):\n    return values\n", encoding="utf-8")

            with self.assertRaisesRegex(WorkflowError, "file block marker leaked into path"):
                files_from_changed_snapshot(project, ["CONTENT/END_FILE sorting_algorithms.py"])

    def test_external_validation_script_basename_is_protected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            external_validator = Path(tmp) / "validators" / "validate_acceptance.py"
            external_validator.parent.mkdir()
            external_validator.write_text("raise SystemExit(0)\n", encoding="utf-8")

            with self.assertRaisesRegex(WorkflowError, "validation scripts"):
                validate_build_files_do_not_overwrite_validation_scripts(
                    project,
                    [("validate_acceptance.py", "print('copied validator')\n")],
                    validation_script=str(external_validator),
                )

            with self.assertRaisesRegex(WorkflowError, "validation scripts"):
                validate_build_files_do_not_overwrite_validation_scripts(
                    project,
                    [("validate_acceptance.py (Treated as read-only acceptance test script provided)", "print('copied validator')\n")],
                    validation_script=str(external_validator),
                )

    def test_test_code_must_be_separate_from_production_files(self) -> None:
        validate_test_code_is_separate([("tests/test_sorting.py", "def test_sorting():\n    assert True\n")])
        validate_test_code_is_separate([("project/tests/test_sorting.py", "def test_sorting():\n    assert True\n")])
        with self.assertRaisesRegex(WorkflowError, "test code must be separated"):
            validate_test_code_is_separate([("sorting_algorithms.py", "def test_sorting():\n    assert True\n")])

    def test_generated_python_files_must_be_clean_source(self) -> None:
        validate_generated_code_files_are_clean([("src/tool.py", "def run():\n    return 1\n")])
        with self.assertRaisesRegex(WorkflowError, "source code only"):
            validate_generated_code_files_are_clean([("src/tool.py", "def run():\n    return 1\n\n## Retry Feedback for build\n")])
        with self.assertRaisesRegex(WorkflowError, "invalid syntax"):
            validate_generated_code_files_are_clean([("src/tool.py", "def bad(:\n    pass\n")])

    def test_extract_build_files_accepts_fenced_code_with_filename_comments(self) -> None:
        text = """# Result

```python
# src/tool.py
def run():
    return "ok"

# tests/test_tool.py
from src.tool import run

def test_run():
    assert run() == "ok"
```
"""
        files = dict(extract_build_files(text))
        self.assertEqual(files["src/tool.py"], "def run():\n    return \"ok\"\n")
        self.assertIn("def test_run", files["tests/test_tool.py"])

    def test_extract_build_files_ignores_non_file_tool_call_json(self) -> None:
        text = '{"name": "ask_user_question", "arguments": {"question": "Need input?"}}'
        self.assertEqual(extract_build_files(text), [])

    def test_validate_generated_test_files_rejects_python_syntax_errors(self) -> None:
        with self.assertRaisesRegex(WorkflowError, "invalid Python syntax"):
            validate_generated_test_files([("tests/test_bad.py", "def test_bad(:\n    pass\n")])

    def test_validate_generated_test_files_rejects_placeholder_example_tests(self) -> None:
        with self.assertRaisesRegex(WorkflowError, "placeholder example"):
            validate_generated_test_files([("tests/test_example.py", "from example import example\n")])
        with self.assertRaisesRegex(WorkflowError, "placeholder example"):
            validate_generated_test_files([("tests/test_placeholder.py", "from your_module import main  # Replace 'your_module' with the actual module name\n")])
        with self.assertRaisesRegex(WorkflowError, "placeholder example"):
            validate_generated_test_files([("tests/test_sorting.py", "def test_sorting():\n    assert False, 'implementation is incomplete'\n")])

    def test_validate_generated_test_files_rejects_empty_pytest_files(self) -> None:
        with self.assertRaisesRegex(WorkflowError, "without test functions"):
            validate_generated_test_files([("tests/test_sorting.py", "\n")])

    def test_validate_generated_test_files_rejects_only_conftest(self) -> None:
        with self.assertRaisesRegex(WorkflowError, "concrete pytest test file"):
            validate_generated_test_files([("tests/conftest.py", "import pytest\n")])

    def test_validate_generated_test_files_rejects_unresolved_fixture_args(self) -> None:
        with self.assertRaisesRegex(WorkflowError, "unresolved required fixture arguments"):
            validate_generated_test_files([("tests/test_sorting.py", "def test_sort(data):\n    assert sorted(data) == data\n")])

    def test_validate_generated_test_files_allows_local_fixture_args(self) -> None:
        validate_generated_test_files(
            [
                (
                    "tests/test_sorting.py",
                    "import pytest\n\n"
                    "@pytest.fixture\n"
                    "def data():\n"
                    "    return [1, 2]\n\n"
                    "def test_sort(data):\n"
                    "    assert sorted(data) == data\n",
                )
            ]
        )

    def test_project_profile_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
            (project / "src").mkdir()
            (project / "src" / "sorter.py").write_text("def sort(): pass\n", encoding="utf-8")
            (project / "tests").mkdir()
            (project / "tests" / "test_sorter.py").write_text("def test_sort(): pass\n", encoding="utf-8")

            profile = project_profile(project)
            self.assertIn("Dominant source extensions:", profile)
            self.assertIn(".py", profile)
            self.assertIn("pytest", profile)
            self.assertIn("src/sorter.py", profile)

    def test_requirement_clarification_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            empty_project = Path(tmp) / "empty"
            empty_project.mkdir()
            existing_project = Path(tmp) / "existing"
            existing_project.mkdir()
            (existing_project / "main.py").write_text("def main(): pass\n", encoding="utf-8")

            self.assertFalse(requirement_has_actionable_signal("??"))
            self.assertTrue(should_ask_for_spec_input("??", existing_project))
            self.assertIn("concrete task", spec_input_questions("??", existing_project))
            self.assertTrue(requirement_has_actionable_signal("asdf qwer zxcv"))
            self.assertFalse(should_ask_for_spec_input("asdf qwer zxcv", existing_project))

            self.assertTrue(requirement_has_actionable_signal("Add quick sort"))
            self.assertFalse(should_ask_for_spec_input("Add quick sort", existing_project))
            self.assertFalse(should_ask_for_spec_input("Add quick sort", empty_project))

            self.assertFalse(should_ask_for_spec_input("asdf qwer zxcv", existing_project, "Add quick sort in Python."))
            self.assertFalse(should_ask_for_spec_input("Add quick sort", empty_project, "Use Python."))

    def test_generic_smoke_tests_are_valid_with_windows_style_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            nested = project / "algorithms"
            nested.mkdir()
            (nested / "bubble_sort.py").write_text("def bubble_sort(values):\n    return sorted(values)\n", encoding="utf-8")

            files = build_generic_python_import_smoke_test(project, excluded_paths=[nested / "validation.py"])
            self.assertEqual([path for path, _content in files], ["tests/test_ai_workflow_generated_smoke.py"])
            compile(files[0][1], files[0][0], "exec")
            self.assertIn("'algorithms/bubble_sort.py'", files[0][1])
            self.assertIn("test_generated_python_modules_import_cleanly", files[0][1])
            self.assertNotIn("sorted(original)", files[0][1])

    def test_validation_script_pytest_wrapper_runs_project_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "validation.py").write_text("print('ok')\n", encoding="utf-8")

            files = build_validation_script_pytest_wrapper(project, "validation.py", [])
            self.assertEqual([path for path, _content in files], ["tests/test_ai_workflow_validation.py"])
            compile(files[0][1], files[0][0], "exec")
            self.assertIn("validation.py", files[0][1])

    def test_qwen_mock_client_and_command_options(self) -> None:
        old_mock = os.environ.get("QWEN_MOCK")
        old_bare = os.environ.get("QWEN_BARE")
        old_auth = os.environ.get("QWEN_AUTH_TYPE")
        try:
            os.environ["QWEN_MOCK"] = "1"
            os.environ["QWEN_BARE"] = "1"
            os.environ["QWEN_AUTH_TYPE"] = "openai"
            client = QwenCliClient({"reuse_session": True})
            command = client.command("session-1", include_prompt_flag=False)

            self.assertIn("--bare", command)
            self.assertIn("--session-id", command)
            self.assertIn("session-1", command)
            self.assertIn("--auth-type", command)
            self.assertIn("openai", command)
            self.assertIn("## Goal", client.run("OUTPUT_FILE: output/spec.md", Path.cwd()))
        finally:
            _restore_env("QWEN_MOCK", old_mock)
            _restore_env("QWEN_BARE", old_bare)
            _restore_env("QWEN_AUTH_TYPE", old_auth)

    def test_qwen_adapter_defaults_to_cli_unless_serve_is_enabled(self) -> None:
        old_mock = os.environ.get("QWEN_MOCK")
        old_use_serve = os.environ.get("QWEN_USE_SERVE")
        try:
            os.environ.pop("QWEN_MOCK", None)
            os.environ.pop("QWEN_USE_SERVE", None)
            request = AgentRequest(
                run_id="run-1",
                step_key="step",
                prompt="hello",
                cwd=Path.cwd(),
                session_id="session-1",
            )

            adapter = QwenAdapter()
            self.assertIn("<prompt via stdin>", adapter.command_preview(request))
            self.assertIn("--output-format stream-json", adapter.command_preview(request))
            self.assertIn("--include-partial-messages", adapter.command_preview(request))
            self.assertEqual(adapter.health()["type"], "qwen_cli")

            os.environ["QWEN_USE_SERVE"] = "1"
            adapter = QwenAdapter()
            self.assertEqual(adapter.command_preview(request), "POST qwen serve /session/<session>/prompt")
            self.assertEqual(adapter.health()["type"], "qwen_serve")
        finally:
            _restore_env("QWEN_MOCK", old_mock)
            _restore_env("QWEN_USE_SERVE", old_use_serve)

    def test_qwen_serve_status_is_disabled_by_default(self) -> None:
        old_use_serve = os.environ.get("QWEN_USE_SERVE")
        old_serve = os.environ.get("QWEN_SERVE")
        try:
            os.environ.pop("QWEN_USE_SERVE", None)
            os.environ.pop("QWEN_SERVE", None)
            self.assertTrue(qwen_serve_disabled())

            os.environ["QWEN_USE_SERVE"] = "1"
            self.assertFalse(qwen_serve_disabled())

            os.environ["QWEN_SERVE"] = "0"
            self.assertTrue(qwen_serve_disabled())
        finally:
            _restore_env("QWEN_USE_SERVE", old_use_serve)
            _restore_env("QWEN_SERVE", old_serve)

    def test_opencode_adapter_prefers_cmd_on_windows_and_renders_command(self) -> None:
        adapter = OpenCodeCliAdapter({"bin": "opencode", "mode": "run", "model": "test/model", "agent": "build"})
        request = AgentRequest(
            run_id="run-1",
            step_key="step",
            prompt="hello",
            cwd=Path.cwd(),
        )
        self.assertEqual(adapter.command_preview(request), f"{adapter.bin} run --format json <prompt>")
        self.assertEqual(adapter.health()["model"], "test/model")
        self.assertEqual(adapter.health()["agent"], "build")
        self.assertEqual(adapter.health()["timeout_sec"], 1200)
        session_request = AgentRequest(
            run_id="run-1",
            step_key="step",
            prompt="hello",
            cwd=Path.cwd(),
            session_id="session-1",
        )
        self.assertEqual(adapter.command_preview(session_request), f"{adapter.bin} run --session <session> --format json <prompt>")
        no_reuse = OpenCodeCliAdapter({"bin": "opencode", "mode": "run", "reuseSession": False})
        self.assertEqual(no_reuse.command_preview(session_request), f"{no_reuse.bin} run --format json <prompt>")
        if os.name == "nt":
            self.assertTrue(adapter.bin.endswith("opencode.cmd") or adapter.bin.endswith("opencode.exe") or adapter.bin == "opencode.cmd")

    def test_agent_json_stream_parser_normalizes_partial_thinking_and_final_text(self) -> None:
        parser = AgentJsonStreamParser()

        self.assertEqual(parser.feed_line('{"type":"message_partial","content":"hel"}'), [("display", "hel")])
        self.assertEqual(parser.feed_line('{"type":"message_partial","content":"hello"}'), [("display", "lo")])
        self.assertEqual(parser.feed_line('{"type":"thinking","text":"checking"}'), [("thinking", "checking")])
        self.assertEqual(parser.feed_line('{"type":"message","content":[{"type":"text","text":" done"}]}'), [("display", " done")])
        self.assertEqual(parser.final_text(), "done")

        qwen = AgentJsonStreamParser()
        self.assertEqual(
            qwen.feed_line('{"type":"stream_event","event":{"type":"content_block_delta","delta":{"type":"text_delta","text":"OK"}}}'),
            [("display", "OK")],
        )
        self.assertEqual(qwen.feed_line('{"type":"result","result":"OK"}'), [])
        self.assertEqual(qwen.final_text(), "OK")

        opencode = AgentJsonStreamParser()
        self.assertEqual(
            opencode.feed_line('{"type":"text","part":{"type":"text","text":"OK"}}'),
            [("display", "OK")],
        )

    def test_opencode_mock_uses_agent_contract_without_cli(self) -> None:
        old_mock = os.environ.get("OPENCODE_MOCK")
        try:
            os.environ["OPENCODE_MOCK"] = "1"
            adapter = OpenCodeCliAdapter({"bin": "missing-opencode"})
            self.assertTrue(adapter.health()["mock"])
            self.assertTrue(adapter.health()["exists"])
        finally:
            _restore_env("OPENCODE_MOCK", old_mock)

    def test_opencode_recovers_from_missing_session_by_retrying_fresh(self) -> None:
        async def run() -> None:
            adapter = OpenCodeCliAdapter({"bin": "opencode", "mode": "run", "reuseSession": True})
            request = AgentRequest(
                run_id="run-1",
                step_key="chat",
                prompt="hello",
                cwd=Path.cwd(),
                session_id="missing-session",
            )
            calls: list[list[str]] = []

            async def fake_process(command, cwd, *, env=None, on_output=None, timeout_sec=None):
                calls.append(command)
                if "--session" in command:
                    raise WorkflowError("Agent process failed with exit code 1: opencode run --session missing-session\nError: Session not found")
                return "fresh answer", ""

            with patch("app.workflow.agents.providers.opencode.run_process_stream", new=AsyncMock(side_effect=fake_process)):
                result = await adapter.run_stream(request)

            self.assertEqual(result.output, "fresh answer")
            self.assertIsNone(result.session_id)
            self.assertEqual(len(calls), 2)
            self.assertIn("--session", calls[0])
            self.assertNotIn("--session", calls[1])

        import asyncio

        asyncio.run(run())

    def test_process_runner_falls_back_when_async_subprocess_is_unavailable(self) -> None:
        async def run() -> None:
            completed = subprocess.CompletedProcess(["agent"], 0, stdout="ok\n", stderr="")
            with patch("asyncio.create_subprocess_exec", side_effect=NotImplementedError), patch(
                "subprocess.run",
                return_value=completed,
            ) as subprocess_run:
                stdout, stderr = await run_process_stream(["agent", "run"], Path.cwd())

            self.assertEqual(stdout, "ok")
            self.assertEqual(stderr, "")
            subprocess_run.assert_called_once()

        import asyncio
        import subprocess

        asyncio.run(run())


def _restore_env(key: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
