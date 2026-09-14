"""B-10 tests: the flat table replays (DET-84), the assumptions block's required
IDs, the manifest's hashes, and the gate record's completeness and A-16 list."""

from __future__ import annotations

import copy
import hashlib
import json
import pathlib

import pytest

from factory.report import assumptions, manifest, record
from factory.report.__main__ import build
from factory.report.paths import PathError, resolve
from factory.validate.harness import CHECKS, Level3, det_84, evaluate_harness

REPO = pathlib.Path(__file__).resolve().parents[1]
TOKENS = ("crvUSD", "GHO", "LUSD")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    import shutil
    root = tmp_path_factory.mktemp("repo")
    for sub in ("out/bundles", "out/trees", "out/stress", "out/raw", "out/logs", "config",
                "docs/context", "templates"):
        src = REPO / sub
        if src.exists():
            shutil.copytree(src, root / sub)
    for code in manifest.TEMPLATE_CODE:                     # B-11c: inside template_hash
        (root / code).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / code, root / code)
    return {t: build(root, t) for t in TOKENS}


def test_registry_carries_det84_at_the_report_stage():
    assert len(CHECKS) == 88                                   # B-11b +15, B-12 +6
    (c,) = [c for c in CHECKS if c.entry_id == "DET-84"]
    assert (c.stage, c.consumer) == ("S2", "report")


def test_every_row_replays_and_the_committed_table_matches(built):
    for t, r in built.items():
        doc = r["doc"]
        assert {"DET-17", "DET-18", "DET-15", "DET-16", "DET-19", "DET-30", "DET-31",
                "DET-68", "DET-73", "DET-32"} <= {row["owner_entry"] for row in doc["rows"]}, t
        committed = json.loads((REPO / f"out/report/{t}/{doc['run_block']}/table.json")
                               .read_text(encoding="utf-8"))
        assert committed["table_hash"] == doc["table_hash"], t
    gho = {row["field_id"]: row for row in built["GHO"]["doc"]["rows"]}
    assert gho["supply.off_mainnet.share"]["denominator"] == "supply_ruled"
    assert gho["exit.offvenue.x"]["value"].startswith("0.9243")     # B-11d run, live fetch


def _det84(token, doc):
    from factory.schema import StressReport
    from factory.stress import load_inputs
    inp = load_inputs(REPO, token)
    blk = inp["bundle"].header.run_block
    s = StressReport.model_validate_json((REPO / f"out/stress/{token}/{blk}.json")
                                         .read_text(encoding="utf-8"))
    mirror = json.loads(json.dumps(inp["cfg"].sheet, default=str))
    from factory.report.table import build_grid
    from factory.schema import serialise_stress
    grid = build_grid(json.loads(serialise_stress(s)))
    return det_84(inp["bundle"], inp["tree"], s, {"table": doc, "grid": grid, "mirror": mirror})


def test_det84_fails_an_edited_row_and_a_stale_hash(built):
    doc = built["LUSD"]["doc"]
    assert "rows replay" in _det84("LUSD", doc)
    bad = copy.deepcopy(doc)
    row = next(r for r in bad["rows"] if r["field_id"] == "supply.supply_ruled")
    row["value"] = row["value"] + 10 ** 18
    with pytest.raises(Level3, match="do not replay"):
        _det84("LUSD", bad)
    stale = copy.deepcopy(doc)
    stale["table_hash"] = "0" * 64
    with pytest.raises(Level3, match="table_hash"):
        _det84("LUSD", stale)
    orphan = copy.deepcopy(doc)
    orphan["rows"][0]["owner_entry"] = ""
    with pytest.raises(Level3, match="no owner"):
        _det84("LUSD", orphan)


def test_resolver_selectors():
    src = {"stress": {"cells": [{"id": "a", "m": {"x": 1}}, {"id": "b", "m": {"x": 2}}]}}
    assert resolve(src, "stress/cells/[id=b]/m/x") == 2
    with pytest.raises(PathError):
        resolve(src, "stress/cells/[id=c]/m/x")


def test_assumptions_required_ids_per_token(built):
    want_all = set(assumptions.REQUIRED_ALL)
    for t, r in built.items():
        got = {a["id"] for a in r["doc"]["assumptions"] if a["required"]}
        extra = ({"h5_slippage_bound", "gsm_fee_exit"} if t == "GHO" else set()) | \
                ({"lst_discount_grid"} if t != "LUSD" else set())
        assert got == want_all | extra, t
        assert all(a["data_ref"] or a["rule_ref"] for a in r["doc"]["assumptions"])


def test_manifest_hashes(tmp_path, built):
    m = built["crvUSD"]["manifest"]
    joined = "".join(m[k] for k in manifest.ORDER)
    assert m["report_hash"] == hashlib.sha256(joined.encode()).hexdigest()
    (tmp_path / "templates").mkdir()
    (tmp_path / "src/factory/report").mkdir(parents=True)
    for code in manifest.TEMPLATE_CODE:                     # B-11c: the renderer is in scope
        (tmp_path / code).write_bytes(b"pass\n")
    (tmp_path / "templates/a.txt").write_bytes(b"x\r\ny\n")
    h1 = manifest.template_hash(tmp_path)
    (tmp_path / "templates/a.txt").write_bytes(b"x\ny\n")
    assert manifest.template_hash(tmp_path) == h1           # LF-normalised
    (tmp_path / "templates/b.txt").write_bytes(b"")
    h2 = manifest.template_hash(tmp_path)
    assert h2 != h1                                         # a new file moves it
    (tmp_path / "src/factory/report/render.py").write_bytes(b"pass  # changed\n")
    assert manifest.template_hash(tmp_path) != h2           # so does a renderer edit
    assert [p.relative_to(REPO).as_posix() for p in manifest.template_files(REPO)
            if p.suffix == ".py"] == list(manifest.TEMPLATE_CODE)


def test_record_is_complete_and_enumerates_the_unregistered(built):
    rubric = (REPO / "docs/context/rubic_v1.md").read_bytes().replace(b"\r\n", b"\n").decode()
    un = record.unregistered(rubric)
    ids = [u["entry_id"] for u in un]
    assert len(ids) == len(set(ids)) == 14                     # B-12: 20 - 6
    assert {"DET-81", "DET-76abcd", "LLM-06", "DET-80"} <= set(ids)
    assert not {"DET-12-S3", "DET-13", "DET-58", "DET-59", "DET-60", "DET-87"} & set(ids)
    assert not {"DET-29c", "DET-14cd", "DET-22-S3", "DET-79"} & set(ids)
    assert not {c.entry_id for c in CHECKS} & set(ids)
    for r in built.values():
        rec = r["record"]
        assert {x.entry_id for x in rec.results} == {c.entry_id for c in CHECKS}
        assert rec.revision_count == 0 and rec.revision_cause == [] and rec.judge == []
    assert [x["trigger"] for x in built["GHO"]["record"].triggers][:2] == ["T-20", "T-02"]
    assert {x["trigger"] for x in built["GHO"]["record"].triggers[2:]} == {"T-28"}   # A-17


def test_evaluate_harness_never_raises():
    import tests.test_schema as ts
    b = ts.a_bundle()
    b = b.model_copy(update={"nodes": [b.nodes[0].model_copy(update={"disclosure_cadence": None})]})
    out = evaluate_harness(b, {})
    by = {g.entry_id: g.result for g in out.results}
    assert by["DET-76e"] == "fail" and len(out.results) == len(
        [c for c in CHECKS if c.stage in ("S0", "S1")])
