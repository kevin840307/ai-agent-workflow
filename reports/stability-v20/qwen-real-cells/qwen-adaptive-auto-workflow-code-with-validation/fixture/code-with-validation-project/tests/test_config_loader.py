import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config_loader


def test_load_config_valid():
    data = {"name": "test", "value": 42}
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        json.dump(data, f)
        path = f.name
    try:
        result = config_loader.load_config(path)
        assert result == data
    finally:
        Path(path).unlink()


def test_load_config_missing_file():
    missing = Path(tempfile.gettempdir()) / "does_not_exist_12345.json"
    try:
        config_loader.load_config(str(missing))
        assert False, "Expected FileNotFoundError"
    except FileNotFoundError:
        pass


def test_load_config_invalid_json():
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        f.write("{not valid json")
        path = f.name
    try:
        try:
            config_loader.load_config(path)
            assert False, "Expected JSONDecodeError"
        except json.JSONDecodeError:
            pass
    finally:
        Path(path).unlink()


def test_load_config_real_project_file():
    project_root = Path(__file__).resolve().parent.parent
    config_path = project_root / "opencode.json"
    config = config_loader.load_config(str(config_path))
    assert isinstance(config, dict)
    assert len(config) > 0
