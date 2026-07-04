This step is executed by deterministic Python.

Expected behavior:
- Read the user requirement and current project index.
- Generate `output/task-manifest.md` and `output/task-manifest.json`.
- Generate one task-scoped prompt per task under `output/task-prompts/TASK-xxx.md`.
- Generate task TODO files under `output/todos/TASK-xxx.md`.
- Compile and validate a generated workflow instance for traceability only.
- Do not create or modify a persistent `.workflow` file.
