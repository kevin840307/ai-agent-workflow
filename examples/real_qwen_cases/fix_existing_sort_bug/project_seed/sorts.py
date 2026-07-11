def selection_sort(data):
    result = list(data)
    for i in range(len(result)):
        minimum = i
        for j in range(i + 1, len(result)):
            if result[j] > result[minimum]:  # intentional bug
                minimum = j
        result[i], result[minimum] = result[minimum], result[i]
    return result
