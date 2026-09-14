"""The bundle store's first-run and prior-bundle readers (DET-86, P-3.14).

B-12 (P-7.01 R14): `Logbook` retired - `eventlog.py` is the one log, and its
quarantine lifecycle (`open_entries`, `consecutive_quarantined_runs`,
`plan_quarantine`, `resolve`) replaced `open_levels` and the per-entry counter.
`is_first_run` and `load_prior` stay here.
"""

from __future__ import annotations

import pathlib

from factory.schema import PriorBundle


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
               before_block: int) -> PriorBundle | None:
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
    # Read through the PRIOR VIEW, never the full current `Bundle`: the store
    # holds older shapes by construction, and validating history against the
    # present schema is what broke the P-3.46 tree. See `PriorBundle`.
    return PriorBundle.model_validate_json(
        (d / f"{prior[-1]}.json").read_text(encoding="utf-8"))
