"""The dependencies v0.30.0 adds for sign-in, checked before anything uses them.

Stage 6 pins the real hashing parameters; this only proves the library is
installed, gives Argon2id, and round-trips. Small parameters keep it fast.
"""

import pytest
from argon2 import PasswordHasher, Type
from argon2.exceptions import VerifyMismatchError


def test_argon2id_round_trip():
    hasher = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1, type=Type.ID)
    stored = hasher.hash("correct horse battery staple")
    assert stored.startswith("$argon2id$")
    assert hasher.verify(stored, "correct horse battery staple")
    with pytest.raises(VerifyMismatchError):
        hasher.verify(stored, "wrong")
