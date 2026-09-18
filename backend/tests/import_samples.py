"""Synthetic import files in the formats of other collection tools (v0.18.0).

Built from each format's published layout — OpenNumismat's schema in its
source code, Numista's collection export header, a hand-kept spreadsheet, a
Colnect-style export with lines above its header — never from anyone's real
data or OpenNumismat's GPL-licensed demo files. The tests build them on the
fly; to write a set you can upload by hand:

    cd backend && python -m tests.import_samples ../docs/import-samples
"""

import csv
import io
import sqlite3
import sys
from pathlib import Path

from PIL import Image

# ---------------------------------------------------------------- pictures


def picture(fmt: str = "JPEG", color=(180, 150, 60)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (80, 80), color).save(buf, fmt)
    return buf.getvalue()


# ---------------------------------------------------------------- OpenNumismat

# Columns every schema version since 9 has (OpenNumismat's CollectionFields).
_ON_COLUMNS = """title TEXT, value NUMERIC, unit TEXT, country TEXT, year INTEGER, period TEXT,
 mint TEXT, mintmark TEXT, issuedate TEXT, type TEXT, series TEXT, subjectshort TEXT, status TEXT,
 material TEXT, fineness INTEGER, shape TEXT, diameter NUMERIC, thickness NUMERIC, weight NUMERIC,
 grade TEXT, edge TEXT, edgelabel TEXT, obvrev TEXT, quality TEXT, mintage INTEGER, dateemis TEXT,
 catalognum1 TEXT, catalognum2 TEXT, catalognum3 TEXT, catalognum4 TEXT, rarity TEXT,
 price1 NUMERIC, price2 NUMERIC, price3 NUMERIC, price4 NUMERIC, variety TEXT, obversevar TEXT,
 reversevar TEXT, edgevar TEXT, {buy_sell} note TEXT, image INTEGER, obverseimg INTEGER,
 obversedesign TEXT, obversedesigner TEXT, reverseimg INTEGER, reversedesign TEXT,
 reversedesigner TEXT, edgeimg INTEGER, subject TEXT, photo1 INTEGER, photo2 INTEGER,
 photo3 INTEGER, photo4 INTEGER, defect TEXT, storage TEXT, features TEXT, createdat TEXT,
 updatedat TEXT, quantity INTEGER, url TEXT, barcode TEXT, ruler TEXT, region TEXT,
 varietydesc TEXT, format TEXT, condition TEXT, category TEXT, sort_id INTEGER, emitent TEXT,
 signaturetype TEXT, signature TEXT, signatureimg INTEGER, photo5 INTEGER, photo6 INTEGER,
 grader TEXT, seat TEXT, native_year TEXT, composition TEXT, material2 TEXT, width NUMERIC,
 height NUMERIC, axis INTEGER, real_weight NUMERIC, real_diameter NUMERIC, rating TEXT"""
_ON_BUY_SELL = """paydate TEXT, payprice NUMERIC, totalpayprice NUMERIC, saller TEXT,
 payplace TEXT, payinfo TEXT, saledate TEXT, saleprice NUMERIC, totalsaleprice NUMERIC,
 buyer TEXT, saleplace TEXT, saleinfo TEXT,"""


def _on_schema(conn: sqlite3.Connection, version: int) -> None:
    buy_sell = _ON_BUY_SELL if version <= 10 else ""
    conn.execute(
        "CREATE TABLE coins (id INTEGER PRIMARY KEY, " + _ON_COLUMNS.format(buy_sell=buy_sell) + ")"
    )
    conn.execute("CREATE TABLE photos (id INTEGER PRIMARY KEY, title TEXT, image BLOB)")
    conn.execute("CREATE TABLE images (id INTEGER PRIMARY KEY, image BLOB)")
    conn.execute("CREATE TABLE settings (title CHAR NOT NULL UNIQUE, value CHAR)")
    conn.execute(
        "CREATE TABLE fields (id INTEGER NOT NULL PRIMARY KEY, title TEXT, enabled INTEGER)"
    )
    conn.execute(
        "CREATE TABLE tags (id INTEGER NOT NULL PRIMARY KEY, tag TEXT, parent_id INTEGER, "
        "position INTEGER)"
    )
    conn.execute("CREATE TABLE coins_tags (coin_id INTEGER, tag_id INTEGER)")
    if version >= 11:
        conn.execute(
            "CREATE TABLE prices (id INTEGER NOT NULL PRIMARY KEY, coin_id INTEGER, action TEXT, "
            "date TEXT, quantity INTEGER, price NUMERIC, currency TEXT, total_price NUMERIC, "
            "shipping NUMERIC, grade TEXT, url TEXT, place TEXT, number TEXT, "
            "counterparty TEXT, info TEXT)"
        )
    conn.executemany(
        "INSERT INTO settings VALUES (?, ?)", [("Version", str(version)), ("Type", "OpenNumismat")]
    )
    # Field titles: the catalogue columns (ids 27–30) default to "1#"…"4#";
    # this collection renamed the first two.
    conn.executemany(
        "INSERT INTO fields VALUES (?, ?, 1)",
        [(27, "Krause#"), (28, "Red Book"), (29, "3#"), (30, "4#")],
    )


def _insert(conn: sqlite3.Connection, table: str, row: dict) -> int:
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    return conn.execute(
        f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(row.values())
    ).lastrowid


def opennumismat(path: Path, version: int = 10) -> Path:
    """An OpenNumismat collection: `version` 10 keeps purchase and sale on the
    coins table (with '' in numeric columns and JPEG photos, like older files);
    11 uses the `prices` table and WebP photos, like OpenNumismat 1.11."""
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    _on_schema(conn, version)
    fmt = "JPEG" if version <= 10 else "WEBP"
    obverse = _insert(conn, "photos", {"title": "", "image": picture(fmt, (200, 170, 70))})
    reverse = _insert(conn, "photos", {"title": "", "image": picture(fmt, (150, 120, 40))})
    stamp = "2025-06-01T12:00:00" + (".000Z" if version >= 11 else ".000")
    coins = [
        {  # 1 — bought at a show, two photos, a renamed and a prefixed catalogue number
            "title": "1 Dollar 1978", "value": 1, "unit": "Dollar", "country": "United States",
            "year": 1978, "mintmark": "", "series": "Eisenhower Dollar", "status": "owned",
            "material": "Copper-nickel clad copper", "weight": 22.68, "diameter": 38.1,
            "grade": "AU", "catalognum1": "KM# 203", "catalognum2": "5820", "quantity": 1,
            "obverseimg": obverse, "reverseimg": reverse, "storage": "Album 2, page 4",
            "note": "Apollo 11 reverse.", "createdat": stamp,
            "_buy": {"date": "2025-06-01", "price": 3.5, "total": 4.25, "from": "Coin show"},
        },
        {  # 2 — sold, with fees taken off the sale
            "title": "25 Cents 1932 D", "value": 0.25, "unit": "Dollar", "country": "United States",
            "year": 1932, "mintmark": "D", "series": "Washington Quarter", "status": "sold",
            "material": "Silver", "fineness": 900, "weight": 6.25, "grade": "VF-30",
            "catalognum1": "KM# 164", "createdat": stamp,
            "_buy": {"date": "2019-03-02", "price": 120, "total": 120, "from": "Dealer"},
            "_sell": {"date": "2025-08-15", "price": 400, "total": 360, "to": "Heritage"},
        },
        {  # 3 — on the wish list
            "title": "5 Mark 1975", "value": 5, "unit": "Mark", "country": "Germany",
            "year": 1975, "mintmark": "J", "status": "wish", "grade": "Unc", "createdat": stamp,
        },
        {  # 4 — a graded banknote
            "title": "1 Dollar 2017", "value": 1, "unit": "Dollar", "country": "United States",
            "year": 2017, "category": "Banknote", "status": "owned", "grade": "64 EPQ",
            "grader": "PMG", "barcode": "8081234-001", "signature": "Carranza / Mnuchin",
            "emitent": "Federal Reserve Bank of New York", "width": 156, "height": 66,
            "createdat": stamp,
        },
        {  # 5 — lost at auction: not imported
            "title": "2 Euro 2002", "value": 2, "unit": "Euro", "country": "France",
            "year": 2002, "status": "pass", "createdat": stamp,
        },
        {  # 6 — no year anywhere: an error
            "title": "Token", "value": 1, "unit": "Token", "country": "Nowhere",
            "year": "", "status": "owned", "createdat": stamp,
        },
        {  # 7 — a proof silver dollar, year only in the issue date
            "title": "1 Dollar 1986 S", "value": 1, "unit": "Dollar", "country": "United States",
            "year": "", "issuedate": "1986-01-01", "mintmark": "S", "status": "owned",
            "quality": "Proof", "grade": "PF-69 DCAM", "grader": "NGC", "barcode": "2851234-007",
            "material": "Silver", "fineness": 900, "weight": 26.73, "createdat": stamp,
            "_buy": {"date": "2000-01-01", "price": 45, "total": 52.5, "from": "eBay",
                     "currency": "EUR"},
        },
    ]  # fmt: skip
    tag = _insert(conn, "tags", {"tag": "Type set", "parent_id": 0, "position": 0})
    for coin in coins:
        buy, sell = coin.pop("_buy", None), coin.pop("_sell", None)
        if version <= 10:
            if buy:
                coin.update(paydate=buy["date"], payprice=buy["price"], totalpayprice=buy["total"],
                            saller=buy["from"])  # fmt: skip
            if sell:
                coin.update(saledate=sell["date"], saleprice=sell["price"],
                            totalsaleprice=sell["total"], buyer=sell["to"])  # fmt: skip
        coin_id = _insert(conn, "coins", coin)
        if version >= 11:
            for action, deal in (("buy", buy), ("sell", sell)):
                if deal:
                    row = {
                        "coin_id": coin_id,
                        "action": action,
                        "date": deal["date"],
                        "price": deal["price"],
                        "total_price": deal["total"],
                        "currency": deal.get("currency", "USD"),
                        "counterparty": deal.get("from") or deal.get("to"),
                    }
                    _insert(conn, "prices", row)
        if coin_id == 1:
            conn.execute("INSERT INTO coins_tags VALUES (?, ?)", (coin_id, tag))
    conn.commit()
    conn.close()
    return path


# ---------------------------------------------------------------- Numista export

# The header of numista.com's collection export (the columns a member picks).
NUMISTA_HEADER = [
    "Country", "Issuer", "Currency", "Face value", "Title", "Type", "Year range", "Shape",
    "Composition", "Weight", "Diameter", "Year", "Gregorian year", "Mintmark", "Quantity",
    "Grade", "Collection", "From set", "Estimate (USD)", "N# number", "Buying price (USD)",
    "Acquisition date", "Acquisition place", "Storage location", "Private comment",
    "Serial number",
]  # fmt: skip
NUMISTA_ROWS = [
    ["United States", "United States", "Dollar", "1", "1 Dollar - Eisenhower Apollo 11",
     "Standard circulation coin", "1971-1978", "Round", "Copper-nickel clad copper", "22.68",
     "38.1", "1978", "1978", "", "1", "AU", "Main", "", "2.10", "1340", "3.50", "2025-06-01",
     "Coin show", "Album 2", "Nice luster", ""],
    ["Egypt", "Kingdom of Egypt", "Millieme", "5", "5 Milliemes - Fuad I",
     "Standard circulation coin", "1924-1935", "Round with scalloped edges", "Copper-nickel",
     "5", "21", "1352", "1933", "H", "2", "VF", "Main", "", "1.40", "1234", "", "", "", "", "",
     ""],
    ["United States", "United States", "Dollar", "1", "1 Dollar - Federal Reserve Note",
     "Banknote", "2017", "Rectangular", "Paper", "", "156", "2017", "2017", "", "1", "UNC",
     "Notes", "", "1.50", "205430", "1.00", "2024-12-24", "Bank", "", "", "B12345678C"],
    ["France", "France", "Franc", "1", "1 Franc - Semeuse", "Standard circulation coin",
     "1960-2001", "Round", "Nickel", "6", "24", "", "", "", "1", "XF", "Main", "", "", "5678",
     "", "", "", "", "Undated in this listing", ""],
]  # fmt: skip


def numista_csv(path: Path) -> Path:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_ALL)
        writer.writerow(NUMISTA_HEADER)
        writer.writerows(NUMISTA_ROWS)
    return path


def numista_xlsx(path: Path) -> Path:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(NUMISTA_HEADER)
    for row in NUMISTA_ROWS:
        ws.append(row)
    wb.save(path)
    return path


# ---------------------------------------------------------------- spreadsheets


def hand_sheet(path: Path) -> Path:
    """A hand-kept US-style sheet: dollar signs, month-first dates, no type column."""
    rows = [
        ["Country", "Denomination", "Year", "Mint", "Grade", "Price Paid", "Purchase Date",
         "Seller", "Qty", "Notes"],
        ["United States", "1 Cent", "1909", "S", "VF-20", "$1,250.00", "3/14/2024",
         "Great Collections", "1", "VDB"],
        ["United States", "5 Cents", "1937", "D", "MS63", "$45", "11/2/2023", "Coin show", "1",
         "3-legged? no"],
        ["United States", "10 Cents", "1964", "", "BU", "$3.25", "7/4/2024", "LCS", "20",
         "roll"],
        ["United States", "1 Dollar", "", "P", "XF", "$40", "1/5/2024", "", "1", "no year"],
    ]  # fmt: skip
    with path.open("w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(rows)
    return path


def colnect_like(path: Path) -> Path:
    """A Colnect-style export: lines of title and totals above the header.
    Colnect's real column names are translated per user and unconfirmed —
    this only exercises header detection and column matching."""
    preamble = [
        ["Colnect collection export"], ["Coins"], ["Collector: sample"],
        ["Exported: 2026-09-18"], ["Items: 2"], [""], ["https://colnect.com"],
    ]  # fmt: skip
    rows = [
        ["Name", "Country", "Series", "Catalog Codes", "Issued on", "Face value", "Currency",
         "Composition", "Condition", "My comments"],
        ["1 Krone", "Denmark", "Margrethe II", "KM# 873", "1992", "1 Krone", "DKK",
         "Copper-nickel", "XF", "holed"],
        ["20 Euro Cent", "Germany", "Euro", "KM# 211", "2002", "20 Euro Cent", "EUR",
         "Nordic gold", "UNC", ""],
    ]  # fmt: skip
    with path.open("w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(preamble + rows)
    return path


# ---------------------------------------------------------------- Numista account

NUMISTA_COLLECTION = {
    "items_count": 3,
    "items": [
        {
            "id": 90001, "quantity": 1, "for_swap": False, "grade": "au",
            "type": {"id": 1340, "title": "1 Dollar - Eisenhower Apollo 11", "category": "coin",
                     "issuer": {"code": "united-states", "name": "United States"}},
            "issue": {"id": 55, "is_dated": True, "year": 1978, "gregorian_year": 1978},
            "price": {"value": 3.5, "currency": "USD"}, "acquisition_date": "2025-06-01",
            "acquisition_place": "Coin show", "storage_location": "Album 2",
            "private_comment": "Nice luster",
            "collection": {"id": 1, "name": "Main"},
            "pictures": [{"url": "https://example.com/ike.jpg",
                          "thumbnail_url": "https://example.com/ike-t.jpg"}],
        },
        {
            "id": 90002, "quantity": 1, "for_swap": True, "grade": "unc",
            "type": {"id": 7777, "title": "1 Dollar - Morgan", "category": "coin",
                     "issuer": {"code": "united-states", "name": "United States"}},
            "issue": {"id": 66, "is_dated": True, "year": 1881, "gregorian_year": 1881,
                      "mint_letter": "S"},
            "grading_details": {
                "grading_company": {"id": 2, "name": "PCGS"},
                "slab_grade": {"id": 64, "value": "MS 64"}, "slab_number": "12345678",
                "cac_sticker": "Green",
                "grading_designations": [{"id": 3, "value": "DMPL"}],
            },
        },
        {
            "id": 90003, "quantity": 1, "for_swap": False,
            "type": {"id": 999, "title": "Token - Casino", "category": "exonumia",
                     "issuer": {"code": "x", "name": "Nevada"}},
            "issue": {"id": 1, "is_dated": False, "min_year": 1990, "max_year": 1995},
        },
    ],
}  # fmt: skip
NUMISTA_TYPES = {
    1340: {"id": 1340, "title": "1 Dollar - Eisenhower Apollo 11", "category": "coin",
           "issuer": {"name": "United States"}, "value": {"text": "1 Dollar"},
           "composition": {"text": "Copper-nickel clad copper"}, "weight": 22.68, "size": 38.1,
           "series": "Eisenhower Dollar"},
    7777: {"id": 7777, "title": "1 Dollar - Morgan", "category": "coin",
           "issuer": {"name": "United States"}, "value": {"text": "1 Dollar"},
           "composition": {"text": "Silver (.900)"}, "weight": 26.73, "size": 38.1},
}  # fmt: skip


# ---------------------------------------------------------------- write a set


def write_all(folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    return [
        opennumismat(folder / "opennumismat-1.10.db", 10),
        opennumismat(folder / "opennumismat-1.11.db", 11),
        numista_csv(folder / "numista-export.csv"),
        numista_xlsx(folder / "numista-export.xlsx"),
        hand_sheet(folder / "hand-kept-sheet.csv"),
        colnect_like(folder / "colnect-style.csv"),
    ]


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "import-samples")
    for written in write_all(target):
        print(written)
