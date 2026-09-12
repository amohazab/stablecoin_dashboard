"""Step 6 B-1: the stress report's container, its two stops, and its routing.

`uv run python -m factory.stress <TOKEN> [--allow-stale-sheet]` folds the
LATEST promoted bundle in `out/bundles/<TOKEN>/`, its tree and its raw dump
into a `StressReport` at `out/stress/<TOKEN>/<run_block>.json` (P-6.01 R2).
One required positional token, `sys.argv[1]` - the P-4.02 shape, no argparse.

B-1 BUILDS THE CONTAINER AND THE ROUTING ONLY. `fold` is a stub returning the
present-and-empty report: no pool is read, no cell is computed, `len(CHECKS)`
does not move. From B-2 on this module DOES make pinned reads - unlike
`factory.tree`, which is a pure fold - at the bundle's own `run_block`, and
R-13 holds precisely because the block is the bundle's, not a fresh one.

TWO STOPS, both before anything is folded, both pure functions so they are
testable without a fixture repository:

  * `assert_raw_hash` - the raw dump's bytes must hash to the bundle's
    `raw_positions_hash`. This is P-3.05's integrity link finally exercised:
    the link was recorded so "a regenerated dump is verifiable byte-identical
    to what the run consumed", and until now nothing checked it. The preimage
    is the FILE BYTES AS WRITTEN, never a re-serialisation - each adapter
    hashes the exact string it then writes, so re-encoding here would test our
    own encoder rather than the link.
  * `assert_sheet_coherent` - the bundle's `sheet_hash` must equal the config
    mirror's (P-6.01 R3). `--allow-stale-sheet` is a DEV flag and nothing
    else: it stamps `stale_sheet` into the artifact and forces rehearsal
    routing regardless of checks, and Step 8's cron never passes it.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys

from factory.config import load
from factory.schema import (
    ExitDepth,
    Mechanism,
    StressHeader,
    StressReport,
    finalise_stress,
    serialise_stress,
)

# Memo section 6.1.4's content, carried as a constant because it is text, not a
# computed figure. The RENDERED wording is DET-36's at Step 7 and may be
# re-ruled there; this is the field it renders from.
LP_FLIGHT_LITERAL = (
    "LP capital assumed sticky; haircut grid 0% / 30% / 60% - assumed scenario "
    "modifier, not data-derived; LP flight modeled as single-sided withdrawal "
    "of the paired asset."
)


# ------------------------------------------------------------- the stops ----


def assert_raw_hash(expected: str, raw_bytes: bytes) -> None:
    """P-3.05's integrity link. A mismatch means the dump on disk is not the
    one the run consumed, so nothing folded from it can be trusted."""
    got = hashlib.sha256(raw_bytes).hexdigest()
    if got != expected:
        from factory.run import AssemblyStop  # lazy: `run` pulls the adapters
        raise AssemblyStop(
            f"raw dump does not match the bundle's raw_positions_hash: "
            f"bundle {expected}, file {got}. The dump on disk is not the one "
            "this bundle was assembled from (P-3.05).")


def assert_sheet_coherent(bundle_sheet_hash: str, mirror_sheet_hash: str,
                          allow_stale: bool) -> bool:
    """R3. Returns True when the pairing is stale AND the dev flag permits it;
    False when the two agree. Raises otherwise."""
    if bundle_sheet_hash == mirror_sheet_hash:
        return False
    if not allow_stale:
        from factory.run import AssemblyStop
        raise AssemblyStop(
            f"sheet stamps disagree: bundle {bundle_sheet_hash}, mirror "
            f"{mirror_sheet_hash}. The promoted bundle predates the current "
            "sheet; re-run the adapter, or pass --allow-stale-sheet to fold a "
            "rehearsal artifact (P-6.01 R3).")
    return True


# ------------------------------------------------------------- the inputs ---


def load_inputs(repo: pathlib.Path, token: str,
                allow_stale_sheet: bool = False) -> dict:
    """The promoted bundle, ITS tree, its raw dump and its config, with both
    stops applied before anything is folded."""
    from factory.run import AssemblyStop
    from factory.tree import latest_bundle, latest_tree

    bundle = latest_bundle(repo, token)
    tree = latest_tree(repo, token)
    if tree is None:
        raise AssemblyStop(
            f"no tree in out/trees/{token}/ - run `factory.tree {token}` first; "
            "the stress module folds a bundle AND its tree.")
    # "its tree", asserted rather than assumed: the latest tree must be the one
    # folded from the latest bundle, or a promotion without a re-fold would
    # silently pair a new bundle with an old tree.
    if tree.source_bundle_hash != bundle.header.bundle_hash:
        raise AssemblyStop(
            f"the latest tree was folded from a different bundle: tree "
            f"{tree.source_bundle_hash[:8]}, bundle "
            f"{bundle.header.bundle_hash[:8]}. Re-fold before stressing.")

    cfg = load(repo / "config", token)
    raw_path = repo / "out/raw" / f"{bundle.header.run_block}.json"
    if not raw_path.exists():
        raise AssemblyStop(
            f"raw dump absent at {raw_path} - it is gitignored and regenerable "
            "from any archive node at run_block (P-3.05), but it is not "
            "optional: the stress module folds per-position rows.")
    raw_bytes = raw_path.read_bytes()
    assert_raw_hash(bundle.header.raw_positions_hash, raw_bytes)
    stale = assert_sheet_coherent(bundle.header.sheet_hash,
                                  cfg.sheet["sheet_hash"], allow_stale_sheet)
    fs = json.loads(cfg.frozen_set_path.read_text(encoding="utf-8"))
    return {"bundle": bundle, "tree": tree, "cfg": cfg, "raw": raw_bytes,
            "stale_sheet": stale, "member2_target": fs.get("member2_target")}


# --------------------------------------------------------------- the fold ---


def fold(inputs: dict) -> StressReport:
    """B-1's stub: the present-and-empty report. Every figure below the header
    lands at its own block - exit depth at B-2, the mechanism block at B-4/5/6,
    the cells from B-4 on."""
    from factory.run import PIPELINE_VERSION
    b, t = inputs["bundle"], inputs["tree"]
    return StressReport(
        header=StressHeader(
            token=b.header.token, run_block=b.header.run_block,
            source_bundle_hash=b.header.bundle_hash,
            source_tree_hash=t.tree_hash,
            bundle_sheet_hash=b.header.sheet_hash,
            mirror_sheet_hash=inputs["cfg"].sheet["sheet_hash"],
            stale_sheet=inputs["stale_sheet"],
            pipeline_version=PIPELINE_VERSION),
        value_scale=t.root.value_scale,
        member2_target=inputs["member2_target"] or None,
        exit_depth=ExitDepth(lp_flight_literal=LP_FLIGHT_LITERAL),
        mechanism=Mechanism())


# ------------------------------------------------------------------ I/O -----


def emit(repo: pathlib.Path, bundle, tree,
         report: StressReport) -> tuple[pathlib.Path, bool]:
    """Run the stress checks, stamp, and route. The routing is the only write.

    Promotion needs THREE things: every check passing, a non-empty cell set,
    and a coherent sheet pairing. The cell clause is a named implementer
    default (P-6.01 R2): a report with no cells has computed nothing, and an
    empty artifact in `out/stress/` would read as a completed run.
    """
    from factory.validate.harness import run_stress_checks
    report = report.model_copy(update={
        "checks": run_stress_checks(bundle, tree, report)})
    ok = (all(r.result == "pass" for r in report.checks)
          and bool(report.cells)
          and not report.header.stale_sheet)
    report = finalise_stress(report)
    token, blk = report.header.token, report.header.run_block
    path = (repo / "out/stress" / token / f"{blk}.json" if ok
            else repo / "out/rehearsal" / token / f"stress-{blk}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialise_stress(report), encoding="utf-8", newline="")
    return path, ok


def main(repo: pathlib.Path, token: str,
         allow_stale_sheet: bool = False) -> tuple[pathlib.Path, bool, StressReport]:
    inputs = load_inputs(repo, token, allow_stale_sheet)
    report = fold(inputs)
    path, ok = emit(repo, inputs["bundle"], inputs["tree"], report)
    written = StressReport.model_validate_json(path.read_text(encoding="utf-8"))
    return path, ok, written


if __name__ == "__main__":
    _repo = pathlib.Path(__file__).resolve().parents[2]
    if len(sys.argv) < 2:
        print("usage: python -m factory.stress <TOKEN> [--allow-stale-sheet]"
              "  (crvUSD | GHO | LUSD)")
        sys.exit(2)
    _allow = "--allow-stale-sheet" in sys.argv[2:]
    try:
        _path, _ok, _r = main(_repo, sys.argv[1], _allow)
    except Exception as exc:                                  # a raised stop
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    print(f"token {_r.header.token} | run_block {_r.header.run_block} | "
          f"stress {_r.header.stress_hash[:8]} | cells {len(_r.cells)} | "
          f"checks {sum(x.result == 'pass' for x in _r.checks)}/{len(_r.checks)} | "
          f"stale_sheet {str(_r.header.stale_sheet).lower()} | "
          f"{'promoted' if _ok else 'REHEARSAL'} | {_path}")
    sys.exit(0 if _ok else 1)
