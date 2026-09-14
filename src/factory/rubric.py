"""B-12 (inventory finding 8): rubric §3's printed trigger table, parsed.

DET-12's S0 limb compares the runtime table to THIS parse of
`docs/context/rubic_v1.md` - it compared the runtime table to a copy of itself
until B-12 (`run.py`'s `dict(TRIGGER_TABLE)`). The renderer's flag names and
sections read the same parse, so there is one reader of §3.

Row shape: `| ID | Trigger | Level | Section (flag renders) | Defined | Computing owner |`.
NAMED DEFAULT: a split-level cell ("2 (≥ 5% exit depth) / 1 (< 5%)", T-18) yields
every level in printed order; the runtime table carries the first.
"""

from __future__ import annotations

import pathlib
import re

ROW = re.compile(r"^\| (T-\d\d) \| ([^|]+?) \| ([^|]+?) \| ([^|]+?) \| [^|]* \| ([^|]*) \|$", re.M)


def trigger_table(rubric_text: str) -> dict[str, dict]:
    head = rubric_text.find("## 3. Trigger table")
    if head < 0:
        raise ValueError("rubric §3 trigger table not found")
    body = rubric_text[head:]
    end = body.find("\n## ", 5)
    body = body if end < 0 else body[:end]
    out: dict[str, dict] = {}
    for m in ROW.finditer(body):
        levels = [int(x) for x in re.findall(r"(?:^|/ )([123])\b", m.group(3).strip())]
        if m.group(1) in out:
            raise ValueError(f"rubric §3: duplicate row {m.group(1)}")
        out[m.group(1)] = {"name": m.group(2).strip(), "levels": levels,
                           "section": m.group(4).strip(),
                           # B-13: the computing owners' entry ids, "DET-29(a)" -> "DET-29"
                           "owners": sorted(set(re.findall(r"DET-\d\d", m.group(5))))}
    if not out:
        raise ValueError("rubric §3: no trigger rows parsed")
    return out


def read_trigger_table(repo: pathlib.Path) -> dict[str, dict]:
    text = (repo / "docs/context/rubic_v1.md").read_bytes().replace(b"\r\n", b"\n").decode()
    return trigger_table(text)
