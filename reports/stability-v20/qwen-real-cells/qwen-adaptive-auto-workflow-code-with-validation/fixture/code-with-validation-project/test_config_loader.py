"""CLI demo helper for ``config_loader``.

NOTE: the pytest test suite for ``config_loader`` lives under ``tests/``. This
file is intentionally NOT a pytest test module so it does not mix test code with
production source at the project root. It only provides a small demo entry point.

Usage:
    python test_config_loader.py <path_to_json>
"""

import json
import sys

from config_loader import load_config


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python test_config_loader.py <path_to_json>")
    else:
        print(json.dumps(load_config(sys.argv[1]), indent=2))
