"""B-10: the gate-evaluation record (P-7.01 R13, inventory B.1) at
`out/evaluation/<TOKEN>/<run_block>.json`, committed.

One record per report attempt: every REGISTERED check's result with its stage
(S0/S1 re-evaluated over the promoted bundle without raising; S2 as the tree and
stress artifacts recorded them; the report stage run now), the triggers they
fired, A-16's enumeration of UNREGISTERED rubric IDs with their queue item, the
report manifest's seven components and `report_hash`, and `revision_count` /
`revision_cause`, which left `Header` at B-9 (DET-13(g)). S3 results enter at
B-11b; the judge and generation fields stay empty until B-13.

NAMED DEFAULTS (B-10): S2 triggers are parsed from the scope text the S2 rows
already carry (`T-xx (Ln)` / `T-21 …`), level from `TRIGGER_TABLE` when the text
names none - B-12 structures trigger collection; `outcome` is null until the
loop exists (B-13), except "blocked_S3" (B-11b): any S3 row not passing routes the
pages to `out/rehearsal/` and the record says so.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel

from factory.validate.harness import CHECKS, TRIGGER_TABLE

# A-16: every rubric ID not registered, by the queue item that builds it (the
# P-7.01 block plan; P-4.01 for items no Step-7 block owns). A registry that
# grows removes an ID from here; a rubric ID in neither place fails the build.
QUEUE = {
    "DET-09": "P-4.01 (DET-09 set-file inputs: GHO discovery_m absent, LUSD 0.4459 - ruling)",
    "DET-64": "P-4.01 (GHO attribution cross-check: aggregate reads)",
    "DET-75": "P-4.01 #25/#26 (field-existence clause; FR-14 fields)",
    "DET-81": "P-4.01 (GHO [[reference_feed]] rows, gap column - P-7.05)",
    "DET-23abd": "P-4.01 (DET-23 limbs a/b/d beside the registered DET-23c)",
    "DET-76abcd": "P-4.01 (DET-76 limbs a-d beside the registered DET-76e)",
}
# Rubric entries whose registration is split into limb rows, and the S3 limbs
# of entries registered at S0/S2 (inventory L).
LIMBS = {"DET-29(a)": ["DET-29a"], "DET-29(b)(c)": ["DET-29bc"], "DET-23": ["DET-23c"],
         "DET-76": ["DET-76e"]}
UNREGISTERED_LIMBS = {"DET-23": "DET-23abd", "DET-76": "DET-76abcd",
                      "DET-29(b)(c)": "DET-29c", "DET-12": "DET-12-S3", "DET-14": "DET-14cd",
                      "DET-22": "DET-22-S3"}


class RecordResult(BaseModel):
    entry_id: str
    stage: Literal["S0", "S1", "S2", "S3"]
    result: Literal["pass", "fail", "not_applicable", "error"]
    scope_condition: str | None = None


class GateRecord(BaseModel):
    token: str
    run_block: int
    report_hash: str
    bundle_hash: str
    tree_hash: str
    stress_hash: str
    table_hash: str
    template_hash: str
    pipeline_version: str
    sheet_hash: str
    results: list[RecordResult]
    triggers: list[dict[str, Any]]
    unregistered: list[dict[str, str]]
    judge: list[dict[str, Any]] = []            # B-13: envelopes, calls, span events
    generation: list[dict[str, Any]] = []       # B-13: one entry per slot call per pass
    # B-12 (DET-87's rubric_change evidence): the rubric header stamp this run read.
    rubric_hash: str | None = None
    revision_count: Literal[0, 1] = 0
    revision_cause: list[str] = []
    outcome: Literal["published", "quarantined", "template_defect", "judge_instability",
                     "harness_error", "blocked_S3", "rehearsal"] | None = None


def rubric_ids(rubric_text: str) -> list[str]:
    ids = re.findall(r"^\*\*(DET-\d\d(?:\([a-z]\))*|LLM-\d\d)(?= )", rubric_text, re.M)
    return list(dict.fromkeys(ids))


def unregistered(rubric_text: str) -> list[dict[str, str]]:
    registered = {c.entry_id for c in CHECKS}
    out = []
    for rid in rubric_ids(rubric_text):
        mapped = LIMBS.get(rid, [rid])
        if not any(m in registered for m in mapped):
            out.append(rid)
        if (rid in UNREGISTERED_LIMBS and any(m in registered for m in mapped)
                and UNREGISTERED_LIMBS[rid] not in registered):
            out.append(UNREGISTERED_LIMBS[rid])
    missing = [x for x in out if x not in QUEUE]
    if missing:
        raise ValueError(f"A-16: unregistered ID(s) with no queue item {missing}")
    return [{"entry_id": x, "queue_item": QUEUE[x]} for x in out]


def _triggers_from_scope(entry_id: str, scope: str | None) -> list[dict]:
    if not scope:
        return []
    m = re.match(r"^(T-\d\d)(?: \(L(\d)\))?", scope)
    if not m:
        return []
    level = int(m.group(2)) if m.group(2) else TRIGGER_TABLE.get(m.group(1))
    if isinstance(level, tuple):
        level = level[0]
    return [{"trigger": m.group(1), "level": level, "source_entry": entry_id}]


def triggers_of(results) -> list[dict]:
    """The triggers S0-S3 results fired, from their scope text (B-10's default)."""
    return [x for g in results for x in _triggers_from_scope(g.entry_id, g.scope_condition)]


def build(parts: dict, manifest: dict, s01, tree_checks, stress_checks, report_checks,
          rubric_text: str, gate_triggers: tuple = (), outcome: str | None = None,
          llm: dict | None = None) -> GateRecord:
    stage = {c.entry_id: c.stage for c in CHECKS}
    results, triggers = [], []
    for g in [*s01.results, *tree_checks, *stress_checks, *report_checks]:
        results.append(RecordResult(entry_id=g.entry_id, stage=stage[g.entry_id],
                                    result=g.result, scope_condition=g.scope_condition))
        triggers += _triggers_from_scope(g.entry_id, g.scope_condition)
    triggers += list(gate_triggers)                  # B-12: T-28 / T-23 per failed check
    got = {r.entry_id for r in results}
    want = {c.entry_id for c in CHECKS}
    if got != want:
        raise ValueError(f"record incomplete: missing {sorted(want - got)}, extra "
                         f"{sorted(got - want)}")
    llm = llm or {}
    return GateRecord(token=manifest["token"], run_block=manifest["run_block"],
                      judge=llm.get("judge", []), generation=llm.get("generation", []),
                      revision_count=llm.get("revision_count", 0),
                      revision_cause=llm.get("revision_cause", []),
                      report_hash=manifest["report_hash"],
                      **{k: parts[k] for k in ("bundle_hash", "tree_hash", "stress_hash",
                                               "table_hash", "template_hash",
                                               "pipeline_version", "sheet_hash")},
                      results=results, triggers=triggers,
                      unregistered=unregistered(rubric_text),
                      rubric_hash=__import__("hashlib").sha256(rubric_text.encode()).hexdigest()[:8],
                      outcome=outcome if outcome is not None else
                      ("blocked_S3" if any(r.stage == "S3" and r.result != "pass"
                                           for r in results) else None))
