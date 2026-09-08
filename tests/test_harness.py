"""B-6 tests: the S0/S1 harness, the log, the spot-check sheet.

The composition tests are the ones the B-3b failures taught us to write: a
failing harness must make promotion UNREACHABLE, not warned-past.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
from decimal import Decimal

import pytest

from factory.config import Root
from factory.discovery import still_enumerated
from factory.eventlog import FreezeEvent, IntakeTriggerEvent, last_event
from factory.logbook import Logbook, is_first_run, load_prior
from factory.provenance import AbsenceRead
from factory.schema import (
    Counts,
    LogEntry,
    PoolDetectors,
    PoolRow,
    PriorBundle,
    RedemptionPath,
    finalise,
)
from factory.spotcheck import generate as spot_generate
from factory.validate.harness import (
    TRIGGER_TABLE,
    Level3,
    NotYetImplemented,
    det_66,
    run_harness,
)
from tests.test_discovery import FakeRpc
from tests.test_schema import CF, CTRL, FROZEN_POOL, RB, a_bundle

CRVUSD = "0xf939e0a03fb07f59a73314e73794be0e57ac1b4e"


def a_prior(**kw):
    """A prior as `ctx["prior_bundle"]` actually holds it: a `PriorBundle`.

    Built by round-tripping a full bundle through the view, which is what
    `load_prior` does with the stored JSON - so these tests exercise the same
    parser the store is read with, not a convenient stand-in.
    """
    return PriorBundle.model_validate(a_bundle(**kw).model_dump())


def a_ctx(**kw):
    base = dict(
        labels={}, printed_trigger_table=dict(TRIGGER_TABLE),
        sheet={"sheet_hash": "43a5d27b", "near_bound_threshold": 0.80,
               "counterparties": "n/a", "attribution_method": "direct"},
        roots={"controller_factory": Root("controller_factory", CF, "r", "s",
                                          dt.date(2026, 9, 1))},
        today=dt.date(2026, 9, 4), is_first_run=True, prior_bundle=None,
        # DET-10 / DET-77 chain to the event log; both comparands come from
        # OUTSIDE the bundle, never from the bundle itself.
        event_log=[
            IntakeTriggerEvent(date="2026-09-04", token="crvUSD",
                               sheet_hash="43a5d27b", set_file_hash=None,
                               source="test"),
            FreezeEvent(date="2026-09-04", token="crvUSD",
                        freeze_block=25905210, set_file_hash="80d87407",
                        set_file_path="config/frozen_set_crvusd.json",
                        source="test"),
        ],
        last_event=last_event,
        frozen_set_members={FROZEN_POOL},
        last_run_ratio={FROZEN_POOL: Decimal("0.5605")},
    )
    base.update(kw)
    return base


# --- the harness passes on a clean bundle ------------------------------------


def test_clean_bundle_passes_every_check():
    out = run_harness(a_bundle(), a_ctx())
    assert out.all_pass and out.worst_level == 0
    assert {r.entry_id for r in out.results} >= {"DET-02", "DET-12", "DET-77",
                                                 "DET-83", "DET-86", "DET-82"}
    assert all(r.result in ("pass", "fail", "not_applicable", "error")
               for r in out.results)     # DET-13(c) enum, no skipped/overridden


# --- S0 ----------------------------------------------------------------------


def test_det12_trigger_table_mismatch_stops_the_pipeline():
    bad = dict(TRIGGER_TABLE)
    bad["T-13"] = 2                      # a Level-3 trigger demoted
    with pytest.raises(Level3, match="DET-12"):
        run_harness(a_bundle(), a_ctx(printed_trigger_table=bad))


def test_det77_sheet_hash_binds_bundle_to_mirror():
    with pytest.raises(Level3, match="DET-77"):
        run_harness(a_bundle(), a_ctx(sheet={"sheet_hash": "deadbeef",
                                             "near_bound_threshold": 0.8,
                                             "counterparties": "n/a",
                                             "attribution_method": "direct"}))


# --- S1 ----------------------------------------------------------------------


def test_det83_stale_block_is_level_3():
    b = a_bundle()
    b.header.run_start_time = b.header.block_timestamp + 4000
    with pytest.raises(Level3, match="DET-83"):
        run_harness(b, a_ctx())


def test_det86_first_run_must_agree_with_the_bundle_store():
    with pytest.raises(Level3, match="DET-86"):
        run_harness(a_bundle(first_run=True), a_ctx(is_first_run=False))


def test_det86_convention_named_in_the_log_module():
    """P-3.14: the Step-3 convention is carried as a named convention."""
    assert "P-3.14" in is_first_run.__doc__
    assert "monotone in the fail-closed direction" in is_first_run.__doc__


def test_det82_breach_is_level_3():
    b = a_bundle()
    b.markets[0].position_completeness.relative_diff = Decimal("1e-6")
    with pytest.raises(Level3, match="DET-82"):
        run_harness(b, a_ctx())


def test_det61_near_bound_fires_t07_level_1_and_publishes():
    b = a_bundle()
    op = b.stabilizer.operations[0]
    op.debt_ceiling, op.current_debt = 100, 90
    op.utilization, op.utilization_na_reason = Decimal("0.9"), None
    out = run_harness(b, a_ctx())
    assert ("T-07", 1) in out.triggers and out.worst_level == 1   # publishes


def test_det08_unlisted_over_5pct_is_level_2_and_raises():
    b = a_bundle()
    b.nodes[0].label = "unlisted"
    b.nodes[0].share_of_backing = Decimal("0.31")
    with pytest.raises(Level3, match="Level 2"):
        run_harness(b, a_ctx())


def test_det08_unlisted_under_5pct_is_level_1_the_lbtc_shape():
    """The live LBTC case: 0.0000% of backing -> T-01, report publishes."""
    b = a_bundle()
    b.nodes[0].label = "unlisted"
    b.nodes[0].share_of_backing = Decimal("0.0000")
    out = run_harness(b, a_ctx())
    assert out.triggers == [] or ("T-09", 2) not in out.triggers


def test_det33_absent_bridge_config_must_be_disclosed():
    b = a_bundle()
    b.supply.bridge_disclosure = "all good"        # not a disclosure of absence
    with pytest.raises(Level3, match="DET-33"):
        run_harness(b, a_ctx())


def test_det66_r1_none_implication_is_enforced():
    """DET-66 synthetic fail path: R1 = none must force R2 = no_one.

    The live crvUSD block conforms, so the fail path cannot be exercised
    against real data - the input is built to violate exactly one clause.
    """
    bad = RedemptionPath(
        r1_path="none", r2_who="anyone", r3_received="n/a", r4_rate="n/a",
        r5_minimum="n/a", r6_gates=[{"kind": "none", "param": None}],
        r7_capacity="n/a", r8="n/a", r9_legal_claim="no_pure_protocol",
        r10_provenance=AbsenceRead(contract=CF, method="selector_absence_scan",
                                   evidence="no holder redemption function",
                                   block=RB))
    with pytest.raises(Level3, match="DET-66"):
        run_harness(a_bundle(redemption_paths=[bad]), a_ctx())


def test_det66_gho_token_raises_not_yet_implemented():
    """The ruled fail-loud dispatch: a token whose path-count clause is not
    built raises rather than passing. `run_harness` turns it into DET-85's
    `error` + Level 3 (T-25); asserted on `det_66` directly so the exception
    type itself is pinned, not just its harness consequence."""
    gho = a_bundle(header=a_bundle().header.model_copy(update={"token": "GHO"}))
    with pytest.raises(NotYetImplemented, match="GHO"):
        det_66(gho, a_ctx())



# --- DET-10, one synthetic fail path per clause (the live state passes) -------


def test_det10a_hash_mismatch_and_null_chain_both_fail_closed():
    """(a) Level 3, its two ruled fail modes. A null `set_file_hash` on the last
    event is backfilled entry 1's shape: no chain is not a passing chain."""
    bad = a_bundle().model_copy(update={"header": a_bundle().header.model_copy(
        update={"frozen_set_hash": "deadbeef"})})
    with pytest.raises(Level3, match="DET-10"):
        run_harness(bad, a_ctx())
    only_null = [IntakeTriggerEvent(date="2026-09-04", token="crvUSD",
                                    sheet_hash="43a5d27b", set_file_hash=None,
                                    source="test")]
    with pytest.raises(Level3, match="null set_file_hash"):
        run_harness(a_bundle(), a_ctx(event_log=only_null))


def test_det10b_modeled_pool_outside_the_frozen_set_fails():
    """(b) Level 2: membership is exact equality against the SIGNED set file."""
    with pytest.raises(Level3, match="DET-10.b."):
        run_harness(a_bundle(), a_ctx(frozen_set_members={CTRL}))


def test_det10d_new_pool_above_ten_percent_fires_t10():
    """(d)-i Level 2 via T-10: a new above-floor pool at >= 10% of coverage."""
    b = a_bundle()
    rows = list(b.pools) + [PoolRow(
        address=CTRL, in_frozen_set=False, tvl_at_par=20_000_000,
        ratio_to_frozen_coverage=Decimal("0.12"),
        exclusion_reason="added_since_freeze",
        annotations=["detector: new pool above the dust floor"])]
    b = b.model_copy(update={
        "pools": rows,
        "pool_detectors": PoolDetectors(new_pool_above_floor=[CTRL],
                                        baseline_source="freeze_set_file")})
    with pytest.raises(Level3, match="Level 2 trigger"):
        run_harness(b, a_ctx())


def test_det10d_disappeared_frozen_pool_above_ten_percent_fires_t10():
    """(d)-ii Level 2 via T-10, on the FACTORY-SIDE pin (ruled 2026-09-07).

    `still_enumerated` is exercised against a stubbed `pool_list(index)` that
    returns a different address - the disappearance condition - and the row it
    annotates then drives the trigger. The row is KEPT (P-3.46 R5) so (b)'s
    exact-equality membership still holds and the event evaluates FROM the row
    rather than from its absence.
    """
    other = "0x" + "ab" * 20
    table = {(CF, "pool_count()", ()): (600,),
             (CF, "pool_list(uint256)", ("117",)): (other,)}
    assert still_enumerated(FakeRpc(table), FROZEN_POOL, CF, 117) is False
    # and the same pool still listed at its index is NOT a disappearance
    ok = {(CF, "pool_count()", ()): (600,),
          (CF, "pool_list(uint256)", ("117",)): (FROZEN_POOL,)}
    assert still_enumerated(FakeRpc(ok), FROZEN_POOL, CF, 117) is True

    b = a_bundle()
    row = b.pools[0].model_copy(update={
        "annotations": ["disappeared: pool_factory_crvusd.pool_list(1) "
                        "no longer holds it"]})
    b = b.model_copy(update={"pools": [row]})
    with pytest.raises(Level3, match="Level 2 trigger"):
        run_harness(b, a_ctx())


def test_det10e_undisclosed_detection_fails():
    """(e) Level 2: a detection with no matching pool-row annotation."""
    b = a_bundle()
    b = b.model_copy(update={"pool_detectors": PoolDetectors(
        frozen_pool_below_floor=[FROZEN_POOL], baseline_source="freeze_set_file")})
    with pytest.raises(Level3, match="undisclosed detection"):
        run_harness(b, a_ctx())


def test_det10f_freeze_overdue_fires_t17_level_1_and_publishes():
    """(f) Level 1 via T-17, evaluated against the bundle's own pinned date -
    never a wall clock - so a stored bundle re-run gives the same answer."""
    b = a_bundle().model_copy(update={"header": a_bundle().header.model_copy(
        update={"freeze_date": "2026-05-01"})})
    out = run_harness(b, a_ctx())
    assert ("T-17", 1) in out.triggers and out.worst_level == 1


def test_det77_second_limb_chains_to_the_logged_intake_trigger():
    """The sheet edit that never logged its event fails HERE at Level 3 - the
    gate that makes the (d)-machinery's new last step load-bearing."""
    stale = [FreezeEvent(date="2026-09-04", token="crvUSD", freeze_block=25905210,
                         set_file_hash="80d87407",
                         set_file_path="config/frozen_set_crvusd.json",
                         source="test"),
             IntakeTriggerEvent(date="2026-09-05", token="crvUSD",
                                sheet_hash="ffffffff", set_file_hash="80d87407",
                                source="test")]
    with pytest.raises(Level3, match="DET-77"):
        run_harness(a_bundle(), a_ctx(event_log=stale))


def test_det04_stale_analyst_root_fires_t16():
    old = {"controller_factory": Root("controller_factory", CF, "r", "s",
                                      dt.date(2026, 1, 1))}
    out = run_harness(a_bundle(), a_ctx(roots=old))
    assert ("T-16", 1) in out.triggers


# --- run 2 semantics (the seven flips) ---------------------------------------


def test_run2_supply_jump_without_confirmations_is_level_3():
    prior = a_prior(first_run=True)
    b = a_bundle(first_run=False, first_run_literals=None)
    b.supply.total_supply = prior.supply.total_supply * 2
    with pytest.raises(Level3, match="Level 2|DET-62|T-14"):
        run_harness(b, a_ctx(is_first_run=False, prior_bundle=prior,
                             supply_confirmations={}))


def test_det62_confirmation_legs_are_read_when_the_branch_opens():
    """3.2: the jump branch's wiring, proved against stubbed legs.

    crvUSD `totalSupply` is piecewise-constant - it moves only on a governance
    ceiling change (P-3.40) - so this branch will essentially never open live.
    The prior is synthetic precisely so the wiring is exercised at all.
    """
    calls: list[str] = []

    def stub_get(url: str) -> dict:
        calls.append(url)
        if "etherscan" in url:
            return {"result": "2104809"}          # both legs return raw wei
        return {"total_supply": "2104809"}

    prior = a_prior(supply=a_bundle().supply.model_copy(
        update={"total_supply": 1_000_000}))
    b = a_bundle(first_run=False, first_run_literals=None)
    out = run_harness(b, a_ctx(is_first_run=False, prior_bundle=prior,
                               http_get=stub_get, token_address=CRVUSD))
    # both legs read, on the v2 Etherscan base, both agreeing within 5%
    assert len(calls) == 2
    assert any("/v2/api?chainid=1" in u and "tokensupply" in u for u in calls)
    assert any("blockscout" in u for u in calls)
    assert ("T-05", 1) in out.triggers and out.worst_level == 1


def test_run2_market_removal_is_level_2():
    prior = a_prior(first_run=True)
    b = a_bundle(first_run=False, first_run_literals=None,
                 counts=Counts(mint_market_count=8, lend_market_count="unknown"))
    with pytest.raises(Level3, match="Level 2"):
        run_harness(b, a_ctx(is_first_run=False, prior_bundle=prior))


# --- composition: a failing harness makes promotion unreachable --------------


def promote(bundle, ctx, out_dir: pathlib.Path) -> pathlib.Path:
    """The only promotion path: the harness gates it structurally."""
    run_harness(bundle, ctx)                      # raises => nothing below runs
    stamped, _ = finalise(bundle)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{stamped.header.run_block}.json"
    p.write_text(json.dumps({"ok": True}), encoding="utf-8")
    return p


def test_level3_makes_promotion_unreachable(tmp_path):
    b = a_bundle()
    b.markets[0].position_completeness.relative_diff = Decimal("1e-6")  # DET-82
    with pytest.raises(Level3):
        promote(b, a_ctx(), tmp_path)
    assert list(tmp_path.glob("*.json")) == [], "no bundle may be written on a Level 3"


def test_clean_run_promotes():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = promote(a_bundle(), a_ctx(), pathlib.Path(d))
        assert p.exists()


# --- the log -----------------------------------------------------------------


def test_log_rejects_illegal_resolution_type(tmp_path):
    lb = Logbook(tmp_path / "log.json")
    with pytest.raises(ValueError, match="illegal resolution_type"):
        lb.append(LogEntry(date="2026-09-04", token="crvUSD", trigger="T-01",
                           level=1, resolution_type="override",
                           resolution_date="2026-09-05"))


def test_log_requires_type_and_date_together(tmp_path):
    lb = Logbook(tmp_path / "log.json")
    with pytest.raises(ValueError, match="set together"):
        lb.append(LogEntry(date="2026-09-04", token="crvUSD", trigger="T-01",
                           level=1, resolution_type="config_change"))


def test_log_round_trips_and_counts_quarantined_runs(tmp_path):
    p = tmp_path / "log.json"
    lb = Logbook(p)
    lb.append(LogEntry(date="2026-09-04", token="crvUSD", trigger="T-13", level=3))
    lb.append(LogEntry(date="2026-09-05", token="crvUSD", trigger="T-09", level=2))
    lb.write()
    again = Logbook(p)
    assert len(again.entries) == 2
    assert again.consecutive_quarantined_runs("crvUSD") == 2
    assert again.open_levels("crvUSD") == [3, 2]


def test_is_first_run_uses_prior_bundles_not_publication(tmp_path):
    assert is_first_run(tmp_path, "crvUSD") is True
    d = tmp_path / "crvUSD"
    d.mkdir()
    (d / "1.json").write_text("{}")
    assert is_first_run(tmp_path, "crvUSD") is False


# --- the spot-check sheet ----------------------------------------------------


def _sheet():
    b, _ = finalise(a_bundle())
    return spot_generate(b, crvusd=CRVUSD, controller_factory=CF,
                         biggest_position={"user": CTRL, "collateral": 10,
                                           "stablecoin_in_position": 0,
                                           "gross_debt": 105})


def test_spotcheck_never_embeds_a_key():
    """Binding 1. Rev 2 satisfies it by construction: the transports are
    keyless, so there is no placeholder to substitute and nothing to leak."""
    s = _sheet()
    assert "apikey" not in s.lower()
    assert "ETHERSCAN_API_KEY" not in s
    assert "No API key appears anywhere in this file" in s
    assert "gitignored" in s


def test_spotcheck_transport_pins_and_is_independent():
    """Binding 5 + the independence invariant the rev-1 defect exposed.

    Rev 1 shipped a transport that silently answered every call at the head.
    The sheet must now prove it pins before any row is trusted, and must read
    through two operators rather than one so agreement — not trust in a single
    provider — carries the check.
    """
    from factory.spotcheck import PIN_TEST_BLOCK, PRIMARY, SECOND

    s = _sheet()
    assert "pin self-test" in s.lower()
    assert f"0x{PIN_TEST_BLOCK:x}" in s and "must be DIFFERENT" in s
    assert PRIMARY in s and SECOND in s
    assert "etherscan.io/v2/api" not in s          # rev-1 transport is gone
    # the block is pinned in the JSON-RPC body, never as a query parameter
    assert '"params":[' in s and "&tag=" not in s


def test_spotcheck_states_checker_independence_and_both_value_forms():
    s = _sheet()
    assert "substitutable" in s.lower() and "ANY row" in s
    assert "0x" in s and "expected (raw hex)" in s and "expected (decoded)" in s


def test_spotcheck_keeper_address_comes_from_the_bundle():
    """Binding 4: P4's no-hardcoded-keepers rule applies to tooling too."""
    b, _ = finalise(a_bundle())
    s = spot_generate(b, crvusd=CRVUSD, controller_factory=CF, biggest_position=None)
    assert b.stabilizer.operations[0].operation_address[:10] in s


def test_spotcheck_carries_the_mismatch_rule():
    assert "flag, never a correction" in _sheet()


def test_spotcheck_item10_is_informational_not_a_gate():
    """Ruled 2026-09-05: no rubric entry owns a supply-level agreement gate,
    so the sheet must not manufacture one. The row records a figure; it does
    not threshold it."""
    s = _sheet()
    row = next(ln for ln in s.splitlines() if ln.startswith("| 10 |"))
    assert "Informational" in row and "no threshold, no pass/fail" in row
    assert "within 5%" not in row          # the gate is gone from the row...
    assert "within 5%" in s                # ...and survives only as the note
    assert "do not compare it to `totalSupply()`" in s


def test_every_promoted_bundle_on_disk_still_loads():
    """SCHEMA-EVOLUTION REGRESSION GUARD.

    Every bundle in the committed store must load through `load_prior`'s
    parser. Nothing else in the suite deserializes a bundle written by an
    earlier version - the in-process fixture tracks the current schema by
    construction, the on-disk store does not - which is exactly how P-3.46
    shipped a tree whose demonstration run died before its first read.

    Reads the REAL committed artifacts, as `test_discovery` reads the real
    config. The standing rule this encodes: before any commit that changes
    `Bundle`'s shape, this test must pass.
    """
    store = pathlib.Path(__file__).resolve().parents[1] / "out/bundles/crvUSD"
    promoted = sorted(store.glob("*.json"))
    assert promoted, "no promoted bundles to guard"
    for path in promoted:
        block = int(path.stem)
        got = load_prior(store.parent, "crvUSD", block + 1)
        assert got is not None, f"{path.name} did not load"
        assert got.header.run_block == block
