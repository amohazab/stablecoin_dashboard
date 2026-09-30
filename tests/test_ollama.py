"""Step 8 phase B (P-8.04): the Ollama path. P2 (no Anthropic client, no key read), the
per-criterion output schemas against the rubric's printed shapes (F5), `_call` over two
recorded `/api/chat` bodies (F3), its fail-closed rules (Q6), A-22's scoped calls and computed
pass, A-23's `guard_verified` and the guard's percent substitution (Q8 (2)). No network."""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

import pytest

from factory.report import llm

REPO = pathlib.Path(__file__).resolve().parents[1]
OLLAMA = REPO / "tests" / "fixtures" / "ollama"
RUBRIC = (REPO / "docs/context/rubic_v1.md").read_text(encoding="utf-8")


class Replay:
    """Answers `chat(body)` with one recorded response, or a modified copy."""
    version, digest = "0.34.4", "sha256:recorded"

    def __init__(self, name: str | None = None, **override):
        rec = json.loads((OLLAMA / name).read_text(encoding="utf-8"))["response"] if name else {}
        self.resp = {**rec, **override}
        self.bodies: list[dict] = []

    def chat(self, body: dict) -> dict:
        self.bodies.append(body)
        return self.resp


class Down:
    version, digest = "0.34.4", "sha256:recorded"

    def chat(self, body: dict) -> dict:
        raise ConnectionError("connection refused")


def test_p2_no_anthropic_import_no_key_read_no_make_client():
    for f in (REPO / "src").rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(import|from)\s+anthropic", text, re.M), f
        assert "ANTHROPIC_API_KEY" not in text, f
    assert not hasattr(llm, "make_client")
    assert "anthropic" not in (REPO / "pyproject.toml").read_text(encoding="utf-8")
    # importing the report stage with --llm's client class loads no anthropic module
    code = ("import sys; import factory.report.__main__, factory.report.llm; "
            "assert 'anthropic' not in sys.modules")
    subprocess.run([sys.executable, "-c", code], check=True, cwd=REPO)


def test_item_models_match_the_rubric_printed_shapes():
    for cid, model in llm.ITEM_MODELS.items():
        shape = llm.printed_shape(RUBRIC, cid)
        body = shape[shape.index("`") + 2:shape.rindex("`") - 1]      # inside the outer braces
        parts, depth, cur = [], 0, ""
        for ch in body:                                             # split at depth-0 commas
            depth += (ch == "{") - (ch == "}")
            if ch == "," and depth == 0:
                parts, cur = [*parts, cur], ""
            else:
                cur += ch
        keys = [re.match(r"\s*([a-z_0-9]+)", x).group(1) for x in [*parts, cur]]
        assert keys == list(model.model_fields), (cid, keys)
        out = llm.CRITERION_OUT[cid].model_json_schema()
        assert set(out["properties"]) == {"items", "defects"}


def test_call_parses_the_recorded_generation_body_and_records_every_field():
    client = Replay("generation_lusd_member1.json")
    prose, meta = llm._call(client, kind="generate", system="s", user="u",
                            output=llm.SlotProse, phash="p")
    assert prose.text.startswith("A crash in collateral prices")
    body = client.bodies[0]
    assert body["think"] is False and body["stream"] is False
    assert body["format"] == llm.SlotProse.model_json_schema()
    assert body["options"] == {"num_ctx": 32768, "num_predict": 2000, "temperature": 0, "seed": 0}
    assert {k: meta[k] for k in ("model", "digest", "ollama_version", "think", "done_reason",
                                 "prompt_eval_count", "eval_count")} == {
        "model": "qwen3.5:9b", "digest": "sha256:recorded", "ollama_version": "0.34.4",
        "think": False, "done_reason": "stop", "prompt_eval_count": 10030, "eval_count": 307}
    assert meta["sampling"] == {"temperature": 0, "seed": 0} and "wall_s" in meta
    assert {"prompt_eval_duration", "eval_duration", "total_duration", "input_hash"} <= set(meta)


def test_call_parses_the_recorded_criterion_body_with_typed_items():
    out, meta = llm._call(Replay("llm01_lusd_finding.json"), kind="judge", system="s",
                          user="u", output=llm.CRITERION_OUT["LLM-01"], phash="p")
    assert len(out.items) == 7 and len(out.defects) == 4
    assert isinstance(out.items[0], llm.Item01) and meta["num_predict"] == 4000


@pytest.mark.parametrize("client,chars,match", [
    (Replay("generation_lusd_member1.json", done_reason="length"), 1, "done_reason length"),
    (Replay("generation_lusd_member1.json", prompt_eval_count=31000), 1, "prompt truncated"),
    (Replay("generation_lusd_member1.json"), 3 * 31000, "input too long"),
    (Down(), 1, "ollama call failed"),
    (Replay(message={"content": "not json"}, done_reason="stop", prompt_eval_count=1), 1,
     "schema validation failed"),
], ids=["length", "truncated", "too-long", "unreachable", "invalid"])
def test_call_fails_closed(client, chars, match):
    with pytest.raises(llm.LLMError, match=match) as e:
        llm._call(client, kind="generate", system="s", user="x" * chars, output=llm.SlotProse,
                  phash="p")
    assert e.value.calls and e.value.calls[0]["model"] == "qwen3.5:9b"


def test_an_unreachable_server_stops_the_client():
    with pytest.raises(llm.LLMError, match="unreachable"):
        llm.OllamaClient(base="http://127.0.0.1:9")


def _loc(span, kind="untraceable", ref=None):
    return llm.Defect(kind=kind, location=llm.Location(section_id="finding", paragraph_index=1,
                                                       quoted_span=span),
                      table_ref=ref, figure_ref=None, reason="r")


def test_a23_guard_verified():
    rows = [{"field_id": "stress.structural_zero.reason",
             "printed": ["first liquidation at an ETH shock of -81.63%; 72 troves"]},
            {"field_id": "tree.root.backing_value", "printed": ["$183.5M"]},
            {"field_id": "headline.m2.bad_debt", "printed": ["$0"]}]
    displays = {r["field_id"]: r["printed"] for r in rows}
    item = llm.Item01(quoted_span="$5", section_id="finding", claimed_value="$5",
                      claimed_object="bad debt", matched_field_id="headline.m2.bad_debt",
                      table_value="$0", match="mismatch")
    out = llm.CRITERION_OUT["LLM-01"](items=[item], defects=[
        _loc("$183.5M in backing"),               # printed by a slot row -> discarded
        _loc("-81.63%"),                          # F3's false defect, a signed figure: discarded
        _loc("72 troves"),                        # integers under 1,000 are not figures: kept
        _loc("$5"),                               # the planted figure: not printed -> kept
        _loc("$5", kind="mismatch"),              # its matched row prints "$0" -> kept
        _loc("$0", kind="mismatch", ref="headline.m2.bad_debt"),   # row prints it -> discarded
        _loc("$0", kind="wrong_denominator"),     # LLM-01 keeps denominators
        _loc("most of it")])                      # no number: kept
    keep, gone = llm.guard_verified("LLM-01", out, rows, displays)
    assert [d.location.quoted_span for d in keep] == ["72 troves", "$5", "$5", "$0", "most of it"]
    assert [(g["kind"], g["quoted_span"]) for g in gone] == [
        ("untraceable", "$183.5M in backing"), ("untraceable", "-81.63%"), ("mismatch", "$0")]
    keep, gone = llm.guard_verified("LLM-04", out, rows, displays)
    assert len(keep) == 8 and gone == []


def test_a_leading_minus_is_part_of_the_figure():
    from factory.validate.harness import _num_tokens
    assert _num_tokens("-81.63% and −50% of -$5; Member-1, -72 troves, 5.9 -> 1.1") == [
        "-81.63%", "−50%", "-$5", "5.9", "1.1"]


def test_identifiers_are_read_and_the_guard_rejects_them():
    text = ("The absence_read status and a fetchPrice call at run_block; crvUSD, wstETH, sUSDe, "
            "cbBTC, waEthUSDC and the PegKeepers are names; 0x3d32e8…5521 is an address; "
            "Member-1.")
    assert sorted(llm.identifiers(text)) == ["absence_read", "fetchPrice", "run_block"]
    bad = llm.guard(llm.SlotProse(text="The owner read is contract_read.",
                                  references_field_ids=[]), [])
    assert bad == {"identifiers": ["contract_read"]}


def test_an_identifier_costs_one_reask_then_publishes(tmp_path):
    import shutil

    from factory.report.__main__ import build
    from tests.llm_fake import FIXTURES, FakeClient
    from tests.test_b13 import tmp_repo
    case = tmp_path / "case"
    shutil.copytree(FIXTURES / "k8_positive_control", case)
    gen = json.loads((case / "generation.json").read_text(encoding="utf-8"))
    first = {"admin_surface_narrative": {**gen["admin_surface_narrative"],
             "text": gen["admin_surface_narrative"]["text"] + " The status is absence_read."}}
    (case / "generation_first.json").write_text(json.dumps(first), encoding="utf-8")
    fake = FakeClient("k8_positive_control")
    fake.dir = case
    r = build(tmp_repo(tmp_path / "repo"), "LUSD", client=fake)
    g = next(x for x in r["record"].generation if x["slot"] == "admin_surface_narrative")
    assert g["reasks"] == 1 and fake.slot_calls["admin_surface_narrative"] == 2
    assert g["rejected"][0]["guard_violations"] == {"identifiers": ["absence_read"]}
    assert r["record"].outcome == "published"


def test_admin_rows_reach_the_generator_in_plain_words():
    import tomllib
    doc = json.loads((REPO / "out/report/LUSD/26052560/table.json").read_text(encoding="utf-8"))
    w = tomllib.loads((REPO / "templates/wording.toml").read_text(encoding="utf-8"))
    spec = llm.prompts(REPO)["slots"]["admin_surface_narrative"]
    rows = {r["field_id"]: r for r in json.loads(llm.slot_input(
        "admin_surface_narrative", {**spec, "owners": [], "max_entities_per_group": None}, doc, {},
        [], w))["rows"]}
    assert rows["admin.mint.None.holder_type"]["label"] == "minting: who holds it"
    assert rows["admin.mint.None.holder_type"]["printed"] == ["no one holds this power"]
    assert rows["admin.mint.None.delay_bucket"]["printed"] == ["no delay"]
    assert rows["admin.mint.None.A8"]["printed"] == [w["evidence"]["absence_read"]]
    blob = json.dumps([{k: r[k] for k in ("label", "value", "printed")} for r in rows.values()])
    assert "absence_read" not in blob and "contract_read" not in blob and "bucket" not in blob


def test_the_guard_rejects_em_and_en_dashes():
    bad = llm.guard(llm.SlotProse(text="Supply is steady \u2014 and 1\u20137 days.",
                                  references_field_ids=[]), [])
    assert bad["dashes"] == ["\u2013", "\u2014"]
    assert "dashes" not in llm.guard(llm.SlotProse(text="Supply is steady, and holds.",
                                                   references_field_ids=[]), [])


def test_a_dash_costs_one_reask_then_publishes(tmp_path):
    import shutil

    from factory.report.__main__ import build
    from tests.llm_fake import FIXTURES, FakeClient
    from tests.test_b13 import tmp_repo
    case = tmp_path / "case"
    shutil.copytree(FIXTURES / "k8_positive_control", case)
    gen = json.loads((case / "generation.json").read_text(encoding="utf-8"))
    first = {"admin_surface_narrative": {**gen["admin_surface_narrative"],
             "text": gen["admin_surface_narrative"]["text"] + " Nothing changes \u2014 ever."}}
    (case / "generation_first.json").write_text(json.dumps(first), encoding="utf-8")
    fake = FakeClient("k8_positive_control")
    fake.dir = case
    r = build(tmp_repo(tmp_path / "repo"), "LUSD", client=fake)
    g = next(x for x in r["record"].generation if x["slot"] == "admin_surface_narrative")
    assert g["reasks"] == 1 and g["rejected"][0]["guard_violations"] == {"dashes": ["\u2014"]}
    assert r["record"].outcome == "published"


def test_percent_substitution_carries_the_printed_form():
    rows = [{"field_id": "a", "printed": ["5.0%"]}, {"field_id": "b", "printed": ["25.0%"]}]
    text, subs = llm.substitute_percents("a 5% fall and 25% of 5.0%", rows)
    assert text == "a 5.0% fall and 25.0% of 5.0%"
    assert subs == [{"from": "25%", "to": "25.0%"}, {"from": "5%", "to": "5.0%"}]
    assert llm.guard(llm.SlotProse(text=text, references_field_ids=[]), rows) == {}
    two = rows + [{"field_id": "c", "printed": ["5.00%"]}]
    assert llm.substitute_percents("a 5% fall", two) == ("a 5% fall", [])    # ambiguous: none


def test_judge_calls_are_scoped_subsets_and_pass_is_computed():
    sections = {"finding": ["p0", "p1"], "backing": ["b0"], "exit-liquidity": ["e0", "e1"],
                "oracle": ["o0"], "counterfactuals": ["c0"], "admin": ["a0"]}
    slots = llm.prompts(REPO)["slots"]
    users = {s: json.dumps({"token": "T", "slot": s, "rows": [
        {"field_id": f"{s}.x", "printed": ["$1.0M"]},
        {"field_id": "headline.cf.EMA_lag.value", "printed": ["1.2"]}], "assumptions": [],
        **({"open_level1_flags": [{"entry_id": "T:1"}]} if s == "flag_explanations" else {})})
        for s in slots}
    prose = {s: "text" for s in slots}
    calls = llm.judge_calls(sections, users, prose, slots)
    by = [(c["criterion"], c["scope"]) for c in calls]
    assert by[0] == ("LLM-03", "page") and len(calls) == 19
    assert sum(1 for c, _ in by if c == "LLM-01") == 7 and ("LLM-06", "member2_opening") in by
    l01 = next(c for c in calls
               if c["criterion"] == "LLM-01" and c["scope"] == "admin_surface_narrative")
    assert l01["page"] == "## section_id: admin\n[0] a0" and "rows" in l01["body"]
    assert "rows" not in calls[0]["body"] and "## section_id: admin" in calls[0]["page"]
    l05 = next(c for c in calls if c["criterion"] == "LLM-05")
    assert [r["field_id"] for r in l05["body"]["rows"]] == ["headline.cf.EMA_lag.value"]
    assert l05["body"]["open_level1_flags"] == [{"entry_id": "T:1"}]
    env = llm.JudgeEnvelope(rubric_version="v1", report_id="r", bundle_hash="h",
                            judge_model="m", prompt_schema_version="1", overall_pass=False,
                            criteria=[llm.Criterion(id=c, items=[], defects=[], **{"pass": False})
                                      for c in llm.LLM_IDS])
    done = llm.computed_pass(env, {})
    assert done.overall_pass and all(c.pass_ for c in done.criteria)
    assert not llm.computed_pass(env, {"LLM-02": "x"}).overall_pass


def test_code_words_leave_no_identifier_in_any_slot_input():
    # P-8.07 (b'): every code name in a label, value, printed form or assumption id is worded
    import tomllib

    from factory.report.__main__ import row_displays
    w = tomllib.loads((REPO / "templates/wording.toml").read_text(encoding="utf-8"))
    spec = llm.prompts(REPO)["slots"]
    left = set()
    for t, b in (("crvUSD", 26053560), ("GHO", 26053568), ("LUSD", 26052560)):
        doc = json.loads((REPO / f"out/report/{t}/{b}/table.json").read_text(encoding="utf-8"))
        d = row_displays(REPO, doc)
        for slot in spec:
            u = json.loads(llm.slot_input(slot, {**spec[slot], "owners": [],
                                                 "max_entities_per_group": None}, doc, d, [], w))
            for r in u["rows"]:
                left |= set(llm.identifiers(json.dumps([r["label"], r["value"], r["printed"]],
                                                       ensure_ascii=False)))
            left |= {i for a in u["assumptions"] for i in llm.identifiers(a["id"])}
    assert left == set()


class _Paras:
    """Answers each generation call with the next queued text."""
    version, digest = "0", "sha256:x"

    def __init__(self, texts):
        self.texts = list(texts)

    def chat(self, body):
        return {"message": {"content": json.dumps({"text": self.texts.pop(0),
                                                   "references_field_ids": []})},
                "done_reason": "stop", "prompt_eval_count": 10, "eval_count": 5}


def test_generate_parts_joins_one_paragraph_per_part_and_fails_closed():
    users = [json.dumps({"rows": [], "part": {"line": x}}) for x in ("A", "B")]
    out, meta = llm.generate_parts("counterfactual_explanations", users, _Paras(["one.", "two."]),
                                   REPO, "obligations")
    assert out.text == "one.\n\ntwo." and [p["part"]["line"] for p in meta["parts"]] == ["A", "B"]
    assert meta["sampling"] == {"temperature": 0, "seed": 0} and len(meta["calls"]) == 2
    with pytest.raises(llm.LLMError, match="part 2 of 2") as e:       # 2 paragraphs, twice
        llm.generate_parts("counterfactual_explanations", users,
                           _Paras(["one.", "a.\n\nb.", "a.\n\nb."]), REPO, "obligations")
    assert len(e.value.calls) == 3


def test_a_length_stop_keeps_its_content():
    client = Replay(message={"content": '{"text": "loop loop'}, done_reason="length",
                    prompt_eval_count=10)
    with pytest.raises(llm.LLMError, match="length") as e:
        llm._call(client, kind="generate", system="s", user="u", output=llm.SlotProse, phash="p")
    assert e.value.calls[0]["rejected"]["text"] == '{"text": "loop loop'


def test_split_slots_run_one_call_per_part_through_the_report_stage(tmp_path):
    from factory.report.__main__ import build
    from tests.llm_fake import FakeClient
    from tests.test_b13 import tmp_repo
    fake = FakeClient("k8_positive_control")
    r = build(tmp_repo(tmp_path), "LUSD", client=fake, extra_fired=(("T-22", 1),))
    gen = {g["slot"]: g for g in r["record"].generation}
    assert [p["part"]["line"] for p in gen["counterfactual_explanations"]["parts"]] == \
        ["Tellor_fallback"]
    assert len(gen["flag_explanations"]["parts"]) == 1
    assert fake.slot_calls["counterfactual_explanations"] == 1
    assert r["record"].outcome == "published"


def test_the_entity_cap_keeps_whole_entities_and_exempts_admin_and_member2():
    import tomllib

    from factory.report.__main__ import row_displays
    w = tomllib.loads((REPO / "templates/wording.toml").read_text(encoding="utf-8"))
    spec = llm.prompts(REPO)["slots"]
    assert "max_entities_per_group" not in spec["admin_surface_narrative"]
    assert "max_entities_per_group" not in spec["member2_opening"]
    assert spec["verifiability_narrative"]["max_entities_per_group"] == 8
    doc = json.loads((REPO / "out/report/GHO/26053568/table.json").read_text(encoding="utf-8"))
    u = json.loads(llm.slot_input("verifiability_narrative",
                                  {**spec["verifiability_narrative"], "owners": []}, doc,
                                  row_displays(REPO, doc), [], w))
    nodes = {r["field_id"].rsplit(".", 1)[0] for r in u["rows"]
             if r["field_id"].startswith("tree.node.")}
    assert len(nodes) == 8 and all(f"{n}.bar" in {r["field_id"] for r in u["rows"]} for n in nodes)


def test_the_generator_copy_carries_no_spaced_dash_and_the_page_keeps_its_literals():
    import tomllib

    from factory.report.__main__ import row_displays
    rows = [{"label": "a — b", "value": ["x – y", 3], "printed": ["p — q", "—"]},
            {"label": "c", "value": "—", "printed": ["—"]}]
    llm.undash(rows)
    assert rows == [{"label": "a, b", "value": ["x, y", 3], "printed": ["p, q", "none"]},
                    {"label": "c", "value": "none", "printed": ["none"]}]
    w = tomllib.loads((REPO / "templates/wording.toml").read_text(encoding="utf-8"))
    doc = json.loads((REPO / "out/report/LUSD/26060799/table.json").read_text(encoding="utf-8"))
    spec = llm.prompts(REPO)["slots"]
    for slot in spec:
        u = llm.slot_input(slot, {**spec[slot], "owners": []}, doc, row_displays(REPO, doc), [], w)
        assert "—" not in u and " – " not in u, slot        # no U+2014 at all
    banner = next(r for r in doc["rows"] if r["field_id"] == "verif.banner")
    assert banner["value"] == "No admin power can alter backing — immutable."   # untouched
