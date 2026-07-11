import sorts
assert sorts.selection_sort([]) == []
assert sorts.selection_sort([3, -1, 3, 2]) == [-1, 2, 3, 3]
assert sorts.selection_sort([1]) == [1]
print("VALIDATION PASS: fix_existing_sort_bug")
