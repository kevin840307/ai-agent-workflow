import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sort_utils import bubble_sort


def test_empty():
    assert bubble_sort([]) == []


def test_single():
    assert bubble_sort([5]) == [5]


def test_already_sorted():
    assert bubble_sort([1, 2, 3]) == [1, 2, 3]


def test_reverse_sorted():
    assert bubble_sort([3, 2, 1]) == [1, 2, 3]


def test_duplicates():
    assert bubble_sort([2, 2, -1]) == [-1, 2, 2]


def test_negatives():
    assert bubble_sort([-3, -1, -2]) == [-3, -2, -1]


def test_mixed():
    assert bubble_sort([3, 1, 2]) == [1, 2, 3]


def test_input_not_mutated():
    data = [3, 1, 2]
    bubble_sort(data)
    assert data == [3, 1, 2]


def test_returns_new_list():
    data = [1, 2, 3]
    result = bubble_sort(data)
    assert result is not data
