"""B-13 (P-7.01 R12; rubric 2.1, 2.2) and Step 8 phase B (P-8.04): the generation, judge and
remediation calls, on the local Ollama model only (P-8.01: no Anthropic call in any form).

Every call goes through `_call`: one `POST /api/chat` with `think: false`, `stream: false`,
`format` = the Pydantic output model's own `model_json_schema()` (one source, nothing
retyped) and options {num_ctx, num_predict, temperature 0, seed 0} (A-21). The client is
injected: the report stage builds an `OllamaClient` only when asked (`--llm`); the tests pass
a fake that answers the same `chat(body)` seam from recorded bodies - the suite never touches
the network.

Recorded per call (P-8.04 Q6): model, digest, ollama_version, think false, sampling, num_ctx,
num_predict, prompt hash, input hash, done_reason, the five counters and the wall time.
Fail-closed (`LLMError`): an unreachable server; an input whose chars / 3 + num_predict
exceeds num_ctx (before the call); `done_reason == "length"`; prompt_eval_count +
num_predict above num_ctx (a truncated prompt, after the call); a non-JSON or
schema-invalid reply.

The judge (A-22): one call per criterion, each scoped to the part of 2.1's input that the
criterion reads; the harness assembles 2.1's envelope, fills its header and computes each
`pass` and `overall_pass`. A-23: an LLM-01 `untraceable` defect whose span's number tokens are
all printed forms of its slot's rows, or a `mismatch` whose matched row prints them, is
discarded and recorded as `guard_verified`.

NAMED DEFAULTS (B-13): one generation call per slot; a defect whose `quoted_span` is not in
the paragraph it names is discarded and recorded as `judge_span_not_found`.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import time
import tomllib
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

MODEL = "qwen3.5:9b"                     # P-8.01: generator and judge
JUDGE_MODEL = GENERATOR_MODEL = MODEL
OLLAMA_URL = "http://localhost:11434"
NUM_CTX = 32768                          # P-8.04 Q5
NUM_PREDICT = {"generate": 2000, "judge": 4000, "remediate": 2000}
SAMPLING = {"temperature": 0, "seed": 0}   # A-21
CHARS_PER_TOKEN = 3                      # Inventory F2: qwen counts 10,030 tokens for 30,122 chars
LLM_IDS = ("LLM-01", "LLM-02", "LLM-03", "LLM-04", "LLM-05", "LLM-06")
# A-24 (Amin, 2026-09-25, P-8.05): the judge is withdrawn in the local configuration.
JUDGE_WITHDRAWN = "judge withdrawn (P-8.05): the local model failed the Q13 control"


class LLMError(Exception):
    """A call that did not yield a parsed, schema-valid object. `calls` carries the record of
    every call made before the failure (ruling G)."""

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
    """Rubric 2.1's criterion. P-8.04 Q4: items are typed objects (the Ollama grammar takes
    them); the Claude-era JSON-string form (ruling (A) a1) stays readable for the recorded
    fixtures. Each item is validated against its criterion's printed schema (`ITEM_MODELS`)."""

    id: Literal["LLM-01", "LLM-02", "LLM-03", "LLM-04", "LLM-05", "LLM-06"]
    pass_: bool = Field(alias="pass")
    items: list[dict[str, Any] | str]
    defects: list[Defect]


def _item(raw: dict | str) -> dict:
    return json.loads(raw) if isinstance(raw, str) else raw


def item_errors(env: JudgeEnvelope) -> dict[str, str]:
    """`{criterion id: reason}` for every criterion with an item that is not its printed
    schema - an invalid item is `error` on that criterion's row."""
    out = {}
    for c in env.criteria:
        for i, raw in enumerate(c.items):
            try:
                ITEM_MODELS[c.id].model_validate(_item(raw))
            except Exception as exc:                       # JSON or schema
                out[c.id] = f"item {i}: {type(exc).__name__}: {str(exc)[:160]}"
                break
    return out


# A-22: one call per criterion; its output is that criterion's items and defects, the typed
# item model generated from `ITEM_MODELS` (F5: one source).
CRITERION_OUT = {cid: create_model(f"Out{cid.replace('-', '')}", __base__=_Strict,
                                   items=(list[m], ...), defects=(list[Defect], ...))
                 for cid, m in ITEM_MODELS.items()}


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
            "slots": _slots(tpl / "slots.toml")}


def _slots(path: pathlib.Path) -> dict:
    """slots.toml's `[slot.*]` tables, each carrying the file's `max_entities_per_group`
    unless the slot sets `cap = false`."""
    doc = tomllib.loads(path.read_text(encoding="utf-8"))
    cap = doc.get("max_entities_per_group")
    return {k: ({**v, "max_entities_per_group": cap} if cap and v.get("cap", True) else v)
            for k, v in doc["slot"].items()}


def sha(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8") + b"\0")
    return h.hexdigest()


def prompt_hash(repo: pathlib.Path) -> str:
    """One hash over the prompt files, the slot table, the output schemas, the six typed
    item schemas and the six per-criterion output schemas (P-8.04) - the value recorded
    beside every recorded fixture (a prompt edit visibly stales them)."""
    tpl = repo / "templates/prompts"
    files = [(tpl / n).read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
             for n in ("generate.md", "judge.md", "remediate.md", "revise.md", "slots.toml")]
    schemas = [json.dumps(m.model_json_schema(), sort_keys=True)
               for m in (SlotProse, SlotRevision, JudgeEnvelope, Remediation,
                         *ITEM_MODELS.values(), *CRITERION_OUT.values())]
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


def printed_shape(rubric_text: str, cid: str) -> str:
    """The rubric's printed `Schema ...: `{...}`` span for one criterion, verbatim."""
    text = dict(zip(LLM_IDS, rubric_criteria(rubric_text).split("\n\n"), strict=True))[cid]
    m = re.search(r"Schema[^`]*`[^`]*`", text)
    if m is None:
        raise LLMError(f"rubric entry {cid}: no printed item shape")
    return m.group(0)


def item_shape(rubric_text: str, cid: str) -> str:
    """Ruling 4 on the fourth live run and ruling 2 (b) on the sixth: the printed shape with
    the typed item schema the harness validates against."""
    typed = json.dumps(ITEM_MODELS[cid].model_json_schema(), ensure_ascii=False,
                       separators=(",", ":"))
    return f"- {cid}: {printed_shape(rubric_text, cid)}\n  typed item schema: {typed}"


def item_shapes(rubric_text: str) -> str:
    return "\n".join(item_shape(rubric_text, cid) for cid in LLM_IDS)


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


class OllamaClient:
    """The local model behind `POST /api/chat` (P-8.04 Q1). Built once per run: the server
    version and the model digest are read at construction, and an unreachable server or an
    absent model is an `LLMError` before any work (fail-closed)."""

    def __init__(self, base: str = OLLAMA_URL, model: str = MODEL, timeout: float = 3600):
        import requests
        self.base, self.model, self.timeout, self._requests = base, model, timeout, requests
        try:
            self.version = requests.get(f"{base}/api/version", timeout=10).json()["version"]
            tags = requests.get(f"{base}/api/tags", timeout=10).json()["models"]
        except Exception as exc:
            msg = f"ollama unreachable at {base}: {type(exc).__name__}: {exc}"
            raise LLMError(msg[:300]) from exc
        hit = [m["digest"] for m in tags if m["name"] == model]
        if not hit:
            raise LLMError(f"model {model} not present in ollama at {base}")
        self.digest = hit[0]

    def chat(self, body: dict) -> dict:
        r = self._requests.post(f"{self.base}/api/chat", json=body, timeout=self.timeout)
        r.raise_for_status()
        return r.json()


def llm_header(client) -> dict:
    """The gate record's `llm` header (P-8.04 Q6); the manifest stays R3's."""
    return {"backend": "ollama", "version": client.version, "model": MODEL,
            "digest": client.digest}


def _call(client, *, kind: str, system: str, user: str, output: type, phash: str
          ) -> tuple[Any, dict]:
    """One `/api/chat` call, recorded on every path; see the module docstring for the
    fail-closed rules."""
    num_predict = NUM_PREDICT[kind]
    meta = {"model": MODEL, "digest": client.digest, "ollama_version": client.version,
            "think": False, "sampling": dict(SAMPLING), "num_ctx": NUM_CTX,
            "num_predict": num_predict, "prompt_hash": phash, "input_hash": sha(system, user),
            "done_reason": None}
    est = (len(system) + len(user)) // CHARS_PER_TOKEN
    if est + num_predict > NUM_CTX:
        meta["estimated_prompt_tokens"] = est
        raise LLMError(f"input too long: ~{est} tokens + {num_predict} > num_ctx {NUM_CTX}",
                       [meta])
    body = {"model": MODEL, "think": False, "stream": False,
            "format": output.model_json_schema(),
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "options": {"num_ctx": NUM_CTX, "num_predict": num_predict, **SAMPLING}}
    t0 = time.perf_counter()
    try:
        resp = client.chat(body)
    except Exception as exc:                          # unreachable, HTTP error
        meta["wall_s"] = round(time.perf_counter() - t0, 1)
        raise LLMError(f"ollama call failed: {type(exc).__name__}: {exc}"[:300],
                       [meta]) from exc
    meta["wall_s"] = round(time.perf_counter() - t0, 1)
    meta.update({k: resp.get(k) for k in ("done_reason", "prompt_eval_count", "eval_count",
                                           "prompt_eval_duration", "eval_duration",
                                           "total_duration")})
    if meta["done_reason"] == "length":           # P-8.07: the content is kept
        meta["rejected"] = {"text": (resp.get("message") or {}).get("content") or "",
                            "guard_violations": {"done_reason": "length"}}
        raise LLMError(f"done_reason length at num_predict {num_predict}", [meta])
    if (meta["prompt_eval_count"] or 0) + num_predict > NUM_CTX:
        raise LLMError(f"prompt truncated: prompt_eval_count {meta['prompt_eval_count']} + "
                       f"{num_predict} > num_ctx {NUM_CTX}", [meta])
    text = (resp.get("message") or {}).get("content") or ""
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


def _magnitude(v: Any) -> Decimal:
    if isinstance(v, bool) or v is None:
        return Decimal(-1)
    try:
        return abs(Decimal(str(v)))
    except (InvalidOperation, ValueError):
        return Decimal(-1)


def cap_groups(rows: list[dict], spec: dict) -> list[dict]:
    """P-8.07 (c), ruled (i): each prefix group (the slots.toml prefix, or the owner entry,
    that selected the row) keeps its `max_entities_per_group` largest entities - an entity
    is a row's parent field id - ranked by their largest |value| (non-numeric ranks last,
    then table order), with all their rows; the kept rows stay in table order."""
    cap = spec.get("max_entities_per_group")
    if not cap:
        return rows
    groups: dict[str, dict[str, list[int]]] = {}
    for i, r in enumerate(rows):
        g = next((p for p in spec["prefixes"] if r["field_id"].startswith(p)),
                 f"owner:{r.get('owner_entry')}")
        groups.setdefault(g, {}).setdefault(r["field_id"].rsplit(".", 1)[0], []).append(i)
    keep: set[int] = set()
    for ents in groups.values():
        ranked = sorted(ents.values(),
                        key=lambda idx: (-max(_magnitude(rows[i]["value"]) for i in idx), idx[0]))
        for idx in ranked[:cap]:
            keep.update(idx)
    return [r for i, r in enumerate(rows) if i in keep]


def counterfactual_lines(doc: dict) -> list[str]:
    """The counterfactual line ids, in table order."""
    out: list[str] = []
    for r in doc["rows"]:
        m = re.match(r"headline\.cf\.([^.]+)\.", r["field_id"])
        if m and m[1] not in out:
            out.append(m[1])
    return out


def slot_input(slot: str, spec: dict, doc: dict, displays: dict, flags: list[dict],
               wording: dict | None = None, part: dict | None = None) -> str:
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

    chosen = [r for r in doc["rows"]
              if any(r["field_id"].startswith(p) for p in spec["prefixes"])
              or r.get("owner_entry") in spec.get("owners", [])]
    if part and "line" in part:           # P-8.07: one counterfactual line's rows only
        chosen = [r for r in chosen if not r["field_id"].startswith("headline.cf.")
                  or r["field_id"].startswith(f"headline.cf.{part['line']}.")]
    rows = [{"field_id": r["field_id"], "label": label(r),
             "value": r["value"], "unit": r["unit"], "denominator": r["denominator"],
             "printed": sorted(displays.get(r["field_id"], []), key=lambda x: (len(x), x))}
            for r in cap_groups(chosen, spec)]
    admin_words(rows, wording)
    assumptions = code_words(rows, doc["assumptions"], wording)
    undash(rows)
    body = {"token": doc["token"], "slot": slot, "rows": rows, "assumptions": assumptions}
    if slot == "flag_explanations":
        body["open_level1_flags"] = flags
    if part:
        body["part"] = part
    return json.dumps(body, ensure_ascii=False, sort_keys=True, default=str)




def admin_words(rows: list[dict], wording: dict) -> None:
    """P-8.06 (Amin): an admin row reaches the generator in plain words - its label is the
    power's name and `[admin_row]`'s kind, and a holder type, delay bucket or evidence kind
    its `[holders]` / `[delay_short]` / `[evidence]` words (an unmapped value stays)."""
    kinds = wording.get("admin_row", {})
    tables = {"holder_type": wording.get("holders", {}), "delay_bucket":
              wording.get("delay_short", {}), "A8": wording.get("evidence", {}),
              "reads": wording.get("evidence", {})}
    for r in rows:
        parts = r["field_id"].split(".")
        if parts[0] != "admin" or len(parts) < 4:
            continue
        kind = "reads" if "reads" in parts[3:] else parts[-1]
        if kind not in kinds:
            continue
        r["label"] = f"{wording.get('powers', {}).get(parts[1], parts[1])}: {kinds[kind]}"
        v = "none" if r["value"] is None else str(r["value"])
        if v in tables[kind]:
            r["value"] = tables[kind][v]
            r["printed"] = [tables[kind][v]]


SPACED_DASH = re.compile(" [—–] ")


def undash(rows: list[dict]) -> None:
    """Polish (Amin): the generator's copy of each label, string value and printed form reads
    " — " and " – " as ", " (rule 17 bans both dashes in its text); the page and the
    literals themselves are untouched."""
    def sub(x):
        return SPACED_DASH.sub(", ", x) if isinstance(x, str) else x
    for r in rows:
        r["label"] = sub(r["label"])
        v = r["value"]
        r["value"] = [sub(x) for x in v] if isinstance(v, list) else sub(v)
        r["printed"] = [sub(p) for p in r["printed"]]


def code_words(rows: list[dict], assumptions: list[dict], wording: dict) -> list[dict]:
    """P-8.07 (b'): every identifier token in a row's label, string value or printed forms,
    and in an assumption's id, becomes its plain words - `[code_words]`, then `[holders]` and
    `[powers]`; an unmapped identifier stays (the guard rejects it if copied). Field ids are
    never touched. Returns the assumptions block with its ids worded."""
    table = {**wording.get("holders", {}), **wording.get("powers", {}),
             **wording.get("code_words", {})}

    def sub(text: str) -> str:
        for tok in sorted(set(identifiers(text)), key=len, reverse=True):
            if tok in table:
                text = re.sub(rf"(?<![\w.]){re.escape(tok)}(?!\w)", table[tok], text)
        return text
    for r in rows:
        r["label"] = sub(r["label"])
        if isinstance(r["value"], str):
            r["value"] = sub(r["value"])
        elif isinstance(r["value"], list):
            r["value"] = [sub(x) if isinstance(x, str) else x for x in r["value"]]
        r["printed"] = [sub(p) for p in r["printed"]]
    return [{**a, "id": sub(a["id"])} if isinstance(a.get("id"), str) else a
            for a in assumptions]


def number_tokens(text: str) -> list[str]:
    """Amin, previews ruling 1: the guard reads numbers with DET-89's tokenizer - one owner
    (dates, addresses and bare integers below 1,000 are not figures)."""
    from factory.validate.harness import _num_tokens
    return _num_tokens(text)


DASHES = "\u2014\u2013"     # the em dash and the en dash, never written in a slot (rule 17)


def identifiers(text: str) -> list[str]:
    """P-8.06: snake_case and camelCase tokens - rule 4 as code (harness owns the regexes)."""
    from factory.validate.harness import _identifiers
    return _identifiers(text)


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
    idents = sorted(set(identifiers(prose.text)))          # P-8.06: rule 4 as code
    dashes = sorted({c for c in prose.text if c in DASHES})  # polish: generate.md rule 17
    return {k: v for k, v in (("numbers_not_printed", stray), ("missing_field_ids", missing),
                              ("references_outside_rows", outside),
                              ("paragraph_count", wrong), ("identifiers", idents),
                              ("dashes", dashes)) if v}


_PCT = re.compile(r"^(-?\d[\d,]*(?:\.\d+)?)%$")


def _pct(tok: str) -> Decimal | None:
    m = _PCT.match(tok.replace("\u2212", "-"))
    try:
        return Decimal(m.group(1).replace(",", "")) if m else None
    except InvalidOperation:
        return None


def substitute_percents(text: str, rows: list[dict]) -> tuple[str, list[dict]]:
    """P-8.04 Q8 (2), option (i): a percentage the rows do not print, numerically equal to
    exactly one printed percentage of another precision ("5%" for "5.0%"), is replaced by
    that printed form - the page then carries DET-89's string. Recorded per substitution."""
    printed = _printed(rows)
    forms = {t for t in printed if _pct(t) is not None}
    subs = []
    for tok in sorted(set(number_tokens(text))):
        v = _pct(tok)
        if v is None or tok in printed:
            continue
        equal = sorted(f for f in forms if _pct(f) == v)
        if len(equal) == 1:
            text = re.sub(rf"(?<![\w.$\-\u2212]){re.escape(tok)}(?![\w%])", equal[0], text)
            subs.append({"from": tok, "to": equal[0]})
    return text, subs


def _counters(metas: list[dict]) -> dict:
    return {k: sum(m.get(k) or 0 for m in metas) for k in ("prompt_eval_count", "eval_count")}


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
            prose, meta = _call(client, kind="generate", system=system, user=content,
                                output=SlotProse, phash=prompt_hash(repo))
        except LLMError as exc:
            raise LLMError(f"{slot}: {exc}", [*metas, *exc.calls]) from exc
        metas.append(meta)
        text, subs = substitute_percents(prose.text, rows)
        if subs:
            meta["substituted"] = subs
            prose = SlotProse(text=text, references_field_ids=prose.references_field_ids)
        bad = guard(prose, rows, bounds) if prose.text.strip() else {"empty_text": True}
        if not bad:
            prose, added = fill_references(prose, rows)
            return prose, {**meta, "slot": slot, "reasks": attempt, **_counters(metas),
                           "calls": metas, "references_added": added,
                           "rejected": [m["rejected"] for m in metas if "rejected" in m]}
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


def generate_parts(slot: str, users: list[str], client, repo: pathlib.Path,
                   obligations: str) -> tuple[SlotProse, dict]:
    """P-8.07 (Amin): one generation call per counterfactual line or open flag, each bounded
    to one paragraph, joined in order; any part that fails after its re-ask empties the
    slot (an `LLMError` carrying every call)."""
    texts, refs, parts, metas = [], [], [], []
    for i, user in enumerate(users):
        try:
            out, meta = generate(slot, user, client, repo, obligations, (1, 1))
        except LLMError as exc:
            raise LLMError(f"part {i + 1} of {len(users)}: {exc}",
                           [*metas, *exc.calls]) from exc
        metas += meta["calls"]
        texts.append(out.text.strip())
        refs += out.references_field_ids
        parts.append({"part": json.loads(user).get("part"), "reasks": meta["reasks"],
                      "text": out.text})
    joined = SlotProse(text="\n\n".join(texts), references_field_ids=list(dict.fromkeys(refs)))
    first = {k: metas[0].get(k) for k in ("digest", "ollama_version", "think", "sampling",
                                           "num_ctx", "num_predict", "prompt_hash")}
    return joined, {"model": MODEL, **first, "slot": slot,
                    "reasks": sum(p["reasks"] for p in parts),
                    "parts": parts, "calls": metas, **_counters(metas),
                    "rejected": [m["rejected"] for m in metas if "rejected" in m]}


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
            rev, meta = _call(client, kind="generate", system=system, user=content,
                              output=SlotRevision, phash=prompt_hash(repo))
        except LLMError as exc:
            raise LLMError(f"{slot}: {exc}", [*metas, *exc.calls]) from exc
        metas.append(meta)
        text, errors = apply_replacements(pass1, rev, defects)
        text, subs = substitute_percents(text, rows)
        if subs:
            meta["substituted"] = subs
        refs = list(dict.fromkeys([*pass1_refs, *rev.references_field_ids]))
        prose = SlotProse(text=text, references_field_ids=refs)
        bad = guard(prose, rows, bounds)
        if errors:
            bad["replacement_errors"] = errors
        if not bad:
            prose, added = fill_references(prose, rows)
            return prose, {**meta, "slot": slot, "reasks": attempt, **_counters(metas),
                           "calls": metas, "references_added": added,
                           "rejected": [m["rejected"] for m in metas if "rejected" in m],
                           "replacements": [r.model_dump() for r in rev.replacements]}
        meta["rejected"] = {"text": text, "references_field_ids": refs, "guard_violations": bad,
                            "replacements": [r.model_dump() for r in rev.replacements],
                            "printed_by": printed_by(text, rows)}
        if attempt == 0:
            content = json.dumps({**body, "guard_violations": bad,
                                  "printed_by": meta["rejected"]["printed_by"]},
                                 ensure_ascii=False)
    raise LLMError(f"{slot}: guard failed after one re-ask {bad}", metas)


def judge_calls(sections: dict[str, list[str]], slot_users: dict[str, str],
                prose: dict[str, str], slots: dict) -> list[dict]:
    """A-22: the scoped calls of one judgment, `{criterion, scope, page, body}`, each input a
    subset of 2.1's (P-8.04 Q3). LLM-03 first, over the whole page text and no table; LLM-01
    and LLM-04 per filled slot, with the slot's section and the rows its generator received;
    LLM-02 per member slot; LLM-05 on the oracle and counterfactual sections with the open
    Level-1 flags and the `headline.cf.*` rows; LLM-06 on member2's section and rows. A
    section keeps its full paragraph list, so every index is the page's own."""
    def page(*sids: str) -> str:
        return page_text({sid: sections[sid] for sid in sids if sid in sections})

    def rows_of(slot: str) -> dict:
        u = json.loads(slot_users[slot])
        return {k: u[k] for k in ("rows", "assumptions", "open_level1_flags") if k in u}

    filled = [s for s in slot_users if (prose.get(s) or "").strip()]
    out = [{"criterion": "LLM-03", "scope": "page", "page": page(*sections), "body": {}}]
    for cid in ("LLM-01", "LLM-02", "LLM-04"):
        for slot in filled:
            if cid == "LLM-02" and slot not in ("member1_opening", "member2_opening"):
                continue
            out.append({"criterion": cid, "scope": slot,
                        "page": page(slots[slot]["page_section"]), "body": rows_of(slot)})
    flags = (json.loads(slot_users["flag_explanations"]).get("open_level1_flags", [])
             if "flag_explanations" in slot_users else [])
    cf = {r["field_id"]: r for u in slot_users.values() for r in json.loads(u)["rows"]
          if r["field_id"].startswith("headline.cf.")}
    out.append({"criterion": "LLM-05", "scope": "oracle+counterfactuals",
                "page": page("oracle", "counterfactuals"),
                "body": {"rows": list(cf.values()), "open_level1_flags": flags}})
    if "member2_opening" in filled:
        out.append({"criterion": "LLM-06", "scope": "member2_opening",
                    "page": page(slots["member2_opening"]["page_section"]),
                    "body": rows_of("member2_opening")})
    return out


def guard_verified(cid: str, out, rows: list[dict], displays: dict[str, list[str]]
                   ) -> tuple[list, list[dict]]:
    """A-23: an LLM-01 `untraceable` defect whose span's number tokens are all printed forms
    of the rows its slot was generated from (the guard's own test), or a `mismatch` whose
    `matched_field_id` row prints the span's number tokens, is discarded and recorded."""
    if cid != "LLM-01":
        return list(out.defects), []
    printed = _printed(rows)
    matched = {i.quoted_span: i.matched_field_id for i in out.items}
    keep, gone = [], []
    for d in out.defects:
        toks = number_tokens(d.location.quoted_span)
        fid = matched.get(d.location.quoted_span) or d.table_ref
        row_forms = {t for f in displays.get(fid or "", []) for t in [*number_tokens(f), f]}
        hit = bool(toks) and (
            (d.kind == "untraceable" and all(t in printed for t in toks)) or
            (d.kind == "mismatch" and all(t in row_forms for t in toks)))
        if hit:
            gone.append({"event": "guard_verified", "criterion": cid, "kind": d.kind,
                         "section_id": d.location.section_id,
                         "paragraph_index": d.location.paragraph_index,
                         "quoted_span": d.location.quoted_span, "matched_field_id": fid})
        else:
            keep.append(d)
    return keep, gone


def judge(sections: dict[str, list[str]], slot_users: dict[str, str], prose: dict[str, str],
          displays: dict[str, list[str]], client, repo: pathlib.Path, rubric_text: str,
          header: dict) -> tuple[JudgeEnvelope, dict]:
    """A-22: every scoped call, then 2.1's envelope assembled by the harness - the header
    filled here, items and defects concatenated per criterion, A-23's discards applied; the
    caller computes `pass` / `overall_pass` after its own discards (`computed_pass`). A
    criterion whose call fails is recorded under `criterion_errors` (its row reads `error`);
    every criterion failing is an `LLMError`."""
    p = prompts(repo)
    phash = prompt_hash(repo)
    crit_text = dict(zip(LLM_IDS, rubric_criteria(rubric_text).split("\n\n"), strict=True))
    items: dict[str, list] = {c: [] for c in LLM_IDS}
    defects: dict[str, list] = {c: [] for c in LLM_IDS}
    metas, errors, verified = [], {}, []
    for c in judge_calls(sections, slot_users, prose, p["slots"]):
        cid = c["criterion"]
        system = (p["judge"].replace("{criterion_id}", cid)
                  .replace("{criterion}", crit_text[cid])
                  .replace("{item_shape}", item_shape(rubric_text, cid)))
        user = json.dumps({**c["body"], "page": c["page"]}, ensure_ascii=False, default=str)
        try:
            out, meta = _call(client, kind="judge", system=system, user=user,
                              output=CRITERION_OUT[cid], phash=phash)
        except LLMError as exc:
            errors.setdefault(cid, f"{c['scope']}: {exc}")
            metas.extend({**m, "criterion": cid, "scope": c["scope"], "error": str(exc)}
                         for m in exc.calls)
            continue
        keep, gone = guard_verified(cid, out, c["body"].get("rows", []), displays)
        verified += [{**g, "scope": c["scope"]} for g in gone]
        items[cid] += [i.model_dump() for i in out.items]
        defects[cid] += keep
        metas.append({**meta, "criterion": cid, "scope": c["scope"],
                      "items": len(out.items), "defects": len(out.defects),
                      "raw_defects": [d.model_dump() for d in out.defects]})
    if len(errors) == len(LLM_IDS):
        raise LLMError(next(iter(errors.values())), metas)
    env = JudgeEnvelope(**header, judge_model=MODEL, overall_pass=False, criteria=[
        Criterion(id=cid, items=items[cid], defects=defects[cid], **{"pass": False})
        for cid in LLM_IDS])
    return env, {"model": MODEL, "digest": client.digest, "ollama_version": client.version,
                 "calls": metas, "criterion_errors": errors, "guard_verified": verified,
                 "wall_s": round(sum(m.get("wall_s") or 0 for m in metas), 1),
                 **_counters(metas)}


def computed_pass(env: JudgeEnvelope, errors: dict[str, str]) -> JudgeEnvelope:
    """A-22: each criterion's `pass` is "no surviving defect" (and no failed call);
    `overall_pass` is every criterion passing - computed after every discard."""
    crit = [c.model_copy(update={"pass_": not c.defects and c.id not in errors})
            for c in env.criteria]
    return env.model_copy(update={"criteria": crit,
                                  "overall_pass": all(c.pass_ for c in crit)})


def remediate(defects: list[dict], text: str, client, repo: pathlib.Path
              ) -> tuple[Remediation, dict]:
    p = prompts(repo)
    user = json.dumps({"pass1_defects": defects, "page": text}, ensure_ascii=False)
    rem, meta = _call(client, kind="remediate", system=p["remediate"], user=user,
                      output=Remediation, phash=prompt_hash(repo))
    if sorted(a.defect_index for a in rem.items) != list(range(len(defects))):
        raise LLMError("remediation does not answer every pass-1 defect once", [meta])
    return rem, meta
