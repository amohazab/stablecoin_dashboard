"""B-1 tests: the stress report's hash, the two stops, and the routing.

Four, by ruling. Two of them need no fixture repository because both stops are
pure functions; the other two use `emit(tmp_path, ...)`, the `test_tree.py`
pattern, so nothing is written inside the repo.
"""

from __future__ import annotations

import hashlib
import pathlib
from decimal import Decimal

import pytest

from factory.run import AssemblyStop
from factory.schema import (
    ExitDepth,
    Mechanism,
    StressHeader,
    StressReport,
    finalise_stress,
    serialise_stress,
)
from factory.stress import (
    LP_FLIGHT_LITERAL,
    assert_raw_hash,
    assert_sheet_coherent,
    emit,
)
from factory.tree import latest_bundle, latest_tree

REPO = pathlib.Path(__file__).resolve().parents[1]


def _report(token: str = "LUSD", stale: bool = False) -> StressReport:
    b, t = latest_bundle(REPO, token), latest_tree(REPO, token)
    return StressReport(
        header=StressHeader(
            token=token, run_block=b.header.run_block,
            source_bundle_hash=b.header.bundle_hash,
            source_tree_hash=t.tree_hash,
            bundle_sheet_hash=b.header.sheet_hash,
            mirror_sheet_hash=b.header.sheet_hash,
            stale_sheet=stale, pipeline_version="0.1.0"),
        value_scale=t.root.value_scale,
        exit_depth=ExitDepth(lp_flight_literal=LP_FLIGHT_LITERAL),
        mechanism=Mechanism())


def test_finalise_stress_is_deterministic_and_excludes_its_own_hash():
    r = _report()
    a, b = finalise_stress(r), finalise_stress(r)
    assert a.header.stress_hash == b.header.stress_hash
    assert len(a.header.stress_hash) == 64
    # the stamp is never an input to itself: re-finalising a STAMPED report
    # reproduces the same value, which it could not do if it were hashed in.
    assert finalise_stress(a).header.stress_hash == a.header.stress_hash
    assert serialise_stress(a).count(a.header.stress_hash) == 1


def test_a_tampered_raw_dump_stops_the_run():
    raw = (REPO / "out/raw/25955393.json").read_bytes()
    good = hashlib.sha256(raw).hexdigest()
    assert_raw_hash(good, raw)                       # the real pair passes
    with pytest.raises(AssemblyStop, match="raw_positions_hash"):
        assert_raw_hash(good, raw + b" ")


def test_the_sheet_stop_fires_and_the_dev_flag_routes_to_rehearsal(tmp_path):
    assert assert_sheet_coherent("c7298252", "c7298252", False) is False
    with pytest.raises(AssemblyStop, match="d2114a96"):
        assert_sheet_coherent("d2114a96", "c7298252", False)
    assert assert_sheet_coherent("d2114a96", "c7298252", True) is True
    b, t = latest_bundle(REPO, "LUSD"), latest_tree(REPO, "LUSD")
    path, ok = emit(tmp_path, b, t, _report(stale=True))
    assert not ok
    # the block is DERIVED, never pinned: a pinned one breaks on every re-run
    # of the adapter, which is exactly what B-3b's three re-runs did.
    assert path == tmp_path / f"out/rehearsal/LUSD/stress-{b.header.run_block}.json"
    written = StressReport.model_validate_json(path.read_text(encoding="utf-8"))
    assert written.header.stale_sheet is True


def test_a_zero_cell_report_is_never_promotable(tmp_path):
    """A clean sheet pairing and no cells still routes to rehearsal.

    At B-1 this test also asserted every check passed, so that the empty cell
    set was demonstrably the ONLY thing keeping the report out of
    `out/stress/`. B-2 retired that half: the five stress entries now fail on a
    synthetic report with an empty `exit_depth`, which is correct behaviour and
    not something to stub around. The zero-cell clause itself is unchanged.
    """
    b, t = latest_bundle(REPO, "LUSD"), latest_tree(REPO, "LUSD")
    r = _report()
    assert r.cells == [] and r.header.stale_sheet is False
    path, ok = emit(tmp_path, b, t, r)
    assert not ok
    assert path == tmp_path / f"out/rehearsal/LUSD/stress-{b.header.run_block}.json"
    written = StressReport.model_validate_json(path.read_text(encoding="utf-8"))
    assert written.cells == [] and len(written.checks) == 25  # +DET-46/47/51


# --- B-3a: DET-50's three branches, the kill decode, DET-52's plumbing -------


def _with_cands(r: StressReport, target=None) -> StressReport:
    from factory.schema import Member2Candidate
    usdt, usdc = "0x" + "d" * 40, "0x" + "c" * 40
    ed = r.exit_depth.model_copy(update={"member2_candidates": [
        Member2Candidate(asset=usdt, depth_at_2pct=90, share=Decimal("0.9"),
                         label="recurses", basis="gsm_venue"),
        Member2Candidate(asset=usdc, depth_at_2pct=10, share=Decimal("0.1"),
                         label="recurses", basis="paired_direct")]})
    return r.model_copy(update={"exit_depth": ed, "member2_target": target})


def test_det50_records_the_owed_fill_rather_than_failing_on_a_null_target():
    """P-3.09 R-a1's precedent: nothing consumes `member2_target` until the
    Member-2 cells exist, so a null is an OWED fill. The scope condition names
    the address the fill must carry, which is what makes the pass auditable
    instead of permissive."""
    from factory.validate.harness import det_50
    b, t = latest_bundle(REPO, "LUSD"), latest_tree(REPO, "LUSD")
    scope = det_50(b, t, _with_cands(_report()))
    assert scope.startswith("target owed: fill event lands 0x" + "d" * 40)


def test_det50_asserts_identity_once_the_target_is_filled():
    from factory.validate.harness import Level3, det_50
    b, t = latest_bundle(REPO, "LUSD"), latest_tree(REPO, "LUSD")
    usdt, usdc = "0x" + "d" * 40, "0x" + "c" * 40
    assert "share 0.9" in det_50(b, t, _with_cands(_report(), usdt))
    with pytest.raises(Level3, match="!= the largest"):
        det_50(b, t, _with_cands(_report(), usdc))       # not the argmax


def test_det50_fails_when_a_target_is_asserted_with_no_table():
    from factory.validate.harness import Level3, det_50
    b, t = latest_bundle(REPO, "LUSD"), latest_tree(REPO, "LUSD")
    r = _report().model_copy(update={"member2_target": "0x" + "d" * 40})
    with pytest.raises(Level3, match="no candidate table"):
        det_50(b, t, r)


def test_the_kill_flag_decodes_as_two_independent_bits():
    """From the verified source's `enum Killed: Provide # 1 / Withdraw # 2`.
    The both-killed state is 3, which an equality test would miss."""
    from factory.reads import decode_killed
    assert decode_killed(0) == (False, False)
    assert decode_killed(1) == (True, False)
    assert decode_killed(2) == (False, True)
    assert decode_killed(3) == (True, True)


def test_det20_requires_the_kill_read_on_every_stabilizer_row():
    import tests.test_schema as ts
    from factory.validate.harness import Level3, det_20
    b = ts.a_bundle()
    det_20(b, {})                                        # the fixture carries it
    op = b.stabilizer.operations[0]
    stripped = op.model_copy(update={
        "reads": {k: v for k, v in op.reads.items() if k != "is_killed"}})
    with pytest.raises(Level3, match="is_killed"):
        det_20(b.model_copy(update={
            "stabilizer": b.stabilizer.model_copy(update={"operations": [stripped]})}), {})


def test_the_sell_side_parameter_is_armed_and_volatile_only():
    """DET-52's plumbing, live since B-3b's signed edit put 19 rows on the
    sheet. Until then `cfg.sell_side` was empty and every node got `None`;
    now the rows load, and the two rules that remain are: only a VOLATILE node
    carries one, and a node the sheet does not list gets `None` rather than a
    default — which is what makes DET-52's Level 3 reachable."""
    from factory.config import load, sell_side_for
    cfg = load(REPO / "config", "GHO")
    assert len(cfg.sell_side) == 11
    weth = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
    got = sell_side_for(cfg, weth, "volatile")
    assert got["value"] == "13750.0000" and got["date"] == "2026-09-12"
    assert "Paraswap" in got["source"]
    assert sell_side_for(cfg, weth, "stable") is None       # volatile only
    assert sell_side_for(cfg, "0x" + "f" * 40, "volatile") is None   # unlisted
    # USCC's zero is a VALUE, not an absence: the row is complete and passes.
    uscc = sell_side_for(cfg, "0x14d60e7fdc0d71d8611742720e4c50e7a974020c", "volatile")
    assert uscc["value"] == "0" and "no route" in uscc["source"]
    assert len(load(REPO / "config", "crvUSD").sell_side) == 8
    assert len(load(REPO / "config", "LUSD").sell_side) == 1


# --- B-4a: DET-69's either-direction equality --------------------------------


def test_det69_fails_in_both_directions():
    """The entry's own wording: "either direction mismatch = fail". A row
    marked live with nothing consuming it fails; so does a run that consumes a
    §13 field whose row is unmarked. GHO is the live example of the first —
    its `pause` mark (R18) anticipates DET-46's freezer routing, which is
    B-5's, so the mark leads its consumer."""
    from factory.validate.harness import Level3, det_69
    b, t = latest_bundle(REPO, "LUSD"), latest_tree(REPO, "LUSD")
    r = _report()
    assert det_69(b, t, r).startswith("marked == consumed")   # LUSD marks nothing

    marked = b.admin_surface[0].model_copy(update={
        "live_model_input": True, "consumed_by": ["DET-45 alpha"]})
    b_marked = b.model_copy(update={"admin_surface": [marked] + list(b.admin_surface[1:])})
    with pytest.raises(Level3, match="marked .* != consumed"):
        det_69(b_marked, t, r)                     # marked, nothing consumes it
