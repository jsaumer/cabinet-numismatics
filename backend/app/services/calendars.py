"""Dates as struck: the calendars world coins are dated in, and the Gregorian
year each struck year mostly falls in."""

import math

CALENDARS = {  # key -> label
    "hijri": "Islamic (AH)",
    "solar_hijri": "Persian (SH)",
    "thai_buddhist": "Thai Buddhist (BE)",
    "hebrew": "Hebrew (AM)",
    "japanese": "Japanese era",
    "vikram_samvat": "Vikram Samvat (VS)",
    "saka": "Saka (SE)",
    "minguo": "Republic of China (Minguo)",
    "chula_sakarat": "Chula Sakarat (CS)",
    "rattanakosin": "Rattanakosin (RS)",
    "ethiopian": "Ethiopian (EE)",
}
# Japanese eras: year 1 of the era is offset + 1.
ERAS = {"meiji": 1867, "taisho": 1911, "showa": 1925, "heisei": 1988, "reiwa": 2018}
ERA_LABELS = {
    "meiji": "Meiji",
    "taisho": "Taisho",
    "showa": "Showa",
    "heisei": "Heisei",
    "reiwa": "Reiwa",
}

# Fixed offsets to the Gregorian year. The lunar Hijri year is shorter than a
# solar one, so it has a formula of its own.
OFFSETS = {
    "solar_hijri": 621,
    "thai_buddhist": -543,
    "hebrew": -3760,
    "vikram_samvat": -57,
    "saka": 78,
    "minguo": 1911,
    "chula_sakarat": 638,
    "rattanakosin": 1781,
    "ethiopian": 8,
}


def check_era(calendar: str | None, era: str | None) -> None:
    """An era goes with the Japanese calendar, and only with it. ValueError."""
    if calendar == "japanese":
        if era is None:
            raise ValueError("The Japanese calendar needs an era (struck_era)")
        if era not in ERAS:
            raise ValueError(f"Unknown era {era!r}; expected one of {', '.join(ERAS)}")
    elif era is not None:
        raise ValueError("struck_era is only for the Japanese calendar")


def to_gregorian(calendar: str, year: int, era: str | None = None) -> int:
    """The Gregorian year a struck year mostly falls in. ValueError for an
    unknown calendar, or a Japanese year without a known era."""
    if calendar not in CALENDARS:
        raise ValueError(f"Unknown calendar {calendar!r}; expected one of {', '.join(CALENDARS)}")
    check_era(calendar, era)
    if calendar == "hijri":
        return math.floor(year * 0.970224 + 621.5774)
    if calendar == "japanese":
        return ERAS[era] + year
    return year + OFFSETS[calendar]
