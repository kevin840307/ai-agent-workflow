from pathlib import Path
import json
import config_loader
sample = Path("sample.json")
sample.write_text(json.dumps({"name": "demo", "enabled": True}), encoding="utf-8")
assert config_loader.load_config(sample) == {"name": "demo", "enabled": True}
try:
    config_loader.load_config("missing.json")
except FileNotFoundError:
    pass
else:
    raise AssertionError("missing file should raise FileNotFoundError")
print("VALIDATION PASS: json_config_loader")
