from __future__ import annotations

"""Stable launcher used by Qwen Code/OpenCode interactive slash commands.

The custom command is executed from the user's project directory, not from the
controller source tree.  This launcher adds the controller root to ``sys.path``
so ``app.cli.aiwf`` remains importable after project- or user-scoped command
installation.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.cli.aiwf import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
