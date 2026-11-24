
def test_one():
    assert 1 == 10/10

def test_two():
    assert 2 == 3

def test_three():
    assert "hello" == "world"

import pytest

@pytest.mark.parametrize('i', range(100))
def test_many(i):
    test_one()

class TestStuff:

    def test_final(self):
        crash
