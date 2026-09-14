"""B-13 tests: the generation / judge / remediation loop over recorded envelopes (plan §8;
K3, K4, K6 both cases, K8, refusal, the pass-2 green branch), the span post-check,
DET-80, DET-85 and the offline path. A fake client answers every call - no network."""

from __future__ import annotations

import json
import pathlib
import shutil

import pytest

from factory import eventlog
from factory.report import llm
from factory.report.__main__ import build
from factory.validate.harness import CHECKS, Level3, det_80, det_85
from tests.llm_fake import FIXTURES, FakeClient

REPO = pathlib.Path(__file__).resolve().parents[1]
LLM_ROWS = {f"LLM-0{i}" for i in range(1, 7)}


def tmp_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    for sub in ("out/bundles", "out/trees", "out/stress", "out/raw", "out/logs", "out/evaluation",
                "config", "docs/context", "templates"):
        if (REPO / sub).exists():
            shutil.copytree(REPO / sub, tmp_path / sub)
    for code in ("src/factory/report/render.py", "src/factory/report/svg.py"):
        (tmp_path / code).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / code, tmp_path / code)
    return tmp_path


def run(tmp_path, case: str, **kw):
    root = tmp_repo(tmp_path)
    fake = FakeClient(case)
    r = build(root, "LUSD", client=fake, **kw)
    return root, fake, r, r["record"]


def results(rec) -> dict[str, str]:
    return {x.entry_id: x.result for x in rec.results}


def test_fixtures_carry_the_current_prompt_hash():
    ph = llm.prompt_hash(REPO)
    for case in FIXTURES.iterdir():
        assert (case / "prompt_hash.txt").read_text(encoding="utf-8").strip() == ph, case.name


def test_k8_positive_control_publishes_with_its_flag(tmp_path):
    root, fake, r, rec = run(tmp_path, "k8_positive_control", extra_fired=(("T-22", 1),))
    assert rec.outcome == "published" and rec.revision_count == 0 and r["site"] is not None
    calls = fake.messages.calls
    assert calls.count("SlotProse") == 7 and calls.count("JudgeEnvelope") == 1
    assert all(v == "pass" for v in results(rec).values()) and len(rec.results) == len(CHECKS)
    page = (root / "out/site/LUSD/index.html").read_text(encoding="utf-8")
    assert 'data-section="exit liquidity"' in page and "off-venue share not computed" in page
    assert page.count('class="prose-slot"') == 7 and "[slot:" not in page
    log = eventlog.read(root / "out/logs/events_lusd.jsonl")
    assert log[-1].type == "published"
    assert not [e for _, e in eventlog.open_entries(log, "LUSD") if e.level > 1]   # T-28 resolved
    ev = [json.loads(x) for x in (root / "out/evaluation/LUSD/resolutions.jsonl")
          .read_text(encoding="utf-8").splitlines()]
    assert ev[-1]["resolution_type"] == "template_change" and ev[-1]["fire_value"] != \
        ev[-1]["resolution_value"]
    gens = [g for g in rec.generation if g.get("slot")]
    assert len(gens) == 7 and all(g["sampling"] is None and g["thinking"] == "adaptive"
                                  and g["prompt_hash"] == llm.prompt_hash(root) for g in gens)
    assert rec.judge[0]["model"] == llm.JUDGE_MODEL and gens[0]["model"] == llm.GENERATOR_MODEL


def test_pass2_green_publishes_with_one_revision(tmp_path):
    _root, fake, r, rec = run(tmp_path, "pass2_green")
    assert rec.outcome == "published" and rec.revision_count == 1
    assert rec.revision_cause == ["LLM-04"] and r["site"] is not None
    assert fake.messages.calls.count("JudgeEnvelope") == 2 and "Remediation" in fake.messages.calls


def test_k3_same_kind_and_section_twice_is_a_template_defect(tmp_path):
    _root, _fake, r, rec = run(tmp_path, "k3_template_defect")
    assert rec.outcome == "template_defect" and r["site"] is None and rec.revision_count == 1
    assert results(rec)["LLM-04"] == "fail"
    assert ("T-28", "LLM-04") in {(x["trigger"], x["source_entry"]) for x in rec.triggers}


def test_k6a_differing_findings_are_judge_instability(tmp_path):
    root, _fake, r, rec = run(tmp_path, "k6a_differing")
    assert rec.outcome == "judge_instability" and r["site"] is None
    assert ("T-24", "LLM-01") in {(x["trigger"], x["source_entry"]) for x in rec.triggers}
    log = eventlog.read(root / "out/logs/events_lusd.jsonl")
    assert any(e.type == "quarantine" and e.trigger == "T-24" for e in log)


def test_k6b_an_unlocated_span_is_discarded_and_is_judge_instability(tmp_path):
    _root, _fake, r, rec = run(tmp_path, "k6b_span_not_found")
    assert rec.outcome == "judge_instability" and r["site"] is None
    lost = [x for j in rec.judge for x in j.get("judge_span_not_found", [])]
    assert lost == [{"event": "judge_span_not_found", "criterion": "LLM-03",
                     "section_id": "finding", "paragraph_index": -1, "kind": "direct_negation"}]
    assert results(rec)["LLM-03"] == "pass"                     # the discarded defect is gone


@pytest.mark.parametrize("case,why", [("k4_malformed", "schema"), ("refusal", "refusal")])
def test_k4_and_refusal_error_the_llm_rows_and_block_with_t25(tmp_path, case, why):
    _root, _fake, r, rec = run(tmp_path, case)
    res = results(rec)
    assert {res[x] for x in LLM_ROWS} == {"error"} and res["DET-85"] == "fail"
    assert rec.outcome == "blocked_S3" and r["site"] is None and rec.revision_count == 0
    assert ("T-25", "DET-85") in {(x["trigger"], x["source_entry"]) for x in rec.triggers}
    assert why in rec.judge[0]["error"]


def test_a_run_without_llm_is_a_rehearsal(tmp_path):
    root = tmp_repo(tmp_path)
    log_before = (root / "out/logs/events_lusd.jsonl").read_bytes()
    rec_before = (root / "out/evaluation/LUSD/25974949.json").read_bytes()
    r = build(root, "LUSD")
    rec = r["record"]
    res = results(rec)
    assert res["DET-80"] == "fail" and {res[x] for x in LLM_ROWS} == {"error"}
    assert rec.outcome == "rehearsal" and rec.judge == [] and rec.generation == []
    assert not {x["trigger"] for x in rec.triggers} & {"T-25"} and r["log_lines"] == []
    assert (root / "out/logs/events_lusd.jsonl").read_bytes() == log_before
    assert (root / "out/evaluation/LUSD/25974949.json").read_bytes() == rec_before
    assert (root / "out/rehearsal/LUSD/25974949/evaluation-rehearsal-25974949.json").exists()
    assert r["site"] is None and not (root / "out/site").exists()


def test_post_check_keeps_located_spans_only():
    env = llm.JudgeEnvelope.model_validate(json.loads(
        (FIXTURES / "k6b_span_not_found/env1.json").read_text(encoding="utf-8")))
    sections = {"finding": ["Every LUSD in circulation is backed by ether locked in borrower "
                            "troves. More."]}
    for c in env.criteria:
        for d in c.defects:
            d.location.paragraph_index = 0
    kept, lost = llm.post_check(env, sections)
    assert [len(c.defects) for c in kept.criteria if c.defects] == [1]
    assert lost[0]["criterion"] == "LLM-03"


def test_slot_input_never_carries_the_bundle():
    doc = json.loads((REPO / "out/report/LUSD/25974949/table.json").read_text(encoding="utf-8"))
    spec = llm.prompts(REPO)["slots"]["structural_summary"]
    user = json.loads(llm.slot_input("structural_summary", spec, doc, {}, []))
    assert set(user) == {"token", "slot", "rows", "assumptions"}
    assert all(any(r["field_id"].startswith(p) for p in spec["prefixes"]) for r in user["rows"])


def test_det80_and_det85_units(tmp_path):
    root, _fake, r, rec = run(tmp_path, "k8_positive_control", extra_fired=(("T-22", 1),))
    html = (root / "out/site/LUSD/index.html").read_text(encoding="utf-8")
    mf = {"prose_slots": [{"id": x} for x in ("structural_summary", "verifiability_narrative",
                                              "member1_opening", "member2_opening",
                                              "flag_explanations", "counterfactual_explanations",
                                              "admin_surface_narrative")]}
    page = {"html": {"index": html}, "manifest": mf}
    assert det_80(None, None, None, page) == "7 slots present and bounded"
    gone = {"html": {"index": html.replace('data-slot="admin_surface_narrative"', 'data-slot="x"')},
            "manifest": mf}
    with pytest.raises(Level3, match="admin_surface_narrative"):
        det_80(None, None, None, gone)
    leak = html.replace("</main>", "<p>Every LUSD in circulation is backed by ether locked in "
                                   "borrower troves.</p></main>")
    with pytest.raises(Level3, match="outside its block"):
        det_80(None, None, None, {"html": {"index": leak}, "manifest": mf})
    prior = [{"entry_id": x.entry_id, "result": x.result, "scope_condition": None}
             for x in rec.results if x.entry_id not in ("DET-85", "DET-13")]
    assert "no error" in det_85(None, None, None, {"prior_results": prior})
    prior[0] = {**prior[0], "result": "error"}
    with pytest.raises(Level3, match="error on"):
        det_85(None, None, None, {"prior_results": prior})


def test_the_api_key_is_never_written(tmp_path):
    root, _fake, _r, _rec = run(tmp_path, "k8_positive_control", extra_fired=(("T-22", 1),))
    key_line = next((ln for ln in (REPO / ".env").read_text(encoding="utf-8").splitlines()
                     if ln.startswith("ANTHROPIC_API_KEY=")), "")
    key = key_line.split("=", 1)[1].strip() if key_line else ""
    if not key:
        pytest.skip("no key configured")
    for p in root.rglob("*"):
        if p.is_file() and p.suffix in (".json", ".jsonl", ".html", ".md"):
            assert key not in p.read_text(encoding="utf-8", errors="ignore"), p


def test_guard_reasks_once_then_publishes(tmp_path):
    _root, fake, r, rec = run(tmp_path, "k8_reask", extra_fired=(("T-22", 1),))
    assert rec.outcome == "published" and r["site"] is not None
    assert fake.messages.slot_calls["structural_summary"] == 2
    reasks = {g["slot"]: g["reasks"] for g in rec.generation if "reasks" in g}
    assert reasks["structural_summary"] == 1 and reasks["admin_surface_narrative"] == 0
    assert all(g["effort"] == "low" for g in rec.generation if "effort" in g)
    assert rec.judge[0]["effort"] == "medium"


def test_a_second_slip_leaves_the_slot_empty_and_det80_blocks(tmp_path):
    _root, fake, r, rec = run(tmp_path, "double_slip")
    assert fake.messages.slot_calls["structural_summary"] == 2
    bad = [g for g in rec.generation if g["slot"] == "structural_summary"]
    assert bad[0]["reasks"] == 1 and "guard failed" in bad[0]["error"]
    assert results(rec)["DET-80"] == "fail" and rec.outcome == "blocked_S3" and r["site"] is None


def test_an_invalid_item_errors_its_criterion_only(tmp_path):
    _root, _fake, r, rec = run(tmp_path, "invalid_item")
    res = results(rec)
    assert res["LLM-02"] == "error" and {res[x] for x in LLM_ROWS - {"LLM-02"}} == {"pass"}
    assert res["DET-85"] == "fail" and rec.outcome == "blocked_S3"
    assert "LLM-02" in rec.judge[0]["item_errors"]


def test_guard_and_labels_units():
    # previews ruling 1: DET-89's tokenizer - "Member-1" and dates are not figures
    p = llm.SlotProse(text="Supply is $26.2M; 1.0 day old; wstETH at 45.7% of 12.5% (Member-1).",
                      references_field_ids=["supply.supply_ruled"])
    rows = [{"field_id": "supply.supply_ruled", "printed": ["$26.2M", "26,227,238.67"]},
            {"field_id": "verif.staleness.worst.days", "printed": ["1.0 days"]},
            {"field_id": "d", "printed": ["12.5%"]}]
    # the fifth live run's ruling 1: a single-row number is filled, not missing
    assert llm.guard(p, rows) == {"numbers_not_printed": ["45.7%"]}   # "1.0 day" is "1.0 days"
    filled, added = llm.fill_references(p, rows)
    assert added == ["d", "verif.staleness.worst.days"]
    assert filled.references_field_ids == ["supply.supply_ruled", *added]
    two = rows + [{"field_id": "e", "printed": ["12.5%"]}]
    assert llm.guard(p, two) == {"numbers_not_printed": ["45.7%"],
                                 "missing_field_ids": ["d"]}
    assert llm.printed_by(p.text, two) == {"$26.2M": ["supply.supply_ruled"],
                                           "1.0 days": ["verif.staleness.worst.days"],
                                           "12.5%": ["d", "e"]}
    # previews ruling 4: the paragraph count
    assert llm.guard(llm.SlotProse(text="a\n\nb\n\nc", references_field_ids=[]), [],
                     (1, 2)) == {"paragraph_count": {"have": 3, "want": [1, 2]}}
    assert llm.paragraph_bounds({"paragraphs": "per_counterfactual_line"}, {"rows": [
        {"field_id": "headline.cf.H1_kill.value_primary"},
        {"field_id": "headline.cf.EMA_lag.description"}]}) == (2, 2)
    labels = {"m2_bad_debt": "bad debt"}
    assert llm.plain_label("headline.m2.bad_debt", "m2 bad debt", labels) == "bad debt"
    assert llm.plain_label("exit.curve.s0.005.s", "depth curve price impact", labels) == \
        "depth curve price impact"
    assert len(json.dumps(llm.JudgeEnvelope.model_json_schema())) < 3000   # ruling (A)


def test_judge_max_tokens_is_an_error_with_usage_kept(tmp_path):
    _root, fake, r, rec = run(tmp_path, "judge_max_tokens")
    res = results(rec)
    assert {res[x] for x in LLM_ROWS} == {"error"} and rec.outcome == "blocked_S3"
    j = rec.judge[0]
    assert "max_tokens" in j["error"] and j["stop_reason"] == "max_tokens"
    assert j["usage"]["input_tokens"] > 0 and j["model"] == llm.JUDGE_MODEL
    judge_req = next(q for q in fake.messages.requests if q["kind"] == "JudgeEnvelope")
    gen_req = next(q for q in fake.messages.requests if q["kind"] == "SlotProse")
    assert judge_req["max_tokens"] == 64000 and judge_req["effort"] == "medium"
    assert gen_req["effort"] == "low" and gen_req["thinking"] == {"type": "adaptive"}


def test_failed_generation_keeps_its_usage(tmp_path):
    _root, _fake, _r, rec = run(tmp_path, "double_slip")
    bad = next(g for g in rec.generation if g["slot"] == "structural_summary")
    assert len(bad["calls"]) == 2 and bad["usage"]["input_tokens"] > 0
    # ruling 2 on the fourth live run: both rejected answers are in the record
    assert [c["rejected"]["guard_violations"] for c in bad["calls"]][0]
    assert all("26.2 million" in c["rejected"]["text"] for c in bad["calls"])


def test_rulings_on_the_fourth_live_run():
    shape = '{"span_a":"a","section_a":"b","nature":"state_conflict","counterpart":%s}'
    assert llm.Item03.model_validate_json(shape % '{"span_b":"x","section_b":"y","figure_ref":"f"}')
    assert llm.Item03.model_validate_json(shape % '{"figure_ref":"f"}')
    with pytest.raises(ValueError):
        llm.Item03.model_validate_json(shape % '{"span_b":"x"}')
    assert llm.Item02.model_validate_json(
        '{"member":2,"rationale_present_at_open":true,"links_shock_to_mechanism":true,'
        '"names_token_mechanism":true,"first_result_sentence_span":null}')
    rubric = (REPO / "docs/context/rubic_v1.md").read_text(encoding="utf-8")
    assert "counterpart ∈ {span_b + section_b | figure_ref}" in llm.item_shapes(rubric)
    doc = json.loads((REPO / "out/report/crvUSD/25974925/table.json").read_text(encoding="utf-8"))
    bars = {r["field_id"]: r["value"] for r in doc["rows"] if r["field_id"].endswith(".bar")}
    wbtc = "tree.node.0x2260fac5e5542a773aa44fbcfedf7c193bc2c599.bar"
    assert bars[wbtc] == "disclosure_dependent"


def test_printed_forms_for_rulings_e_f_h():
    import tomllib

    from factory.report.render import Formatter
    mf = tomllib.loads((REPO / "templates/manifest.toml").read_text(encoding="utf-8"))
    f = Formatter(mf["display_rule"], mf["compact"])
    assert f("0.88", "price") == "0.88" and f(604800, "seconds") == "7 days"
    assert f(3600, "seconds") == "1 hour" and f(866, "seconds") == "866 s"
    assert f("1–7d", "literal") == "1–7 days"
    assert f(["0xc9332fdcb1c491dcc683bae86fe3cb70360738bc"], "list") == "0xc9332f…38bc"
    doc = json.loads((REPO / "out/report/crvUSD/25974925/table.json").read_text(encoding="utf-8"))
    w = tomllib.loads((REPO / "templates/wording.toml").read_text(encoding="utf-8"))
    user = json.loads(llm.slot_input("structural_summary",
                                     llm.prompts(REPO)["slots"]["structural_summary"], doc, {}, [],
                                     w))
    labels = {r["field_id"]: r["label"] for r in user["rows"]}
    assert labels["verif.bar.terminal"].startswith("backing held in assets")
    fam = [v for k, v in labels.items() if k.startswith("supply.family.")]
    assert any(v.startswith("crvUSD minted into controllers") for v in fam)


def test_rulings_on_the_sixth_live_run(tmp_path):
    from factory.report.__main__ import NOT_JUDGED
    # ruling 5: a deterministic S3 failure ends the pass with no judge call
    _root, fake, _r, rec = run(tmp_path / "a", "double_slip")
    assert "JudgeEnvelope" not in fake.messages.calls and results(rec)["DET-80"] == "fail"
    assert {x.result for x in rec.results if x.entry_id.startswith("LLM-")} == {"error"}
    assert rec.judge == [{"pass": 1, "error": NOT_JUDGED, "failing": ["DET-79", "DET-80"]}]
    # ruling 3: pass 2 regenerates only the slot carrying the pass-1 defect
    _root, fake, _r, rec = run(tmp_path / "b", "pass2_green")
    p2 = {g["slot"]: g for g in rec.generation if g["pass"] == 2}
    assert not p2["structural_summary"].get("carried")
    assert all(g.get("carried") for s, g in p2.items() if s != "structural_summary")
    assert fake.messages.slot_calls["structural_summary"] == 1      # pass 2 is a revision call
    revised = [q["slot"] for q in fake.messages.requests if q["kind"] == "SlotRevision"]
    assert revised == ["structural_summary"]
    assert fake.messages.slot_calls["admin_surface_narrative"] == 1
    # ruling 2 (c): a bare string counterpart reads as figure_ref; 6: the judge model
    item = llm.Item03.model_validate_json('{"span_a":"a","section_a":"b","nature":'
                                          '"state_conflict","counterpart":"figure_ref: x"}')
    assert item.counterpart.figure_ref == "figure_ref: x"
    assert llm.JUDGE_MODEL == "claude-opus-5" and rec.judge[0]["model"] == "claude-opus-5"


def test_ruling_a_on_the_seventh_live_run_and_the_preview(tmp_path):
    # pass 2 revises the defective slot against its own text and defects only
    _root, fake, _r, _rec = run(tmp_path / "a", "pass2_green")
    p2 = [q for q in fake.messages.requests if q["kind"] == "SlotRevision"
          and "pass1_text" in q["user_keys"]]
    assert [q["slot"] for q in p2] == ["structural_summary"] and p2[0]["pass1_defects"] == 1
    # the preview: generation only - no judge call, nothing written
    root = tmp_repo(tmp_path / "b")
    fake = FakeClient("k8_positive_control")
    before = sorted(p for p in (root / "out").rglob("*"))
    r = build(root, "LUSD", client=fake, preview=True)
    assert r["preview"] and len(r["generation"]) == 7
    assert "JudgeEnvelope" not in fake.messages.calls
    assert sorted(p for p in (root / "out").rglob("*")) == before


def test_run8_ruling_1a_defects_outside_prose_are_discarded():
    loc = {"section_id": "break", "paragraph_index": 0, "quoted_span": "no exit liquidity"}
    d = {"kind": "restates_only", "location": loc, "table_ref": None, "figure_ref": None,
         "reason": "r"}
    env = llm.JudgeEnvelope.model_validate({
        "rubric_version": "v1", "report_id": "x", "bundle_hash": "h", "judge_model": "m",
        "prompt_schema_version": "1", "overall_pass": False,
        "criteria": [{"id": c, "pass": False, "items": [], "defects": [d]}
                     for c in llm.LLM_IDS]})
    sections = {"break": ["template text: no exit liquidity is left"]}
    kept, dropped = llm.drop_outside_prose(env, sections, prose=set())
    assert [len(c.defects) for c in kept.criteria] == [0, 0, 1, 0, 0, 0]      # LLM-03 kept
    assert {x["criterion"] for x in dropped} == set(llm.LLM_IDS) - {"LLM-03"}
    html = '<div class="prose-slot" data-slot="s"><p>slot text here</p></div><p>template</p>'
    assert llm.prose_paragraphs(html) == {"slot text here"}


def test_final_spend_rulings(tmp_path):
    # pass 2 is span replacement only: the defect span is replaced, the rest kept verbatim
    _root, fake, _r, rec = run(tmp_path / "a", "pass2_green")
    p1 = next(g for g in rec.generation if g["pass"] == 1 and g["slot"] == "structural_summary")
    p2 = next(g for g in rec.generation if g["pass"] == 2 and g["slot"] == "structural_summary")
    assert p2["replacements"] and "Liquity troves, each opened by one borrower." in p2["text"]
    assert p2["text"].split(".", 1)[1] == p1["text"].split(".", 1)[1]
    assert "SlotRevision" in fake.messages.calls and rec.outcome == "published"
    # (7) the judge's table block is cached; (8) judge effort medium
    j = [q for q in fake.messages.requests if q["kind"] == "JudgeEnvelope"]
    assert j[0]["cache"] == [llm.JUDGE_CACHE] and j[0]["effort"] == "medium"
    # "N day" reads as "N days"
    from factory.validate.harness import _num_tokens
    assert _num_tokens("a 7 day delay, 7 days") == ["7 days", "7 days"]
    # the budget guard: no judge call when spent + 1.5 would exceed the budget
    root = tmp_repo(tmp_path / "b")
    fake = FakeClient("k8_positive_control")
    r = build(root, "LUSD", client=fake, budget=6.0, spent=5.0)
    assert "JudgeEnvelope" not in fake.messages.calls
    assert r["record"].judge[0]["error"] == "not judged: budget guard"
    assert r["record"].outcome == "blocked_S3"


def test_publish_without_banner_by_ruling(tmp_path):
    from factory.report.__main__ import BANNER, PILL_FLAGS, PLACEHOLDER, publish_without_banner
    root = tmp_repo(tmp_path)
    build(root, "crvUSD")                           # a rehearsal page set: banner, placeholders
    log_before = (root / "out/logs/events_crvusd.jsonl").read_bytes()
    stage = root / "out/rehearsal/crvUSD/25974925"
    staged = (stage / "index.html").read_text(encoding="utf-8")
    assert '<div class="banner quarantine">' in staged and "[slot:" in staged
    r = publish_without_banner(root, "crvUSD", "2026-09-14")
    site = root / "out/site/crvUSD"
    index = (site / "index.html").read_text(encoding="utf-8")
    assert r["removed"]["index.html"] == {"banner": 1, "placeholders": 7}
    # nothing else changes: banner and placeholders removed, the notices pill rebuilt
    expected = PLACEHOLDER.sub("", BANNER.sub("", staged))
    expected = PILL_FLAGS.sub(lambda m: r["pill"]["after"], expected, count=1)
    assert index == expected and "[slot:" not in index
    open_names = ("gate failure", "harness error", "judge instability")   # T-28, T-25, T-24
    assert all(x in r["pill"]["after"] for x in open_names)
    for n in ("appendix.html", "verify.html", "data/table.json"):
        assert (site / n).read_bytes() == (stage / n).read_bytes()
    rec = json.loads((root / "out/evaluation/crvUSD/25974925.json").read_text(encoding="utf-8"))
    pub = rec["publication"]
    assert rec["outcome"] == "published_without_banner_by_ruling" and pub["ruling"] == "P-7.11"
    assert pub["pill"]["note"] == "pill rebuilt from open entries" and pub["date"] == "2026-09-14"
    assert len(pub["placeholders_removed"]) == 7
    assert (root / "out/logs/events_crvusd.jsonl").read_bytes() == log_before
    assert (root / "out/site/style.css").exists()
