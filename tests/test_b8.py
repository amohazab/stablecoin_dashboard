"""B-8 tests (P-7.01 R1): the seven S2 rows registered from buckets (a)+(b).

One test pins each row's result on the three promoted artifacts — the rows
that fail on today's data register failing (P-6.08's DET-69 precedent), and
this table changes when B-9 resolves them. One mutation per row proves the
check can fail on a bundle that passes it.
"""

from __future__ import annotations

import pathlib
from decimal import Decimal

import pytest

from factory.tree import latest_bundle, latest_tree
from factory.validate.harness import (
    Level3,
    _derive_r8,
    det_06,
    det_16,
    det_22,
    det_28,
    det_29a,
    det_34,
    det_67,
    det_72,
    run_tree_checks,
)

REPO = pathlib.Path(__file__).resolve().parents[1]
NEW = ("DET-06", "DET-16", "DET-22", "DET-28", "DET-34", "DET-67", "DET-72")
# B-9 (P-7.03 ruling 1): the five rows that failed at B-8 - GHO DET-28/67/72,
# LUSD DET-06/67 - pass on the B-9 artifacts, which is what this table pins.
EXPECTED = {t: dict.fromkeys(NEW, "pass") for t in ("crvUSD", "GHO", "LUSD")}


@pytest.fixture(scope="module")
def art():
    return {t: (latest_bundle(REPO, t), latest_tree(REPO, t)) for t in EXPECTED}


def test_b8_rows_on_the_promoted_artifacts(art):
    for token, want in EXPECTED.items():
        got = {g.entry_id: g.result for g in run_tree_checks(*art[token])
               if g.entry_id in NEW}
        assert got == want, token


def test_det06_fails_when_netting_sums_break(art):
    b, t = art["crvUSD"]
    m = b.markets[2].model_copy(update={"surplus_sum": b.markets[2].surplus_sum + 1})
    with pytest.raises(Level3, match="DET-06"):
        det_06(b.model_copy(update={"markets": [*b.markets[:2], m, *b.markets[3:]]}), t)


def test_det16_fails_on_a_line_that_does_not_replay(art):
    b, t = art["crvUSD"]
    s = b.supply.model_copy(update={
        "stabilizer_over_supply": b.supply.stabilizer_over_supply + Decimal("1e-5")})
    with pytest.raises(Level3, match="DET-16"):
        det_16(b.model_copy(update={"supply": s}), t)


def test_det22_fails_on_a_ceiling_aggregate_off_by_one(art):
    b, t = art["crvUSD"]
    st = b.stabilizer.model_copy(update={"ceiling_aggregate": b.stabilizer.ceiling_aggregate + 1})
    with pytest.raises(Level3, match="DET-22"):
        det_22(b.model_copy(update={"stabilizer": st}), t)


def test_det28_fails_on_a_gsm_count_without_rows(art):
    b, t = art["crvUSD"]
    with pytest.raises(Level3, match="gsm_count"):
        det_28(b.model_copy(update={"counts": b.counts.model_copy(update={"gsm_count": 1})}), t)


def test_det34_fails_on_a_reason_outside_the_set(art):
    b, t = art["crvUSD"]
    pools = [p.model_copy(update={"exclusion_reason": "other"})
             if p.exclusion_reason == "tail_beyond_freeze_coverage" else p for p in b.pools]
    with pytest.raises(Level3, match="outside the set"):
        det_34(b.model_copy(update={"pools": pools}), t)


def test_det67_fails_on_a_hand_keyed_r8(art):
    b, t = art["crvUSD"]
    paths = [b.redemption_paths[0].model_copy(update={"r8": "enforceable"})]
    with pytest.raises(Level3, match="DET-67"):
        det_67(b.model_copy(update={"redemption_paths": paths}), t)


def test_derive_r8_reproduces_the_rubrics_verified_strings(art):
    """DET-67's "Verified" line: GHO GSM → `enforceable_unless_paused (see R7)`;
    LUSD → `enforceable_unless_TCR<MCR (see R7)` on DET-66's ruled R6
    {state_conditional(TCR<MCR), capacity_limited}; crvUSD → `n/a`."""
    gho = art["GHO"][0].redemption_paths[0]
    assert _derive_r8(gho) == "enforceable_unless_paused (see R7)"
    lusd = art["LUSD"][0].redemption_paths[0].model_copy(update={"r6_gates": [
        {"kind": "state_conditional", "param": "system_tcr"},
        {"kind": "capacity_limited", "param": None}]})
    assert _derive_r8(lusd) == "enforceable_unless_TCR<MCR (see R7)"
    assert _derive_r8(art["crvUSD"][0].redemption_paths[0]) == "n/a"


def _set_file(token: str) -> dict:
    import json
    path = REPO / f"config/frozen_set_{token.lower()}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_det29a_on_the_three_set_files_under_the_recorded_readings(art):
    """P-7.03: `tvl_at_par` is the set file's `freeze_tvl`; GHO's waiver reason
    counts as the literal with its elaboration, so GHO carries T-20 Level 1."""
    for token, want in (("crvUSD", None), ("GHO", ("T-20", 1)), ("LUSD", None)):
        assert det_29a(art[token][0], {"frozen_set": _set_file(token)}) == want, token


def test_det29a_fails_closed_without_a_waiver_or_a_pool_tvl(art):
    gho = _set_file("GHO")
    with pytest.raises(Level3, match="without a waiver"):
        det_29a(art["GHO"][0], {"frozen_set": {**gho, "r20_waiver": None}})
    crv = _set_file("crvUSD")
    pools = [{k: v for k, v in p.items() if k != "tvl_at_par"} for p in crv["pools"]]
    with pytest.raises(Level3, match="freeze_tvl"):
        det_29a(art["crvUSD"][0], {"frozen_set": {**crv, "pools": pools}})


def test_det72_fails_on_a_pausable_mark_with_no_matching_row(art):
    b, t = art["LUSD"]
    p = b.redemption_paths[0]
    paths = [p.model_copy(update={"r6_gates": [*p.r6_gates, {"kind": "pausable", "param": None}]})]
    with pytest.raises(Level3, match="DET-72"):
        det_72(b.model_copy(update={"redemption_paths": paths}), t)
