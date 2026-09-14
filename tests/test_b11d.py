"""B-11c′ / B-11d tests: the §14 tag dates in the mirror, the tree-side stabilizer
slice and DET-22's replay of it, the table rows the page now prints, and the
token's decimals read declared on the bundle."""

from __future__ import annotations

import json
import pathlib

import pytest

from factory import mirror
from factory.config import load
from factory.report.table import build_rows
from factory.schema import Bundle, serialise, serialise_stress, serialise_tree
from factory.tree import fold
from factory.validate.harness import Level3, det_22

REPO = pathlib.Path(__file__).resolve().parents[1]
SHEET = REPO / "docs/context/intake-sheets-cdp.md"
BLOCKS = {"crvUSD": 25974925, "GHO": 25974932, "LUSD": 25974949}


def _bundle(token: str) -> Bundle:
    return Bundle.model_validate_json(
        (REPO / f"out/bundles/{token}/{BLOCKS[token]}.json").read_text(encoding="utf-8"))


def test_audit_tag_dates_parse_and_the_mirrors_carry_them():
    assert mirror.parse_audit_tag_dates(SHEET, "crvUSD") == {
        "audits": "2026-09-13", "bug_bounty": "2026-09-13",
        "last_material_change_audited": "2026-09-13"}
    assert set(mirror.parse_audit_tag_dates(SHEET, "LUSD")) == {"audits", "bug_bounty"}
    for tok in BLOCKS:
        committed = (REPO / f"config/{tok.lower()}_sheet.toml").read_bytes().replace(
            b"\r\n", b"\n").decode("utf-8")
        assert committed.rstrip("\n") == mirror.generate(SHEET, tok).rstrip("\n"), tok
        assert load(REPO / "config", tok).sheet["audit_tag_date"]["bug_bounty"] == "2026-09-13"


@pytest.mark.parametrize("token", ["crvUSD", "LUSD"])
def test_stabilizer_slice_folds_and_det22_replays_it(token):
    b = _bundle(token)
    t = fold(b, load(REPO / "config", token))
    ops = b.stabilizer.operations
    sl = t.stabilizer_slice
    assert (sl.debt, sl.ceiling_aggregate, sl.operation_count) == (
        sum(o.current_debt for o in ops), b.stabilizer.ceiling_aggregate, len(ops))
    assert t.denominators["stabilizer_slice.ceiling_aggregate"] == "amount"
    det_22(b, t)
    bad = t.model_copy(update={"stabilizer_slice": sl.model_copy(update={"debt": sl.debt + 1})})
    with pytest.raises(Level3, match="stabilizer slice"):
        det_22(b, bad)


def test_table_carries_the_slice_operations_price_impact_and_tag_dates():
    from factory.schema import StressReport
    token = "crvUSD"
    b = _bundle(token)
    cfg = load(REPO / "config", token)
    t = fold(b, cfg)
    s = StressReport.model_validate_json(
        (REPO / f"out/stress/{token}/{BLOCKS[token]}.json").read_text(encoding="utf-8"))
    bj = json.loads(serialise(b))
    bj["header"]["bundle_hash"] = b.header.bundle_hash
    rows = {r["field_id"]: r for r in build_rows(bj, json.loads(serialise_tree(t)),
                                                 json.loads(serialise_stress(s)),
                                                 json.loads(json.dumps(cfg.sheet, default=str)))}
    assert rows["stabilizer.slice.debt"]["value"] == t.stabilizer_slice.debt
    ops = [f for f in rows if f.startswith("stabilizer.op.") and f.endswith(".debt_ceiling")]
    assert len(ops) == len(b.stabilizer.operations) == 5
    assert rows["exit.curve.s0.005.s"]["denominator"] == "price_impact"
    assert rows["audit.tag_date.bug_bounty"]["value"] == "2026-09-13"


def test_decimals_read_is_declared_on_each_adapter():
    src = {p: (REPO / p).read_text(encoding="utf-8") for p in
           ("src/factory/run.py", "src/factory/adapters/gho.py", "src/factory/adapters/lusd.py")}
    for path, text in src.items():
        assert '"decimals": ' in text and '"decimals()"' in text, path
        assert "!= 18" in text, path


def test_m2_note_parses_from_the_sheet_row_it_annotates():
    notes = mirror.parse_node_notes(SHEET, "GHO")
    assert notes == [{"row_key": "aDAI / aUSDS / asDAI → DAI/USDS",
                      "applies_to": ["DAI", "USDS", "sDAI"], "date": "2026-09-01",
                      "note": "Sky reserves ≈ USDC-via-LitePSM + RWA; note only, not analyzed"}]
    assert mirror.parse_node_notes(SHEET, "crvUSD") == mirror.parse_node_notes(SHEET, "LUSD") == []
    assert load(REPO / "config", "GHO").sheet["node_note"][0]["date"] == "2026-09-01"


def test_ceiling_share_is_det19s_second_carve_out():
    from decimal import Decimal

    from factory.validate.harness import det_19
    b = _bundle("crvUSD")
    t = fold(b, load(REPO / "config", "crvUSD"))
    sl = t.stabilizer_slice
    assert sl.ceiling_share_of_supply_ruled == (Decimal(b.stabilizer.ceiling_aggregate)
                                                / Decimal(b.supply.supply_ruled))
    assert t.denominators["stabilizer_slice.ceiling_share_of_supply_ruled"] == "supply_ruled"
    det_19(b, t)
    off = t.model_copy(update={"stabilizer_slice": sl.model_copy(
        update={"ceiling_share_of_supply_ruled": sl.ceiling_share_of_supply_ruled * 2})})
    with pytest.raises(Level3, match="ceiling share does not replay"):
        det_19(b, off)
    stray = t.model_copy(update={"denominators": {**t.denominators,
                                                  "root.residual": "supply_ruled"}})
    with pytest.raises(Level3, match="R1 forbids"):
        det_19(b, stray)
