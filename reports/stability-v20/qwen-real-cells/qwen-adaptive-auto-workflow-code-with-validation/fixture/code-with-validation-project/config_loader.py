import json
from typing import Any, Dict


def load_config(path: str) -> Dict[str, Any]:
    """Load a JSON configuration file.

    Args:
        path: Path to the JSON file.

    Returns:
        Parsed JSON as a dictionary.

    Raises:
        FileNotFoundError: If the file does not exist.
        json.JSONDecodeError: If the file contents are not valid JSON.
    """
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("Usage: python config_loader.py <path_to_json>")
    else:
        config = load_config(sys.argv[1])
        print(config)
