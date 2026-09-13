"""B-6 tests: the Liquity mechanism, exercised where the live book cannot.

R-B6.1 is the point of this file. At 25963959 the minimum ICR is 5.9683 against
an MCR of 1.10, so no trove is eligible at any point on §6.2's grid and the
promoted artifact's twelve Member-1 cells are all zero. The offset,
redistribution and bad-debt paths are therefore exercised HERE, on a synthetic
book where the Stability Pool IS exhausted and redistribution DOES reach a
trove below 100% — the entry's conditions, met on purpose.
"""

from __future__ import annotations

import json
import pathlib
from decimal import Decimal

import pytest

from factory.lusd_cells import (
    M4_KEYS,
    ONE_E18,
    LusdError,
    Trove,
    crash_path,
    decayed_base_rate,
    icr,
    redemption_capacity,
    redistribute,
)

REPO = pathlib.Path(__file__).resolve().parents[1]
MCR = Decimal("1.10")
PRICE = 1000 * ONE_E18                       # $1,000/ETH, round numbers on purpose


def t(owner: str, debt: float, coll: float) -> Trove:
    return Trove(owner=owner, debt=int(debt * ONE_E18), coll=int(coll * ONE_E18))


# --------------------------------------------------------------- the model ---


def test_redistribution_conserves_debt_and_collateral_exactly():
    """Σ before = Σ after, as integers — the identity DET-51 rests on.

    The shares are deliberately not divisible: 7 and 13 wei against a basis of
    three unequal survivors, so every pro-rata share floors and the remainder
    has to land somewhere. If it were dropped the sums would differ by wei and
    this test would fail, which is the whole point of asserting equality rather
    than a tolerance.
    """
    liq = [Trove("0xdead", debt=7, coll=13)]
    surv = [t("0xa", 100, 1), t("0xb", 200, 3), t("0xc", 300, 7)]
    after, r_debt, r_coll = redistribute(liq, surv)
    assert r_debt == 7 and r_coll == 13
    assert sum(x.debt for x in after) == sum(x.debt for x in surv) + 7
    assert sum(x.coll for x in after) == sum(x.coll for x in surv) + 13


def test_redistribution_basis_of_zero_stops():
    """Survivors holding no collateral make Liquity's pro-rata rule undefined;
    the model stops instead of dividing by zero or inventing a basis."""
    with pytest.raises(LusdError, match="basis is zero"):
        redistribute([t("0xdead", 10, 10)], [Trove("0xa", debt=5, coll=0)])


def test_stability_pool_offsets_whole_troves_ascending_by_icr():
    """A trove is offset entire or not at all, and the Pool is spent on the
    worst trove first — R12's ascending-by-CR default read onto Liquity's ICR."""
    book = [t("0xworst", 100, 0.09),          # ICR 0.90
            t("0xmid", 100, 0.105),           # ICR 1.05
            t("0xsafe", 100, 2.0)]            # ICR 20.0
    res = crash_path(book, PRICE, MCR, sp_effective=int(100 * ONE_E18))
    assert res["eligible"] == 2               # 0.90 and 1.05 are under MCR
    assert res["offset"] == 1                 # the Pool covers exactly one
    assert res["redistributed"] == 1
    # the Pool took the WORST one, so what is left to redistribute is the 1.05
    assert res["bad_debt"] == 0               # 1.05 is above 100%, no shortfall


def test_bad_debt_is_the_redistributed_troves_own_shortfall():
    """DET-51's reading, named in the module and asserted here.

    One trove at ICR 0.90 is redistributed with the Pool empty: its shortfall
    is 100 debt against 90 of collateral value = 10. The receiving trove ends
    up at a LOWER ratio than it started, but nothing about the receiver enters
    `bad_debt` — that is the other reading, and it would double-count.
    """
    book = [t("0xunder", 100, 0.09), t("0xsafe", 100, 2.0)]
    res = crash_path(book, PRICE, MCR, sp_effective=0)
    assert res["redistributed"] == 1
    assert res["bad_debt"] == int(10 * ONE_E18)
    assert res["redistributed_below_100"] == res["bad_debt"]
    assert res["redistributed_debt"] == int(100 * ONE_E18)
    assert res["conserved"]


def test_a_redistributed_trove_above_100_contributes_no_bad_debt():
    """Eligible (ICR < MCR) is not the same condition as insolvent (CR < 1).
    A trove at 1.05 is liquidated and redistributed, and carries no shortfall."""
    book = [t("0xmid", 100, 0.105), t("0xsafe", 100, 2.0)]
    res = crash_path(book, PRICE, MCR, sp_effective=0)
    assert res["redistributed"] == 1 and res["bad_debt"] == 0


def test_bad_debt_is_never_negative():
    book = [t("0xa", 100, 0.109), t("0xb", 100, 5.0)]
    for sp in (0, int(50 * ONE_E18), int(1e9 * ONE_E18)):
        assert crash_path(book, PRICE, MCR, sp_effective=sp)["bad_debt"] >= 0


def test_bad_debt_is_monotone_in_the_shock():
    """R-29 on the shock axis, on a book that actually liquidates."""
    book = [t("0xa", 100, 0.30), t("0xb", 100, 0.20), t("0xc", 100, 5.0)]
    last = -1
    for shock in (Decimal("-0.20"), Decimal("-0.35"), Decimal("-0.50"),
                  Decimal("-0.70")):
        p = int(Decimal(PRICE) * (Decimal(1) + shock))
        bad = crash_path(book, p, MCR, sp_effective=0)["bad_debt"]
        assert bad >= last
        last = bad
    assert last > 0                            # the axis is genuinely exercised


# ----------------------------------------------------------------- H4 --------


def test_decayed_base_rate_is_the_contracts_own_state():
    """No decay over zero elapsed minutes; strictly decaying after that."""
    mdf = 999037758833783000
    assert decayed_base_rate(10 ** 16, mdf, 1000, 1000) == Decimal("0.01")
    later = decayed_base_rate(10 ** 16, mdf, 1000, 1000 + 60 * 60)
    assert later < Decimal("0.01")


def test_redemption_capacity_zero_once_the_fee_ceiling_is_passed():
    floor = Decimal("0.005")
    assert redemption_capacity(Decimal("0.10"), floor, 2, 10 ** 24) == 0
    assert redemption_capacity(Decimal("0"), floor, 2, 10 ** 24) > 0


# ------------------------------------------------- the promoted artifact -----


def _artifact():
    p = REPO / "out/stress/LUSD/25963959.json"
    if not p.exists():
        pytest.skip("LUSD stress artifact not present")
    return json.loads(p.read_text(encoding="utf-8"))


def _bundle():
    return json.loads((REPO / "out/bundles/LUSD/25963959.json")
                      .read_text(encoding="utf-8"))


def test_tcr_post_at_the_base_cell_replays_the_system_reads():
    """`tcr_post` on the unshocked compound cell must equal the TCR implied by
    `getEntireSystemColl()` / `getEntireSystemDebt()` to 1e-6."""
    a, b = _artifact(), _bundle()
    m = b["markets"][0]
    price = (Decimal(m["external_collateral_value"])
             / Decimal(m["external_collateral_sum"]))
    want = (Decimal(m["external_collateral_sum"]) * price
            / Decimal(m["gross_debt_sum"]))
    cell = next(c for c in a["cells"] if c["id"] == "M2-compound")
    assert abs(Decimal(cell["m4"]["tcr_post"]) - want) < Decimal("1e-6")
    assert abs(Decimal(b["system_tcr"]) - want) < Decimal("1e-6")


def test_every_cell_carries_the_nine_m4_keys_and_the_tellor_line():
    a = _artifact()
    assert len(a["cells"]) == 23
    for c in a["cells"]:
        assert set(c["m4"]) == set(M4_KEYS)
        ids = {ln["id"] for ln in c["counterfactual_lines"]}
        assert "Tellor_fallback" in ids
    lines = [ln for c in a["cells"] for ln in c["counterfactual_lines"]
             if ln["id"] == "Tellor_fallback"]
    for ln in lines:
        assert ln["metric_affected"] == "none"
        assert ln["value_primary"] is None and ln["value_counterfactual"] is None
        assert "14400 s" in ln["assumption_text"]


def test_r_b6_1_the_grid_never_engages_the_mechanism():
    """The finding itself, pinned: every Member-1 cell is zero, and the artifact
    says at what shock the mechanism would first engage."""
    a = _artifact()
    for c in a["cells"]:
        if c["member"] == "M1":
            assert c["m2"]["bad_debt"] == 0
            assert c["m4"]["redistributed_debt"] == 0
            assert c["m4"]["recovery_mode_flag"] is False
    lit = a["assumptions"]["engagement_thresholds"]
    assert "-81.57%" in lit and "-78.48%" in lit and "72 troves" in lit


def test_the_live_book_has_no_eligible_trove_at_the_deepest_shock():
    """Read from the raw dump, not from the artifact: the premise R-B6.1 rests
    on, asserted against the source rows."""
    b = _bundle()
    rows = json.loads((REPO / "out/raw/25963959.json").read_text(encoding="utf-8"))
    m = b["markets"][0]
    price = int(Decimal(m["external_collateral_value"]) * ONE_E18
                // Decimal(m["external_collateral_sum"]))
    worst = int(Decimal(price) * Decimal("0.30"))          # the -70% grid point
    troves = [Trove(r["owner"], r["debt"], r["coll"]) for r in rows]
    assert len(troves) == 72
    assert min(icr(x, worst) for x in troves) > MCR
