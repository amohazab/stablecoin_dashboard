"""B-5: the common schema — the bundle every downstream step consumes.

Rubric field names are used verbatim wherever a name is ruled. Amounts are
integer base units; ratios are Decimal serialised as strings (O-2). Provenance
lives in `reads` maps keyed by field name (C-2), so DET-named read coverage is
checkable as a set equality rather than a parade of `*_provenance` twins.

`bundle_hash` is computed over the bundle alone in Step 3, and over the bundle
plus the flat table once that exists (Step 7, DET-84) — the phased definition
(P-3.08).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from decimal import Decimal
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, StringConstraints, model_validator

from factory.provenance import (  # noqa: F401
    AbsenceRead,
    AnalystSupplied,
    ContractRead,
    Lineage,
    Provenance,
)

# R2 (ruled P-4.13): native ETH is keyed `0xeeee...eeee`, Curve's convention and
# already present in this repo's catalog data. NO CHANGE WAS NEEDED HERE - the
# pattern admits it as written, and `eth_getCode` at that address is empty. The
# ruling is a naming convention, not a type relaxation: the key is a NAME, and
# nothing may read a balance or code at it. LUSD's ETH figure comes from
# ActivePool.getETH() + DefaultPool.getETH() (P-4.16).
Address = Annotated[str, StringConstraints(pattern=r"^0x[0-9a-f]{40}$")]

# ---------------------------------------------------------------- header ----


class Header(BaseModel):
    token: str
    run_block: int
    block_timestamp: int
    run_start_time: int
    first_run: bool
    chain_id: Literal[1] = 1
    pipeline_version: str
    sheet_hash: str
    frozen_set_hash: str | None = None
    freeze_date: str | None = None
    template_hash: str | None = None
    raw_positions_hash: str
    bundle_hash: str = ""          # filled last, over everything else
    revision_count: Literal[0, 1] = 0
    revision_cause: list[str] = []

    @property
    def det83_delta_s(self) -> int:
        return self.run_start_time - self.block_timestamp

    @property
    def run_date(self) -> _dt.date:
        """The run's date as a PURE FUNCTION OF THE BUNDLE (P-3.46 R4).

        DET-10(f) must give the same answer when a stored bundle is re-run
        through the harness later, so it cannot read a wall clock. There is no
        `run_date` FIELD - this derives from `block_timestamp`, which is the
        pinned block's own timestamp and is already in the hash preimage, so
        adding a property changes no emitted byte.
        """
        return _dt.datetime.fromtimestamp(self.block_timestamp,
                                          _dt.UTC).date()


# --------------------------------------------------------------- markets ----


class PositionCompleteness(BaseModel):
    sum_position_gross_debt: int
    controller_total_debt: int
    relative_diff: Decimal

    @property
    def ok(self) -> bool:                                   # DET-82, 1e-9
        return self.relative_diff <= Decimal("1e-9")


class Market(BaseModel):
    """One origination unit of a CDP that mints against posted collateral.

    R1 (ruled P-4.13). FOUR OF THESE FIELDS WERE LLAMMA LEAKAGE. `Market` was
    written from crvUSD alone, and LUSD - the simplicity control, whose whole
    job is to ask whether the common schema fits a second CDP - has 16 of the
    20 exactly, and no analogue at all for `amm_address`, `monetary_policy_
    address`, `a_coefficient` and `slot_base_verified`: a trove system has no
    AMM, no per-market rate contract, no LLAMMA `A`, and no band storage slot
    to verify. They are OPTIONAL from here, so LUSD carries `markets[]` with
    one row rather than a third table, and DET-01/03/04/07/82 keep iterating
    one list. crvUSD sets all four exactly as before and its bundle does not
    move a byte - asserted by re-assembling block 25934920 to `bundle_hash
    dfbcd558...` (P-3.15's pattern).

    THE HONEST FIX IS NOT THIS ONE. These four belong in a nested optional
    LLAMMA block, so the shape says which fields are one mechanism's rather
    than leaving four holes in a common model. That is Block D's queue, by
    name (P-4.13). Recorded here so the compromise is visible in the type.
    """

    address: Address                                        # controller
    amm_address: Address | None = None                      # R1: LLAMMA-only
    collateral_address: Address
    monetary_policy_address: Address | None = None          # R1: LLAMMA-only
    symbol: str                                             # display only
    origination_class: Literal["mint", "lend"]              # DET-07
    decimals: int
    a_coefficient: int | None = None                        # R1: LLAMMA-only
    n_positions: int
    principal_sum: int                                      # DET-03
    accrued_interest_sum: int
    gross_debt_sum: int
    net_debt_sum: int                                       # DET-06
    surplus_sum: int
    stablecoin_in_position_sum: int
    external_collateral_sum: int
    external_collateral_value: int                          # DET-81, priced
    position_completeness: PositionCompleteness
    slot_base_verified: int | None = None                   # R1: LLAMMA-only
    reads: dict[str, Provenance]
    lineage: list[Lineage]

    REQUIRED_READS: ClassVar[frozenset[str]] = frozenset(
        {"gross_debt", "principal", "total_debt", "decimals", "collateral_price"}
    )

    @model_validator(mode="after")
    def _check(self):
        if self.gross_debt_sum != self.principal_sum + self.accrued_interest_sum:
            raise ValueError(f"{self.symbol}: DET-03 identity broken")
        missing = self.REQUIRED_READS - set(self.reads)
        if missing:                                         # C-2 / C-3
            raise ValueError(f"{self.symbol}: reads missing {sorted(missing)}")
        # C-3: all three tracing to ONE read plus arithmetic = fail. A read is
        # independent by (contract, method) — and the DET-03 principal path is
        # an F4-shaped `storage_slot_read`, which P-3.07 ruling (i) branch 2
        # makes a compliant contract read. Counting only ContractRead here would
        # reject the ruled production shape.
        independent = set()
        for k, r in self.reads.items():
            if k not in ("principal", "accrued_interest", "gross_debt"):
                continue
            if isinstance(r, ContractRead):
                independent.add((r.source_contract, r.function))
            elif isinstance(r, AbsenceRead):
                independent.add((r.contract, r.method))
        if len(independent) < 2:
            raise ValueError(f"{self.symbol}: DET-03 anti-tautology - need two reads")
        return self


# ------------------------------------------------------------ stabilizer ----


class StabilizerOperation(BaseModel):
    operation_address: Address
    paired_pool_address: Address
    paired_asset_address: Address | None = None
    debt_ceiling: int
    current_debt: int
    balance: int
    utilization: Decimal | None                              # O-1: no prose here
    utilization_na_reason: Literal["ceiling_zero"] | None = None
    protocol_lp_share: Decimal | None = None
    net_non_self_referential_value: int | None = None
    residual: int | None = None
    is_killed_provide: bool
    is_killed_withdraw: bool
    reads: dict[str, Provenance]
    lineage: list[Lineage]

    @model_validator(mode="after")
    def _check(self):
        if (self.debt_ceiling == 0) != (self.utilization is None):
            raise ValueError("DET-21: utilization is None iff ceiling is 0")
        if (self.utilization_na_reason == "ceiling_zero") != (self.debt_ceiling == 0):
            raise ValueError("DET-21: na_reason must accompany a zero ceiling")
        return self


class StabilizerBlock(BaseModel):
    operations: list[StabilizerOperation]
    credited_backing_value: Literal[0] = 0                   # DET-05(b), exact
    ceiling_aggregate: int
    ceiling_aggregate_lineage: list[Lineage]                 # derived: no provenance
    alpha: Decimal | None = None
    beta: Decimal | None = None
    effective_headroom: int | None = None                    # R-b1: present-and-empty
    naive_headroom: int | None = None
    reads: dict[str, Provenance] = {}


# ------------------------------------------------- facilitators (GHO) ------
# The `facilitators[]` sibling P-3.08 endorsed and P-4.04 R1 ruled: GHO's
# supply-origination surface is not a market set, so it is its own table rather
# than a fake generalisation of `markets[]`. `markets` stays empty for GHO.


class Facilitator(BaseModel):
    """One row of `GhoToken.getFacilitatorsList()`, classified by what its
    bytecode answers rather than by its label string (DET-28)."""

    address: Address
    label: str                                              # the on-chain label
    bucket_capacity: int
    bucket_level: int
    utilization: Decimal | None                             # O-1: no prose here
    utilization_na_reason: Literal["ceiling_zero"] | None = None
    facilitator_class: Literal["direct_minter", "gsm_funder", "flash_minter",
                               "off_mainnet", "unresolved"]
    class_evidence: list[str]                               # selectors that answered
    pool_address: Address | None = None                     # direct_minter: POOL()
    inventory: int | None = None                            # undrawn, held elsewhere
    # P-4.04 R1's literal words: a direct_minter row carries "pool, bucket
    # capacity/level and drawn debt with principal and accrued interest
    # separated". crvUSD hangs those on `markets[]`; GHO has none, and the
    # facilitator IS the origination unit, so they hang here (P-4.07).
    debt_token_address: Address | None = None
    atoken_address: Address | None = None
    n_positions: int | None = None
    principal_sum: int | None = None
    accrued_interest_sum: int | None = None
    gross_debt_sum: int | None = None
    position_completeness: PositionCompleteness | None = None
    reads: dict[str, Provenance]

    @model_validator(mode="after")
    def _check(self):
        if (self.bucket_capacity == 0) != (self.utilization is None):
            raise ValueError("DET-21: utilization is None iff capacity is 0")
        if (self.utilization_na_reason == "ceiling_zero") != (self.bucket_capacity == 0):
            raise ValueError("DET-21: na_reason must accompany a zero capacity")
        if (self.facilitator_class == "direct_minter") != (self.pool_address is not None):
            raise ValueError("a direct_minter carries its POOL(), and only it does")
        if self.gross_debt_sum is not None:                  # DET-03, integer-exact
            if self.gross_debt_sum != (self.principal_sum or 0) + (self.accrued_interest_sum or 0):
                raise ValueError(f"DET-03 identity broken on facilitator {self.address}")
            if (self.principal_sum or 0) < 0 or (self.accrued_interest_sum or 0) < 0:
                raise ValueError(f"DET-03 negative component on {self.address}")
        return self


class GhoPosition(BaseModel):
    """One borrower's GHO debt in one Aave instance.

    Position rows stay OUT of the bundle and out of `bundle_hash` (P-3.05's
    boundary); they are validated here on the way to the raw dump, which is
    where `principal <= gross` gets a row-level home rather than a comment.
    """

    borrower: Address
    instance: Address                                       # the Pool
    gross_debt: int                                         # balanceOf at run_block
    principal: int                                          # R7, P-4.04-A1
    accrued_interest: int
    gho_debt_base: int = 0                                  # gross in base currency
    total_debt_base: int = 0                                # all reserves, for pro-rata
    collateral: dict[Address, int] = {}                     # reserve -> aToken balance

    @model_validator(mode="after")
    def _check(self):
        if self.principal > self.gross_debt:
            raise ValueError(f"{self.borrower}: principal {self.principal} > gross "
                             f"{self.gross_debt} — R7 without LiquidationCall (P-4.04-A1)")
        if self.accrued_interest != self.gross_debt - self.principal:
            raise ValueError(f"{self.borrower}: accrued must be gross - principal")
        return self


class Gsm(BaseModel):
    """One live GSM from `GsmRegistry.getGsmList()`, with the memo §6.3 H2
    freezer state. `freezer_address` is discovered, never configured: the
    holder comes from the role log pointer and `hasRole` is the verdict
    (P-4.04 R5)."""

    address: Address
    underlying_asset: Address
    exposure_cap: int
    available_liquidity: int
    available_underlying_exposure: int
    is_frozen: bool
    is_seized: bool
    price_strategy: Address
    fee_strategy: Address
    gho_treasury: Address
    freezer_address: Address | None = None
    freeze_bound_lo: int | None = None
    freeze_bound_hi: int | None = None
    unfreeze_bound_lo: int | None = None
    unfreeze_bound_hi: int | None = None
    can_unfreeze: bool | None = None
    freezer_role_confirmed: bool = False
    reads: dict[str, Provenance]


# ------------------------------------------------------------ supply -------


class Bridge(BaseModel):
    bridge_address: Address
    amount: int
    bridge_type: Literal["lock_and_mint", "burn_and_mint", "unresolved"]
    reads: dict[str, Provenance]


class Supply(BaseModel):
    total_supply: int
    supply_ruled: int
    bridge_state: Literal["not_configured", "explicit_empty", "populated"]
    bridge_disclosure: str
    bridges: list[Bridge] = []
    origination_sum: int
    residual: int
    stabilizer_over_supply: Decimal                          # DET-16, unconditional
    # R18: LUSD's Stability Pool balance as a NUMBER beside the provenance that
    # was already in `reads`. It is deposited supply and liquidation capacity —
    # never backing, never a residual (sheet §5.4) — and until B-3a its value
    # survived only inside `bridge_disclosure` prose. `None` on crvUSD and GHO,
    # which have no stability pool.
    stability_pool_deposits: int | None = None
    reads: dict[str, Provenance]


# ------------------------------------------------------------- nodes -------


class CollateralNode(BaseModel):
    address: Address
    symbol: str
    label: Literal["terminal", "terminal_other_layer", "recurses",
                   "recurses_truncated", "unlisted"]
    label_source_address: Address
    node_class: Literal["volatile", "stable"]
    lst_discount_applies: bool
    value: int
    share_of_backing: Decimal
    disclosure_cadence: str | None = None
    last_disclosure_date: str | None = None
    # DET-52 (B-3a): the §6.3 collateral-sell-side bound, a SHEET-owned analyst
    # parameter carried on the node exactly as `disclosure_cadence` is — DET-52
    # is an S1 entry, so it must be checkable against the bundle alone. Memo
    # §6.3: "amount of [node] absorbable into stable markets within the shock
    # window at ≤ 2% impact". `None` until B-3b's values land; LUSD's one
    # volatile node carries the exempt literal in `value` and no number.
    sell_side_capacity: dict[str, str] | None = None
    flags: list[str] = []
    reads: dict[str, Provenance]
    lineage: list[Lineage]

    @model_validator(mode="after")
    def _check(self):
        if self.label_source_address != self.address:        # DET-02
            raise ValueError(f"{self.symbol}: label_source_address must equal address")
        if self.lst_discount_applies and self.node_class != "volatile":
            raise ValueError(f"{self.symbol}: DET-02 clause (i)")
        return self


# ------------------------------------------------------------ oracles ------


class EmaWindow(BaseModel):
    type: Literal["ema_window"] = "ema_window"
    ema_window_s: int
    constituents: list[dict[str, Any]]                       # transitive hops, P-3.32
    provenance: list[Provenance]


class DeviationHeartbeat(BaseModel):
    """DET-55's OTHER update-condition type, built when GHO first needed it.

    P-3.07 flag (v) records that "DET-55's `update_condition.type` enum already
    splits `deviation_heartbeat` from `ema_window`", and that T-26's formula
    references `heartbeat_s` — a field only this type carries. crvUSD's oracles
    are all `ema_window`, so this member had no instance until now; GHO's are
    Chainlink deviation/heartbeat feeds. Implementing a ruled enum member, not
    inventing one (P-4.08).

    `heartbeat_s` is None until the values are signed — present-and-empty, and
    T-26 evaluates only where it is present.
    """

    type: Literal["deviation_heartbeat"] = "deviation_heartbeat"
    heartbeat_s: int | None = None
    deviation_bps: int | None = None
    answer: int | None = None
    updated_at: int | None = None
    provenance: list[Provenance]


class OracleRow(BaseModel):
    node_address: Address
    market_or_reserve_address: Address                       # crvUSD: per mint market
    feed_or_source: Address
    update_condition: EmaWindow | DeviationHeartbeat
    assumption_applied: Literal["instant_optimistic_counterfactual"]
    counterfactual_ref: Literal["EMA_lag"]
    reference_feed: AnalystSupplied | Literal["no_reference_feed", "pending_config_round"]
    market_vs_protocol_oracle_gap: Decimal | Literal["no_reference_feed",
                                                     "pending_config_round"]
    # None where the row is present-and-empty for T-26: a deviation/heartbeat
    # source whose heartbeat is not yet signed, or a NAV adapter which has no
    # heartbeat at all. The class is named in `adapter_class` so the absence
    # says WHICH kind of absence it is.
    staleness_check: Literal["not_applicable_ema_oracle"] | None = None
    adapter_class: Literal["raw", "capo", "nav", "other"] | None = None
    use_chainlink: bool | None = None
    disclosure: str | None = None                            # weETH rate mechanism


# --------------------------------------------------- redemption / admin ----


class RedemptionPath(BaseModel):
    r1_path: Literal["direct_on_chain", "module_on_chain", "issuer_offchain", "none"]
    r2_who: Literal["anyone", "whitelisted", "borrowers_only", "no_one"]
    r3_received: list[Address] | Literal["n/a"]
    r4_rate: str
    r5_minimum: str
    r6_gates: list[dict[str, Any]]
    r7_capacity: str
    r8: str
    r8_source: Literal["computed"] = "computed"
    r9_legal_claim: Literal["yes", "no_pure_protocol", "disclaimed"]
    r10_provenance: Provenance


class AdminRow(BaseModel):
    power: Literal["mint", "set_ceiling", "upgrade", "pause", "freeze_asset",
                   "blacklist_address", "set_oracle", "set_parameters", "seize"]
    holder_address: Address | None
    holder_type: Literal["eoa", "multisig", "dao_governance", "timelock",
                         "contract_automated", "none"]
    delay_seconds: int | None = None
    # DET-68's printed bucket literals verbatim - `1–7d` with the EN DASH
    # (P-5.01 R15(a)); the ASCII hyphen this set carried until then matched
    # nothing the rubric prints.
    delay_bucket: Literal["none", "<24h", "1–7d", ">7d"] | None = None
    veto_address: Address | None = None
    upgradeability: Literal["immutable", "proxy_upgradeable"] | None = None
    scope: list[Address] = []
    provenance: Provenance                                   # DET-68 A8: the holder read
    # C-2's map (P-3.08) for a row with a second provenanced value. Today one
    # key, `delay_seconds`, carrying the dated analyst row an off-chain-governed
    # holder's A4 comes from (P-5.01 R13). `delay_bucket` is a DET-68 replay,
    # not a read, so it has no entry. Moving `provenance` itself in here is
    # P-4.01 #22, not done (P-5.02).
    reads: dict[str, Provenance] = {}
    live_model_input: bool = False
    consumed_by: list[str] = []


class StaticMetadata(BaseModel):
    audits: list[dict[str, str]] | Literal["none"]
    bug_bounty: dict[str, str] | Literal["none"]
    last_material_change_audited: Literal["yes", "no"]
    staleness_date: str
    counterparties: str                                      # ruled literal


# ---------------------------------------------------------------- pools -----


class ZeroedSideRow(BaseModel):
    """A pool side that contributed nothing to par value, disclosed rather than
    silently dropped (P-3.26). Mirrors `freeze.ZeroedSide` in the bundle."""

    address: Address
    units: int
    par_eligibility: str = "none"


class PoolRow(BaseModel):
    """One pool as seen at `run_block` (DET-10(c)(e); memo 5.6's per-run pass).

    `ratio_to_frozen_coverage` is `tvl_at_par / freeze_discovery_total` - a
    RATIO to the freeze-time denominator, not a share of a partition. It may
    exceed 1.0 for a pool that did not exist at the freeze. The denominator is
    held fixed between refreshes on purpose (P-3.43): a moving denominator
    would move DET-10(d)'s 10% threshold every week.
    """

    address: Address
    in_frozen_set: bool
    paired_assets: list[Address] = []
    freeze_tvl: int | None = None                # None for a non-F pool
    tvl_at_par: int
    ratio_to_frozen_coverage: Decimal
    is_stabilizer_pool: bool = False
    exclusion_reason: str | None = None          # non-F only; exactly one
    annotations: list[str] = []                  # DET-10(e)'s disclosure surface
    zeroed_sides: list[ZeroedSideRow] = []
    reads: dict[str, Provenance] = {}


class PoolDetectors(BaseModel):
    """DET-10(c). Three address lists, each sorted ascending.

    The lists carry NO figures of their own - every number lives on the
    `pools[]` row the address names, so no quantity has two owners. Presence is
    STRUCTURAL: these fields are required, so a bundle without them cannot be
    constructed. That is where clause (c) is enforced; the rubric assigns (c)
    no consequence level and none is invented here (P-3.46 R3).
    """

    new_pool_above_floor: list[Address] = []
    frozen_pool_below_floor: list[Address] = []
    frozen_pool_tvl_change_gt_50pct: list[Address] = []
    # Named implementer default (P-3.43): which comparand the last-run figures
    # came from. `freeze_set_file` is true exactly once - at the first run whose
    # prior bundle predates `pools[]` - and is DISCLOSED, never silent.
    baseline_source: Literal["prior_bundle", "freeze_set_file"]
    baseline_note: str | None = None


class LendMarket(BaseModel):
    """One lend market, enumerated ONLY to exclude (DET-07, FR-10/FR-11).

    A lend market re-lends existing crvUSD; it originates none. This table is
    therefore a DISCLOSURE, not an input: `det_07` asserts structurally that
    no address here appears in any backing-, supply- or stress-bearing table.
    """

    address: Address
    factory: Address
    index: int
    reads: dict[str, Provenance]


class Counts(BaseModel):
    mint_market_count: int
    lend_market_count: int | str                             # three-state (P-3.17)
    # P-3.14-class disclosure (3.1b): set when the prior run carried the
    # three-state STRING rather than an integer, so no delta is computable.
    lend_market_count_note: str | None = None
    # DET-10(e): below-floor non-F pools are COUNTED, not listed (P-3.43).
    below_floor_pool_count: int = 0
    gsm_count: int = 0                                       # explicit for crvUSD
    facilitator_count: int | str = "n/a"


class LogEntry(BaseModel, extra="forbid"):                   # DET-60 closed schema
    date: str
    token: str
    trigger: str
    level: Literal[1, 2, 3]
    resolution_type: str | None = None
    resolution_date: str | None = None


class GateResult(BaseModel):
    entry_id: str
    result: Literal["pass", "fail", "not_applicable", "error"]
    scope_condition: str | None = None


class FirstRunLiterals(BaseModel):
    """DET-62 / DET-63 / DET-65 first-run literals, present-and-explained."""

    supply: str = "first run - no prior supply"
    composition: str = "first run - no prior composition"
    market_count: str = "first run - no trigger, disclosed"


# ------------------------------------------------------------- bundle ------


class Bundle(BaseModel):
    header: Header
    markets: list[Market]
    stabilizer: StabilizerBlock
    supply: Supply
    nodes: list[CollateralNode]
    oracle_rows: list[OracleRow]
    redemption_paths: list[RedemptionPath]
    admin_surface: list[AdminRow]
    lend_markets: list[LendMarket] = []
    # GHO's origination surface (P-4.04 R1). Empty for crvUSD, whose surface is
    # `markets[]`; `markets[]` is empty for GHO. Neither token carries both.
    facilitators: list[Facilitator] = []
    gsms: list[Gsm] = []
    pools: list[PoolRow] = []
    # R3 (ruled P-4.13). DET-66 resolves R7 either by a DOTTED PATH FROM THE
    # BUNDLE ROOT or, for GHO, by row identity. LUSD's R7 - "ActivePool +
    # DefaultPool ETH at oracle price" - resolves by neither: it is a figure
    # over two contracts, and `markets.external_collateral_value` is a table,
    # not a path. Rather than admit a third resolver or an index, the adapter
    # EMITS the number the path names. Optional, because only a token whose R7
    # is this shape carries it; `reads` is required whenever it is present.
    redeemable_collateral_value: int | None = None
    redeemable_collateral_reads: dict[str, Provenance] = {}
    # FLAGGED ADDITION, not covered by R3 (P-4.16, awaiting Amin's ruling).
    # DET-66's R6 requires `state_conditional(C)` to name a field that resolves
    # from the bundle root, by the same resolver R3 addresses. LUSD's gate is
    # the sheet's `state_conditional(TCR < MCR)`, and NO bundle field carried a
    # system TCR. Emitting it is the same shape of fix R3 already is; the
    # alternatives were to misclassify the gate as `capacity_limited` (loses the
    # condition) or to point C at an unrelated field (false). Reversible.
    system_tcr: Decimal | None = None
    pool_detectors: PoolDetectors
    static_metadata: StaticMetadata
    counts: Counts
    attribution_method: Literal["per_position", "protocol_level_fallback", "direct"]
    first_run_literals: FirstRunLiterals | None = None
    gate_results: list[GateResult] = []
    log_entries: list[LogEntry] = []

    @model_validator(mode="after")
    def _check(self):
        powers = [r.power for r in self.admin_surface]
        if len(set(powers)) != 9:                            # DET-68
            raise ValueError("DET-68: nine A1 powers required")
        if self.first_run_literals is None and self.header.first_run:
            raise ValueError("first_run bundle must carry its literals")
        # R3: the scalar is optional, its provenance is not. A figure DET-66
        # will resolve against must say where it came from (C-2).
        if self.redeemable_collateral_value is not None and \
                not self.redeemable_collateral_reads:
            raise ValueError("redeemable_collateral_value without provenance")
        # P-4.06 queued this move: the identity was enforced in the adapter
        # while no GHO bundle existed to hang it on. It lives here now.
        if self.facilitators:
            levels = sum(f.bucket_level for f in self.facilitators)
            if levels != self.supply.total_supply:
                raise ValueError(f"sum of facilitator bucket levels {levels} != "
                                 f"totalSupply {self.supply.total_supply}")
        return self


# ------------------------------------------------------- the prior view -----


class PriorHeader(BaseModel, extra="ignore"):
    token: str
    run_block: int
    first_run: bool


class PriorCounts(BaseModel, extra="ignore"):
    mint_market_count: int
    lend_market_count: int | str


class PriorSupply(BaseModel, extra="ignore"):
    total_supply: int


class PriorNode(BaseModel, extra="ignore"):
    address: Address
    share_of_backing: Decimal


class PriorPool(BaseModel, extra="ignore"):
    address: Address
    tvl_at_par: int
    ratio_to_frozen_coverage: Decimal


class PriorBundle(BaseModel, extra="ignore"):
    """A stored bundle read as HISTORY, not as a current bundle.

    `load_prior` used to validate the prior through the full `Bundle`. That was
    wrong on principle, and P-3.46 proved it: making `pool_detectors` required
    - correctly, for what a run EMITS - made every previously promoted bundle
    undeserializable, and the demonstration run died before its first read.
    The store will always hold older shapes, and every field Steps 4-6 add
    would recreate the same failure.

    So the two directions are separated. The full `Bundle` validates what this
    run emits and stays strict. This view reads every shape the store has ever
    held, and carries ONLY the fields a delta or cross check actually reads
    from a prior:

      * `header`  - DET-86 (the prior's existence must agree with `first_run`)
      * `counts`  - DET-63's market count; the lend three-state (P-3.45)
      * `supply`  - DET-62's supply jump
      * `nodes`   - DET-65's composition shift
      * `pools`   - DET-10(d)-ii's last-run ratio, and the TVL-change baseline

    `extra="ignore"` throughout, so a field this view does not name is skipped
    rather than rejected. A field that POSTDATES some stored shape defaults to
    TYPED ABSENCE - `pools: list[PriorPool] = []` - never a sentinel and never
    a fabricated value: an older bundle genuinely has no pools, and the
    baseline fallback (`baseline_source = "freeze_set_file"`) is what discloses
    that. Fields present in every shape ever stored stay REQUIRED, so a
    malformed prior fails loudly instead of reading as an empty one.

    This is not a shim and has no retirement condition. A check that reads a
    field this view does not carry fails at attribute access, which the tests
    surface; the field list grows when a delta check needs it to.
    """

    header: PriorHeader
    counts: PriorCounts
    supply: PriorSupply
    nodes: list[PriorNode]
    pools: list[PriorPool] = []


# ------------------------------------------------- verifiability tree -------
# P-5.01 R2/R3: a SIBLING artifact folded from a promoted bundle, never a field
# on `Bundle` - so `Bundle`'s shape and `bundle_hash` do not move. Every share
# and bar is over `backing_value` (R1, DET-19); `supply_ruled` appears only as
# an amount on the root line.


class TreeRoot(BaseModel):
    backing_value: int                   # DET-14(a): sum of nodes[].value
    # Named implementer default (R3): the unit `nodes[].value` is carried in,
    # per adapter - crvUSD whole USD (P-3.34), GHO AaveOracle base 1e8 (P-4.07),
    # LUSD 1e18 (P-4.17). The tree never converts; rendering divides.
    value_scale: int
    backed_supply: int                   # = supply.origination_sum (R1)
    supply_ruled: int
    residual: int
    perimeter: str
    stabilizer_debt: int                 # sum of stabilizer.operations[].current_debt


class TreeShares(BaseModel):
    terminal: Decimal
    terminal_other_layer: Decimal
    recurses: Decimal
    recurses_truncated: Decimal
    unlisted: Decimal                    # U, inside the denominator (R-6)


class TreeBar(BaseModel):
    name: Literal["terminal", "terminal_other_layer", "disclosure_dependent"]
    share: Decimal
    denominator: Literal["backing_value"] = "backing_value"


class TruncatedNode(BaseModel):
    address: Address
    symbol: str
    share: Decimal
    reason: str                          # memo 4.1's reason string


class StalenessNode(BaseModel):
    address: Address
    symbol: str
    share: Decimal
    last_disclosure_date: str | None
    staleness_days: int | None


class StalenessWorst(BaseModel):
    symbol: str
    days: int
    share: Decimal


class TreeStaleness(BaseModel):
    D: list[StalenessNode]
    weighted_days: Decimal | None
    worst: StalenessWorst | None
    companion: str | None
    # Present-and-empty (R3, F3): never a number where an input is null.
    status: str | None


class QualifierRow(BaseModel):
    power: str
    holder_type: str
    signer_disclosure: str               # "n/a" - named default, no A3 field (F6)
    delay_bucket: str | None
    veto: Address | None


class PairedAssetRow(BaseModel):
    pool: Address
    address: Address
    symbol: str | None
    label: str
    source: str | None
    source_tree: str | None = None       # R5: "<token>@<run_block>" when linked
    linked_shares: TreeShares | None = None
    constituents: list[dict[str, Any]] | None = None
    note: str | None = None


class ConcentrationLine(BaseModel):
    largest_paired_asset: Address
    share_of_exit_depth: Decimal         # freeze_tvl-weighted over F
    label: str
    disclosure_source: str | None


class VerifiabilityTree(BaseModel):
    token: str
    run_block: int
    source_bundle_hash: str
    tree_hash: str = ""                  # sha256 over everything but itself
    root: TreeRoot
    shares: TreeShares
    bars: list[TreeBar]
    truncated_share: Decimal
    truncated_nodes: list[TruncatedNode]
    unclassified_literal: str | None
    staleness: TreeStaleness
    qualifier: list[QualifierRow]
    banner: str
    denominators: dict[str, str]
    paired_assets: list[PairedAssetRow]
    concentration: ConcentrationLine | None
    checks: list[GateResult] = []
    flags: list[str] = []


def finalise_tree(tree: VerifiabilityTree) -> VerifiabilityTree:
    """`tree_hash` over the tree with `tree_hash` excluded - the bundle's own
    convention (`finalise`), same O-2 serialisation."""
    payload = tree.model_dump(mode="python", exclude={"tree_hash"})
    h = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                  ensure_ascii=False, default=_default)
                       .encode("utf-8")).hexdigest()
    return tree.model_copy(update={"tree_hash": h})


def serialise_tree(tree: VerifiabilityTree) -> str:
    return json.dumps(tree.model_dump(mode="python"), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False, default=_default)


def _default(o: Any) -> Any:
    if isinstance(o, Decimal):
        return str(o)                                        # O-2: never a float
    if isinstance(o, (_dt.date, _dt.datetime)):
        return o.isoformat()
    raise TypeError(type(o))


def serialise(bundle: Bundle) -> str:
    """Deterministic JSON (O-2): sorted keys, fixed separators, no floats."""
    payload = bundle.model_dump(mode="python", exclude={"header": {"bundle_hash"}})
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=_default)


def serialise_for_disk(bundle: Bundle) -> str:
    """The written artifact, INCLUDING `header.bundle_hash`.

    `serialise()` is the hash INPUT (hash excluded from its own preimage);
    this is the artifact (hash embedded, per DET-13(a)). Same deterministic
    settings (O-2) either way.
    """
    return json.dumps(bundle.model_dump(mode="python"), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False, default=_default)


def finalise(bundle: Bundle) -> tuple[Bundle, str]:
    """Compute `bundle_hash` over everything but itself, then stamp it."""
    h = hashlib.sha256(serialise(bundle).encode("utf-8")).hexdigest()
    stamped = bundle.model_copy(deep=True)
    stamped.header.bundle_hash = h
    return stamped, h


# ------------------------------------------------------- the stress report ---
# P-6.01 R2/R3: a SIBLING artifact again - folded from a promoted bundle, its
# tree and its raw dump, so `Bundle`'s shape and `bundle_hash` do not move.
# Amounts are integer base units at the tree's own `value_scale`; ratios are
# `Decimal` serialised as strings (O-2). B-1 builds the container and the
# routing only: everything below `header` is present-and-empty until its block.


class StressHeader(BaseModel):
    token: str
    run_block: int
    source_bundle_hash: str
    source_tree_hash: str
    # R3: the bundle's stamp and the mirror's, carried SIDE BY SIDE so a stale
    # pairing is a fact in the artifact rather than something inferred later.
    bundle_sheet_hash: str
    mirror_sheet_hash: str
    stale_sheet: bool = False
    pipeline_version: str
    stress_hash: str = ""          # filled last, over everything else


class DepthPoint(BaseModel):
    """Named implementer default (R-B2, ruled 2026-09-12): the GSM term is
    NEVER inside `pool_depth` (DET-35 lists it separately); the headline
    `exit_depth` is `total` at s = 0.02. Amounts are the analyzed token's own
    base units — R-B2.1, not `value_scale`."""

    s: Decimal
    pool_depth: int
    per_pool: dict[Address, int] = {}
    gsm_contribution: int = 0
    total: int


class GsmVenue(BaseModel):
    """DET-35 / §5.10. `fee_exit` is the fee on stablecoin -> boxed asset,
    which is the GSM's BUY fee, not its sell fee (Inventory B F12).

    The boxed asset is a stata wrapper, not the bare stable (C2): `balance` is
    the wrapper balance put through `convertToAssets` and counted at 1.00 per
    unit of the UNDERLYING — §6.1.3's par applied through §4.3's pass-through,
    which is R-B2.6's rate-scaled logic applied to a venue instead of a pool.
    """

    gsm: Address
    boxed_asset: Address
    underlying: Address                               # C2: the §4.3 look-through
    fee_exit: Decimal
    exchange_rate: Decimal                            # ERC-4626 shares -> assets
    balance: int          # CONVERTED to the underlying, then scaled to 18 dp
    enters: bool
    reason: str


class SensitivityRow(BaseModel):
    k: str                                            # "80" / "90" / "95"
    pools: list[Address]
    depth_at_2pct: int
    share_of_F: Decimal


class DepthConcentration(BaseModel):
    """§5.3's concentration line recomputed on the DEPTH basis (Inventory B
    F18). The tree's own `concentration` stays freeze-TVL-weighted and is
    untouched; which one a report renders is Step 7's question."""

    largest_paired_asset: Address
    share_of_exit_depth: Decimal
    label: str
    disclosure_source: str | None = None


class GroundTruth(BaseModel):
    """DET-31's `get_dy` ground truth, RECORDED during the fold so the harness
    stays pure. The comparison needs an `eth_call` at `run_block` and
    `run_stress_checks` is given no RPC — as `run_tree_checks` is not — so the
    evidence is written into the artifact and `det_31` asserts over it. Named
    addition beyond the B-2 proposal (2026-09-12)."""

    pool: Address
    dx: int                                           # the pipeline's own depth
    ddx: int
    onchain_dy_at_dx: int
    onchain_dy_at_dx_plus: int
    implied_price: Decimal
    within_epsilon: bool


class Member2Candidate(BaseModel):
    """DET-50's replay input, RECORDED so the harness stays pure (B-3a).

    One row per asset that could be the Member-2 target, at s = 2%, carrying the
    label it holds under DET-11/§4 and HOW it reached the table. `linked` assets
    are recorded with their label and excluded by the selector, not dropped:
    §6.2.5 excludes them by ruling, and a reader should see that it happened.
    """

    asset: Address
    depth_at_2pct: int
    share: Decimal
    label: str
    basis: Literal["paired_direct", "composite_constituent", "gsm_venue"]


class ExitDepth(BaseModel):
    """B-2's home. `lp_flight_literal` is the section 6.1.4 text, a constant
    rather than a computed figure."""

    ground_truth: list[GroundTruth] = []
    # R-B2.6: the metapool's second rate is the base pool's virtual price at
    # `run_block`, and it is real content rather than a decimals scale — so it
    # is RECORDED beside the reads rather than left implicit. Keyed by metapool
    # address; empty for every single-asset pool.
    base_virtual_price: dict[Address, int] = {}
    # C4, closed at B-2 (R-B2.8): base pool -> {constituent -> balance at
    # `run_block`}. RAW BALANCES ONLY, nothing derived — the composite's
    # pass-through weights and LUSD's Member-2 target are computed from these
    # at B-3, never here. `{}` for a token with no metapool in F.
    base_pool_composition: dict[Address, dict[Address, int]] = {}
    member2_candidates: list[Member2Candidate] = []   # DET-50's replay, B-3a
    depth_curve: list[DepthPoint] = []
    k_subsets: dict[str, list[Address]] = {}          # keys "80" / "90" / "95"
    sensitivity_rows: list[SensitivityRow] = []
    gsm_venues: list[GsmVenue] = []
    concentration: DepthConcentration | None = None
    lp_flight_literal: str
    reads: dict[str, Provenance] = {}


class Mechanism(BaseModel):
    """ONE model with optional fields - the `Market`/R1 pattern (P-4.13), not
    three models. crvUSD's four, GHO's two and LUSD's three sit together and a
    token fills only its own; nothing is required until its block."""

    effective_headroom: int | None = None             # crvUSD, B-4
    naive_headroom: int | None = None
    provide_allowed: dict[Address, int] = {}
    withdraw_allowed: dict[Address, int] = {}
    h2_routing: dict[Address, str] = {}               # GHO, B-5
    binding_side: dict[str, str] = {}
    sp_balance: int | None = None                     # LUSD, B-6
    base_rate: int | None = None
    redemption_capacity: int | None = None


class MetricReading(BaseModel):
    ratio: Decimal
    share_below_100: Decimal


class MetricOne(BaseModel):
    """DET-39: two readings and the gap between them; post is the headline."""

    pre: MetricReading
    post: MetricReading
    gap: Decimal


class MetricTwo(BaseModel):
    bad_debt: int
    pct_supply: Decimal                               # over `supply_ruled` (R1)


class MetricThree(BaseModel):
    ratio: Decimal
    forced_sell_volume: int
    exit_depth: int


class CounterfactualLine(BaseModel):
    """DET-44. A line under metric 4, NEVER a cell axis (memo section 6.3)."""

    id: str
    assumption_text: str
    metric_affected: str
    value_primary: Decimal | int | None = None
    value_counterfactual: Decimal | int | None = None
    approximation_flag: bool = False


class Cell(BaseModel):
    """NOTHING here is optional: a cell is only ever constructed complete, so
    optionality lives at the report level (`cells = []`) rather than inside a
    row. `id` follows the named default `M1-s20-d0-lp0` / `M2-t0.97-lp30` /
    `M2-compound` / `JOINT`; DET-37 asserts uniqueness and the 47/47/23 count
    rather than trusting the scheme."""

    id: str
    member: Literal["M1", "M2", "M2_COMPOUND", "JOINT"]
    shock: Decimal | None
    lst: Decimal | None
    lp: Decimal
    target: Decimal | None
    m1: MetricOne
    m2: MetricTwo
    m3: MetricThree
    m4: dict[str, Any]                                # = the sheet's m4_fields[]
    counterfactual_lines: list[CounterfactualLine] = []
    lineage: list[Lineage] = []


class StressReport(BaseModel):
    header: StressHeader
    # Copied from `tree.root.value_scale`, never recomputed: `tree.VALUE_SCALE`
    # stays the one owner of the per-token unit (P-6.01 R2).
    value_scale: int
    member2_target: Address | None = None             # from the set file; B-3
    exit_depth: ExitDepth
    mechanism: Mechanism
    cells: list[Cell] = []
    reference_points: list[dict[str, Any]] = []       # DET-48, B-4
    assumptions: dict[str, str] = {}                  # DET-57, B-7
    checks: list[GateResult] = []
    flags: list[str] = []


def finalise_stress(report: StressReport) -> StressReport:
    """`stress_hash` over the report with `stress_hash` excluded. The exclusion
    is NESTED - the stamp lives in `header`, unlike the tree's top-level
    `tree_hash` - so this takes `serialise(bundle)`'s form, not
    `finalise_tree`'s."""
    payload = report.model_dump(mode="python", exclude={"header": {"stress_hash"}})
    h = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                  ensure_ascii=False, default=_default)
                       .encode("utf-8")).hexdigest()
    return report.model_copy(update={
        "header": report.header.model_copy(update={"stress_hash": h})})


def serialise_stress(report: StressReport) -> str:
    return json.dumps(report.model_dump(mode="python"), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False, default=_default)
