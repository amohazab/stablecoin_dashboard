"""1b: the typed event log — the hash chain DET-10(a), DET-77 and DET-86 need.

Finding that produced this module (P-3.43): those three entries all chain to
"the log", and no log existed. `LogEntry` (DET-60's closed schema) holds only
quarantine triggers — no set-file hash, `level` constrained to 1/2/3 — so a
freeze is not representable in it, `out/logs/` held only `.gitkeep`, and the
P-3.28 freeze left no machine-readable event. PROGRESS entries had been serving
as the log.

**Interpretive extension, ruled P-3.43, queued for the rubric revision.**
DET-60's "any additional field = fail" scopes to `quarantine` entries, which
are exactly its closed schema plus `type`. The other three types are outside
DET-60's scope; the amendment queue carries: define the event log's entry
types, scope DET-60 to trigger entries, and have DET-77 / DET-86 / DET-10(a)
reference this log by name.

The file is COMMITTED, not gitignored — it *is* the chain. One JSON object per
line so an append never rewrites history, serialised under O-2 (sorted keys,
tight separators, no float).
"""

from __future__ import annotations

import json
import pathlib
from typing import Annotated, Literal

from pydantic import BaseModel, Field

# Named implementer default (P-3.43): the `token` on a SHEET-level event is the
# token whose sheet it is — "crvUSD" — not a sentinel. The intake sheet is
# per-token and `last_event` filters by token; a null or "all" token would make
# that filter a special case at every call site.


class FreezeEvent(BaseModel, extra="forbid"):
    type: Literal["freeze"] = "freeze"
    date: str
    token: str
    freeze_block: int
    set_file_hash: str
    set_file_path: str
    source: str


class IntakeTriggerEvent(BaseModel, extra="forbid"):
    type: Literal["intake_trigger"] = "intake_trigger"
    date: str
    token: str
    sheet_hash: str
    # None where the edit preceded any freeze — backfilled entry 1's shape.
    # DET-10(a) FAILS CLOSED on a null here: no chain is not a passing chain.
    set_file_hash: str | None = None
    source: str


class PublishedEvent(BaseModel, extra="forbid"):
    """Reserved. First written at Step 7, when publication exists and DET-86's
    letter resumes from the P-3.14 convention."""

    type: Literal["published"] = "published"
    date: str
    token: str
    bundle_hash: str


class QuarantineEvent(BaseModel, extra="forbid"):
    """DET-60's closed schema exactly, plus `type`. DET-60's additional-field
    prohibition applies to THIS type and no other."""

    type: Literal["quarantine"] = "quarantine"
    date: str
    token: str
    trigger: str
    level: Literal[1, 2, 3]
    resolution_type: str | None = None
    resolution_date: str | None = None


Event = Annotated[
    FreezeEvent | IntakeTriggerEvent | PublishedEvent | QuarantineEvent,
    Field(discriminator="type"),
]

_ADAPTER: dict[str, type[BaseModel]] = {
    "freeze": FreezeEvent,
    "intake_trigger": IntakeTriggerEvent,
    "published": PublishedEvent,
    "quarantine": QuarantineEvent,
}


def _line(entry: BaseModel) -> str:
    return json.dumps(entry.model_dump(), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False) + "\n"


def read(path: pathlib.Path) -> list[BaseModel]:
    """Every entry, in file order. A missing file is an empty log."""
    if not path.exists():
        return []
    out: list[BaseModel] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        obj = json.loads(raw)
        out.append(_ADAPTER[obj["type"]](**obj))
    return out


def append(path: pathlib.Path, entry: BaseModel) -> None:
    """Append one entry. Never rewrites, never reorders."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as fh:
        fh.write(_line(entry))


def last_event(entries: list[BaseModel], types: tuple[str, ...],
               token: str) -> BaseModel | None:
    """The most recent entry of any of `types` for `token`, or None.

    "Most recent" is FILE ORDER, not `date` order: the log is append-only, so
    file order is the order events were recorded, and two events sharing a date
    (the 2026-09-04 pair) must not resolve by a tie-break that has no meaning.
    """
    for e in reversed(entries):
        if e.type in types and e.token == token:
            return e
    return None


def append_intake_trigger(path: pathlib.Path, *, date: str, token: str,
                          sheet_hash: str, set_file_hash: str | None,
                          source: str) -> None:
    """The (d)-machinery's last step (ruled P-3.46 R1's neighbourhood).

    A sheet edit is a human act; nothing in the pipeline writes this event. The
    enforcement is DET-77's limb — a sheet edit without its event fails the next
    run at Level 3 — and the honest fix is to append the event dated when the
    edit happened. Documented, deliberately not tool-enforced: no CLI.
    """
    append(path, IntakeTriggerEvent(date=date, token=token,
                                    sheet_hash=sheet_hash,
                                    set_file_hash=set_file_hash, source=source))
