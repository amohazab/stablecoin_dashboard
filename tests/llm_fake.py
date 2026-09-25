"""B-13, through Step 8's seam (P-8.04): a fake Ollama client for the report stage's calls - no
network.

`client.chat(body)` answers a `/api/chat` body from a recorded fixture directory
(`tests/fixtures/llm/<case>/`, Claude-era history, P-8.04 Q6) as a response whose
`message.content` is the recorded JSON. The call kind is the requested `format` schema's
title: `SlotProse` per slot from `generation.json` (`generation_first.json`, when present,
answers a slot's first call - the re-ask fixtures); `SlotRevision` from `revision.json` or an
identity replacement; `Remediation` from `remediation.json`; `OutLLM0x` (A-22, one call per
criterion) from that criterion's slice of `env1.json` / `env2.json`, one judgment per LLM-03
call (the judge's first call). Within a judgment a criterion's items go on its first call, and
each defect on the first call whose page holds its span - or on the first call when none does;
a recorded `paragraph_index = -1` is placed at the page paragraph holding the span, and a span
on no paragraph keeps -1, which the post-check discards (`judge_span_not_found`). Items
recorded as JSON strings are sent as objects (Q4). `judge_mode.txt` = `malformed` (content
fails the schema), `refusal` (empty content) or `max_tokens` (`done_reason` "length")
applies to every criterion call."""

from __future__ import annotations

import json
import pathlib
import re

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "llm"
RECORDED = {"crvUSD": 25974925, "GHO": 25974932, "LUSD": 25974949}   # the Claude-era runs


def pin_to_recorded(root: pathlib.Path) -> pathlib.Path:
    """P-8.06: the recorded fixtures and assertions belong to each token's Claude-era block
    (P-7.10/P-7.11); a later local-model run (LUSD 26052560) is removed from the tmp copy so
    `latest_bundle` reads the recorded block - the tests read the recorded state."""
    import shutil
    for tok, blk in RECORDED.items():
        for sub in ("out/bundles", "out/trees", "out/stress", "out/evaluation"):
            for f in (root / sub / tok).glob("*.json"):
                if f.stem.isdigit() and int(f.stem) > blk:
                    f.unlink()
        for d in (root / "out/report" / tok).glob("*"):
            if d.name.isdigit() and int(d.name) > blk:
                shutil.rmtree(d)
    return root


def _sections(page: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for block in page.split("## section_id: ")[1:]:
        sid, _, body = block.partition("\n")
        out[sid.strip()] = [re.sub(r"^\[\d+\] ", "", ln) for ln in body.splitlines()
                            if re.match(r"^\[\d+\] ", ln)]
    return out


def _locate(d: dict, secs: dict[str, list[str]]) -> dict:
    loc = dict(d["location"])
    if loc["paragraph_index"] == -1:
        paras = secs.get(loc["section_id"], [])
        hit = [i for i, p in enumerate(paras) if loc["quoted_span"] in p]
        loc["paragraph_index"] = hit[0] if hit else -1
    return {**d, "location": loc}


class FakeClient:
    version = "fake"
    digest = "sha256:fake"

    def __init__(self, case: str):
        self.dir = FIXTURES / case
        self.judgments = 0
        self.calls: list[str] = []
        self.slot_calls: dict[str, int] = {}
        self.requests: list[dict] = []
        self._full: dict[str, list[str]] = {}
        self._sent: set = set()

    def _load(self, name: str):
        p = self.dir / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def _criterion(self, cid: str, page: str) -> dict:
        env = self._load(f"env{self.judgments}.json") or self._load("env1.json") or {}
        crit = next((c for c in env.get("criteria", []) if c["id"] == cid),
                    {"items": [], "defects": []})
        secs = _sections(page)
        items = []
        if (cid, "items") not in self._sent:
            self._sent.add((cid, "items"))
            items = [json.loads(i) if isinstance(i, str) else i for i in crit["items"]]
        defects = []
        for n, d in enumerate(crit["defects"]):
            if (cid, n) in self._sent:
                continue
            span, sid = d["location"]["quoted_span"], d["location"]["section_id"]
            here = any(span in p for p in secs.get(sid, []))
            anywhere = any(span in p for p in self._full.get(sid, []))
            if here or not anywhere:
                self._sent.add((cid, n))
                defects.append(_locate(d, self._full))
        return {"items": items, "defects": defects}

    def chat(self, body: dict) -> dict:
        kind = body["format"].get("title")
        user = json.loads(body["messages"][1]["content"])
        self.calls.append(kind)
        self.requests.append({"kind": kind, "model": body["model"], "think": body["think"],
                              "options": body["options"], "user_keys": sorted(user),
                              "slot": user.get("slot"),
                              "pass1_defects": len(user.get("pass1_defects", []))})
        done, text = "stop", None
        if kind == "SlotProse":
            slot = user["slot"]
            self.slot_calls[slot] = self.slot_calls.get(slot, 0) + 1
            first = self._load("generation_first.json") or {}
            obj = (first[slot] if slot in first and self.slot_calls[slot] == 1
                   else self._load("generation.json")[slot])
        elif kind == "SlotRevision":
            rec = (self._load("revision.json") or {}).get(user["slot"])
            obj = rec or {"references_field_ids": [], "replacements": [
                {"quoted_span": d["location"]["quoted_span"],
                 "replacement": d["location"]["quoted_span"]}
                for d in user["pass1_defects"]
                if d["location"]["quoted_span"] in user["pass1_text"]]}
        elif kind and kind.startswith("OutLLM"):
            cid = f"LLM-{kind[-2:]}"
            if cid == "LLM-03":                      # the first call of every judgment
                self.judgments += 1
                self._full = _sections(user["page"])
                self._sent = set()
            mode = self.dir / "judge_mode.txt"
            mode = mode.read_text(encoding="utf-8").strip() if mode.exists() else ""
            obj = self._criterion(cid, user["page"])
            if mode == "malformed":
                text = '{"items": "not a list"}'
            elif mode == "refusal":
                text = ""
            elif mode == "max_tokens":
                done, text = "length", '{"items": [{"quoted_span": "'
        else:
            obj = self._load("remediation.json") or {"items": [
                {"defect_index": d["index"], "addressed": "yes", "reason": "recorded"}
                for d in user["pass1_defects"]]}
        if text is None:
            text = json.dumps(obj, ensure_ascii=False)
        n = len(body["messages"][0]["content"]) + len(body["messages"][1]["content"])
        return {"model": body["model"], "message": {"role": "assistant", "content": text},
                "done": True, "done_reason": done, "prompt_eval_count": n // 3,
                "eval_count": len(text) // 3, "prompt_eval_duration": 1, "eval_duration": 1,
                "total_duration": 2}
