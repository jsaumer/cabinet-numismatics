#!/usr/bin/env python3
"""Probe a price source against a real item and show exactly what came back.

The adapter tests use canned responses; this covers the other half — what the
live APIs actually return. It runs one adapter for one item and prints the
upstream calls made, the raw payload, and the estimate parsed out of it.
Nothing is written to `price_estimates`: this only looks.

    docker compose exec backend python scripts/check_sources.py --list
    docker compose exec backend python scripts/check_sources.py -s numista -i <item-id>
    docker compose exec backend python scripts/check_sources.py -s pcgs -i <item-id> --fresh

`--fresh` ignores the `source_cache` TTL to force a real request — each one
counts against the source's quota (Numista 2,000/month, PCGS 1,000/day).
Without it, a cached response is reused and the run costs nothing.

This lives with the backend rather than in the repo-root `scripts/` because it
imports the application; the scripts up there talk to the API or to Docker.
Credentials are read from Settings and are never printed.
"""

import argparse
import json
import sys
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Item, SourceCache
from app.services import app_settings, pricing

SOURCES = ("melt", "numista", "pcgs")
LIST_LIMIT = 3  # long lists (auction lots, price rows) are trimmed to this
STRING_LIMIT = 500  # long strings (e.g. PCGS CoinFactsNotes essays) are trimmed to this


def adapter_module(source: str):
    """The module backing a source, for spying on its requests. None for melt,
    which has no single upstream call to intercept."""
    if source == "numista":
        from app.services import numista

        return numista
    if source == "pcgs":
        from app.services import pcgs

        return pcgs
    return None


def trim(value, full: bool):
    """Shorten long lists and strings so one payload fits on a screen."""
    if full:
        return value
    if isinstance(value, list):
        head = [trim(v, full) for v in value[:LIST_LIMIT]]
        extra = len(value) - LIST_LIMIT
        return head + [f"… {extra} more"] if extra > 0 else head
    if isinstance(value, dict):
        return {k: trim(v, full) for k, v in value.items()}
    if isinstance(value, str) and len(value) > STRING_LIMIT:
        return value[:STRING_LIMIT] + f"... ({len(value) - STRING_LIMIT} more chars)"
    return value


def dump(label: str, payload, full: bool) -> None:
    print(f"\n{label}:")
    print(json.dumps(trim(payload, full), indent=2, default=str, ensure_ascii=False))


def describe(item: Item) -> str:
    bits = [item.year and str(item.year), item.mint_mark, item.denomination, item.country]
    return " ".join(b for b in bits if b)


def list_candidates(db) -> int:
    """Items any external source could plausibly price, and by what handle."""
    rows = db.execute(select(Item).order_by(Item.country, Item.year)).scalars().all()
    found = 0
    for item in rows:
        handles = []
        for ref in item.catalog_refs:
            if ref.catalog.lower() in ("numista", "pcgs"):
                handles.append(f"{ref.catalog}={ref.ref_code}")
        if (item.cert_service or "").upper() == "PCGS" and item.cert_number:
            handles.append(f"pcgs cert={item.cert_number}")
        if not handles:
            continue
        found += 1
        grade = item.grade.code if item.grade else "no grade"
        print(f"{item.id}  {describe(item):<40} {grade:<8} {', '.join(handles)}")
    if not found:
        print("No items carry a numista/pcgs catalog reference or a PCGS cert number.")
        print("Add one to an item, then re-run with -s <source> -i <item-id>.")
    return 0 if found else 1


def report_settings(db, source: str) -> None:
    enabled = bool(app_settings.get_setting(db, f"{source}_enabled"))
    print(f"source     : {source} ({'enabled' if enabled else 'DISABLED in Settings'})")
    if source != "melt":
        key = "numista_api_key" if source == "numista" else "pcgs_api_token"
        configured = bool(str(app_settings.get_setting(db, key)))
        print(f"credential : {'configured' if configured else 'MISSING — set it in Settings'}")


def probe(db, source: str, item_id: str, fresh: bool, full: bool) -> int:
    item = db.get(Item, item_id)
    if item is None:
        print(f"No item {item_id}. Try --list.", file=sys.stderr)
        return 2

    print(f"item       : {item.id}  {describe(item)}")
    print(f"grade      : {item.grade.code + ' (' + item.grade.scale + ')' if item.grade else '—'}")
    refs = ", ".join(f"{r.catalog}={r.ref_code}" for r in item.catalog_refs) or "—"
    print(f"refs       : {refs}")
    print(f"cert       : {item.cert_service or '—'} {item.cert_number or ''}".rstrip())
    report_settings(db, source)

    module = adapter_module(source)
    calls: list[tuple] = []
    if module is not None:
        original = module._request

        def spy(*args, **kwargs):
            # args[0] is the credential — deliberately never captured.
            path = args[1] if len(args) > 1 else kwargs.get("path")
            params = args[2] if len(args) > 2 else kwargs.get("params")
            try:
                payload = original(*args, **kwargs)
            except Exception as exc:  # record the attempt, then let it propagate
                calls.append((path, params, {"<failed>": str(exc)}))
                raise
            calls.append((path, params, payload))
            return payload

        module._request = spy
        if fresh:
            # Expire every cache window so the adapter really calls upstream.
            for name in dir(module):
                if name.endswith("_TTL"):
                    setattr(module, name, timedelta(0))

    adapter = pricing.get_adapter(source)
    try:
        result = adapter(db, item)
    except pricing.NotApplicable as exc:
        print(f"\nNOT APPLICABLE (the API would answer 422)\n  {exc}")
        status = 1
        result = None
    except pricing.SourceUnavailable as exc:
        print(f"\nUNAVAILABLE (the API would answer 502)\n  {exc}")
        status = 1
        result = None
    else:
        status = 0

    if module is not None:
        print(f"\nupstream calls: {len(calls)}" + ("" if calls else "  (served from source_cache)"))
        for path, params, payload in calls:
            print(f"  GET {path}  {params if params else ''}".rstrip())
            dump("  payload", payload, full)
        if not calls:
            for row in db.execute(
                select(SourceCache).where(SourceCache.source == source)
            ).scalars():
                dump(
                    f"cached {row.cache_key} (fetched {row.fetched_at:%Y-%m-%d %H:%M})",
                    row.payload,
                    full,
                )

    if result is not None:
        print("\nESTIMATE (not saved)")
        print(f"  value      : {result.estimated_value} {result.currency}")
        print(f"  source     : {result.source}")
        print(f"  confidence : {result.confidence}")
        print(f"  sample     : {result.sample_size if result.sample_size is not None else '—'}")
        if item.quantity != 1:
            per_piece = (Decimal(result.estimated_value) / item.quantity).quantize(Decimal("0.01"))
            print(f"  per piece  : {per_piece} (quantity {item.quantity})")
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("-s", "--source", choices=SOURCES, help="which adapter to run")
    parser.add_argument("-i", "--item", help="item id (see --list)")
    parser.add_argument(
        "--list", action="store_true", help="list items an external source could price"
    )
    parser.add_argument(
        "--fresh", action="store_true", help="bypass the cache; spends a real request"
    )
    parser.add_argument("--full", action="store_true", help="print whole payloads, untrimmed")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.list:
            return list_candidates(db)
        if not args.source or not args.item:
            parser.error("need -s/--source and -i/--item (or --list)")
        return probe(db, args.source, args.item, args.fresh, args.full)
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
