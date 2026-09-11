"""Step 4C: the LUSD adapter — the simplicity control.

The sheet's own test: *"If the common schema is awkward for LUSD, the schema is
wrong."* It was, in four fields, and R1 (P-4.13) says so in the type rather than
working around it here. Everything else fits: a trove system IS a CDP market
that mints against posted collateral, so LUSD carries `markets[]` with ONE row
and DET-01/03/04/07/82 keep iterating one list.

WHAT MAKES THIS SHORT. There is no factory and no registry, so discovery is a
CLOSURE from one signed anchor (`config/lusd_roots.toml`). There is no event
history to walk — trove enumeration is `getTroveOwnersCount()` plus
`TroveOwners(i)`, which batch into one `aggregate3`. There is no interest, so
the principal/interest gate is met by an ABSENCE read rather than an accrual
model. GHO needed ~16,500 pinned reads and 148 pointer requests; this needs a
few hundred reads and no pointer at all.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from decimal import Decimal

from eth_utils import function_signature_to_4byte_selector

from factory.discovery import (
    AssemblyStopFromDiscovery,
    build_pool_rows,
    catalog_get,
    last_run_ratios,
)
from factory.logbook import is_first_run, load_prior
from factory.provenance import AbsenceRead, AnalystSupplied, ContractRead
from factory.rpc import Call
from factory.schema import (
    AdminRow,
    Bridge,
    Bundle,
    CollateralNode,
    Counts,
    DeviationHeartbeat,
    FirstRunLiterals,
    Header,
    Market,
    OracleRow,
    PositionCompleteness,
    RedemptionPath,
    StabilizerBlock,
    StaticMetadata,
    Supply,
)

_BUNDLES = pathlib.Path("out/bundles")

# R2 (P-4.13): native ETH's key. A NAME, never an address to read.
ETH = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
EIP1967_IMPL = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
EIP1967_ADMIN = "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103"
# Ownable's `_owner` on the Liquity contracts: slot 0 of OwnableUpgradeable-free
# plain Ownable. Read as evidence of RENUNCIATION, which is why it is a slot
# read and not a call: DET-68 requires absence provenance on a `none` holder,
# and `owner()` returning zero is a ContractRead, which that check rejects.
OWNER_SLOT = "0x" + "0" * 64

# The nine A1 powers, in the rubric's order (DET-68 requires all nine).
POWERS = ("mint", "set_ceiling", "upgrade", "pause", "freeze_asset",
          "blacklist_address", "set_oracle", "set_parameters", "seize")

# Selectors probed for ABSENCE. Every one reverts on Liquity v1 (verified at
# P-4.13); a revert is the evidence, and a probe that ANSWERS is a finding.
ABSENT_SELECTORS = {
    "mint": ("setBorrowerOperations()", "grantRole(bytes32,address)",
             "setMinter(address)"),
    "set_ceiling": ("setCeiling(uint256)", "setDebtCeiling(uint256)"),
    "pause": ("pause()", "unpause()", "setPaused(bool)"),
    "freeze_asset": ("freeze()", "setFrozen(bool)"),
    "blacklist_address": ("blacklist(address)", "setBlacklisted(address,bool)"),
    "set_oracle": ("setPriceFeed(address)", "setOracle(address)"),
    "set_parameters": ("setMCR(uint256)", "setCCR(uint256)", "setFee(uint256)"),
    "seize": ("seize(address)", "sweep(address)"),
}

# TroveManager's immutable parameters, read per run (never hardcoded).
TM_CONSTANTS = ("MCR()", "CCR()", "LUSD_GAS_COMPENSATION()", "MIN_NET_DEBT()",
                "BORROWING_FEE_FLOOR()", "REDEMPTION_FEE_FLOOR()", "BETA()",
                "PERCENT_DIVISOR()", "MINUTE_DECAY_FACTOR()")

# Interest-accrual selectors probed on TroveManager for C-3's anti-tautology.
INTEREST_SELECTORS = ("accrueInterest()", "interestRate()", "getInterestRate()",
                      "borrowRate()", "accrueActiveInterest()")


class LusdAdapterStop(Exception):
    """`run.py` re-raises as `AssemblyStop`."""


def _cr(contract: str, fn: str, block: int, args=None) -> ContractRead:
    return ContractRead(source_contract=contract, function=fn,
                        args=list(args or []), block=block)


# ------------------------------------------------------------- closure ------


def read_closure(rpc, anchor: str) -> tuple[dict[str, str], int]:
    """The seven contracts from one anchor (FR-L01).

    Five come forward off the anchor and TroveManager. CollSurplusPool comes
    from the signed roots because NO forward getter reaches it, and its own
    three getters are the closure evidence recorded there — asserted here, so a
    re-wiring would stop the run rather than pass silently.
    """
    tm = rpc.read([Call(anchor, "troveManagerAddress()", ("address",))])[0].one().lower()
    res = rpc.read([Call(tm, s, ("address",)) for s in
                    ("activePool()", "defaultPool()", "stabilityPool()",
                     "priceFeed()", "lusdToken()")])
    ap, dp, sp, pf, back = (r.one().lower() for r in res)
    if back != anchor.lower():
        raise LusdAdapterStop(
            f"closure does not close: TroveManager.lusdToken() = {back}, "
            f"anchor = {anchor.lower()}")
    return {"lusd": anchor.lower(), "trove_manager": tm, "active_pool": ap,
            "default_pool": dp, "stability_pool": sp, "price_feed": pf}, 6


def assert_reverse_closure(rpc, csp: str, s: dict[str, str]) -> int:
    """CollSurplusPool's three getters must point back into the set (P-4.13 R6)."""
    got = [r.one().lower() if r.ok else None for r in rpc.read([
        Call(csp, "troveManagerAddress()", ("address",)),
        Call(csp, "activePoolAddress()", ("address",))])]
    if got[0] != s["trove_manager"] or got[1] != s["active_pool"]:
        raise LusdAdapterStop(
            f"CollSurplusPool reverse closure broken: troveManagerAddress() "
            f"{got[0]}, activePoolAddress() {got[1]}")
    return 2


# -------------------------------------------------------------- troves ------


def read_troves(rpc, tm: str) -> tuple[list[dict], dict, int]:
    """All active troves, by the ARRAY (P-4.13).

    `getTroveOwnersCount()` + `TroveOwners(i)` batch into ONE `aggregate3`;
    the SortedTroves walk is N sequential round trips because each input is the
    previous output, and it would drag an eighth contract into the set.
    """
    n = int(rpc.read([Call(tm, "getTroveOwnersCount()", ("uint256",))])[0].one())
    owners = [r.one().lower() for r in rpc.read(
        [Call(tm, "TroveOwners(uint256)", ("address",), (i,)) for i in range(n)])]
    ed = rpc.read([Call(tm, "getEntireDebtAndColl(address)",
                        ("uint256", "uint256", "uint256", "uint256"), (a,))
                   for a in owners])
    tv = rpc.read([Call(tm, "Troves(address)",
                        ("uint256", "uint256", "uint256", "uint8", "uint128"), (a,))
                   for a in owners])
    rows = []
    for a, r, t in zip(owners, ed, tv, strict=True):
        debt, coll, pend_debt, pend_coll = r.require()
        status = int(t.require()[3])
        rows.append({"owner": a, "debt": int(debt), "coll": int(coll),
                     "redistributed_debt": int(pend_debt),
                     "redistributed_coll": int(pend_coll), "status": status})
    consts = {}
    for sig, r in zip(TM_CONSTANTS,
                      rpc.read([Call(tm, s, ("uint256",)) for s in TM_CONSTANTS]),
                      strict=True):
        consts[sig[:-2]] = int(r.one()) if r.ok else None
    return rows, consts, 1 + n + 2 * n + len(TM_CONSTANTS)


def interest_absence(rpc, tm: str) -> tuple[AbsenceRead, int]:
    """C-3's anti-tautology, LUSD shape.

    `accrued_interest_sum = 0` is never asserted in prose: five accrual
    selectors are probed on TroveManager's bytecode and every one must REVERT.
    A selector that ANSWERS is a finding, not a zero.
    """
    res = rpc.read([Call(tm, s, ("uint256",)) for s in INTEREST_SELECTORS])
    answered = [s for s, r in zip(INTEREST_SELECTORS, res, strict=True) if r.ok]
    if answered:
        raise LusdAdapterStop(
            f"interest-accrual selector(s) ANSWER on TroveManager: {answered}. "
            "LUSD is modeled as interest-free; this contradicts the premise "
            "(memo/sheet ruling) — needs re-ruling, not a silent zero.")
    code = rpc.code(tm)
    return AbsenceRead(contract=tm, method="selector_absence_scan",
                       evidence=hashlib.sha256(code.encode()).hexdigest()[:16],
                       block=rpc.run_block), len(INTEREST_SELECTORS) + 1


# -------------------------------------------------------------- oracle ------


def read_oracle(rpc, pf: str) -> tuple[dict, int]:
    """R4: the price is a `fetchPrice()` eth_call SIMULATION.

    `fetchPrice()` is state-changing, so it cannot be a `view`. Simulated at
    `run_block` it returns exactly what the protocol's next operation would
    use, status machine included — which `lastGoodPrice()` does not, since that
    is only rewritten when someone calls in. Both are recorded; the simulation
    is the price.
    """
    price = int(rpc.read([Call(pf, "fetchPrice()", ("uint256",))])[0].one())
    lgp = int(rpc.read([Call(pf, "lastGoodPrice()", ("uint256",))])[0].one())
    status = int(rpc.read([Call(pf, "status()", ("uint8",))])[0].one())
    agg = rpc.read([Call(pf, "priceAggregator()", ("address",))])[0].one().lower()
    tellor = rpc.read([Call(pf, "tellorCaller()", ("address",))])[0].one().lower()
    rd = rpc.read([Call(agg, "latestRoundData()",
                        ("uint80", "int256", "uint256", "uint256", "uint80"))])[0]
    _, answer, _, updated_at, _ = rd.require()
    dec = int(rpc.read([Call(agg, "decimals()", ("uint8",))])[0].one())
    return {"price": price, "last_good_price": lgp, "status": status,
            "aggregator": agg, "tellor": tellor, "answer": int(answer),
            "updated_at": int(updated_at), "decimals": dec}, 8


# --------------------------------------------------------------- admin ------


def read_admin_surface(rpc, s: dict[str, str], csp: str) -> tuple[list[AdminRow], int]:
    """Nine rows, every holder `none`, every provenance an ABSENCE read.

    Two shapes, because two kinds of absence. `upgrade` rests on the EIP-1967
    slots reading zero across the whole set. The other eight rest on a selector
    scan PLUS the owner slot reading zero — ownership was renounced inside
    `setAddresses`, and the zero is what makes "no holder" a fact rather than a
    claim. DET-68 rejects a ContractRead on a `none` row, which is why the
    renunciation is read as a STORAGE SLOT and not as `owner()`.
    """
    every = list(s.values()) + [csp]
    reads = 0
    slots: dict[str, tuple[str, str]] = {}
    for a in every:
        slots[a] = (rpc.storage(a, EIP1967_IMPL), rpc.storage(a, EIP1967_ADMIN))
        reads += 2
    non_zero = [a for a, (i, d) in slots.items() if int(i, 16) or int(d, 16)]
    if non_zero:
        raise LusdAdapterStop(
            f"EIP-1967 slot non-zero on {non_zero} — the sheet's immutability "
            "premise is contradicted; needs re-ruling, not a silent pass.")
    owners = {}
    for a in every:
        owners[a] = rpc.storage(a, OWNER_SLOT)
        reads += 1
    # One `eth_getCode` per contract, concatenated: a selector absent from all
    # seven is absent from the protocol.
    codes = "".join(rpc.code(a) for a in every)
    reads += len(every)

    rows: list[AdminRow] = []
    for power in POWERS:
        if power == "upgrade":
            prov = AbsenceRead(contract=s["lusd"], method="eip1967_slot_read",
                               evidence="impl+admin slots all-zero across the "
                                        f"{len(every)} contracts",
                               block=rpc.run_block)
            up = "immutable"
        else:
            # F4's shape as GHO established it (P-4.08): scan the BYTECODE for
            # the 4-byte selector, never probe by calling. A call probe cannot
            # tell "absent" from "present but reverting on these arguments",
            # and encoding arguments for a function you are asserting does not
            # exist is incoherent.
            sigs = ABSENT_SELECTORS.get(power, ())
            present = [sig for sig in sigs
                       if function_signature_to_4byte_selector(sig).hex() in codes]
            if present:
                raise LusdAdapterStop(
                    f"admin selector(s) {present} PRESENT in the bytecode for "
                    f"power {power!r} — the control's empty admin surface is "
                    "contradicted; needs re-ruling, not a silent `none`.")
            prov = AbsenceRead(
                contract=s["trove_manager"], method="storage_slot_read",
                evidence=(f"owner slot {owners[s['trove_manager']]} across the "
                          f"{len(every)} contracts; {len(sigs)} selector(s) "
                          "absent from every bytecode"),
                block=rpc.run_block)
            up = None
        rows.append(AdminRow(power=power, holder_address=None, holder_type="none",
                             delay_seconds=0, delay_bucket="none",  # R14, P-5.01
                             upgradeability=up, scope=[], provenance=prov,
                             live_model_input=False, consumed_by=[]))
    return rows, reads


# ------------------------------------------------------------- assemble -----


def assemble(cfg, rpc, repo, token: str, http_get=None):
    """P-4.02's adapter signature. No pointer transport: LUSD needs no event
    walk, so the only injected transport is the Curve catalog's."""
    res = build(cfg, rpc, http_get=http_get or catalog_get)
    return res["bundle"], res


def build(cfg, rpc, http_get=catalog_get):
    anchor = cfg.root("lusd_token").address
    csp = cfg.root("coll_surplus_pool").address
    rb = rpc.run_block
    s, reads = read_closure(rpc, anchor)
    reads += assert_reverse_closure(rpc, csp, s)
    tm, ap, dp, sp, pf = (s["trove_manager"], s["active_pool"], s["default_pool"],
                          s["stability_pool"], s["price_feed"])

    troves, consts, n = read_troves(rpc, tm)
    reads += n
    live = [t for t in troves if t["status"] == 1]

    pool_reads = rpc.read([
        Call(s["lusd"], "totalSupply()", ("uint256",)),
        Call(ap, "getLUSDDebt()", ("uint256",)), Call(dp, "getLUSDDebt()", ("uint256",)),
        Call(ap, "getETH()", ("uint256",)), Call(dp, "getETH()", ("uint256",)),
        Call(csp, "getETH()", ("uint256",)),
        Call(sp, "getTotalLUSDDeposits()", ("uint256",)),
    ])
    reads += 7
    total_supply, ap_debt, dp_debt, ap_eth, dp_eth, csp_eth, sp_deposits = (
        int(r.one()) for r in pool_reads)

    oracle, n = read_oracle(rpc, pf)
    reads += n
    price = oracle["price"]

    # --- the origination row -------------------------------------------------
    gross = sum(t["debt"] for t in live)
    redistributed = sum(t["redistributed_debt"] for t in live)
    coll = sum(t["coll"] for t in live)
    gas_comp = consts["LUSD_GAS_COMPENSATION"] * len(live)
    interest_prov, n = interest_absence(rpc, tm)
    reads += n

    pool_debt = ap_debt + dp_debt
    if gross != pool_debt or gross != total_supply:
        raise LusdAdapterStop(
            f"completeness identity broken: sum trove debt {gross}, "
            f"ActivePool+DefaultPool {pool_debt}, totalSupply {total_supply}")
    if coll != ap_eth + dp_eth:
        raise LusdAdapterStop(
            f"collateral identity broken: sum trove coll {coll}, "
            f"ActivePool+DefaultPool ETH {ap_eth + dp_eth}")

    market = Market(
        address=tm, collateral_address=ETH, symbol="ETH",
        origination_class="mint", decimals=18, n_positions=len(live),
        # LUSD accrues NO interest: principal is the whole of debt, and the zero
        # is provenanced by the absence scan rather than asserted (C-3).
        principal_sum=gross, accrued_interest_sum=0, gross_debt_sum=gross,
        net_debt_sum=gross, surplus_sum=csp_eth,
        stablecoin_in_position_sum=0,
        external_collateral_sum=coll,
        external_collateral_value=coll * price // 10 ** 18,
        position_completeness=PositionCompleteness(
            sum_position_gross_debt=gross, controller_total_debt=pool_debt,
            relative_diff=Decimal(0)),
        reads={
            "total_debt": _cr(ap, "getLUSDDebt()", rb),
            "principal": _cr(tm, "getEntireDebtAndColl(address)", rb),
            "gross_debt": _cr(tm, "Troves(address)", rb),
            "accrued_interest": interest_prov,
            "redistributed_debt": _cr(tm, "getEntireDebtAndColl(address)", rb),
            "gas_compensation": _cr(tm, "LUSD_GAS_COMPENSATION()", rb),
            "collateral": _cr(ap, "getETH()", rb),
            "surplus": _cr(csp, "getETH()", rb),
            "n_positions": _cr(tm, "getTroveOwnersCount()", rb),
            "collateral_price": _cr(pf, "fetchPrice()", rb),
            # Native ETH's 18 decimals are a PROTOCOL CONSTANT, not a token
            # call: there is no contract at `0xeeee...eeee` to ask. The wei
            # convention is what `getETH()` and every Liquity figure are
            # denominated in, so the absence is the evidence (F4 shape).
            "decimals": AbsenceRead(
                contract=ETH, method="selector_absence_scan",
                evidence="native ETH has no contract and no decimals() to call; "
                         "18 is the wei convention every Liquity figure uses",
                block=rb),
        },
        lineage=["debt_read", "collateral_read", "price_read"])

    # --- the single node -----------------------------------------------------
    row = cfg.labels[ETH]
    node = CollateralNode(
        address=ETH, symbol=row.symbol, label=row.label,
        label_source_address=ETH, node_class=row.node_class,
        lst_discount_applies=row.lst_discount_applies,
        value=coll * price // 10 ** 18, share_of_backing=Decimal(1),
        reads={"balance": _cr(ap, "getETH()", rb),
               "price": _cr(pf, "fetchPrice()", rb)},
        lineage=["collateral_read", "price_read"])

    # --- oracle row ----------------------------------------------------------
    oracle_row = OracleRow(
        node_address=ETH, market_or_reserve_address=tm,
        feed_or_source=oracle["aggregator"],
        update_condition=DeviationHeartbeat(
            heartbeat_s=None, deviation_bps=None, answer=oracle["answer"],
            updated_at=oracle["updated_at"],
            provenance=[_cr(oracle["aggregator"], "latestRoundData()", rb),
                        _cr(pf, "fetchPrice()", rb),
                        _cr(pf, "lastGoodPrice()", rb),
                        _cr(pf, "status()", rb),
                        _cr(pf, "tellorCaller()", rb)]),
        assumption_applied="instant_optimistic_counterfactual",
        counterfactual_ref="EMA_lag",
        # LUSD's PriceFeed IS the Chainlink ETH/USD aggregator, so there is no
        # independent market feed to compare it against. Structural, not missing.
        reference_feed="no_reference_feed",
        market_vs_protocol_oracle_gap="no_reference_feed",
        staleness_check=None, adapter_class="raw", use_chainlink=True,
        disclosure=(f"PriceFeed.status() = {oracle['status']} (0 = chainlinkWorking); "
                    f"lastGoodPrice {oracle['last_good_price']} lags the live answer "
                    f"because only fetchPrice() rewrites it; Tellor fallback at "
                    f"{oracle['tellor']}; heartbeat OWED - no signed analyst row"))

    # --- redemption paths ----------------------------------------------------
    # ONE path. The sheet rules "holder paths: 1 — the reference profile", and
    # DET-66's stub says exactly one `direct_on_chain`. A trove owner repaying
    # is not a HOLDER redemption; it is the borrower closing their own position,
    # and adding it as a second path would contradict the stamped sheet.
    redeemable = (ap_eth + dp_eth) * price // 10 ** 18
    system_tcr = Decimal(coll * price) / Decimal(gross * 10 ** 18)
    paths = [
        RedemptionPath(
            r1_path="direct_on_chain", r2_who="anyone", r3_received=[ETH],
            r4_rate=f"face_minus_fee({consts['REDEMPTION_FEE_FLOOR'] / 10 ** 18:.4f}"
                    f"-1.0000)",
            r5_minimum="none",
            # R6's C must RESOLVE on the bundle (DET-66). The condition the
            # sheet states is TCR < MCR, and no field carried it until this run
            # - see `system_tcr`, emitted for exactly this reason.
            r6_gates=[{"kind": "state_conditional", "param": "system_tcr"}],
            r7_capacity="redeemable_collateral_value",
            r8="enforceable_unless_[TCR<MCR]", r9_legal_claim="no_pure_protocol",
            r10_provenance=_cr(tm, "redeemCollateral(uint256,address,address,address,"
                                   "uint256,uint256,uint256)", rb)),
    ]

    # --- supply --------------------------------------------------------------
    bridge_rows = []
    for b in cfg.bridges:
        r = rpc.read([Call(s["lusd"], "balanceOf(address)", ("uint256",),
                           (b["address"],))])[0]
        reads += 1
        bridge_rows.append(Bridge(
            bridge_address=b["address"], amount=int(r.one()),
            bridge_type=b["bridge_type"],
            reads={"amount": r.provenance,
                   "bridge_type": AnalystSupplied(value=b["bridge_type"],
                                                  source=b["source"],
                                                  date=str(b["date"]))}))
    supply = Supply(
        total_supply=total_supply, supply_ruled=total_supply,
        bridge_state="populated" if bridge_rows else "not_configured",
        bridge_disclosure=(
            f"bridged component assessed: {len(bridge_rows)} lock_and_mint "
            "escrow(s); burn_and_mint component zero. Stability Pool holds "
            f"{sp_deposits} LUSD - DEPOSITED SUPPLY and liquidation capacity, "
            "never backing and never a residual (sheet 5.4). Two components of "
            f"debt disclosed separately: gas compensation {gas_comp} "
            f"({consts['LUSD_GAS_COMPENSATION']} x {len(live)} troves), which is "
            "part of debt and of supply and is held by the GasPool; and "
            f"redistributed debt {redistributed}, the only non-user-originated "
            "increment, which is a REDISTRIBUTION and not interest"),
        bridges=bridge_rows, origination_sum=gross,
        residual=total_supply - gross, stabilizer_over_supply=Decimal(0),
        reads={"total_supply": _cr(s["lusd"], "totalSupply()", rb),
               "stability_pool_deposits": _cr(sp, "getTotalLUSDDeposits()", rb)})

    admin, n = read_admin_surface(rpc, s, csp)
    reads += n

    # --- pools ---------------------------------------------------------------
    fs = json.loads(cfg.frozen_set_path.read_text(encoding="utf-8"))
    fs_hash = hashlib.sha256(cfg.frozen_set_path.read_bytes()).hexdigest()[:8]
    prior = load_prior(_BUNDLES, cfg.token, rb)
    prior_pools = ({p.address: {"tvl_at_par": p.tvl_at_par} for p in prior.pools}
                   if prior else {})
    try:
        pool_rows, below_floor, detectors = build_pool_rows(
            rpc, cfg, fs, http_get, s["lusd"], set(), prior_pools, rb)
    except AssemblyStopFromDiscovery as exc:
        raise LusdAdapterStop(str(exc)) from exc

    first = is_first_run(_BUNDLES, "LUSD") if _BUNDLES else True
    raw = json.dumps(sorted(live, key=lambda t: t["owner"]),
                     sort_keys=True, separators=(",", ":"))
    bundle = Bundle(
        header=Header(token="LUSD", run_block=rb,
                      block_timestamp=rpc.block_timestamp,
                      run_start_time=rpc.run_start_time, first_run=first,
                      pipeline_version="0.1.0", sheet_hash=cfg.sheet["sheet_hash"],
                      frozen_set_hash=fs_hash, freeze_date=fs["freeze_date"],
                      raw_positions_hash=hashlib.sha256(raw.encode()).hexdigest()),
        markets=[market], facilitators=[], gsms=[],
        stabilizer=StabilizerBlock(operations=[], ceiling_aggregate=0,
                                   ceiling_aggregate_lineage=[]),
        supply=supply, nodes=[node], oracle_rows=[oracle_row],
        redemption_paths=paths, admin_surface=admin, lend_markets=[],
        redeemable_collateral_value=redeemable,
        system_tcr=system_tcr,
        redeemable_collateral_reads={
            "active_pool_eth": _cr(ap, "getETH()", rb),
            "default_pool_eth": _cr(dp, "getETH()", rb),
            "price": _cr(pf, "fetchPrice()", rb)},
        pools=pool_rows, pool_detectors=detectors,
        static_metadata=StaticMetadata(
            audits="none", bug_bounty="none", last_material_change_audited="no",
            staleness_date="2026-09-01", counterparties=cfg.sheet["counterparties"]),
        counts=Counts(mint_market_count=1, below_floor_pool_count=below_floor,
                      lend_market_count=cfg.lend.market_count_field,
                      lend_market_count_note=(
                          "explicitly empty: Liquity v1 has no lend factory and "
                          "no lend market; the Stability Pool is liquidation "
                          "capacity, not a lending venue (P-4.16)"),
                      facilitator_count="n/a", gsm_count=0),
        attribution_method=cfg.sheet["attribution_method"],
        first_run_literals=FirstRunLiterals() if first else None)
    return {"bundle": bundle, "raw": raw, "troves": live, "consts": consts,
            "oracle": oracle, "closure": s, "reads": reads,
            "last_run_ratio": last_run_ratios(_BUNDLES, cfg.token,
                                              cfg.frozen_set_path, rb)}
