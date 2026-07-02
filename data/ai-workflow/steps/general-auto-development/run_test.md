Run the generated and existing automated tests.

This step is executed by the Python function `run_pytest`.

Expected behavior:
- Run the configured test command when provided.
- Otherwise run the project default test command.
- Write `output/test-result.md`.
- On failure, pass the concrete stderr/stdout back into workflow retry feedback.
- Retry Build for implementation failures.
- Retry Generate Tests for invalid test imports or broken generated tests.
