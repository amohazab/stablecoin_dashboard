"""GHO adapter, build slice 1: facilitators, GSMs, the inventory reads.

WHAT THIS SLICE IS. P-4.04 R1 ruled GHO's origination surface: circulating GHO
appears when a borrower draws against pledged collateral, the pre-minted
undrawn balance is protocol-held inventory, and the three `*GhoDirectMinter`
contracts are `facilitators[]` rows rather than `markets[]` rows. This module
reads that surface. Positions, nodes, the admin surface, oracle rows and the
pool pass are sessions 2 and 3, so `assemble` **stops** rather than returning a
half-built bundle — see `GhoAdapterIncomplete`.

DISCOVERY. Two declared roots (`gho_roots.toml`) and nothing else: the
facilitator set comes from `GhoToken.getFacilitatorsList()`, the live GSMs from
`GsmRegistry.getGsmList()`, and each Aave instance from its own minter's
`POOL()`. No market, pool or facilitator list is written down anywhere.
"""

from __future__ import annotations

from decimal import Decimal

from eth_utils import keccak

from factory.logs_pointer import get_logs
from factory.rpc import Call
from factory.schema import Facilitator, GhoPosition, Gsm, PositionCompleteness

# DET-28's discriminators, read from the chain at block 25930871 rather than
# recalled: each class answers a selector no other class answers.
PROBE: tuple[tuple[str, str, tuple], ...] = (
    ("POOL()", "address", ()),                    # direct minter -> its Aave instance
    ("maxFlashLoan(address)", "uint256", ("token",)),   # flash minter
    ("getToken()", "address", ()),                # CCIP-class token pool
    ("GHO_TOKEN()", "address", ()),               # every GHO-aware facilitator
)
def _sig(text: str) -> str:
    h = keccak(text=text).hex()
    return h if h.startswith("0x") else "0x" + h


BORROW = _sig("Borrow(address,address,address,uint256,uint8,uint256,uint16)")
REPAY = _sig("Repay(address,address,address,uint256,bool)")
LIQUIDATION = _sig("LiquidationCall(address,address,address,uint256,uint256,address,bool)")
TRANSFER = _sig("Transfer(address,address,uint256)")
SWAP_FREEZER_ROLE = keccak(text="SWAP_FREEZER_ROLE")
ROLE_GRANTED = _sig("RoleGranted(bytes32,address,address)")

# R7 as corrected at P-4.04-A1. Aave burns liquidated debt through
# `LiquidationCall`, which emits NO `Repay`: leaving it out puts principal above
# gross on 128 of 2,142 live positions. All three index `reserve`/`debtAsset`,
# but LiquidationCall indexes it at topic2, so its GHO filter is applied
# locally. Every run re-walks the full range — no cursor, no ledger.
ZERO_TOPIC = "0x" + "00" * 32

GSM_READS: tuple[tuple[str, str], ...] = (
    ("UNDERLYING_ASSET()", "address"),
    ("getExposureCap()", "uint128"),
    ("getAvailableLiquidity()", "uint256"),
    ("getAvailableUnderlyingExposure()", "uint256"),
    ("getIsFrozen()", "bool"),
    ("getIsSeized()", "bool"),
    ("PRICE_STRATEGY()", "address"),
    ("getFeeStrategy()", "address"),
    ("getGhoTreasury()", "address"),
)
FREEZER_READS: tuple[tuple[str, str], ...] = (
    ("getFreezeBound()", "(uint128,uint128)"),
    ("getUnfreezeBound()", "(uint128,uint128)"),
    ("getCanUnfreeze()", "bool"),
    ("GSM()", "address"),
)


class GhoAdapterIncomplete(Exception):
    """Build slice 1 stops here BY CONSTRUCTION, not by failure.

    `Bundle` requires `nodes`, `oracle_rows`, `redemption_paths`, nine
    `admin_surface` rows (DET-68) and `pool_detectors`; none of them exists
    yet. Emitting placeholders to get a bundle past validation would be
    fabricating the fields the gates check, so the adapter names what it built
    and what it owes and stops. Sessions 2 and 3 delete this.
    """


def _class_of(evidence: list[str]) -> str:
    """DET-28 classification from what ANSWERED, never from the label string.

    FINDING, carried in code because it changes what this function can return:
    `gsm_funder` and `off_mainnet` are NOT separable by selector. The four
    `GhoDirectFacilitator *` rows answer exactly `GHO_TOKEN()` and nothing
    else, whether they fund the mainnet GSMs or bridge to Plasma / Arbitrum /
    Monad. Splitting them would mean reading the label string, which the
    no-symbol gate forbids, so they come back `unresolved` WITH their evidence
    — the C-1 shape (P-3.06): a class comes from a menu or a dated analyst
    row, never from an inference.
    """
    if "POOL()" in evidence:
        return "direct_minter"
    if "maxFlashLoan(address)" in evidence:
        return "flash_minter"
    if "getToken()" in evidence:
        return "off_mainnet"
    return "unresolved"


def read_facilitators(rpc, gho: str) -> tuple[list[Facilitator], int]:
    """`getFacilitatorsList()` -> one row per facilitator. Returns the rows and
    the read count, so the caller can report reads without recounting."""
    listed = rpc.read([Call(gho, "getFacilitatorsList()", ("address[]",))])[0]
    addrs = [a.lower() for a in listed.require()[0]]
    n = 1

    calls, meta = [], []
    for a in addrs:
        calls.append(Call(gho, "getFacilitator(address)", ("(uint128,uint128,string)",), (a,)))
        meta.append((a, "facilitator"))
        calls.append(Call(gho, "getFacilitatorBucket(address)", ("uint256", "uint256"), (a,)))
        meta.append((a, "bucket"))
        for sig, out, args in PROBE:
            calls.append(Call(a, sig, (out,), (gho,) if args else ()))
            meta.append((a, sig))
    res = rpc.read(calls)
    n += len(calls)

    by: dict[str, dict] = {a: {} for a in addrs}
    for (a, what), r in zip(meta, res, strict=True):
        by[a][what] = r

    rows: list[Facilitator] = []
    for a in addrs:
        cap, lvl = by[a]["bucket"].require()
        label = by[a]["facilitator"].require()[0][2]
        evidence = [sig for sig, _, _ in PROBE if by[a][sig].ok]
        cls = _class_of(evidence)
        pool = by[a]["POOL()"].one().lower() if cls == "direct_minter" else None
        rows.append(Facilitator(
            address=a, label=label, bucket_capacity=int(cap), bucket_level=int(lvl),
            utilization=(Decimal(int(lvl)) / Decimal(int(cap))) if cap else None,
            utilization_na_reason=None if cap else "ceiling_zero",
            facilitator_class=cls, class_evidence=evidence, pool_address=pool,
            reads={"bucket": by[a]["bucket"].provenance,
                   "label": by[a]["facilitator"].provenance},
        ))
    return sorted(rows, key=lambda f: f.address), n


def check_supply_identity(rows: list[Facilitator], total_supply: int) -> None:
    """Sigma bucket levels == `totalSupply()`, exact.

    Observed exact at block 25930871 (699,000,000.00 both sides). Enforced here
    rather than as a Pydantic validator because no GHO `Bundle` exists to hang
    one on yet; it MOVES onto `Bundle` in session 2, when the first GHO bundle
    is constructed — named so the move is a step, not a rediscovery.
    """
    total = sum(f.bucket_level for f in rows)
    if total != total_supply:
        raise GhoAdapterIncomplete(
            f"supply identity broken: sum of bucket levels {total} != "
            f"totalSupply {total_supply}. A facilitator is missing from the "
            "registry or a level was read wrong; never reconciled away."
        )


def read_gsms(rpc, registry: str, http_get=None, key: str = "",
              from_block: int = 0) -> tuple[list[Gsm], int]:
    """`getGsmList()` -> per-GSM state plus the memo §6.3 H2 freezer block.

    The freezer HOLDER is discovered, not configured: `RoleGranted` logs on the
    GSM filtered to `SWAP_FREEZER_ROLE` are the POINTER, and `hasRole` at
    `run_block` is the VERDICT (P-4.04 R5). With no pointer injected the H2
    fields stay None — present-and-empty, never guessed.
    """
    listed = rpc.read([Call(registry, "getGsmList()", ("address[]",))])[0]
    addrs = [a.lower() for a in listed.require()[0]]
    n = 1

    calls, meta = [], []
    for a in addrs:
        for sig, out in GSM_READS:
            calls.append(Call(a, sig, (out,)))
            meta.append((a, sig))
    res = rpc.read(calls)
    n += len(calls)
    by: dict[str, dict] = {a: {} for a in addrs}
    for (a, sig), r in zip(meta, res, strict=True):
        by[a][sig] = r

    rows: list[Gsm] = []
    for a in addrs:
        g = by[a]
        freezer = None
        if http_get is not None:
            from factory.logs_pointer import get_logs
            ptr = get_logs(a, [ROLE_GRANTED, "0x" + SWAP_FREEZER_ROLE.hex(), None],
                           from_block, rpc.run_block, http_get, key)
            holders = ["0x" + r.topics[2][-40:] for r in ptr.rows if len(r.topics) > 2]
            uniq = list(dict.fromkeys(holders))
            conf = rpc.read([Call(a, "hasRole(bytes32,address)", ("bool",),
                                  (SWAP_FREEZER_ROLE, h)) for h in uniq]) if uniq else []
            n += len(conf)
            current = [h for h, v in zip(uniq, conf, strict=True) if v.ok and v.one()]
            # SWAP_FREEZER_ROLE is held by BOTH the automation contract and the
            # Aave DAO executor (AIP-8). Only one of them is the freezer the
            # memo §6.3 H2 check is about, and the discriminator is CLOSURE:
            # its `GSM()` must point back at this GSM. Taking the last holder
            # returned EXECUTOR_LVL_1 and left the bands unreadable.
            back = rpc.read([Call(h, "GSM()", ("address",)) for h in current]) if current else []
            n += len(back)
            for h, r in zip(current, back, strict=True):
                if r.ok and r.one().lower() == a:
                    freezer = h
                    break
        fz: dict[str, object] = {}
        if freezer is not None:
            fr = rpc.read([Call(freezer, sig, (out,)) for sig, out in FREEZER_READS])
            n += len(fr)
            lo_hi = fr[0].require()[0] if fr[0].ok else (None, None)
            u_lo_hi = fr[1].require()[0] if fr[1].ok else (None, None)
            fz = {"freezer_address": freezer,
                  "freeze_bound_lo": lo_hi[0], "freeze_bound_hi": lo_hi[1],
                  "unfreeze_bound_lo": u_lo_hi[0], "unfreeze_bound_hi": u_lo_hi[1],
                  "can_unfreeze": fr[2].one() if fr[2].ok else None,
                  "freezer_role_confirmed": bool(fr[3].ok and fr[3].one().lower() == a)}
        rows.append(Gsm(
            address=a,
            underlying_asset=g["UNDERLYING_ASSET()"].one().lower(),
            exposure_cap=int(g["getExposureCap()"].one()),
            available_liquidity=int(g["getAvailableLiquidity()"].one()),
            available_underlying_exposure=int(g["getAvailableUnderlyingExposure()"].one()),
            is_frozen=bool(g["getIsFrozen()"].one()),
            is_seized=bool(g["getIsSeized()"].one()),
            price_strategy=g["PRICE_STRATEGY()"].one().lower(),
            fee_strategy=g["getFeeStrategy()"].one().lower(),
            gho_treasury=g["getGhoTreasury()"].one().lower(),
            reads={sig: g[sig].provenance for sig, _ in GSM_READS},
            **fz,
        ))
    return sorted(rows, key=lambda x: x.address), n


def read_inventory(rpc, gho: str, atoken: str) -> tuple[int, object, int]:
    """Undrawn protocol-held inventory for one instance: the GHO SITTING IN the
    aToken contract, `GHO.balanceOf(aGHO)`. Reading `aGHO.balanceOf(aGHO)`
    instead returns zero — the aToken does not hold itself. Amounts only; the
    `supply_ruled` denominator is P-4.01 #3 and is not answered here (F4).
    """
    r = rpc.read([Call(gho, "balanceOf(address)", ("uint256",), (atoken,))])[0]
    return int(r.one()), r.provenance, 1


def assemble(cfg, rpc, repo, token: str, http_get=None, key: str = "",
             from_block: int = 0):
    """P-4.02's adapter signature. Builds slice 2a and STOPS — see
    `GhoAdapterIncomplete`. Returns nothing; the numbers ride the stop."""
    return build(cfg, rpc, http_get=http_get, key=key, from_block=from_block, stop=True)


def build(cfg, rpc, http_get=None, key: str = "", from_block: int = 0, stop: bool = False):
    """Slice 2a end to end: facilitators, GSMs, supply inventory, positions,
    principal, node weights. Returns a dict; `assemble` raises on it."""
    gho = cfg.root("gho_token").address
    registry = cfg.root("gsm_registry").address
    reads = 0

    facilitators, n = read_facilitators(rpc, gho)
    reads += n
    supply = int(rpc.read([Call(gho, "totalSupply()", ("uint256",))])[0].one())
    reads += 1
    check_supply_identity(facilitators, supply)

    gsms, n = read_gsms(rpc, registry, http_get=http_get, key=key, from_block=from_block)
    reads += n
    bridge_rows = []
    for b in cfg.bridges:
        r = rpc.read([Call(gho, "balanceOf(address)", ("uint256",), (b["address"],))])[0]
        reads += 1
        bridge_rows.append({"bridge_address": b["address"], "amount": int(r.one()),
                            "bridge_type": b["bridge_type"], "reads": {"amount": r.provenance}})

    # ---- positions, per instance -------------------------------------------
    positions: list[GhoPosition] = []
    node_reserves: dict[str, set[str]] = {}
    pointers = []
    out_f = []
    for f in facilitators:
        if f.facilitator_class != "direct_minter":
            out_f.append(f)
            continue
        debt_token, atoken, reserves, atokens, oracle, n = read_instance(rpc, gho, f.pool_address)
        reads += n
        inv, inv_prov, n = read_inventory(rpc, gho, atoken)
        reads += n
        ledger, ptrs = ({}, [])
        if http_get is not None:
            ledger, ptrs = borrower_ledger(f.pool_address, debt_token, gho,
                                           rpc.run_block, from_block, http_get, key)
            pointers.extend(ptrs)
        rows, completeness, n = read_positions(rpc, f.pool_address, oracle, gho,
                                               debt_token, reserves, atokens, ledger)
        reads += n
        positions.extend(rows)
        for r in rows:
            for res in r.collateral:
                node_reserves.setdefault(res, set()).add(f.pool_address)
        out_f.append(f.model_copy(update={
            "debt_token_address": debt_token, "atoken_address": atoken, "inventory": inv,
            "reads": {**f.reads, "inventory": inv_prov},
            "n_positions": len(rows),
            "principal_sum": sum(x.principal for x in rows),
            "accrued_interest_sum": sum(x.accrued_interest for x in rows),
            "gross_debt_sum": sum(x.gross_debt for x in rows),
            "position_completeness": completeness}))
    facilitators = out_f

    result = {"facilitators": facilitators, "gsms": gsms, "total_supply": supply,
              "oracles": {f.pool_address: f.atoken_address for f in facilitators
                          if f.facilitator_class == "direct_minter"},
              "bridges": bridge_rows, "positions": positions,
              "node_weights": attribute_nodes(positions),
              "node_instances": {k: sorted(v) for k, v in node_reserves.items()},
              "pointers": [p.record() for p in pointers], "reads": reads}
    if stop:
        raise GhoAdapterIncomplete(
            f"GHO slice 2a built: {len(facilitators)} facilitators, {len(gsms)} GSMs, "
            f"{len(positions)} positions, {len(result['node_weights'])} nodes, "
            f"totalSupply {supply}, {reads} pinned reads. "
            "OWED before a bundle can be constructed: node LABELS (analyst, 2b), the "
            "nine admin_surface rows (DET-68), oracle_rows, redemption_paths (DET-66's "
            "GHO clause), the lend disclosure, and the freeze with pools and "
            "pool_detectors. Sessions 2b and 3."
        )
    return result


__all__ = ["GhoAdapterIncomplete", "PROBE", "assemble", "attribute_nodes", "build",
           "borrower_ledger", "check_supply_identity", "read_facilitators",
           "read_gsms", "read_instance", "read_inventory", "read_positions"]


# --------------------------------------------------------------- positions ---


def _topic_addr(t: str) -> str:
    return "0x" + t[-40:]


def _word(data: str, i: int) -> int:
    d = data[2:] if data.startswith("0x") else data
    return int(d[i * 64:(i + 1) * 64], 16)


def borrower_ledger(pool: str, debt_token: str, gho: str, run_block: int,
                    from_block: int, http_get, key: str) -> tuple[dict[str, int], list]:
    """R7 as corrected (P-4.04-A1): per borrower,
    `sum Borrow - sum Repay - sum LiquidationCall.debtToCover`, floored at zero,
    plus the mint-side `Transfer` set that bounds who to read on-chain.

    POINTER ONLY. Nothing here is a bundle number: the ledger says who to ask
    and what their borrowed-minus-repaid total is, and every gross figure comes
    from a pinned `balanceOf` (P-4.04 R3).
    """
    gho_topic = "0x" + "0" * 24 + gho[2:]
    ptrs, ledger = [], {}
    mint = get_logs(debt_token, [TRANSFER, ZERO_TOPIC], from_block, run_block, http_get, key)
    ptrs.append(mint)
    candidates = {_topic_addr(r.topics[2]) for r in mint.rows if len(r.topics) > 2}
    for topic0, sign, word, who in ((BORROW, 1, 1, 2), (REPAY, -1, 0, 2)):
        p = get_logs(pool, [topic0, gho_topic], from_block, run_block, http_get, key)
        ptrs.append(p)
        for r in p.rows:
            a = _topic_addr(r.topics[who])
            ledger[a] = ledger.get(a, 0) + sign * _word(r.data, word)
    liq = get_logs(pool, [LIQUIDATION], from_block, run_block, http_get, key)
    ptrs.append(liq)
    for r in liq.rows:
        if len(r.topics) < 4 or r.topics[2].lower() != gho_topic:
            continue                                    # debtAsset is topic2, filtered here
        a = _topic_addr(r.topics[3])
        ledger[a] = ledger.get(a, 0) - _word(r.data, 0)
    for a in candidates:
        ledger.setdefault(a, 0)
    return {a: max(v, 0) for a, v in ledger.items()}, ptrs


def read_positions(rpc, pool: str, oracle: str, gho: str, debt_token: str,
                   reserves: list[str], atokens: dict[str, str],
                   ledger: dict[str, int]) -> tuple[
                       list[GhoPosition], PositionCompleteness, int]:
    """Route A (P-4.04 R2), bitmap-filtered. The chain is the verdict: the
    ledger's candidate set is filtered to live debt by a pinned `balanceOf`,
    then each live borrower's OWN reserves come from `getUserConfiguration`,
    so the read grid is the 3,786 slots borrowers actually occupy rather than
    borrowers x reserves.
    """
    cands = sorted(ledger)
    n = 0
    bal = rpc.read([Call(debt_token, "balanceOf(address)", ("uint256",), (u,)) for u in cands])
    n += len(bal)
    live = [(u, int(r.one())) for u, r in zip(cands, bal, strict=True) if r.ok and r.one() > 0]
    if not live:
        return [], PositionCompleteness(sum_position_gross_debt=0,
                                        controller_total_debt=0,
                                        relative_diff=Decimal(0)), n

    cfg = rpc.read([Call(pool, "getUserConfiguration(address)", ("uint256",), (u,))
                    for u, _ in live])
    n += len(cfg)
    # memo §11.1's DENOMINATOR. A borrower's GHO share is GHO debt over TOTAL
    # debt, and totals across reserves are only comparable in the pool's base
    # currency, so `getUserAccountData` supplies `totalDebtBase` — one read per
    # borrower. Without it the ratio is 1 and every borrower's whole collateral
    # is credited to GHO, which is the upper bound, not the attribution.
    acct = rpc.read([Call(pool, "getUserAccountData(address)",
                          ("uint256", "uint256", "uint256", "uint256", "uint256", "uint256"),
                          (u,)) for u, _ in live])
    n += len(acct)
    debt_base = {u: (int(r.value[1]) if r.ok else 0) for (u, _), r in zip(live, acct, strict=True)}
    gho_px = rpc.read([Call(oracle, "getAssetPrice(address)", ("uint256",), (gho,))])[0]
    n += 1
    px = int(gho_px.one()) if gho_px.ok else 0
    calls, meta = [], []
    for (u, _), c in zip(live, cfg, strict=True):
        m = int(c.one()) if c.ok else 0
        for i, res in enumerate(reserves):
            if (m >> (2 * i + 1)) & 1 and res in atokens:
                calls.append(Call(atokens[res], "balanceOf(address)", ("uint256",), (u,)))
                meta.append((u, res))
    got = rpc.read(calls) if calls else []
    n += len(got)
    coll: dict[str, dict[str, int]] = {}
    for (u, res), r in zip(meta, got, strict=True):
        if r.ok and r.one() > 0:
            coll.setdefault(u, {})[res] = int(r.one())

    rows = [GhoPosition(borrower=u, instance=pool, gross_debt=g,
                        principal=min(ledger.get(u, 0), g),
                        accrued_interest=g - min(ledger.get(u, 0), g),
                        gho_debt_base=(g * px) // 10 ** 18,
                        total_debt_base=debt_base.get(u, 0),
                        collateral=coll.get(u, {}))
            for u, g in live]
    total = rpc.read([Call(debt_token, "totalSupply()", ("uint256",))])[0]
    n += 1
    ts = int(total.one())
    s = sum(r.gross_debt for r in rows)
    diff = (Decimal(abs(s - ts)) / Decimal(ts)) if ts else Decimal(0)
    return rows, PositionCompleteness(sum_position_gross_debt=s, controller_total_debt=ts,
                                      relative_diff=diff), n


def read_instance(rpc, gho: str, pool: str) -> tuple[
        str, str, list[str], dict[str, str], str, int]:
    """Everything about one Aave instance that is DISCOVERED, not listed: its
    GHO debt token and aToken, its reserve list, each reserve's aToken, and the
    instance's own price oracle via `ADDRESSES_PROVIDER()` — no address here
    appears in config."""
    head = rpc.read([Call(pool, "getReserveVariableDebtToken(address)", ("address",), (gho,)),
                     Call(pool, "getReserveAToken(address)", ("address",), (gho,)),
                     Call(pool, "getReservesList()", ("address[]",)),
                     Call(pool, "ADDRESSES_PROVIDER()", ("address",))])
    n = 4
    ap = head[3].one()
    oracle = rpc.read([Call(ap, "getPriceOracle()", ("address",))])[0].one().lower()
    n += 1
    debt_token = head[0].one().lower()
    atoken = head[1].one().lower()
    reserves = [a.lower() for a in head[2].one()]
    at = rpc.read([Call(pool, "getReserveAToken(address)", ("address",), (r,)) for r in reserves])
    n += len(at)
    atokens = {r: x.one().lower() for r, x in zip(reserves, at, strict=True) if x.ok}
    return debt_token, atoken, reserves, atokens, oracle, n


# ------------------------------------------------------------------ nodes ---


def attribute_nodes(positions: list[GhoPosition]) -> dict[str, int]:
    """Memo §11.1 pro-rata: each borrower's collateral is credited to GHO in the
    ratio of their GHO debt to their TOTAL debt. Keyed by UNDERLYING ASSET
    ADDRESS across instances (P-4.04 R1) — the same reserve in Core and in Lido
    is one node, and the instance stays on the read that produced it.

    `total_debt_base` is the borrower's whole debt; where it is not yet read the
    ratio is 1 (the borrower's only debt is GHO), which is the CONSERVATIVE
    direction and is disclosed rather than silently assumed.
    """
    out: dict[str, int] = {}
    for p in positions:
        if p.total_debt_base <= 0 or p.gho_debt_base <= 0:
            continue
        num = min(p.gho_debt_base, p.total_debt_base)     # a share, never > 1
        for res, amount in p.collateral.items():
            out[res] = out.get(res, 0) + (amount * num) // p.total_debt_base
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
