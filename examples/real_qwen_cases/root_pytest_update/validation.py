from pathlib import Path
import sys
root=Path(__file__).parent; sys.path.insert(0,str(root))
from math_utils import clamp
assert clamp(10,0,5)==5
assert clamp(-1,0,5)==0
assert clamp(3,0,5)==3
try:
    clamp(1,5,0)
except ValueError:
    pass
else:
    raise AssertionError("minimum > maximum must raise ValueError")
assert (root/"tests"/"test_math_utils.py").is_file()
assert not (root/"test_math_utils.py").exists(), "root duplicate test must be removed"
print("PASS")
