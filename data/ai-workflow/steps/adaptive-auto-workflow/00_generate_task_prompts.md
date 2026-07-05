You are planning the next prompts for a CLI coding agent.

{{thinking_guidance}}
User request:
{{requirement_brief}}

Project snapshot, brief:
{{project_profile_brief}}
{{project_index_brief}}

Retry feedback from the last failed run, if any:
{{latest_failure_feedback}}

Create the SPEC and the short prompts that a human would type next into Qwen/OpenCode.

Rules:
- Do not implement code in this step.
- Do not create workflow docs or explain this workflow platform.
- The SPEC must be a faithful acceptance checklist derived from the user request.
- Python will only validate JSON shape and task prompt format; you must make the SPEC useful for the later review.
- Each task prompt must be a short natural-language CLI instruction for the selected project.
- Do not include shell commands, tool-call JSON, code blocks, absolute paths, or file contents.
- Prefer 1 task for simple requests. Use 2-3 tasks only when independent chunks are safer.
- If retry feedback exists, revise the SPEC/task prompts to fix that concrete failure.

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
