import random

import pytest

import sorts

ALGORITHMS = [
    sorts.bubble_sort,
    sorts.selection_sort,
    sorts.insertion_sort,
    sorts.quick_sort,
    sorts.merge_sort,
    sorts.heap_sort,
    sorts.shell_sort,
]

CASES = [
    [],
    [1],
    [1, 2, 3],
    [3, 2, 1],
    [4, 2, 7, 1, 3],
    [5, 5, 5, 5],
    [2, 2, 1, 3, 3, 1],
    [9, 8, 7, 6, 5, 4, 3, 2, 1],
    [1, 3, 2, 4, 5, 7, 6, 8, 0, 9],
]


@pytest.mark.parametrize("algo", ALGORITHMS)
@pytest.mark.parametrize("case", CASES)
def test_sorting(algo, case):
    result = algo(case)
    assert result == sorted(case)
    assert all(
        result[i] <= result[i + 1] for i in range(len(result) - 1)
    )


@pytest.mark.parametrize("algo", ALGORITHMS)
def test_no_input_mutation(algo):
    data = [3, 1, 2]
    original = list(data)
    algo(data)
    assert data == original


def test_random_case():
    rng = random.Random(42)
    case = [rng.randint(-100, 100) for _ in range(200)]
    for algo in ALGORITHMS:
        assert algo(case) == sorted(case)
