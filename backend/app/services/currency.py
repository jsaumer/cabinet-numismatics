"""Currency conversion via cached exchange rates (frankfurter.app: free,
keyless, ECB daily rates). Same cache discipline as spot prices: 24h TTL,
stale beats nothing, unavailable means the amount is excluded (never guessed).
"""

import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy.orm import Session

from app.models import ExchangeRate

CACHE_TTL = timedelta(hours=24)
RATE_API = "https://api.frankfurter.dev/v1/latest"
# After a failed fetch the pair is left alone this long: without it, a rate
# the service doesn't carry (or an upstream that is down) cost one request,
# with its five-second timeout, for every amount on every page.
FAILURE_BACKOFF_S = 120
_failed: dict[tuple[str, str], float] = {}  # pair -> time.monotonic() of the failure


def reset_memory() -> None:
    _failed.clear()


def _failed_recently(pair: tuple[str, str]) -> bool:
    at = _failed.get(pair)
    return at is not None and time.monotonic() - at < FAILURE_BACKOFF_S


class RateUnavailable(Exception):
    pass


def fetch_rate(base: str, quote: str) -> Decimal:
    try:
        resp = httpx.get(
            RATE_API, params={"from": base, "to": quote}, timeout=5.0, follow_redirects=True
        )
        resp.raise_for_status()
        rate = Decimal(str(resp.json()["rates"][quote]))
    except (httpx.HTTPError, KeyError, ValueError, ArithmeticError) as exc:
        raise RateUnavailable(f"Rate fetch {base}->{quote} failed: {exc}") from exc
    if rate <= 0:
        raise RateUnavailable(f"Rate fetch {base}->{quote} returned {rate}")
    return rate


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def get_rate(db: Session, base: str, quote: str, fetch: bool = True) -> Decimal | None:
    """Cached rate base→quote, or None if unobtainable. Never raises. With
    `fetch=False` only the cache is read, however old: the share view's
    public routes never make a network call."""
    if base == quote:
        return Decimal(1)
    cached = db.get(ExchangeRate, (base, quote))
    if not fetch:
        return Decimal(cached.rate) if cached is not None else None
    now = datetime.now(timezone.utc)
    if cached is not None and now - _as_utc(cached.fetched_at) < CACHE_TTL:
        return Decimal(cached.rate)
    stale = Decimal(cached.rate) if cached is not None else None  # beats nothing
    if _failed_recently((base, quote)):
        return stale
    try:
        rate = fetch_rate(base, quote)
    except RateUnavailable:
        if len(_failed) > 1000:  # pairs come from the data; keep the memory small
            _failed.clear()
        _failed[(base, quote)] = time.monotonic()
        return stale
    _failed.pop((base, quote), None)
    if cached is None:
        cached = ExchangeRate(base=base, quote=quote, source="frankfurter.app")
        db.add(cached)
    cached.rate = rate
    cached.source = "frankfurter.app"
    cached.fetched_at = now
    # Commit so the cache survives read-only requests (which never commit).
    db.commit()
    return rate


class Converter:
    """Converts amounts into one display currency, memoizing rates per request.
    Tracks whether anything was converted or had to be excluded."""

    def __init__(self, db: Session, display: str, fetch: bool = True):
        self.db = db
        self.display = display
        self.fetch = fetch  # False: cached rates only, never a request
        self.converted = 0
        self.excluded = 0
        self._rates: dict[str, Decimal | None] = {}  # one lookup per currency

    def convert(self, amount: float | Decimal | None, currency: str) -> float | None:
        """Amount in display currency, or None (and counted) if no rate."""
        if amount is None:
            return None
        if currency == self.display:
            return float(amount)
        if currency not in self._rates:
            self._rates[currency] = get_rate(self.db, currency, self.display, fetch=self.fetch)
        rate = self._rates[currency]
        if rate is None:
            self.excluded += 1
            return None
        self.converted += 1
        return float(Decimal(amount) * rate)
