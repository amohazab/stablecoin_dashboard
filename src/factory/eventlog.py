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


# ---- B-12: the quarantine lifecycle (P-7.01 R14; inventory H.2/H.3) -----------------
#
# NAMED DEFAULTS (R14). A resolution is a SECOND `quarantine` line repeating the fire
# line's `{date, token, trigger, level}` with `resolution_type` / `resolution_date` set;
# "open" = a fire line with no matching resolution line. The entry id is
# `<token>:<line>` - the fire line's 1-based line number in the token's file, derived,
# never stored. A run = a distinct `(token, date)` among Level 2/3 fire lines after
# the token's last `published` line. Level 1 follows lifecycle (ii): an open entry
# satisfies later runs while its trigger keeps firing, and the run where it stops
# firing resolves it with `data_correction`. Level 2/3 lines are written once per run
# (per (token, date, trigger, level)) and are resolved only by an explicit
# `resolution_type` with its DET-87 evidence - never automatically (B-12 default).
# The run's `date` is the UTC date of the bundle's block timestamp, so a re-run of
# the report stage over the same bundle writes nothing new.

RESOLUTION_TYPES = frozenset({"template_change", "intake_change", "config_change",
                              "data_correction", "code_fix", "rubric_change"})


def _key(e) -> tuple:
    return (e.date, e.token, e.trigger, e.level)


def quarantine_lines(entries: list[BaseModel], token: str) -> list[tuple[int, QuarantineEvent]]:
    """`(line number, entry)` for the token's quarantine lines, 1-based over the file."""
    return [(i, e) for i, e in enumerate(entries, 1)
            if e.type == "quarantine" and e.token == token]


def entry_id(token: str, line: int) -> str:
    return f"{token}:{line}"


def open_entries(entries: list[BaseModel], token: str) -> list[tuple[str, QuarantineEvent]]:
    """`(entry id, fire line)` for every fire line with no matching resolution line."""
    lines = quarantine_lines(entries, token)
    resolved = {_key(e) for _, e in lines if e.resolution_date is not None}
    return [(entry_id(token, i), e) for i, e in lines
            if e.resolution_date is None and _key(e) not in resolved]


def last_published(entries: list[BaseModel], token: str) -> PublishedEvent | None:
    return last_event(entries, ("published",), token)


def consecutive_quarantined_runs(entries: list[BaseModel], token: str) -> int:
    """DET-59: distinct run dates among Level 2/3 fire lines after the last
    `published` line - runs, not entries."""
    start = 0
    for i, e in enumerate(entries):
        if e.type == "published" and e.token == token:
            start = i + 1
    return len({e.date for e in entries[start:]
                if e.type == "quarantine" and e.token == token and e.level in (2, 3)
                and e.resolution_date is None})


def plan_quarantine(entries: list[BaseModel], token: str, date: str,
                    fired: list[tuple[str, int]]) -> list[QuarantineEvent]:
    """The lines this run appends, given `fired` = the run's `(trigger, level)`s.

    Level 1: a fire line only when no open entry exists for (trigger, level); an open
    Level-1 entry whose trigger did not fire this run gets its resolution line
    (`data_correction`, dated this run). Level 2/3: one fire line per run date."""
    fired_set = set(fired)
    opened = open_entries(entries, token)
    new: list[QuarantineEvent] = []
    for trig, lvl in sorted(fired_set):
        if lvl == 1:
            if any(e.trigger == trig and e.level == 1 for _, e in opened):
                continue
        elif any(e.trigger == trig and e.level == lvl and e.date == date
                 for _, e in quarantine_lines(entries, token)):
            continue
        new.append(QuarantineEvent(date=date, token=token, trigger=trig, level=lvl))
    for _, e in opened:
        if e.level == 1 and (e.trigger, 1) not in fired_set:
            new.append(QuarantineEvent(date=e.date, token=token, trigger=e.trigger, level=1,
                                       resolution_type="data_correction",
                                       resolution_date=date))
    return new


def resolve(path: pathlib.Path, fire: QuarantineEvent, resolution_type: str,
            resolution_date: str) -> None:
    """An explicit resolution line (Level 2/3, or any level by hand). DET-13(e)'s
    closed set; DET-87's evidence is checked at the next report stage."""
    if resolution_type not in RESOLUTION_TYPES:
        raise ValueError(f"illegal resolution_type: {resolution_type}")
    append(path, QuarantineEvent(date=fire.date, token=fire.token, trigger=fire.trigger,
                                 level=fire.level, resolution_type=resolution_type,
                                 resolution_date=resolution_date))
