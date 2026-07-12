from pathlib import Path
import sys, tempfile, yaml
root=Path(__file__).parent; sys.path.insert(0,str(root))
from config_store import load_config, get_value, set_value
with tempfile.TemporaryDirectory() as tmp:
    path=Path(tmp)/"config.yaml"; path.write_text("name: demo\ncount: 1\n",encoding="utf-8")
    assert load_config(path)["name"]=="demo"
    assert get_value(path,"count")==1
    set_value(path,"count",2)
    data=yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data=={"name":"demo","count":2}
assert (root/"tests"/"test_config_store.py").is_file()
print("PASS")
