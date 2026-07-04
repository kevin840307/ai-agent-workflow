from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.paths import write_text

MANAGED_QWEN_SETTINGS_PATH = Path('.qwen') / 'settings.json'
MANAGED_QWEN_RULES_PATH = Path('.qwen') / 'QWEN.md'
MANAGED_OPENCODE_CONFIG_PATH = Path('opencode.json')

_GUARD_NOTICE = "Managed by AI Workflow project guard. Keep edits inside this project."
_DRIVE_DENY_RULES = {f"{letter}:/**": "deny" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}
_DRIVE_DENY_RULES.update({f"{letter}:\\**": "deny" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"})


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        backup = path.with_suffix(path.suffix + '.backup-invalid-json')
        try:
            backup.write_text(path.read_text(encoding='utf-8'), encoding='utf-8')
        except OSError:
            pass
        return {}
    return data if isinstance(data, dict) else {}


def _dump_json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def _merge_qwen_settings(existing: dict[str, Any]) -> dict[str, Any]:
    data = dict(existing)
    data.setdefault('$schema', 'https://qwenlm.github.io/qwen-code/schemas/settings.json')
    tools = dict(data.get('tools') or {})
    # auto-edit lets Qwen use its file edit/write tools without approving shell commands.
    # We intentionally do not enable yolo. Sandbox is left off because the requested
    # read policy is unrestricted; write enforcement is handled by Qwen approval mode,
    # project instructions, and the post-run project change guard.
    tools['approvalMode'] = 'auto-edit'
    tools.setdefault('sandbox', False)
    excluded = list(tools.get('exclude') or [])
    for tool_name in [
        'shell',
        'run_shell_command',
        'execute_command',
        'web_fetch',
        'web_search',
        'git_commit',
        'git_push',
    ]:
        if tool_name not in excluded:
            excluded.append(tool_name)
    tools['exclude'] = excluded
    data['tools'] = tools
    context = dict(data.get('context') or {})
    # Do not add includeDirectories here: the user wants read access to stay possible,
    # but project-local settings should not silently load huge external folders.
    context.setdefault('includeDirectories', [])
    data['context'] = context
    data.setdefault('advanced', {})
    data['aiWorkflowGuard'] = {
        'managed': True,
        'writePolicy': 'project_only',
        'readPolicy': 'unrestricted',
        'dangerousOperations': 'disabled_or_denied',
        'note': _GUARD_NOTICE,
    }
    return data


def _merge_opencode_config(existing: dict[str, Any]) -> dict[str, Any]:
    data = dict(existing)
    data.setdefault('$schema', 'https://opencode.ai/config.json')
    existing_permission = data.get('permission') if isinstance(data.get('permission'), dict) else {}
    permission = dict(existing_permission)
    permission.update(
        {
            # Read/search are allowed. .env remains protected by OpenCode's documented default pattern.
            'read': {'*': 'allow', '*.env': 'deny', '*.env.*': 'deny', '*.env.example': 'allow'},
            'glob': 'allow',
            'grep': 'allow',
            'list': 'allow',
            # Allow the agent to modify files addressed as project-relative paths,
            # then explicitly deny common escape paths and managed guard files.
            'edit': {
                '*': 'deny',
                '**': 'allow',
                '../**': 'deny',
                '..\\**': 'deny',
                '/**': 'deny',
                '\\\\**': 'deny',
                '~/**': 'deny',
                '$HOME/**': 'deny',
                '.git/**': 'deny',
                '.qwen/**': 'deny',
                '.ai-workflow/**': 'deny',
                '.qwen-workflow/**': 'deny',
                'opencode.json': 'deny',
                **_DRIVE_DENY_RULES,
            },
            # External directories are allowed so OpenCode can read external context.
            # The edit rules above deny common external write paths; the runtime still
            # validates that only project files changed after the run.
            'external_directory': {'*': 'allow'},
            'bash': {
                '*': 'deny',
                'git status*': 'allow',
                'git diff*': 'allow',
                'dir*': 'allow',
                'ls*': 'allow',
                'type *': 'allow',
                'cat *': 'allow',
                'grep *': 'allow',
                'findstr *': 'allow',
            },
            'task': 'deny',
            'webfetch': 'deny',
            'websearch': 'deny',
            'question': 'allow',
            'todowrite': 'allow',
            'lsp': 'allow',
            'skill': 'allow',
            'doom_loop': 'deny',
        }
    )
    data['permission'] = permission
    data['aiWorkflowGuard'] = {
        'managed': True,
        'writePolicy': 'project_only',
        'readPolicy': 'unrestricted',
        'dangerousOperations': 'denied',
        'note': _GUARD_NOTICE,
    }
    return data


def _qwen_rules_text(project_root: Path) -> str:
    return f"""# AI Workflow Project Guard

This file is managed by AI Workflow.

Rules for Qwen/OpenCode agent runs in this project:
- You may read files from this project and from external locations when needed for context.
- You may edit/write only files inside this project root: `{project_root}`.
- Never edit `.qwen/settings.json`, `.qwen/**`, `opencode.json`, `.ai-workflow/**`, `.qwen-workflow/**`, or `.git/**`.
- Do not run dangerous operations such as deleting directories, changing git history, pushing to remotes, installing system packages, or modifying files outside the project root.
- Use built-in file edit/write tools to change files directly. Do not return platform file blocks for the workflow platform to materialize.
- After editing, report the files changed and what was done.
"""


def ensure_agent_project_configs(project_root: str | Path) -> list[Path]:
    """Create/update project-local Qwen/OpenCode guard configs.

    These config files are intentionally project-local so each selected Project
    Path carries its own agent permissions. They are platform-managed; runtime
    guards still validate post-run project changes because CLI settings are not
    an OS sandbox.
    """
    root = Path(project_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    qwen_settings = root / MANAGED_QWEN_SETTINGS_PATH
    qwen_settings.parent.mkdir(parents=True, exist_ok=True)
    qwen_data = _merge_qwen_settings(_read_json_object(qwen_settings))
    qwen_text = _dump_json(qwen_data)
    if not qwen_settings.is_file() or qwen_settings.read_text(encoding='utf-8') != qwen_text:
        write_text(qwen_settings, qwen_text)
        written.append(qwen_settings)

    qwen_rules = root / MANAGED_QWEN_RULES_PATH
    rules_text = _qwen_rules_text(root)
    if not qwen_rules.is_file() or qwen_rules.read_text(encoding='utf-8') != rules_text:
        write_text(qwen_rules, rules_text)
        written.append(qwen_rules)

    opencode_config = root / MANAGED_OPENCODE_CONFIG_PATH
    opencode_data = _merge_opencode_config(_read_json_object(opencode_config))
    opencode_text = _dump_json(opencode_data)
    if not opencode_config.is_file() or opencode_config.read_text(encoding='utf-8') != opencode_text:
        write_text(opencode_config, opencode_text)
        written.append(opencode_config)

    return written


MANAGED_AGENT_CONFIG_REL_PATHS = {
    MANAGED_QWEN_SETTINGS_PATH.as_posix(),
    MANAGED_QWEN_RULES_PATH.as_posix(),
    MANAGED_OPENCODE_CONFIG_PATH.as_posix(),
}
