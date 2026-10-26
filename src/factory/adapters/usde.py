"""Step 10, commit 4 (P-10.06): the USDe adapter - archetype #2's first live reads.

It reads the signed sheet's registry (intake-sheet-usde.md, FR-U01..FR-U37) and
nothing else: on-chain reads pinned to one `run_block`, the seven disclosure
fetches as `DisclosureSnapshot`s, role holders by POINTER (Etherscan logs) and
VERDICT (`hasRole` at `run_block`), group (ii) as the union of the dated wallet
list and the route's Ethereum `addressEntries`. The CDP-shaped bundle fields carry
Q44's ruled empties; the reads themselves sit in `bundle.synthetic`, keyed by tag.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import pathlib
import time
import urllib.request
from decimal import Decimal

from eth_utils import function_signature_to_4byte_selector, keccak
from web3 import Web3

from factory.adapters.gho import role_holders
from factory.discovery import (
    AssemblyStopFromDiscovery,
    build_pool_rows,
    catalog_get,
    fetch_candidates,
    value_candidates,
)
from factory.logbook import is_first_run, load_prior
from factory.logs_pointer import default_transport, env
from factory.offvenue import read_share
from factory.provenance import AbsenceRead, AnalystSupplied, ContractRead, DisclosureSnapshot
from factory.rpc import Call
from factory.schema import (
    AdminRow,
    Bridge,
    Bundle,
    Counts,
    FirstRunLiterals,
    Header,
    PoolDetectors,
    RedemptionPath,
    StabilizerBlock,
    Supply,
    SyntheticBlock,
    SyntheticRead,
)

_BUNDLES = pathlib.Path("out/bundles")
APP = "https://app.ethena.fi"
MULTICALL3 = "0xca11bde05977b3631167028862be2a173976ca11"
EIP1967 = {"implementation": "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc",
           "admin": "0xb53127684a568b3173ae13b9f8a6016e243e63b6e8ee1178d6a717850b5d6103",
           "beacon": "0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50"}
# NAMED IMPLEMENTER DEFAULT: the log walks start before USDe's launch (sUSDe was
# created at block 18571359, P-10.02 G6-bis); every role and set event is later.
LOGS_FROM_BLOCK = 18_500_000
REDEEM_V2 = ("redeem((string,uint8,uint120,uint128,address,address,address,uint128,uint128),"
             "(uint8,bytes))")                            # verified ABI, P-10.06
SEIZE_SUSDE = "redistributeLockedAmount(address,address)"
ORACLE_SETTERS = ("setOracle(address)", "setPriceOracle(address)", "setAggregator(address)",
                  "setPriceFeed(address)")

# The seven disclosure routes (D15, D13, D14, D19) and the top-level keys each must
# carry - a missing key is a SHAPE CHANGE (Q29: harness error, T-25, Level 2).
ROUTES = {
    "backing_assets": ("/api/positions/current/backing-assets", {"strategies", "timestamp"}),
    "collateral_breakdown": ("/api/collateral-breakdown", {"breakdown"}),
    "status": ("/api/collateralization/status",
               {"timestamp", "totalBackingAssetsInUsd", "totalReserveFundInUsd",
                "totalTokenSupplyInUsd"}),
    "por": ("/api/por", {"lastUpdatedAt", "reports"}),
    "institutional_lending": ("/api/institutional-lending", {"asOf", "totals", "counterparties"}),
    "stablecoin_collateral": ("/api/stablecoin-collateral", None),
    "funding_quarterly": ("/api/funding/quarterly", None),
}


class UsdeAdapterStop(Exception):
    """A read the sheet requires failed, or a disclosure changed shape."""


def _role(name: str) -> bytes:
    return b"\x00" * 32 if name == "DEFAULT_ADMIN_ROLE" else keccak(text=name)


def _cs(a: str) -> str:
    return Web3.to_checksum_address(a)


def _cr(contract: str, fn: str, block: int, args=()) -> ContractRead:
    return ContractRead(source_contract=contract.lower(), function=fn,
                        args=[str(a) for a in args], block=block)


# ------------------------------------------------------------ disclosures --


def _http_bytes(url: str) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "stable-dashboard/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.read()


def _as_of(name: str, body, fetched: _dt.datetime) -> _dt.date:
    """Each route's own as-of; NAMED DEFAULT: the fetch date where the route has none
    (collateral-breakdown, funding/quarterly)."""
    if name == "backing_assets":
        return _dt.datetime.fromtimestamp(int(body["timestamp"]), _dt.UTC).date()
    if name == "status":
        return _dt.date.fromisoformat(str(body["timestamp"])[:10])
    if name == "por":
        return _dt.date.fromisoformat(str(body["lastUpdatedAt"])[:10])
    if name == "institutional_lending":
        return _dt.date.fromisoformat(str(body["asOf"])[:10])
    if name == "stablecoin_collateral":
        ts = max(int(v["timestamp"]) for v in body.values())
        return _dt.datetime.fromtimestamp(ts, _dt.UTC).date()
    return fetched.date()


def fetch_disclosures(get=_http_bytes) -> dict[str, dict]:
    """Fetch the seven routes once each; validate their shape; pin each by sha256."""
    out = {}
    for name, (path, keys) in ROUTES.items():
        url = APP + path
        status, raw = get(url)
        fetched = _dt.datetime.now(_dt.UTC).replace(microsecond=0)
        if status != 200:
            raise UsdeAdapterStop(f"disclosure {path}: HTTP {status}")
        body = json.loads(raw)
        if keys is not None and (not isinstance(body, dict) or not keys <= set(body)):
            raise UsdeAdapterStop(f"disclosure {path}: SHAPE CHANGE, missing "
                                  f"{sorted(keys - set(body) if isinstance(body, dict) else keys)}")
        if name == "stablecoin_collateral" and not isinstance(body, dict):
            raise UsdeAdapterStop(f"disclosure {path}: SHAPE CHANGE (not an object)")
        if name == "funding_quarterly" and not (isinstance(body, list) and body
                                                and {"name", "value"} <= set(body[0])):
            raise UsdeAdapterStop(f"disclosure {path}: SHAPE CHANGE (not a quarter list)")
        prov = DisclosureSnapshot(source_url=url, as_of_date=_as_of(name, body, fetched),
                                  sha256=hashlib.sha256(raw).hexdigest(), fetched_at=fetched)
        out[name] = {"url": url, "body": body, "prov": prov, "bytes": len(raw)}
    return out


def snapshot_set(d: dict[str, dict]) -> str:
    """The committed disclosure set (Q42): every route's body plus its pin."""
    return json.dumps({k: {"url": v["url"], "sha256": v["prov"].sha256,
                           "fetched_at": v["prov"].fetched_at.isoformat(),
                           "as_of_date": v["prov"].as_of_date.isoformat(), "body": v["body"]}
                       for k, v in sorted(d.items())},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ------------------------------------------------------------ chain helpers --


def holder_kind(rpc, addr: str) -> tuple[str, int | None]:
    """Archetype #2's own holder classifier (P-10.06; the GHO helper probes `getDelay()`
    and never returns `eoa`): no code -> eoa; `getThreshold()` -> multisig;
    `getMinDelay()` -> timelock (the delay is the read); otherwise contract_automated."""
    if rpc.code(addr) in ("0x", "0x0", ""):
        return "eoa", None
    r = rpc.read([Call(addr, "getThreshold()", ("uint256",)),
                  Call(addr, "getMinDelay()", ("uint256",))])
    if r[0].ok:
        return "multisig", None
    if r[1].ok:
        return "timelock", int(r[1].one())
    return "contract_automated", None


def _bucket(delay: int | None) -> str:
    if not delay:
        return "none"
    if delay < 86_400:
        return "<24h"
    return "1–7d" if delay <= 604_800 else ">7d"


def _has_selector(code: str, sig: str) -> bool:
    """PUSH4 <selector> in the dispatcher (0x63 + four bytes)."""
    return ("63" + function_signature_to_4byte_selector(sig).hex()) in code.lower()


def _set_from_events(rpc, contract: str, added: str, removed: str, verdict: str,
                     http, key: str) -> tuple[list[str], list[ContractRead]]:
    """POINTER: add/remove events; VERDICT: the `is…` getter at `run_block`."""
    from factory.logs_pointer import get_logs
    cand = set()
    for sig in (added, removed):
        topic = "0x" + keccak(text=sig).hex().removeprefix("0x")
        for r in get_logs(contract, [topic], LOGS_FROM_BLOCK, rpc.run_block, http, key).rows:
            a = r.topics[1] if len(r.topics) > 1 else r.data
            cand.add(("0x" + a[-40:]).lower())
    uniq = sorted(cand)
    res = rpc.read([Call(contract, verdict, ("bool",), (_cs(a),)) for a in uniq])
    held = [a for a, v in zip(uniq, res, strict=True) if v.ok and v.one()]
    return held, [v.provenance for a, v in zip(uniq, res, strict=True) if a in held]


def _balances(rpc, holders: list[str], assets: list[str]) -> tuple[dict, list]:
    """balanceOf(holder) for every asset; one aggregate3 per 150 calls."""
    pairs = [(h, a) for h in holders for a in assets]
    res = rpc.read([Call(a, "balanceOf(address)", ("uint256",), (_cs(h),)) for h, a in pairs])
    out = {}
    for (h, a), r in zip(pairs, res, strict=True):
        if not r.ok:
            raise UsdeAdapterStop(f"balanceOf({h}) on {a} failed: {r.error}")
        if int(r.one()):
            out.setdefault(h, {})[a] = int(r.one())
    return out, [r.provenance for r in res]


def _usd(bals: dict, decimals: dict) -> Decimal:
    """At par (R-16): every buffer asset is a dollar stable."""
    return sum((Decimal(v) / Decimal(10) ** decimals[a]
                for row in bals.values() for a, v in row.items()), Decimal(0))


# ------------------------------------------------------------------ build --


def assemble(cfg, rpc, repo, token: str, http_get=None):
    res = build(cfg, rpc, repo, http_get=http_get or catalog_get)
    return res["bundle"], res


def build(cfg, rpc, repo, http_get=catalog_get, disclosure_get=_http_bytes,
          pointer=None):
    t0 = time.perf_counter()
    rb = rpc.run_block
    usde = cfg.root("usde_token").address
    susde = cfg.root("susde").address
    rf = cfg.root("reserve_fund").address
    oft = cfg.root("oft_adapter").address
    http = pointer or default_transport(repo)
    key = env(repo, "ETHERSCAN_API_KEY")
    R: dict[str, SyntheticRead] = {}
    reg = {r["tag_id"]: r for r in cfg.sheet.get("first_run_read", [])}

    def put(tag, value, prov):
        R[tag] = SyntheticRead(tag_id=tag, field_path=reg[tag]["bundle_field_path"],
                               value=value, provenance=prov if isinstance(prov, list) else [prov])

    # ---- USDe, sUSDe, silo, adapter --------------------------------------------
    c = rpc.read([Call(usde, "owner()", ("address",)), Call(usde, "pendingOwner()", ("address",)),
                  Call(usde, "minter()", ("address",)), Call(usde, "totalSupply()", ("uint256",)),
                  Call(usde, "decimals()", ("uint8",)),
                  Call(susde, "cooldownDuration()", ("uint24",)),
                  Call(susde, "totalAssets()", ("uint256",)),
                  Call(susde, "totalSupply()", ("uint256",)),
                  Call(usde, "balanceOf(address)", ("uint256",), (_cs(susde),)),
                  Call(susde, "silo()", ("address",)),
                  Call(usde, "balanceOf(address)", ("uint256",), (_cs(oft),)),
                  Call(oft, "approvalRequired()", ("bool",)),
                  Call(oft, "token()", ("address",))])
    for r in c:
        r.require()
    owner, pending, minter = (c[i].one().lower() for i in range(3))
    total, dec = int(c[3].one()), int(c[4].one())
    if dec != 18:
        raise UsdeAdapterStop(f"USDe decimals() = {dec}; base units assume 18")
    if c[12].one().lower() != usde:
        raise UsdeAdapterStop("OFT adapter token() is not USDe")
    silo = c[9].one().lower()
    s_bal = rpc.read([Call(usde, "balanceOf(address)", ("uint256",), (_cs(silo),))])[0]
    staked, escrow, cooling = int(c[8].one()), int(c[10].one()), int(s_bal.one())
    put("FR-U01", {"owner": owner, "pending_owner": pending}, [c[0].provenance, c[1].provenance])
    put("FR-U02", minter, c[2].provenance)
    put("FR-U03", total, c[3].provenance)
    put("FR-U04", int(c[5].one()), c[5].provenance)
    put("FR-U05", {"total_assets": int(c[6].one()), "total_supply": int(c[7].one())},
        [c[6].provenance, c[7].provenance])
    put("FR-U06", staked, c[8].provenance)
    put("FR-U07", {"silo": silo, "balance": cooling}, [c[9].provenance, s_bal.provenance])
    put("FR-U08", {"balance": escrow, "approval_required": bool(c[11].one())},
        [c[10].provenance, c[11].provenance])

    # ---- EthenaMinting V2 (derived from minter()) -----------------------------------
    v2 = minter
    g = rpc.read([Call(v2, "globalConfig()", ("uint128", "uint128")),
                  Call(v2, "owner()", ("address",))])
    gmint, gredeem = (int(x) for x in g[0].require())
    v2_owner = g[1].one().lower()
    put("FR-U09", {"global_max_mint_per_block": gmint, "global_max_redeem_per_block": gredeem},
        g[0].provenance)
    custodians, cprov = _set_from_events(rpc, v2, "CustodianAddressAdded(address)",
                                         "CustodianAddressRemoved(address)",
                                         "isCustodianAddress(address)", http, key)
    assets, aprov = _set_from_events(rpc, v2, "AssetAdded(address)", "AssetRemoved(address)",
                                     "isSupportedAsset(address)", http, key)
    put("FR-U11", custodians, cprov)
    put("FR-U12", assets, aprov)
    tc = rpc.read([Call(v2, "tokenConfig(address)", ("uint8", "bool", "uint128", "uint128"),
                        (_cs(a),)) for a in assets])
    put("FR-U10", {a: {"token_type": int(r.require()[0]), "is_active": bool(r.require()[1]),
                       "max_mint_per_block": int(r.require()[2]),
                       "max_redeem_per_block": int(r.require()[3])}
                   for a, r in zip(assets, tc, strict=True)}, [r.provenance for r in tc])

    # ---- roles: logs (POINTER) + hasRole (VERDICT) ------------------------------
    def roles(contract, names):
        held, prov = {}, []
        for n in names:
            h, _ptrs, _k = role_holders(contract, _role(n), rpc, http, key, LOGS_FROM_BLOCK)
            held[n] = h
            prov += [_cr(contract, "hasRole(bytes32,address)", rb, ["0x" + _role(n).hex(), x])
                     for x in h]
        return held, prov

    v2_roles, p13 = roles(v2, ("DEFAULT_ADMIN_ROLE", "MINTER_ROLE", "REDEEMER_ROLE",
                                "GATEKEEPER_ROLE", "COLLATERAL_MANAGER_ROLE"))
    put("FR-U13", v2_roles, p13)
    s_roles, p14 = roles(susde, ("DEFAULT_ADMIN_ROLE", "REWARDER_ROLE", "BLACKLIST_MANAGER_ROLE",
                                 "SOFT_RESTRICTED_STAKER_ROLE"))
    put("FR-U14", s_roles, p14)
    full, p32 = roles(susde, ("FULL_RESTRICTED_STAKER_ROLE",))
    put("FR-U32", len(full["FULL_RESTRICTED_STAKER_ROLE"]), p32[:1] or
        [_cr(susde, "hasRole(bytes32,address)", rb)])

    # ---- timelock ---------------------------------------------------------------------
    tl = owner
    md = rpc.read([Call(tl, "getMinDelay()", ("uint256",))])[0]
    delay = int(md.one())
    put("FR-U15", delay, md.provenance)
    tl_roles, p16 = roles(tl, ("PROPOSER_ROLE", "EXECUTOR_ROLE", "CANCELLER_ROLE"))
    put("FR-U16", tl_roles, p16)

    # ---- holder kinds and Safe getters -------------------------------------------------
    holders = sorted({h for d in (v2_roles, s_roles, tl_roles) for hs in d.values() for h in hs}
                     | {owner, v2_owner, rf})
    kinds = {h: holder_kind(rpc, h) for h in holders}
    safes = [h for h, (k, _) in kinds.items() if k == "multisig"]
    sres = rpc.read([x for h in safes for x in (Call(h, "getOwners()", ("address[]",)),
                                                Call(h, "getThreshold()", ("uint256",)))])
    safe_val = {h: {"owners": [o.lower() for o in sres[2 * i].one()],
                    "threshold": int(sres[2 * i + 1].one())} for i, h in enumerate(safes)}
    put("FR-U17", safe_val, [r.provenance for r in sres])

    # ---- EIP-1967 slots -------------------------------------------------------------
    slots = {c_: {k: rpc.storage(c_, s_) for k, s_ in EIP1967.items()}
             for c_ in (usde, susde, v2, oft)}
    proxied = {c_: v for c_, v in slots.items() if any(int(x, 16) for x in v.values())}
    put("FR-U18", slots, [AbsenceRead(contract=c_, method="eip1967_slot_read",
                                      evidence=json.dumps(v, sort_keys=True), block=rb)
                          for c_, v in slots.items()])

    # ---- reserve fund ---------------------------------------------------------------
    buffer_assets = sorted(set(assets) | {r.address for r in cfg.label_rows.values()
                                          if r.address != "none" and "buffer" in r.roles})
    decs = {a: int(r.one()) for a, r in zip(
        buffer_assets, rpc.read([Call(a, "decimals()", ("uint8",)) for a in buffer_assets]),
        strict=True)}
    rf_bal, prf = _balances(rpc, [rf], buffer_assets + [usde, susde])
    eth = rpc.read([Call(MULTICALL3, "getEthBalance(address)", ("uint256",), (_cs(rf),))])[0]
    put("FR-U19", {"balances": rf_bal.get(rf, {}), "eth": int(eth.one())}, prf + [eth.provenance])

    # ---- disclosures ------------------------------------------------------------------
    d = fetch_disclosures(disclosure_get)
    cats = {b["category"]: int(b["usdAmount"])
            for b in d["collateral_breakdown"]["body"]["breakdown"]}
    put("FR-U20", cats, d["collateral_breakdown"]["prov"])
    st = d["status"]["body"]
    put("FR-U21", {"backing_usd": str(st["totalBackingAssetsInUsd"]),
                   "reserve_fund_usd": str(st["totalReserveFundInUsd"]),
                   "supply_usd": str(st["totalTokenSupplyInUsd"]), "as_of": st["timestamp"]},
        d["status"]["prov"])
    put("FR-U22", d["por"]["body"]["lastUpdatedAt"], d["por"]["prov"])
    il = d["institutional_lending"]["body"]["totals"]
    put("FR-U34", {"lent_usd": str(il.get("lentUsd")),
                   "collateral_usd": str(il.get("collateralUsd")),
                   "overcollateralization_pct": str(il.get("overcollateralizationPct")),
                   "wa_recall_days": str(il.get("waRecallDays"))},
        d["institutional_lending"]["prov"])
    sc = d["stablecoin_collateral"]["body"]
    put("FR-U35", {"by_symbol": {k: str(v["usd_amount"]) for k, v in sc.items()},
                   "sum_usd": str(sum(Decimal(str(v["usd_amount"])) for v in sc.values()))},
        d["stablecoin_collateral"]["prov"])
    ba = d["backing_assets"]["body"]
    eth_entries = sorted({e["address"].lower() for s_ in ba["strategies"]
                          for cp in s_.get("counterparties", []) for a in cp.get("assets", [])
                          for e in (a.get("addressEntries") or [])
                          if e.get("chainSlug") == "ethereum" and str(e.get("address", ""))
                          .startswith("0x") and len(e["address"]) == 42})
    eth_by = {s_["strategy"]: str(sum((Decimal(str(a["value"]))
                                       for cp in s_.get("counterparties", [])
                                       for a in cp.get("assets", [])
                                       if a.get("chainSlug") == "ethereum"), Decimal(0)))
              for s_ in ba["strategies"]}
    locations = sorted({a["location"] for s_ in ba["strategies"]
                        for cp in s_.get("counterparties", []) for a in cp.get("assets", [])
                        if a.get("location")})
    # D16 (row 2): each location's total across all strategies (F2), and each basis
    # counterparty's hedge notional across the two basis strategies.
    loc_tot: dict[str, Decimal] = {}
    for s_ in ba["strategies"]:
        for cp in s_.get("counterparties", []):
            for a in cp.get("assets", []):
                if a.get("location"):
                    loc_tot[a["location"]] = loc_tot.get(a["location"], Decimal(0)) + \
                        Decimal(str(a["value"]))
    hedge = {}
    for s_ in ba["strategies"]:
        if s_["strategy"] in ("Crypto Basis", "Equity and RWA Basis"):
            for cp in s_.get("counterparties", []):
                hedge[cp["counterparty"]] = hedge.get(cp["counterparty"], Decimal(0)) + \
                    Decimal(str(cp["value"]))
    put("FR-U36", {"strategies": {s_["strategy"]: str(s_["value"]) for s_ in ba["strategies"]},
                   "ethereum_by_strategy": eth_by, "locations": locations,
                   "location_totals": {k: str(v) for k, v in sorted(loc_tot.items())},
                   "exchange_notional": {k: str(v) for k, v in sorted(hedge.items())},
                   "timestamp": ba["timestamp"], "ethereum_address_entries": eth_entries},
        d["backing_assets"]["prov"])
    fq = d["funding_quarterly"]["body"]
    lo = min(fq, key=lambda q: Decimal(str(q["value"])))
    put("FR-U37", {"quarter": lo["name"], "value_pct": str(lo["value"]),
                   "negative_quarter_observed": any(Decimal(str(q["value"])) < 0 for q in fq)},
        d["funding_quarterly"]["prov"])

    # ---- buffer groups (i), (ii), (iii) ------------------------------------------------
    b_i, p23 = _balances(rpc, custodians, buffer_assets)
    put("FR-U23", b_i, p23)
    group_ii = sorted(set(cfg.attestation_wallets.get("ethereum", [])) | set(eth_entries))
    b_ii, p24 = _balances(rpc, group_ii, buffer_assets)
    put("FR-U24", {"addresses": group_ii, "balances": b_ii, "decimals": decs}, p24)
    b_iii, p33 = _balances(rpc, [v2], buffer_assets)
    put("FR-U33", b_iii.get(v2, {}), p33)

    # ---- pools: the frozen set's pass once the first freeze exists (J2), else discovery -----
    floor = int(cfg.pool_set["floor_usd"])
    fs = fs_hash = None
    detectors = PoolDetectors(baseline_source="freeze_set_file",
                              baseline_note="no frozen set yet: the first freeze is owed")
    pool_rows, below = [], 0
    try:
        if cfg.frozen_set_path.exists():
            fs = json.loads(cfg.frozen_set_path.read_text(encoding="utf-8"))
            fs_hash = hashlib.sha256(cfg.frozen_set_path.read_bytes()).hexdigest()[:8]
            prior = load_prior(_BUNDLES, cfg.token, rb)
            prior_pools = ({q.address: {"tvl_at_par": q.tvl_at_par} for q in prior.pools}
                           if prior else {})
            pool_rows, below, detectors = build_pool_rows(rpc, cfg, fs, http_get, usde, set(),
                                                          prior_pools, rb)
            disc = pool_rows
            above = sorted(((q.address, q.tvl_at_par, list(q.paired_assets)) for q in pool_rows
                            if q.tvl_at_par >= floor), key=lambda x: -x[1])
        else:
            cands = fetch_candidates(http_get, ["factory-stable-ng"])
            disc = value_candidates(rpc, cands, usde, set(cfg.paired) | {usde})
            above = sorted(((q.address, q.tvl_at_par, list(q.paired_assets)) for q in disc
                            if q.tvl_at_par >= floor), key=lambda x: -x[1])
    except AssemblyStopFromDiscovery as exc:
        raise UsdeAdapterStop(str(exc)) from exc
    put("FR-U25", {"registry_classes": ["factory-stable-ng"], "discovered": len(disc),
                   "above_floor": [{"pool": a, "tvl_at_par": t, "paired": q} for a, t, q in above],
                   "frozen_set": ({"pools": [x["address"] for x in fs["pools"]],
                                   "freeze_block": fs["freeze_block"],
                                   "freeze_coverage": fs["freeze_coverage"],
                                   "set_file_hash": fs_hash} if fs else None)},
        [_cr(a, "balances(uint256)", rb) for a, _, _ in above] or
        [_cr(usde, "totalSupply()", rb)])
    off = read_share(usde)
    put("FR-U26", str(off.x) if off.x is not None else off.literal,
        AnalystSupplied(source=off.source, date=off.date))
    put("FR-U27", ("computed by the stress fold at run_block over the frozen set "
                   "(exit_depth.depth_curve, s = 0.02)" if fs else
                   "not yet runnable: the depth solver reads the frozen set, absent until "
                   "the first freeze"),
        [_cr(a, "balances(uint256)", rb) for a in (x["address"] for x in fs["pools"])]
        if fs else AbsenceRead(contract=usde, method="storage_slot_read",
                               evidence="no frozen set", block=rb))

    # ---- reference feeds (DET-54 gap column) ----------------------------------------------
    feeds = {f["symbol"]: f["feed"] for f in cfg.sheet.get("oracle_feed", [])}
    # A raw Chainlink feed answers latestRoundData(); an Aave CAPO adapter (the GHO
    # sheet's reused USDT / USDC rows) reverts there and answers latestAnswer().
    rounds = rpc.read([Call(f, "latestRoundData()", ("uint80", "int256", "uint256", "uint256",
                                                     "uint80")) for f in feeds.values()])
    answers = rpc.read([Call(f, "latestAnswer()", ("int256",)) for f in feeds.values()])
    ref, pref = {}, []
    for s_, r, a in zip(feeds, rounds, answers, strict=True):
        if r.ok:
            ref[s_] = {"method": "latestRoundData", "answer": int(r.value[1]),
                       "updated_at": int(r.value[3])}
            pref.append(r.provenance)
        elif a.ok:
            ref[s_] = {"method": "latestAnswer", "answer": int(a.one()), "updated_at": None}
            pref.append(a.provenance)
        else:
            raise UsdeAdapterStop(f"reference feed {feeds[s_]} ({s_}) answers neither read")
    put("FR-U28", ref, pref)

    # ---- selector scans ------------------------------------------------------------------
    v2_code, s_code = rpc.code(v2), rpc.code(susde)
    redeem_ok, seize_ok = _has_selector(v2_code, REDEEM_V2), _has_selector(s_code, SEIZE_SUSDE)
    put("FR-U29", redeem_ok, _cr(v2, REDEEM_V2, rb, ["selector_present"]))
    put("FR-U30", seize_ok, _cr(susde, SEIZE_SUSDE, rb, ["selector_present"]))
    codes = {c_: rpc.code(c_) for c_ in (usde, susde, v2)}
    oracle_hits = {c_: [s_ for s_ in ORACLE_SETTERS if _has_selector(code, s_)]
                   for c_, code in codes.items()}
    put("FR-U31", "none" if not any(oracle_hits.values()) else oracle_hits,
        [AbsenceRead(contract=c_, method="selector_absence_scan",
                     evidence="no oracle setter: " + ", ".join(ORACLE_SETTERS), block=rb)
         for c_ in codes])

    # ---- admin surface (Q12) -----------------------------------------------------------
    def arow(power, holder, prov, scope=(), reads=None, upgradeability=None, live=False,
             consumed=()):
        kind, dly = kinds.get(holder, (None, None)) if holder else ("none", None)
        if holder and kind is None:
            kind, dly = holder_kind(rpc, holder)
        dly = delay if kind == "timelock" else (0 if kind in ("eoa", "multisig", "none") else dly)
        return AdminRow(power=power, holder_address=holder, holder_type=kind,
                        delay_seconds=dly, delay_bucket=_bucket(dly),
                        upgradeability=upgradeability, scope=list(scope), provenance=prov,
                        reads=reads or {}, live_model_input=live, consumed_by=list(consumed))

    first = lambda xs: xs[0] if xs else None                            # noqa: E731
    admin = [
        arow("mint", owner, c[0].provenance, (usde, v2), {"minter": c[2].provenance}),
        arow("set_ceiling", v2_owner, g[1].provenance, (v2,), live=True,
             consumed=["stress.S3.capacity_redeem"]),
        arow("upgrade", None, AbsenceRead(contract=usde, method="eip1967_slot_read",
                                          evidence="EIP-1967 slots zero on USDe, sUSDe, V2, OFT",
                                          block=rb),
             upgradeability="proxy_upgradeable" if proxied else "immutable"),
        arow("pause", first(v2_roles["GATEKEEPER_ROLE"]),
             _cr(v2, "hasRole(bytes32,address)", rb, ["GATEKEEPER_ROLE"]), (v2,)),
        arow("freeze_asset", v2_owner, g[1].provenance, (v2,)),
        arow("blacklist_address", first(s_roles["BLACKLIST_MANAGER_ROLE"]),
             _cr(susde, "hasRole(bytes32,address)", rb, ["BLACKLIST_MANAGER_ROLE"]), (susde,)),
        arow("set_oracle", None, AbsenceRead(contract=usde, method="selector_absence_scan",
                                             evidence="no oracle setter on USDe, sUSDe, V2",
                                             block=rb)),
        arow("set_parameters", first(s_roles["DEFAULT_ADMIN_ROLE"]),
             _cr(susde, "hasRole(bytes32,address)", rb, ["DEFAULT_ADMIN_ROLE"]), (susde, v2),
             {f"collateral_manager:{h}": _cr(v2, "hasRole(bytes32,address)", rb,
                                              ["COLLATERAL_MANAGER_ROLE", h])
              for h in v2_roles["COLLATERAL_MANAGER_ROLE"]},
             live=True, consumed=["stress.S3.cooldown_branch"]),
        arow("seize", first(s_roles["DEFAULT_ADMIN_ROLE"]),
             _cr(susde, "hasRole(bytes32,address)", rb, ["DEFAULT_ADMIN_ROLE"]), (susde,)),
    ]

    # ---- the CDP-shaped fields: Q44's ruled empties ---------------------------------------
    raw = snapshot_set(d)
    bridge = Bridge(bridge_address=oft, amount=escrow, bridge_type="lock_and_mint",
                    reads={"amount": c[10].provenance,
                           "bridge_type": AnalystSupplied(source=cfg.bridges[0]["source"],
                                                          date=cfg.bridges[0]["date"])})
    supply = Supply(
        total_supply=total, supply_ruled=total, bridge_state="populated",
        bridge_disclosure=(f"one lock_and_mint escrow, the OFT adapter, holds {escrow} USDe "
                           "inside totalSupply (Q20)"),
        bridges=[bridge], origination_sum=total, residual=0,       # A-29: O = totalSupply()
        residual_unexplained=0,
        stabilizer_over_supply=Decimal(0),
        reads={"total_supply": c[3].provenance, "minter": c[2].provenance,
               "decimals": c[4].provenance})
    redemption = RedemptionPath(
        r1_path="module_on_chain", r2_who="whitelisted", r3_received=assets,
        r4_rate="face_value", r5_minimum="none",
        r6_gates=[{"kind": "capacity_limited", "param": "global_max_redeem_per_block"},
                  {"kind": "pausable", "param": None}],
        r7_capacity="min(synthetic.reads.FR-U09, synthetic.reads.FR-U35)",     # F1
        r8="enforceable_unless_paused (see R7)", r9_legal_claim="disclaimed",
        r10_provenance=_cr(v2, REDEEM_V2, rb, ["selector_present"]))
    from factory.run import static_metadata_of
    first_run = is_first_run(_BUNDLES, "USDe")
    bundle = Bundle(
        header=Header(token="USDe", run_block=rb, block_timestamp=rpc.block_timestamp,
                      run_start_time=rpc.run_start_time, first_run=first_run,
                      pipeline_version="0.1.0", sheet_hash=cfg.sheet["sheet_hash"],
                      frozen_set_hash=fs_hash, freeze_date=fs["freeze_date"] if fs else None,
                      raw_positions_hash=hashlib.sha256(raw.encode()).hexdigest()),
        markets=[], stabilizer=StabilizerBlock(operations=[], ceiling_aggregate=0,
                                               ceiling_aggregate_lineage=[]),
        supply=supply, nodes=[], oracle_rows=[], redemption_paths=[redemption],
        admin_surface=admin, lend_markets=[], pools=pool_rows, pool_detectors=detectors,
        offvenue_share=off, static_metadata=static_metadata_of(cfg),
        counts=Counts(mint_market_count=0, lend_market_count=cfg.lend.market_count_field,
                      below_floor_pool_count=below,
                      lend_market_count_note="no lend markets in this archetype (Q44)",
                      facilitator_count="n/a", gsm_count=0),
        attribution_method=cfg.sheet["attribution_method"],
        first_run_literals=FirstRunLiterals() if first_run else None,
        synthetic=SyntheticBlock(reads=dict(sorted(R.items()))))
    return {"bundle": bundle, "raw": raw, "disclosures": True, "decimals": decs,
            "kinds": kinds, "proxied": proxied, "group_ii": group_ii,
            "balances": {"i": b_i, "ii": b_ii, "iii": b_iii}, "seconds": time.perf_counter() - t0,
            "usd": {"i": _usd(b_i, decs), "ii": _usd(b_ii, decs), "iii": _usd(b_iii, decs)}}
