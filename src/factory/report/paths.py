"""B-10: the flat table's `source_path` - where a row's value is copied from.

A path is `<artifact>/<segment>/...`, artifact ∈ {bundle, tree, stress, mirror}.
A segment is a dict key, a list index, or a selector `[key=value]` (or
`[k1=v1,k2=v2]`) that picks the ONE list element whose fields match. The same
resolver builds the table and replays it (DET-84), so a row can only ever hold
what its owner field holds. Pure: no I/O.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

SEL = re.compile(r"^\[(.+)\]$")


class PathError(KeyError):
    """A `source_path` that resolves to nothing - DET-84's "no owner"."""


def split(path: str) -> list[str]:
    return path.split("/")


def resolve(sources: dict[str, Any], path: str) -> Any:
    parts = split(path)
    if parts[0] not in sources:
        raise PathError(f"{path}: unknown artifact {parts[0]!r}")
    cur = sources[parts[0]]
    for seg in parts[1:]:
        m = SEL.match(seg)
        if m:
            want = dict(kv.split("=", 1) for kv in m.group(1).split(","))
            if not isinstance(cur, list):
                raise PathError(f"{path}: selector {seg} on a non-list")
            hits = [x for x in cur if isinstance(x, dict)
                    and all(str(x.get(k)) == v for k, v in want.items())]
            if len(hits) != 1:
                raise PathError(f"{path}: selector {seg} matched {len(hits)}")
            cur = hits[0]
        elif isinstance(cur, list):
            try:
                cur = cur[int(seg)]
            except (ValueError, IndexError) as exc:
                raise PathError(f"{path}: index {seg}") from exc
        elif isinstance(cur, dict):
            if seg not in cur:
                raise PathError(f"{path}: key {seg!r} absent")
            cur = cur[seg]
        else:
            raise PathError(f"{path}: {seg!r} below a scalar")
    return cur


def jsonable(text: str) -> Any:
    """An artifact's serialised JSON, the form every row value is copied from."""
    return json.loads(text)


def same(a: Any, b: Any, tol: Decimal = Decimal("1e-6")) -> bool:
    """DET-84's comparison: 1e-6 on numerics, equality otherwise."""
    if a == b:
        return True
    if isinstance(a, bool) or isinstance(b, bool):
        return False
    try:
        return abs(Decimal(str(a)) - Decimal(str(b))) <= tol
    except (InvalidOperation, ValueError, TypeError):
        return False
