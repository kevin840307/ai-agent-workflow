from __future__ import annotations

import json
import re


def extract_user_questions(output: str) -> str:
    text = output.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\"ask_user_question\".*\}", text, re.DOTALL)
        if not match:
            return text
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return text

    arguments = data.get("arguments", {}) if isinstance(data, dict) else {}
    questions = arguments.get("questions", []) if isinstance(arguments, dict) else []
    if not isinstance(questions, list) or not questions:
        return text

    lines: list[str] = []
    for index, question in enumerate(questions, start=1):
        if not isinstance(question, dict):
            continue
        header = question.get("header") or question.get("id") or f"Question {index}"
        prompt = question.get("question") or ""
        lines.append(f"## {header}\n\n{prompt}".strip())
        options = question.get("options") or []
        if isinstance(options, list) and options:
            option_lines: list[str] = []
            for option in options:
                if isinstance(option, dict):
                    label = option.get("label") or option.get("value") or ""
                    description = option.get("description") or ""
                    if label and description:
                        option_lines.append(f"- {label}: {description}")
                    elif label:
                        option_lines.append(f"- {label}")
                elif option:
                    option_lines.append(f"- {option}")
            if option_lines:
                lines.append("\n".join(option_lines))
        if question.get("multiSelect"):
            lines.append("_Multiple selections are allowed._")

    return "\n\n".join(lines).strip() or text


def interaction_instruction(allowed: bool) -> str:
    if not allowed:
        return """Human interaction rule:
    - Do not ask the user questions in this step.
    - Make reasonable assumptions and write them into the artifact when needed.
    - If the step cannot proceed safely, fail with a concrete error in the artifact instead of asking."""
    return """Human interaction rule:
- Do not ask for any fact, language, behavior, scope, format, output path, or constraint that is already stated in the Requirement.

- The agent must produce the artifact immediately when the Requirement provides enough information to make a reasonable implementation.

- Asking the user is allowed only when a missing core decision makes the artifact impossible to produce safely or correctly.

- Missing minor details must never block execution. The agent must make reasonable assumptions and record them in `Rules`, `Assumptions`, or `Unknowns`.

- For simple programming tasks, the agent must assume a standard implementation, standard input/output behavior, and basic tests unless the Requirement explicitly says otherwise.

- If the Requirement already specifies the target language, expected behavior, or output format, the agent must follow it directly and must not ask again.

- The agent must not convert the Requirement into questions, options, checklist, survey, requirement questionnaire, or confirmation form.

- The agent must not ask broad clarification questions such as goal, scope, input, output, edge cases, testing strategy, or preferred style when these can be reasonably inferred.

- The agent must prefer action over clarification. When uncertain, it must continue with the most standard and conservative assumption.

- If the agent asks a question, it must ask only the smallest possible blocking question, and it must explain why the artifact cannot be produced without that answer.

- The agent must not ask multiple-choice questions unless every option changes the core implementation and no reasonable default exists.

- The agent must not delay artifact generation just to improve completeness, polish, or preference alignment.

- The default behavior is: generate first, document assumptions, and continue."""
