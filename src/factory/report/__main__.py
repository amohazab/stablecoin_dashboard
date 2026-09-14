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

B-11b, the report-stage gate. With DET-84 green the pages render into
`out/rehearsal/<TOKEN>/<run_block>/` (stylesheet beside it) and the fifteen S3
rows run over them. All pass: the directory is copied to `out/site/<TOKEN>/`
with `out/site/style.css`. Any S3 row not passing: the pages stay in rehearsal,
the record's outcome is "blocked_S3", and `out/site/<TOKEN>/` is withdrawn -
NAMED DEFAULT: a page left there by an earlier attempt would be a published page
this gate did not pass; `out/site/` itself goes when no token remains in it.
The page's pills read the S0-S2 triggers (an S3 trigger, DET-74's T-16, reaches
the record, not the rendered pill - named default until B-12).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import pathlib
import re
import shutil
import sys
import tomllib

from factory import eventlog
from factory.config import load
from factory.mirror import sheet_hash
from factory.report import assumptions, manifest, record, table
from factory.rubric import trigger_table
from factory.run import AssemblyStop, harness_ctx
from factory.schema import serialise, serialise_stress, serialise_tree
from factory.stress import load_inputs
from factory.tree import latest_tree
from factory.validate.harness import CHECKS, evaluate_harness, run_report_checks

JINJA_BLOCK = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.S)


def _json(obj) -> str:
    return json.dumps(obj, sort_keys=True, indent=1, ensure_ascii=False, default=str) + "\n"


def _lf(path: pathlib.Path) -> str:
    return path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")


def s3_page(repo: pathlib.Path, doc: dict, grid: dict, mirror: dict, files: dict) -> dict:
    """What the S3 rows read: the table and grid, the rendered pages, and the
    template-side inputs - read here, so the harness does no file I/O."""
    tpl = repo / "templates"
    wording = tomllib.loads((tpl / "wording.toml").read_text(encoding="utf-8"))
    strings: list[str] = []

    def collect(o):
        if isinstance(o, str):
            strings.append(o)
        elif isinstance(o, dict | list):
            for v in (o.values() if isinstance(o, dict) else o):
                collect(v)
    collect(wording)
    strings += [JINJA_BLOCK.sub(" ", _lf(p)) for p in sorted(tpl.glob("*.j2"))]
    sheet = repo / "docs/context/intake-sheets-cdp.md"
    return {"table": doc, "grid": grid, "mirror": mirror,
            "html": {k: v.read_text(encoding="utf-8") for k, v in files.items()},
            "wording": wording,
            "manifest": tomllib.loads((tpl / "manifest.toml").read_text(encoding="utf-8")),
            "template_strings": strings, "sheet_text": _lf(sheet),
            "sheet_hash": sheet_hash(sheet),
            "memo_text": _lf(repo / "docs/context/archetype-memo-1-cdp.md")}


GATE_INTEGRITY_OWNERS = ("DET-13", "DET-87", "DET-59")


def gate_triggers(results) -> list[dict]:
    """A-17 (B-12): every failed or erroring registered check fires T-28 "gate
    failure", Level 2, naming the check in the record. NAMED DEFAULT: the rows whose
    own trigger is T-23 "gate integrity" (DET-13, DET-87, DET-59 - §3's computing
    owners) fire T-23 instead. The log line is category-level (DET-60): one per
    (token, date, trigger, level); the check names live in the record."""
    return [{"trigger": "T-23" if g.entry_id in GATE_INTEGRITY_OWNERS else "T-28", "level": 2,
             "source_entry": g.entry_id} for g in results if g.result in ("fail", "error")]


def log_view(entries: list, token: str, ttable: dict, wording: dict) -> dict:
    """What the page renders from the log: open Level-1 flags by page place, and the
    banner when a Level 2/3 entry is open (DET-58, DET-59)."""
    flags: dict[str, list] = {}
    place = wording["flag_section"]
    heavy = []
    for eid, e in eventlog.open_entries(entries, token):
        row = ttable[e.trigger]
        if e.level == 1:
            flags.setdefault(place[row["section"]], []).append(
                {"id": eid, "name": row["name"], "date": e.date, "section": row["section"]})
        else:
            heavy.append(row["name"])
    banner = None
    if heavy:
        last = eventlog.last_published(entries, token)
        date = last.date if last else wording["banner"]["none"]
        runs = eventlog.consecutive_quarantined_runs(entries, token)
        banner = {"last": wording["banner"]["last"].format(date=date),
                  "current": wording["banner"]["current"].format(
                      category=", ".join(sorted(set(heavy)))),
                  "review": wording["banner"]["review"].format(date=date) if runs >= 4 else None}
    return {"flags": flags, "banner": banner}


def _stamp(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def run_hashes(repo: pathlib.Path, token: str, current: dict, date: str) -> dict:
    """DET-87's evidence, `{date: hash fields}`, from the token's gate records (run
    dates read from their bundles) and this run's own components."""
    fields = ("template_hash", "pipeline_version", "sheet_hash", "bundle_hash", "rubric_hash")
    out: dict[str, dict] = {}
    for rec_path in sorted((repo / "out/evaluation" / token).glob("*.json")):
        bpath = repo / "out/bundles" / token / rec_path.name
        if not bpath.exists():
            continue
        head = json.loads(bpath.read_text(encoding="utf-8"))["header"]
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        d = _dt.datetime.fromtimestamp(head["block_timestamp"], _dt.UTC).date().isoformat()
        out[d] = {**{k: rec.get(k) for k in fields}, "frozen_set_hash": head.get("frozen_set_hash")}
    out[date] = {**{k: current.get(k) for k in fields}, "frozen_set_hash": None}
    return out


def _site_report_hash(repo: pathlib.Path, token: str) -> str | None:
    p = repo / "out/site" / token / "data/manifest.json"
    return json.loads(p.read_text(encoding="utf-8")).get("report_hash") if p.exists() else None


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
    grid = table.build_grid(stress_j)
    doc["table_hash"] = table.table_hash(doc, grid)
    report_checks = run_report_checks(b, t, s, {"table": doc, "grid": grid, "mirror": mirror_j})
    parts = {"bundle_hash": b.header.bundle_hash, "tree_hash": t.tree_hash,
             "stress_hash": s.header.stress_hash, "table_hash": doc["table_hash"],
             "template_hash": manifest.template_hash(repo),
             "pipeline_version": b.header.pipeline_version, "sheet_hash": b.header.sheet_hash}
    man = manifest.build(token, b.header.run_block, parts)
    s01 = evaluate_harness(b, harness_ctx(repo, load(repo / "config", token), b, token))
    rubric = _lf(repo / "docs/context/rubic_v1.md")
    ttable = trigger_table(rubric)
    wording = tomllib.loads((repo / "templates/wording.toml").read_text(encoding="utf-8"))
    ok = all(g.result == "pass" for g in report_checks)
    blk = b.header.run_block
    stage = repo / "out/rehearsal" / token / str(blk)
    log_path = repo / "out/logs" / f"events_{token.lower()}.jsonl"
    entries = eventlog.read(log_path)
    date = _dt.datetime.fromtimestamp(b.header.block_timestamp, _dt.UTC).date().isoformat()
    prior = [*s01.results, *t.checks, *s.checks, *report_checks]
    stage_of = {c.entry_id: c.stage for c in CHECKS}
    prior_results = [{"entry_id": g.entry_id, "stage": stage_of[g.entry_id], "result": g.result,
                      "scope_condition": g.scope_condition} for g in prior]
    fired_checks = record.triggers_of(prior)
    s3: list = []
    planned: list = []
    gate: list = []
    if ok:
        from factory.report.render import render_token
        # B-12: the page carries the run's flags and banner, which depend on S3's own
        # failures (T-28). Render, check, re-plan from the failures and re-render until
        # the failing set is stable - two passes when it is, four at most.
        seen = None
        for _pass in range(4):
            gate = gate_triggers([*prior, *s3])
            rec_triggers = [*fired_checks, *record.triggers_of(s3), *gate]
            planned = eventlog.plan_quarantine(entries, token, date,
                                               [(x["trigger"], x["level"]) for x in rec_triggers])
            after = [*entries, *planned]
            if stage.exists():
                shutil.rmtree(stage)
            pre = {"triggers": rec_triggers, "log": log_view(after, token, ttable, wording)}
            pages = render_token(repo, token, doc, grid, man, pre, b, s, stage)
            page = s3_page(repo, doc, grid, mirror_j, pages)
            page.update(trigger_table=ttable, log_entries=after, log_date=date,
                        log_raw=[e.model_dump() for e in after], record_triggers=rec_triggers,
                        prior_results=prior_results, report_manifest=man,
                        run_hashes=run_hashes(repo, token, {**parts, "rubric_hash": _stamp(rubric)},
                                              date),
                        site_report_hash=_site_report_hash(repo, token))
            s3 = run_report_checks(b, t, s, page, stage="S3")
            failing = {(g.entry_id, g.result) for g in s3 if g.result != "pass"}
            if failing == seen:
                break
            seen = failing
        else:
            raise AssemblyStop(f"{token}: S3 failures did not stabilise across render passes")
    else:
        gate = gate_triggers(prior)
        planned = eventlog.plan_quarantine(entries, token, date,
                                           [(x["trigger"], x["level"])
                                            for x in [*fired_checks, *gate]])
    after = [*entries, *planned]
    heavy = [e for _, e in eventlog.open_entries(after, token) if e.level in (2, 3)]
    outcome = ("blocked_S3" if any(g.result != "pass" for g in s3) or not ok
               else "quarantined" if heavy else None)
    rec = record.build(parts, man, s01, t.checks, s.checks, [*report_checks, *s3], rubric,
                       gate_triggers=tuple(gate), outcome=outcome)
    out = (repo / "out/report" / token / str(blk) if ok
           else repo / "out/rehearsal" / token / f"report-{blk}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "table.json").write_text(_json(doc), encoding="utf-8", newline="")
    (out / "grid.json").write_text(_json(grid), encoding="utf-8", newline="")
    (out / "manifest.json").write_text(_json(man), encoding="utf-8", newline="")
    ev = repo / "out/evaluation" / token
    ev.mkdir(parents=True, exist_ok=True)
    (ev / f"{blk}.json").write_text(_json(rec.model_dump(mode="json")), encoding="utf-8",
                                    newline="")
    for line in planned:                         # the log is written last, once per run
        eventlog.append(log_path, line)
    site_root = repo / "out/site"
    site = None
    if ok:
        (stage / "data" / f"evaluation-{blk}.json").write_text(
            _json(rec.model_dump(mode="json")), encoding="utf-8", newline="")
        if (site_root / token).exists():
            shutil.rmtree(site_root / token)
        if rec.outcome is None:
            shutil.copytree(stage, site_root / token)
            shutil.copyfile(stage.parent / "style.css", site_root / "style.css")
            site = site_root / token
        elif site_root.exists() and not any(x.is_dir() for x in site_root.iterdir()):
            shutil.rmtree(site_root)
    return {"ok": ok, "doc": doc, "grid": grid, "manifest": man, "record": rec, "out": out,
            "site": site, "pages": stage if ok else None, "log_lines": planned}


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
    print(f"outcome {rec.outcome} | pages {r['pages']} | site {r['site']}")
    if fails:
        print("not pass:", fails)
        for x in rec.results:
            if x.result != "pass":
                print(f"  {x.entry_id} {x.result}: {x.scope_condition}")
    print("triggers:", [(x["trigger"], x["level"], x["source_entry"]) for x in rec.triggers])
