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

from factory.provenance import AbsenceRead, AnalystSupplied, ContractRead
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


class NotYetImplemented(Exception):
    """A ruled check whose token-specific limb is not built yet (P-3.44).

    Fail-loud, house style: `run_harness` records any non-`Level3` exception
    as `error` and re-raises it as a Level 3 (DET-85), so an unbuilt limb
    stops the run instead of passing silently. Never caught in this module.
    """


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
    """Sheet fields present, typed, dated; sheet version stamped (R-47).

    Two limbs. The mirror equality was always here. The SECOND limb — the
    entry's letter, "sheet version at the last logged `intake_trigger`" — is
    new (P-3.43 ruling 1) and is why the event log exists: the mirror check
    compares the bundle to a file this run loaded, which cannot detect that
    file being edited. The log is the chain that can.

    Consequence, stated because it changes the (d)-machinery: a sheet edit
    without a logged `intake_trigger` fails HERE at Level 3. That is the
    intended gate; the fix is to append the event dated when the edit happened
    (`eventlog.append_intake_trigger`), which is now the last step of the
    (d)-machinery.
    """
    if b.header.sheet_hash != ctx["sheet"]["sheet_hash"]:
        raise Level3("DET-77: bundle sheet_hash != mirrored sheet version")
    for field in ("near_bound_threshold", "counterparties", "attribution_method"):
        if field not in ctx["sheet"]:
            raise Level3(f"DET-77: sheet field absent: {field}")

    ev = ctx["last_event"](ctx["event_log"], ("intake_trigger",), b.header.token)
    if ev is None:
        raise Level3("DET-77: no logged intake_trigger for this token - the "
                     "sheet version is unchained")
    if ev.sheet_hash != b.header.sheet_hash:
        raise Level3(f"DET-77: bundle sheet_hash {b.header.sheet_hash} != last "
                     f"logged intake_trigger {ev.sheet_hash} ({ev.date})")


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
    """Principal / interest separation (anti-tautology, C-2/C-3).

    Dispatched on token the way DET-66 is (P-3.44): crvUSD's origination unit
    is a mint market, GHO's is a direct-minter facilitator (P-4.04 R1), and the
    same condition is checked on whichever table the token actually carries.
    """
    for m in b.markets:
        if m.gross_debt_sum != m.principal_sum + m.accrued_interest_sum:
            raise Level3(f"DET-03: identity broken on {m.symbol}")
        if m.principal_sum < 0 or m.accrued_interest_sum < 0:
            raise Level3(f"DET-03: negative component on {m.symbol}")
    for f in b.facilitators:
        if f.gross_debt_sum is None:
            continue                                   # not an origination row
        if f.gross_debt_sum != (f.principal_sum or 0) + (f.accrued_interest_sum or 0):
            raise Level3(f"DET-03: identity broken on facilitator {f.address}")
        if (f.principal_sum or 0) < 0 or (f.accrued_interest_sum or 0) < 0:
            raise Level3(f"DET-03: negative component on {f.address}")
        # C-3's anti-tautology, GHO shape: principal comes from the event
        # ledger (R7) and gross from a pinned `balanceOf` — two sources, and
        # the reads map must show two distinct signatures rather than one read
        # plus arithmetic.
        sigs = {(r.source_contract, r.function) for k, r in f.reads.items()
                if k in ("principal", "gross_debt") and isinstance(r, ContractRead)}
        if len(sigs) < 2:
            raise Level3(f"DET-03 anti-tautology: {f.address} needs two reads")


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
    """Supply origination: class assigned from the factory address.

    3.1b adds the STRUCTURAL half of DET-07's letter. `lend_markets[]` is a
    disclosure, never an input, and that is asserted rather than asserted-in-
    prose: no lend-market address may appear in any table that feeds backing,
    supply or stress. Saying "referenced by no computation" is not a check;
    this is.
    """
    for m in b.markets:
        if m.origination_class not in ("mint", "lend"):
            raise Level3(f"DET-07: bad origination_class on {m.symbol}")
    if any(m.origination_class == "lend" for m in b.markets):
        raise Level3("DET-07: lend rows must not carry backing inputs in Step 3")

    lend = {r.address for r in b.lend_markets}
    if len(lend) != len(b.lend_markets):
        raise Level3("DET-07: duplicate address in lend_markets")
    bearing = {
        "markets": {m.address for m in b.markets}
        | {m.amm_address for m in b.markets}
        | {m.collateral_address for m in b.markets},
        "nodes": {n.address for n in b.nodes},
        "stabilizer": {o.operation_address for o in b.stabilizer.operations}
        | {o.paired_pool_address for o in b.stabilizer.operations},
        "bridges": {br.bridge_address for br in b.supply.bridges},
    }
    for table, addrs in bearing.items():
        overlap = lend & addrs
        if overlap:
            raise Level3(f"DET-07: lend market(s) {sorted(overlap)} also in "
                         f"{table} - a lend row is feeding backing/supply")


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
    # 3.1b: lend counts are LOGGED, NEVER TRIGGERED (DET-63's letter). The
    # bundle's `lend_market_count_note` carries the one-time "no delta
    # computable" disclosure when the prior held the three-state string; it is
    # NOT gated here. Ruled P-3.45 section 2(b): a raise would have been an
    # implementer-invented consequence at a level the rubric does not assign
    # (DET-63's nearest is "wrong route = Level 2"), gating our own emitted
    # field, and retiring after exactly one run.
    prior = ctx["prior_bundle"].counts.mint_market_count
    now = b.counts.mint_market_count
    if now > prior:
        return ("T-06", 1)
    if now < prior:
        return ("T-12", 2)
    return None



# --- DET-62 confirmation legs (P-3.19 / P-3.39) ------------------------------
# Named implementer default: the endpoints are read through `ctx["http_get"]`,
# a callable injected by the caller, so the harness stays free of transport and
# the branch is testable with stubs. `execute()` supplies the real one.
#
# ENDPOINT VERSION, established by live probe 2026-09-07, not from recall:
# Etherscan's v1 base (`api.etherscan.io/api`) is DEPRECATED and answers
# `{"status":"0","message":"NOTOK","result":"You are using a deprecated V1
# endpoint, switch to Etherscan API V2 ..."}` with or without a key. The v2
# form below answers `{"status":"1","result":"<wei>"}`. Both legs return raw
# wei, directly comparable to `supply.total_supply`, which is also raw wei.
SUPPLY_CONFIRMATION_LEGS = {
    # leg 1 - substitutes Dune (P-3.19). Keyed: P-3.19 rules it read with the
    # ETHERSCAN_API_KEY already in `.env`. The key is used to build the URL and
    # is never stored - not in a bundle, a log, or a spot-check sheet
    # (P-3.39 binding 1); a failed leg records `None`, never the URL.
    "etherscan": ("https://api.etherscan.io/v2/api?chainid=1"
                  "&module=stats&action=tokensupply"
                  "&contractaddress={token}&apikey={key}"),
    # leg 2 - substitutes DefiLlama (P-3.39). Keyless as ruled.
    "blockscout": "https://eth.blockscout.com/api/v2/tokens/{token}",
}


def fetch_supply_confirmations(ctx) -> dict[str, int | None]:
    """Read both legs. A leg that cannot be read is `None`, which DET-62 then
    treats as a missing confirmation (T-14, Level 3) - never as agreement."""
    get = ctx.get("http_get")
    token = ctx.get("token_address", "")
    key = ctx.get("etherscan_api_key", "")
    out: dict[str, int | None] = {}
    for leg, url in SUPPLY_CONFIRMATION_LEGS.items():
        if get is None:
            out[leg] = None
            continue
        try:
            payload = get(url.format(token=token, key=key))
            raw = (payload.get("result") if leg == "etherscan"
                   else payload.get("total_supply"))
            out[leg] = int(raw)
        except Exception:                 # unreadable leg; never a zero, and
            out[leg] = None               # never the URL, which carries a key
    return out


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
    # Confirmation legs, BOTH named substitutions, read only now that the
    # branch has opened (the rubric's letter: confirmation is a consequence of
    # the jump, not a per-run cost):
    #   leg 1 `etherscan`   - substitutes the rubric's Dune leg (P-3.19; Dune's
    #                         free plan goes view-only 2026-09-24);
    #   leg 2 `blockscout`  - substitutes the rubric's DefiLlama leg (P-3.39;
    #                         DefiLlama reports a circulating convention that
    #                         excludes protocol-held inventory, which for
    #                         crvUSD is most of supply - not comparable to
    #                         `totalSupply()`. It survives as spot-check item
    #                         10, informational).
    # Both read a token-supply endpoint, NEVER an `eth_call` proxy - that was
    # the rev-1 defect class (a checker re-deriving our own number).
    sources = ctx.get("supply_confirmations")
    if sources is None:
        sources = fetch_supply_confirmations(ctx)
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
    """Position-set completeness, 1e-9 (G-3 — untraceable pointer).

    Same condition on GHO's origination rows: the live positions must sum to
    the instance debt token's own `totalSupply()`, which is what makes an
    event-derived borrower set checkable against the chain (P-4.04 R3).
    """
    for m in b.markets:
        if not m.position_completeness.ok:
            raise Level3(f"DET-82: {m.symbol} rel_diff "
                         f"{m.position_completeness.relative_diff}")
    for f in b.facilitators:
        if f.position_completeness is not None and not f.position_completeness.ok:
            raise Level3(f"DET-82: facilitator {f.address} rel_diff "
                         f"{f.position_completeness.relative_diff}")


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
        # DET-55's enum has TWO update-condition types (P-3.07 flag (v)). crvUSD
        # is all `ema_window`; GHO's Chainlink sources are `deviation_heartbeat`,
        # whose T-26 field is `heartbeat_s`. The check is dispatched on the type
        # rather than on one member's field, and a heartbeat that is not yet
        # SIGNED is present-and-empty, not zero: T-26 evaluates only where the
        # value exists, and the row names its adapter class so the absence says
        # which kind it is (P-4.08).
        uc = r.update_condition
        if uc.type == "ema_window":
            if uc.ema_window_s <= 0:
                raise Level3(f"DET-55: non-positive ema_window_s on {r.node_address}")
        elif uc.heartbeat_s is not None and uc.heartbeat_s <= 0:
            raise Level3(f"DET-55: non-positive heartbeat_s on {r.node_address}")
        elif uc.heartbeat_s is None and not r.adapter_class:
            raise Level3(f"DET-55: {r.node_address} has neither a heartbeat nor an "
                         "adapter class naming why it has none")


# --- DET-66 vocabularies and helpers (rubric line 102) -----------------------
R6_KINDS = frozenset({"none", "pausable", "capacity_limited",
                      "state_conditional", "notice_period"})
# Named implementer default: the `R1 = none` implication reads "R3-R7 n/a", but
# `r6_gates` is typed `list[dict]` on RedemptionPath, so the string "n/a" is not
# representable for R6. Its n/a IS the rubric's own exclusive `none` gate, which
# is the form P-3.40 read the emitted crvUSD block as satisfying.
R6_NA = [{"kind": "none", "param": None}]


def _resolves_on_bundle(b: Bundle, ref: str) -> bool:
    """Named implementer default for the rubric's "`C` references a bundle
    field" (R6) and "resolvable field ref" (R7): a dotted attribute path from
    the bundle root, e.g. `supply.total_supply`. No indexing, no calls."""
    cur: object = b
    for part in ref.split("."):
        if not part or not hasattr(cur, part):
            return False
        cur = getattr(cur, part)
    return True


def _is_figure(s: str) -> bool:
    """Named implementer default for R5's "figure or `none`": a plain decimal
    literal. Units belong to the sheet, not to this field."""
    try:
        Decimal(s)
    except Exception:
        return False
    return True


def det_66(b: Bundle, ctx) -> None:
    """R-blocks complete per path (rubric line 102; S1).

    Consequence as the rubric assigns it: **Level 3** for a missing block,
    **Level 2** for a malformed field. Both surface as a `Level3` raise - the
    harness convention, with `Check.level_on_fail` carrying the ruled level
    (DET-33 is the precedent for a two-level entry registered at 3).

    R1/R2/R9 are Pydantic `Literal`s on `RedemptionPath`, so their enum limbs
    are structurally guaranteed; they are asserted here anyway because the gate
    record is the artifact, not the type system (brief section 1).
    """
    paths = b.redemption_paths
    if not paths:
        raise Level3("DET-66: paths[] missing (empty) - Level 3, missing block")

    # --- token-level path count ---------------------------------------------
    token = b.header.token
    if token == "crvUSD":
        if len(paths) != 1 or paths[0].r1_path != "none":
            raise Level3(
                "DET-66: crvUSD requires exactly one path with R1 = none; got "
                f"{len(paths)} path(s) with R1 = {[p.r1_path for p in paths]}")
    elif token == "GHO":
        # P-4.08 replaces P-3.44's stub. The sheet rules "holder paths: 1 + N
        # GSMs" - one `module_on_chain` path per LIVE GSM plus the Aave
        # facilitator's `none`. Live-GSM identity is the DET-28 probe's, and
        # the count comes from `gsms[]`, which the registry enumerated - never
        # a configured number.
        modules = [p for p in paths if p.r1_path == "module_on_chain"]
        if len(modules) != len(b.gsms):
            raise Level3(
                f"DET-66: GHO requires one module_on_chain path per live GSM; "
                f"got {len(modules)} path(s) against {len(b.gsms)} GSM(s)")
        if not any(p.r1_path == "none" for p in paths):
            raise Level3("DET-66: GHO requires the Aave-facilitator path at R1 = none")
        boxed = {g.underlying_asset for g in b.gsms}
        for m in modules:
            if not isinstance(m.r3_received, list) or not set(m.r3_received) <= boxed:
                raise Level3(f"DET-66: GHO module path R3 must be a boxed asset; "
                             f"got {m.r3_received!r}")
    else:
        raise NotYetImplemented(
            f"DET-66: the path-count clause for {token} is not implemented. "
            "LUSD: exactly one direct_on_chain path. Ruled P-3.44; lands at "
            "Step 4C. The per-path checks below are token-agnostic and apply.")

    # --- per-path field rules, token-agnostic --------------------------------
    for i, p in enumerate(paths):
        at = f"DET-66[path {i}]"
        if p.r1_path not in ("direct_on_chain", "module_on_chain",
                             "issuer_offchain", "none"):
            raise Level3(f"{at}: R1 outside enum: {p.r1_path!r}")
        if p.r2_who not in ("anyone", "whitelisted", "borrowers_only", "no_one"):
            raise Level3(f"{at}: R2 outside enum: {p.r2_who!r}")
        if p.r9_legal_claim not in ("yes", "no_pure_protocol", "disclaimed"):
            raise Level3(f"{at}: R9 absent or outside enum: {p.r9_legal_claim!r}")

        na = p.r1_path == "none"

        # R3 - address list or `n/a`, and `n/a` iff R1 = none
        if (p.r3_received == "n/a") != na:
            raise Level3(f"{at}: R3 is `n/a` iff R1 = none "
                         f"(R1={p.r1_path!r}, R3={p.r3_received!r})")

        if na:
            # the implication: R2 = no_one, R3-R7 n/a, R9 present (checked above)
            if p.r2_who != "no_one":
                raise Level3(f"{at}: R1 = none requires R2 = no_one, "
                             f"got {p.r2_who!r}")
            for name, val in (("R4", p.r4_rate), ("R5", p.r5_minimum),
                              ("R7", p.r7_capacity)):
                if val != "n/a":
                    raise Level3(f"{at}: R1 = none requires {name} = 'n/a', "
                                 f"got {val!r}")
            if p.r6_gates != R6_NA:
                raise Level3(f"{at}: R1 = none requires R6 = the exclusive "
                             f"`none` gate {R6_NA}, got {p.r6_gates}")
        else:
            if not (p.r4_rate in ("face_value", "market")
                    or (p.r4_rate.startswith("face_minus_fee(")
                        and p.r4_rate.endswith(")"))):
                raise Level3(f"{at}: R4 outside "
                             "{face_value, face_minus_fee(range), market}: "
                             f"{p.r4_rate!r}")
            if p.r5_minimum != "none" and not _is_figure(p.r5_minimum):
                raise Level3(f"{at}: R5 must be a figure or `none`: "
                             f"{p.r5_minimum!r}")
            if (p.r7_capacity != "unbounded"
                    and not _resolves_on_bundle(b, p.r7_capacity)):
                raise Level3(f"{at}: R7 must be a resolvable bundle field ref "
                             f"or `unbounded`: {p.r7_capacity!r}")

        # R6 - subset of the closed kind set, `none` exclusive, `C` resolves
        if not p.r6_gates:
            raise Level3(f"{at}: R6 empty; the empty form is the `none` gate")
        kinds = [g.get("kind") for g in p.r6_gates]
        outside = sorted(k for k in set(kinds) if k not in R6_KINDS)
        if outside:
            raise Level3(f"{at}: R6 kinds outside the closed set: {outside}")
        if "none" in kinds and len(kinds) != 1:
            raise Level3(f"{at}: R6 `none` is exclusive, got {kinds}")
        for g in p.r6_gates:
            if g.get("kind") == "state_conditional":
                c = g.get("param")
                if not isinstance(c, str) or not _resolves_on_bundle(b, c):
                    raise Level3(f"{at}: R6 state_conditional(C) must reference "
                                 f"a bundle field; got {c!r}")

        # R10 - {contract, function} + provenance, or {document, date}
        prov = p.r10_provenance
        if isinstance(prov, ContractRead):
            if not prov.source_contract or not prov.function:
                raise Level3(f"{at}: R10 contract read missing contract/function")
        elif isinstance(prov, AbsenceRead):
            # The absence form of {contract, function}: `function` is None by
            # construction and `method` + `evidence` carry the provenance. This
            # is the reading P-3.40 recorded for the emitted crvUSD block.
            if not prov.contract or not prov.method or not prov.evidence:
                raise Level3(f"{at}: R10 absence read missing "
                             "contract/method/evidence")
        elif isinstance(prov, AnalystSupplied):
            if not prov.source or prov.date is None:
                raise Level3(f"{at}: R10 document/date form incomplete")
        else:
            raise Level3(f"{at}: R10 provenance of unknown shape: {type(prov)}")


# --- DET-10 named implementer defaults (all P-3.43 unless stated) ------------
# The 10% denominator is the SET FILE's `freeze_discovery_total`, held fixed
# between refreshes so the threshold does not move as pool TVLs do. It is
# already baked into every row's `ratio_to_frozen_coverage`, so this constant is
# the threshold only.
DET10_SHARE_THRESHOLD = Decimal("0.10")
DET10_FREEZE_MAX_AGE_DAYS = 100          # R-a2; (f) via T-17
# (d)-i's scope: freeze-time reasons that are SIZE cuts, so a pool excluded
# only for being small can re-enter the test by growing. Structural reasons
# are excluded - see `det_10`.
DET10_SIZE_BASED_REASONS = frozenset({"added_since_freeze",
                                      "tail_beyond_freeze_coverage"})


def det_10(b: Bundle, ctx) -> tuple[str, int] | None:
    """Frozen set integrity (rubric line 81; S1).

    Clause consequences EXACTLY as the rubric assigns them - (a) Level 3;
    (b)(d)(e) Level 2; (f) Level 1 via T-17 - and **no consequence for (c),
    because the rubric assigns none**. (c) is satisfied STRUCTURALLY: the three
    detector fields are required on `PoolDetectors`, which is required on
    `Bundle`, so a bundle without them cannot be constructed - Pydantic raises
    before any gate runs, and there is no runtime failure path here to attach a
    level to. Inventing one is what P-3.45's withdrawn `det_63` raise did; the
    missing level is on the rubric-amendment queue instead.
    """
    h = b.header

    # -- (a) Level 3: header stamps, and the chain to the event log ----------
    if not h.freeze_date or not h.frozen_set_hash:
        raise Level3("DET-10(a): header missing freeze_date / frozen_set_hash")
    ev = ctx["last_event"](ctx["event_log"], ("freeze", "intake_trigger"), h.token)
    if ev is None:
        raise Level3("DET-10(a): no logged freeze / intake_trigger event - the "
                     "set file is unchained")
    logged = getattr(ev, "set_file_hash", None)
    if logged is None:
        # Backfilled entry 1's shape: a sheet edit logged before any freeze
        # existed. FAIL CLOSED - no chain is not a passing chain.
        raise Level3(f"DET-10(a): last {ev.type} event ({ev.date}) carries a "
                     "null set_file_hash - no chain is not a passing chain")
    if logged != h.frozen_set_hash:
        raise Level3(f"DET-10(a): frozen_set_hash {h.frozen_set_hash} != last "
                     f"logged {ev.type} {logged} ({ev.date})")

    # -- (b) Level 2: every modeled pool is in the frozen set ---------------
    # A frozen pool that failed the disappearance read KEEPS its row (P-3.46
    # R5), so this exact-equality membership still holds and (d)-ii evaluates
    # from that row rather than from its absence.
    modeled = {r.address for r in b.pools if r.in_frozen_set}
    frozen = set(ctx["frozen_set_members"])
    if modeled != frozen:
        raise Level3(f"DET-10(b): modeled-vs-frozen mismatch; extra "
                     f"{sorted(modeled - frozen)}, missing {sorted(frozen - modeled)}")

    # -- (e) Level 2: every detection disclosed as a pool-table annotation ---
    d = b.pool_detectors
    by_addr = {r.address: r for r in b.pools}
    for field, needle in (("new_pool_above_floor", "new pool above the dust floor"),
                          ("frozen_pool_below_floor", "frozen pool below the dust floor"),
                          ("frozen_pool_tvl_change_gt_50pct", "TVL change > 50%")):
        for addr in getattr(d, field):
            row = by_addr.get(addr)
            if row is None:
                raise Level3(f"DET-10(e): {field} names {addr}, absent from pools[]")
            if not any(needle in a for a in row.annotations):
                raise Level3(f"DET-10(e): undisclosed detection - {addr} in "
                             f"{field} carries no matching annotation")

    # -- (d) Level 2 via T-10: exactly two events ---------------------------
    # (i) an above-floor non-F pool >= 10% of frozen-set coverage.
    #
    # The TEST is wider than the DETECTOR LIST, deliberately (review refinement
    # to P-3.46 R2). `new_pool_above_floor` holds `added_since_freeze` rows
    # only, because a pool the freeze already knew and listed must not re-flag
    # every run. But memo 5.6(i) reads "a new pool above the dust floor NOT IN
    # THE FROZEN SET", and `tail_beyond_freeze_coverage` is a SIZE cut - the
    # coverage rule's own - not a structural exclusion. A tail pool that grew
    # to >= 10% of coverage would otherwise never reach this test at all.
    #
    # Structural reasons stay OUT: `self_referential_wrapper` and
    # `volatile_collateral_circular` are section 5.4 judgments about what a
    # pool IS, and no amount of growth makes such a pool exit liquidity.
    for r in b.pools:
        if r.in_frozen_set:
            continue
        if r.exclusion_reason not in DET10_SIZE_BASED_REASONS:
            continue
        if r.ratio_to_frozen_coverage >= DET10_SHARE_THRESHOLD:
            return ("T-10", 2)
    # (ii) a frozen pool that has DISAPPEARED whose LAST-RUN share >= 10%.
    # Named default: last-run share comes from the prior bundle's pools[],
    # falling back to the set file's freeze_tvl ratios when the prior carries
    # none - true exactly once and disclosed via `baseline_source`.
    for r in b.pools:
        if not r.in_frozen_set:
            continue
        if not any("disappeared" in a for a in r.annotations):
            continue
        last = ctx["last_run_ratio"].get(r.address)
        if last is not None and last >= DET10_SHARE_THRESHOLD:
            return ("T-10", 2)

    # -- (f) Level 1 via T-17: freeze overdue -------------------------------
    # Evaluated against `header.run_date` (derived from the pinned
    # `block_timestamp`), NOT a wall clock, so re-running a stored bundle
    # through the harness gives the same answer.
    freeze_day = _dt.date.fromisoformat(h.freeze_date)
    if (h.run_date - freeze_day).days > DET10_FREEZE_MAX_AGE_DAYS:
        return ("T-17", 1)
    return None


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
    Check("DET-66", "S1", 3, det_66),
    Check("DET-68", "S1", 3, det_68), Check("DET-08", "S1", 2, det_08),
    Check("DET-10", "S1", 3, det_10),
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
