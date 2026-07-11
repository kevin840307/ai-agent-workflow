# Stability V11

V11 is a focused reliability release for retry consistency, existing-project test layouts, recovery UI, change deduplication, and Qwen/OpenCode interactive slash commands.

## Runtime stability

- Existing root-level pytest files such as `test_sorts.py` may be updated when they existed before the Run.
- Newly generated pytest files still default to `tests/`; Build/Test ownership remains enforced.
- Retry and finalization now safely handle Store adapters that return the same mutable Run object.
- Retry reset takes a deep state snapshot before refreshing the stable in-memory Run.
- Final Completion Gate reads a safe snapshot of the latest persisted Run, preventing `workspace`/`steps` loss.

## UI stability

- Restart recovery is shown once inside Current Action, not as a second large failure panel.
- Duplicate path aliases such as `.\\sorts.py` and `sorts.py` are merged.
- Multi-file Changes shows `+/-` statistics once in the file navigator; the preview is labeled `Preview` instead of repeating the same row.

## Interactive `/wf` and `/wstep`

The installer renders the absolute current Python executable and the absolute stable launcher into Qwen Code and OpenCode command files. Commands therefore work from the target project instead of requiring the Controller repository as the current directory.

```bash
python scripts/install_agent_commands.py --target all --scope project --project <project>
```

Installation performs non-mutating dry-runs for both routes from the target project. Production Acceptance also runs this verification.

The command templates follow the current official formats:

- Qwen Code: `.qwen/commands/*.md`, `{{args}}`, and `!{command}` shell injection.
- OpenCode: `.opencode/commands/*.md`, `$ARGUMENTS`, and ``!`command` `` shell output injection.

A real installed TUI visibility check still requires Qwen Code/OpenCode to be installed on the target Windows machine.
