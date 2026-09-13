"""Step 5 tests: the verifiability tree folded from promoted bundles (P-5.01 R3,
R6, R11). Thin by ruling: one fold per token, one replay per DET-14/19/70, one
rehearsal-routing test."""

from __future__ import annotations

import pathlib
from decimal import Decimal

import pytest

from factory.config import load
from factory.schema import Bundle, VerifiabilityTree
from factory.tree import emit, fold
from factory.validate.harness import Level3, det_14, det_19, det_70

REPO = pathlib.Path(__file__).resolve().parents[1]
TOL = Decimal("1e-6")


def _bundle(token: str, block: int) -> Bundle:
    return Bundle.model_validate_json(
        (REPO / f"out/bundles/{token}/{block}.json").read_text(encoding="utf-8"))


def _tree(token: str, block: int):
    b = _bundle(token, block)
    return b, fold(b, load(REPO / "config", token))


@pytest.mark.parametrize("token,block,shares,truncated,backing,scale", [
    ("crvUSD", 25956063, ("0.036672", "0.565070", "0.398259", "0"), "0",
     151_790_063, 1),
    ("GHO", 25946240, ("0.305230", "0.407306", "0.287464", "0"), "0.079152",
     49_830_858_491_193_839, 10**8),
    ("LUSD", 25955393, ("1", "0", "0", "0"), "0",
     186_586_616_348_573_144_396_590_655, 10**18),
])
def test_fold_reproduces_the_bundle_split(token, block, shares, truncated, backing, scale):
    """The three bars, the truncated share and U against the figures the trees
    read (crvUSD at run 5, not Inventory A's 25934920)."""
    _, t = _tree(token, block)
    got = [b.share for b in t.bars] + [t.shares.unlisted]
    for g, want in zip(got, shares, strict=True):
        assert abs(g - Decimal(want)) <= TOL
    assert abs(t.truncated_share - Decimal(truncated)) <= TOL
    assert t.root.backing_value == backing and t.root.value_scale == scale
    assert t.unclassified_literal is None                       # U = 0 on all three


def test_det14_backing_value_must_be_the_sum_of_node_values():
    b, t = _tree("crvUSD", 25956063)
    det_14(b, t)
    with pytest.raises(Level3, match="DET-14"):
        det_14(b, t.model_copy(update={"root": t.root.model_copy(
            update={"backing_value": t.root.backing_value + 1})}))


def test_det19_a_bar_over_supply_or_off_its_replay_fails():
    b, t = _tree("GHO", 25946240)
    det_19(b, t)
    moved = [x.model_copy(update={"share": x.share + Decimal("0.01")}) if i == 0 else x
             for i, x in enumerate(t.bars)]
    with pytest.raises(Level3, match="DET-19"):
        det_19(b, t.model_copy(update={"bars": moved}))
    with pytest.raises(Level3, match="supply_ruled"):
        det_19(b, t.model_copy(update={"denominators": {**t.denominators,
                                                         "root.residual": "supply_ruled"}}))


def test_det70_qualifier_replays_and_a_null_bucket_fails():
    """Run 5 passes; the pre-C0 bundle at 25934920 carries null buckets on its
    qualifying rows - the reason C0 ran first (P-5.01 R12)."""
    b, t = _tree("crvUSD", 25956063)
    det_70(b, t)
    assert t.banner == ("Verifiability conditional on: mint — dao_governance + 1–7d; "
                        "set_oracle — dao_governance + 1–7d")
    with pytest.raises(Level3, match="banner"):
        det_70(b, t.model_copy(update={"banner": "No admin power can alter backing — immutable."}))
    old_b, old_t = _tree("crvUSD", 25934920)
    with pytest.raises(Level3, match="no delay_bucket"):
        det_70(old_b, old_t)


def test_a_tree_with_a_failing_check_goes_to_rehearsal(tmp_path):
    # B-9: the tree-consumer rows now include DET-05/15/32, which a pre-B-9
    # bundle cannot pass; crvUSD's B-9 run (25970226) passes all fourteen.
    b, t = _tree("crvUSD", 25970226)
    path, ok = emit(tmp_path, b, t)
    assert ok and path == tmp_path / "out/trees/crvUSD/25970226.json"
    broken = t.model_copy(update={"root": t.root.model_copy(update={"backing_value": 1})})
    path, ok = emit(tmp_path, b, broken)
    assert not ok and path == tmp_path / "out/rehearsal/crvUSD/tree-25970226.json"
    written = VerifiabilityTree.model_validate_json(path.read_text(encoding="utf-8"))
    assert {r.entry_id: r.result for r in written.checks}["DET-14"] == "fail"
