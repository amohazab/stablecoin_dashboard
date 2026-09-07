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

from decimal import Decimal

from pydantic import BaseModel, ValidationError

from factory.freeze import (
    DUST_FLOOR_USD,
    DiscoveredPool,
    ZeroedSide,
    par_value,
)
from factory.rpc import Call

# The seam P-3.43 anticipated turned out to be zero: `freeze.py` splits pure
# computation from I/O already, so `par_value`, `DUST_FLOOR_USD` and the
# exclusion vocabulary import as they stand. `build_freeze` is deliberately NOT
# imported — it SELECTS, and a per-run pass must never re-select (memo 5.6:
# "detector flags never auto-update the set").

CURVE_POOLS_URL = "https://api.curve.finance/api/getPools/ethereum/{registry}"


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


__all__ = ["CURVE_POOLS_URL", "AssemblyStopFromDiscovery", "PoolsResponse",
           "fetch_candidates", "value_candidates", "still_enumerated",
           "DUST_FLOOR_USD", "ZeroedSide", "Decimal"]
