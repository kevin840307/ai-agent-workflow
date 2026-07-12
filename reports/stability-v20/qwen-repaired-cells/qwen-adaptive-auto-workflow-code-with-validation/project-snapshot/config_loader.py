"""Utility to load JSON configuration files.

Provides a single function :func:`load_config` which reads a JSON file and
returns its contents as a ``dict``. Errors are propagated as ``FileNotFoundError``
if the path does not exist and ``json.JSONDecodeError`` for malformed JSON.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Union


def load_config(path: Union[str, Path]) -> dict:
    """Load a JSON configuration file.

    Args:
        path: Path to the JSON file, as a string or :class:`pathlib.Path`.

    Returns:
        The parsed JSON content as a dictionary.

    Raises:
        FileNotFoundError: If the file does not exist.
        json.JSONDecodeError: If the file content is not valid JSON.
    """
    file_path = Path(path)
    # Let the built‑in open raise FileNotFoundError if missing
    with file_path.open('r', encoding='utf-8') as f:
        return json.load(f)
