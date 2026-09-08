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

from factory.rpc import Call
from factory.schema import Facilitator, Gsm

# DET-28's discriminators, read from the chain at block 25930871 rather than
# recalled: each class answers a selector no other class answers.
PROBE: tuple[tuple[str, str, tuple], ...] = (
    ("POOL()", "address", ()),                    # direct minter -> its Aave instance
    ("maxFlashLoan(address)", "uint256", ("token",)),   # flash minter
    ("getToken()", "address", ()),                # CCIP-class token pool
    ("GHO_TOKEN()", "address", ()),               # every GHO-aware facilitator
)
SWAP_FREEZER_ROLE = keccak(text="SWAP_FREEZER_ROLE")
ROLE_GRANTED = "0x" + keccak(text="RoleGranted(bytes32,address,address)").hex().removeprefix("0x")

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
            for h in dict.fromkeys(holders):                 # order-preserving unique
                v = rpc.read([Call(a, "hasRole(bytes32,address)", ("bool",),
                                   (SWAP_FREEZER_ROLE, h))])[0]
                n += 1
                if v.ok and v.one():
                    freezer = h
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


def read_inventory(rpc, gho: str, rows: list[Facilitator]) -> tuple[list[Facilitator], int]:
    """Undrawn protocol-held inventory per direct minter: the GHO its Aave
    instance still holds, i.e. `aGHO.balanceOf(aGHO)` reached through
    `Pool.getReserveAToken(GHO)`. Amounts only — **no denominator math**: the
    `supply_ruled` question is P-4.01 #3 and is not answered here (F4).
    """
    minters = [f for f in rows if f.facilitator_class == "direct_minter"]
    if not minters:
        return rows, 0
    at = rpc.read([Call(f.pool_address, "getReserveAToken(address)", ("address",), (gho,))
                   for f in minters])
    n = len(at)
    bal = rpc.read([Call(r.one().lower(), "balanceOf(address)", ("uint256",),
                         (r.one().lower(),)) for r in at])
    n += len(bal)
    got = {f.address: int(b.one()) for f, b in zip(minters, bal, strict=True) if b.ok}
    out = [f.model_copy(update={"inventory": got[f.address]}) if f.address in got else f
           for f in rows]
    return out, n


def assemble(cfg, rpc, repo, token: str, http_get=None):
    """P-4.02's adapter signature. Builds slice 1 and STOPS — see
    `GhoAdapterIncomplete`. No bundle is returned and nothing is written."""
    gho = cfg.root("gho_token").address
    registry = cfg.root("gsm_registry").address

    facilitators, n1 = read_facilitators(rpc, gho)
    supply = int(rpc.read([Call(gho, "totalSupply()", ("uint256",))])[0].one())
    check_supply_identity(facilitators, supply)
    facilitators, n2 = read_inventory(rpc, gho, facilitators)
    gsms, n3 = read_gsms(rpc, registry, http_get=http_get)

    raise GhoAdapterIncomplete(
        f"GHO slice 1 built: {len(facilitators)} facilitators, {len(gsms)} GSMs, "
        f"totalSupply {supply}, {n1 + n2 + n3 + 1} pinned reads. "
        "OWED before a bundle can be constructed: positions and nodes, the nine "
        "admin_surface rows (DET-68), oracle_rows, redemption_paths (DET-66's GHO "
        "clause), pools and pool_detectors, and the supply block. Sessions 2-3."
    )


__all__ = ["GhoAdapterIncomplete", "PROBE", "assemble", "check_supply_identity",
           "read_facilitators", "read_gsms", "read_inventory"]
