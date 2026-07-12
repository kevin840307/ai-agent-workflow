from pathlib import Path
import sys
root=Path(__file__).parent; sys.path.insert(0,str(root/"src"))
from texttools import parse_key_values
assert parse_key_values("a=1,b=two")=={"a":"1","b":"two"}
for bad in ["a=1,a=2","broken"]:
    try:
        parse_key_values(bad)
    except ValueError:
        pass
    else:
        raise AssertionError(f"must reject {bad}")
assert (root/"tests"/"test_parser.py").is_file()
print("PASS")
