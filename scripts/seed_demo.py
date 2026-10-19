#!/usr/bin/env python3
"""Load a small demo collection into a running Cabinet instance.

Gives you something to look at (populated list, dashboard breakdowns, gain/
loss tables) without entering real data first. Uses only the standard library
and talks to the public API, so it needs no install:

    python scripts/seed_demo.py
    python scripts/seed_demo.py --base-url http://cabinet.lan --force

Photos are attached through the app's own URL import: public domain and CC0
images from Wikimedia Commons, each one's source recorded beside its piece
below. Cabinet fetches them, so the stack needs to reach
upload.wikimedia.org; Commons refuses bursts, so they come one at a time
(about a minute for all of them), a photo that still can't be fetched is a
warning, not a failure, and --no-photos skips them. The two bullion pieces
have none (their designs are current and not free). Delete the demo items
from the list view when you're done, or start clean by recreating the stack
with `docker compose down -v`.

Cabinet needs a sign-in (v0.30.0): pass a write-scoped API token with
--token, or set CABINET_TOKEN. Create one in Settings -> Account, or with
the write token minted by scripts/ci/stack-smoke.sh.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

COMMONS = "https://upload.wikimedia.org/wikipedia/commons/"
# Commons refuses bursts, so photos are fetched one at a time with a pause,
# and a refusal is retried after these waits (seconds).
PHOTO_PAUSE = 2
RETRY_WAITS = (10, 30, 60)


def commons(angle: str, path: str, license: str, credit: str) -> dict:
    """A photo from Wikimedia Commons: its angle, its path under COMMONS, the
    license Commons states (public domain or CC0 only), and the credit line.
    Checked 15 October 2026; if a file's license changes, take it out."""
    parts = path.split("/")
    name = parts[3] if parts[0] == "thumb" else parts[2]
    return {
        "angle": angle,
        "url": COMMONS + path,
        "page": f"https://commons.wikimedia.org/wiki/File:{name}",
        "license": license,
        "credit": credit,
    }


# (payload, [(value, source) …]). Estimates are recorded oldest first so the
# value-over-time chart has something to draw. A payload's "photos" are
# attached in order, so the first is the primary.
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
            "photos": [
                commons("obverse", "d/da/USA-1921-one-dollar-d.jpg", "Public domain", "Albertomos"),
                commons("reverse", "0/00/USA-1921-one-dollar-r.jpg", "Public domain", "Albertomos"),
            ],
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
            "photos": [
                commons("obverse", "c/c2/1932_Washington_quarter_obverse.jpg", "Public domain",
                        "Numismatic Guaranty Corporation"),
                commons("reverse", "7/77/1932_Washington_quarter_reverse.jpg", "Public domain",
                        "Numismatic Guaranty Corporation"),
            ],
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
            "photos": [
                commons("obverse", "9/98/1955_doubled_die_Lincoln_cent.jpg", "Public domain",
                        "Lost Dutchman Rare Coins (image), Victor David Brenner (design)"),
                # Any wheat cent's reverse; this one is a 1944.
                commons("reverse", "b/b1/Lincoln_Cent_Wheat_Reverse.png", "Public domain",
                        "Brandon Grossardt (image), Victor David Brenner (design)"),
            ],
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
            "photos": [
                commons("reverse", "f/ff/50centpiece1967.jpg", "Public domain",
                        "Snd3054 (photo), Alex Colville (design)"),
            ],
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
            "photos": [
                commons("obverse", "9/9f/George_V_sovereign_MET_DP100407.jpg", "CC0",
                        "The Metropolitan Museum of Art"),
                commons("reverse", "e/e5/George_V_sovereign_MET_DP100408.jpg", "CC0",
                        "The Metropolitan Museum of Art"),
            ],
        },
        [(505.0, "dealer quote"), (612.0, "dealer quote")],
    ),
    (
        {
            "type": "coin", "country": "Germany", "denomination": "5 mark", "year": 1876,
            "series": "Wilhelm I", "composition": "90% silver", "weight_g": 27.78,
            "fineness": 0.9, "grade_code": "F-12", "acquisition_date": "2023-08-21",
            "acquisition_price": 48.0, "tags": ["silver", "world"],
            "photos": [
                commons("obverse", "f/fd/5_Mark_Preussen_Wilhelm_I.jpg", "CC0",
                        "Wikimedia Commons contributor (own work)"),
            ],
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
            "photos": [
                commons("obverse", "d/d6/Obverse_of_%2410_banknote%2C_Canada_1954_Series%2C_"
                        "%22Devil%27s_Head%22_printing.jpg", "Public domain",
                        "Bank of Canada, National Currency Museum"),
                commons("reverse", "9/9f/Reverse_of_%2410_banknote%2C_Canada_1954_Series%2C_"
                        "%22Devil%27s_Head%22_printing.jpg", "Public domain",
                        "Bank of Canada, National Currency Museum"),
            ],
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
            "photos": [
                commons("obverse", "d/de/Heavily_Worn_2_Dollar_Bill.jpg", "Public domain",
                        "Bureau of Engraving and Printing"),
            ],
        },
        [(11.0, "manual")],
    ),
    (
        {
            # A National Bank Note: charter, bank town, and plate position, as on
            # the note in its photo.
            "type": "note", "country": "United States", "denomination": "10 dollars",
            "year": 1902, "series": "Series 1902 Date Back", "signatures": "Lyons / Roberts",
            "serial_number": "T110402A", "issuer": "The Allentown National Bank",
            "charter_number": "1322", "bank_city": "Allentown", "bank_state": "Pennsylvania",
            "plate_position": "E", "width_mm": 190.5, "height_mm": 79.4,
            "printer": "Bureau of Engraving and Printing",
            "grade_scale": "pmg", "grade_code": "25",
            "acquisition_date": "2025-05-19", "acquisition_price": 410.0,
            "catalog_refs": [{"catalog": "friedberg", "ref_code": "Fr. 616"}],
            "tags": ["notes", "national"],
            "photos": [
                # Both sides in one image.
                commons("obverse", "e/e6/1902_-_Ten_Dollar_Bill_Allentown_National_Bank_"
                        "Allentown_PA.jpg", "Public domain", "United States Treasury Department"),
            ],
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
            "photos": [
                # Both sides in one image.
                commons("obverse", "7/72/Bielefeld_-_50Pf._1921_B.png", "Public domain",
                        "5snake5 (scan)"),
            ],
        },
        [(18.0, "manual")],
    ),
    (
        {
            # Dated in the Hijri calendar; the year the coin also carries is kept as entered.
            "type": "coin", "country": "Egypt", "denomination": "20 qirsh", "year": 1916,
            "struck_calendar": "hijri", "struck_year": 1335, "series": "Hussein Kamel",
            "composition": "83.3% silver", "weight_g": 28.0, "fineness": 0.833, "die_axis": 0,
            "acquisition_date": "2025-07-02", "acquisition_price": 64.0,
            "tags": ["silver", "world"],
            "photos": [
                # Both sides in one image.
                commons("obverse", "3/30/20_Qirsh_Hussein_Kamel_1916.png", "CC0", "Windrain"),
            ],
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
            "photos": [
                commons("obverse", "0/02/1942-Mercury-Dime-Obverse.jpg", "Public domain",
                        "Bobby131313"),
                commons("reverse", "d/d4/1942-Mercury-Dime-Reverse.jpg", "Public domain",
                        "Bobby131313"),
            ],
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
            "photos": [
                commons("obverse", "7/7b/Kennedyhalfdollar1964-1.jpg", "CC0",
                        "Len Augsburger, Newman Numismatic Portal"),
                commons("reverse", "4/47/Kennedyhalfdollar1964-2.jpg", "CC0",
                        "Len Augsburger, Newman Numismatic Portal"),
            ],
        },
        [],
    ),
    (
        {
            "type": "coin", "country": "United States", "denomination": "20 dollars",
            "year": 1907, "series": "Saint-Gaudens Double Eagle", "status": "wishlist",
            "target_price": 2400.0, "priority": 1,
            "notes": "The one to save for.", "tags": ["gold", "wishlist"],
            "photos": [
                # Both sides in one image; the original is 20 MB, so a 1280 px copy.
                commons("obverse", "thumb/1/16/NNC-US-1907-G%2420-Saint_Gaudens_%28Arabic%29.jpg/"
                        "1280px-NNC-US-1907-G%2420-Saint_Gaudens_%28Arabic%29.jpg", "Public domain",
                        "National Numismatic Collection, Smithsonian (photo by Jaclyn Nash)"),
            ],
        },
        [(2650.0, "dealer quote")],  # over the target for now
    ),
    (
        {
            # A bar: bullion (P11, v0.31.0), no year, a serial, and a refiner in issuer.
            "type": "bullion", "country": "Switzerland", "denomination": "1 oz silver bar",
            "issuer": "PAMP Suisse", "composition": "999 silver", "weight_g": 31.1035,
            "fineness": 0.999, "serial_number": "A1234567",
            "acquisition_date": "2025-01-20", "acquisition_price": 34.0,
            "acquired_from": "online dealer", "storage_location": "Safe",
            "tags": ["silver", "bullion"],
        },
        [(36.0, "dealer quote")],
    ),
    (
        {
            # A round: same metal, no serial, deliberately unestimated.
            "type": "bullion", "country": "Canada", "denomination": "1 oz silver round",
            "issuer": "Royal Canadian Mint", "composition": "999.9 silver",
            "weight_g": 31.1035, "fineness": 0.9999,
            "acquisition_date": "2025-06-02", "acquisition_price": 33.0,
            "storage_location": "Safe", "tags": ["silver", "bullion"],
        },
        [],
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


def attach_photo(base: str, item_id: str, photo: dict, token: str | None) -> str | None:
    """Ask Cabinet to fetch one photo, retrying while Commons is busy (it
    rate-limits bursts with a 429, which Cabinet passes on in its 422, or
    can't be reached, a 502). Returns None, or why it failed: a missing photo
    is a warning, never a failed seed."""
    for wait in RETRY_WAITS:
        failed = _attach_once(base, item_id, photo, token)
        if failed is None or not _busy(failed):
            return failed
        time.sleep(wait)
    return _attach_once(base, item_id, photo, token)


def _busy(failed: str) -> bool:
    return failed.startswith("HTTP 502") or "answered HTTP 429" in failed or "answered HTTP 5" in failed


def _attach_once(base: str, item_id: str, photo: dict, token: str | None) -> str | None:
    data = json.dumps({"url": photo["url"], "angle": photo["angle"]}).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"{base}/api/items/{item_id}/photos/url", data=data, method="POST", headers=headers
    )
    try:
        # Cabinet downloads the file before it answers, so allow for a slow fetch.
        with urllib.request.urlopen(req, timeout=120):
            return None
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("detail")
        except ValueError:
            detail = None
        return f"HTTP {exc.code}" + (f": {detail}" if isinstance(detail, str) else "")
    except (urllib.error.URLError, TimeoutError) as exc:
        return str(getattr(exc, "reason", exc))


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
    parser.add_argument(
        "--no-photos",
        action="store_true",
        help="skip the photos (Cabinet fetches them from Wikimedia Commons)",
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

    created = estimates = photos = 0
    missed: list[str] = []
    for payload, values in DEMO_ITEMS:
        payload = dict(payload)
        item_photos = payload.pop("photos", [])
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
        for photo in [] if args.no_photos else item_photos:
            if photos or missed:
                time.sleep(PHOTO_PAUSE)
            failed = attach_photo(base, item["id"], photo, token)
            if failed:
                name = " ".join(str(payload.get(k) or "") for k in ("year", "country", "denomination"))
                missed.append(f"  {name.strip()}, {photo['angle']}: {failed}")
            else:
                photos += 1

    print(f"Seeded {created} items, {estimates} estimates, and {photos} photos into {base}.")
    if missed:
        print(f"{len(missed)} photo(s) could not be fetched (the items are fine):", file=sys.stderr)
        print("\n".join(missed), file=sys.stderr)
    print("Open the dashboard to see breakdowns, gains, and value over time.")
    print("Tip: items with composition + weight can be priced with the melt button.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
