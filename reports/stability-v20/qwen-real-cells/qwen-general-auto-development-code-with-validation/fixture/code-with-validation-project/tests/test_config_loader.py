import json
from pathlib import Path

import pytest

from config_loader import load_config


def test_load_config_returns_dict(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text('{"name": "demo", "value": 42}', encoding="utf-8")

    result = load_config(config_file)

    assert isinstance(result, dict)
    assert result == {"name": "demo", "value": 42}


def test_load_config_accepts_string_path(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text('{"key": "val"}', encoding="utf-8")

    result = load_config(str(config_file))

    assert result == {"key": "val"}


def test_load_config_raises_on_missing_file():
    with pytest.raises(FileNotFoundError):
        load_config(Path("does_not_exist_12345.json"))


def test_load_config_raises_on_invalid_json(tmp_path):
    config_file = tmp_path / "bad.json"
    config_file.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        load_config(config_file)
