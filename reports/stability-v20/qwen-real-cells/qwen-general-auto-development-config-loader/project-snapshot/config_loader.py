import json
from pathlib import Path
def load_config(path):
    with Path(path).open('r', encoding='utf-8') as f:
        return json.load(f)