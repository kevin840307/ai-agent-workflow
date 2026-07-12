from pathlib import Path
import sys
root=Path(__file__).parent; sys.path.insert(0,str(root))
from calculator import safe_divide
assert safe_divide(8,2)==4.0
try:
    safe_divide(1,0)
except ValueError:
    pass
else:
    raise AssertionError("division by zero must raise ValueError")
assert (root/"tests"/"test_calculator.py").is_file()
print("PASS")
