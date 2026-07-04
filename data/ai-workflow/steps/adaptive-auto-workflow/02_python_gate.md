# Python Gate

This step is executed by the `adaptive_python_gate` Python function.

Behavior:
- Run a configured validation script when provided.
- Otherwise run pytest when tests exist.
- Otherwise write a skipped PASS because no Python gate is available.

Failures retry `Auto Generation Workflow` with the concrete gate output.
