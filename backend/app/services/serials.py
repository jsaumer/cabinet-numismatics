"""Fancy serial numbers on paper money: the patterns collectors pay for.

`traits` reads the digits of a serial (letters, spaces, and stars dropped,
leading zeros kept). The item keeps the result in `serial_traits` as
`,radar,binary,` so the list can filter with a LIKE.
"""

from datetime import date

# key -> (label, description), in the order `traits` reports them.
TRAITS = {
    "solid": ("Solid", "Every digit the same"),
    "ladder": ("Ladder", "Digits run up or down by one"),
    "radar": ("Radar", "Reads the same backwards"),
    "super_radar": ("Super radar", "A radar whose inner digits are all the same"),
    "repeater": ("Repeater", "The first half repeated"),
    "super_repeater": ("Super repeater", "One two-digit block repeated throughout"),
    "binary": ("Binary", "Only two different digits"),
    "trinary": ("Trinary", "Only three different digits"),
    "low": ("Low number", "Serial number 100 or lower"),
    "high": ("High number", "Serial number 99999900 or higher"),
    "double_quad": ("Double quad", "Two blocks of four of the same digit"),
    "date": ("Date", "Reads as a calendar date"),
    "star": ("Star", "A star or replacement note"),
}
MIN_DIGITS = 4


def _is_date(digits: str) -> bool:
    """MMDDYYYY or YYYYMMDD, year 1700 to 2099."""
    for year, month, day in (
        (digits[4:], digits[:2], digits[2:4]),
        (digits[:4], digits[4:6], digits[6:]),
    ):
        if 1700 <= int(year) <= 2099:
            try:
                date(int(year), int(month), int(day))
            except ValueError:
                continue
            return True
    return False


def traits(serial: str | None, replacement: bool = False) -> list[str]:
    text = serial or ""
    digits = "".join(ch for ch in text if ch.isascii() and ch.isdigit())
    n = len(digits)
    found: set[str] = set()
    if n >= MIN_DIGITS:
        distinct = len(set(digits))
        solid = distinct == 1
        steps = {int(b) - int(a) for a, b in zip(digits, digits[1:], strict=False)}
        if solid:
            found.add("solid")
        if steps in ({1}, {-1}):
            found.add("ladder")
        if not solid and digits == digits[::-1]:
            inner = digits[1:-1]
            found.add("super_radar" if len(set(inner)) == 1 else "radar")
        if not solid and n % 2 == 0:
            if digits[:2] * (n // 2) == digits:
                found.add("super_repeater")
            elif digits[: n // 2] * 2 == digits:
                found.add("repeater")
        if distinct == 2 and n >= 6:
            found.add("binary")
        if distinct == 3 and n == 8:
            found.add("trinary")
        if n >= 6 and 1 <= int(digits) <= 100:
            found.add("low")
        if n == 8:
            if int(digits) >= 99999900:
                found.add("high")
            if not solid and len(set(digits[:4])) == 1 and len(set(digits[4:])) == 1:
                found.add("double_quad")
            if _is_date(digits):
                found.add("date")
    if replacement or "*" in text or "★" in text:
        found.add("star")
    return [key for key in TRAITS if key in found]


def encode(found: list[str]) -> str | None:
    """The stored form: `,radar,binary,`, or None when there are none."""
    return f",{','.join(found)}," if found else None


def decode(stored: str | None) -> list[str]:
    return [key for key in (stored or "").split(",") if key]


def stored_traits(serial: str | None, replacement: bool = False) -> str | None:
    return encode(traits(serial, replacement))
