"""The GHO adapter: facilitators, GSMs, supply, positions, nodes, surfaces.

P-4.04 R1 ruled GHO's origination surface: circulating GHO appears when a
borrower draws against pledged collateral, the pre-minted undrawn balance is
protocol-held inventory, and the three `*GhoDirectMinter` contracts are
`facilitators[]` rows rather than `markets[]` rows. `assemble` returns a whole
`Bundle` (P-4.11); nothing is owed.

DISCOVERY. Two declared roots (`gho_roots.toml`) and nothing else: the
facilitator set comes from `GhoToken.getFacilitatorsList()`, the live GSMs from
`GsmRegistry.getGsmList()`, and each Aave instance from its own minter's
`POOL()`. No market, pool or facilitator list is written down anywhere.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
from decimal import Decimal

from eth_utils import keccak

from factory.config import sell_side_for
from factory.disclosure import disclosure_fields
from factory.discovery import (
    AssemblyStopFromDiscovery,
    build_pool_rows,
    catalog_get,
    last_run_ratios,
)
from factory.feeds import condition_from_row, nav_observed_max
from factory.labels_runtime import resolve_wallet_registry_label
from factory.logbook import is_first_run, load_prior
from factory.logs_pointer import default_transport, get_logs
from factory.logs_pointer import env as pointer_env
from factory.offvenue import read_share
from factory.provenance import AbsenceRead, AnalystSupplied, ContractRead
from factory.rpc import Call
from factory.schema import (
    AdminRow,
    Bridge,
    Bundle,
    CollateralNode,
    Counts,
    Facilitator,
    FirstRunLiterals,
    GhoPosition,
    Gsm,
    Header,
    OracleRow,
    PositionCompleteness,
    RedemptionPath,
    StabilizerBlock,
    Supply,
)

# Where promoted bundles live; `is_first_run` is path-scoped (P-3.14).
_BUNDLES = pathlib.Path("out/bundles")

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


class GhoAdapterStop(Exception):
    """A precondition the GHO bundle cannot be assembled without.

    P-4.11 retires `GhoAdapterIncomplete`: nothing is owed any more, so the
    class no longer means "this slice is unfinished". It is now the pre-harness
    stop `run.py` re-raises as `AssemblyStop` - the same shape
    `AssemblyStopFromDiscovery` takes for crvUSD (P-3.46 R1).
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


def read_facilitators(rpc, gho: str, cfg=None) -> tuple[list[Facilitator], int]:
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
        # DET-28's dated fallback (P-4.08 ruling 1): consulted ONLY where the
        # probe could not resolve; a row's absence keeps `unresolved`.
        if cls == "unresolved" and cfg is not None:
            fb = getattr(cfg, "facilitator_classes", {}).get(a)
            if fb:
                cls = fb["facilitator_class"]
                evidence = evidence + [f"analyst row {fb['classified_on']}"]
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
        raise GhoAdapterStop(
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


def boxed_asset_walk(rpc, gsms: list) -> tuple[list[dict], int]:
    """DET-28's boxed asset, identified rather than assumed (C2, R-C2.1).

    Each GSM's `UNDERLYING_ASSET()` is a `StataTokenV2` — an ERC-4626 wrapper,
    NOT the bare stable — so the walk is wrapper -> aToken -> underlying, and it
    is confirmed from BOTH ends: the wrapper's `asset()` must equal the aToken's
    own `UNDERLYING_ASSET_ADDRESS()`. Every accessor here is named from the
    verified implementation's ABI (`0x487c2c53…`, solc 0.8.20); a wrapper whose
    walk does not close stops the run rather than defaulting to the wrapper.
    """
    out, n = [], 0
    for g in gsms:
        w = g.underlying_asset
        r = rpc.read([Call(w, "asset()", ("address",)),
                      Call(w, "aToken()", ("address",)),
                      Call(w, "symbol()", ("string",)),
                      Call(w, "decimals()", ("uint8",)),
                      Call(w, "convertToAssets(uint256)", ("uint256",),
                           (g.available_liquidity,))])
        n += len(r)
        if not all(x.ok for x in r):
            raise GhoAdapterStop(
                f"GSM {g.address}: boxed asset {w} does not answer the ERC-4626 "
                "walk (asset/aToken/convertToAssets); its identity is unresolved "
                "and DET-28's node is never emitted on a guess")
        under, atoken = r[0].one().lower(), r[1].one().lower()
        q = rpc.read([Call(atoken, "UNDERLYING_ASSET_ADDRESS()", ("address",)),
                      Call(atoken, "symbol()", ("string",)),
                      Call(atoken, "decimals()", ("uint8",)),
                      Call(under, "symbol()", ("string",)),
                      Call(under, "decimals()", ("uint8",))])
        n += len(q)
        if not q[0].ok or q[0].one().lower() != under:
            raise GhoAdapterStop(
                f"GSM {g.address}: the walk disagrees at its two ends — wrapper "
                f"{w}.asset() = {under}, aToken {atoken}.UNDERLYING_ASSET_ADDRESS() "
                f"= {q[0].one().lower() if q[0].ok else 'no answer'}")
        out.append({
            "gsm": g.address, "wrapper": w, "atoken": atoken, "underlying": under,
            "shares": g.available_liquidity, "converted": int(r[4].one()),
            "symbol": r[2].one(), "decimals": int(r[3].one()),
            "atoken_symbol": q[1].one(), "atoken_decimals": int(q[2].one()),
            "underlying_symbol": q[3].one(), "underlying_decimals": int(q[4].one()),
            "reads": {"asset": r[0].provenance, "atoken": r[1].provenance,
                      "symbol": r[2].provenance, "decimals": r[3].provenance,
                      "convert": r[4].provenance, "atoken_underlying": q[0].provenance,
                      "underlying_decimals": q[4].provenance},
        })
    return out, n


def read_inventory(rpc, gho: str, atoken: str) -> tuple[int, object, int]:
    """Undrawn protocol-held inventory for one instance: the GHO SITTING IN the
    aToken contract, `GHO.balanceOf(aGHO)`. Reading `aGHO.balanceOf(aGHO)`
    instead returns zero — the aToken does not hold itself. Amounts only: the
    `supply_ruled` denominator was ruled at C0/R1 (P-6.02) and is `totalSupply`
    for every pilot token, so this read feeds a numerator and settles nothing
    about the denominator. The stale P-4.01 #3 pointer is retired here (R18).
    """
    r = rpc.read([Call(gho, "balanceOf(address)", ("uint256",), (atoken,))])[0]
    return int(r.one()), r.provenance, 1


def _boxed(cfg, rpc, walk, pools, oracle_by_pool, priced: dict,
           price_prov: dict | None = None) -> tuple[list[dict], int]:
    """DET-28's boxed-asset nodes, one per GSM, keyed by the WRAPPER (C2).

    They are not merged into the USDC/USDT collateral nodes: different assets on
    different branches. The label comes from the wrapper's OWN dated row —
    DET-02 forbids sourcing a label across an address, so §4.3's look-through is
    resolved at design time in that row's prose (R-C2.6) and the walk that
    justifies it rides in `reads`. The PRICE is the underlying's: the wrapper is
    not a reserve on the GHO instance, so `getAssetPrice(wrapper)` is zero, and
    §4.3 says a pass-through wrapper is worth its underlying (R-C2.3).
    """
    n = 0
    out = []
    price_prov = price_prov if price_prov is not None else {}
    for w in walk:
        if w["wrapper"] not in cfg.labels:
            raise GhoAdapterStop(
                f"boxed asset {w['wrapper']} ({w['symbol']}) has no dated label "
                "row; DET-02 needs one keyed to its own address before it can be "
                "a node (C2, R-C2.6)")
        if w["underlying"] not in cfg.labels:
            raise GhoAdapterStop(
                f"boxed asset {w['wrapper']} passes through to {w['underlying']}, "
                "which carries no label row: the §4.3 walk left the labelled set "
                "and that is a ruling, not a default")
        price = priced.get(w["underlying"])
        if price is None:
            o = oracle_by_pool.get(pools[0]) if pools else None
            r = rpc.read([Call(o, "getAssetPrice(address)", ("uint256",),
                               (w["underlying"],))])[0] if o else None
            n += 1 if o else 0
            price = int(r.one()) if r is not None and r.ok else 0
            if r is not None and r.ok:
                price_prov[w["underlying"]] = r.provenance
        out.append({**w, "value": (w["converted"] * price) // 10 ** w["underlying_decimals"],
                    "price_read": price_prov.get(w["underlying"]),
                    "flags": [
                        f"§4.3 pass-through: {w['symbol']} -> {w['atoken_symbol']} -> "
                        f"{w['underlying_symbol']} ({w['underlying']}); "
                        f"{w['shares']} wrapper units convert to {w['converted']}, "
                        "priced at the underlying's oracle (C2)"]})
    return out, n


def _nodes(cfg, weights, node_instance, rpc, pools, oracle_by_pool,
           resolved: dict | None = None, boxed_walk=(), http_get=None,
           key: str = "") -> tuple[list, int]:
    """`CollateralNode` rows for every node carrying a config row, valued at the
    instance's own Aave oracle (DET-81). A config `unlabeled` row emits
    `unlisted` — the tree's label set is closed and §8.2 is where these belong
    (P-4.08); its `reason` and share ride in `flags` so the disclosure names
    which wedge is unruled rather than hiding it inside a label.
    """
    n = 0
    resolved = resolved or {}
    priced: dict[str, int] = {}
    price_prov: dict = {}
    dec: dict[str, int] = {}
    addrs = [a for a in weights if a in cfg.labels]
    if addrs:
        d = rpc.read([Call(a, "decimals()", ("uint8",)) for a in addrs])
        n += len(d)
        dec = {a: int(r.one()) if r.ok else 18 for a, r in zip(addrs, d, strict=True)}
        for pool in pools:
            o = oracle_by_pool.get(pool)
            mine = [a for a in addrs if pool in (node_instance.get(a) or []) and a not in priced]
            if not o or not mine:
                continue
            pr = rpc.read([Call(o, "getAssetPrice(address)", ("uint256",), (a,)) for a in mine])
            n += len(pr)
            for a, r in zip(mine, pr, strict=True):
                if r.ok:
                    priced[a] = int(r.one())
                    price_prov[a] = r.provenance
    values = {a: (weights[a] * priced.get(a, 0)) // (10 ** dec.get(a, 18)) for a in addrs}
    boxed, n_b = _boxed(cfg, rpc, boxed_walk, pools, oracle_by_pool, priced, price_prov)
    n += n_b
    # DET-14(a): `backing_value` is the sum of node values, so the boxed assets
    # are inside the denominator every share is taken over - they are backing,
    # not a footnote to it (C2, R-C2.2).
    total = sum(values.values()) + sum(x["value"] for x in boxed) or 1
    rows = []

    def disc_of(addr, label):
        nonlocal n
        if label != "recurses":
            return {}
        d, k = disclosure_fields(cfg, rpc, addr, http_get=http_get, key=key)
        n += k
        return d

    for x in boxed:
        row = cfg.labels[x["wrapper"]]
        d = disc_of(x["wrapper"], row.label)
        # DET-28 (P-7.03 ruling 1): the boxed node's price read is the protocol's
        # own `getAssetPrice(underlying)`; its feed address is filled from the
        # DET-55 row once the oracle rows are read (`assemble`).
        price = {"price": x["price_read"]} if x.get("price_read") else {}
        rows.append(CollateralNode(
            address=x["wrapper"], symbol=x["symbol"], label=row.label,
            label_source_address=x["wrapper"], node_class=row.node_class,
            lst_discount_applies=row.lst_discount_applies, value=x["value"],
            share_of_backing=Decimal(x["value"]) / Decimal(total),
            flags=x["flags"] + d.get("flags", []),
            disclosure_cadence=d.get("disclosure_cadence"),
            last_disclosure_date=d.get("last_disclosure_date"),
            last_disclosure_block=d.get("last_disclosure_block"),
            reads={**x["reads"], **price, **d.get("reads", {})},
            lineage=["gsm_read", "price_read"]))
    for a in addrs:
        row = cfg.labels[a]
        label = row.label
        flags: list[str] = []
        extra_reads: dict = {}
        if label is None:
            # A5: the READ is the label authority. GHO runs the same resolver
            # crvUSD does, on its own `[[wallet_registry]]` row; an unreachable
            # or non-closing read leaves the node unlabeled-in-run and routes
            # via §8.2 — never a default label (P-3.37 binding 2).
            got = resolved.get(a)
            if got is None:
                label = "unlisted"
                flags.append("A5: run-time label read unavailable or closure broken; "
                             "unlabeled-in-run, routed via 8.2")
            else:
                label, label_prov = got
                extra_reads["label"] = label_prov
                flags.append("A5: label from the run-time wallet-registry read")
        elif label == "unlabeled":
            label = "unlisted"
            flags.append(f"unlabeled: {row.reason} (share at classification {row.share})")
        d = disc_of(a, label)
        if a in price_prov:                     # DET-81's per-node price provenance
            extra_reads["price"] = price_prov[a]
        rows.append(CollateralNode(
            address=a, symbol=row.symbol, label=label, label_source_address=a,
            node_class=row.node_class, lst_discount_applies=row.lst_discount_applies,
            sell_side_capacity=sell_side_for(cfg, a, row.node_class),
            value=values[a], share_of_backing=Decimal(values[a]) / Decimal(total),
            flags=flags + d.get("flags", []),
            disclosure_cadence=d.get("disclosure_cadence"),
            last_disclosure_date=d.get("last_disclosure_date"),
            last_disclosure_block=d.get("last_disclosure_block"),
            reads={"balance": ContractRead(source_contract=a, function="balanceOf(address)",
                                           args=[], block=rpc.run_block), **extra_reads,
                   **d.get("reads", {})},
            lineage=["collateral_read", "price_read"]))
    return sorted(rows, key=lambda r: r.address), n


def assemble(cfg, rpc, repo, token: str, http_get=None, key: str = "",
             from_block: int = 0):
    """P-4.02's adapter signature — returns a full `Bundle` and its extras.

    `execute()` is token-agnostic and passes no transport, so the adapter builds
    its own POINTER transport here (two-argument, keyed) while the pool pass
    uses `discovery.catalog_get` (one-argument). Injection still wins, which is
    what keeps the walk stubbable in tests.
    """
    if http_get is None:
        http_get = default_transport(repo)
        key = key or pointer_env(repo, "ETHERSCAN_API_KEY")
    res = build(cfg, rpc, http_get=http_get, key=key, from_block=from_block)
    return res["bundle"], res


def build(cfg, rpc, http_get=None, key: str = "", from_block: int = 0):
    """Slice 2a+2b end to end: facilitators, GSMs, supply, positions, principal,
    nodes, admin surface, oracle rows, redemption paths — a whole `Bundle`."""
    gho = cfg.root("gho_token").address
    registry = cfg.root("gsm_registry").address
    reads = 0

    facilitators, n = read_facilitators(rpc, gho, cfg)
    reads += n
    supply_total = int(rpc.read([Call(gho, "totalSupply()", ("uint256",))])[0].one())
    reads += 1
    check_supply_identity(facilitators, supply_total)
    gsms, n = read_gsms(rpc, registry, http_get=http_get, key=key, from_block=from_block)
    reads += n

    bridge_rows = []
    for b in cfg.bridges:
        r = rpc.read([Call(gho, "balanceOf(address)", ("uint256",), (b["address"],))])[0]
        reads += 1
        # C-1: the AMOUNT is a contract read, the TYPE is the dated analyst row
        # from the DET-33 menu. Two provenances, because they are two claims.
        bridge_rows.append(Bridge(
            bridge_address=b["address"], amount=int(r.one()),
            bridge_type=b["bridge_type"],
            reads={"amount": r.provenance,
                   "bridge_type": AnalystSupplied(value=b["bridge_type"],
                                                  source=b["source"],
                                                  date=str(b["date"]))}))

    positions: list[GhoPosition] = []
    node_instance: dict[str, list[str]] = {}
    pointers = []
    oracle_by_pool: dict[str, str] = {}
    out_f = []
    for f in facilitators:
        if f.facilitator_class != "direct_minter":
            out_f.append(f)
            continue
        debt_token, atoken, reserves, atokens, oracle, n = read_instance(rpc, gho, f.pool_address)
        reads += n
        oracle_by_pool[f.pool_address] = oracle
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
            for res_addr in r.collateral:
                node_instance.setdefault(res_addr, [])
                if f.pool_address not in node_instance[res_addr]:
                    node_instance[res_addr].append(f.pool_address)
        out_f.append(f.model_copy(update={
            "debt_token_address": debt_token, "atoken_address": atoken, "inventory": inv,
            "reads": {**f.reads, "inventory": inv_prov,
                      "principal": ContractRead(source_contract=f.pool_address,
                                                function="Borrow(address,address,address,"
                                                         "uint256,uint8,uint256,uint16)",
                                                args=[gho], block=rpc.run_block),
                      "gross_debt": ContractRead(source_contract=debt_token,
                                                 function="balanceOf(address)", args=[],
                                                 block=rpc.run_block)},
            "n_positions": len(rows),
            "principal_sum": sum(x.principal for x in rows),
            "accrued_interest_sum": sum(x.accrued_interest for x in rows),
            "gross_debt_sum": sum(x.gross_debt for x in rows),
            "position_completeness": completeness}))
    facilitators = out_f
    pools = sorted(oracle_by_pool)

    weights = attribute_nodes(positions)
    # A5: the same resolver crvUSD uses, on GHO's own `[[wallet_registry]]`
    # rows. Nothing token-specific about it - the row carries the addresses.
    resolved = {}
    for wr in cfg.wallet_registries:
        got = resolve_wallet_registry_label(rpc, wr)
        reads += 2
        if got is not None:
            resolved[wr["node_address"]] = got
    walk, n = boxed_asset_walk(rpc, gsms) if gsms else ([], 0)
    reads += n
    nodes, n = _nodes(cfg, weights, node_instance, rpc, pools, oracle_by_pool,
                      resolved, walk, http_get=http_get, key=key)
    reads += n

    # ---- the per-run pool pass, THE SAME CODE crvUSD runs (P-4.11) ----------
    # GHO has no stabilizer, so `stabilizer_pools` is empty - the argument the
    # extraction introduced exists precisely so that is expressible.
    fs = json.loads(cfg.frozen_set_path.read_text(encoding="utf-8"))
    # DET-10(a) limb 1: the header stamps the bytes of the set file this run
    # read. Limb 2 is the gate's chain to the logged freeze event - the bundle
    # never compares the file to itself (P-3.46).
    fs_hash = hashlib.sha256(cfg.frozen_set_path.read_bytes()).hexdigest()[:8]
    prior = load_prior(_BUNDLES, cfg.token, rpc.run_block)
    prior_pools = ({p.address: {"tvl_at_par": p.tvl_at_par} for p in prior.pools}
                   if prior else {})
    try:
        pool_rows, below_floor, pool_detectors = build_pool_rows(
            rpc, cfg, fs, catalog_get, cfg.root("gho_token").address,
            set(), prior_pools, rpc.run_block)
    except AssemblyStopFromDiscovery as exc:
        raise GhoAdapterStop(str(exc)) from exc
    admin, aptrs, n = read_admin_surface(rpc, gho, gsms, pools, http_get, key, from_block)
    reads += n
    pointers.extend(aptrs)
    # DET-55 wants a row per priced node; a boxed wrapper is priced at its
    # underlying's feed, so the row is discovered there and says so (C2).
    oracle_rows, n = read_oracle_rows(rpc, cfg, pools, [r.address for r in nodes],
                                      node_instance,
                                      {w["wrapper"]: w["underlying"] for w in walk})
    reads += n
    feed_of = {r.node_address: r.feed_or_source for r in oracle_rows}
    boxed_wrappers = {w["wrapper"] for w in walk}
    nodes = [nd.model_copy(update={"feed_address": feed_of.get(nd.address)})
             if nd.address in boxed_wrappers else nd for nd in nodes]
    paths, n = redemption_paths(rpc, gsms, gho)
    reads += n

    # DET-15(b) (P-7.05 S1, the letter): GHO's O is the sum of facilitator
    # bucket levels, so the residual is 0 by the supply identity. P-4.04 R1's
    # direct-minter-principal reading is superseded.
    origination = sum(f.bucket_level for f in facilitators)
    burn_mint = [b for b in bridge_rows if b.bridge_type == "burn_and_mint"]
    disclosure = (f"bridged component assessed: {len(bridge_rows)} "
                  f"{bridge_rows[0].bridge_type if bridge_rows else 'no'} escrow(s); "
                  f"burn_and_mint component {'zero' if not burn_mint else 'present'}")
    supply = Supply(total_supply=supply_total, supply_ruled=supply_total,
                    bridge_state="populated" if bridge_rows else "not_configured",
                    bridge_disclosure=disclosure if bridge_rows
                    else "no bridge classification data configured",
                    bridges=bridge_rows, origination_sum=origination,
                    residual=supply_total - origination,
                    residual_unexplained=supply_total - origination,
                    stabilizer_over_supply=Decimal(0),
                    reads={"total_supply": ContractRead(
                        source_contract=gho, function="totalSupply()", args=[],
                        block=rpc.run_block)})

    from factory.run import static_metadata_of
    first = is_first_run(_BUNDLES, "GHO") if _BUNDLES else True
    raw = json.dumps([p.model_dump(mode="json") for p in positions],
                     sort_keys=True, separators=(",", ":"))
    bundle = Bundle(
        header=Header(token="GHO", run_block=rpc.run_block,
                      block_timestamp=rpc.block_timestamp,
                      run_start_time=rpc.run_start_time, first_run=first,
                      pipeline_version="0.1.0", sheet_hash=cfg.sheet["sheet_hash"],
                      frozen_set_hash=fs_hash, freeze_date=fs["freeze_date"],
                      raw_positions_hash=hashlib.sha256(raw.encode()).hexdigest()),
        markets=[], facilitators=facilitators, gsms=gsms,
        stabilizer=StabilizerBlock(operations=[], ceiling_aggregate=0,
                                   ceiling_aggregate_lineage=[]),
        supply=supply, nodes=nodes, oracle_rows=oracle_rows, redemption_paths=paths,
        admin_surface=admin, lend_markets=[],
        pools=pool_rows, pool_detectors=pool_detectors,
        offvenue_share=read_share(gho),
        static_metadata=static_metadata_of(cfg),
        counts=Counts(mint_market_count=sum(1 for f in facilitators
                                            if f.facilitator_class == "direct_minter"),
                      below_floor_pool_count=below_floor,
                      lend_market_count=cfg.lend.market_count_field,
                      lend_market_count_note=(
                          "explicitly empty: GHO's Aave instances ARE the lending "
                          "venues and are counted as origination, not re-lending; a "
                          "third-party aGHO holding is a supply read (P-4.08)"),
                      facilitator_count=len(facilitators), gsm_count=len(gsms)),
        attribution_method=cfg.sheet["attribution_method"],
        first_run_literals=FirstRunLiterals() if first else None)
    return {"bundle": bundle, "positions": positions, "raw": raw,
            "last_run_ratio": last_run_ratios(_BUNDLES, cfg.token,
                                              cfg.frozen_set_path, rpc.run_block),
            "node_weights": weights, "node_instances": node_instance,
            "pointers": [p.record() for p in pointers], "reads": reads}

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

# --------------------------------------------------------------- surfaces ---
# 2b: the admin surface, oracle rows, redemption paths, lend disclosure. Every
# holder here is DISCOVERED - role logs as pointer, `hasRole` at `run_block` as
# verdict (P-4.04 R5) - and every absence is an F4-shaped absence read rather
# than a silent omission.

ROLE_REVOKED = _sig("RoleRevoked(bytes32,address,address)")
A1_POWERS = ("mint", "set_ceiling", "upgrade", "pause", "freeze_asset",
             "blacklist_address", "set_oracle", "set_parameters", "seize")
EIP1967_IMPL = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
EIP1967_ADMIN = "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103"


def role_holders(contract: str, role: bytes, rpc, http_get, key: str,
                 from_block: int) -> tuple[list[str], object, int]:
    """Current holders of one role: `RoleGranted`/`RoleRevoked` as POINTER,
    `hasRole` at `run_block` as VERDICT. A revoked-then-regranted holder comes
    back because the verdict is a state read, not a replay of the log."""
    role_topic = "0x" + role.hex()
    cand: set[str] = set()
    ptrs = []
    for sig in (ROLE_GRANTED, ROLE_REVOKED):
        p = get_logs(contract, [sig, role_topic], from_block, rpc.run_block, http_get, key)
        ptrs.append(p)
        for r in p.rows:
            if len(r.topics) > 2:
                cand.add("0x" + r.topics[2][-40:])
    uniq = sorted(cand)
    res = rpc.read([Call(contract, "hasRole(bytes32,address)", ("bool",), (role, h))
                    for h in uniq]) if uniq else []
    held = [h for h, v in zip(uniq, res, strict=False) if v.ok and v.one()]
    return held, ptrs, len(res)


def holder_type(rpc, addr: str) -> tuple[str, int | None, int]:
    """What KIND of holder, from what the address answers - never from a name.

    `getDelay()` answers  -> timelock, and the delay is the read.
    `getThreshold()`      -> multisig.
    no code               -> eoa.
    otherwise             -> contract_automated.
    NAMED DEFAULT (P-4.08): `dao_governance` is never assigned by probe. An
    Aave executor IS the DAO's instrument, and it answers `getDelay()`, so it
    lands as `timelock` - the stricter, read-backed statement.
    """
    r = rpc.read([Call(addr, "getDelay()", ("uint256",)),
                  Call(addr, "getThreshold()", ("uint256",))])
    if r[0].ok:
        return "timelock", int(r[0].one()), 2
    if r[1].ok:
        return "multisig", None, 2
    return "contract_automated", None, 2


def _bucket(delay: int | None) -> str:
    if not delay:
        return "none"
    if delay < 86_400:
        return "<24h"
    return "1-7d" if delay <= 604_800 else ">7d"


def read_admin_surface(rpc, gho: str, gsms: list, pools: list[str], http_get, key: str,
                       from_block: int) -> tuple[list, list, int]:
    """The nine A1 rows (DET-68). Holders by role logs + `hasRole`; upgrade by
    EIP-1967 slot; `blacklist_address` by selector-absence scan."""
    rows, ptrs, n = [], [], 0
    roles = {"FACILITATOR_MANAGER_ROLE": keccak(text="FACILITATOR_MANAGER_ROLE"),
             "BUCKET_MANAGER_ROLE": keccak(text="BUCKET_MANAGER_ROLE")}
    acl = {}
    for p in pools:
        ap = rpc.read([Call(p, "ADDRESSES_PROVIDER()", ("address",))])[0]
        n += 1
        if ap.ok:
            m = rpc.read([Call(ap.one(), "getACLManager()", ("address",))])[0]
            n += 1
            if m.ok:
                acl[p] = m.one().lower()

    def first(holders):
        return holders[0] if holders else None

    def row(power, holder, prov, **kw):
        ht, delay, k = ("none", None, 0)
        if holder:
            ht, delay, k = holder_type(rpc, holder)
        return (AdminRow(power=power, holder_address=holder, holder_type=ht,
                         delay_seconds=delay, delay_bucket=_bucket(delay),
                         provenance=prov, **kw), k)

    # --- mint / set_ceiling: GhoToken roles ---------------------------------
    for power, role_name in (("mint", "FACILITATOR_MANAGER_ROLE"),
                             ("set_ceiling", "BUCKET_MANAGER_ROLE")):
        held, p, k = role_holders(gho, roles[role_name], rpc, http_get, key, from_block)
        ptrs.extend(p)
        n += k
        h = first(held)
        prov = (ContractRead(source_contract=gho, function="hasRole(bytes32,address)",
                             args=[role_name, h or ""], block=rpc.run_block) if h
                else AbsenceRead(contract=gho, method="selector_absence_scan",
                                 evidence=f"no live {role_name} holder", block=rpc.run_block))
        r, k = row(power, h, prov, scope=[gho])
        n += k
        rows.append(r)

    # --- upgrade: EIP-1967 slots -------------------------------------------
    admin_slot = rpc.storage(gho, EIP1967_ADMIN)
    impl_slot = rpc.storage(gho, EIP1967_IMPL)
    n += 2
    up = "proxy_upgradeable" if int(impl_slot, 16) else "immutable"
    holder = ("0x" + admin_slot[-40:]) if int(admin_slot, 16) else None
    prov = AbsenceRead(contract=gho, method="eip1967_slot_read",
                       evidence=admin_slot, block=rpc.run_block)
    r, k = row("upgrade", holder, prov, upgradeability=up, scope=[gho])
    n += k
    rows.append(r)

    # --- pause / freeze_asset / set_oracle / set_parameters: ACLManager -----
    acl_roles = {"pause": "EMERGENCY_ADMIN", "freeze_asset": "RISK_ADMIN",
                 "set_oracle": "ASSET_LISTING_ADMIN", "set_parameters": "RISK_ADMIN"}
    for power, rname in acl_roles.items():
        h, prov = None, None
        for mgr in acl.values():
            held, p, k = role_holders(mgr, keccak(text=rname), rpc, http_get, key,
                                      from_block)
            ptrs.extend(p)
            n += k
            if held:
                h = held[0]
                prov = ContractRead(source_contract=mgr,
                                    function="hasRole(bytes32,address)",
                                    args=[rname, h], block=rpc.run_block)
                break
        if prov is None:
            prov = AbsenceRead(contract=(next(iter(acl.values())) if acl else gho),
                               method="selector_absence_scan",
                               evidence=f"no live {rname} holder", block=rpc.run_block)
        # DET-69 (R18): GHO marked nothing. `pause` is the live model input —
        # the EMERGENCY_ADMIN role is what the §6.3 H2 freezer routing turns on
        # (DET-46), so the row that names its holder feeds a modeled quantity.
        live = power == "pause"
        r, k = row(power, h, prov, scope=sorted(acl), live_model_input=live,
                   consumed_by=["DET-46 freezer"] if live else [])
        n += k
        rows.append(r)

    # --- pause: the GSM swap freeze, its own rows (P-7.05 S7) ---------------
    # The sheet's §13 `pause` row names GSM `SWAP_FREEZER_ROLE` beside the Pool's
    # EMERGENCY_ADMIN. DET-68 is "one row per (power, holder) pair, A2 scalar", so
    # each freezer is its own row: holder the freezer `read_gsms` discovered, A8 =
    # `hasRole(SWAP_FREEZER_ROLE, freezer)` on each GSM, A7 = the GSMs on which
    # that read is true. The Pool rows above are unchanged.
    freezers = sorted({g.freezer_address for g in gsms if g.freezer_address})
    if freezers:
        fr = rpc.read([Call(g.address, "hasRole(bytes32,address)", ("bool",),
                            (SWAP_FREEZER_ROLE, f)) for f in freezers for g in gsms])
        n += len(fr)
        for i, f in enumerate(freezers):
            held = [g for j, g in enumerate(gsms)
                    if fr[i * len(gsms) + j].ok and fr[i * len(gsms) + j].one()]
            if not held:
                continue
            r, k = row("pause", f, ContractRead(
                source_contract=held[0].address, function="hasRole(bytes32,address)",
                args=["SWAP_FREEZER_ROLE", f], block=rpc.run_block),
                scope=[g.address for g in held],
                reads={f"SWAP_FREEZER_ROLE:{g.address}": ContractRead(
                    source_contract=g.address, function="hasRole(bytes32,address)",
                    args=["SWAP_FREEZER_ROLE", f], block=rpc.run_block) for g in held})
            n += k
            rows.append(r)

    # --- blacklist_address: the selector is simply absent (F4) --------------
    code = rpc.code(gho)
    n += 1
    present = any(sel in code for sel in ("0xf9f92be4", "0x1a695230"))
    rows.append(AdminRow(power="blacklist_address", holder_address=None,
                         holder_type="none", delay_bucket="none",
                         provenance=AbsenceRead(
                             contract=gho, method="selector_absence_scan",
                             evidence=f"blacklist selector present={present}",
                             block=rpc.run_block)))

    # --- seize: GSM LIQUIDATOR_ROLE ----------------------------------------
    h, prov = None, None
    for g in gsms:
        held, p, k = role_holders(g.address, keccak(text="LIQUIDATOR_ROLE"), rpc,
                                  http_get, key, from_block)
        ptrs.extend(p)
        n += k
        if held:
            h = held[0]
            prov = ContractRead(source_contract=g.address,
                                function="hasRole(bytes32,address)",
                                args=["LIQUIDATOR_ROLE", h], block=rpc.run_block)
            break
    if prov is None:
        prov = AbsenceRead(contract=(gsms[0].address if gsms else gho),
                           method="selector_absence_scan",
                           evidence="no live LIQUIDATOR_ROLE holder", block=rpc.run_block)
    r, k = row("seize", h, prov, scope=[g.address for g in gsms])
    n += k
    rows.append(r)
    return rows, ptrs, n


def read_oracle_rows(rpc, cfg, pools: list[str], nodes: list[str],
                     node_instance: dict[str, list[str]],
                     priced_by: dict[str, str] | None = None) -> tuple[list, int]:
    """One row per labelled node. The Aave price SOURCE is discovered per
    instance; its class comes from `description()` and whether `aggregator()`
    answers, not from a list.

    `priced_by` names the address whose feed prices a node when that is not the
    node itself — DET-28's boxed wrappers, which are not reserves and whose
    price is their underlying's under §4.3 (C2). DET-55 needs a row for every
    node with value > 0, so the pass-through is disclosed on the row rather
    than left to produce a missing one.
    """
    n = 0
    oracle = {}
    for p in pools:
        ap = rpc.read([Call(p, "ADDRESSES_PROVIDER()", ("address",))])[0]
        n += 1
        if ap.ok:
            o = rpc.read([Call(ap.one(), "getPriceOracle()", ("address",))])[0]
            n += 1
            if o.ok:
                oracle[p] = o.one()
    rows = []
    priced_by = priced_by or {}
    for node in nodes:
        asset = priced_by.get(node, node)
        inst = (node_instance.get(asset) or pools)[0]
        o = oracle.get(inst)
        if o is None:
            continue
        s = rpc.read([Call(o, "getSourceOfAsset(address)", ("address",), (asset,))])[0]
        n += 1
        if not s.ok:
            continue
        src = s.one().lower()
        q = rpc.read([Call(src, "description()", ("string",)),
                      Call(src, "aggregator()", ("address",)),
                      Call(src, "latestRoundData()",
                           ("uint80", "int256", "uint256", "uint256", "uint80"))])
        n += 3
        desc = q[0].value[0] if q[0].ok else ""
        raw = q[1].ok
        cls = "nav" if "NAV" in desc else ("capo" if desc.startswith("Capped") or "/" in desc
                                           and not raw else ("raw" if raw else "other"))
        if raw and not desc.startswith("Capped") and "NAV" not in desc:
            cls = "raw"
        answer = int(q[2].value[1]) if q[2].ok else None
        updated = int(q[2].value[3]) if q[2].ok else None
        signed = cfg.oracle_feeds.get(node)
        if signed is None:
            raise GhoAdapterStop(f"DET-55: no signed feed row for priced node {node}")
        observed, extra = None, []
        if signed["heartbeat_form"] == "observed_max":
            observed, extra, k = nav_observed_max(rpc, src)
            n += k
        rows.append(OracleRow(
            node_address=node, market_or_reserve_address=inst, feed_or_source=src,
            update_condition=condition_from_row(
                signed, src, answer, updated,
                [q[2].provenance if hasattr(q[2], "provenance") else s.provenance], observed),
            # DET-55's enum, from the sheet's §7 line: "instant observation,
            # nearly exact" - GHO carries no oracle counterfactual (B-9).
            assumption_applied="instant",
            counterfactual_ref=None,
            reference_feed="pending_config_round",
            market_vs_protocol_oracle_gap="pending_config_round",
            staleness_check=None, adapter_class=cls,
            disclosure="; ".join([desc, *extra])
            + ("" if asset == node else
               f"; priced through memo 4.3 at its underlying {asset}'s feed (C2)")))
    return rows, n


def redemption_paths(rpc, gsms: list, gho: str) -> tuple[list, int]:
    """The sheet's R1-R5: one `module_on_chain` path per LIVE GSM, plus the
    Aave facilitator path at `none` (a borrower repaying is not a holder
    redemption - R2 is `no_one` on that path, per the sheet's Path 2)."""
    n = 0
    out = []
    for g in gsms:
        out.append(RedemptionPath(
            r1_path="module_on_chain", r2_who="anyone",
            r3_received=[g.underlying_asset],
            r4_rate="face_minus_fee(sell fee from GSM.getFeeStrategy())",
            r5_minimum="none", r6_gates=[{"kind": "capacity_limited", "param": None},
                                         {"kind": "pausable", "param": None}],
            # R7 by IDENTITY (ruled 2026-09-08): the path names the table and
            # the field; the row is the one whose `underlying_asset` is this
            # path's R3. A raw number here is not a resolvable field ref.
            r7_capacity="gsms.available_liquidity", r8="enforceable_unless_paused (see R7)",
            r9_legal_claim="no_pure_protocol",
            r10_provenance=ContractRead(source_contract=g.address,
                                        function="getFeeStrategy()", args=[],
                                        block=rpc.run_block)))
    out.append(RedemptionPath(
        r1_path="none", r2_who="no_one", r3_received="n/a", r4_rate="n/a",
        r5_minimum="n/a", r6_gates=[{"kind": "none", "param": None}],
        r7_capacity="n/a", r8="n/a", r9_legal_claim="no_pure_protocol",
        r10_provenance=AbsenceRead(contract=gho, method="selector_absence_scan",
                                   evidence="no holder redemption function on GhoToken",
                                   block=rpc.run_block)))
    return out, n


__all__ = ["GhoAdapterStop", "PROBE", "assemble", "attribute_nodes",
           "boxed_asset_walk", "build",
           "borrower_ledger", "check_supply_identity", "read_admin_surface",
           "read_facilitators", "read_gsms", "read_instance", "read_inventory",
           "read_oracle_rows", "read_positions", "redemption_paths", "role_holders"]
