from math_utils import clamp

def test_clamp():
    assert clamp(10, 0, 5) == 5
