from pathlib import Path
import importlib.util

path = Path("bubble_sort.py")
assert path.exists(), "bubble_sort.py 不存在"
spec = importlib.util.spec_from_file_location("bubble_sort", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
source = [3, 1, 2, -1]
result = module.bubble_sort(source)
assert result == [-1, 1, 2, 3], result
assert source == [3, 1, 2, -1], "bubble_sort 修改了輸入列表"
print("VALIDATION PASS: bubble_sort_new")
