"""B-13 (P-7.01 R12; rubric 2.1, 2.2): the generation, judge and remediation calls.

Every call goes through `client.messages.parse(..., output_format=<Pydantic type>)`
(anthropic 1.5.0: the type becomes `output_config={"format": {"type": "json_schema",
...}}`; the parsed object is `response.parsed_output`). The client is injected: the
report stage builds one only when asked to call the API (`--llm`), and the tests pass
a fake that returns recorded JSON through the same models - the suite never touches
the network.

Recorded per call (Amin, 2026-09-14): model, thinking `adaptive`, effort `default`,
sampling `null` (A-18), the prompt hash, the input hash, stop reason and the API's own
usage counts. `ANTHROPIC_API_KEY` is read like `ETH_RPC_URL` (environment, then
`.env`) and never written to any artifact, record, log or fixture.

NAMED DEFAULTS (B-13): one generation call per slot; the judge sees index.html's text
split by section `id` into numbered paragraphs, plus table.json; a defect whose
`quoted_span` is not in the paragraph it names is discarded and recorded as
`judge_span_not_found`; a refusal, a missing parse or a schema-invalid response is an
`LLMError`, which the LLM rows record as `error` (DET-85).
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import tomllib
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

JUDGE_MODEL = "claude-opus-5"   # Amin, sixth live run, ruling 6 (runs 3-6: claude-fable-5-1)
GENERATOR_MODEL = "claude-sonnet-5"
THINKING = {"type": "adaptive"}
CALL_RECORD = {"thinking": "adaptive", "sampling": None}
EFFORT = {"generate": "low", "judge": "medium", "remediate": None}   # None = model default
# Amin, 2026-09-14 (final spend): judge effort "medium" (8); the judge's table block is
# cached (7) - NAMED DEFAULT: TTL 1 h, since pass 2's judgment starts more than five
# minutes after pass 1's (a pass-1 judgment alone streams for about five).
JUDGE_CACHE = {"type": "ephemeral", "ttl": "1h"}
# $ per MTok (input, output); a 1-h cache write is 2x input, a cache read 0.1x input.
PRICE = {"claude-sonnet-5": (2, 10), "claude-fable-5-1": (10, 50), "claude-opus-5": (5, 25)}


def call_cost(model: str, usage: dict | None) -> float:
    u = usage or {}
    i, o = PRICE[model]
    return ((u.get("input_tokens") or 0) * i + (u.get("output_tokens") or 0) * o
            + (u.get("cache_creation_input_tokens") or 0) * i * 2
            + (u.get("cache_read_input_tokens") or 0) * i * 0.1) / 1e6
# Ruling (D): every call streams, so the judge's ceiling is 64,000 (the SDK refuses a
# non-streaming call above 21,333).
MAX_TOKENS = {"generate": 8000, "judge": 64000, "remediate": 8000}
LLM_IDS = ("LLM-01", "LLM-02", "LLM-03", "LLM-04", "LLM-05", "LLM-06")


class LLMError(Exception):
    """A call that did not yield a parsed, schema-valid object. `calls` carries the usage
    and stop reason of every API call made before the failure (ruling G)."""

    def __init__(self, message: str, calls: list[dict] | None = None):
        super().__init__(message)
        self.calls = calls or []


# ---- output schemas ----------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SlotProse(_Strict):
    text: str
    references_field_ids: list[str]


class SpanReplacement(_Strict):
    quoted_span: str
    replacement: str


class SlotRevision(_Strict):
    """Amin, 2026-09-14: pass 2 is span replacement only - each replacement names a defect's
    quoted span in the slot's pass-1 text and the text that takes its place."""

    replacements: list[SpanReplacement]
    references_field_ids: list[str]


class Location(_Strict):
    section_id: str
    paragraph_index: int
    quoted_span: str


class Defect(_Strict):
    kind: str
    location: Location
    table_ref: str | None
    figure_ref: str | None
    reason: str


class Item01(_Strict):
    quoted_span: str
    section_id: str
    claimed_value: str
    claimed_object: str
    matched_field_id: str | None
    table_value: str | None
    match: Literal["exact", "rounded_ok", "approximate_ok", "mismatch", "wrong_denominator",
                   "untraceable"]


class Item02(_Strict):
    # Amin's ruling on the third live run, defect 2 (a): the rubric prints `member`
    # untyped and owns the shape, so both an int and a string are the printed schema.
    member: int | str
    rationale_present_at_open: bool
    links_shock_to_mechanism: bool
    names_token_mechanism: bool
    first_result_sentence_span: str | None


class Counterpart(_Strict):
    """Ruling 4 on the fourth live run, the recorded reading: the rubric's `span_b +
    section_b | figure_ref` means at least one of the pair and the figure; both present is
    valid. NAMED DEFAULT: the pair is span_b and section_b together or neither."""

    span_b: str | None = None
    section_b: str | None = None
    figure_ref: str | None = None

    @model_validator(mode="after")
    def _at_least_one(self):
        pair = (self.span_b is not None, self.section_b is not None)
        if pair[0] != pair[1]:
            raise ValueError("span_b and section_b come together")
        if not pair[0] and self.figure_ref is None:
            raise ValueError("counterpart needs span_b + section_b, figure_ref, or both")
        return self


class Item03(_Strict):
    # defect 2 (a): the rubric's `counterpart ∈ {span_b + section_b | figure_ref}`, as printed.
    span_a: str
    section_a: str
    counterpart: Counterpart
    nature: Literal["direct_negation", "magnitude_conflict", "direction_conflict", "state_conflict"]

    @field_validator("counterpart", mode="before")
    @classmethod
    def _bare_string(cls, v):
        # sixth live run, ruling 2 (c), the recorded reading: a bare string is a figure_ref
        return {"figure_ref": v} if isinstance(v, str) else v


class Item04(_Strict):
    slot_id: str
    token_specific: bool
    references_field_ids: list[str]
    generic_spans: list[str]


class Item05(_Strict):
    item_id: str
    section_id: str
    explained: Literal["adequate", "restates_only", "absent", "wrong"]
    explanation_span: str | None
    reason: str


class Item06(_Strict):
    applicable: bool
    negation_spans: list[str]
    positive_framing: bool
    curve_referenced: bool
    m4_referenced: bool


ITEM_MODELS = dict(zip(LLM_IDS, (Item01, Item02, Item03, Item04, Item05, Item06), strict=True))


class Criterion(_Strict):
    """Rubric 2.1's criterion. Amin's ruling (A) a1, 2026-09-14: `items` travel as JSON
    strings - the typed union compiled to a grammar the API refused - and each is
    validated after parsing against its criterion's printed schema (`ITEM_MODELS`)."""

    id: Literal["LLM-01", "LLM-02", "LLM-03", "LLM-04", "LLM-05", "LLM-06"]
    pass_: bool = Field(alias="pass")
    items: list[str]
    defects: list[Defect]


def item_errors(env: JudgeEnvelope) -> dict[str, str]:
    """`{criterion id: reason}` for every criterion with an item that is not JSON or not
    its printed schema - an invalid item is `error` on that criterion's row."""
    out = {}
    for c in env.criteria:
        for i, raw in enumerate(c.items):
            try:
                ITEM_MODELS[c.id].model_validate(json.loads(raw))
            except Exception as exc:                       # JSON or schema
                out[c.id] = f"item {i}: {type(exc).__name__}: {str(exc)[:160]}"
                break
    return out


class JudgeEnvelope(_Strict):
    """Rubric 2.1's envelope, field for field."""

    rubric_version: str
    report_id: str
    bundle_hash: str
    judge_model: str
    prompt_schema_version: str
    criteria: list[Criterion]
    overall_pass: bool


class Addressed(_Strict):
    defect_index: int
    addressed: Literal["yes", "no"]
    reason: str


class Remediation(_Strict):
    items: list[Addressed]


# ---- prompts, hashes, the page as the judge reads it -----------------------------------------


def prompts(repo: pathlib.Path) -> dict[str, Any]:
    tpl = repo / "templates/prompts"
    return {"generate": (tpl / "generate.md").read_text(encoding="utf-8"),
            "judge": (tpl / "judge.md").read_text(encoding="utf-8"),
            "remediate": (tpl / "remediate.md").read_text(encoding="utf-8"),
            "revise": (tpl / "revise.md").read_text(encoding="utf-8"),
            "slots": tomllib.loads((tpl / "slots.toml").read_text(encoding="utf-8"))["slot"]}


def sha(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8") + b"\0")
    return h.hexdigest()


def prompt_hash(repo: pathlib.Path) -> str:
    """One hash over the three prompt files, the slot table, the three schemas and the six
    typed item schemas (shown to the judge since the sixth live run) - the value recorded
    beside every recorded fixture (a prompt edit visibly stales them)."""
    tpl = repo / "templates/prompts"
    files = [(tpl / n).read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
             for n in ("generate.md", "judge.md", "remediate.md", "revise.md", "slots.toml")]
    schemas = [json.dumps(m.model_json_schema(), sort_keys=True)
               for m in (SlotProse, SlotRevision, JudgeEnvelope, Remediation,
                         *ITEM_MODELS.values())]
    return sha(*files, *schemas)


def rubric_criteria(rubric_text: str) -> str:
    """LLM-01...LLM-06 verbatim from the rubric (one owner: the judge prompt inserts them)."""
    out = []
    for cid in LLM_IDS:
        m = re.search(rf"^\*\*{cid} .*?(?=^\s*$)", rubric_text, re.M | re.S)
        if m is None:
            raise LLMError(f"rubric entry {cid} not found")
        out.append(m.group(0).strip())
    return "\n\n".join(out)


def item_shapes(rubric_text: str) -> str:
    """Ruling 4 on the fourth live run: each criterion's printed item shape, verbatim (the
    rubric's `Schema ...: `{...}`` span), one line per criterion."""
    crit = rubric_criteria(rubric_text).split("\n\n")
    out = []
    for cid, text in zip(LLM_IDS, crit, strict=True):
        m = re.search(r"Schema[^`]*`[^`]*`", text)
        if m is None:
            raise LLMError(f"rubric entry {cid}: no printed item shape")
        typed = json.dumps(ITEM_MODELS[cid].model_json_schema(), ensure_ascii=False,
                           separators=(",", ":"))
        # sixth live run, ruling 2 (b): the typed item schema beside the rubric's shape
        out.append(f"- {cid}: {m.group(0)}\n  typed item schema: {typed}")
    return "\n".join(out)


def defects_by_slot(defects: list[dict], prose: dict[str, str], sections: dict[str, str]
                    ) -> dict[str, list[dict]]:
    """Sixth live run, ruling 3 (NAMED DEFAULT, accepted on the seventh): each pass-1 defect
    lands on the slot whose pass-1 text holds its quoted span, else on every slot rendering
    in its section. Pass 2 revises only these slots, each against its own defects; the rest
    carry verbatim."""
    out: dict[str, list[dict]] = {}
    for d in defects:
        loc = d["location"]
        own = {s for s, text in prose.items() if text and loc["quoted_span"] in text}
        for s in sorted(own or {s for s, sec in sections.items() if sec == loc["section_id"]}):
            out.setdefault(s, []).append(d)
    return out


_TAG = re.compile(r'<(/?)(section|details)\b([^>]*)>')
_ID = re.compile(r'\bid="([^"]+)"')


def _id_blocks(html: str) -> list[tuple[str, str]]:
    """`(id, inner html)` for every section/details carrying an id, nesting-safe."""
    stack: list[tuple[str, str | None, int]] = []
    out = []
    for m in _TAG.finditer(html):
        closing, tag, attrs = m.group(1), m.group(2), m.group(3)
        if not closing:
            idm = _ID.search(attrs)
            stack.append((tag, idm.group(1) if idm else None, m.end()))
            continue
        for i in range(len(stack) - 1, -1, -1):
            if stack[i][0] == tag:
                _t, sid, start = stack[i]
                del stack[i:]
                if sid:
                    out.append((sid, html[start:m.start()]))
                break
    order = {sid: html.find(f'id="{sid}"') for sid, _ in out}
    return sorted(out, key=lambda x: order[x[0]])


def page_sections(html: str) -> dict[str, list[str]]:
    """`{section id: [paragraph text, ...]}` - the numbering the judge cites and the
    post-check reads. A paragraph is a p, li, table row, heading, summary or caption."""
    from factory.validate.harness import _elements
    out: dict[str, list[str]] = {}
    for sid, body in _id_blocks(html):
        paras = [e for e in _elements(body) if e]
        seen, keep = set(), []
        for e in paras:                              # nested elements repeat their text
            if e not in seen and not any(e != k and e in k for k in paras):
                keep.append(e)
                seen.add(e)
        out[sid] = keep
    return out


def page_text(sections: dict[str, list[str]]) -> str:
    return "\n\n".join(f"## section_id: {sid}\n" + "\n".join(f"[{i}] {p}" for i, p in
                                                             enumerate(paras))
                       for sid, paras in sections.items())


def post_check(env: JudgeEnvelope, sections: dict[str, list[str]]
               ) -> tuple[JudgeEnvelope, list[dict]]:
    """Discard every defect whose span is not verbatim in the paragraph it names."""
    lost = []
    crit = []
    for c in env.criteria:
        keep = []
        for d in c.defects:
            paras = sections.get(d.location.section_id, [])
            i = d.location.paragraph_index
            span = d.location.quoted_span
            if 0 <= i < len(paras) and span and span in paras[i]:
                keep.append(d)
            else:
                lost.append({"event": "judge_span_not_found", "criterion": c.id,
                             "section_id": d.location.section_id, "paragraph_index": i,
                             "kind": d.kind})
        crit.append(c.model_copy(update={"defects": keep}))
    return env.model_copy(update={"criteria": crit}), lost


def prose_paragraphs(html: str) -> set[str]:
    """The text of every paragraph inside a rendered `prose-slot` block (DET-80's blocks)."""
    from factory.validate.harness import PROSE_BLOCK, _elements
    return {e for _slot, body in PROSE_BLOCK.findall(html) for e in _elements(body) if e}


def drop_outside_prose(env: JudgeEnvelope, sections: dict[str, list[str]], prose: set[str]
                       ) -> tuple[JudgeEnvelope, list[dict]]:
    """Amin, run 8 ruling 1 (a): judge.md's "judge only prose", enforced - a defect whose
    paragraph is not a prose-slot paragraph is discarded for every criterion but LLM-03
    (which compares prose with template text). Run after `post_check`; the discards are
    recorded as `outside_prose`, not as `judge_span_not_found`."""
    dropped, crit = [], []
    for c in env.criteria:
        keep = []
        for d in c.defects:
            paras = sections.get(d.location.section_id, [])
            para = paras[d.location.paragraph_index]
            if c.id == "LLM-03" or para in prose:
                keep.append(d)
            else:
                dropped.append({"event": "outside_prose", "criterion": c.id,
                                "section_id": d.location.section_id,
                                "paragraph_index": d.location.paragraph_index,
                                "kind": d.kind, "quoted_span": d.location.quoted_span})
        crit.append(c.model_copy(update={"defects": keep}))
    return env.model_copy(update={"criteria": crit}), dropped


# ---- the calls ----------------------------------------------------------------------------


def make_client(repo: pathlib.Path):
    from anthropic import Anthropic

    from factory.logs_pointer import env
    key = env(repo, "ANTHROPIC_API_KEY")
    if not key:
        raise LLMError("ANTHROPIC_API_KEY is not set (environment or .env)")
    return Anthropic(api_key=key)


def _call(client, *, model: str, max_tokens: int, system: str, user: str | list, output: type,
          phash: str, effort: str | None = None) -> tuple[Any, dict]:
    """One streamed call (ruling D): the JSON schema goes as `output_config.format` (the
    SDK's own `transform_schema`), the final message's text is validated here, and the
    usage and stop reason are recorded on every path - a `max_tokens` stop, a refusal or
    an invalid text is an `LLMError` that carries them."""
    from anthropic.lib._parse._transform import transform_schema
    meta = {"model": model, **CALL_RECORD, "effort": effort or "default", "prompt_hash": phash,
            "input_hash": sha(system, user if isinstance(user, str) else json.dumps(user)),
            "stop_reason": None, "usage": None}
    if not isinstance(user, str):
        meta["cache"] = [b.get("cache_control") for b in user if b.get("cache_control")]
    config: dict = {"format": {"type": "json_schema", "schema": transform_schema(output)}}
    if effort:
        config["effort"] = effort
    try:
        with client.messages.stream(model=model, max_tokens=max_tokens, system=system,
                                    thinking=THINKING, output_config=config,
                                    messages=[{"role": "user", "content": user}]) as stream:
            msg = stream.get_final_message()
    except Exception as exc:                          # transport, request refused
        raise LLMError(f"{type(exc).__name__}: {exc}"[:300], [meta]) from exc
    usage = getattr(msg, "usage", None)
    meta.update(stop_reason=getattr(msg, "stop_reason", None),
                usage={k: getattr(usage, k, None) for k in
                       ("input_tokens", "output_tokens", "cache_read_input_tokens",
                        "cache_creation_input_tokens")} if usage is not None else None)
    if meta["stop_reason"] in ("refusal", "max_tokens"):
        raise LLMError(f"stop_reason {meta['stop_reason']}", [meta])
    text = "".join(getattr(b, "text", "") for b in getattr(msg, "content", [])
                   if getattr(b, "type", None) == "text")
    try:
        return output.model_validate_json(text), meta
    except Exception as exc:
        raise LLMError(f"schema validation failed: {type(exc).__name__}: {str(exc)[:200]}",
                       [meta]) from exc


def plain_label(field_id: str, table_label: str, labels: dict) -> str:
    """Ruling (C): the row's wording.toml label beside its field_id. NAMED DEFAULT: the
    longest underscore-joined suffix of the field_id's segments that is a `[labels]` key
    (`headline.m2.bad_debt` -> `m2_bad_debt`), else the table's own label."""
    parts = [p for p in field_id.split(".") if not p.startswith("0x")]
    hits = [(j - i, i, "_".join(parts[i:j])) for i in range(len(parts))
            for j in range(i + 1, len(parts) + 1) if "_".join(parts[i:j]) in labels]
    return labels[max(hits)[2]] if hits else table_label


def _family_labels(doc: dict, families: dict) -> dict[str, str]:
    """Ruling (I): every `supply.family.<i>.*` row carries its family's description,
    matched on the family literal's opening words."""
    out = {}
    for r in doc["rows"]:
        f = r["field_id"]
        if f.startswith("supply.family.") and f.endswith(".family"):
            hit = next((d for k, d in families.items() if str(r["value"]).startswith(k)), None)
            if hit:
                out[f.rsplit(".", 1)[0] + "."] = hit
    return out


def slot_input(slot: str, spec: dict, doc: dict, displays: dict, flags: list[dict],
               wording: dict | None = None) -> str:
    """The user content for one slot: that slot's rows (each with its plain label and the
    printed forms the page uses - the only forms a number may be cited in, compact
    first), the assumptions block, and - for flag explanations - the open Level-1
    entries. Never the bundle, tree or stress."""
    wording = wording or {}
    labels = wording.get("labels", {})
    fam = _family_labels(doc, wording.get("residual_families", {}))

    def label(r: dict) -> str:
        # defect 3: both value rows of a counterfactual line name its measured quantity
        m = re.fullmatch(r"headline\.cf\.([^.]+)\.value_(?:primary|counterfactual)", r["field_id"])
        if m and m[1] in wording.get("counterfactual_value", {}):
            return wording["counterfactual_value"][m[1]]
        # ruling 1 on the fourth live run: an M2 curve point names its price-impact level,
        # in the page's printed form of the level's own row (exit.curve.s<p>.s)
        m = re.fullmatch(r"m2\.curve\.t([\d.]+)\.s([\d.]+)", r["field_id"])
        if m and "m2_curve" in wording:
            lvl = sorted(displays.get(f"exit.curve.s{m[2]}.s", []), key=lambda x: (len(x), x))
            impact = lvl[0] if lvl else f"{Decimal(m[2]) * 100:.1f}%"
            return wording["m2_curve"]["label"].format(target=m[1], impact=impact)
        pre = next((p for p in fam if r["field_id"].startswith(p)), None)
        return fam[pre] if pre else plain_label(r["field_id"], r["label"], labels)

    rows = [{"field_id": r["field_id"], "label": label(r),
             "value": r["value"], "unit": r["unit"], "denominator": r["denominator"],
             "printed": sorted(displays.get(r["field_id"], []), key=lambda x: (len(x), x))}
            for r in doc["rows"]
            if any(r["field_id"].startswith(p) for p in spec["prefixes"])
            or r.get("owner_entry") in spec.get("owners", [])]
    body = {"token": doc["token"], "slot": slot, "rows": rows, "assumptions": doc["assumptions"]}
    if slot == "flag_explanations":
        body["open_level1_flags"] = flags
    return json.dumps(body, ensure_ascii=False, sort_keys=True, default=str)




def number_tokens(text: str) -> list[str]:
    """Amin, previews ruling 1: the guard reads numbers with DET-89's tokenizer - one owner
    (dates, addresses and bare integers below 1,000 are not figures)."""
    from factory.validate.harness import _num_tokens
    return _num_tokens(text)


def _printed(rows: list[dict]) -> dict[str, set[str]]:
    printed: dict[str, set[str]] = {}
    for r in rows:
        for form in r["printed"]:
            for tok in [*number_tokens(form), form]:
                printed.setdefault(tok, set()).add(r["field_id"])
    return printed


def printed_by(text: str, rows: list[dict]) -> dict[str, list[str]]:
    """Ruling 1 on the fifth live run: each number in a text with the slot's rows that print it
    (the re-ask carries it)."""
    printed = _printed(rows)
    return {t: sorted(printed[t]) for t in sorted(set(number_tokens(text))) if t in printed}


def fill_references(prose: SlotProse, rows: list[dict]) -> tuple[SlotProse, list[str]]:
    """Ruling 1 on the fifth live run (amends ruling B's second clause; NAMED DEFAULT for
    P-7.10): a number printed by exactly one of the slot's rows adds that row to
    `references_field_ids`, merged after the model's own list."""
    printed = _printed(rows)
    have = set(prose.references_field_ids)
    added = sorted({next(iter(printed[t])) for t in number_tokens(prose.text)
                    if len(printed.get(t, ())) == 1} - have)
    return SlotProse(text=prose.text,
                     references_field_ids=[*prose.references_field_ids, *added]), added


def paragraph_bounds(spec: dict, user: dict) -> tuple[int, int] | None:
    """Previews ruling 4: a slot's paragraph count from slots.toml's `paragraphs` - `[min,
    max]`, or "per_flag" / "per_counterfactual_line" (exactly one per entry, at least one)."""
    p = spec.get("paragraphs")
    if p == "per_flag":
        n = max(1, len(user.get("open_level1_flags", [])))
        return n, n
    if p == "per_counterfactual_line":
        n = max(1, len({r["field_id"].split(".")[2] for r in user["rows"]
                        if r["field_id"].startswith("headline.cf.")}))
        return n, n
    return (p[0], p[1]) if p else None


def paragraphs_of(text: str) -> int:
    return len([x for x in re.split(r"\n\s*\n", text) if x.strip()])


def guard(prose: SlotProse, rows: list[dict], bounds: tuple[int, int] | None = None) -> dict:
    """Ruling (B) b1 as amended on the fifth live run: every number in the text is one of the
    given rows' printed forms; a number printed by several rows needs one of them in the
    model's own `references_field_ids` (a single-row number is filled by
    `fill_references`). Returns the violations (empty = pass).
    NAMED DEFAULT: an input guard on the generation call, not a report revision."""
    printed = _printed(rows)
    refs = set(prose.references_field_ids)
    stray = sorted({t for t in number_tokens(prose.text) if t not in printed})
    missing = sorted({min(printed[t]) for t in number_tokens(prose.text)
                      if len(printed.get(t, ())) > 1 and not printed[t] & refs})
    outside = sorted(f for f in refs if f not in {r["field_id"] for r in rows})
    count = paragraphs_of(prose.text)
    wrong = ({"have": count, "want": list(bounds)}
             if bounds and not bounds[0] <= count <= bounds[1] else None)
    return {k: v for k, v in (("numbers_not_printed", stray), ("missing_field_ids", missing),
                              ("references_outside_rows", outside),
                              ("paragraph_count", wrong)) if v}


def generate(slot: str, user: str, client, repo: pathlib.Path, obligations: str,
             bounds: tuple[int, int] | None = None) -> tuple[SlotProse, dict]:
    """One slot, with at most one re-ask on a guard violation; a second slip is an
    `LLMError` (the slot stays empty and DET-80 blocks)."""
    p = prompts(repo)
    system = p["generate"].replace("{slot}", slot).replace("{obligations}", obligations)
    rows = json.loads(user)["rows"]
    metas, content = [], user
    for attempt in (0, 1):
        try:
            prose, meta = _call(client, model=GENERATOR_MODEL, max_tokens=MAX_TOKENS["generate"],
                                system=system, user=content, output=SlotProse,
                                phash=prompt_hash(repo), effort=EFFORT["generate"])
        except LLMError as exc:
            raise LLMError(f"{slot}: {exc}", [*metas, *exc.calls]) from exc
        metas.append(meta)
        bad = guard(prose, rows, bounds) if prose.text.strip() else {"empty_text": True}
        if not bad:
            prose, added = fill_references(prose, rows)
            usage = {k: sum((m["usage"] or {}).get(k) or 0 for m in metas)
                     for k in ("input_tokens", "output_tokens")}
            return prose, {**meta, "slot": slot, "reasks": attempt, "usage": usage,
                           "calls": [m["usage"] for m in metas],
                           "rejected": [m["rejected"] for m in metas if "rejected" in m],
                           "references_added": added}
        # ruling 2 on the fourth live run: a guard-rejected answer is kept in the record
        meta["rejected"] = {"text": prose.text,
                            "references_field_ids": prose.references_field_ids,
                            "guard_violations": bad,
                            "printed_by": printed_by(prose.text, rows)}
        if attempt == 0:
            content = json.dumps({**json.loads(user), "guard_violations": bad,
                                  "printed_by": meta["rejected"]["printed_by"]},
                                 ensure_ascii=False)
    raise LLMError(f"{slot}: guard failed after one re-ask {bad}", metas)


def apply_replacements(text: str, rev: SlotRevision, defects: list[dict]
                       ) -> tuple[str, list[str]]:
    """The span replacements applied to the pass-1 text, in order; a replacement whose span
    is not one of the slot's defect spans, or not in the text, is an error (the re-ask)."""
    spans = {d["location"]["quoted_span"] for d in defects}
    errors = []
    for r in rev.replacements:
        if r.quoted_span not in spans:
            errors.append(f"not a defect span: {r.quoted_span[:80]}")
        elif r.quoted_span not in text:
            errors.append(f"span not in the pass-1 text: {r.quoted_span[:80]}")
        else:
            text = text.replace(r.quoted_span, r.replacement, 1)
    return text, errors


def revise(slot: str, user: str, client, repo: pathlib.Path, obligations: str,
           bounds: tuple[int, int] | None, pass1_refs: list[str]) -> tuple[SlotProse, dict]:
    """Pass 2 for one slot (Amin, 2026-09-14): the model returns span replacements only; the
    harness applies them to the pass-1 text and runs the same guard, with one re-ask."""
    p = prompts(repo)
    system = (p["generate"].replace("{slot}", slot).replace("{obligations}", obligations)
              + "\n\n" + p["revise"])
    body = json.loads(user)
    rows, pass1, defects = body["rows"], body["pass1_text"], body["pass1_defects"]
    metas, content = [], user
    bad: dict = {}
    for attempt in (0, 1):
        try:
            rev, meta = _call(client, model=GENERATOR_MODEL, max_tokens=MAX_TOKENS["generate"],
                              system=system, user=content, output=SlotRevision,
                              phash=prompt_hash(repo), effort=EFFORT["generate"])
        except LLMError as exc:
            raise LLMError(f"{slot}: {exc}", [*metas, *exc.calls]) from exc
        metas.append(meta)
        text, errors = apply_replacements(pass1, rev, defects)
        refs = list(dict.fromkeys([*pass1_refs, *rev.references_field_ids]))
        prose = SlotProse(text=text, references_field_ids=refs)
        bad = guard(prose, rows, bounds)
        if errors:
            bad["replacement_errors"] = errors
        if not bad:
            prose, added = fill_references(prose, rows)
            usage = {k: sum((m["usage"] or {}).get(k) or 0 for m in metas)
                     for k in ("input_tokens", "output_tokens")}
            return prose, {**meta, "slot": slot, "reasks": attempt, "usage": usage,
                           "calls": [m["usage"] for m in metas],
                           "rejected": [m["rejected"] for m in metas if "rejected" in m],
                           "references_added": added,
                           "replacements": [r.model_dump() for r in rev.replacements]}
        meta["rejected"] = {"text": text, "references_field_ids": refs, "guard_violations": bad,
                            "replacements": [r.model_dump() for r in rev.replacements],
                            "printed_by": printed_by(text, rows)}
        if attempt == 0:
            content = json.dumps({**body, "guard_violations": bad,
                                  "printed_by": meta["rejected"]["printed_by"]},
                                 ensure_ascii=False)
    raise LLMError(f"{slot}: guard failed after one re-ask {bad}", metas)


def judge(text: str, table: dict, client, repo: pathlib.Path, rubric_text: str,
          header: dict) -> tuple[JudgeEnvelope, dict]:
    p = prompts(repo)
    system = (p["judge"].replace("{criteria}", rubric_criteria(rubric_text))
              .replace("{item_shapes}", item_shapes(rubric_text))
              .replace("{rubric_version}", header["rubric_version"])
              .replace("{report_id}", header["report_id"])
              .replace("{bundle_hash}", header["bundle_hash"])
              .replace("{judge_model}", JUDGE_MODEL)
              .replace("{prompt_schema_version}", header["prompt_schema_version"]))
    # (7): the table block first, cached, so pass 2's judgment reads it; the page after it
    user = [{"type": "text", "cache_control": JUDGE_CACHE,
             "text": json.dumps({"table": table}, ensure_ascii=False, default=str)},
            {"type": "text", "text": json.dumps({"page": text}, ensure_ascii=False)}]
    env, meta = _call(client, model=JUDGE_MODEL, max_tokens=MAX_TOKENS["judge"], system=system,
                      user=user, output=JudgeEnvelope, phash=prompt_hash(repo),
                      effort=EFFORT["judge"])
    if sorted(c.id for c in env.criteria) != list(LLM_IDS):
        raise LLMError(f"envelope criteria {sorted(c.id for c in env.criteria)}")
    return env, meta


def remediate(defects: list[dict], text: str, client, repo: pathlib.Path
              ) -> tuple[Remediation, dict]:
    p = prompts(repo)
    user = json.dumps({"pass1_defects": defects, "page": text}, ensure_ascii=False)
    rem, meta = _call(client, model=JUDGE_MODEL, max_tokens=MAX_TOKENS["remediate"],
                      system=p["remediate"], user=user, output=Remediation,
                      phash=prompt_hash(repo))
    if sorted(a.defect_index for a in rem.items) != list(range(len(defects))):
        raise LLMError("remediation does not answer every pass-1 defect once")
    return rem, meta
