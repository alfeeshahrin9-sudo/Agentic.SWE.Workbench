from src.calculator import add


def test_add_simple():
    assert add(2, 2) == 4


def test_add_zeros():
    assert add(0, 5) == 5
