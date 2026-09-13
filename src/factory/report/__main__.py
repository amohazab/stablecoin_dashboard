"""`uv run python -m factory.report <TOKEN>` - B-10's report stage, no RPC.

Folds the promoted bundle, its tree and its stress report into the flat table
and assumptions block, runs the report-stage rows (DET-84), computes
`template_hash` and `report_hash`, and writes:

  out/report/<TOKEN>/<run_block>/table.json      (committed)
  out/report/<TOKEN>/<run_block>/manifest.json   (committed)
  out/evaluation/<TOKEN>/<run_block>.json        (committed, R13)

NAMED DEFAULT (B-10): the manifest sits beside its table under `out/report/`
(inventory §I's layout), not under `out/site/` (Step 9's page output) nor
`out/reports/` (gitignored working reports). A failing report-stage row routes
table and manifest to `out/rehearsal/<TOKEN>/report-<run_block>/`; the record is
written either way - it is the evidence of the failure.
"""

from __future__ import annotations

import json
import pathlib
import sys

from factory.config import load
from factory.report import assumptions, manifest, record, table
from factory.run import AssemblyStop, harness_ctx
from factory.schema import serialise, serialise_stress, serialise_tree
from factory.stress import load_inputs
from factory.tree import latest_tree
from factory.validate.harness import evaluate_harness, run_report_checks


def _json(obj) -> str:
    return json.dumps(obj, sort_keys=True, indent=1, ensure_ascii=False, default=str) + "\n"


def build(repo: pathlib.Path, token: str) -> dict:
    inputs = load_inputs(repo, token)
    b, t, cfg = inputs["bundle"], inputs["tree"], inputs["cfg"]
    d = repo / "out/stress" / token
    files = sorted((p for p in d.glob("*.json") if p.stem.isdigit()), key=lambda p: int(p.stem))
    from factory.schema import StressReport
    s = StressReport.model_validate_json(files[-1].read_text(encoding="utf-8"))
    if (s.header.source_bundle_hash, s.header.source_tree_hash) != (b.header.bundle_hash,
                                                                    t.tree_hash):
        raise AssemblyStop(f"{token}: the latest stress report is not folded from the latest "
                           "bundle and tree - re-fold before the report stage")
    assert latest_tree(repo, token).tree_hash == t.tree_hash
    bundle_j = {**json.loads(serialise(b))}
    bundle_j["header"] = {**bundle_j["header"], "bundle_hash": b.header.bundle_hash}
    tree_j, stress_j = json.loads(serialise_tree(t)), json.loads(serialise_stress(s))
    mirror_j = json.loads(json.dumps(cfg.sheet, default=str))
    rows = table.build_rows(bundle_j, tree_j, stress_j, mirror_j)
    doc = {"token": token, "run_block": b.header.run_block, "rows": rows,
           "assumptions": assumptions.build(token, rows)}
    doc["table_hash"] = table.table_hash(doc)
    report_checks = run_report_checks(b, t, s, {"table": doc, "mirror": mirror_j})
    parts = {"bundle_hash": b.header.bundle_hash, "tree_hash": t.tree_hash,
             "stress_hash": s.header.stress_hash, "table_hash": doc["table_hash"],
             "template_hash": manifest.template_hash(repo / "templates"),
             "pipeline_version": b.header.pipeline_version, "sheet_hash": b.header.sheet_hash}
    man = manifest.build(token, b.header.run_block, parts)
    s01 = evaluate_harness(b, harness_ctx(repo, load(repo / "config", token), b, token))
    rubric = (repo / "docs/context/rubic_v1.md").read_bytes().replace(b"\r\n", b"\n").decode()
    rec = record.build(parts, man, s01, t.checks, s.checks, report_checks, rubric)
    ok = all(g.result == "pass" for g in report_checks)
    blk = b.header.run_block
    out = (repo / "out/report" / token / str(blk) if ok
           else repo / "out/rehearsal" / token / f"report-{blk}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "table.json").write_text(_json(doc), encoding="utf-8", newline="")
    (out / "manifest.json").write_text(_json(man), encoding="utf-8", newline="")
    ev = repo / "out/evaluation" / token
    ev.mkdir(parents=True, exist_ok=True)
    (ev / f"{blk}.json").write_text(_json(rec.model_dump(mode="json")), encoding="utf-8",
                                    newline="")
    return {"ok": ok, "doc": doc, "manifest": man, "record": rec, "out": out}


if __name__ == "__main__":
    _repo = pathlib.Path(__file__).resolve().parents[3]
    if len(sys.argv) < 2:
        print("usage: python -m factory.report <TOKEN>  (crvUSD | GHO | LUSD)")
        sys.exit(2)
    try:
        r = build(_repo, sys.argv[1])
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    rec = r["record"]
    fails = [x.entry_id for x in rec.results if x.result != "pass"]
    print(f"token {rec.token} | run_block {rec.run_block} | rows {len(r['doc']['rows'])} | "
          f"table {rec.table_hash[:8]} | template {rec.template_hash[:8]} | "
          f"report {rec.report_hash[:8]} | results {len(rec.results) - len(fails)}/"
          f"{len(rec.results)} | unregistered {len(rec.unregistered)} | "
          f"{'promoted' if r['ok'] else 'rehearsal'} | {r['out']}")
    if fails:
        print("not pass:", fails)
    print("triggers:", [(x["trigger"], x["level"], x["source_entry"]) for x in rec.triggers])
