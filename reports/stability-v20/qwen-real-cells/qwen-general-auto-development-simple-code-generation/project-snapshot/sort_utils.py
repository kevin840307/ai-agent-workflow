def bubble_sort(data):
    """Return a new list containing the items of *data* sorted in ascending order.

    The input sequence is **not** modified. A ``TypeError`` is raised if the
    elements cannot be compared with each other.
    """
    # Convert the input to a list to avoid mutating the original iterable.
    arr = list(data)
    n = len(arr)
    # Perform the bubble sort algorithm.
    for i in range(n):
        swapped = False
        # After each outer iteration, the largest element among the unsorted
        # portion is bubbled to its final position at ``n - i - 1``.
        for j in range(0, n - i - 1):
            try:
                if arr[j] > arr[j + 1]:
                    arr[j], arr[j + 1] = arr[j + 1], arr[j]
                    swapped = True
            except TypeError:
                # Re‑raise with a clear message while preserving the original
                # exception context for debugging.
                raise TypeError("Elements of the input are not comparable") from None
        if not swapped:
            break
    return arr
