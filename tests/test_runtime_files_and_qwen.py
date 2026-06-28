from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from app.runtime_modules.files import (
    extract_build_files,
    project_profile,
    requirement_mentions_language,
    validate_build_files_are_not_tests,
    validate_generated_test_files,
)
from app.runtime_modules.qwen import QwenCliClient
from app.runtime_modules.errors import WorkflowError


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

    def test_requirement_language_and_project_profile_detection(self) -> None:
        self.assertTrue(requirement_mentions_language("請用 Python 寫泡沫排序"))
        self.assertFalse(requirement_mentions_language("幫我做排序功能"))

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
            (project / "src").mkdir()
            (project / "src" / "sorter.py").write_text("def sort(): pass\n", encoding="utf-8")
            (project / "tests").mkdir()
            (project / "tests" / "test_sorter.py").write_text("def test_sort(): pass\n", encoding="utf-8")

            profile = project_profile(project)
            self.assertIn("Primary language: Python", profile)
            self.assertIn("pytest", profile)
            self.assertIn("src/sorter.py", profile)

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


def _restore_env(key: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
