"""B-6(1): end-to-end assembly — live reads -> models -> harness -> promotion.

Promotion is reachable only through the gate: `run_harness` raises, so every
line after it is unreachable on a Level 3. That is the B-3b lesson (P-3.27)
applied to the last composition seam in Step 3.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import sys
import time
from decimal import Decimal

from factory.config import Config, load
from factory.logbook import is_first_run, load_prior
from factory.provenance import AbsenceRead, AnalystSupplied, ContractRead
from factory.reads import (
    EIP1967_IMPL_SLOT,
    aggregate_positions,
    loan_slot,
    verify_slot_layout,
)
from factory.rpc import Call, RpcClient
from factory.schema import (
    AdminRow,
    Bridge,
    Bundle,
    CollateralNode,
    Counts,
    EmaWindow,
    FirstRunLiterals,
    GateResult,
    Header,
    Market,
    OracleRow,
    PositionCompleteness,
    RedemptionPath,
    StabilizerBlock,
    StabilizerOperation,
    StaticMetadata,
    Supply,
    finalise,
    serialise_for_disk,
)
from factory.spotcheck import write as write_spotcheck
from factory.validate.harness import TRIGGER_TABLE, run_harness

PIPELINE_VERSION = "0.1.0"
CRVUSD = "0xf939e0a03fb07f59a73314e73794be0e57ac1b4e"
A1_POWERS = ("mint", "set_ceiling", "upgrade", "pause", "freeze_asset",
             "blacklist_address", "set_oracle", "set_parameters", "seize")
# Rows whose stamped section-13 veto column names the Emergency DAO (FR-31).
VETO_ROWS = ("set_ceiling", "set_oracle", "set_parameters")


class AssemblyStop(Exception):
    """A precondition the bundle cannot be assembled without. Not a gate
    failure — a statement that the inputs are incomplete."""


def _cr(contract: str, fn: str, block: int, args=()) -> ContractRead:
    return ContractRead(source_contract=contract.lower(), function=fn,
                        args=[str(a) for a in args], block=block)


def resolve_ema_window(rpc, oracle: str, seen: set[str] | None = None,
                       constituents: dict[str, list[str]] | None = None) -> tuple[int, list]:
    """Transitive-max price-EMA window (P-3.32), live.

    Route (a): zero-arg address getters -> pool `ma_time` / `ma_exp_time`.
    Route (b): indexed `POOLS(i)` up to `POOL_COUNT`.
    Chained oracles recurse; the max over the whole chain wins.
    Raises AssemblyStop where neither route yields a window — the constructor-arg
    route (P-3.32 route 2) needs a dated config entry, which does not exist yet.
    """
    seen = seen or set()
    if oracle in seen:
        return 0, []
    seen.add(oracle)
    hops: list[dict] = []
    best = 0

    def window_of(addr: str) -> int | None:
        for sig in ("ma_time()", "ma_exp_time()"):
            r = rpc.read([Call(addr, sig, ("uint256",))])[0]
            if r.ok:
                return int(r.one())
        return None

    cands: list[str] = []
    for g in ("STABLESWAP", "TRICRYPTO", "STAKEDSWAP", "POOL", "stableswap",
              "staked_swap", "AGG"):
        r = rpc.read([Call(oracle, f"{g}()", ("address",))])[0]
        if r.ok:
            cands.append(r.one().lower())
    # route 2 (P-3.32): addresses from the signed config entry, windows from chain
    for a in (constituents or {}).get(oracle, []):
        cands.append(a)
    pc = rpc.read([Call(oracle, "POOL_COUNT()", ("uint256",))])[0]
    if pc.ok:
        for i in range(int(pc.one())):
            r = rpc.read([Call(oracle, "POOLS(uint256)", ("address",), (i,))])[0]
            if r.ok:
                cands.append(r.one().lower())

    for a in dict.fromkeys(cands):
        w = window_of(a)
        if w is not None:
            hops.append({"hop": a, "window_s": w, "via": "pool"})
            best = max(best, w)
            continue
        sub, subhops = resolve_ema_window(rpc, a, seen, constituents)  # chained oracle
        if sub:
            hops.append({"hop": a, "window_s": sub, "via": "oracle_chain"})
            hops.extend(subhops)
            best = max(best, sub)
    if best == 0:
        raise AssemblyStop(
            f"oracle {oracle}: no constituent window via getters or POOLS walk. "
            "P-3.32 route 2 (verified constructor args) ruled the provenance form "
            "but no dated config entry was ever created for it."
        )
    return best, hops


def resolve_wallet_registry_label(rpc, entry: dict) -> tuple[str, ContractRead] | None:
    """DET-76(c): the per-run read IS the label authority (P-3.37 binding 2).

    Memo 4.4 branch 1 - reserves locatable on-chain without any disclosure ->
    `terminal_other_layer` (verifiable on the Bitcoin chain, which this pipeline
    does not read). Branch 2 - a custodian or committee disclosure is required
    to locate them -> `recurses`, as WBTC. An unreachable read returns None:
    unlabeled-in-run, routed via 8.2 / DET-08, never a default label (A5).
    """
    rb = rpc.run_block
    locator = rpc.read([Call(entry["bridge_address"], "activeWalletPubKeyHash()",
                             ("bytes20",))])[0]
    if not locator.ok:
        return None
    pkh = locator.one()
    if not any(pkh):                      # zero hash locates nothing
        return None
    owner = rpc.read([Call(entry["registry_address"], "walletOwner()", ("address",))])[0]
    if not owner.ok or owner.one().lower() != entry["bridge_address"]:
        return None                       # closure broken -> do not trust the branch
    return "terminal_other_layer", _cr(entry["bridge_address"],
                                       "activeWalletPubKeyHash()", rb)


def assemble(cfg: Config, rpc: RpcClient, repo: pathlib.Path) -> tuple[Bundle, dict]:
    rb = rpc.run_block
    cf = cfg.root("controller_factory").address
    reg = cfg.root("pegkeeper_regulator").address

    # ---- markets + positions -----------------------------------------------
    n = int(rpc.read([Call(cf, "n_collaterals()", ("uint256",))])[0].one())
    markets, raw_rows, node_values = [], [], {}
    for i in range(n):
        ctrl, amm, col = (r.one().lower() for r in rpc.read([
            Call(cf, "controllers(uint256)", ("address",), (i,)),
            Call(cf, "amms(uint256)", ("address",), (i,)),
            Call(cf, "collaterals(uint256)", ("address",), (i,))]))
        td, nl, mp = (r.one() for r in rpc.read([
            Call(ctrl, "total_debt()", ("uint256",)),
            Call(ctrl, "n_loans()", ("uint256",)),
            Call(ctrl, "monetary_policy()", ("address",))]))
        a_coef = int(rpc.read([Call(amm, "A()", ("uint256",))])[0].one())
        px = int(rpc.read([Call(amm, "price_oracle()", ("uint256",))])[0].one())
        dec = int(rpc.read([Call(col, "decimals()", ("uint8",))])[0].one())
        sym_r = rpc.read([Call(col, "symbol()", ("string",))])[0]
        sym = sym_r.one() if sym_r.ok else "?"

        users = [r.one().lower() for r in rpc.read(
            [Call(ctrl, "loans(uint256)", ("address",), (k,)) for k in range(int(nl))])]
        states = rpc.read([Call(ctrl, "user_state(address)", ("uint256[4]",), (u,))
                           for u in users])
        debts = {u: int(r.one()) for u, r in zip(users, rpc.read(
            [Call(ctrl, "debt(address)", ("uint256",), (u,)) for u in users]), strict=True)}

        def storage(contract, slot):
            return int.from_bytes(rpc._w3.eth.get_storage_at(
                rpc._w3.to_checksum_address(contract), slot, block_identifier=rb), "big")

        ver = verify_slot_layout(storage, ctrl, users, debts)
        rows = []
        for u, s in zip(users, states, strict=True):
            c, stbl, gross, _N = s.one()
            rows.append({"user": u, "collateral": int(c), "stablecoin_in_position": int(stbl),
                         "gross_debt": int(gross),
                         "principal": storage(ctrl, loan_slot(ver.base_slot, u))})
        agg = aggregate_positions(ctrl, rows, int(td), ver, {})
        raw_rows.extend({"controller": ctrl, **r} for r in rows)

        value = int(Decimal(agg.external_collateral_sum) / Decimal(10 ** dec)
                    * Decimal(px) / Decimal(10 ** 18))
        node_values[col] = node_values.get(col, 0) + value
        markets.append(Market(
            address=ctrl, amm_address=amm, collateral_address=col,
            monetary_policy_address=mp.lower(), symbol=sym, origination_class="mint",
            decimals=dec, a_coefficient=a_coef, n_positions=agg.n_positions,
            principal_sum=agg.principal_sum, accrued_interest_sum=agg.accrued_interest_sum,
            gross_debt_sum=agg.gross_debt_sum, net_debt_sum=agg.net_debt_sum,
            surplus_sum=agg.surplus_sum,
            stablecoin_in_position_sum=agg.stablecoin_in_position_sum,
            external_collateral_sum=agg.external_collateral_sum,
            external_collateral_value=value,
            position_completeness=PositionCompleteness(
                sum_position_gross_debt=agg.gross_debt_sum, controller_total_debt=int(td),
                relative_diff=agg.det82_relative_diff),
            slot_base_verified=ver.base_slot,
            reads={"gross_debt": _cr(ctrl, "debt(address)", rb),
                   "principal": AbsenceRead(contract=ctrl, method="storage_slot_read",
                                            evidence=f"slot base {ver.base_slot}", block=rb),
                   "total_debt": _cr(ctrl, "total_debt()", rb),
                   "decimals": _cr(col, "decimals()", rb),
                   "collateral_price": _cr(amm, "price_oracle()", rb)},
            lineage=["debt_read", "position_netting", "collateral_read", "price_read"]))

    # ---- stabilizer ---------------------------------------------------------
    ops = []
    for i in range(64):
        r = rpc.read([Call(reg, "peg_keepers(uint256)",
                           ("address", "address", "bool", "bool"), (i,))])[0]
        if not r.ok:
            break
        pk, pool, _iv, _ii = r.require()
        pk, pool = pk.lower(), pool.lower()
        debt, bal, ceil_ = (int(x.one()) for x in rpc.read([
            Call(pk, "debt()", ("uint256",)),
            Call(CRVUSD, "balanceOf(address)", ("uint256",), (pk,)),
            Call(cf, "debt_ceiling(address)", ("uint256",), (pk,))]))
        ops.append(StabilizerOperation(
            operation_address=pk, paired_pool_address=pool, debt_ceiling=ceil_,
            current_debt=debt, balance=bal,
            utilization=None if ceil_ == 0 else Decimal(debt) / Decimal(ceil_),
            utilization_na_reason="ceiling_zero" if ceil_ == 0 else None,
            is_killed_provide=False, is_killed_withdraw=False,
            reads={"current_debt": _cr(pk, "debt()", rb),
                   "balance": _cr(CRVUSD, "balanceOf(address)", rb, (pk,)),
                   "debt_ceiling": _cr(cf, "debt_ceiling(address)", rb, (pk,))},
            lineage=["stabilizer_debt"]))
    alpha, beta = (int(x.one()) for x in rpc.read([
        Call(reg, "alpha()", ("uint256",)), Call(reg, "beta()", ("uint256",))]))
    stab = StabilizerBlock(
        operations=ops, ceiling_aggregate=sum(o.debt_ceiling for o in ops),
        ceiling_aggregate_lineage=["stabilizer_debt"],
        alpha=Decimal(alpha) / Decimal(10**18), beta=Decimal(beta) / Decimal(10**18),
        reads={"alpha": _cr(reg, "alpha()", rb), "beta": _cr(reg, "beta()", rb)})

    # ---- supply + bridges (three-state) -------------------------------------
    ts = int(rpc.read([Call(CRVUSD, "totalSupply()", ("uint256",))])[0].one())
    raw_cfg = cfg.sheet  # bridges live in discovery_roots; read via config loader below
    bridge_rows = []
    for b in getattr(cfg, "bridges", []):
        amt = int(rpc.read([Call(CRVUSD, "balanceOf(address)", ("uint256",),
                                 (b["address"],))])[0].one())
        bridge_rows.append(Bridge(
            bridge_address=b["address"], amount=amt, bridge_type=b["bridge_type"],
            reads={"amount": _cr(CRVUSD, "balanceOf(address)", rb, (b["address"],)),
                   "bridge_type": AnalystSupplied(source=b["source"], date=b["date"])}))
    state = "populated" if bridge_rows else "not_configured"
    disclosure = ("bridged component assessed: %d lock_and_mint escrow(s); "
                  "burn_and_mint component zero" % len(bridge_rows)) if bridge_rows else \
                 "no bridge classification data configured - bridged component unassessed"
    burn = sum(b.amount for b in bridge_rows if b.bridge_type == "burn_and_mint")
    supply = Supply(total_supply=ts, supply_ruled=ts + burn, bridge_state=state,
                    bridge_disclosure=disclosure, bridges=bridge_rows,
                    origination_sum=sum(m.principal_sum for m in markets)
                    + sum(o.current_debt for o in ops),
                    residual=0, stabilizer_over_supply=Decimal(
                        sum(o.current_debt for o in ops)) / Decimal(ts),
                    reads={"total_supply": _cr(CRVUSD, "totalSupply()", rb)})
    supply.residual = supply.supply_ruled - supply.origination_sum

    # ---- nodes --------------------------------------------------------------
    total_value = sum(node_values.values()) or 1
    wr_by_node = {w["node_address"]: w for w in cfg.wallet_registries}
    nodes = []
    for addr, val in node_values.items():
        row = cfg.labels.get(addr)
        resolved, resolved_prov = None, None
        if row is not None and row.label is None and addr in wr_by_node:
            got = resolve_wallet_registry_label(rpc, wr_by_node[addr])
            if got:
                resolved, resolved_prov = got
        nodes.append(CollateralNode(
            address=addr, symbol=row.symbol if row else "?",
            label=(row.label if row and row.label else (resolved or "unlisted")),
            label_source_address=addr,
            node_class=row.node_class if row else "volatile",
            lst_discount_applies=bool(row.lst_discount_applies) if row else False,
            value=val, share_of_backing=Decimal(val) / Decimal(total_value),
            reads=({"collateral": _cr(addr, "balanceOf(address)", rb)}
                   | ({"label": resolved_prov} if resolved_prov else {})),
            lineage=["collateral_read", "price_read"]))

    # ---- oracle rows --------------------------------------------------------
    oracle_rows = []
    for m in markets:
        oc = rpc.read([Call(m.amm_address, "price_oracle_contract()", ("address",))])[0]
        if not oc.ok:
            raise AssemblyStop(f"{m.symbol}: price_oracle_contract() reverted")
        ocl = oc.one().lower()
        win, hops = resolve_ema_window(rpc, ocl, None, cfg.oracle_constituents)
        uc = rpc.read([Call(ocl, "use_chainlink()", ("bool",))])[0]
        ref = next((f for f in cfg.reference_feeds
                    if f["node_address"] == m.collateral_address), None)
        oracle_rows.append(OracleRow(
            node_address=m.collateral_address, market_or_reserve_address=m.address,
            feed_or_source=ocl,
            update_condition=EmaWindow(ema_window_s=win, constituents=hops,
                                       provenance=[_cr(ocl, "ma_exp_time()", rb)]),
            assumption_applied="instant_optimistic_counterfactual",
            counterfactual_ref="EMA_lag",
            reference_feed=(AnalystSupplied(source=ref["source"], date=ref["date"])
                            if ref and ref["kind"] == "chainlink" else "no_reference_feed"),
            market_vs_protocol_oracle_gap=("no_reference_feed"
                                           if not ref or ref["kind"] != "chainlink"
                                           else Decimal(0)),
            staleness_check="not_applicable_ema_oracle",
            use_chainlink=bool(uc.one()) if uc.ok else None))

    # ---- admin surface ------------------------------------------------------
    cf_admin = rpc.read([Call(cf, "admin()", ("address",))])[0].one().lower()
    e_admin = rpc.read([Call(reg, "emergency_admin()", ("address",))])[0].one().lower()
    immutable = all(int.from_bytes(rpc._w3.eth.get_storage_at(
        rpc._w3.to_checksum_address(m.address), EIP1967_IMPL_SLOT,
        block_identifier=rb), "big") == 0 for m in markets)
    admin = []
    for p in A1_POWERS:
        if p in ("mint", "set_ceiling", "set_oracle", "set_parameters"):
            # FR-31 (P-3.38): the A5 veto is READ, not left empty. The rows that
            # carry it are exactly those whose stamped section-13 veto column
            # names the Emergency DAO. The read fetches the address; it does NOT
            # settle the sheet's question-mark hedges - whether that address
            # holds actual veto power over each function is a permission-level
            # question, queued for a future intake edit.
            veto = e_admin if p in VETO_ROWS else None
            admin.append(AdminRow(power=p, holder_address=cf_admin,
                                  holder_type="dao_governance", scope=[cf, reg],
                                  veto_address=veto,
                                  provenance=_cr(cf, "admin()", rb)))
        elif p == "pause":
            admin.append(AdminRow(power=p, holder_address=e_admin,
                                  holder_type="dao_governance", scope=[reg],
                                  provenance=_cr(reg, "emergency_admin()", rb),
                                  live_model_input=True,
                                  consumed_by=["DET-45 is_killed"]))
        else:
            admin.append(AdminRow(
                power=p, holder_address=None, holder_type="none",
                upgradeability="immutable" if (p == "upgrade" and immutable) else None,
                provenance=AbsenceRead(contract=cf, method="selector_absence_scan",
                                       evidence="no matching selector", block=rb)))

    # ---- raw dump + header --------------------------------------------------
    raw = json.dumps(raw_rows, sort_keys=True, separators=(",", ":"))
    raw_hash = hashlib.sha256(raw.encode()).hexdigest()
    fs = json.loads((repo / "config/frozen_set_crvusd.json").read_text(encoding="utf-8"))
    fs_hash = hashlib.sha256(
        (repo / "config/frozen_set_crvusd.json").read_bytes()).hexdigest()[:8]
    first = is_first_run(repo / "out/bundles", "crvUSD")

    bundle = Bundle(
        header=Header(token="crvUSD", run_block=rb, block_timestamp=rpc.block_timestamp,
                      run_start_time=rpc.run_start_time, first_run=first,
                      pipeline_version=PIPELINE_VERSION,
                      sheet_hash=cfg.sheet["sheet_hash"], frozen_set_hash=fs_hash,
                      freeze_date=fs["freeze_date"], raw_positions_hash=raw_hash),
        markets=markets, stabilizer=stab, supply=supply, nodes=nodes,
        oracle_rows=oracle_rows,
        redemption_paths=[RedemptionPath(
            r1_path="none", r2_who="no_one", r3_received="n/a", r4_rate="n/a",
            r5_minimum="n/a", r6_gates=[{"kind": "none", "param": None}],
            r7_capacity="n/a", r8="n/a", r9_legal_claim="no_pure_protocol",
            r10_provenance=AbsenceRead(contract=CRVUSD, method="selector_absence_scan",
                                       evidence="no holder redemption function", block=rb))],
        admin_surface=admin,
        static_metadata=StaticMetadata(
            audits="none", bug_bounty="none", last_material_change_audited="no",
            staleness_date="2026-09-01",
            counterparties=cfg.sheet["counterparties"]),
        counts=Counts(mint_market_count=len(markets),
                      lend_market_count=cfg.lend.market_count_field),
        attribution_method="direct",
        first_run_literals=FirstRunLiterals() if first else None)
    return bundle, {"raw": raw, "raw_hash": raw_hash, "rows": raw_rows}


def execute(repo: pathlib.Path, rpc_url: str) -> dict:
    """Assemble, gate, promote. Promotion is unreachable on a Level 3."""
    cfg = load(repo / "config")
    rpc = RpcClient(rpc_url)
    t0 = time.time()
    bundle, extra = assemble(cfg, rpc, repo)

    ctx = {"labels": cfg.labels, "printed_trigger_table": dict(TRIGGER_TABLE),
           "sheet": cfg.sheet, "roots": cfg.roots,
           "today": __import__("datetime").date.today(),
           "is_first_run": bundle.header.first_run,
           # the delta checks (DET-62/63/65) need the last successful run; it is
           # None exactly when first_run is true, which DET-86 cross-checks.
           "prior_bundle": load_prior(repo / "out/bundles", "crvUSD",
                                      bundle.header.run_block)}
    outcome = run_harness(bundle, ctx)            # raises => nothing below runs

    stamped, h = finalise(bundle)
    stamped.gate_results = [GateResult(entry_id=r.entry_id, result=r.result)
                            for r in outcome.results]
    out = repo / "out/bundles/crvUSD"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{stamped.header.run_block}.json").write_text(
        serialise_for_disk(stamped), encoding="utf-8", newline="")
    (repo / "out/raw").mkdir(parents=True, exist_ok=True)
    (repo / f"out/raw/{stamped.header.run_block}.json").write_text(
        extra["raw"], encoding="utf-8", newline="")
    # spot-check sheet (P-3.13, Method A). Gitignored; key is a placeholder.
    biggest = None
    if extra.get("rows"):
        biggest = max(extra["rows"], key=lambda r: r["gross_debt"])
    sheet_path = write_spotcheck(
        stamped, repo / "out/spotcheck", crvusd=CRVUSD,
        controller_factory=cfg.root("controller_factory").address,
        biggest_position=biggest)
    return {"bundle": stamped, "hash": h, "outcome": outcome, "spotcheck": sheet_path,
            "seconds": round(time.time() - t0, 1)}


# --------------------------------------------------------------- entry ------
# 0.5(c), P-3.42: the run entry point. Ruled in because the record could not
# otherwise state how a run is invoked, and the Step-8 cron needs the same
# entry point. Minimal by ruling: no argparse, no options.
#
# RPC URL source, named implementer default: `ETH_RPC_URL` from the process
# environment, falling back to the `ETH_RPC_URL=` line of `.env` at the repo
# root. The fallback exists because NOTHING in the tracked tree has ever read
# an environment variable (runs 1 and 2 passed the URL into `execute()` from
# an uncommitted one-liner), while `.env` is the ruled home for the key
# (P-3.05; `.env.example`). Without it the documented invocation would not
# run on this repo as configured.


def _rpc_url(repo: pathlib.Path) -> str:
    url = os.environ.get("ETH_RPC_URL", "").strip()
    if url:
        return url
    env = repo / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("ETH_RPC_URL="):
                return line.split("=", 1)[1].strip()
    raise AssemblyStop("ETH_RPC_URL not set in the environment or .env")


if __name__ == "__main__":
    _repo = pathlib.Path(__file__).resolve().parents[2]
    try:
        _r = execute(_repo, _rpc_url(_repo))
    except Exception as exc:                                  # a raised stop
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    _o = _r["outcome"]
    print(f"run_block {_r['bundle'].header.run_block} | bundle {_r['hash'][:8]} | "
          f"gates {sum(1 for g in _o.results if g.result == 'pass')}/{len(_o.results)} pass"
          f" | worst_level {_o.worst_level} | {_r['seconds']}s | spotcheck {_r['spotcheck']}")
