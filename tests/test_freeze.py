"""B-3b synthetic tests: DET-09 routing, freeze construction, DET-11 labelling.

These prove the routing. Only the live freeze proves the data (P-3.17).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

import factory.freeze as freeze_mod
from factory.freeze import (
    DUST_FLOOR_USD,
    DiscoveredPool,
    DiscoveryMismatch,
    FreezeCoverageStop,
    ScopeDeclaration,
    SourceTotal,
    build_freeze,
    classify_exclusions,
    label_paired_assets,
    par_value,
    reconcile,
)

USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
CVCRVUSD = "0xcea18a8752bb7e7817f9ae7565328fe415c0f2ca"
WSTETH = "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0"
PMUSD = "0xc0c17dd08263c16f6b64e772fb9b723bf1344ddf"
CRVUSD_ADDR = "0xf939e0a03fb07f59a73314e73794be0e57ac1b4e"


def pool(addr, paired, tvl, stab=False):
    return DiscoveredPool(addr, (paired,), tvl, stab)


# --- DET-09 ------------------------------------------------------------------


def test_reconcile_within_tolerance_returns_m():
    m = reconcile([SourceTotal("curve_api", 100_000_000),
                   SourceTotal("defillama", 98_000_000),
                   SourceTotal("onchain", 99_000_000)])
    assert m == Decimal("0.020000")  # (100-98)/100, denominator max (R-3)


def test_reconcile_beyond_tolerance_is_level_3():
    with pytest.raises(DiscoveryMismatch, match="M = "):
        reconcile([SourceTotal("curve_api", 100_000_000),
                   SourceTotal("defillama", 90_000_000),
                   SourceTotal("onchain", 99_000_000)])


def test_reconcile_requires_exactly_three_legs():
    with pytest.raises(ValueError, match="exactly three"):
        reconcile([SourceTotal("curve_api", 1), SourceTotal("defillama", 1)])


# --- §5.4 / DET-34 -----------------------------------------------------------


def test_self_referential_wrapper_excluded_and_named():
    """R-4: the extension is load-bearing — the pool clears the floor."""
    pools = [pool("0xp1", USDT, 49_000_000), pool("0xp2", CVCRVUSD, 690_000)]
    ex = classify_exclusions(pools, volatile_nodes=set(), self_referential={CVCRVUSD})
    assert [(e.address, e.exclusion_reason) for e in ex] == [
        ("0xp2", "self_referential_wrapper")
    ]


def test_volatile_circular_reason_only_for_volatile_nodes():
    """DET-34: a stablecoin-paired pool must never carry the circular reason."""
    pools = [pool("0xp1", WSTETH, 5_000_000), pool("0xp2", USDC, 5_000_000)]
    ex = classify_exclusions(pools, volatile_nodes={WSTETH}, self_referential=set())
    assert [(e.address, e.exclusion_reason) for e in ex] == [
        ("0xp1", "volatile_collateral_circular")
    ]


# --- the freeze --------------------------------------------------------------


def test_freeze_applies_floor_but_exempts_stabilizer_pools():
    """§5.5 floor; P-4 exemption; DET-24 — every stabilizer pool lands in F."""
    pools = [
        pool("0xbig", USDT, 90_000_000),
        pool("0xdust", PMUSD, 100_000),                      # below floor, dropped
        pool("0xkeeper", USDC, 200_000, stab=True),          # below floor, EXEMPT
    ]
    fs = build_freeze(pools, [], "2026-09-04", 25904647)
    addrs = {p.address for p in fs.pools}
    assert "0xbig" in addrs
    assert "0xkeeper" in addrs, "stabilizer pool must be in F regardless of floor"
    assert "0xdust" not in addrs
    assert all(p.tvl_at_par >= DUST_FLOOR_USD or p.is_stabilizer_pool for p in fs.pools)


def test_freeze_coverage_below_target_stops_for_waiver():
    """R-a3: never a self-issued waiver — the run stops with the numbers."""
    pools = [pool("0xa", USDT, 500_000)] + [
        pool(f"0xd{i}", PMUSD, 400_000) for i in range(10)  # dust: 4M below floor
    ]
    with pytest.raises(FreezeCoverageStop) as ei:
        build_freeze(pools, [], "2026-09-04", 25904647)
    assert ei.value.achieved < Decimal("0.95")
    assert ei.value.discovery_total == 4_500_000
    assert ei.value.tail, "the stop must carry the excluded tail for the decision"


def test_set_file_fields_and_member2_target_null():
    fs = build_freeze([pool("0xa", USDT, 90_000_000), pool("0xb", USDC, 9_000_000)],
                      [], "2026-09-04", 25904647)
    assert fs.chain_id == 1
    assert fs.freeze_block == 25904647
    assert fs.member2_target is None  # R-a1: filled at the Step-6/7 refresh
    assert fs.coverage_waiver is None
    assert fs.freeze_coverage >= Decimal("0.95")


def test_k_subset_is_shortest_prefix_and_nested():
    fs = build_freeze(
        [pool("0xa", USDT, 60_000_000), pool("0xb", USDC, 30_000_000),
         pool("0xc", PMUSD, 9_000_000), pool("0xd", "0xzz", 1_000_000)],
        [], "2026-09-04", 25904647)
    k90 = fs.k_subset(Decimal("0.90"))
    k95 = fs.k_subset(Decimal("0.95"))
    assert {p.address for p in k90} <= {p.address for p in k95}
    assert [p.address for p in k90] == ["0xa", "0xb"]  # 90M/100M reaches 90%


# --- DET-11 / T-18 -----------------------------------------------------------


def test_unlabeled_paired_asset_above_5pct_is_level_2():
    modeled = (pool("0xp1", USDT, 50_000_000), pool("0xp2", PMUSD, 50_000_000))
    labels = label_paired_assets(modeled, {"0xp1": 500, "0xp2": 500}, {USDT: "recurses"})
    by = {x.address: x for x in labels}
    assert by[USDT].label == "recurses"
    assert by[PMUSD].label == "unlabeled"
    assert by[PMUSD].level == 2  # q = 0.5


def test_unlabeled_paired_asset_below_5pct_is_level_1_and_pool_stays():
    modeled = (pool("0xp1", USDT, 97_000_000), pool("0xp2", PMUSD, 2_000_000))
    labels = label_paired_assets(modeled, {"0xp1": 970, "0xp2": 20}, {USDT: "recurses"})
    by = {x.address: x for x in labels}
    assert by[PMUSD].level == 1
    assert by[PMUSD].share_of_exit_depth < Decimal("0.05")


def test_q_is_share_of_depth_not_tvl():
    """DET-11 defines q over exit depth; a TVL-weighted answer would differ."""
    modeled = (pool("0xp1", USDT, 90_000_000), pool("0xp2", PMUSD, 10_000_000))
    # depth is deliberately NOT proportional to tvl here
    labels = label_paired_assets(modeled, {"0xp1": 100, "0xp2": 100}, {USDT: "recurses"})
    by = {x.address: x for x in labels}
    assert by[PMUSD].share_of_exit_depth == Decimal("0.5")  # not 0.10
    assert by[PMUSD].level == 2


# --- regressions from the failed first execution (P-3.26) --------------------

SPANK = "0xc425c0877c7b0f8179cdbd636b2efe3204b24bc4"


def test_par_eligibility_gate_zeroes_unruled_assets():
    """F1 regression: the live SPANK pool valued at $1.004B before the gate.

    An asset with no ruled row contributes ZERO and is disclosed as a zeroed
    side; no external price enters the path.
    """
    coins = [USDC, USDT, "0xf939e0a03fb07f59a73314e73794be0e57ac1b4e", SPANK]
    balances = [50_000, 470_000, 800 * 10**18, 1_004_406_865 * 10**18]
    decimals = [6, 6, 18, 18]
    eligible = {USDC, USDT, "0xf939e0a03fb07f59a73314e73794be0e57ac1b4e"}

    value, zeroed = par_value(coins, balances, decimals, eligible)

    assert value == 800  # ruled sides only; the billion SPANK units contribute 0
    assert [z.address for z in zeroed] == [SPANK]
    assert zeroed[0].units == 1_004_406_865
    assert zeroed[0].par_eligibility == "none"


def test_zeroed_pool_dies_at_the_floor_with_its_ruled_reason():
    """The SPANK-class pool must leave with DET-29(a)'s below_dust_floor."""
    pools = [pool("0xbig", USDT, 90_000_000), pool("0xspank", SPANK, 1)]
    fs = build_freeze(pools, [], "2026-09-04", 25904962)
    reasons = {e.address: e.exclusion_reason for e in fs.excluded}
    assert reasons["0xspank"] == "below_dust_floor"
    assert "0xspank" not in {p.address for p in fs.pools}


def test_q_partitions_pool_depth_across_paired_assets():
    """F3 regression: four paired assets in one pool each returned q = 1.0."""
    multi = DiscoveredPool("0xmulti", (USDC, USDT, SPANK, "0xrlusd"), 1_000_000)
    labels = label_paired_assets((multi,), {"0xmulti": 400}, {USDC: "recurses"})
    shares = {x.address: x.share_of_exit_depth for x in labels}
    assert sum(shares.values()) == Decimal(1)          # partitioned, not duplicated
    assert all(v == Decimal("0.25") for v in shares.values())
    unl = {x.address: x for x in labels if x.label == "unlabeled"}
    assert unl[SPANK].level == 2  # 0.25 >= 5%


# --- composition test: the gap that module tests could not see (D1, P-3.27) --

SCOPE = ScopeDeclaration("crvUSD stableswap pools, post-5.4", ("factory-crvusd",))


def test_discovery_mismatch_makes_the_freeze_unreachable(monkeypatch):
    """D1: a T-13 must make build_freeze UNREACHABLE, not warned-past.

    Two consecutive live executions built a set past a raised
    DiscoveryMismatch because the orchestration caught it. Module tests cannot
    see this; only a composition test can.
    """
    called: list[int] = []
    monkeypatch.setattr(freeze_mod, "build_freeze", lambda *a, **k: called.append(1))

    bad = [SourceTotal("curve_api", 100_000_000),
           SourceTotal("defillama", 10_000_000),
           SourceTotal("onchain_par", 90_000_000)]
    with pytest.raises(DiscoveryMismatch):
        freeze_mod.discover_and_freeze(bad, [pool("0xa", USDT, 9_000_000)], [],
                                       "2026-09-04", 25905086, SCOPE)
    assert called == [], "build_freeze must never be reached on a T-13"


def test_clean_legs_reach_the_freeze_and_record_the_scope():
    legs = [SourceTotal("curve_api", 100_000_000),
            SourceTotal("defillama", 98_000_000),
            SourceTotal("onchain_par", 99_000_000)]
    m, fs = freeze_mod.discover_and_freeze(
        legs, [pool("0xa", USDT, 90_000_000), pool("0xb", USDC, 9_000_000)], [],
        "2026-09-04", 25905086, SCOPE)
    assert m == Decimal("0.020000")
    assert fs.discovery_m == m
    assert fs.scope is SCOPE  # M auditable against a named universe


def test_node_label_row_grants_no_par_eligibility():
    """P-3.27 residual: cvcrvUSD has a label row but no paired_asset row."""
    coins = [CRVUSD_ADDR, CVCRVUSD]
    value, zeroed = par_value(coins, [322_044 * 10**18, 452_708_949 * 10**18],
                              [18, 18], {CRVUSD_ADDR})  # paired set only
    assert value == 322_044
    assert [z.address for z in zeroed] == [CVCRVUSD]
    assert zeroed[0].units == 452_708_949
