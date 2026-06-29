from __future__ import annotations


def _ui(
    *,
    supports_prompt: bool = False,
    supports_agent: bool = False,
    tabs: list[str] | None = None,
    prompt_defaults: bool | None = None,
    note: str = "",
) -> dict:
    """UI capability metadata consumed by workflow-designer.

    Keep this catalog as the single source of truth for function-specific UI.
    Step type still provides safe defaults, but selected function metadata can
    enable Prompt / Agent settings for special Python-backed functions.
    """

    data: dict[str, object] = {
        "supportsPrompt": supports_prompt,
        "supportsAgent": supports_agent,
    }
    if tabs is not None:
        data["tabs"] = tabs
    if prompt_defaults is not None:
        data["promptDefaults"] = prompt_defaults
    if note:
        data["note"] = note
    return data


PROMPT_AGENT_TABS = ["basic", "sources", "retry", "advanced"]
REVIEW_AGENT_TABS = ["basic", "sources", "review", "retry", "advanced"]
VALIDATOR_TABS = ["basic", "retry", "advanced"]


AVAILABLE_WORKFLOW_FUNCTIONS = {
    "validators": [
        {
            "id": "validate_spec",
            "label": "Validate Spec",
            "description": "Check required spec sections and AC IDs.",
            "ui": _ui(tabs=VALIDATOR_TABS),
        },
        {
            "id": "validate_todo",
            "label": "Validate Todo",
            "description": "Check todo sections, TEST IDs, and AC coverage.",
            "ui": _ui(tabs=VALIDATOR_TABS),
        },
        {
            "id": "require_status_pass",
            "label": "Require Status PASS",
            "description": "Gate helper for review artifacts that must contain Status: PASS.",
            "ui": _ui(tabs=["basic", "gate", "retry", "advanced"]),
        },
        {
            "id": "run_pytest",
            "label": "Run Pytest",
            "description": "Run the configured Python test command and write output/test-result.md.",
            "ui": _ui(tabs=VALIDATOR_TABS),
        },
        {
            "id": "collect_security_context",
            "label": "Collect Security Context",
            "description": "Write security scan scope and exclude rules to output/security-context.md without embedding source file contents.",
            "ui": _ui(tabs=VALIDATOR_TABS),
        },
        {
            "id": "consensus_agent",
            "label": "Consensus Agent",
            "description": "Run multiple internal agent generations with per-agent validation and retry in one visible workflow step.",
            "ui": _ui(
                supports_prompt=True,
                supports_agent=True,
                tabs=PROMPT_AGENT_TABS,
                prompt_defaults=True,
                note="This Python function wraps internal agent prompt executions.",
            ),
        },
        {
            "id": "combine_security_candidates",
            "label": "Combine Security Candidates",
            "description": "Merge same-task multi-agent security candidate files, deduplicate evidence, compute consensus confidence, and write output/security-findings.md.",
            "ui": _ui(tabs=VALIDATOR_TABS),
        },
        {
            "id": "generate_security_report",
            "label": "Generate Security Report",
            "description": "Generate output/security-report.md from Python-combined security-findings.md using the deterministic report template.",
            "ui": _ui(tabs=VALIDATOR_TABS),
        },
        {
            "id": "finalize_security_report",
            "label": "Finalize Security Report",
            "description": "Write output/security-final.md after security-report.md has passed validation.",
            "ui": _ui(tabs=VALIDATOR_TABS),
        },
        {
            "id": "validate_security_candidates",
            "label": "Validate Security Candidates",
            "description": "Check and score one AI-generated security-candidates-agent-*.md artifact for status, checklist coverage, CAND IDs, severity, confidence, evidence quality, and required fields. Fails when quality score is below thresholds.",
            "ui": _ui(tabs=VALIDATOR_TABS),
        },
        {
            "id": "validate_security_report",
            "label": "Validate Security Report",
            "description": "Check and score output/security-report.md for required findings, source finding IDs, severity, confidence, evidence quality, checklist coverage, and risk matrix format. Fails when quality score is below thresholds.",
            "ui": _ui(tabs=VALIDATOR_TABS),
        },
    ],
    "reviewStrategies": [
        {
            "id": "current_session",
            "label": "Current Session Review",
            "description": "Reuse the current agent session and evaluate pass/fail keywords plus confidence threshold.",
            "ui": _ui(
                supports_prompt=True,
                supports_agent=True,
                tabs=REVIEW_AGENT_TABS,
                prompt_defaults=True,
            ),
        },
        {
            "id": "new_agent",
            "label": "New Agent Review",
            "description": "Run review in a fresh agent session, then evaluate pass/fail keywords plus confidence threshold.",
            "ui": _ui(
                supports_prompt=True,
                supports_agent=True,
                tabs=REVIEW_AGENT_TABS,
                prompt_defaults=True,
            ),
        },
        {
            "id": "multi_agent",
            "label": "Multi-Agent Review",
            "description": "Run one or more reviewer agents and aggregate with keyword_confidence, majority_vote, or all_must_pass.",
            "ui": _ui(
                supports_prompt=True,
                supports_agent=True,
                tabs=REVIEW_AGENT_TABS,
                prompt_defaults=True,
            ),
        },
    ],
    "aggregators": [
        {
            "id": "keyword_confidence",
            "label": "Keyword + Confidence",
            "description": "Combine pass/fail keywords with a confidence threshold.",
        },
        {
            "id": "majority_vote",
            "label": "Majority Vote",
            "description": "Pass when most reviewers pass.",
        },
        {
            "id": "all_must_pass",
            "label": "All Must Pass",
            "description": "Pass only when every reviewer passes.",
        },
    ],
    "promptParams": [
        {"id": "requirement", "label": "Requirement", "description": "Main user input from the runner composer.", "sample": "Create a controllable agent workflow UI."},
        {"id": "project_path", "label": "Project Path", "description": "Current project folder path.", "sample": "C:\\Users\\kevin\\sort"},
        {"id": "workspace_path", "label": "Workspace Path", "description": "Workflow run workspace path.", "sample": "runs/workflow-001"},
        {"id": "project_overview", "label": "Project Overview", "description": "Auto-generated overview of project files and folders.", "sample": "Project files:\n- app/main.py"},
        {"id": "project_profile", "label": "Project Profile", "description": "Detected language, test framework, source files, and test files from the selected project path.", "sample": "Primary language: Python\nTest framework: pytest"},
        {"id": "architecture", "label": "Architecture", "description": "Content of architecture.md from the selected project path.", "sample": "# Architecture\nFastAPI backend with static frontend."},
        {"id": "spec", "label": "Spec", "description": "Content of output/spec.md.", "sample": "## Goal\nBuild the requested workflow feature."},
        {"id": "spec_review", "label": "Spec Review", "description": "Content of output/spec-review.md.", "sample": "Status: PASS"},
        {"id": "todo", "label": "Todo", "description": "Content of output/todo.md.", "sample": "## Todo List\n- TODO-001 Implement UI."},
        {"id": "todo_review", "label": "Todo Review", "description": "Content of output/todo-review.md.", "sample": "Status: PASS"},
        {"id": "test_plan", "label": "Test Plan", "description": "Content of output/test-plan.md.", "sample": "## Test Plan\n- TEST-001 Verify output."},
        {"id": "test_result", "label": "Test Result", "description": "Content of output/test-result.md.", "sample": "Status: FAIL\nAssertionError: expected file missing."},
        {"id": "build_result", "label": "Build Result", "description": "Content of output/build-result.md.", "sample": "FILE: app/main.py\nCONTENT:\n..."},
        {"id": "final_review", "label": "Final Review", "description": "Content of output/final-review.md.", "sample": "Status: PASS"},
        {"id": "raw_spec", "label": "Raw Spec", "description": "Alias of output/spec.md for older templates.", "sample": "## Goal\nBuild the requested workflow feature."},
        {"id": "answers", "label": "Answers", "description": "User answers from previous workflow interaction.", "sample": "Use Python and FastAPI."},
        {"id": "guidance", "label": "Guidance", "description": "User guidance added during the workflow.", "sample": "Keep implementation minimal."},
        {"id": "last_error", "label": "Last Error", "description": "Latest validation, review, timeout, or runner error.", "sample": "Missing Acceptance Criteria section."},
        {"id": "failure_feedback", "label": "Failure Feedback", "description": "Accumulated failure feedback for retry prompts.", "sample": "Retry 1/2 from build: tests failed."},
        {"id": "step_output", "label": "Step Output", "description": "Current step output text when available.", "sample": "Step completed successfully."},
        {"id": "security_context", "label": "Security Scope", "description": "Content of output/security-context.md. This artifact records project path, exclude rules, scanned file counts, and bounded security-relevant source excerpts.", "sample": "# Security Scan Scope"},
        {"id": "security_candidates", "label": "Security Candidates", "description": "Multi-agent candidate files such as security-candidates-auth-config.md.", "sample": "## CAND-001"},
        {"id": "security_findings", "label": "Security Findings", "description": "Python-combined normalized findings from output/security-findings.md.", "sample": "## SEC-001"},
    ],
}
