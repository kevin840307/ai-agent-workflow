from sort_utils import bubble_sort


def test_basic_sorting():
    data = [3, 1, 2]
    result = bubble_sort(data)
    assert result == [1, 2, 3]
    assert data == [3, 1, 2]


def test_duplicates_and_negatives():
    data = [2, 2, -1]
    result = bubble_sort(data)
    assert result == [-1, 2, 2]
    assert data == [2, 2, -1]


def test_empty_list():
    data = []
    result = bubble_sort(data)
    assert result == []
    assert data == []
