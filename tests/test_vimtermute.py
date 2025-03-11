# pylint: disable=import-error
# pylint: disable=missing-docstring
import pytest
import vimtermute

def test_vector():
    v1 = vimtermute.Vector(1, 2, 3)
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
    assert isinstance(v2, vimtermute.Vector)
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
    assert isinstance(v3, vimtermute.Vector)
    assert len(v3) == 3
    assert v3[0] == 4
    assert v3[1] == 2
    assert v3[2] == 5
