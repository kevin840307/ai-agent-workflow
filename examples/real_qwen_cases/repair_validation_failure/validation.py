import calculator
assert calculator.divide(8, 2) == 4
try:
    calculator.divide(1, 0)
except ZeroDivisionError:
    pass
else:
    raise AssertionError("divide by zero must raise ZeroDivisionError")
print("VALIDATION PASS: repair_validation_failure")
