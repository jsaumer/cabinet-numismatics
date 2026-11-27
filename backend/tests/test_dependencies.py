"""The dependencies v0.30.0 adds for sign-in, checked before anything uses them.

Stage 6 pins the real hashing parameters; this only proves the library is
installed, gives Argon2id, and round-trips. Small parameters keep it fast.
"""

import subprocess
import sys

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


@pytest.mark.skipif(sys.version_info < (3, 11), reason="httpx2 has no release for Python 3.10")
def test_the_test_client_runs_on_httpx2():
    """Starlette's test client prefers httpx2 and warns that plain httpx is
    on its way out. With the dev extra installed it must find httpx2 and say
    nothing, so the day Starlette drops the fallback isn't the day the whole
    suite stops importing. A fresh interpreter, since the module is long
    imported here and a warning is only raised once."""
    code = (
        "import warnings\n"
        "warnings.simplefilter('error')\n"
        "import starlette.testclient as tc\n"
        "print(tc.httpx.__name__)\n"
    )
    ran = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.strip() == "httpx2"
