"""B-6: the S0/S1 deterministic harness — one function per DET id.

Stage order S0 -> S1 (rubric §0.2); a stage's failure stops at that stage's
consequence. **Fail-closed (DET-85, Step-3 scope): a missing result or an
exception is `error`, never `pass` and never `not_applicable`**, and any Level 3
makes bundle promotion unreachable — enforced structurally in `run_harness`,
which raises rather than returning a flag a caller could walk past (the B-3b
lesson, P-3.27).
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from factory.provenance import AnalystSupplied, ContractRead
from factory.schema import Bundle, GateResult

# Trigger table, mirrored from rubric §3. DET-12 compares this to the printed
# table row-for-row at S0; a mismatch means the pipeline does not start.
TRIGGER_TABLE: dict[str, int] = {
    "T-01": 1, "T-02": 1, "T-03": 1, "T-04": 1, "T-05": 1, "T-06": 1, "T-07": 1,
    "T-08": 1, "T-09": 2, "T-10": 2, "T-11": 2, "T-12": 2, "T-13": 3, "T-14": 3,
    "T-15": 3, "T-16": 1, "T-17": 1, "T-18": 2, "T-19": 1, "T-20": 1, "T-21": 1,
    "T-22": 1, "T-23": 2, "T-24": 2, "T-25": 2, "T-26": 1, "T-27": 1,
}

STALENESS_LIMIT_DAYS = 92  # R-1
DET83_FRESHNESS_LIMIT_S = 3600


class Level3(Exception):
    """A Level-3 condition. Nothing downstream computes; no promotion."""


@dataclass
class Check:
    entry_id: str
    stage: str            # "S0" | "S1"
    level_on_fail: int
    fn: Callable


@dataclass
class HarnessOutcome:
    results: list[GateResult]
    triggers: list[tuple[str, int]]      # (trigger_id, level) fired this run

    @property
    def worst_level(self) -> int:
        return max((lvl for _, lvl in self.triggers), default=0)

    @property
    def all_pass(self) -> bool:
        return all(r.result == "pass" for r in self.results)


# --------------------------------------------------------------- S0 --------


def det_02(b: Bundle, ctx) -> None:
    """Label config address-keyed; node classification fields (R-21)."""
    seen = set()
    for row in ctx["labels"].values():
        if row.address in seen:
            raise Level3(f"DET-02: duplicate config address {row.address}")
        seen.add(row.address)
        if row.lst_discount_applies and row.node_class != "volatile":
            raise Level3(f"DET-02(i): {row.symbol}")
    for n in b.nodes:
        if n.label_source_address != n.address:
            raise Level3(f"DET-02: label_source_address mismatch on {n.symbol}")


def det_12(b: Bundle, ctx) -> None:
    """Declare-your-level: the runtime trigger table equals the printed one."""
    printed = ctx["printed_trigger_table"]
    if TRIGGER_TABLE != printed:
        diff = set(TRIGGER_TABLE.items()) ^ set(printed.items())
        raise Level3(f"DET-12: trigger table mismatch {sorted(diff)[:4]}")


def det_77(b: Bundle, ctx) -> None:
    """Sheet fields present, typed, dated; sheet version stamped (R-47)."""
    if b.header.sheet_hash != ctx["sheet"]["sheet_hash"]:
        raise Level3("DET-77: bundle sheet_hash != mirrored sheet version")
    for field in ("near_bound_threshold", "counterparties", "attribution_method"):
        if field not in ctx["sheet"]:
            raise Level3(f"DET-77: sheet field absent: {field}")


# --------------------------------------------------------------- S1 --------


def det_83(b: Bundle, ctx) -> None:
    """Pinned block freshness (G-4 — untraceable pointer, A2/P-3.01)."""
    if b.header.det83_delta_s > DET83_FRESHNESS_LIMIT_S:
        raise Level3(f"DET-83: freshness {b.header.det83_delta_s}s > {DET83_FRESHNESS_LIMIT_S}")


def det_86(b: Bundle, ctx) -> None:
    """First-run gating under the NAMED Step-3 convention (P-3.14).

    `first_run = true` iff no prior successfully-validated bundle. Monotone in
    the fail-closed direction; retires at Step 7.
    """
    if b.header.first_run != ctx["is_first_run"]:
        raise Level3("DET-86: first_run disagrees with the bundle store")
    if not b.header.first_run and ctx.get("prior_bundle") is None:
        raise Level3("DET-86: not first run but no retrievable prior bundle")


def det_01(b: Bundle, ctx) -> None:
    """Address-keyed entities; no duplicate address within a table."""
    for table, rows in (("markets", b.markets), ("nodes", b.nodes)):
        addrs = [r.address for r in rows]
        if len(addrs) != len(set(addrs)):
            raise Level3(f"DET-01: duplicate address in {table}")
        for a in addrs:
            if a != a.lower():
                raise Level3(f"DET-01: non-lowercase address in {table}")


def det_03(b: Bundle, ctx) -> None:
    """Principal / interest separation (anti-tautology, C-2/C-3)."""
    for m in b.markets:
        if m.gross_debt_sum != m.principal_sum + m.accrued_interest_sum:
            raise Level3(f"DET-03: identity broken on {m.symbol}")
        if m.principal_sum < 0 or m.accrued_interest_sum < 0:
            raise Level3(f"DET-03: negative component on {m.symbol}")


def det_04(b: Bundle, ctx) -> tuple[str, int] | None:
    """Enumeration provenance; analyst source older than 92 d -> T-16."""
    stale = []
    for root in ctx["roots"].values():
        if root.stale_days(ctx["today"]) > STALENESS_LIMIT_DAYS:
            stale.append(root.id)
    for m in b.markets:
        if "total_debt" not in m.reads:
            raise Level3(f"DET-04: no provenance on {m.symbol}")
    return ("T-16", 1) if stale else None


def det_07(b: Bundle, ctx) -> None:
    """Supply origination: class assigned from the factory address."""
    for m in b.markets:
        if m.origination_class not in ("mint", "lend"):
            raise Level3(f"DET-07: bad origination_class on {m.symbol}")
    if any(m.origination_class == "lend" for m in b.markets):
        raise Level3("DET-07: lend rows must not carry backing inputs in Step 3")


def det_20(b: Bundle, ctx) -> None:
    """Stabilizer rows complete; ceilings per-run reads (C-2 key set)."""
    required = {"current_debt", "balance", "debt_ceiling"}
    for op in b.stabilizer.operations:
        missing = required - set(op.reads)
        if missing:
            raise Level3(f"DET-20: {op.operation_address} missing {sorted(missing)}")


def det_21(b: Bundle, ctx) -> None:
    """Utilization replay, with the ceiling-zero edge (R-11)."""
    for op in b.stabilizer.operations:
        if op.debt_ceiling == 0:
            continue
        want = Decimal(op.current_debt) / Decimal(op.debt_ceiling)
        if abs(want - op.utilization) > Decimal("1e-6"):
            raise Level3(f"DET-21: utilization replay failed on {op.operation_address}")


def det_61(b: Bundle, ctx) -> tuple[str, int] | None:
    """Mechanism near bound -> T-07 at the sheet threshold (default 0.80)."""
    thr = Decimal(str(ctx["sheet"].get("near_bound_threshold", 0.80)))
    for op in b.stabilizer.operations:
        if op.utilization is not None and op.utilization >= thr:
            return ("T-07", 1)
    return None


def det_63(b: Bundle, ctx) -> tuple[str, int] | None:
    """Market-count change; first run -> no trigger, disclosed."""
    if b.header.first_run:
        if b.first_run_literals is None:
            raise Level3("DET-63: first run without its literal")
        return None
    prior = ctx["prior_bundle"].counts.mint_market_count
    now = b.counts.mint_market_count
    if now > prior:
        return ("T-06", 1)
    if now < prior:
        return ("T-12", 2)
    return None


def det_62(b: Bundle, ctx) -> tuple[str, int] | None:
    """Supply jump, two-branch; first run -> literal, no trigger."""
    if b.header.first_run:
        return None
    prior = ctx["prior_bundle"].supply.total_supply
    if prior == 0:
        raise Level3("DET-62: prior supply is zero")
    jump = abs(Decimal(b.supply.total_supply - prior)) / Decimal(prior)
    if jump <= Decimal("0.25"):
        return None
    # confirmation sources: DefiLlama + Etherscan (P-3.19)
    sources = ctx.get("supply_confirmations") or {}
    if len(sources) < 2 or any(v is None for v in sources.values()):
        return ("T-14", 3)
    ok = all(abs(Decimal(v - b.supply.total_supply)) / Decimal(b.supply.total_supply)
             <= Decimal("0.05") for v in sources.values())
    return ("T-05", 1) if ok else ("T-14", 3)


def det_65(b: Bundle, ctx) -> tuple[str, int] | None:
    """Composition shift; first run -> literal."""
    if b.header.first_run:
        return None
    prior = {n.address: n.share_of_backing for n in ctx["prior_bundle"].nodes}
    for n in b.nodes:
        if n.address in prior and abs(n.share_of_backing - prior[n.address]) > Decimal("0.10"):
            return ("T-04", 1)
    return None


def det_68(b: Bundle, ctx) -> None:
    """A1-A8 complete, enum closed; absence rows carry F4 provenance."""
    if len({r.power for r in b.admin_surface}) != 9:
        raise Level3("DET-68: nine A1 powers required")
    for r in b.admin_surface:
        if r.holder_type == "none" and isinstance(r.provenance, ContractRead):
            raise Level3(f"DET-68: none-holder row {r.power} needs absence provenance")


def det_08(b: Bundle, ctx) -> tuple[str, int] | None:
    """Unlisted node routing: U >= 5% -> T-09 (L2); 0 < U < 5% -> T-01 (L1)."""
    u = sum((n.share_of_backing for n in b.nodes if n.label == "unlisted"), Decimal(0))
    if u == 0:
        return None
    return ("T-09", 2) if u >= Decimal("0.05") else ("T-01", 1)


def det_82(b: Bundle, ctx) -> None:
    """Position-set completeness, 1e-9 (G-3 — untraceable pointer)."""
    for m in b.markets:
        if not m.position_completeness.ok:
            raise Level3(f"DET-82: {m.symbol} rel_diff "
                         f"{m.position_completeness.relative_diff}")


def det_33(b: Bundle, ctx) -> tuple[str, int] | None:
    """Bridged supply: amounts only; type never inferred (C-1). T-19 on unresolved."""
    if b.supply.bridge_state != "populated":
        # three-state: absent config is a fact about the config (P-3.29)
        if "no bridge" not in b.supply.bridge_disclosure.lower():
            raise Level3("DET-33: bridge state must be disclosed")
        return None
    for br in b.supply.bridges:
        if "bridge_type" not in br.reads:
            raise Level3(f"DET-33: {br.bridge_address} bridge_type without provenance")
        if not isinstance(br.reads["bridge_type"], (ContractRead, AnalystSupplied)):
            raise Level3("DET-33: bridge_type provenance must be read or analyst-supplied")
    if any(br.bridge_type == "unresolved" for br in b.supply.bridges):
        return ("T-19", 1)
    return None


def det_55(b: Bundle, ctx) -> None:
    """Oracle-dependency table: a row per priced node, ema_window typed."""
    priced = {n.address for n in b.nodes if n.value > 0}
    covered = {r.node_address for r in b.oracle_rows}
    if priced - covered:
        raise Level3(f"DET-55: no oracle row for priced node(s) {sorted(priced - covered)}")
    for r in b.oracle_rows:
        if r.update_condition.ema_window_s <= 0:
            raise Level3(f"DET-55: non-positive ema_window_s on {r.node_address}")


CHECKS: list[Check] = [
    Check("DET-02", "S0", 3, det_02), Check("DET-12", "S0", 3, det_12),
    Check("DET-77", "S0", 3, det_77),
    Check("DET-83", "S1", 3, det_83), Check("DET-86", "S1", 3, det_86),
    Check("DET-01", "S1", 3, det_01), Check("DET-03", "S1", 3, det_03),
    Check("DET-04", "S1", 3, det_04), Check("DET-07", "S1", 2, det_07),
    Check("DET-20", "S1", 3, det_20), Check("DET-21", "S1", 2, det_21),
    Check("DET-33", "S1", 3, det_33), Check("DET-55", "S1", 3, det_55),
    Check("DET-61", "S1", 1, det_61), Check("DET-62", "S1", 3, det_62),
    Check("DET-63", "S1", 2, det_63), Check("DET-65", "S1", 2, det_65),
    Check("DET-68", "S1", 3, det_68), Check("DET-08", "S1", 2, det_08),
    Check("DET-82", "S1", 3, det_82),
]


def run_harness(bundle: Bundle, ctx: dict) -> HarnessOutcome:
    """Run S0 then S1, fail-closed. A Level 3 RAISES — promotion unreachable.

    DET-85's Step-3 scope: every check yields a result; an exception is
    recorded as `error`, never `pass` and never `not_applicable`.
    """
    results: list[GateResult] = []
    triggers: list[tuple[str, int]] = []
    for stage in ("S0", "S1"):
        for chk in (c for c in CHECKS if c.stage == stage):
            try:
                fired = chk.fn(bundle, ctx)
                results.append(GateResult(entry_id=chk.entry_id, result="pass"))
                if fired:
                    triggers.append(fired)
            except Level3 as exc:
                results.append(GateResult(entry_id=chk.entry_id, result="fail"))
                raise Level3(f"{chk.entry_id}: {exc}") from exc
            except Exception as exc:                       # DET-85 fail-closed
                results.append(GateResult(entry_id=chk.entry_id, result="error"))
                raise Level3(f"{chk.entry_id} harness error (T-25): {exc}") from exc
    if any(lvl >= 2 for _, lvl in triggers):
        raise Level3(f"Level 2 trigger(s): {[t for t, lvl in triggers if lvl >= 2]}")
    return HarnessOutcome(results, triggers)


def today() -> _dt.date:
    return _dt.date.today()
