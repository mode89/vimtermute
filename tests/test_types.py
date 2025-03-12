# pylint: disable=import-error
# pylint: disable=missing-docstring
import pytest
from vimtermute.types import Vector, record

def test_vector():
    v1 = Vector(1, 2, 3)
    assert len(v1) == 3
    assert v1[0] == 1
    assert v1[1] == 2
    assert v1[2] == 3
    assert v1[-1] == 3
    assert v1[-2] == 2
    with pytest.raises(IndexError):
        assert v1[3] == 4
    with pytest.raises(TypeError):
        v1[0] = 4

    v2 = v1.append(42)
    assert len(v1) == 3
    assert v1[0] == 1
    assert v1[1] == 2
    assert v1[2] == 3
    with pytest.raises(IndexError):
        assert v1[3] == 4
    assert isinstance(v2, Vector)
    assert len(v2) == 4
    assert v2[0] == 1
    assert v2[1] == 2
    assert v2[2] == 3
    assert v2[3] == 42

    v3 = v1.assoc(0, 4, 2, 5)
    assert len(v1) == 3
    assert v1[0] == 1
    assert v1[1] == 2
    assert v1[2] == 3
    with pytest.raises(IndexError):
        assert v1[3] == 4
    assert isinstance(v3, Vector)
    assert len(v3) == 3
    assert v3[0] == 4
    assert v3[1] == 2
    assert v3[2] == 5

def test_record():
    Record = record("Record", "a", "b", "c") # pylint: disable=invalid-name

    r1 = Record(a=1, b=2, c=3)
    with pytest.raises(AttributeError):
        r1.a = 4
    assert r1.a == 1
    assert r1.b == 2
    assert r1.c == 3
    with pytest.raises(AttributeError):
        assert r1.d == 4

    r2 = r1.assoc(a=4, b=5)
    assert r2.a == 4
    assert r2.b == 5
    assert r2.c == 3
