"""B-4 synthetic tests: slot verification, DET-03/06/82 folds, C-2, DET-68, §8.2.

Includes the composition test the B-3b failures taught us to write: a failed
slot reconciliation must make aggregate emission unreachable, not warned-past.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from factory.reads import (
    A1_POWERS,
    AdminRow,
    BridgeReport,
    BridgeState,
    SlotLayoutError,
    absence_evidence,
    aggregate_positions,
    check_admin_surface,
    loan_slot,
    unlisted_weight_level,
    verify_slot_layout,
)

CTRL = "0xf8c786b1064889ffd3c8a08b48d5e0c159f4cbe3"
U1 = "0x860918553d2935748ea01f88306f3b615f6572fd"
U2 = "0x68e42872838dfd8358f9486283387faea64cc954"


def _reader(table):
    return lambda contract, slot: table.get((contract, slot), 0)


def _live_like_table(base=1):
    """Values taken from the live P-3.20 verification, so the fixture is real."""
    t = {}
    for u, initial, rate in ((U1, 332477993801951547894, 1073785035247853337),
                             (U2, 500000000000000000000, 1078776605519351747)):
        t[(CTRL, loan_slot(base, u))] = initial
        t[(CTRL, loan_slot(base, u) + 1)] = rate
    return t


DEBTS = {U1: 334596312191605756817, U2: 500857378935936577668}


# --- slot verification (P-3.29 per-controller rule) --------------------------


def test_slot_layout_verifies_on_real_values():
    v = verify_slot_layout(_reader(_live_like_table()), CTRL, [U1, U2], DEBTS)
    assert v.ok and v.reconciled == v.sampled == 2
    assert v.base_slot == 1


def test_wrong_base_slot_does_not_verify():
    """Slot 0 read zeros live; the verification must refuse it."""
    v = verify_slot_layout(_reader(_live_like_table(base=1)), CTRL, [U1, U2], DEBTS, base=0)
    assert not v.ok and v.reconciled == 0
    assert v.detail  # carries why


def test_accrual_ratio_outside_band_fails_verification():
    t = _live_like_table()
    t[(CTRL, loan_slot(1, U1))] = 1  # gross/initial explodes
    v = verify_slot_layout(_reader(t), CTRL, [U1, U2], DEBTS)
    assert not v.ok
    assert any("outside band" in d for d in v.detail)


# --- composition: unverified slot => aggregates unreachable ------------------


def test_unverified_slot_makes_aggregation_unreachable():
    """The B-3b lesson applied ahead of time: a failed check must BLOCK, not warn."""
    bad = verify_slot_layout(_reader({}), CTRL, [U1], DEBTS)  # nothing readable
    assert not bad.ok
    with pytest.raises(SlotLayoutError, match="Level 3 for this market"):
        aggregate_positions(CTRL, [{"principal": 1, "gross_debt": 2,
                                    "stablecoin_in_position": 0, "collateral": 5}],
                            2, bad, {})


# --- DET-03 / DET-06 / DET-82 folds -----------------------------------------


def _agg(rows, total_debt):
    v = verify_slot_layout(_reader(_live_like_table()), CTRL, [U1, U2], DEBTS)
    return aggregate_positions(CTRL, rows, total_debt, v, {})


def test_det03_identity_and_det06_netting():
    rows = [
        {"principal": 100, "gross_debt": 110, "stablecoin_in_position": 30, "collateral": 500},
        {"principal": 200, "gross_debt": 205, "stablecoin_in_position": 300, "collateral": 900},
    ]
    a = _agg(rows, 315)
    assert a.det03_identity  # gross == principal + accrued, exactly
    assert a.accrued_interest_sum == 15
    # DET-06: net floored at 0; surplus disclosed separately, never netted in
    assert a.net_debt_sum == 80  # (110-30) + max(205-300,0)
    assert a.surplus_sum == 95   # max(300-205,0)
    assert a.stablecoin_in_position_sum == 330


def test_det82_tolerance_and_breach():
    rows = [{"principal": 100, "gross_debt": 100, "stablecoin_in_position": 0,
             "collateral": 1}]
    assert _agg(rows, 100).det82_ok
    breached = _agg(rows, 101)
    assert not breached.det82_ok
    assert breached.det82_relative_diff > Decimal("1e-9")


# --- C-2 keeper read completeness: RETIRED at B-3a --------------------------
# `check_keeper_reads` is deleted (R-B3.3). Its key set could never be met: it
# mixed per-operation reads with block-level regulator ones. `det_20` owns the
# per-operation set and `test_harness.py` exercises it, `is_killed` included.


# --- DET-68 admin surface ----------------------------------------------------


def test_nine_a1_rows_required_and_absence_shape():
    prov = absence_evidence(CTRL, "selector_absence_scan", "0xdeadbeef", 25905210)
    rows = [AdminRow(p, None, "none", (), prov) for p in A1_POWERS]
    check_admin_surface(rows)  # nine rows, enum exact
    assert prov.function is None and prov.method == "selector_absence_scan"
    with pytest.raises(ValueError, match="A1 enum mismatch"):
        check_admin_surface(rows[:-1])


# --- bridges: three states (P-3.29) -----------------------------------------


def test_bridge_states_never_claim_no_bridges_from_absent_config():
    absent = BridgeReport(BridgeState.NOT_CONFIGURED)
    assert "unassessed" in absent.disclosure
    assert "no bridges exist" not in absent.disclosure
    assert absent.bridged_component_assessed is False
    assert BridgeReport(BridgeState.EXPLICIT_EMPTY).disclosure == "no bridges exist"
    assert BridgeReport(BridgeState.POPULATED, (1, 2)).bridged_component_assessed


# --- §8.2 weight routing (the LBTC question) --------------------------------


def test_unlisted_weight_routes_to_t01_or_t09():
    assert unlisted_weight_level(Decimal("0.0499")) == 1   # T-01
    assert unlisted_weight_level(Decimal("0.05")) == 2     # T-09, boundary inclusive
    assert unlisted_weight_level(Decimal("0.31")) == 2
