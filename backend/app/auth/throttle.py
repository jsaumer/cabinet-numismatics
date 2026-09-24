"""Sign-in throttles, in memory. Constants, not settings.

| Bucket        | Free                  | Then                                             |
| ------------- | --------------------- | ------------------------------------------------ |
| `user:<name>` | 5 failures            | wait 2^(n-5) s after the last, at most 60 s      |
| `addr:<ip>`   | 20 failures           | the same curve from the 20th                     |
| global        | 60 checks a minute    | 429                                              |
| `setup:<ip>`  | 5 wrong codes         | 429 until 15 minutes after the last              |
| `share:<ip>`  | 20 failed lookups     | the same curve as `addr`                         |
| share, global | 300 failed lookups a minute, all addresses | 429                     |
| `oidc:<ip>`   | 20 failed sign-on callbacks | the same curve as `addr`                   |
| oidc, global  | 300 failed callbacks a minute, all addresses | 429                    |

Never a lock-out. A bucket forgets its failures 15 minutes after the last
one, and on a success. One bounded map of at most MAX_KEYS entries, oldest
dropped first; a restart clears everything. Failed share lookups (v0.32.0)
have a bounded map of their own, so a flood of them from many addresses can
never push a sign-in, address, or setup bucket out; an IPv6 address is
counted by its /64, which is what one client usually holds. Failed single
sign-on callbacks (v0.33.0, CR-09) get a third map, keyed the same way, for
the same reason. A sign-in attempt is counted
by `attempt` before its password is checked, so parallel requests can't all
pass on the count as it was. A known-device cookie lifts the user, address,
and global limits (the caller skips `attempt` and `check_global`), never the
setup one.

`reset-password` in the container can't reach this process's memory, so it
touches a flag file on the state volume, and every check clears the map when
that file's time has changed.
"""

import ipaddress
import math
import threading
from collections import OrderedDict, deque
from dataclasses import dataclass
from pathlib import Path

from app.auth import common

WINDOW = 15 * 60
MAX_KEYS = 10_000
CAP = 60
FREE = {"user": 5, "addr": 20, "share": 20, "oidc": 20}
SETUP_FREE = 5
GLOBAL_PER_MINUTE = 60
SHARE_GLOBAL_PER_MINUTE = 300
OIDC_GLOBAL_PER_MINUTE = 300
RESET_FLAG = "throttle_reset"


class Throttled(Exception):
    def __init__(self, wait: float):
        super().__init__("Too many attempts. Try again shortly.")
        self.retry_after = max(1, math.ceil(wait))


@dataclass
class _Entry:
    failures: int = 0
    last: float = 0.0


_lock = threading.Lock()
_entries: OrderedDict[str, _Entry] = OrderedDict()
_checks: deque[float] = deque()
_flag_seen: tuple[bool, float | None] | None = None
# Failed share lookups: their own map and their own global count.
_shares: OrderedDict[str, _Entry] = OrderedDict()
_share_failures: deque[float] = deque()
# Failed single sign-on callbacks: the same again, apart from both.
_oidc: OrderedDict[str, _Entry] = OrderedDict()
_oidc_failures: deque[float] = deque()
# The kinds whose buckets live in a map of their own, keyed by address.
_APART = {"share": (_shares, _share_failures), "oidc": (_oidc, _oidc_failures)}


def _key(kind: str, value: str) -> str:
    return f"{kind}:{value}"


def _map(key: str) -> OrderedDict[str, _Entry]:
    kind = key.split(":", 1)[0]
    return _APART[kind][0] if kind in _APART else _entries


def share_address(address: str) -> str:
    """The bucket for a share lookup: an IPv6 address by its /64 (a single
    client usually holds the whole prefix), anything else as given."""
    try:
        found = ipaddress.ip_address(address)
    except ValueError:
        return address
    if found.version == 6:
        if found.ipv4_mapped is not None:
            return str(found.ipv4_mapped)
        return str(ipaddress.ip_network(f"{found}/64", strict=False))
    return str(found)


def _value(kind: str, value: str) -> str:
    return share_address(value) if kind in _APART else value


def _live(key: str, t: float) -> _Entry | None:
    entries = _map(key)
    entry = entries.get(key)
    if entry is not None and t - entry.last >= WINDOW:
        del entries[key]
        return None
    return entry


def _wait(kind: str, entry: _Entry, t: float) -> float:
    if kind == "setup":
        return entry.last + WINDOW - t if entry.failures >= SETUP_FREE else 0.0
    free = FREE[kind]
    if entry.failures < free:
        return 0.0
    return entry.last + min(CAP, 2 ** (entry.failures - free)) - t


def wait(kind: str, value: str) -> float:
    """Seconds until the next attempt in this bucket is allowed (0: now)."""
    _apply_reset_flag()
    t = common.monotonic()
    with _lock:
        entry = _live(_key(kind, _value(kind, value)), t)
        return max(0.0, _wait(kind, entry, t)) if entry else 0.0


def check(*buckets: tuple[str, str]) -> None:
    """Raise Throttled when any of these (kind, value) buckets must wait."""
    longest = max((wait(kind, value) for kind, value in buckets), default=0.0)
    if longest > 0:
        raise Throttled(longest)


def attempt(*buckets: tuple[str, str]) -> None:
    """Check these buckets and, in the same step under the lock, count this
    attempt as a failure in each: requests queued behind the password check
    all see the attempts ahead of them, so a burst can't all read the old
    count. `succeed` takes it back; a failure has nothing more to count."""
    _apply_reset_flag()
    t = common.monotonic()
    with _lock:
        longest = 0.0
        for kind, value in buckets:
            entry = _live(_key(kind, value), t)
            if entry is not None:
                longest = max(longest, _wait(kind, entry, t))
        if longest > 0:
            raise Throttled(longest)
        for kind, value in buckets:
            key = _key(kind, value)
            entry = _live(key, t) or _Entry()
            entry.failures += 1
            entry.last = t
            _entries[key] = entry
            _entries.move_to_end(key)
        while len(_entries) > MAX_KEYS:
            _entries.popitem(last=False)


def check_global() -> None:
    """Count one password check against the global limit, or refuse it."""
    _apply_reset_flag()
    t = common.monotonic()
    with _lock:
        while _checks and t - _checks[0] >= 60:
            _checks.popleft()
        if len(_checks) >= GLOBAL_PER_MINUTE:
            raise Throttled(_checks[0] + 60 - t)
        _checks.append(t)


def _count(key: str, t: float) -> None:
    """One more failure in this bucket, in its own map; the map's oldest
    entries go past MAX_KEYS. Under the lock."""
    entries = _map(key)
    entry = _live(key, t) or _Entry()
    entry.failures += 1
    entry.last = t
    entries[key] = entry
    entries.move_to_end(key)
    while len(entries) > MAX_KEYS:
        entries.popitem(last=False)


def fail(kind: str, value: str) -> None:
    t = common.monotonic()
    with _lock:
        _count(_key(kind, _value(kind, value)), t)


def _address_failure(kind: str, address: str, cap: int) -> float:
    t = common.monotonic()
    key = _key(kind, share_address(address))
    failures = _APART[kind][1]
    with _lock:
        entry = _live(key, t)
        waiting = max(0.0, _wait(kind, entry, t)) if entry else 0.0
        while failures and t - failures[0] >= 60:
            failures.popleft()
        if len(failures) >= cap:
            waiting = max(waiting, failures[0] + 60 - t)
        if waiting > 0:
            return waiting
        _count(key, t)
        failures.append(t)
        return 0.0


def share_failure(address: str) -> float:
    """A failed share lookup from this address. Inside the address's wait,
    or past SHARE_GLOBAL_PER_MINUTE failures across every address, nothing is
    counted and the seconds to wait come back (the caller answers 429);
    otherwise the failure is counted and 0 comes back (the caller answers
    404). A lookup that succeeds never comes here, so a live link is never
    throttled."""
    return _address_failure("share", address, SHARE_GLOBAL_PER_MINUTE)


def oidc_failure(address: str) -> float:
    """A failed single sign-on callback from this address (v0.33.0, CR-09),
    the same way as `share_failure`, in its own map and with its own global
    count (OIDC_GLOBAL_PER_MINUTE): a callback that succeeds never comes
    here, and a flood of failures can never push a sign-in bucket out."""
    return _address_failure("oidc", address, OIDC_GLOBAL_PER_MINUTE)


def succeed(kind: str, value: str) -> None:
    key = _key(kind, _value(kind, value))
    with _lock:
        _map(key).pop(key, None)


def clear() -> None:
    global _flag_seen
    with _lock:
        _entries.clear()
        _checks.clear()
        _shares.clear()
        _share_failures.clear()
        _oidc.clear()
        _oidc_failures.clear()
        _flag_seen = None


def size() -> int:
    """Sign-in, address, and setup buckets; share and single sign-on buckets
    are `share_size` and `oidc_size`."""
    return len(_entries)


def share_size() -> int:
    return len(_shares)


def oidc_size() -> int:
    return len(_oidc)


def _flag_path() -> Path:
    from app.services import archive_keys

    return archive_keys.state_dir() / RESET_FLAG


def _flag_state() -> tuple[bool, float | None]:
    try:
        return True, _flag_path().stat().st_mtime_ns
    except OSError:
        return False, None


def _apply_reset_flag() -> None:
    """Clear the map when `reset-password` has touched the flag since the
    last look. The first look only notes the flag: nothing is counted yet."""
    global _flag_seen
    state = _flag_state()
    with _lock:
        if _flag_seen is not None and state != _flag_seen and state[0]:
            _entries.clear()
            _checks.clear()
        _flag_seen = state


def request_reset() -> None:
    """For the container command: tell the running backend to forget every
    throttle. Written with a fresh time each call."""
    path = _flag_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{common.now().isoformat()}\n", encoding="ascii")
