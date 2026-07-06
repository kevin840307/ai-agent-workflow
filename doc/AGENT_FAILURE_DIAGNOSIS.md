# Agent Failure Diagnosis

The controller classifies common real-agent failures:

- `NO_PROJECT_CHANGES`: agent replied but did not edit project files.
- `TOOL_CALL_JSON`: agent emitted edit_file/write_file JSON.
- `FILE_BLOCK_OUTPUT`: agent emitted FILE blocks in real mode.
- `SHELL_COMMAND_PROMPT`: planner created shell commands instead of CLI prompts.
- `TEST_ONLY_CHANGE`: only tests changed when production changes were expected.
- `VALIDATION_FAILED`: validation.py or test command failed.
- `AGENT_TIMEOUT`: CLI or validation exceeded timeout.
- `AGENT_EMPTY_OUTPUT`: process returned no useful output.

Diagnosis appears in failure feedback, run trace, and gate report.
