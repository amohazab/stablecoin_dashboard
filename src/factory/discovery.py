"""1b: the per-run pool discovery pass — memo 5.6's second half, finally built.

Memo 5.6 rules it directly: *"Per run: read the frozen pools' state;
additionally run full discovery and a detector that flags (i) a new pool above
the dust floor not in the frozen set, (ii) a frozen pool fallen below the
floor, (iii) any frozen pool with TVL change > 50% since the last run."*
DET-10(c)(d)(e) enforce that ruling. Until now an ordinary run never touched a
pool: the frozen set was opened only to hash its bytes (P-3.43 finding (ii)),
and the enumeration that PRODUCED the signed set file was never in the tracked
tree. This module is that missing producer.

ROUTE A (ruled P-3.43): the freeze's own method — the Curve API catalog is the
POINTER, the chain is the VERDICT. Route B (walking `pool_list(i)` across all
six factories, ~5,000-7,200 reads) was rejected on cost for an every-run pass.

FAILURE ROUTE (ruled P-3.46 R1). A shape change, an empty signed class, and a
transport failure all raise `AssemblyStop`, which halts the token BEFORE
analysis — memo 8.1.1's Level 3 shape: no bundle, no promotion, nothing
published. **No trigger ID accompanies it, because none exists**: the printed
T-01..T-27 table has no shape-change trigger, and DET-12 halts the pipeline on
any runtime table that differs from the printed one, so inventing one is not an
implementer's to make. The brief's schema/shape-change hard gate (brief line
80, scoped at line 43 to scraped transparency dashboards) has no trigger and no
DET owner; that is on the rubric-amendment queue and becomes load-bearing at
step 10 (USDe). P-3.43 ruling 2 recorded a DET-85 / T-25 route; that route does
not exist, because discovery runs in `assemble()` before `run_harness` is ever
called — see P-3.43-A1.
"""

from __future__ import annotations

import json
import pathlib
from decimal import Decimal

from pydantic import BaseModel, ValidationError

from factory.freeze import (
    DUST_FLOOR_USD,
    DiscoveredPool,
    ZeroedSide,
    par_value,
)
from factory.logbook import load_prior
from factory.provenance import AbsenceRead, ContractRead
from factory.rpc import Call
from factory.schema import PoolDetectors, PoolRow, ZeroedSideRow

# The seam P-3.43 anticipated turned out to be zero: `freeze.py` splits pure
# computation from I/O already, so `par_value`, `DUST_FLOOR_USD` and the
# exclusion vocabulary import as they stand. `build_freeze` is deliberately NOT
# imported — it SELECTS, and a per-run pass must never re-select (memo 5.6:
# "detector flags never auto-update the set").

CURVE_POOLS_URL = "https://api.curve.finance/api/getPools/ethereum/{registry}"


def catalog_get(url: str) -> dict:
    """The CATALOG transport - one argument, a plain GET.

    P-4.11: moved here from `run.py`, because the catalog is this module's and
    both adapters need it. It is NOT the log pointer's transport, which takes
    `(url, params)`; handing one to the other is what broke GHO's first pool
    pass. Two transports, two shapes, named apart. `requests` is already a
    declared dependency (pyproject), so no lockfile change is involved.
    """
    import requests
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    return resp.json()


class AssemblyStopFromDiscovery(Exception):
    """Internal marker; `run.py` re-raises as `AssemblyStop`."""


# --------------------------------------------------------------- pointer ----


class CoinEntry(BaseModel, extra="ignore"):
    address: str
    decimals: int | str


class PoolEntry(BaseModel, extra="ignore"):
    address: str
    coins: list[CoinEntry]


class PoolData(BaseModel, extra="ignore"):
    poolData: list[PoolEntry]


class PoolsResponse(BaseModel, extra="ignore"):
    """`extra="ignore"` on purpose: the Curve API adds fields routinely and the
    freeze already tolerated that. A shape change is a field this model
    REQUIRES going missing or changing type — not a field being added."""

    data: PoolData


def fetch_candidates(http_get, scope_classes: list[str]) -> dict[str, PoolEntry]:
    """Pointer fetch over THE DECLARED SCOPE, not over every signed root.

    `scope_classes` is the set file's own `scope.classes` — the named universe
    the freeze measured (`ScopeDeclaration`, P-3.27). Reading a wider universe
    per run than the freeze read would make every pool in the extra classes
    look `added_since_freeze` forever: the six signed pool-factory roots span
    183 crvUSD pools, while the freeze's declared stableswap scope
    (`factory-crvusd`, `factory-stable-ng`, `factory`) spans the 103 it
    actually froze. Same universe, or the detector is noise.

    An EMPTY `poolData` for a class in the declared scope is a shape change,
    not a quiet zero (P-3.46 R1): a class is in scope precisely because it held
    crvUSD pools at the freeze.
    """
    out: dict[str, PoolEntry] = {}
    for registry in scope_classes:
        url = CURVE_POOLS_URL.format(registry=registry)
        try:
            payload = http_get(url)
        except Exception as exc:                      # transport, per R1
            raise AssemblyStopFromDiscovery(
                f"pointer source unavailable for registry class {registry!r}: "
                f"{type(exc).__name__}. Halts before analysis; no trigger ID "
                "exists for this condition (P-3.46 R1)."
            ) from exc
        try:
            parsed = PoolsResponse(**payload)
        except ValidationError as exc:
            raise AssemblyStopFromDiscovery(
                f"pointer source SHAPE CHANGE for registry class {registry!r}: "
                f"{exc.error_count()} validation error(s). Quarantine rather "
                "than publish garbage (brief hard gate); halts before analysis."
            ) from exc
        rows = parsed.data.poolData
        if not rows:
            raise AssemblyStopFromDiscovery(
                f"registry class {registry!r} is in the frozen set's declared "
                "scope but returned an EMPTY pool list. Treated as a shape "
                "change, not a zero (P-3.46 R1)."
            )
        for row in rows:
            out[row.address.lower()] = row
    return out


# ----------------------------------------------------------------- chain ----


def value_candidates(rpc, candidates: dict[str, PoolEntry], token: str,
                     eligible: set[str]) -> list[DiscoveredPool]:
    """The chain is the verdict: par value from on-chain `balances(i)` under the
    SAME par-eligibility gate the freeze used (`freeze.par_value`, P-3.26/27).
    No external price enters this path; R-16 preserved, not patched.
    """
    holders = {a: e for a, e in candidates.items()
               if any(c.address.lower() == token for c in e.coins)}
    out: list[DiscoveredPool] = []
    for addr, entry in holders.items():
        coins = [c.address.lower() for c in entry.coins]
        decs = [int(c.decimals) for c in entry.coins]
        res = rpc.read([Call(addr, "balances(uint256)", ("uint256",), (i,))
                        for i in range(len(coins))])
        bals = [int(r.one()) if r.ok else None for r in res]
        tvl, zeroed = par_value(coins, bals, decs, eligible)
        out.append(DiscoveredPool(address=addr, paired_assets=tuple(
            c for c in coins if c != token), tvl_at_par=tvl,
            zeroed_sides=tuple(zeroed)))
    return sorted(out, key=lambda p: p.address)


def still_enumerated(rpc, pool: str, factory: str, index: int) -> bool:
    """DET-10(d)-ii's disappearance test, FACTORY-SIDE (ruled 2026-09-07).

    `factory.pool_list(index)` at `run_block` must equal `pool`. Anything else
    - a different address, a revert, or `pool_count() <= index` - is the
    disappearance event. This is the rubric's letter, "absent from on-chain
    factory enumeration": the factory is asked what it lists, rather than the
    pool being asked to vouch for itself.

    It replaces an earlier `pool.factory()` design that was signed and then
    failed on real data: probed at block 25927789, `factory()` REVERTS on 3 of
    the 5 frozen pools, whose classes carry `derivation_route = "candidate ->
    closure"` in the signed roots. Treating a revert as disappearance would
    have marked 3 of 5 gone on the first run and fired T-10 Level 2 on frxUSD
    at 17.5% of freeze coverage - a false positive that would have quarantined
    the report. One code path now covers all five, including the two that do
    answer `factory()`.

    Sound because `pool_list` is APPEND-ONLY in all three declared-scope
    factories, verified from their verified source rather than from recall -
    see the `[[frozen_pool_index]]` block in `config/discovery_roots.toml` for
    the line-by-line reading. An index is stable for the life of the factory.

    Two reads per pool: `pool_count()` to bound the index, then
    `pool_list(index)`. API absence is DET-09 territory and is NOT this event.
    """
    n = rpc.read([Call(factory, "pool_count()", ("uint256",))])[0]
    if not n.ok or int(n.one()) <= index:
        return False
    r = rpc.read([Call(factory, "pool_list(uint256)", ("address",), (index,))])[0]
    return bool(r.ok and r.one().lower() == pool.lower())


# ---------------------------------------------------- the per-run pool pass --
# EXTRACTED FROM `run.py` (P-4.11, ruled at P-3.46 follow-up 5 and forced once a
# second adapter needed it - P-3.04's "extract from two real implementations,
# never guessed from one"). `run.py` imports `gho.py`, so a shared function
# could not live there; `discovery.py` is the module BOTH adapters already
# import, so it is the owner rather than a new one.
#
# EXTRACTION NOTES - every place the old code named crvUSD, and what it takes
# now. Nothing else changed while it moved:
#   1. the `CRVUSD` module constant            -> the `numeraire` argument
#   2. `{o.paired_pool_address for o in ops}`  -> the `stabilizer_pools` argument
#      (crvUSD passes its keeper pools; GHO has no stabilizer and passes set())
#   3. `run.py`'s `_cr(...)` helper            -> `_cr_local` here, identical
#      output for this call (`args=()` and `args=[]` both emit `args=[]`)
#   4. `raise AssemblyStop(...)`               -> `AssemblyStopFromDiscovery`,
#      which every caller already re-raises as `AssemblyStop`
#   5. `repo / BUNDLES` in the ratios helper   -> the `bundles_dir` argument
# `cfg.paired`, `cfg.frozen_pool_index`, `cfg.root(...)` and `fs["scope"]` were
# already Config- or set-file-carried and are untouched.


def _cr_local(contract: str, fn: str, block: int) -> ContractRead:
    return ContractRead(source_contract=contract.lower(), function=fn, args=[],
                        block=block)


def build_pool_rows(rpc, cfg, fs: dict, http_get, numeraire: str,
                    stabilizer_pools: set[str], prior_pools: dict[str, dict],
                    rb: int) -> tuple[list, int, PoolDetectors]:
    """memo 5.6's second half for any token: the frozen set's state plus full
    discovery plus the three detectors. Returns `(pool_rows, below_floor_count,
    detectors)`."""
    # ---- per-run pool discovery (1b): memo 5.6's second half ----------------
    # Route A (P-3.43): the Curve catalog is the pointer, the chain is the
    # verdict. Runs AFTER the stabilizer block because DET-24 forces every
    # keeper pool into F and the rows carry `is_stabilizer_pool`.
    fs_pools = {q["address"].lower(): q for q in fs["pools"]}
    fs_excluded = {q["address"].lower(): q["exclusion_reason"] for q in fs["excluded"]}
    fs_total = int(fs["freeze_discovery_total"])
    eligible = set(cfg.paired) | {numeraire}

    # No try/except here any more: both callees already raise
    # `AssemblyStopFromDiscovery`, and `run.py`'s wrapper caught it only to
    # re-raise as `AssemblyStop`. Inside this module the raise IS the route.
    cands = fetch_candidates(http_get, fs['scope']['classes'])
    discovered = value_candidates(rpc, cands, numeraire, eligible)

    pool_rows, below_floor_count = [], 0
    seen = set()
    for d in discovered:
        seen.add(d.address)
        in_f = d.address in fs_pools
        if not in_f and d.tvl_at_par < DUST_FLOOR_USD:
            below_floor_count += 1          # counted, not listed (P-3.43)
            continue
        # R2 (P-3.46): "new" means the freeze did not know it, or knew it and
        # excluded it ONLY for size. A structural freeze-time exclusion
        # (self_referential_wrapper, volatile_collateral_circular, tail) is
        # carried and is NOT new - a signed exclusion must not re-flag weekly.
        reason = None
        if not in_f:
            prior_reason = fs_excluded.get(d.address)
            reason = ("added_since_freeze"
                      if prior_reason in (None, "below_dust_floor")
                      else prior_reason)
        pool_rows.append(PoolRow(
            address=d.address, in_frozen_set=in_f,
            paired_assets=list(d.paired_assets),
            freeze_tvl=int(fs_pools[d.address]["tvl_at_par"]) if in_f else None,
            tvl_at_par=d.tvl_at_par,
            ratio_to_frozen_coverage=Decimal(d.tvl_at_par) / Decimal(fs_total),
            is_stabilizer_pool=d.address in stabilizer_pools,
            exclusion_reason=reason,
            zeroed_sides=[ZeroedSideRow(address=z.address, units=z.units)
                          for z in d.zeroed_sides],
            reads={"balances": _cr_local(d.address, "balances(uint256)", rb)}))

    # A frozen pool the pointer no longer lists still gets its row: (b)'s
    # exact-equality membership must hold and (d)-ii evaluates FROM the row
    # (P-3.46 R5). Its disappearance is an annotation, not an omission.
    for addr, q in fs_pools.items():
        if addr in seen:
            continue
        pool_rows.append(PoolRow(
            address=addr, in_frozen_set=True, paired_assets=list(q["paired"]),
            freeze_tvl=int(q["tvl_at_par"]), tvl_at_par=0,
            ratio_to_frozen_coverage=Decimal(0),
            is_stabilizer_pool=addr in stabilizer_pools,
            annotations=["absent from the pointer source this run"],
            reads={"balances": AbsenceRead(contract=addr,
                                           method="selector_absence_scan",
                                           evidence="not listed by the pointer",
                                           block=rb)}))

    # Disappearance, factory-side (ruled 2026-09-07): each frozen pool's signed
    # `pool_list` index must still hold that pool. Uniform on all five - one
    # code path, and it is the rubric's letter rather than the pool's
    # self-report. A frozen pool with no signed index row is a CONFIG DEFECT,
    # not a runtime state: present config or no run.
    pins = {q["pool"].lower(): q for q in cfg.frozen_pool_index}
    for row in pool_rows:
        if not row.in_frozen_set:
            continue
        pin = pins.get(row.address)
        if pin is None:
            raise AssemblyStopFromDiscovery(
                f"no [[frozen_pool_index]] row for frozen pool {row.address}; "
                "DET-10(d)-ii's factory-side test cannot be evaluated. Present "
                "config or no run (ruled 2026-09-07).")
        fac = cfg.root(pin["factory_root"]).address
        if not still_enumerated(rpc, row.address, fac, int(pin["index"])):
            row.annotations.append(
                f"disappeared: {pin['factory_root']}.pool_list({pin['index']}) "
                "no longer holds it")
    pool_rows.sort(key=lambda r: r.address)
    return pool_rows, below_floor_count, detectors(pool_rows, prior_pools, fs_pools)


def detectors(rows: list[PoolRow], prior_pools: dict[str, dict],
               fs_pools: dict[str, dict]) -> PoolDetectors:
    """DET-10(c), computed from `pools[]` alone — no second read of anything.

    Named implementer defaults (P-3.43):
      * the 10% denominator is the set file's `freeze_discovery_total`, held
        fixed between refreshes so the threshold does not move weekly. It is
        already baked into every row's `ratio_to_frozen_coverage`.
      * the TVL-change baseline is the PRIOR RUN's per-pool `tvl_at_par`,
        falling back to the set file's `freeze_tvl` when the prior carries no
        `pools[]`. True exactly once — the first run after this field lands —
        and DISCLOSED via `baseline_source`, never silent.

    The below-floor list reports a frozen pool under the floor even when that
    pool is floor-EXEMPT at selection (memo 5.5 / P-4 exempt stabilizer pools).
    The exemption is a SELECTION rule; the detector is a disclosure, and (e)
    gives below-floor detections no consequence beyond disclosure, so reporting
    it costs nothing and hides nothing. All five of crvUSD's frozen pools are
    keeper pools (P-3.28), which is why this is stated rather than assumed.
    """
    src = "prior_bundle" if prior_pools else "freeze_set_file"
    note = None if prior_pools else (
        "no prior pools[] — last-run figures fall back to the set file's "
        "freeze_tvl; true this run only (P-3.43)")

    new_above, below, moved = [], [], []
    for r in rows:
        if not r.in_frozen_set:
            if (r.exclusion_reason == "added_since_freeze"
                    and r.tvl_at_par >= DUST_FLOOR_USD):
                new_above.append(r.address)
            continue
        if r.tvl_at_par < DUST_FLOOR_USD:
            below.append(r.address)
        base = (int(prior_pools[r.address]["tvl_at_par"])
                if r.address in prior_pools else (r.freeze_tvl or 0))
        if base and abs(Decimal(r.tvl_at_par - base)) / Decimal(base) > Decimal("0.50"):
            moved.append(r.address)

    # DET-10(e): every detection is disclosed on its row, or (e) fails.
    by_addr = {r.address: r for r in rows}
    for addr in new_above:
        by_addr[addr].annotations.append("detector: new pool above the dust floor")
    for addr in below:
        by_addr[addr].annotations.append("detector: frozen pool below the dust floor")
    for addr in moved:
        by_addr[addr].annotations.append("detector: TVL change > 50% vs baseline")

    return PoolDetectors(
        new_pool_above_floor=sorted(new_above),
        frozen_pool_below_floor=sorted(below),
        frozen_pool_tvl_change_gt_50pct=sorted(moved),
        baseline_source=src, baseline_note=note)


def fs_members(fs_path: pathlib.Path) -> set[str]:
    fs = json.loads(fs_path.read_text(encoding="utf-8"))
    return {q["address"].lower() for q in fs["pools"]}


def last_run_ratios(bundles_dir: pathlib.Path, token: str,
                    fs_path: pathlib.Path, run_block: int) -> dict[str, Decimal]:
    """DET-10(d)-ii's "last-run share", with its NAMED one-time fallback.

    Prior bundle's `pools[]` where it has one; otherwise the set file's
    `freeze_tvl` over `freeze_discovery_total`. The fallback is true exactly
    once - for the first run whose prior predates `pools[]` - and the bundle
    discloses which was used via `pool_detectors.baseline_source` (P-3.43).
    """
    prior = load_prior(bundles_dir, token, run_block)
    if prior is not None and prior.pools:
        return {p.address: p.ratio_to_frozen_coverage for p in prior.pools}
    fs = json.loads(fs_path.read_text(encoding="utf-8"))
    total = Decimal(int(fs["freeze_discovery_total"]))
    return {q["address"].lower(): Decimal(int(q["tvl_at_par"])) / total
            for q in fs["pools"]}


__all__ = ["CURVE_POOLS_URL", "AssemblyStopFromDiscovery", "PoolsResponse",
           "build_pool_rows", "detectors", "fetch_candidates", "fs_members",
           "last_run_ratios", "still_enumerated", "value_candidates",
           "DUST_FLOOR_USD", "ZeroedSide", "Decimal"]
