import unittest
from sort_utils import bubble_sort

class TestBubbleSort(unittest.TestCase):
    def test_basic_integer_sort(self):
        self.assertEqual(bubble_sort([3, 1, 2]), [1, 2, 3])

    def test_empty_list(self):
        data = []
        result = bubble_sort(data)
        self.assertEqual(result, [])
        self.assertIsNot(data, result)  # ensure original is not mutated

    def test_tuple_input(self):
        self.assertEqual(bubble_sort((4, 2, 5)), [2, 4, 5])

    def test_already_sorted(self):
        self.assertEqual(bubble_sort([1, 2, 3, 4]), [1, 2, 3, 4])

    def test_mixed_type_error(self):
        with self.assertRaises(TypeError):
            bubble_sort([1, 'a', 3])

    def test_input_unchanged(self):
        data = [5, 3, 4]
        copy = list(data)
        bubble_sort(data)
        self.assertEqual(data, copy)

if __name__ == '__main__':
    unittest.main()
