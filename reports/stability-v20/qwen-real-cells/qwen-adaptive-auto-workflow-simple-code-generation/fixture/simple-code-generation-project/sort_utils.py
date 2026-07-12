def bubble_sort(data):
    """Return a new list containing the items from *data* sorted in ascending order using bubble sort.
    The input *data* is not mutated.
    """
    # Make a shallow copy to avoid mutating the original iterable
    arr = list(data)
    n = len(arr)
    for i in range(n):
        # Early exit flag for optimisation
        swapped = False
        for j in range(0, n - i - 1):
            if arr[j] > arr[j + 1]:
                arr[j], arr[j + 1] = arr[j + 1], arr[j]
                swapped = True
        if not swapped:
            break
    return arr
