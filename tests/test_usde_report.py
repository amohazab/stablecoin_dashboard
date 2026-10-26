"""P-10.10: archetype #2's report rows (DET-84 replay), A-36's assumption IDs, A-31's
declared slots and A-33's methodology count line."""

import json
import pathlib
import tomllib

from factory.config import load
from factory.report import assumptions, llm, synthetic_table
from factory.run import harness_ctx
from factory.schema import serialise, serialise_stress, serialise_tree
from factory.site import counts_line
from factory.stress import load_inputs
from factory.validate.harness import det61_figures, det90_figures, det_84

REPO = pathlib.Path(__file__).resolve().parents[1]


def _doc():
    inp = load_inputs(REPO, "USDe")
    b, t, cfg = inp["bundle"], inp["tree"], inp["cfg"]
    from factory.schema import StressReport
    d = REPO / "out/stress/USDe"
    s = StressReport.model_validate_json(
        max(d.glob("*.json"), key=lambda p: int(p.stem)).read_text(encoding="utf-8"))
    bj = json.loads(serialise(b))
    bj["header"]["bundle_hash"] = b.header.bundle_hash
    w = tomllib.loads((REPO / "templates/wording.toml").read_text(encoding="utf-8"))
    gate = json.loads(json.dumps(
        {"DET-90": det90_figures(b, harness_ctx(REPO, cfg, b, "USDe")),
         "DET-61": det61_figures(b)}, default=str))
    rows = synthetic_table.build_rows(bj, json.loads(serialise_tree(t)),
                                      json.loads(serialise_stress(s)),
                                      json.loads(json.dumps(cfg.sheet, default=str)), w, gate)
    return b, t, s, cfg, w, rows


def test_synthetic_rows_replay_through_det84():
    from factory.report.table import build_grid, table_hash
    b, t, s, cfg, w, rows = _doc()
    doc = {"token": "USDe", "run_block": b.header.run_block, "rows": rows,
           "assumptions": assumptions.build("USDe", rows)}
    grid = build_grid(json.loads(serialise_stress(s)))
    doc["table_hash"] = table_hash(doc, grid)
    page = {"table": doc, "grid": grid, "mirror": json.loads(json.dumps(cfg.sheet, default=str)),
            "wording": w, "label_rows": cfg.label_rows}
    assert "rows replay" in det_84(b, t, s, page)
    ids = {r["field_id"] for r in rows}
    assert {"cell.S1-n90.post_loss_ratio", "cell.S3.K90.ratio", "recon.gap",
            "redemption.r2_words", "tree.root.status_backing"} <= ids


def test_a36_ids_and_a31_declared_slots():
    *_, rows = _doc()
    got = [a["id"] for a in assumptions.build("USDe", rows) if a["required"]]
    assert got == list(assumptions.REQUIRED_SYNTHETIC)
    mf = tomllib.loads((REPO / "templates/manifest.toml").read_text(encoding="utf-8"))
    assert llm.declared_slots(mf, "synthetic") == [                        # A-53 (P-10.12)
        "structural_summary", "stress_opening", "flag_explanations"]
    assert len(llm.declared_slots(mf, "cdp")) == 7
    assert set(llm.prompts(REPO, "synthetic")["slots"]) == set(llm.declared_slots(mf, "synthetic"))
    assert load(REPO / "config", "USDe").token == "USDe"


def test_counts_line_form():
    rec = {"results": [{"entry_id": "DET-90", "result": "pass"},
                       {"entry_id": "DET-02", "result": "pass"},
                       {"entry_id": "LLM-01", "result": "not_evaluated"}],
           "not_applicable": [{"entry_id": "DET-03"}, {"entry_id": "DET-07"}]}
    assert counts_line("USDe", rec) == "2 evaluated, 2 not applicable (archetype #2), 1 new"
    assert counts_line("LUSD", {"results": rec["results"][1:]}) == "1 evaluated"
