import json
from pathlib import Path
from typing import Any, Dict

def load_config(config_path: str | Path) -> Dict[str, Any]:
    """Load a JSON configuration file and return its contents as a dictionary.

    Args:
        config_path: Path to the JSON file. Can be a string or a ``Path`` object.

    Returns:
        The parsed JSON content as a ``dict``.
    """
    path = Path(config_path)
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)
