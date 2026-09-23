"""Metal detection and fineness parsing (P11, v0.31.0, stage 1): the one
rule each in `pricing.detect_metal` and `pricing.parse_fineness`, the table
the frontend's `detectMetal` mirrors."""

from decimal import Decimal

import pytest

from app.services import numista, pricing

DETECT = [
    ("Silver", "silver"),
    ("90% silver", "silver"),
    ("Copper 10%, Silver 90%", "silver"),
    ("Silver (.900)", "silver"),
    ("Gold", "gold"),
    ("Golden brass", None),  # whole words only
    ("Nickel silver", None),
    ("German silver", None),
    ("Nordic gold", None),  # the euro 10, 20, 50 cent alloy
    ("Copper-nickel", None),
    ("Gold plated brass", None),
    ("Gold-plated brass", None),
    ("Silver-plated copper", None),
    ("Gold plated silver", "silver"),  # the plating is a surface, the silver is the metal
    ("Silver-gilt", "silver"),
    ("Silver, gilt", "silver"),
    ("Gold washed silver", "silver"),
    ("40% silver-clad", "silver"),  # clad is not stripped: the halves hold silver
    ("Bimetallic: gold centre 75%, silver ring 25%", "gold"),
    ("Silver 25%, gold 75%", "gold"),
    ("Silver ring, gold centre", "silver"),  # no shares: the first named
    ("Platinum", "platinum"),
    ("Palladium 95%", "palladium"),
    ("", None),
    (None, None),
]


@pytest.mark.parametrize("composition,metal", DETECT, ids=[str(c) for c, _ in DETECT])
def test_detect_metal(composition, metal):
    assert pricing.detect_metal(composition) == metal


FINENESS = [
    ("90% silver", "silver", "0.900"),
    ("Silver 90%", "silver", "0.900"),
    ("Copper 10%, Silver 90%", "silver", "0.900"),  # the metal's own percentage, not the first
    ("Silver (90%)", "silver", "0.900"),
    ("Silver (.900)", "silver", "0.900"),
    ("0.925 silver", "silver", "0.925"),
    (".9999 gold", "gold", "0.9999"),
    ("Silver 999", "silver", "0.999"),
    ("Gold 916.7", "gold", "0.9167"),
    ("Silver 999.9", "silver", "0.9999"),
    ("Sterling silver", "silver", "0.925"),
    ("Britannia silver", "silver", "0.958"),
    ("Coin silver", "silver", "0.900"),
    ("22K gold", "gold", "0.9167"),
    ("22 karat gold", "gold", "0.9167"),
    ("24K gold", "gold", "0.999"),
    ("18 ct gold", "gold", None),  # "ct" is not a carat word; nothing is guessed
    ("18k gold", "gold", "0.750"),
    ("14K gold", "gold", "0.585"),
    ("9K gold", "gold", "0.375"),
    ("21K gold", "gold", "0.8750"),  # not in the table: carats / 24
    ("Silver", "silver", None),
    ("Silver, 1 oz", "silver", None),  # a weight is not a fineness
    ("Bronze 950", None, None),  # no precious metal: no fineness
    ("Silver 950", "gold", None),  # placeholder: see the test below
]


CASES = FINENESS[:-1]


@pytest.mark.parametrize("composition,metal,fineness", CASES, ids=[c for c, *_ in CASES])
def test_parse_fineness(composition, metal, fineness):
    found = pricing.parse_fineness(composition, metal)
    assert found == (Decimal(fineness) if fineness is not None else None)


def test_parse_fineness_reads_a_plain_number_for_any_named_metal():
    # The millesimal fallback isn't tied to the metal, since a composition
    # rarely names two finenesses; the caller decides the metal.
    assert pricing.parse_fineness("Silver 950", "gold") == Decimal("0.950")


def test_numista_and_melt_share_the_parser():
    assert numista.fineness_from_composition("Copper 10%, Silver 90%") == 0.9
    assert numista.fineness_from_composition("Nickel silver") is None
    assert numista.fineness_from_composition("Gold 916.7") == 0.9167
    assert numista.fineness_from_composition("Bronze 950") is None
