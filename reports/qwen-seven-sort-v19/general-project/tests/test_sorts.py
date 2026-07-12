import unittest
from sorts import (
    bubble_sort,
    selection_sort,
    insertion_sort,
    quick_sort,
    merge_sort,
    heap_sort,
    shell_sort,
)

class TestSortingAlgorithms(unittest.TestCase):
    def setUp(self):
        self.test_cases = [
            [],
            [1],
            [1, 2, 3, 4, 5],
            [5, 4, 3, 2, 1],
            [3, 1, 2, 3, 1, 2],
        ]
        self.expected = [sorted(case) for case in self.test_cases]

    def _assert_sort(self, func):
        for inp, exp in zip(self.test_cases, self.expected):
            self.assertEqual(func(inp), exp)

    def test_bubble_sort(self):
        self._assert_sort(bubble_sort)

    def test_selection_sort(self):
        self._assert_sort(selection_sort)

    def test_insertion_sort(self):
        self._assert_sort(insertion_sort)

    def test_quick_sort(self):
        self._assert_sort(quick_sort)

    def test_merge_sort(self):
        self._assert_sort(merge_sort)

    def test_heap_sort(self):
        self._assert_sort(heap_sort)

    def test_shell_sort(self):
        self._assert_sort(shell_sort)

if __name__ == "__main__":
    unittest.main()
