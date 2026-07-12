from pathlib import Path
import importlib.util
target = Path('sort_utils.py')
assert target.exists(), 'sort_utils.py is missing'
spec = importlib.util.spec_from_file_location('sort_utils', target)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert mod.bubble_sort([3, 1, 2]) == [1, 2, 3]
assert mod.bubble_sort([2, 2, -1]) == [-1, 2, 2]
print('validation ok')
