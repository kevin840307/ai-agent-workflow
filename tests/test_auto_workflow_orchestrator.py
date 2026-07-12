from __future__ import annotations

from pathlib import Path

from app.auto_workflow import orchestrator


def test_route_request_distinguishes_ask_from_development_and_acceptance() -> None:
    ask = orchestrator.route_request("這個專案怎麼運作?", project_has_files=True, requested_intent="ASK")
    assert ask["intent"] == "ASK"
    assert not ask["requires_code_change"]

    dev = orchestrator.route_request("幫我新增 config checker", project_has_files=True, requested_intent="DEVELOP_EXISTING_PROJECT")
    assert dev["intent"] == "DEVELOP_EXISTING_PROJECT"
    assert dev["requires_workflow_instance"]

    acceptance = orchestrator.route_request("幫我做 config checker", validation_script="tools/check.py", project_has_files=True, requested_intent="AUTO_WORKFLOW")
    assert acceptance["intent"] == "AUTO_WORKFLOW"
    assert acceptance["requires_acceptance"]



def test_route_request_does_not_guess_intent_from_natural_language() -> None:
    first = orchestrator.route_request("這是一個問題嗎？", project_has_files=True)
    second = orchestrator.route_request("請修改登入、資料庫、部署與文件", project_has_files=True)
    assert first["intent"] == second["intent"] == "DEVELOP_EXISTING_PROJECT"
    assert first["routing_source"] == second["routing_source"] == "workflow_context"

def test_extract_user_instructions_reads_numbered_steps_and_md_constraints(tmp_path: Path) -> None:
    workflow_md = tmp_path / "dev-flow.md"
    workflow_md.write_text("""# Flow\n\n1. 先理解專案\n2. 拆分任務\n3. 不可跳過驗證\n""", encoding="utf-8")

    result = orchestrator.extract_user_instructions(
        "請依照 dev-flow.md 執行\n1. 先理解專案\n2. 再修正功能",
        tmp_path,
    )

    assert [item["order"] for item in result["user_sequence"]] == [1, 2]
    assert result["workflow_md_refs"][0]["found"] is True
    assert "不可跳過驗證" in str(result["workflow_md_refs"][0]["summary"])


def test_task_manifest_and_workflow_instance_are_valid(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "tests").mkdir()
    todo = """# Todo\n\nStatus: READY\n\n## Requirement\n- Add a calculator.\n\n## Task Index\n| ID | Task | Acceptance Criteria | Depends On |\n| --- | --- | --- | --- |\n| TASK-001 | Implement add | AC-001 | None |\n\n## Tasks\n\n### TASK-001: Implement add\n- Goal: Implement calculator.add.\n- Files: app/calculator.py\n- Acceptance Criteria:\n  - AC-001: add(2, 3) returns 5.\n- Depends On:\n  - None\n- Validation:\n  - Covered by tests.\n"""

    manifest = orchestrator.task_manifest_from_todo(todo, project_dir=tmp_path)
    assert manifest["status"] == "READY"
    assert manifest["tasks"][0]["owner"] == "build"
    assert manifest["tasks"][0]["acceptance"] == ["AC-001: add(2, 3) returns 5."]
    assert orchestrator.validate_task_manifest(manifest, tmp_path) == []

    instance = orchestrator.compile_workflow_instance(manifest, run_profile="deep")
    assert instance["status"] == "READY"
    assert {step["id"] for step in instance["steps"]} >= {"TASK-001_BUILD", "ASSEMBLY_VERIFY", "FINAL_GATE"}
    assert orchestrator.validate_workflow_instance(instance, manifest) == []
    assert "Status: PASS" in orchestrator.render_validation_markdown([], [])
