import pytest
from policy import violations


@pytest.mark.parametrize("pw,banned,exp", [
    ("Abcdefghij12", (), []), ("Abcdefghij1", (), ["length"]), ("abcdefghijkl", (), ["digit", "upper"]),
    ("ABCDEFGHIJ12", (), ["lower"]), ("Abcdefg hij12", (), ["space"]), ("Abcdefg\thij12", (), ["space"]),
    ("Password1234", ["password1234"], ["banned"]), ("", (), ["length", "digit", "upper", "lower"]),
    ("aaaaaaaaaaa1", (), ["upper"]),
])
def test_violations(pw, banned, exp):
    assert violations(pw, banned) == exp
