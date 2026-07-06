# Real Agent Smoke

Mock E2E validates the controller. Real smoke validates Qwen/OpenCode behavior.

First run a self-prompt check:

```bash
python scripts/run_real_agent_smoke.py --self-prompt-test --agent qwen --workflow adaptive-auto-workflow --case sort
```

Then run a real agent smoke when Qwen/OpenCode is available:

```bash
python scripts/run_real_agent_smoke.py --agent qwen --workflow adaptive-auto-workflow --case sort
python scripts/run_real_agent_smoke.py --agent qwen --workflow general-auto-development --case config-loader
python scripts/run_real_agent_smoke.py --agent opencode --workflow adaptive-auto-workflow --case readme
```

The script refuses real runs when `QWEN_MOCK=1`, unless `--allow-mock` is explicitly provided.
