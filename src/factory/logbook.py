"""B-6: the quarantine log — DET-60's closed schema, written at `out/logs/`.

The log is public (§8.1.3) and is what DET-86's first-run gate and DET-59's
consecutive-quarantine counter read. Committed, per P-3.05.
"""

from __future__ import annotations

import json
import pathlib

from factory.schema import Bundle, LogEntry

RESOLUTION_TYPES = frozenset(
    {"template_change", "intake_change", "config_change",
     "data_correction", "code_fix", "rubric_change"}
)


class Logbook:
    """Append-only log of quarantine events, one JSON array per token."""

    def __init__(self, path: pathlib.Path):
        self.path = path
        self.entries: list[LogEntry] = []
        if path.exists():
            self.entries = [LogEntry(**e) for e in json.loads(path.read_text("utf-8"))]

    def append(self, entry: LogEntry) -> None:
        if entry.resolution_type is not None and entry.resolution_type not in RESOLUTION_TYPES:
            # DET-13(e): no override or output-edit value exists
            raise ValueError(f"illegal resolution_type: {entry.resolution_type}")
        if (entry.resolution_type is None) != (entry.resolution_date is None):
            raise ValueError("DET-60: resolution_type and resolution_date set together")
        self.entries.append(entry)

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [e.model_dump() for e in self.entries]
        self.path.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False) + "\n",
            encoding="utf-8", newline="")

    # --- what downstream gates read from the log ----------------------------

    def has_published_entry(self, token: str) -> bool:
        """DET-86's letter. In Step 3 nothing publishes, hence the convention
        below — see `is_first_run`."""
        return any(e.token == token and e.trigger == "published" for e in self.entries)

    def open_levels(self, token: str) -> list[int]:
        return [e.level for e in self.entries
                if e.token == token and e.resolution_date is None]

    def consecutive_quarantined_runs(self, token: str) -> int:
        """DET-59: counted from the tail; a published run resets it."""
        n = 0
        for e in reversed(self.entries):
            if e.token != token:
                continue
            if e.trigger == "published":
                break
            if e.level in (2, 3):
                n += 1
        return n


def is_first_run(bundles_dir: pathlib.Path, token: str) -> bool:
    """DET-86 under the **named Step-3 convention (P-3.14)**.

    `first_run = true` iff no prior successfully-validated bundle exists for the
    token. The rubric's letter keys on a *published* entry, and Step 3 publishes
    nothing — under the letter the delta machinery would never run. The
    convention is **monotone in the fail-closed direction**: it makes
    `first_run` false in strictly more cases than the letter requires, and
    `false` is the state that runs MORE checks. **Retires at Step 7**, when
    publication exists and the letter resumes.
    """
    d = bundles_dir / token
    return not (d.exists() and any(d.glob("*.json")))


def load_prior(bundles_dir: pathlib.Path, token: str,
               before_block: int) -> Bundle | None:
    """The prior bundle the delta checks compare against — `is_first_run`'s
    exact counterpart, under the same P-3.14 convention and the same scope.

    DET-62's letter defines `previous = last successful run`. A bundle in
    `out/bundles/<token>/` **is** a successfully-validated run: promotion is
    structurally unreachable on a Level 3 (the harness raises before anything
    is written), so presence in that directory is the validation record. The
    prior is therefore the highest `run_block` strictly below this run's.

    Returns None exactly when `is_first_run` is true. The two must never
    disagree, and DET-86 is what checks that they do not.
    """
    d = bundles_dir / token
    if not d.exists():
        return None
    blocks = sorted(int(p.stem) for p in d.glob("*.json") if p.stem.isdigit())
    prior = [b for b in blocks if b < before_block]
    if not prior:
        return None
    return Bundle.model_validate_json(
        (d / f"{prior[-1]}.json").read_text(encoding="utf-8"))
