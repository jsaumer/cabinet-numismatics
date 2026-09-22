#!/usr/bin/env python3
"""Load a small demo collection into a running Cabinet instance.

Gives you something to look at (populated list, dashboard breakdowns, gain/
loss tables) without entering real data first. Uses only the standard library
and talks to the public API, so it needs no install:

    python scripts/seed_demo.py
    python scripts/seed_demo.py --base-url http://cabinet.lan --force

Photos are not seeded (upload a couple by hand to see them). Delete the demo
items from the list view when you're done, or start clean by recreating the
stack with `docker compose down -v`.

Cabinet needs a sign-in (v0.30.0): pass a write-scoped API token with
--token, or set CABINET_TOKEN. Create one in Settings -> Account, or with
the write token minted by scripts/ci/stack-smoke.sh.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

# (payload, [(value, source) …]). Estimates are recorded oldest first so the
# value-over-time chart has something to draw.
DEMO_ITEMS: list[tuple[dict, list[tuple[float, str]]]] = [
    (
        {
            "type": "coin", "country": "United States", "denomination": "1 dollar",
            "year": 1921, "series": "Morgan Dollar", "composition": "90% silver",
            "weight_g": 26.73, "fineness": 0.9, "die_axis": 180, "grade_code": "MS-63",
            "acquisition_date": "2023-04-18", "acquisition_price": 62.0, "acquisition_fees": 7.5,
            "acquired_from": "regional coin show", "storage_location": "Slab box 1",
            "tags": ["silver", "type set"],
            "catalog_refs": [{"catalog": "krause", "ref_code": "KM#110"}],
        },
        [(58.0, "Red Book"), (71.5, "dealer quote")],
    ),
    (
        {
            "type": "coin", "country": "United States", "denomination": "25 cents",
            "year": 1932, "mint_mark": "D", "series": "Washington Quarter",
            "composition": "90% silver", "weight_g": 6.25, "fineness": 0.9,
            "grade_code": "VF-20", "acquisition_date": "2024-02-02",
            "acquisition_price": 118.0, "acquired_from": "online auction",
            "storage_location": "Slab box 1", "tags": ["silver", "key date"],
        },
        [(155.0, "auction comparable")],
    ),
    (
        {
            "type": "coin", "country": "United States", "denomination": "1 cent",
            "year": 1955, "series": "Lincoln Wheat", "variety": "1955 Doubled Die Obverse",
            "grade_code": "XF-40", "designations": ["BN"], "acquisition_date": "2024-09-30",
            "acquisition_price": 900.0, "acquired_from": "estate sale",
            "storage_location": "Safe", "tags": ["error", "key date"],
            "custom_fields": {"attribution": "FS-101"},
        },
        [(1450.0, "auction comparable")],
    ),
    (
        {
            "type": "coin", "country": "Canada", "denomination": "50 cents",
            "year": 1967, "series": "Centennial", "composition": "80% silver",
            "weight_g": 11.66, "fineness": 0.8, "grade_code": "AU-55",
            "acquisition_date": "2024-06-11", "acquisition_price": 14.0,
            "currency": "CAD", "tags": ["silver"],
        },
        [(19.5, "manual")],
    ),
    (
        {
            "type": "coin", "country": "United Kingdom", "denomination": "1 sovereign",
            "year": 1911, "composition": "22kt gold (91.7%)", "weight_g": 7.99,
            "fineness": 0.9167, "grade_code": "AU-58", "acquisition_date": "2022-11-05",
            # Before the purchase-day spot source starts, so it is typed in.
            "spot_at_purchase": 1670.0,
            "acquisition_price": 410.0, "acquired_from": "dealer",
            "storage_location": "Safe", "tags": ["gold", "bullion"],
        },
        [(505.0, "dealer quote"), (612.0, "dealer quote")],
    ),
    (
        {
            "type": "coin", "country": "Germany", "denomination": "5 mark", "year": 1876,
            "series": "Wilhelm I", "composition": "90% silver", "weight_g": 27.78,
            "fineness": 0.9, "grade_code": "F-12", "acquisition_date": "2023-08-21",
            "acquisition_price": 48.0, "tags": ["silver", "world"],
        },
        [(52.0, "manual")],
    ),
    (
        {
            "type": "note", "country": "Canada", "denomination": "10 dollars",
            "year": 1954, "series": "Devil's Face", "grade_scale": "pmg",
            "serial_number": "1234567", "prefix_block": "A/D", "signatures": "Coyne–Towers",
            "issuer": "Bank of Canada", "width_mm": 152.4, "height_mm": 69.85,
            "printer": "Canadian Bank Note Company",
            "grade_code": "35", "acquisition_date": "2024-01-14",
            "acquisition_price": 205.0, "acquired_from": "paper money show",
            "storage_location": "Album 2", "tags": ["notes", "world"],
        },
        [(240.0, "price guide")],
    ),
    (
        {
            "type": "note", "country": "United States", "denomination": "2 dollars",
            "year": 1976, "series": "Series 1976", "grade_scale": "pmg", "designations": ["EPQ"],
            # A repeater serial, so the fancy-serial badge and filter have something to show.
            "serial_number": "B19761976A", "signatures": "Neff / Simon",
            "issuer": "Federal Reserve Bank of New York", "width_mm": 156.21, "height_mm": 66.29,
            "printer": "Bureau of Engraving and Printing",
            "grade_code": "65", "acquisition_date": "2025-03-08",
            "acquisition_price": 9.0, "storage_location": "Album 2", "tags": ["notes"],
        },
        [(11.0, "manual")],
    ),
    (
        {
            # A National Bank Note: charter, bank town, and plate position.
            "type": "note", "country": "United States", "denomination": "10 dollars",
            "year": 1902, "series": "Series 1902 Plain Back", "signatures": "Lyons / Roberts",
            "serial_number": "A541263", "issuer": "The First National Bank of Cooperstown",
            "charter_number": "280", "bank_city": "Cooperstown", "bank_state": "New York",
            "plate_position": "B", "width_mm": 190.5, "height_mm": 79.4,
            "printer": "Bureau of Engraving and Printing",
            "grade_scale": "pmg", "grade_code": "25",
            "acquisition_date": "2025-05-19", "acquisition_price": 410.0,
            "catalog_refs": [{"catalog": "friedberg", "ref_code": "Fr. 624"}],
            "tags": ["notes", "national"],
        },
        [],  # deliberately unestimated, so coverage gaps are visible
    ),
    (
        {
            # Undated (ND), with the year it is attributed to: German notgeld.
            "type": "note", "country": "Germany", "denomination": "50 pfennig",
            "year": 1921, "year_nd": True, "series": "Notgeld, Stadt Bielefeld",
            "issuer": "Stadt Bielefeld", "grade_scale": "pmg", "grade_code": "55",
            "acquisition_date": "2026-01-14", "acquisition_price": 14.0,
            "storage_location": "Album 2", "tags": ["notes", "world"],
        },
        [(18.0, "manual")],
    ),
    (
        {
            # Dated in the Hijri calendar; the year the coin also carries is kept as entered.
            "type": "coin", "country": "Egypt", "denomination": "20 qirsh", "year": 1917,
            "struck_calendar": "hijri", "struck_year": 1335, "series": "Hussein Kamel",
            "composition": "83.3% silver", "weight_g": 28.0, "fineness": 0.833, "die_axis": 0,
            "acquisition_date": "2025-07-02", "acquisition_price": 64.0,
            "tags": ["silver", "world"],
        },
        [],
    ),
    (
        {
            "type": "coin", "country": "United States", "denomination": "10 cents",
            "year": 1942, "series": "Mercury Dime", "composition": "90% silver",
            "weight_g": 2.5, "fineness": 0.9, "grade_code": "MS-64", "quantity": 5,
            "acquisition_date": "2023-12-01", "acquisition_price": 95.0,
            "notes": "Roll remnant, priced as a lot.", "tags": ["silver"],
        },
        [(128.0, "manual")],
    ),
    (
        {
            "type": "coin", "country": "United States", "denomination": "50 cents",
            "year": 1964, "series": "Kennedy", "composition": "90% silver",
            "weight_g": 12.5, "fineness": 0.9, "grade_code": "MS-62",
            "status": "sold", "acquisition_date": "2022-05-30",
            "acquisition_price": 18.0, "sold_date": "2025-10-12", "sold_price": 34.0,
            "tags": ["silver"],
        },
        [],
    ),
    (
        {
            "type": "coin", "country": "United States", "denomination": "20 dollars",
            "year": 1907, "series": "Saint-Gaudens Double Eagle", "status": "wishlist",
            "target_price": 2400.0, "priority": 1,
            "notes": "The one to save for.", "tags": ["gold", "wishlist"],
        },
        [(2650.0, "dealer quote")],  # over the target for now
    ),
]


def request(base: str, method: str, path: str, payload: dict | None = None, token: str | None = None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{base}{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        if exc.code == 401:
            raise SystemExit(
                "Cabinet needs a sign-in now (v0.30.0). Pass a write-scoped API token with "
                "--token or CABINET_TOKEN (Settings -> Account -> API tokens)."
            ) from None
        raise SystemExit(f"{method} {path} failed: HTTP {exc.code} {detail}") from None
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Could not reach Cabinet at {base} ({exc.reason}). Is the stack running?"
        ) from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost", help="default: http://localhost")
    parser.add_argument(
        "--force", action="store_true", help="seed even if the collection already has items"
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("CABINET_TOKEN"),
        help="a write-scoped API token, sent as Bearer (default: the CABINET_TOKEN env var)",
    )
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    token = args.token

    def call(method: str, path: str, payload: dict | None = None):
        return request(base, method, path, payload, token=token)

    existing = call("GET", "/api/items?limit=1")
    if existing["total"] and not args.force:
        print(
            f"Collection already has {existing['total']} item(s); refusing to add demo data.\n"
            "Re-run with --force if you really want to mix demo data in.",
            file=sys.stderr,
        )
        return 1

    grades: dict[tuple[str, str], int] = {}
    for scale in ("sheldon", "pmg"):
        for grade in call("GET", f"/api/grades?scale={scale}"):
            grades[(scale, grade["code"])] = grade["id"]

    created = estimates = 0
    for payload, values in DEMO_ITEMS:
        payload = dict(payload)
        scale = payload.pop("grade_scale", "sheldon")
        code = payload.pop("grade_code", None)
        if code:
            payload["grade_id"] = grades[(scale, code)]

        item = call("POST", "/api/items", payload)
        created += 1
        for value, source in values:
            call(
                "POST",
                f"/api/items/{item['id']}/estimates",
                {"estimated_value": value, "currency": payload.get("currency", "USD"),
                 "source": source},
            )
            estimates += 1

    print(f"Seeded {created} items and {estimates} estimates into {base}.")
    print("Open the dashboard to see breakdowns, gains, and value over time.")
    print("Tip: items with composition + weight can be priced with the melt button.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
