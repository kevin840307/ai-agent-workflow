def bubble_sort(arr):
    result = list(arr)
    n = len(result)
    for i in range(n):
        swapped = False
        for j in range(n - i - 1):
            if result[j] > result[j + 1]:
                result[j], result[j + 1] = result[j + 1], result[j]
                swapped = True
        if not swapped:
            break
    return result


def selection_sort(arr):
    result = list(arr)
    n = len(result)
    for i in range(n):
        min_idx = i
        for j in range(i + 1, n):
            if result[j] < result[min_idx]:
                min_idx = j
        result[i], result[min_idx] = result[min_idx], result[i]
    return result


def insertion_sort(arr):
    result = list(arr)
    for i in range(1, len(result)):
        key = result[i]
        j = i - 1
        while j >= 0 and result[j] > key:
            result[j + 1] = result[j]
            j -= 1
        result[j + 1] = key
    return result


def quick_sort(arr):
    result = list(arr)
    _quick_sort(result, 0, len(result) - 1)
    return result


def _quick_sort(arr, low, high):
    if low < high:
        p = _partition(arr, low, high)
        _quick_sort(arr, low, p - 1)
        _quick_sort(arr, p + 1, high)


def _partition(arr, low, high):
    pivot = arr[high]
    i = low - 1
    for j in range(low, high):
        if arr[j] <= pivot:
            i += 1
            arr[i], arr[j] = arr[j], arr[i]
    arr[i + 1], arr[high] = arr[high], arr[i + 1]
    return i + 1


def merge_sort(arr):
    result = list(arr)
    _merge_sort(result, 0, len(result) - 1)
    return result


def _merge_sort(arr, left, right):
    if left < right:
        mid = (left + right) // 2
        _merge_sort(arr, left, mid)
        _merge_sort(arr, mid + 1, right)
        _merge(arr, left, mid, right)


def _merge(arr, left, mid, right):
    left_part = arr[left:mid + 1]
    right_part = arr[mid + 1:right + 1]
    i = j = 0
    k = left
    while i < len(left_part) and j < len(right_part):
        if left_part[i] <= right_part[j]:
            arr[k] = left_part[i]
            i += 1
        else:
            arr[k] = right_part[j]
            j += 1
        k += 1
    while i < len(left_part):
        arr[k] = left_part[i]
        i += 1
        k += 1
    while j < len(right_part):
        arr[k] = right_part[j]
        j += 1
        k += 1


def heap_sort(arr):
    result = list(arr)
    n = len(result)

    def heapify(size, root):
        largest = root
        left = 2 * root + 1
        right = 2 * root + 2
        if left < size and result[left] > result[largest]:
            largest = left
        if right < size and result[right] > result[largest]:
            largest = right
        if largest != root:
            result[root], result[largest] = result[largest], result[root]
            heapify(size, largest)

    for i in range(n // 2 - 1, -1, -1):
        heapify(n, i)
    for i in range(n - 1, 0, -1):
        result[0], result[i] = result[i], result[0]
        heapify(i, 0)
    return result


def shell_sort(arr):
    result = list(arr)
    n = len(result)
    gap = n // 2
    while gap > 0:
        for i in range(gap, n):
            temp = result[i]
            j = i
            while j >= gap and result[j - gap] > temp:
                result[j] = result[j - gap]
                j -= gap
            result[j] = temp
        gap //= 2
    return result
