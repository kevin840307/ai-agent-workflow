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
- Do not ask the user by default.
- Do not ask for facts already stated in the Requirement.
- Ask only if a missing core decision makes the artifact impossible to produce.
- Minor missing details must be handled with reasonable assumptions and recorded in Rules or Unknowns.
- For simple programming tasks, assume standard implementation and tests.
- If the Requirement already includes language and behavior, produce the artifact immediately.
- Do not convert the spec into questions, options, checklist, or requirement questionnaire.
- 規格內容必須是明確陳述句，不可以寫成問題、選項、問卷、訪談清單。"""
