from pathlib import Path
import sorts
assert sorts.insertion_sort([4, 1, 3, 1]) == [1, 1, 3, 4]
root_test = Path("test_sorts.py")
assert root_test.exists(), "既有 test_sorts.py 被移除"
assert "insertion_sort" in root_test.read_text(encoding="utf-8"), "test_sorts.py 未新增 insertion_sort 測試"
assert not Path("tests/test_sorts.py").exists(), "產生了重複 tests/test_sorts.py"
print("VALIDATION PASS: root_pytest_update")
