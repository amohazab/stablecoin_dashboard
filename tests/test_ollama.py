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
