def bubble_sort(data):
    """Return a new list with the items of *data* sorted in ascending order.

    Uses the classic bubble sort algorithm and does not mutate the input.
    """
    arr = list(data)
    n = len(arr)
    for i in range(n):
        for j in range(0, n - i - 1):
            if arr[j] > arr[j + 1]:
                arr[j], arr[j + 1] = arr[j + 1], arr[j]
    return arr
