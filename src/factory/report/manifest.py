"""B-10: `template_hash` and the report manifest (P-7.01 R3).

`template_hash` = sha256 over the sorted `(repo-relative path, LF-normalised
bytes)` pairs of `templates/**` plus `src/factory/report/{render,svg}.py` (NAMED
DEFAULT, Amin's ruling at B-11c: the renderer shapes the page as much as the
templates do): each pair is `path\\0bytes\\0`. Prompts live under `templates/`
from B-13, so a prompt patch is a `template_change` with evidence.

`report_hash = sha256(bundle_hash ‖ tree_hash ‖ stress_hash ‖ table_hash ‖
template_hash ‖ pipeline_version ‖ sheet_hash)`. NAMED DEFAULT: `‖` is plain
concatenation of the seven UTF-8 strings in that order, no separator - every
hash is fixed-width hex, so only the two short tail fields could run together,
and they are the last two.
"""

from __future__ import annotations

import hashlib
import pathlib

ORDER = ("bundle_hash", "tree_hash", "stress_hash", "table_hash", "template_hash",
         "pipeline_version", "sheet_hash")


TEMPLATE_CODE = ("src/factory/report/render.py", "src/factory/report/svg.py")


def template_files(repo: pathlib.Path) -> list[pathlib.Path]:
    files = [x for x in (repo / "templates").rglob("*") if x.is_file()]
    return sorted([*files, *(repo / c for c in TEMPLATE_CODE)],
                  key=lambda p: p.relative_to(repo).as_posix())


def template_hash(repo: pathlib.Path) -> str:
    h = hashlib.sha256()
    for p in template_files(repo):
        rel = p.relative_to(repo).as_posix()
        h.update(rel.encode("utf-8") + b"\0" + p.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


def report_hash(parts: dict[str, str]) -> str:
    return hashlib.sha256("".join(parts[k] for k in ORDER).encode("utf-8")).hexdigest()


def build(token: str, run_block: int, parts: dict[str, str]) -> dict:
    missing = [k for k in ORDER if not parts.get(k)]
    if missing:
        raise ValueError(f"manifest components absent: {missing}")
    return {"token": token, "run_block": run_block, **{k: parts[k] for k in ORDER},
            "report_hash": report_hash(parts)}
