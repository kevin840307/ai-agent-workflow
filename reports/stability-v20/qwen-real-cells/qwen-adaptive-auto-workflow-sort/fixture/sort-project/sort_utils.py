def bubble_sort(data):
    """Return a new list with the items of *data* sorted in ascending order using bubble sort.
    The original *data* is not modified.
    """
    # Work on a copy to avoid mutating the input
    arr = list(data)
    n = len(arr)
    for i in range(n):
        # Last i elements are already in place
        for j in range(0, n - i - 1):
            if arr[j] > arr[j + 1]:
                arr[j], arr[j + 1] = arr[j + 1], arr[j]
    return arr
