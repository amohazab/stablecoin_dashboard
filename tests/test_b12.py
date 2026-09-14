"""B-12 tests: rubric §3's parse and DET-12, the event log's quarantine lifecycle,
T-28, and the six rows - a pass on the recorded run and one mutation each."""

from __future__ import annotations

import copy
import json
import pathlib

import pytest

from factory import eventlog
from factory.eventlog import QuarantineEvent
from factory.report.__main__ import gate_triggers, s3_page
from factory.rubric import read_trigger_table
from factory.schema import GateResult
from factory.validate.harness import (
    CHECKS,
    TRIGGER_SECTION,
    TRIGGER_TABLE,
    Level3,
    det_12,
    det_12_s3,
    det_13,
    det_58,
    det_59,
    det_60,
    det_87,
)

REPO = pathlib.Path(__file__).resolve().parents[1]
BLOCKS = {"crvUSD": 25974925, "GHO": 25974932, "LUSD": 25974949}


# ---- §3 and DET-12 S0 --------------------------------------------------------------


def test_section3_parses_every_row_with_split_levels_and_sections():
    t = read_trigger_table(REPO)
    assert len(t) == 28 and set(t) == set(TRIGGER_TABLE)
    assert t["T-18"]["levels"] == [2, 1] and t["T-28"] == {"name": "gate failure", "levels": [2],
                                                          "section": "—", "owners": []}
    assert t["T-20"]["owners"] == ["DET-29"] and t["T-23"]["owners"] == ["DET-13", "DET-59",
                                                                          "DET-87"]
    assert {k: v["section"] for k, v in t.items()} == TRIGGER_SECTION
    det_12(None, {"printed_trigger_table": t})
    moved = copy.deepcopy(t)
    moved["T-02"]["section"] = "supply"
    with pytest.raises(Level3, match="DET-12"):
        det_12(None, {"printed_trigger_table": moved})


# ---- the log lifecycle -------------------------------------------------------------------


def test_level1_lifecycle_ii_and_its_resolution():
    e: list = []
    first = eventlog.plan_quarantine(e, "GHO", "2026-09-14", [("T-20", 1)])
    assert [(x.trigger, x.level, x.resolution_date) for x in first] == [("T-20", 1, None)]
    e += first
    assert eventlog.plan_quarantine(e, "GHO", "2026-09-21", [("T-20", 1)]) == []   # still open
    assert eventlog.open_entries(e, "GHO") == [("GHO:1", first[0])]
    stop = eventlog.plan_quarantine(e, "GHO", "2026-09-28", [])
    assert [(x.date, x.resolution_type, x.resolution_date) for x in stop] == [
        ("2026-09-14", "data_correction", "2026-09-28")]
    assert eventlog.open_entries([*e, *stop], "GHO") == []


def test_level2_fires_once_per_run_and_runs_count_dates_after_publication():
    e: list = [eventlog.PublishedEvent(date="2026-09-01", token="crvUSD", bundle_hash="h")]
    for d in ("2026-09-07", "2026-09-07", "2026-09-14"):
        e += eventlog.plan_quarantine(e, "crvUSD", d, [("T-28", 2), ("T-23", 2)])
    assert len(eventlog.quarantine_lines(e, "crvUSD")) == 4                       # 2 x 2 dates
    assert eventlog.consecutive_quarantined_runs(e, "crvUSD") == 2
    e.append(eventlog.PublishedEvent(date="2026-09-15", token="crvUSD", bundle_hash="h2"))
    assert eventlog.consecutive_quarantined_runs(e, "crvUSD") == 0


def test_resolve_refuses_an_override(tmp_path):
    fire = QuarantineEvent(date="2026-09-14", token="LUSD", trigger="T-28", level=2)
    with pytest.raises(ValueError, match="illegal resolution_type"):
        eventlog.resolve(tmp_path / "log.jsonl", fire, "override", "2026-09-15")
    eventlog.resolve(tmp_path / "log.jsonl", fire, "template_change", "2026-09-15")
    assert eventlog.read(tmp_path / "log.jsonl")[0].resolution_type == "template_change"


def test_t28_names_each_failed_check_and_t23_owners_keep_their_trigger():
    res = [GateResult(entry_id="DET-79", result="fail"),
           GateResult(entry_id="DET-13", result="error"),
           GateResult(entry_id="DET-17", result="pass")]
    assert gate_triggers(res) == [
        {"trigger": "T-28", "level": 2, "source_entry": "DET-79"},
        {"trigger": "T-23", "level": 2, "source_entry": "DET-13"}]


# ---- the six rows over the recorded run -----------------------------------------------


@pytest.fixture(scope="module")
def runs():
    from factory.schema import StressReport
    from factory.stress import load_inputs
    out = {}
    for tok, blk in BLOCKS.items():
        inp = load_inputs(REPO, tok)
        s = StressReport.model_validate_json((REPO / f"out/stress/{tok}/{blk}.json")
                                             .read_text(encoding="utf-8"))
        rep = REPO / f"out/report/{tok}/{blk}"
        doc = json.loads((rep / "table.json").read_text(encoding="utf-8"))
        grid = json.loads((rep / "grid.json").read_text(encoding="utf-8"))
        man = json.loads((rep / "manifest.json").read_text(encoding="utf-8"))
        rec = json.loads((REPO / f"out/evaluation/{tok}/{blk}.json").read_text(encoding="utf-8"))
        stage = REPO / f"out/rehearsal/{tok}/{blk}"
        files = {k: stage / f"{k}.html" for k in ("index", "appendix", "verify")}
        page = s3_page(REPO, doc, grid, json.loads(json.dumps(inp["cfg"].sheet, default=str)),
                       files)
        entries = eventlog.read(REPO / f"out/logs/events_{tok.lower()}.jsonl")
        page.update(trigger_table=read_trigger_table(REPO), log_entries=entries,
                    log_raw=[e.model_dump() for e in entries], log_date="2026-09-14",
                    record_triggers=rec["triggers"], report_manifest=man,
                    prior_results=[r for r in rec["results"] if r["stage"] != "S3"],
                    resolution_evidence=[], site_report_hash=None)
        page["_s3_results"] = [r for r in rec["results"]
                               if r["stage"] == "S3" and r["entry_id"] != "DET-13"]
        have = {r["entry_id"] for r in rec["results"]}          # B-13's rows postdate the record
        page["_s3_results"] += [{"entry_id": c.entry_id, "stage": "S3", "result": "pass",
                                 "scope_condition": None} for c in CHECKS
                                if c.entry_id not in have and c.entry_id != "DET-13"]
        out[tok] = (inp["bundle"], inp["tree"], s, page)
    return out


def fresh(page: dict, **upd) -> dict:
    p = {k: v for k, v in page.items() if k != "_s3"}
    p["html"] = dict(page["html"])
    p.update(upd)
    return p


def call(fn, runs, tok, page):
    b, t, s, _ = runs[tok]
    return fn(b, t, s, page)


def test_det12_s3(runs):
    page = runs["GHO"][3]
    # P-7.10's final spend run added T-25 to GHO's record triggers
    assert call(det_12_s3, runs, "GHO", fresh(page)).startswith("4 trigger(s)")
    bad = fresh(page)
    bad["html"]["index"] = bad["html"]["index"].replace("4 notice(s)", "3 notice(s)")
    with pytest.raises(Level3, match="flags line"):
        call(det_12_s3, runs, "GHO", bad)


def test_det58(runs):
    page = runs["GHO"][3]
    assert call(det_58, runs, "GHO", fresh(page)) == "2 open Level-1 entr(ies) flagged"
    bad = fresh(page)
    bad["html"]["index"] = bad["html"]["index"].replace('data-entry="GHO:10"',
                                                        'data-entry="GHO:99"')
    with pytest.raises(Level3, match="no open Level-1 entry"):
        call(det_58, runs, "GHO", bad)


def test_det59(runs):
    # LUSD published at P-7.10 (no banner); crvUSD's last live page still carries it
    crv = runs["crvUSD"][3]
    assert "Current run: quarantined — gate failure" in call(det_59, runs, "crvUSD", fresh(crv))
    bad = fresh(crv)
    bad["html"]["index"] = bad["html"]["index"].replace("Current run: quarantined", "Current run")
    with pytest.raises(Level3, match="banner literal"):
        call(det_59, runs, "crvUSD", bad)
    page = runs["LUSD"][3]
    nob = fresh(page)
    nob["html"]["index"] = nob["html"]["index"].replace("behavioral tier: pending", "")
    with pytest.raises(Level3, match=r"DET-59\(b\)"):
        call(det_59, runs, "LUSD", nob)


def test_det60(runs):
    page = runs["GHO"][3]
    assert "every fired trigger has one entry" in call(det_60, runs, "GHO", fresh(page))
    extra = fresh(page, log_raw=[*page["log_raw"][:-1], {**page["log_raw"][-1], "check": "x"}])
    with pytest.raises(Level3, match="fields"):
        call(det_60, runs, "GHO", extra)
    unlogged = fresh(page, record_triggers=[*page["record_triggers"],
                                            {"trigger": "T-07", "level": 1, "source_entry": "x"}])
    with pytest.raises(Level3, match="T-07"):
        call(det_60, runs, "GHO", unlogged)


def test_det87(runs):
    page = runs["crvUSD"][3]
    assert "0 resolution(s)" in call(det_87, runs, "crvUSD", fresh(page))
    fire = next(e for e in page["log_entries"] if e.type == "quarantine")
    same_day = QuarantineEvent(date=fire.date, token="crvUSD", trigger=fire.trigger,
                               level=fire.level, resolution_type="template_change",
                               resolution_date=fire.date)
    with pytest.raises(Level3, match="no evidence"):
        call(det_87, runs, "crvUSD", fresh(page, log_entries=[*page["log_entries"], same_day]))
    flat = {"date": fire.date, "trigger": fire.trigger, "level": fire.level,
            "resolution_type": "template_change", "resolution_date": fire.date,
            "field": "template_hash", "fire_value": "f89ddcc5", "resolution_value": "f89ddcc5"}
    with pytest.raises(Level3, match="did not change"):
        call(det_87, runs, "crvUSD", fresh(page, log_entries=[*page["log_entries"], same_day],
                                           resolution_evidence=[flat]))
    moved = {**flat, "resolution_value": "4a23fe50"}                 # B-13: evidence by run
    assert "1 resolution(s) evidenced" in call(det_87, runs, "crvUSD", fresh(
        page, log_entries=[*page["log_entries"], same_day], resolution_evidence=[moved]))
    with pytest.raises(Level3, match="pipeline_version"):
        call(det_87, runs, "crvUSD", fresh(page, report_manifest={
            **page["report_manifest"], "pipeline_version": ""}))


def test_det13(runs):
    page = runs["LUSD"][3]
    assert "(f) vacuous" in call(det_13, runs, "LUSD", fresh(page))
    with pytest.raises(Level3, match=r"DET-13\(a\)"):
        call(det_13, runs, "LUSD", fresh(page, report_manifest={
            **page["report_manifest"], "bundle_hash": "0" * 64}))
    crv = runs["crvUSD"][3]                    # (d) needs an open Level 2/3 entry: crvUSD's
    with pytest.raises(Level3, match=r"DET-13\(d\)"):
        call(det_13, runs, "crvUSD", fresh(crv,
                                           site_report_hash=crv["report_manifest"]["report_hash"]))
    with pytest.raises(Level3, match=r"DET-13\(c\)"):
        call(det_13, runs, "LUSD", fresh(page, prior_results=page["prior_results"][1:]))


def test_the_recorded_run_logged_t28_and_the_gho_flags():
    for tok in BLOCKS:
        log = eventlog.read(REPO / f"out/logs/events_{tok.lower()}.jsonl")
        lines = eventlog.quarantine_lines(log, tok)
        got = {(e.trigger, e.level, e.date) for _, e in lines}
        assert ("T-28", 2, "2026-09-14") in got
    gho = {e.trigger for _, e in eventlog.open_entries(
        eventlog.read(REPO / "out/logs/events_gho.jsonl"), "GHO")}
    assert gho == {"T-20", "T-02", "T-28", "T-25"}                 # T-25: P-7.10's final spend


def test_det89_reads_the_section3_literals_as_printed_text(runs):
    from factory.validate.harness import det_89
    page = runs["GHO"][3]                          # ruling (a): T-02's "> 25%" flag literal
    assert "off-venue share &gt; 25%" in page["html"]["index"]
    assert "every figure a fmt output" in call(det_89, runs, "GHO", fresh(page))
    with pytest.raises(Level3, match=r"index:25%"):
        call(det_89, runs, "GHO", fresh(page, trigger_table={}))
