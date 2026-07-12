from pathlib import Path
import importlib.util

root = Path(__file__).parent
target = root / "bubble_sort.py"
assert target.is_file(), "missing bubble_sort.py"
spec = importlib.util.spec_from_file_location("bubble_sort", target)
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
source = [3, -1, 3, 0]
assert module.bubble_sort(source) == [-1, 0, 3, 3]
assert source == [3, -1, 3, 0], "input must not be mutated"
assert (root / "tests" / "test_bubble_sort.py").is_file()
print("PASS")
