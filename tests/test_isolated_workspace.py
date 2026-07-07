from __future__ import annotations

from pathlib import Path

from app.security.isolated_workspace import apply_isolated_changes, changed_project_files, create_isolated_project_copy


def test_isolated_workspace_copy_and_apply_reviewed_changes(tmp_path: Path) -> None:
    project = tmp_path / "project"
    workspace = tmp_path / "workspace"
    project.mkdir()
    (project / "app.py").write_text("value = 1\n", encoding="utf-8")
    (project / ".git").mkdir()
    (project / ".git" / "config").write_text("ignored", encoding="utf-8")

    isolated = create_isolated_project_copy(project, workspace)
    assert (isolated / "app.py").exists()
    assert not (isolated / ".git").exists()

    (isolated / "app.py").write_text("value = 2\n", encoding="utf-8")
    (isolated / "new.py").write_text("created = True\n", encoding="utf-8")
    changed = changed_project_files(project, isolated)
    assert changed == ["app.py", "new.py"]

    written = apply_isolated_changes(project, isolated, changed)
    assert [path.name for path in written] == ["app.py", "new.py"]
    assert (project / "app.py").read_text(encoding="utf-8") == "value = 2\n"
    assert (project / "new.py").exists()


def test_isolated_workspace_rejects_unsafe_apply_paths(tmp_path: Path) -> None:
    project = tmp_path / "project"
    isolated = tmp_path / "isolated"
    project.mkdir()
    isolated.mkdir()
    try:
        apply_isolated_changes(project, isolated, ["nested/../../outside.py"])
    except ValueError as exc:
        assert "Unsafe relative path" in str(exc)
    else:
        raise AssertionError("unsafe path should be rejected")
