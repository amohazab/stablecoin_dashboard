"""B-13: a fake Anthropic client for the report stage's LLM calls - no network.

`client.messages.stream(...)` (ruling D: every call streams) answers from a recorded
fixture directory (`tests/fixtures/llm/<case>/`) as a final message whose text is the
recorded JSON: `generation.json` per slot (`generation_first.json`, when present,
answers a slot's first call - the re-ask fixtures); `env1.json` / `env2.json` for the
first and second judgment; `remediation.json`; `judge_mode.txt` = `malformed` (the
text fails the schema), `refusal` (stop_reason "refusal") or `max_tokens` (a truncated
envelope, stop_reason "max_tokens"). The call kind is read from the requested JSON
schema. A recorded defect with `paragraph_index = -1` is placed at the paragraph of the
judged page that holds its span; a span on no paragraph keeps -1, which the harness
post-check discards (`judge_span_not_found`)."""

from __future__ import annotations

import json
import pathlib
import re
from types import SimpleNamespace

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "llm"


def _sections(page: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for block in page.split("## section_id: ")[1:]:
        sid, _, body = block.partition("\n")
        out[sid.strip()] = [re.sub(r"^\[\d+\] ", "", ln) for ln in body.splitlines()
                            if re.match(r"^\[\d+\] ", ln)]
    return out


def _kind(output_config: dict) -> str:
    props = output_config["format"]["schema"].get("properties", {})
    if "criteria" in props:
        return "JudgeEnvelope"
    if "text" in props:
        return "SlotProse"
    if "replacements" in props:
        return "SlotRevision"
    return "Remediation"


class _Stream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.message


class _Messages:
    def __init__(self, case: str):
        self.dir = FIXTURES / case
        self.judgments = 0
        self.calls: list[str] = []
        self.slot_calls: dict[str, int] = {}
        self.requests: list[dict] = []

    def _load(self, name: str):
        p = self.dir / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def stream(self, *, model, max_tokens, system, messages, output_config, thinking=None, **kw):
        content = messages[0]["content"]
        if isinstance(content, str):
            user = json.loads(content)
        else:                                     # the judge's cached table block + page block
            user = {k: v for b in content for k, v in json.loads(b["text"]).items()}
        kind = _kind(output_config)
        self.calls.append(kind)
        self.requests.append({"kind": kind, "model": model, "max_tokens": max_tokens,
                              "effort": output_config.get("effort"), "thinking": thinking,
                              "cache": [b.get("cache_control") for b in content
                                        if isinstance(b, dict) and b.get("cache_control")]
                              if not isinstance(content, str) else [],
                              "user_keys": sorted(user), "slot": user.get("slot"),
                              "pass1_defects": len(user.get("pass1_defects", []))})
        usage = SimpleNamespace(input_tokens=len(json.dumps(content)) // 4, output_tokens=200,
                                cache_read_input_tokens=0, cache_creation_input_tokens=0)
        stop, text = "end_turn", None
        if kind == "SlotProse":
            slot = user["slot"]
            self.slot_calls[slot] = self.slot_calls.get(slot, 0) + 1
            first = self._load("generation_first.json") or {}
            obj = (first[slot] if slot in first and self.slot_calls[slot] == 1
                   else self._load("generation.json")[slot])
        elif kind == "SlotRevision":
            # `revision.json` {slot: {replacements, references_field_ids}} when present; else
            # an identity replacement of each defect span found in the pass-1 text
            rec = (self._load("revision.json") or {}).get(user["slot"])
            obj = rec or {"references_field_ids": [], "replacements": [
                {"quoted_span": d["location"]["quoted_span"],
                 "replacement": d["location"]["quoted_span"]}
                for d in user["pass1_defects"]
                if d["location"]["quoted_span"] in user["pass1_text"]]}
        elif kind == "JudgeEnvelope":
            self.judgments += 1
            mode = self.dir / "judge_mode.txt"
            mode = mode.read_text(encoding="utf-8").strip() if mode.exists() else ""
            obj = self._load(f"env{self.judgments}.json") or self._load("env1.json") or {}
            if mode == "malformed":
                text = '{"rubric_version": "v1", "criteria": "not a list"}'
            elif mode == "refusal":
                stop, text = "refusal", ""
            elif mode == "max_tokens":
                stop, text = "max_tokens", '{"rubric_version": "v1", "criteria": [{"id": "LLM-0'
            else:
                secs = _sections(user["page"])
                for c in obj["criteria"]:
                    for d in c["defects"]:
                        loc = d["location"]
                        if loc["paragraph_index"] == -1:
                            paras = secs.get(loc["section_id"], [])
                            hit = [i for i, p in enumerate(paras) if loc["quoted_span"] in p]
                            loc["paragraph_index"] = hit[0] if hit else -1
        else:
            obj = self._load("remediation.json") or {"items": [
                {"defect_index": d["index"], "addressed": "yes", "reason": "recorded"}
                for d in user["pass1_defects"]]}
        if text is None:
            text = json.dumps(obj, ensure_ascii=False)
        msg = SimpleNamespace(content=[SimpleNamespace(type="text", text=text)],
                              stop_reason=stop, usage=usage)
        return _Stream(msg)


class FakeClient:
    def __init__(self, case: str):
        self.messages = _Messages(case)
