"""B-11b tests: the fifteen S3 rows (a pass and one mutation each, DET-79's
placeholder case), the report-stage routing, and the print rules.

A pass case reads the rendered rehearsal page, with a test-only block appended
where today's page lacks the clause's literal - the fixture, never an output;
the mutation removes or alters one thing the clause needs."""

from __future__ import annotations

import copy
import json
import pathlib

import pytest

from factory.report import record
from factory.report.__main__ import s3_page
from factory.validate.harness import (
    CHECKS,
    Level3,
    _figures,
    det_14cd,
    det_17,
    det_18,
    det_22_s3,
    det_29c,
    det_36,
    det_53,
    det_54,
    det_56,
    det_57,
    det_73,
    det_74,
    det_79,
    det_88,
    det_89,
    run_report_checks,
)

REPO = pathlib.Path(__file__).resolve().parents[1]
BLOCKS = {"crvUSD": 25970226, "GHO": 25970233, "LUSD": 25970249}
S3_IDS = {"DET-14cd", "DET-22-S3", "DET-29c", "DET-17", "DET-18", "DET-36", "DET-53", "DET-54",
          "DET-56", "DET-57", "DET-73", "DET-74", "DET-79", "DET-88", "DET-89"}


@pytest.fixture(scope="module")
def inputs():
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
        stage = REPO / f"out/rehearsal/{tok}/{blk}"
        files = {k: stage / f"{k}.html" for k in ("index", "appendix", "verify")}
        mirror = json.loads(json.dumps(inp["cfg"].sheet, default=str))
        out[tok] = (inp["bundle"], inp["tree"], s, s3_page(REPO, doc, grid, mirror, files))
    return out


def fresh(page: dict, **html_add) -> dict:
    """A copy without the parse cache; `index=` / `appendix=` text is appended."""
    p = {k: v for k, v in page.items() if k != "_s3"}
    p["html"] = dict(page["html"])
    for name, extra in html_add.items():
        p["html"][name] = p["html"][name].replace("</main>", extra + "</main>")
    return p


def edit(page: dict, name: str, old: str, new: str) -> dict:
    p = fresh(page)
    assert old in p["html"][name], old
    p["html"][name] = p["html"][name].replace(old, new)
    return p


def run(fn, tok, inputs, page):
    b, t, s, _ = inputs[tok]
    return fn(b, t, s, page)


def test_registry_carries_the_fifteen_s3_rows():
    s3 = [c for c in CHECKS if c.stage == "S3"]
    assert {c.entry_id for c in s3} == S3_IDS and len(CHECKS) == 82
    assert all(c.consumer == "report" and c.level_on_fail >= 2 for c in s3)


def test_det14cd(inputs):
    page = inputs["crvUSD"][3]
    assert "segments printed" in run(det_14cd, "crvUSD", inputs, fresh(page))
    with pytest.raises(Level3, match=r"DET-14\(d\)"):
        run(det_14cd, "crvUSD", inputs, edit(page, "index", "Checkable on-chain — 3.6%",
                                             "Checkable on-chain — 3.7%"))


def test_det17(inputs):
    page = inputs["GHO"][3]
    assert "three bars in order" in run(det_17, "GHO", inputs, fresh(page))
    with pytest.raises(Level3, match="reason string absent"):
        run(det_17, "GHO", inputs, edit(page, "index", "depth truncated at USCC;", "truncated;"))


def test_det18(inputs):
    assert "D = 0" in run(det_18, "LUSD", inputs, fresh(inputs["LUSD"][3]))
    page = inputs["crvUSD"][3]
    ok = "<p>disclosures 0.2 d on average; worst cbBTC 1 d, 6.1% of backing</p>"
    assert "D = 3" in run(det_18, "crvUSD", inputs, fresh(page, index=ok))
    with pytest.raises(Level3, match="worst weight"):
        run(det_18, "crvUSD", inputs, fresh(page, index=ok.replace(", 6.1% of backing", "")))


def test_det22_s3(inputs):
    page = inputs["LUSD"][3]
    ok = ("<table><tr><td>protocol stabilizer debt</td><td>0</td><td>0</td></tr>"
          "<tr><td>ceiling aggregate, the slice's upper bound</td><td>0</td><td>0</td></tr>"
          "</table>")
    assert "slice row" in run(det_22_s3, "LUSD", inputs, fresh(page, index=ok))
    with pytest.raises(Level3, match="protocol stabilizer debt"):
        run(det_22_s3, "LUSD", inputs, fresh(page, index=ok.replace("stabilizer", "stabiliser")))


def test_det29c(inputs):
    page = inputs["crvUSD"][3]
    line = ("<p>modeled pools: the largest pools covering 90% of the frozen set, which itself "
            "covered 95% of discovered on-Curve liquidity at freeze time (2026-09-04). "
            "K-subset share of the frozen set: 94.9%</p>")
    assert "one-liner printed" in run(det_29c, "crvUSD", inputs, fresh(page, index=line))
    with pytest.raises(Level3, match="one-liner"):
        run(det_29c, "crvUSD", inputs, fresh(page, index=line.replace("09-04", "09-05")))


def test_det36(inputs):
    page = inputs["crvUSD"][3]
    depth = sorted(_figures(fresh(page), "headline.m3.exit_depth"))[0]
    ok = (f"<p>exit liquidity {depth} — LP capital assumed sticky</p>"
          "<p>LP flight 0% / 30% / 60% — assumed scenario modifier, not data-derived</p>")
    assert run(det_36, "crvUSD", inputs, fresh(page, index=ok)) == "LP-flight lines printed"
    twice = ok + "<p>single-sided withdrawal of the paired asset</p>"
    with pytest.raises(Level3, match="2 times"):
        run(det_36, "crvUSD", inputs, fresh(page, index=twice))


def test_det53(inputs):
    page = inputs["LUSD"][3]
    assert "four literals present" in run(det_53, "LUSD", inputs, fresh(page))
    with pytest.raises(Level3, match="not rendered"):
        run(det_53, "LUSD", inputs, edit(page, "index", "Stability Pool refills (H3)",
                                         "Stability Pool refills"))


def test_det54(inputs):
    page = inputs["GHO"][3]
    ok = "<p>instant observation — nearly exact: Chainlink deviation triggers ≤ 1%</p>"
    assert run(det_54, "GHO", inputs, fresh(page, index=ok)) == "X = 100 bps"
    with pytest.raises(Level3, match="nearly-exact"):
        run(det_54, "GHO", inputs, fresh(page, index=ok.replace("≤ 1%", "≤ 0.5%")))


def test_det56(inputs):
    page = inputs["LUSD"][3]
    ok = ("<p>oracle manipulation out of scope — feed control reported under the admin-power "
          "surface</p><p>sequencer/infra risk n/a — mainnet only</p>")
    assert "printed" in run(det_56, "LUSD", inputs, fresh(page, index=ok))
    with pytest.raises(Level3, match="sequencer"):
        run(det_56, "LUSD", inputs, fresh(page, index=ok.replace(" — mainnet only", "")))


def test_det57(inputs):
    page = fresh(inputs["GHO"][3], index="<p>paired assets counted at 1.00 for depth</p>")
    assert run(det_57, "GHO", inputs, page) == "12 required IDs"
    bad = fresh(page)
    bad["table"] = copy.deepcopy(page["table"])
    bad["table"]["assumptions"] = [a for a in bad["table"]["assumptions"]
                                   if a["id"] != "gsm_fee_exit"]
    with pytest.raises(Level3, match="gsm_fee_exit"):
        run(det_57, "GHO", inputs, bad)


def test_det73(inputs):
    page = inputs["LUSD"][3]
    ok = "<p>audit status as of 2026-09-13</p>"
    assert "2 audits" in run(det_73, "LUSD", inputs, fresh(page, index=ok))
    with pytest.raises(Level3, match="counterparties literal not printed"):
        run(det_73, "LUSD", inputs, edit(fresh(page, index=ok), "index",
                                         "archetype #1 holds", "archetype holds"))


def test_det74(inputs):
    page = inputs["LUSD"][3]
    ok = "<p>audit and bounty tags dated 2026-09-13</p>"
    assert "class S absent" in run(det_74, "LUSD", inputs, fresh(page, index=ok))
    with pytest.raises(Level3, match="class D"):
        run(det_74, "LUSD", inputs, fresh(page))
    with pytest.raises(Level3, match=r"class S tag\(s\) still in the consumed sheet version "
                                     r"\['S1', 'S2'\]"):
        run(det_74, "crvUSD", inputs, fresh(inputs["crvUSD"][3], index=ok))


def test_det79_and_its_placeholder_case(inputs):
    page = inputs["LUSD"][3]
    clean = fresh(page)
    clean["html"] = {"index": "<main><p>supply 26,227,238.67</p></main>", "appendix": "<p></p>",
                     "verify": "<p></p>"}
    assert "0 matches" in run(det_79, "LUSD", inputs, clean)
    with pytest.raises(Level3, match=r"\[freeze date\]"):
        run(det_79, "LUSD", inputs, fresh(clean, index="<p>frozen on [freeze date]</p>"))
    with pytest.raises(Level3, match=r"index '\[slot:' x6"):         # the expected fail
        run(det_79, "LUSD", inputs, fresh(page))


def test_det88(inputs):
    page = inputs["crvUSD"][3]
    assert run(det_88, "crvUSD", inputs, fresh(page)).startswith("no grade")
    with pytest.raises(Level3, match="attribute"):
        run(det_88, "crvUSD", inputs, fresh(page, index='<span class="score">B+</span>'))


def test_det89(inputs):
    from factory.provenance import ContractRead
    b, t, s, page = inputs["crvUSD"]
    token = b.supply.reads["total_supply"].source_contract
    dec = ContractRead(source_contract=token, function="decimals()", args=[],
                       block=b.header.run_block)
    b2 = b.model_copy(update={"supply": b.supply.model_copy(
        update={"reads": {**b.supply.reads, "decimals": dec}})})
    clean = fresh(page)
    clean["html"] = {"index": "<p>supply 2,104,809,204.98 · $2.1B · backing 3.6%</p>",
                     "appendix": "<p></p>", "verify": '<pre class="sheet">0.500%</pre>'}
    assert "every figure a fmt output" in det_89(b2, t, s, clean)
    stray = fresh(clean)
    stray["html"] = {**clean["html"], "index": "<p>at 0.500% price impact</p>"}
    with pytest.raises(Level3, match=r"index:0\.500%"):
        det_89(b2, t, s, stray)
    with pytest.raises(Level3, match=r"no decimals\(\) read"):
        det_89(b, t, s, clean)


def test_run_report_checks_splits_the_stages(inputs):
    b, t, s, page = inputs["LUSD"]
    s3 = run_report_checks(b, t, s, fresh(page), stage="S3")
    assert {g.entry_id for g in s3} == S3_IDS
    assert {g.entry_id for g in s3 if g.result == "pass"} >= {"DET-14cd", "DET-17", "DET-53",
                                                              "DET-88"}


def test_routing_blocks_the_site_and_records_the_outcome(tmp_path):
    import shutil

    from factory.report.__main__ import build
    for sub in ("out/bundles", "out/trees", "out/stress", "out/raw", "out/logs", "config",
                "docs/context", "templates"):
        if (REPO / sub).exists():
            shutil.copytree(REPO / sub, tmp_path / sub)
    (tmp_path / "out/site/LUSD").mkdir(parents=True)
    (tmp_path / "out/site/LUSD/index.html").write_text("stale", encoding="utf-8")
    r = build(tmp_path, "LUSD")
    rec = r["record"]
    assert rec.outcome == "blocked_S3" and r["site"] is None
    assert len(rec.results) == 82 and [x.result for x in rec.results
                                       if x.entry_id == "DET-79"] == ["fail"]
    assert not (tmp_path / "out/site").exists()                  # withdrawn, then emptied
    stage = tmp_path / "out/rehearsal/LUSD/25970249"
    assert {p.name for p in stage.iterdir()} >= {"index.html", "appendix.html", "verify.html"}
    assert (stage.parent / "style.css").exists()
    ev = json.loads((stage / "data/evaluation-25970249.json").read_text(encoding="utf-8"))
    assert ev["outcome"] == "blocked_S3"
    assert record.GateRecord.model_validate(ev).outcome == "blocked_S3"


def test_print_rules_are_present():
    css = (REPO / "templates/style.css").read_text(encoding="utf-8")
    pr = css[css.index("@media print"):]
    for rule in (".tip, .tip-text { display: none !important; }",
                 "details > :not(summary) { display: none !important; }",
                 'summary::after { content: "full tables: appendix";',
                 'section:has(figure.tree), section:has(table.grid) { break-before: page; }',
                 '.pill.green::before { content: "ok: ";',
                 '.pill.amber::before { content: "caution: ";',
                 '.pill.red::before { content: "warning: ";',
                 ".pill { background: #fff !important; color: var(--ink) !important;"):
        assert rule in pr, rule
