You are planning a fixed SOP development run for a CLI coding agent.

User request:
{{requirement_brief}}

Project snapshot, brief:
{{project_profile_brief}}
{{project_index_brief}}

Validation script, if provided:
{{validation_script}}

Controller complexity profile: {{complexity_profile}}
Recommended task count: {{recommended_task_count}}
Hard maximum task count: {{max_planned_tasks}}

Retry feedback, if any:
{{latest_failure_feedback}}

Create the SPEC, TODO, and short task prompts that a human would type into Qwen/OpenCode.

Rules:
- Do not implement code in this step.
- Do not explain the workflow platform.
- The SPEC must be derived only from the user request and project evidence.
- Each task prompt must be a natural-language CLI instruction for the selected project.
- Tasks may include implementation, tests, repair, or assembly work.
- Do not include review tasks; review is handled by the fixed SOP review step.
- Do not include shell commands, tool-call JSON, code blocks, absolute paths, or file contents.
- Use the minimum sufficient implementation. Do not add unrequested features, duplicate modules, extra examples, or documentation.
- Respect the controller complexity profile and hard maximum task count. Tiny requests should normally be 1 task, or at most 2 when tests are separate.
- If retry feedback exists, revise the plan/task prompts to address that concrete failure.

Output one JSON object only:
{
  "goal": "short goal",
  "spec": "Markdown SPEC with Goal, Scope, Acceptance Criteria, Test Expectations, Review Checklist",
  "tasks": [
    {
      "id": "TASK-001",
      "title": "short task title",
      "kind": "implementation|test|repair|assembly",
      "prompt": "short human CLI instruction for Qwen/OpenCode",
      "acceptance": ["concrete acceptance item"]
    }
  ]
}
