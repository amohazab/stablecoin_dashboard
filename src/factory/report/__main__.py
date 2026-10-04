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
with `out/site/style.css`. Any S3 row not passing: the pages stay in rehearsal
and the record's outcome is "blocked_S3". P-8.04 Q7 (superseding B-11b's
withdrawal default): `out/site/<TOKEN>/` is replaced only by a published run;
the last published pages stay otherwise, with the failed run's record and log
line as the evidence.
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


NOT_JUDGED = "not judged: deterministic S3 failure"         # sixth live run, ruling 5
LEVEL1_CHECKS = ("DET-80",)   # A-25 (P-8.10): a missing prose slot notices, never blocks
GATE_OWNERS = {"DET-13": "T-23", "DET-87": "T-23", "DET-59": "T-23", "DET-85": "T-25"}
EVIDENCE_ORDER = (("template_hash", "template_change"), ("sheet_hash", "intake_change"),
                  ("pipeline_version", "code_fix"), ("rubric_hash", "rubric_change"),
                  ("frozen_set_hash", "config_change"), ("bundle_hash", "data_correction"))


def gate_triggers(results, instability: bool = False) -> list[dict]:
    """A-17 (B-12): every failed or erroring registered check fires T-28 "gate
    failure", Level 2, naming the check in the record. NAMED DEFAULTS: §3's computing
    owners keep their own trigger - DET-13, DET-87, DET-59 fire T-23 "gate integrity",
    DET-85 fires T-25 "harness error" - and on a judge-instability outcome (R-48b) the
    LLM rows fire T-24. The log line is category-level (DET-60): one per (token, date,
    trigger, level); the check names live in the record."""
    out = []
    for g in results:
        if g.result not in ("fail", "error"):
            continue
        trig = ("T-24" if instability and g.entry_id.startswith("LLM-")
                else GATE_OWNERS.get(g.entry_id, "T-28"))
        # A-25: a failed DET-80 (a slot shown as the notice) is T-28 at Level 1
        level = 1 if g.entry_id in LEVEL1_CHECKS and g.result == "fail" else 2
        out.append({"trigger": trig, "level": level, "source_entry": g.entry_id})
    return out


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


HASH_FIELDS = ("template_hash", "pipeline_version", "sheet_hash", "bundle_hash", "rubric_hash")


def run_hashes(repo: pathlib.Path, token: str) -> dict[int, dict]:
    """DET-87's run evidence keyed by RUN BLOCK (Amin, 2026-09-14): `{run_block: {hash
    fields, date}}` from the token's gate records ON DISK - read before this run
    rewrites its own - with each record's date from its bundle's block timestamp."""
    out: dict[int, dict] = {}
    for rec_path in sorted((repo / "out/evaluation" / token).glob("*.json")):
        bpath = repo / "out/bundles" / token / rec_path.name
        if not rec_path.stem.isdigit() or not bpath.exists():
            continue
        head = json.loads(bpath.read_text(encoding="utf-8"))["header"]
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        out[int(rec_path.stem)] = {
            **{k: rec.get(k) for k in HASH_FIELDS}, "frozen_set_hash": head.get("frozen_set_hash"),
            "date": _dt.datetime.fromtimestamp(head["block_timestamp"], _dt.UTC).date().isoformat()}
    return out


def _fire_run(hashes: dict[int, dict], fire_date: str) -> int | None:
    """The log's fire date resolved to its run through the gate records (named default:
    the latest record of that date on disk - before this run rewrites its own)."""
    runs = sorted(blk for blk, h in hashes.items() if h["date"] == fire_date)
    return runs[-1] if runs else None


def plan_resolutions(entries: list, token: str, date: str, hashes: dict[int, dict],
                     current: dict) -> list:
    """A green run resolves its open Level 2/3 entries (B-13; the open T-28 lines) with
    the first evidence field that differs between the fire run and this run, in
    `EVIDENCE_ORDER`; no difference, no resolution (DET-87)."""
    lines = []
    for _eid, e in eventlog.open_entries(entries, token):
        fire_blk = _fire_run(hashes, e.date) if e.level in (2, 3) else None
        if fire_blk is None:
            continue
        fire = hashes[fire_blk]
        for field, rtype in EVIDENCE_ORDER:
            if fire.get(field) and current.get(field) and fire[field] != current[field]:
                lines.append(eventlog.QuarantineEvent(date=e.date, token=token, trigger=e.trigger,
                                                      level=e.level, resolution_type=rtype,
                                                      resolution_date=date))
                break
    return lines


def evidence_of(line, hashes: dict[int, dict], current: dict, blk: int) -> dict | None:
    """DET-87's evidence for one resolution line: its type's field at the fire run and
    at this run, kept in `out/evaluation/<T>/resolutions.jsonl` beside the records."""
    field = dict((r, f) for f, r in EVIDENCE_ORDER)[line.resolution_type]
    fire_blk = _fire_run(hashes, line.date)
    if fire_blk is None:
        return None
    return {"date": line.date, "trigger": line.trigger, "level": line.level,
            "resolution_type": line.resolution_type, "resolution_date": line.resolution_date,
            "field": field, "fire_value": hashes[fire_blk].get(field),
            "resolution_value": current.get(field), "fire_block": fire_blk,
            "resolution_block": blk}


def read_evidence(repo: pathlib.Path, token: str) -> list[dict]:
    p = repo / "out/evaluation" / token / "resolutions.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] \
        if p.exists() else []


def _site_report_hash(repo: pathlib.Path, token: str) -> str | None:
    p = repo / "out/site" / token / "data/manifest.json"
    return json.loads(p.read_text(encoding="utf-8")).get("report_hash") if p.exists() else None


def row_displays(repo: pathlib.Path, doc: dict) -> dict[str, list[str]]:
    """Each row's printed forms (full and compact) - the only forms prose may cite."""
    from factory.report.render import Formatter
    mf = tomllib.loads((repo / "templates/manifest.toml").read_text(encoding="utf-8"))
    rows = {r["field_id"]: r for r in doc["rows"]}
    fmt = Formatter(mf["display_rule"], mf["compact"],
                    int(rows["tree.root.value_scale"]["value"]))
    return {f: sorted({fmt(r["value"], r["unit"], r["denominator"]),
                       fmt(r["value"], r["unit"], r["denominator"], compact=True)})
            for f, r in rows.items()}


class ReplayClient:
    """`--from-record` (P-8.10): the model identity of the replayed record; no call is ever
    made through it."""

    def __init__(self, rec: dict):
        head = rec.get("llm") or {}
        self.version, self.digest = head.get("version"), head.get("digest")

    def chat(self, body: dict) -> dict:
        raise RuntimeError("--from-record makes no model call")


def replayed_prose(rec: dict) -> dict[str, str]:
    """The guard-passed slot texts of a record (its highest pass per slot)."""
    best: dict[str, dict] = {}
    for g in rec.get("generation", []):
        if g.get("slot") and g.get("text") and not g.get("error"):
            if g["slot"] not in best or g["pass"] >= best[g["slot"]]["pass"]:
                best[g["slot"]] = g
    return {s: g["text"] for s, g in best.items()}


def build(repo: pathlib.Path, token: str, client=None, extra_fired: tuple = (),
          preview: bool = False, judge_withdrawn: str | None = "default",
          replay: dict | None = None) -> dict:
    """`client` = None is a REHEARSAL (Amin, 2026-09-14): no generation, no judgment, the
    slots stay placeholders; pages stay in `out/rehearsal/`, the record's outcome is
    "rehearsal" and it is written beside them, not to `out/evaluation/`; nothing is
    appended to the log, no resolution evidence is kept, `out/site/` is not touched, and
    the LLM rows' and DET-85's by-construction errors fire no trigger. `extra_fired`
    injects `(trigger, level)` pairs into this run's fired set - a test hook (K8).
    `preview` (Amin, seventh live run): pass-1 generation with the guard only - returns the
    generation records before any render, judge, remediation, log line or file write."""
    from factory.report import llm
    # A-24 (P-8.05): with a client, the judge is withdrawn unless a caller passes None - the
    # loop's tests do, on the Claude-era fixtures; the loop code stays and stays tested
    withdrawn = llm.JUDGE_WITHDRAWN if judge_withdrawn == "default" else judge_withdrawn
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
    template_j = tomllib.loads((repo / "templates/wording.toml").read_text(encoding="utf-8"))
    rows = table.build_rows(bundle_j, tree_j, stress_j, mirror_j, template_j)
    doc = {"token": token, "run_block": b.header.run_block, "rows": rows,
           "assumptions": assumptions.build(token, rows)}
    grid = table.build_grid(stress_j)
    doc["table_hash"] = table.table_hash(doc, grid)
    report_checks = run_report_checks(b, t, s, {"table": doc, "grid": grid, "mirror": mirror_j,
                                                "wording": template_j})
    parts = {"bundle_hash": b.header.bundle_hash, "tree_hash": t.tree_hash,
             "stress_hash": s.header.stress_hash, "table_hash": doc["table_hash"],
             "template_hash": manifest.template_hash(repo),
             "pipeline_version": b.header.pipeline_version, "sheet_hash": b.header.sheet_hash}
    man = manifest.build(token, b.header.run_block, parts)
    s01 = evaluate_harness(b, harness_ctx(repo, load(repo / "config", token), b, token))
    rubric = _lf(repo / "docs/context/rubic_v1.md")
    ttable = trigger_table(rubric)
    wording = tomllib.loads((repo / "templates/wording.toml").read_text(encoding="utf-8"))
    mf = tomllib.loads((repo / "templates/manifest.toml").read_text(encoding="utf-8"))
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
    fired_checks = [*record.triggers_of(prior),
                    *({"trigger": tr, "level": lv, "source_entry": "test"}
                      for tr, lv in extra_fired)]
    hashes = run_hashes(repo, token)
    current = {**parts, "rubric_hash": _stamp(rubric), "frozen_set_hash": b.header.frozen_set_hash}
    persisted_evidence = read_evidence(repo, token)
    llm_rec: dict = {"judge": [], "generation": [], "revision_count": 0, "revision_cause": []}
    if client is not None:
        llm_rec["llm"] = llm.llm_header(client)          # P-8.04 Q6
    s3: list = []
    planned: list = []
    evidence: list = []
    gate: list = []
    llm_outcome = None

    rehearsal = client is None

    def gates(results, instability: bool) -> list[dict]:
        found = gate_triggers(results, instability)
        return [x for x in found if not (rehearsal and (x["source_entry"].startswith("LLM-")
                                                        or x["source_entry"] == "DET-85"))]

    last_prose: list = [{}]

    def slots_missing(prose: dict) -> list[str]:
        """A-25: the prose slots a model run left empty (shown as the notice); a rehearsal
        (no client) keeps its placeholders and reports none."""
        last_prose[0] = prose
        if client is None:
            return []
        return [x["id"] for x in mf["prose_slots"] if not (prose.get(x["id"]) or "").strip()]

    def evaluate(prose: dict, judge_state: dict, instability: bool, pass_no: int):
        """Render and run S3 until the failing set is stable (the B-12 loop), then - with a
        client, once per pass - judge the first-rendered page only when every deterministic
        S3 row passed (Amin, sixth live run, ruling 5), and settle S3 again with the LLM rows
        reading this pass's stored envelope. NAMED DEFAULT: the deterministic rows are every
        S3 row except LLM-01...06 and the two tail rows over the record, DET-85 and DET-13."""
        if client is None or "sections" in judge_state:
            return settle(prose, judge_state, instability)
        if withdrawn:                        # A-24: generate -> guard -> deterministic S3
            judge_state.update(withdrawn=withdrawn, sections={})
            llm_rec["judge"].append({"pass": pass_no, "not_evaluated": withdrawn})
            return settle(prose, judge_state, instability)
        judge_state["error"] = "judgment pending: deterministic S3 rows first"
        settle(prose, judge_state, instability)
        det = sorted(g.entry_id for g in s3 if g.result != "pass" and
                     not g.entry_id.startswith("LLM-") and g.entry_id not in ("DET-85", "DET-13")
                     and g.entry_id not in LEVEL1_CHECKS)                       # A-25
        if det:
            judge_state.update(envelope=None, error=NOT_JUDGED, lost=[], not_judged=det)
            llm_rec["judge"].append({"pass": pass_no, "error": NOT_JUDGED, "failing": det})
            return settle(prose, judge_state, instability)
        judge_state.pop("error")
        try:
            # A-22: one call per criterion, the envelope assembled here; A-23 inside `judge`
            env, meta = llm.judge(judge_state["sections"], slot_users(), prose,
                                  row_displays(repo, doc), client, repo, rubric,
                                  {"rubric_version": "v1", "report_id": f"{token}@{blk}",
                                   "bundle_hash": man["report_hash"],
                                   "prompt_schema_version": str(mf["prompt_schema_version"])})
            env, lost = llm.post_check(env, judge_state["sections"])
            env, outside = llm.drop_outside_prose(env, judge_state["sections"],
                                                  judge_state["prose_paras"])
            env = llm.computed_pass(env, meta["criterion_errors"])
            judge_state.update(envelope=env.model_dump(by_alias=True), lost=lost,
                               item_errors={**llm.item_errors(env), **meta["criterion_errors"]})
            llm_rec["judge"].append({"pass": pass_no, **meta,
                                     "envelope": judge_state["envelope"],
                                     "item_errors": judge_state["item_errors"],
                                     "judge_span_not_found": lost, "outside_prose": outside})
        except llm.LLMError as exc:
            judge_state.update(envelope=None, error=str(exc), lost=[])
            llm_rec["judge"].append({"pass": pass_no, "error": str(exc), "calls": exc.calls})
        return settle(prose, judge_state, instability)

    def settle(prose: dict, judge_state: dict, instability: bool):
        from factory.report.render import render_token
        nonlocal s3, planned, evidence, gate
        s3, seen = [], None
        for _loop in range(4):
            gate = gates([*prior, *s3], instability)
            rec_triggers = [*fired_checks, *record.triggers_of(s3), *gate]
            planned = eventlog.plan_quarantine(entries, token, date,
                                               [(x["trigger"], x["level"]) for x in rec_triggers])
            # A-25: a Level-1 failure (DET-80) neither blocks nor stops the resolutions
            # A-24: `not_evaluated` rows are not failures here either (P-8.10 replay finding)
            green = seen is None or not {x for x in seen if x[0] not in LEVEL1_CHECKS
                                         and x[1] != "not_evaluated"}
            if green and not [x for x in gate if x["level"] > 1]:
                planned = [*planned, *plan_resolutions([*entries, *planned], token, date,
                                                       hashes, current)]
            evidence = [x for x in (evidence_of(ln, hashes, current, blk) for ln in planned
                                    if ln.resolution_date is not None) if x]
            after = [*entries, *planned]
            if stage.exists():
                shutil.rmtree(stage)
            pre = {"triggers": rec_triggers, "log": log_view(after, token, ttable, wording),
                   "prose": prose, "slots_missing": slots_missing(prose)}
            pages = render_token(repo, token, doc, grid, man, pre, b, s, stage)
            index_html = pages["index"].read_text(encoding="utf-8")
            if client is not None and not judge_state.get("sections") \
                    and not judge_state.get("withdrawn"):
                judge_state["sections"] = llm.page_sections(index_html)   # the first render
                judge_state["prose_paras"] = llm.prose_paragraphs(index_html)
            page = s3_page(repo, doc, grid, mirror_j, pages)
            page.update(trigger_table=ttable, log_entries=after, log_date=date,
                        log_raw=[e.model_dump() for e in after], record_triggers=rec_triggers,
                        prior_results=prior_results, report_manifest=man,
                        resolution_evidence=[*persisted_evidence, *evidence],
                        site_report_hash=_site_report_hash(repo, token), prose=prose,
                        judge_withdrawn=judge_state.get("withdrawn"),
                        judge_envelope=judge_state.get("envelope"),
                        judge_error=judge_state.get("error") or
                        ("no judgment: the report stage ran offline" if client is None else None),
                        remediation_unaddressed=judge_state.get("unaddressed", []),
                        judge_item_errors=judge_state.get("item_errors", {}),
                        revision_count=llm_rec["revision_count"],
                        revision_cause=llm_rec["revision_cause"])
            s3 = run_report_checks(b, t, s, page, stage="S3")
            failing = {(g.entry_id, g.result) for g in s3 if g.result != "pass"}
            if failing == seen:
                return
            seen = failing
        raise AssemblyStop(f"{token}: S3 failures did not stabilise across render passes")

    inputs_memo: dict[str, str] = {}

    def slot_users() -> dict[str, str]:
        """Each slot's generator input (its rows with printed forms, the assumptions block,
        the open Level-1 flags for flag explanations) - also the rows each scoped judge
        call reads (A-22)."""
        if inputs_memo:
            return inputs_memo
        spec = llm.prompts(repo)["slots"]
        displays = row_displays(repo, doc)
        opened = eventlog.open_entries([*entries, *eventlog.plan_quarantine(
            entries, token, date, [(x["trigger"], x["level"]) for x in fired_checks])], token)
        flags = [{"entry_id": eid, "trigger_literal": ttable[e.trigger]["name"],
                  "section": ttable[e.trigger]["section"], "fire_date": e.date,
                  # run 8 ruling 5: what the flag means, from wording.toml
                  "meaning": wording.get("flag_meaning", {}).get(e.trigger)}
                 for eid, e in opened if e.level == 1]
        owners = sorted({o for _eid, e in opened if e.level == 1
                         for o in ttable[e.trigger]["owners"]})
        for slot in (x["id"] for x in mf["prose_slots"]):
            sp = {**spec[slot], "owners": owners if spec[slot].get("owners_from_flags") else []}
            inputs_memo[slot] = llm.slot_input(slot, sp, doc, displays, flags, wording)
        return inputs_memo

    def slot_parts(slot: str) -> list[str] | None:
        """P-8.07: a split slot's per-part inputs - one per counterfactual line (table order)
        or one per open Level-1 flag (log order, each with its own trigger's owners); None
        for an unsplit slot or a flag slot with no open flag."""
        sp = llm.prompts(repo)["slots"][slot]
        if not sp.get("split"):
            return None
        displays = row_displays(repo, doc)
        if sp["split"] == "counterfactual_line":
            lines = llm.counterfactual_lines(doc)
            return [llm.slot_input(slot, {**sp, "owners": []}, doc, displays, [], wording,
                                   {"line": ln, "index": i, "of": len(lines)})
                    for i, ln in enumerate(lines)] or None
        opened = eventlog.open_entries([*entries, *eventlog.plan_quarantine(
            entries, token, date, [(x["trigger"], x["level"]) for x in fired_checks])], token)
        l1 = [(eid, e) for eid, e in opened if e.level == 1]
        return [llm.slot_input(slot, {**sp, "owners": ttable[e.trigger]["owners"]}, doc,
                               displays, [{"entry_id": eid,
                                           "trigger_literal": ttable[e.trigger]["name"],
                                           "section": ttable[e.trigger]["section"],
                                           "fire_date": e.date, "meaning": wording.get(
                                               "flag_meaning", {}).get(e.trigger)}],
                               wording, {"flag": eid, "index": i, "of": len(l1)})
                for i, (eid, e) in enumerate(l1)] or None

    def generate_all(pass_no: int, own: dict[str, list[dict]] | None = None,
                     carry: dict[str, str] | None = None, pass1: dict[str, str] | None = None
                     ) -> dict:
        """Pass 2: slots in `carry` (no pass-1 defect) keep their pass-1 text verbatim and
        make no call (sixth live run, ruling 3); every other slot is REVISED - its input
        carries its own pass-1 text and only its own defects (seventh live run, ruling a)."""
        if client is None:
            return {}
        if replay is not None and own is None:     # --from-record: no model call (P-8.10)
            prose = replayed_prose(replay)
            llm_rec["generation"].extend({**g, "replayed_from": replay["run_block"]}
                                         for g in replay.get("generation", []))
            return {x["id"]: prose[x["id"]] for x in mf["prose_slots"] if x["id"] in prose}
        spec = llm.prompts(repo)["slots"]
        users = slot_users()
        prose = {}
        for slot in (x["id"] for x in mf["prose_slots"]):
            if carry is not None and slot in carry:
                prose[slot] = carry[slot]
                g1 = next(g for g in llm_rec["generation"] if g["pass"] == 1 and g["slot"] == slot)
                llm_rec["generation"].append({"pass": pass_no, "slot": slot, "carried": True,
                                              "text": carry[slot],
                                              "references_field_ids":
                                              g1.get("references_field_ids", [])})
                continue
            sp = spec[slot]
            user = users[slot]
            bounds = llm.paragraph_bounds(sp, json.loads(user))
            try:
                if own is not None:                    # pass 2: span replacement only
                    g1 = next(g for g in llm_rec["generation"]
                              if g["pass"] == 1 and g["slot"] == slot)
                    user = json.dumps({**json.loads(user), "pass1_text": (pass1 or {})[slot],
                                       "pass1_defects": own[slot]}, ensure_ascii=False)
                    out, meta = llm.revise(slot, user, client, repo, sp["obligations"], bounds,
                                           g1.get("references_field_ids", []))
                elif (parts := slot_parts(slot)) is not None:      # P-8.07: per part
                    out, meta = llm.generate_parts(slot, parts, client, repo, sp["obligations"])
                else:
                    out, meta = llm.generate(slot, user, client, repo, sp["obligations"], bounds)
                prose[slot] = out.text
                llm_rec["generation"].append({"pass": pass_no, **meta,
                                              "references_field_ids": out.references_field_ids,
                                              "text": out.text})
            except llm.LLMError as exc:                 # ruling G: usage kept
                llm_rec["generation"].append({
                    "pass": pass_no, "slot": slot, "error": str(exc),
                    "reasks": 1 if "guard failed" in str(exc) else len(exc.calls) - 1,
                    "calls": exc.calls, "model": llm.GENERATOR_MODEL,
                    **{k: sum(c.get(k) or 0 for c in exc.calls)
                       for k in ("prompt_eval_count", "eval_count")}})
        return prose

    if preview and not ok:
        raise AssemblyStop(f"{token}: report-stage rows fail - no preview")
    if ok:
        j1: dict = {}
        prose1 = generate_all(1)
        if preview:
            return {"preview": True, "token": token, "run_block": blk,
                    "generation": llm_rec["generation"], "prose": prose1}
        evaluate(prose1, j1, False, 1)
        llm_fail = [g.entry_id for g in s3 if g.entry_id.startswith("LLM-") and g.result == "fail"]
        det_fail = [g for g in s3 if not g.entry_id.startswith("LLM-") and g.result != "pass"
                    and g.entry_id not in LEVEL1_CHECKS]                       # A-25
        surviving = [(c["id"], d) for c in (j1.get("envelope") or {}).get("criteria", [])
                     for d in c["defects"]]
        paras = j1.get("sections", {})
        outside_only = bool(surviving) and all(
            paras[d["location"]["section_id"]][d["location"]["paragraph_index"]]
            not in j1.get("prose_paras", set()) for _cid, d in surviving)
        if client is not None and llm_fail and not det_fail and j1.get("envelope") \
                and outside_only:
            # Amin, P-8.04 (P-7.11's recorded fix): every surviving pass-1 defect lies outside
            # prose (after post_check and drop_outside_prose; only LLM-03 keeps such defects) -
            # no slot revision can reach it, so pass 2 is skipped: a template defect.
            llm_outcome = "template_defect"
            llm_rec["pass2_skipped"] = "outside_prose"
        elif client is not None and llm_fail and not det_fail and j1.get("envelope"):
            # R-48 pass 2: one revision against an unchanged bundle (DET-13(g)).
            assert table.table_hash(doc, grid) == doc["table_hash"] == man["table_hash"]
            llm_rec["revision_count"] = 1
            llm_rec["revision_cause"] = sorted(llm_fail)
            d1 = [{"index": i, **x} for i, x in enumerate(
                {"criterion": c["id"], **dd} for c in j1["envelope"]["criteria"]
                for dd in c["defects"])]
            slots = llm.prompts(repo)["slots"]
            own = llm.defects_by_slot(d1, prose1, {s: slots[s]["page_section"] for s in prose1})
            # NAMED DEFAULT (span replacement): only a defect whose span is in the slot's own
            # pass-1 text can be replaced; a slot left with none carries verbatim
            own = {s: kept for s, ds in own.items()
                   if (kept := [d for d in ds
                                if d["location"]["quoted_span"] in prose1.get(s, "")])}
            prose2 = generate_all(2, own, carry={s: x for s, x in prose1.items() if s not in own},
                                  pass1=prose1)
            j2: dict = {}
            evaluate(prose2, j2, False, 2)
            if not j2.get("not_judged"):       # a deterministic failure: no remediation
                try:
                    rem, meta = llm.remediate(d1, llm.page_text(j2["sections"]), client, repo)
                    unaddressed = [d1[a.defect_index] for a in rem.items if a.addressed == "no"]
                    llm_rec["judge"].append({"pass": 2, "remediation": rem.model_dump(), **meta})
                except (llm.LLMError, KeyError) as exc:
                    unaddressed = d1
                    llm_rec["judge"].append({"pass": 2, "remediation_error": str(exc),
                                             "calls": getattr(exc, "calls", [])})
                env2 = j2.get("envelope")
                k1 = {(x["kind"], x["location"]["section_id"]) for x in d1}
                k2 = ({(dd["kind"], dd["location"]["section_id"]) for c in env2["criteria"]
                       for dd in c["defects"]} if env2 else set())
                lost = bool(j1.get("lost") or j2.get("lost"))
                if env2 and not k2 and not unaddressed and not lost:
                    llm_outcome = None                                     # R-48a: publish
                elif not lost and k1 & k2:
                    llm_outcome = "template_defect"
                else:
                    llm_outcome = "judge_instability"
                j2["unaddressed"] = unaddressed
                evaluate(prose2, j2, llm_outcome == "judge_instability", 2)
    else:
        gate = gate_triggers(prior)
        planned = eventlog.plan_quarantine(entries, token, date,
                                           [(x["trigger"], x["level"])
                                            for x in [*fired_checks, *gate]])
    after = [*entries, *planned]
    heavy = [e for _, e in eventlog.open_entries(after, token) if e.level in (2, 3)]
    det_fail = [g for g in s3 if not g.entry_id.startswith("LLM-") and g.result != "pass"
                and g.entry_id not in ("DET-85", "DET-13", *LEVEL1_CHECKS)]   # A-25
    llm_rec["slots_missing"] = slots_missing(last_prose[0]) if client is not None else []
    # A-24: `not_evaluated` rows are ignored by the outcome rule
    llm_bad = [g for g in s3 if g.entry_id.startswith("LLM-") and g.result in ("fail", "error")]
    tail_bad = [g for g in s3 if g.entry_id in ("DET-85", "DET-13") and g.result != "pass"]
    if rehearsal:
        outcome = "rehearsal"
    elif not ok or det_fail:
        outcome = "blocked_S3"
    elif llm_outcome:
        outcome = llm_outcome
    elif llm_bad or tail_bad:
        outcome = "blocked_S3"
    else:
        outcome = "quarantined" if heavy else "published"
    rec = record.build(parts, man, s01, t.checks, s.checks, [*report_checks, *s3], rubric,
                       gate_triggers=tuple([*gate, *(x for x in fired_checks
                                                     if x["source_entry"] == "test")]),
                       outcome=outcome, llm=llm_rec)
    out = (repo / "out/report" / token / str(blk) if ok
           else repo / "out/rehearsal" / token / f"report-{blk}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "table.json").write_text(_json(doc), encoding="utf-8", newline="")
    (out / "grid.json").write_text(_json(grid), encoding="utf-8", newline="")
    (out / "manifest.json").write_text(_json(man), encoding="utf-8", newline="")
    ev = repo / "out/evaluation" / token
    if rehearsal:
        planned, evidence = [], []
        stage.mkdir(parents=True, exist_ok=True)
        (stage / f"evaluation-rehearsal-{blk}.json").write_text(
            _json(rec.model_dump(mode="json")), encoding="utf-8", newline="")
    else:
        ev.mkdir(parents=True, exist_ok=True)
        (ev / f"{blk}.json").write_text(_json(rec.model_dump(mode="json")), encoding="utf-8",
                                        newline="")
    if evidence:
        with (ev / "resolutions.jsonl").open("a", encoding="utf-8", newline="") as fh:
            for item in evidence:
                fh.write(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n")
    lines = planned
    for line in lines:                           # the log is written last, once per run
        eventlog.append(log_path, line)
    if outcome == "published":
        eventlog.append(log_path, eventlog.PublishedEvent(date=date, token=token,
                                                          bundle_hash=b.header.bundle_hash))
    site_root = repo / "out/site"
    site = None
    if ok and not rehearsal:
        (stage / "data" / f"evaluation-{blk}.json").write_text(
            _json(rec.model_dump(mode="json")), encoding="utf-8", newline="")
        # P-8.04 Q7 (supersedes B-11b's named default): only a published outcome replaces
        # `out/site/<T>/`; any other outcome leaves the last published pages in place - the
        # record and its log line are the evidence, rendered by `factory.site`
        if outcome == "published":
            if (site_root / token).exists():
                shutil.rmtree(site_root / token)
            shutil.copytree(stage, site_root / token)
            shutil.copyfile(stage.parent / "style.css", site_root / "style.css")
            site = site_root / token
    return {"ok": ok, "doc": doc, "grid": grid, "manifest": man, "record": rec, "out": out,
            "llm": llm_rec,
            "site": site, "pages": stage if ok else None, "log_lines": lines}


BANNER = re.compile(r'<div class="banner quarantine">.*?</div>\n?', re.S)
PLACEHOLDER = re.compile(r'<div class="slot">\[slot: ([a-z0-9_]+) — pending B-13\]</div>\n?')
PILL_FLAGS = re.compile(r'<span class="pill [a-z]+">[^<]*</span>(?=\n</div>)')


def publish_without_banner(repo: pathlib.Path, token: str, date: str,
                           ruling: str = "P-7.11") -> dict:
    """Amin, 2026-09-14 (P-7.11): API spend is closed; the token publishes from its latest
    rehearsal page set as its last live run rendered it, template-only changes:
    - the DET-59 quarantine banner element is removed;
    - (a) an empty prose-slot placeholder element ("[slot: … — pending B-13]") is removed;
    - (b) the notices pill is rebuilt through `render.pills` from the log's open Level
      1/2/3 entries. NAMED DEFAULT: the names in the record's trigger order, then any other
      open entry in log order.
    The gate record keeps its results and gains the outcome
    `published_without_banner_by_ruling` and `publication` (each removal, the pill); the log
    gains no line; DET-59 is not evaluated on these pages."""
    from markupsafe import Markup

    from factory.report.render import Formatter, pills
    ev = repo / "out/evaluation" / token
    rec_path = max((p for p in ev.glob("*.json") if p.stem.isdigit()), key=lambda p: int(p.stem))
    blk = int(rec_path.stem)
    stage = repo / "out/rehearsal" / token / str(blk)
    names = ("index.html", "appendix.html", "verify.html")
    missing = [n for n in (*names, "data") if not (stage / n).exists()]
    if missing:
        raise AssemblyStop(f"{token}: rehearsal page set incomplete at {stage}: {missing}")
    rec = record.GateRecord.model_validate_json(rec_path.read_text(encoding="utf-8"))
    prior = (rec.publication or {}).get("prior_outcome", rec.outcome)      # a re-run keeps it

    # (b) the notices pill from the open entries, through the same fragment
    tpl = repo / "templates"
    mf = tomllib.loads((tpl / "manifest.toml").read_text(encoding="utf-8"))
    w = tomllib.loads((tpl / "wording.toml").read_text(encoding="utf-8"))
    doc = json.loads((stage / "data/table.json").read_text(encoding="utf-8"))
    rows = {r["field_id"]: r for r in doc["rows"]}
    fmt = Formatter(mf["display_rule"], mf["compact"], int(rows["tree.root.value_scale"]["value"]))

    def v(fid: str) -> str:
        r = rows[fid]
        return fmt(r["value"], r["unit"], r["denominator"])
    tnames = {k: (x["name"], x["section"])
              for k, x in trigger_table(_lf(repo / "docs/context/rubic_v1.md")).items()}
    opened = eventlog.open_entries(
        eventlog.read(repo / "out/logs" / f"events_{token.lower()}.jsonl"), token)
    level: dict[str, int] = {}
    for _eid, e in opened:
        level[e.trigger] = max(level.get(e.trigger, 0), e.level)
    order = [t["trigger"] for t in rec.triggers if t["trigger"] in level]
    order += [e.trigger for _eid, e in opened]
    ordered = list(dict.fromkeys(order))
    colour, text = pills(rows, {"triggers": [{"trigger": t, "level": level[t]} for t in ordered]},
                         tnames, w, v)[2]
    new_pill = str(Markup('<span class="pill {}">{}</span>').format(colour, text))

    site_root = repo / "out/site"
    site = site_root / token
    if site.exists():
        shutil.rmtree(site)
    shutil.copytree(stage, site)
    removed, placeholders, pill = {}, [], None
    for n in names:
        html = (site / n).read_text(encoding="utf-8")
        new, count = BANNER.subn("", html)
        placeholders += [f"{n}: {m}" for m in PLACEHOLDER.findall(new)]
        new, slots = PLACEHOLDER.subn("", new)
        if n == "index.html":
            old = PILL_FLAGS.search(new)
            if old is None:
                raise AssemblyStop(f"{token}: no notices pill on {n}")
            pill = {"note": "pill rebuilt from open entries", "before": old.group(0),
                    "after": new_pill}
            new = new[:old.start()] + new_pill + new[old.end():]
        removed[n] = {"banner": count, "placeholders": slots}
        if new != html:
            (site / n).write_bytes(new.encode("utf-8"))
    if not (site_root / "style.css").exists():
        shutil.copyfile(stage.parent / "style.css", site_root / "style.css")
    rec = rec.model_copy(update={
        "outcome": "published_without_banner_by_ruling",
        "publication": {"date": date, "ruling": ruling,
                        "source": stage.relative_to(repo).as_posix(),
                        "removed": {"elements": "DET-59 quarantine banner; empty prose-slot "
                                                "placeholders", **removed},
                        "placeholders_removed": placeholders, "pill": pill,
                        "prior_outcome": prior}})
    rec_path.write_text(_json(rec.model_dump(mode="json")), encoding="utf-8", newline="")
    return {"token": token, "run_block": blk, "site": site, "removed": removed,
            "placeholders": placeholders, "pill": pill, "prior_outcome": prior}


if __name__ == "__main__":
    _repo = pathlib.Path(__file__).resolve().parents[3]
    if len(sys.argv) == 3 and sys.argv[1] == "--publish-without-banner":
        _today = _dt.datetime.now(_dt.UTC).date().isoformat()
        _p = publish_without_banner(_repo, sys.argv[2], _today)
        print(f"published_without_banner_by_ruling | {_p['token']}@{_p['run_block']} | prior "
              f"{_p['prior_outcome']} | removed {_p['removed']} | {_p['site']}")
        sys.exit(0)
    if len(sys.argv) < 2:
        print("usage: python -m factory.report <TOKEN> [--llm [--preview]]  (crvUSD | GHO | LUSD)")
        sys.exit(2)
    if len(sys.argv) == 4 and sys.argv[2] == "--from-record":
        # P-8.10: republish at a record's block from its guard-passed slot texts, the missing
        # slots as the A-25 notice; no model call
        _tok, _blk = sys.argv[1], int(sys.argv[3])
        _rec = json.loads((_repo / "out/evaluation" / _tok / f"{_blk}.json")
                          .read_text(encoding="utf-8"))
        from factory.tree import latest_bundle
        _latest = latest_bundle(_repo, _tok).header.run_block
        if _latest != _blk:
            print(f"AssemblyStop: {_tok}'s latest promoted bundle is {_latest}, not {_blk}",
                  file=sys.stderr)
            sys.exit(1)
        r = build(_repo, _tok, client=ReplayClient(_rec), replay=_rec)
        _rr = r["record"]
        print(f"from-record {_tok}@{_blk} | outcome {_rr.outcome} | report "
              f"{_rr.report_hash[:8]} | slots reused "
              f"{len(replayed_prose(_rec))} | slots as notices {_rr.slots_missing} | results "
              f"{sum(1 for x in _rr.results if x.result == 'pass')} pass, "
              f"{sum(1 for x in _rr.results if x.result == 'not_evaluated')} not_evaluated, "
              f"{sum(1 for x in _rr.results if x.result in ('fail', 'error'))} fail | triggers "
              f"{[(x['trigger'], x['level'], x['source_entry']) for x in _rr.triggers]} | "
              f"site {r['site']}")
        sys.exit(0)
    try:
        _client = None
        if "--llm" in sys.argv[2:]:          # B-13 NAMED DEFAULT: the model only on request
            from factory.report.llm import OllamaClient
            _client = OllamaClient()         # P-8.04: the local Ollama model only
        _preview = "--preview" in sys.argv[2:]   # generation only, needs --llm (seventh run)
        r = build(_repo, sys.argv[1], client=_client, preview=_preview)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    if r.get("preview"):
        for g in r["generation"]:
            print(f"preview {r['token']}@{r['run_block']} | {g['slot']} | re-asks "
                  f"{g.get('reasks')} | {'EMPTY: ' + g['error'] if g.get('error') else 'ok'} | "
                  f"wall {sum(c.get('wall_s') or 0 for c in g.get('calls') or []):.0f} s")
        sys.exit(0)
    rec = r["record"]
    fails = [x.entry_id for x in rec.results if x.result != "pass"]
    print(f"token {rec.token} | run_block {rec.run_block} | rows {len(r['doc']['rows'])} | "
          f"table {rec.table_hash[:8]} | template {rec.template_hash[:8]} | "
          f"report {rec.report_hash[:8]} | results {len(rec.results) - len(fails)}/"
          f"{len(rec.results)} | unregistered {len(rec.unregistered)} | "
          f"{'promoted' if r['ok'] else 'rehearsal'} | {r['out']}")
    if r["llm"].get("llm"):
        _w = sum(c.get("wall_s") or 0 for g in r["llm"]["generation"] for c in g.get("calls") or [])
        _w += sum(j.get("wall_s") or 0 for j in r["llm"]["judge"])
        print(f"model {r['llm']['llm']['model']} | ollama {r['llm']['llm']['version']} | "
              f"model wall time {_w:.0f} s")
    print(f"outcome {rec.outcome} | revision_count {rec.revision_count} | pages {r['pages']} | "
          f"site {r['site']}")
    if fails:
        print("not pass:", fails)
        for x in rec.results:
            if x.result != "pass":
                print(f"  {x.entry_id} {x.result}: {x.scope_condition}")
    print("triggers:", [(x["trigger"], x["level"], x["source_entry"]) for x in rec.triggers])
