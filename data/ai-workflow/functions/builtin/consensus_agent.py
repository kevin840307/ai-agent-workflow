from __future__ import annotations

FUNCTION_META = {
    "id": "consensus_agent",
    "label": "Consensus Agent",
    "description": "Run multiple internal agent generations with per-agent function checks and retry in one visible workflow step.",
    "ui": {"supportsPrompt": True, "supportsAgent": True, "tabs": ["basic", "sources", "retry", "advanced"], "promptDefaults": True},
}


def run(context, artifact=None):
    raise RuntimeError("consensus_agent is executed by the workflow runtime, not directly as a Python asset.")
