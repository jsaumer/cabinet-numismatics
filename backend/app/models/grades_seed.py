"""Seed data for the grades reference table.

Used by migration 0003 and by the test fixtures. Treat as append-only: editing
existing rows here does not change databases that were already migrated.
"""

SHELDON = [
    ("PO-1", "Poor", 1),
    ("FR-2", "Fair", 2),
    ("AG-3", "About Good", 3),
    ("G-4", "Good", 4),
    ("G-6", "Choice Good", 6),
    ("VG-8", "Very Good", 8),
    ("VG-10", "Choice Very Good", 10),
    ("F-12", "Fine", 12),
    ("F-15", "Choice Fine", 15),
    ("VF-20", "Very Fine", 20),
    ("VF-25", "Very Fine+", 25),
    ("VF-30", "Choice Very Fine", 30),
    ("VF-35", "Choice Very Fine+", 35),
    ("XF-40", "Extremely Fine", 40),
    ("XF-45", "Choice Extremely Fine", 45),
    ("AU-50", "About Uncirculated", 50),
    ("AU-53", "About Uncirculated+", 53),
    ("AU-55", "Choice About Uncirculated", 55),
    ("AU-58", "Choice About Uncirculated+", 58),
] + [(f"MS-{n}", f"Mint State {n}", n) for n in range(60, 71)]

PMG = [
    ("4", "Good", 4),
    ("6", "Good+", 6),
    ("8", "Very Good", 8),
    ("10", "Very Good+", 10),
    ("12", "Fine", 12),
    ("15", "Choice Fine", 15),
    ("20", "Very Fine", 20),
    ("25", "Very Fine+", 25),
    ("30", "Very Fine-Extremely Fine", 30),
    ("35", "Choice Very Fine", 35),
    ("40", "Extremely Fine", 40),
    ("45", "Choice Extremely Fine", 45),
    ("50", "About Uncirculated", 50),
    ("53", "About Uncirculated+", 53),
    ("55", "Choice About Uncirculated", 55),
    ("58", "Choice About Uncirculated+", 58),
    ("60", "Uncirculated", 60),
    ("61", "Uncirculated+", 61),
    ("62", "Uncirculated", 62),
    ("63", "Choice Uncirculated", 63),
    ("64", "Choice Uncirculated+", 64),
    ("65", "Gem Uncirculated", 65),
    ("66", "Gem Uncirculated+", 66),
    ("67", "Superb Gem Uncirculated", 67),
    ("68", "Superb Gem Uncirculated+", 68),
    ("69", "Superb Gem Uncirculated++", 69),
    ("70", "Perfect Uncirculated", 70),
]


def seed_rows() -> list[dict]:
    return [{"scale": "sheldon", "code": c, "label": lbl, "rank": r} for c, lbl, r in SHELDON] + [
        {"scale": "pmg", "code": c, "label": lbl, "rank": r} for c, lbl, r in PMG
    ]
