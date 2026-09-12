"""B-4a tests: the regulator port, A-5's ceiling min, and the band union.

Every expected number here is hand-computed from the source's own form, not
copied from a run — the B-2 posture. The live figures at 25963950 are asserted
in `test_stress.py` against the folded artifact.
"""

from __future__ import annotations

from decimal import Decimal
from math import isqrt

import pytest

from factory.llamma import (
    ONE,
    Keeper,
    LlammaError,
    allowed,
    band_union,
    get_max_ratio,
    get_ratio,
    headroom,
    scale_alpha_beta,
)

ALPHA, BETA = ONE // 2, ONE // 4                    # 0.5 / 0.25, the deployed pair


def k(addr: str, debt: int, balance: int, ceiling: int, killed: bool = False) -> Keeper:
    return Keeper(address=addr, debt=debt, balance=balance, ceiling=ceiling,
                  killed_provide=killed, killed_withdraw=False)


def test_the_ratio_carries_the_sources_one_wei_guard():
    """R-B4.2. DET-45 prints `debt / (debt + balance)`; the DEPLOYED form is
    `debt * ONE / (1 + debt + balance)`. The guard is not cosmetic: it is what
    makes an all-zero keeper return 0 instead of dividing by zero, and it moves
    every other ratio by one wei, which is the difference between a replay that
    is an identity and one that is merely close."""
    empty = k("0x" + "0" * 40, 0, 0, 0)
    assert get_ratio(empty) == 0                     # no ZeroDivisionError
    a = k("0x" + "1" * 40, 10 ** 18, 3 * 10 ** 18, 0)
    assert get_ratio(a) == 10 ** 18 * ONE // (1 + 4 * 10 ** 18)
    naive = 10 ** 18 * ONE // (4 * 10 ** 18)         # the rubric's printed form
    assert get_ratio(a) != naive                     # they differ, by design


def test_max_ratio_reproduces_the_source_form():
    """`(alpha + beta * Σ isqrt(r * ONE) / ONE) ** 2 / ONE`, integer throughout
    (R-B4.3). Hand-computed, so a refactor that swapped in a float or a Decimal
    root would fail here rather than in a run."""
    r1, r2 = ONE // 25, ONE // 4                     # 0.04 and 0.25
    want = (ALPHA + BETA * (isqrt(r1 * ONE) + isqrt(r2 * ONE)) // ONE) ** 2 // ONE
    assert get_max_ratio([r1, r2], ALPHA, BETA) == want
    # √0.04 = 0.2, √0.25 = 0.5 -> (0.5 + 0.25*0.7)^2 = 0.675^2 = 0.455625
    assert abs(Decimal(want) / Decimal(ONE) - Decimal("0.455625")) < Decimal("1e-9")
    assert get_max_ratio([], ALPHA, BETA) == ONE // 4          # (0.5)^2 with no peers


def test_the_ceiling_min_is_the_memos_and_it_binds():
    """R-B4.4 / A-5. `provide_allowed` has NO ceiling term — the min is the
    memo's. At 25963950 no head binds, so it is exercised on a synthetic: a
    keeper whose formula allowance exceeds its remaining ceiling is cut to the
    ceiling, and one already at its ceiling gets zero rather than a negative."""
    keepers = [k("0x" + "a" * 40, 0, 100 * ONE, 10 * ONE),      # head 10 < formula
               k("0x" + "b" * 40, 50 * ONE, 50 * ONE, 50 * ONE)]  # at ceiling
    a0, mx0 = allowed(keepers, 0, ALPHA, BETA)
    raw0 = mx0 * (0 + 100 * ONE) // ONE - 0
    assert raw0 > 10 * ONE and a0 == 10 * ONE                   # cut to the head
    a1, _ = allowed(keepers, 1, ALPHA, BETA)
    assert a1 == 0                                              # floored, never < 0


def test_a_killed_provide_keeper_contributes_zero_but_still_counts_for_peers():
    """DET-45's letter on the subject, and the chain's behaviour on its peers:
    `_get_ratio` reads a killed keeper's debt regardless of the flag, because
    the regulator keeps it in `peg_keepers`."""
    live = k("0x" + "a" * 40, 0, 100 * ONE, 100 * ONE)
    dead = k("0x" + "b" * 40, 40 * ONE, 60 * ONE, 100 * ONE, killed=True)
    a_dead, _ = allowed([live, dead], 1, ALPHA, BETA)
    assert a_dead == 0
    with_dead, _ = allowed([live, dead], 0, ALPHA, BETA)
    alone, _ = allowed([live, k("0x" + "b" * 40, 0, 0, 0)], 0, ALPHA, BETA)
    assert with_dead > alone          # the dead keeper's ratio still lifts its peer


def test_effective_never_exceeds_naive():
    keepers = [k("0x" + "a" * 40, 0, 100 * ONE, 100 * ONE),
               k("0x" + "b" * 40, 30 * ONE, 70 * ONE, 100 * ONE),
               k("0x" + "c" * 40, 0, 0, 0)]
    eff, naive, per = headroom(keepers, ALPHA, BETA)
    assert eff <= naive
    assert sum(r["allowed"] for r in per.values()) == eff
    assert len(per) == 3


def test_alpha_beta_scale_from_the_bundles_human_units():
    assert scale_alpha_beta(Decimal("0.5"), Decimal("0.25")) == (ALPHA, BETA)
    with pytest.raises(LlammaError, match="no alpha/beta"):
        scale_alpha_beta(None, Decimal("0.25"))


def test_the_band_union_deduplicates_shared_bands():
    """R11's gate turns on this. Two positions overlapping on three bands cost
    3 + 4 = 7 band-slots but only 5 distinct reads."""
    ticks = {"0xa": (10, 12), "0xb": (11, 14)}
    assert band_union(ticks) == [10, 11, 12, 13, 14]
    assert sum(hi - lo + 1 for lo, hi in ticks.values()) == 7
    assert band_union({"0xa": (5, 5)}) == [5]
    assert band_union({}) == []
