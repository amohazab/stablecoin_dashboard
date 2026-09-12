"""B-1 tests: the stress report's hash, the two stops, and the routing.

Four, by ruling. Two of them need no fixture repository because both stops are
pure functions; the other two use `emit(tmp_path, ...)`, the `test_tree.py`
pattern, so nothing is written inside the repo.
"""

from __future__ import annotations

import hashlib
import pathlib

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
    assert path == tmp_path / "out/rehearsal/LUSD/stress-25955393.json"
    written = StressReport.model_validate_json(path.read_text(encoding="utf-8"))
    assert written.header.stale_sheet is True


def test_a_zero_cell_report_is_never_promotable(tmp_path):
    """The clause on its own: nothing fails and the sheet pairing is clean, so
    the empty cell set is the only thing keeping it out of `out/stress/`."""
    b, t = latest_bundle(REPO, "LUSD"), latest_tree(REPO, "LUSD")
    r = _report()
    assert r.cells == [] and r.header.stale_sheet is False
    path, ok = emit(tmp_path, b, t, r)
    assert not ok
    assert path == tmp_path / "out/rehearsal/LUSD/stress-25955393.json"
    assert all(x.result == "pass" for x in
               StressReport.model_validate_json(
                   path.read_text(encoding="utf-8")).checks)
