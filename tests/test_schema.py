"""B-5 tests: schema invariants, determinism, bundle_hash, mirror reproduction."""

from __future__ import annotations

import json
import pathlib
from decimal import Decimal

import pytest
from pydantic import ValidationError

from factory.mirror import count_first_run_tags, generate, parse_first_run_reads
from factory.provenance import AbsenceRead, ContractRead
from factory.schema import (
    AdminRow,
    Bundle,
    CollateralNode,
    Counts,
    EmaWindow,
    FirstRunLiterals,
    Header,
    LogEntry,
    Market,
    OracleRow,
    PoolDetectors,
    PoolRow,
    PositionCompleteness,
    RedemptionPath,
    StabilizerBlock,
    StabilizerOperation,
    StaticMetadata,
    Supply,
    finalise,
    serialise,
)

REPO = pathlib.Path(__file__).resolve().parents[1]
CF = "0xc9332fdcb1c491dcc683bae86fe3cb70360738bc"
CTRL = "0xf8c786b1064889ffd3c8a08b48d5e0c159f4cbe3"
COL = "0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf"
RB = 25905210
FROZEN_POOL = "0x390f3595bca2df7d23783dfd126427cceb997bf4"


def cr(fn, contract=CTRL):
    return ContractRead(source_contract=contract, function=fn, args=[], block=RB)


def a_market(**kw):
    base = dict(
        address=CTRL, amm_address=CF, collateral_address=COL,
        monetary_policy_address=CF, symbol="cbBTC", origination_class="mint",
        decimals=8, a_coefficient=75, n_positions=28,
        principal_sum=100, accrued_interest_sum=5, gross_debt_sum=105,
        net_debt_sum=105, surplus_sum=0, stablecoin_in_position_sum=0,
        external_collateral_sum=10, external_collateral_value=6_865_146,
        position_completeness=PositionCompleteness(
            sum_position_gross_debt=105, controller_total_debt=105,
            relative_diff=Decimal(0)),
        slot_base_verified=1,
        reads={"gross_debt": cr("debt(address)"),
               "principal": AbsenceRead(contract=CTRL, method="storage_slot_read",
                                        evidence="0x…", block=RB),
               "total_debt": cr("total_debt()"), "decimals": cr("decimals()", COL),
               "collateral_price": cr("price_oracle()", CF)},
        lineage=["debt_read", "collateral_read", "price_read"],
    )
    base.update(kw)
    return Market(**base)


def a_bundle(first_run=True, **kw):
    powers = ("mint", "set_ceiling", "upgrade", "pause", "freeze_asset",
              "blacklist_address", "set_oracle", "set_parameters", "seize")
    base = dict(
        header=Header(token="crvUSD", run_block=RB, block_timestamp=1788540023,
                      run_start_time=1788540098, first_run=first_run,
                      pipeline_version="0.1.0", sheet_hash="43a5d27b",
                      # DET-10(a) limb 1: the header stamps the gate reads.
                      frozen_set_hash="80d87407", freeze_date="2026-09-04",
                      raw_positions_hash="76f7aebc"),
        markets=[a_market()],
        stabilizer=StabilizerBlock(
            operations=[StabilizerOperation(
                operation_address=CF, paired_pool_address=CTRL, debt_ceiling=0,
                current_debt=0, balance=0, utilization=None,
                utilization_na_reason="ceiling_zero", is_killed_provide=False,
                is_killed_withdraw=False,
                reads={"current_debt": cr("debt()"),
                       "balance": cr("balanceOf(address)", COL),
                       "debt_ceiling": cr("debt_ceiling(address)", CF)},
                lineage=["stabilizer_debt"])],
            ceiling_aggregate=324_000_000,
            ceiling_aggregate_lineage=["stabilizer_debt"]),
        supply=Supply(total_supply=2_104_809, supply_ruled=2_104_809,
                      bridge_state="not_configured",
                      bridge_disclosure="no bridge classification data configured",
                      origination_sum=2_000_000, residual=104_809,
                      stabilizer_over_supply=Decimal("0"),
                      reads={"total_supply": cr("totalSupply()")}),
        nodes=[CollateralNode(address=COL, symbol="cbBTC", label="recurses",
                              label_source_address=COL, node_class="volatile",
                              lst_discount_applies=False, value=6_865_146,
                              share_of_backing=Decimal("0.0455"),
                              reads={"balance": cr("balanceOf(address)", COL)},
                              lineage=["collateral_read"])],
        oracle_rows=[OracleRow(
            node_address=COL, market_or_reserve_address=CTRL, feed_or_source=CF,
            update_condition=EmaWindow(ema_window_s=866,
                                       constituents=[{"hop": "POOL", "window_s": 866}],
                                       provenance=[cr("ma_exp_time()", CF)]),
            assumption_applied="instant_optimistic_counterfactual",
            counterfactual_ref="EMA_lag", reference_feed="pending_config_round",
            market_vs_protocol_oracle_gap="pending_config_round",
            staleness_check="not_applicable_ema_oracle", use_chainlink=False)],
        # DET-66: crvUSD is one path, R1 = none - the shape run.py emits.
        redemption_paths=[RedemptionPath(
            r1_path="none", r2_who="no_one", r3_received="n/a", r4_rate="n/a",
            r5_minimum="n/a", r6_gates=[{"kind": "none", "param": None}],
            r7_capacity="n/a", r8="n/a", r9_legal_claim="no_pure_protocol",
            r10_provenance=AbsenceRead(
                contract=CF, method="selector_absence_scan",
                evidence="no holder redemption function", block=RB))],
        # DET-10: one frozen pool row and the three detector fields. The
        # fields are REQUIRED, which is where clause (c) is enforced.
        pools=[PoolRow(address=FROZEN_POOL, in_frozen_set=True,
                       paired_assets=[COL], freeze_tvl=48_308_600,
                       tvl_at_par=48_308_600,
                       ratio_to_frozen_coverage=Decimal("0.5605"),
                       is_stabilizer_pool=True)],
        pool_detectors=PoolDetectors(baseline_source="freeze_set_file"),
        admin_surface=[AdminRow(power=p, holder_address=None, holder_type="none",
                                provenance=AbsenceRead(contract=CF,
                                                       method="selector_absence_scan",
                                                       evidence="none", block=RB))
                       for p in powers],
        static_metadata=StaticMetadata(audits="none", bug_bounty="none",
                                       last_material_change_audited="no",
                                       staleness_date="2026-09-01",
                                       counterparties="n/a - archetype #1"),
        counts=Counts(mint_market_count=9,
                      lend_market_count="unknown - no lend exclusion data configured"),
        attribution_method="direct",
        first_run_literals=FirstRunLiterals() if first_run else None,
    )
    base.update(kw)
    return Bundle(**base)


# --- schema invariants -------------------------------------------------------


def test_det03_identity_enforced_at_the_model():
    with pytest.raises(ValidationError, match="DET-03 identity broken"):
        a_market(gross_debt_sum=106)


def test_det03_anti_tautology_needs_two_independent_reads():
    """C-3: all three tracing to one read plus arithmetic must fail."""
    one = {"gross_debt": cr("debt(address)"), "principal": cr("debt(address)"),
           "total_debt": cr("total_debt()"), "decimals": cr("decimals()", COL),
           "collateral_price": cr("price_oracle()", CF)}
    with pytest.raises(ValidationError, match="anti-tautology"):
        a_market(reads=one)


def test_missing_required_read_rejected():
    r = dict(a_market().reads)
    del r["principal"]
    with pytest.raises(ValidationError, match="reads missing"):
        a_market(reads=r)


def test_utilization_none_iff_ceiling_zero():
    with pytest.raises(ValidationError, match="utilization is None iff"):
        StabilizerOperation(operation_address=CF, paired_pool_address=CTRL,
                            debt_ceiling=0, current_debt=0, balance=0,
                            utilization=Decimal("0.5"), is_killed_provide=False,
                            is_killed_withdraw=False, reads={}, lineage=[])


def test_node_label_source_must_equal_address():
    with pytest.raises(ValidationError, match="label_source_address"):
        CollateralNode(address=COL, symbol="cbBTC", label="recurses",
                       label_source_address=CF, node_class="volatile",
                       lst_discount_applies=False, value=1,
                       share_of_backing=Decimal(0), reads={}, lineage=[])


def test_nine_admin_powers_required():
    b = a_bundle()
    with pytest.raises(ValidationError, match="nine A1 powers"):
        Bundle(**{**b.model_dump(), "admin_surface": b.admin_surface[:8]})


def test_first_run_bundle_must_carry_its_literals():
    with pytest.raises(ValidationError, match="must carry its literals"):
        a_bundle(first_run_literals=None)


def test_first_run_literals_are_the_ruled_strings():
    lit = a_bundle().first_run_literals
    assert lit.supply == "first run - no prior supply"
    assert lit.composition == "first run - no prior composition"


def test_log_entry_schema_is_closed():
    LogEntry(date="2026-09-04", token="crvUSD", trigger="T-01", level=1)
    with pytest.raises(ValidationError):
        LogEntry(date="2026-09-04", token="crvUSD", trigger="T-01", level=1,
                 note="extra")  # DET-60: any additional field = fail


# --- determinism and bundle_hash --------------------------------------------


def test_serialisation_is_deterministic_and_float_free():
    s = serialise(a_bundle())
    assert s == serialise(a_bundle())            # stable across builds
    assert '"0.0455"' in s                       # Decimal as string, never a float
    parsed = json.loads(s)
    assert "bundle_hash" not in parsed["header"]  # hash excluded from its own input


def test_bundle_hash_stamps_and_is_reproducible():
    b1, h1 = finalise(a_bundle())
    b2, h2 = finalise(a_bundle())
    assert h1 == h2 and b1.header.bundle_hash == h1 and len(h1) == 64


def test_bundle_hash_changes_when_content_changes():
    _, h1 = finalise(a_bundle())
    _, h2 = finalise(a_bundle(counts=Counts(mint_market_count=10,
                                            lend_market_count="unknown")))
    assert h1 != h2


# --- the mirror: reproduce-or-finding (P-3.15) ------------------------------


def test_mirror_generator_reproduces_the_committed_mirror():
    sheet = REPO / "docs/context/intake-sheets-cdp.md"
    on_disk = (REPO / "config/crvusd_sheet.toml").read_text(encoding="utf-8")
    assert generate(sheet) == on_disk, "mirror diff is a FINDING, never patched over"


def test_mirror_preserves_det75_identity():
    sheet = REPO / "docs/context/intake-sheets-cdp.md"
    assert count_first_run_tags(sheet, "crvUSD") == len(
        parse_first_run_reads(sheet, "crvUSD")) == 34
    assert count_first_run_tags(sheet, "GHO") == len(
        parse_first_run_reads(sheet, "GHO")) == 46


def test_det10c_detector_fields_are_required_at_the_model():
    """DET-10(c) has NO consequence level in the rubric, so no gate invents one.
    It is enforced here instead: a bundle without `pool_detectors` cannot be
    constructed, so there is no runtime failure path to assign a level to."""
    base = a_bundle()
    fields = {k: v for k, v in base.__dict__.items() if k != "pool_detectors"}
    with pytest.raises(ValidationError):
        Bundle(**fields)
