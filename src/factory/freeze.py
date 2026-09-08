"""B-3b: three-way reconciliation (DET-09), the pool-set freeze, DET-11 labeling.

The freeze is a one-time event per §5.6; later runs read the set file and run the
detector. Nothing here uses an aggregator's TVL as a selection input — R-16 makes
on-chain `pool.balances(i)` at par the only ranking basis, and the API/DefiLlama
figures are pointers and reconciliation legs only.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal

# Named implementer defaults / ruled constants -------------------------------
DUST_FLOOR_USD = 500_000  # §5.5
FREEZE_COVERAGE_TARGET = Decimal("0.95")  # §5.5, DET-29(a)
HEADLINE_K = Decimal("0.90")  # §5.5 headline subset
DISCOVERY_MISMATCH_LIMIT = Decimal("0.05")  # §5.5 / DET-09
T18_SHARE_THRESHOLD = Decimal("0.05")  # DET-11 / R-5

EXCLUSION_REASONS = {
    "non_market_contract",
    "volatile_collateral_circular",
    "tail_beyond_freeze_coverage",
    "added_since_freeze",
    # Interpretive extension, ruled 2026-09-04 (P-3.24 R-4); amendment-queued
    # for memo §5.4. A crvUSD/cvcrvUSD-type pool is the token against itself:
    # §2's "never its own backing" generalises to "never its own exit depth".
    "self_referential_wrapper",
    # DET-29(a)'s ruled string for pools recorded in excluded_at_freeze[]
    "below_dust_floor",
}


class DiscoveryMismatch(Exception):
    """DET-09 M > 5% — Level 3 T-13. Nothing downstream computes."""


class FreezeCoverageStop(Exception):
    """R-a3: coverage below target halts for Amin's R-20 waiver decision.

    Never self-issued: the run stops and presents the numbers.
    """

    def __init__(self, achieved: Decimal, discovery_total: int, tail: list[str]):
        self.achieved, self.discovery_total, self.tail = achieved, discovery_total, tail
        super().__init__(
            f"freeze_coverage {achieved:.4f} < {FREEZE_COVERAGE_TARGET} "
            f"— stop for R-20 waiver decision"
        )


@dataclass(frozen=True)
class ScopeDeclaration:
    """The single universe all three DET-09 legs measure (P-3.27).

    Recorded in the set file so M is auditable as a statement about a NAMED
    universe rather than an unqualified number.
    """

    description: str
    classes: tuple[str, ...]
    post_exclusion: bool = True
    par_eligibility: str = "paired_asset class + numeraire"


@dataclass(frozen=True)
class SourceTotal:
    """One leg of DET-09. `source_id` is recorded on the bundle."""

    source_id: str
    total: int


def reconcile(totals: list[SourceTotal]) -> Decimal:
    """DET-09: M = (max − min)/max over three source totals; > 5% ⇒ Level 3.

    Denominator is max — the stated choice (R-3); the median rule was rejected
    because sources 1 and 3 overlap.
    """
    if len(totals) != 3:
        raise ValueError(f"DET-09 requires exactly three source totals, got {len(totals)}")
    hi = max(t.total for t in totals)
    lo = min(t.total for t in totals)
    if hi == 0:
        raise DiscoveryMismatch("all discovery sources reported zero liquidity")
    m = (Decimal(hi - lo) / Decimal(hi)).quantize(Decimal("0.000001"))
    if m > DISCOVERY_MISMATCH_LIMIT:
        raise DiscoveryMismatch(
            f"M = {m} > {DISCOVERY_MISMATCH_LIMIT}: "
            + ", ".join(f"{t.source_id}={t.total}" for t in totals)
        )
    return m


@dataclass(frozen=True)
class ZeroedSide:
    """A pool side that contributed nothing to selection value, disclosed.

    Present-and-explained (P-3.26): a zeroed asset is never silently dropped.
    """

    address: str
    units: int
    par_eligibility: str = "none"


@dataclass(frozen=True)
class DiscoveredPool:
    """A pool as discovered, valued at par from on-chain balances (R-16),
    under the par-eligibility gate (P-3.26)."""

    address: str
    paired_assets: tuple[str, ...]
    tvl_at_par: int  # Σ eligible balances at par — never an API figure
    is_stabilizer_pool: bool = False
    zeroed_sides: tuple[ZeroedSide, ...] = ()


def par_value(
    coins: list[str],
    balances: list[int | None],
    decimals: list[int],
    eligible: set[str],
) -> tuple[int, list[ZeroedSide]]:
    """Par value of a pool under the eligibility gate (P-3.26, refined P-3.27).

    An asset is par-eligible iff it is the numeraire or carries a
    `[[paired_asset]]` row. **A section 4 node-label row grants NO par
    eligibility** — the classes are distinct (P-3.24 shape binding), and
    conflating them let cvcrvUSD (label `terminal`, unit price $0.000814) claim
    par at a 1,229x overstatement. Anything ineligible contributes ZERO and is
    disclosed as a zeroed side. No external price enters this path (R-16
    preserved, not patched).

    Callers pass `eligible = set(cfg.paired) | {numeraire}` — never the node set.
    """
    total, zeroed = 0, []
    for addr, bal, dec in zip(coins, balances, decimals, strict=True):
        if bal is None:
            continue
        units = bal // (10 ** dec)
        if addr in eligible:
            total += units
        else:
            zeroed.append(ZeroedSide(addr, units))
    return total, zeroed


@dataclass(frozen=True)
class ExcludedPool:
    address: str
    exclusion_reason: str


@dataclass(frozen=True)
class FrozenSet:
    """DET-29(a) set file. `member2_target` is null until the R-a1 refresh."""

    freeze_date: str
    freeze_block: int
    freeze_discovery_total: int
    freeze_coverage: Decimal
    pools: tuple[DiscoveredPool, ...]
    excluded: tuple[ExcludedPool, ...]
    chain_id: int = 1
    member2_target: str | None = None
    coverage_waiver: dict | None = None
    scope: ScopeDeclaration | None = None  # the declared DET-09 universe
    discovery_m: Decimal | None = None

    def k_subset(self, k: Decimal) -> tuple[DiscoveredPool, ...]:
        """DET-29(b): shortest prefix by tvl desc (ties: ascending address)
        whose cumulative tvl ≥ k × Σ_F tvl."""
        ranked = sorted(self.pools, key=lambda p: (-p.tvl_at_par, p.address))
        target = Decimal(sum(p.tvl_at_par for p in ranked)) * k
        run, out = 0, []
        for p in ranked:
            out.append(p)
            run += p.tvl_at_par
            if Decimal(run) >= target:
                break
        return tuple(out)


def classify_exclusions(
    discovered: list[DiscoveredPool],
    volatile_nodes: set[str],
    self_referential: set[str],
) -> list[ExcludedPool]:
    """§5.4 + DET-34: exactly one reason per excluded pool, each reason valid.

    `volatile_collateral_circular` is legal ONLY where the paired asset is a
    volatile collateral node of the token — a stablecoin-collateral pool
    carrying it is a fail (DET-34).
    """
    out: list[ExcludedPool] = []
    for p in discovered:
        if any(a in self_referential for a in p.paired_assets):
            out.append(ExcludedPool(p.address, "self_referential_wrapper"))
        elif any(a in volatile_nodes for a in p.paired_assets):
            out.append(ExcludedPool(p.address, "volatile_collateral_circular"))
    return out


def build_freeze(
    discovered: list[DiscoveredPool],
    excluded: list[ExcludedPool],
    freeze_date: str,
    freeze_block: int,
    r20_waiver: dict | None = None,
) -> FrozenSet:
    """Build the frozen set: exclusions out, floor applied (stabilizer pools
    exempt, P-4), then the shortest prefix reaching 95% coverage.

    Raises FreezeCoverageStop if the target is unreachable — R-a3, never a
    self-issued waiver.

    R-a3's SECOND HALF (P-4.10): the ruling does not end at the stop — it ends
    at the analyst's R-20 decision, and a granted waiver lets the freeze
    proceed. `r20_waiver` is that decision, `{date, reason, achieved_coverage}`,
    and it is carried onto the set so the file records WHY coverage is short
    rather than leaving a bare number to be rediscovered. Passing it is the
    only way past the stop; the module still cannot issue one itself.
    """
    gone = {e.address for e in excluded}
    eligible = [p for p in discovered if p.address not in gone]
    discovery_total = sum(p.tvl_at_par for p in eligible)

    # §5.5 dust floor; P-4: stabilizer pools are floor-exempt
    above = [p for p in eligible if p.tvl_at_par >= DUST_FLOOR_USD or p.is_stabilizer_pool]
    ranked = sorted(above, key=lambda p: (-p.tvl_at_par, p.address))

    target = Decimal(discovery_total) * FREEZE_COVERAGE_TARGET
    chosen, run = [], 0
    for p in ranked:
        chosen.append(p)
        run += p.tvl_at_par
        if Decimal(run) >= target:
            break

    # every stabilizer pool must be in F — DET-24, no permitted exclusion
    for p in above:
        if p.is_stabilizer_pool and p not in chosen:
            chosen.append(p)
            run += p.tvl_at_par

    coverage = (Decimal(run) / Decimal(discovery_total)).quantize(Decimal("0.0001"))
    if coverage < FREEZE_COVERAGE_TARGET:
        tail = [p.address for p in eligible if p not in chosen]
        if r20_waiver is None:
            raise FreezeCoverageStop(coverage, discovery_total, tail)

    below = {p.address for p in eligible if p not in above}
    tail_excluded = [
        ExcludedPool(p.address,
                     "below_dust_floor" if p.address in below else "tail_beyond_freeze_coverage")
        for p in eligible
        if p not in chosen and p.address not in gone
    ]
    return FrozenSet(
        freeze_date=freeze_date,
        freeze_block=freeze_block,
        freeze_discovery_total=discovery_total,
        freeze_coverage=coverage,
        pools=tuple(chosen),
        excluded=tuple(excluded) + tuple(tail_excluded),
    )


def discover_and_freeze(
    legs: list[SourceTotal],
    discovered: list[DiscoveredPool],
    excluded: list[ExcludedPool],
    freeze_date: str,
    freeze_block: int,
    scope: ScopeDeclaration,
) -> tuple[Decimal, FrozenSet]:
    """DET-09 GATES the freeze structurally (D1, P-3.27).

    `reconcile` raises on a mismatch, so every line below it is unreachable —
    the freeze cannot be built past an ungated T-13. This is deliberately an
    orchestration function rather than a caller convention: the second
    execution proved a caller convention can be, and was, warned past.
    """
    m = reconcile(legs)  # raises DiscoveryMismatch => nothing downstream computes
    fs = build_freeze(discovered, excluded, freeze_date, freeze_block)
    return m, replace(fs, scope=scope, discovery_m=m)


@dataclass(frozen=True)
class PairedAssetLabel:
    address: str
    label: str  # one of the four, or "unlabeled"
    share_of_exit_depth: Decimal
    level: int | None = None  # T-18 level where unlabeled
    flags: tuple[str, ...] = field(default_factory=tuple)


def label_paired_assets(
    modeled: tuple[DiscoveredPool, ...],
    depth_by_pool: dict[str, int],
    paired_config: dict[str, str],
) -> list[PairedAssetLabel]:
    """DET-11 / R-5: label each paired asset; route unlabeled ones by their
    share q of modeled exit depth — q ≥ 5% ⇒ Level 2 (no report), q < 5% ⇒
    Level 1 with the pool still modeled.

    q is a share of EXIT DEPTH on the K-subset, not of TVL (DET-11's wording).
    """
    total_depth = sum(depth_by_pool.get(p.address, 0) for p in modeled)
    by_asset: dict[str, Decimal] = {}
    for p in modeled:
        d = Decimal(depth_by_pool.get(p.address, 0))
        if not p.paired_assets:
            continue
        # A pool's depth is ONE number; it is partitioned across that pool's
        # paired assets rather than credited whole to each (F3, P-3.26).
        # Named implementer default: equal split, since the eligible-balance
        # split is unavailable until the Step-6 solver gives per-asset depth.
        share = d / Decimal(len(p.paired_assets))
        for a in p.paired_assets:
            by_asset[a] = by_asset.get(a, Decimal(0)) + share

    out: list[PairedAssetLabel] = []
    for asset, depth in sorted(by_asset.items()):
        q = (depth / Decimal(total_depth)) if total_depth else Decimal(0)
        if asset in paired_config:
            out.append(PairedAssetLabel(asset, paired_config[asset], q))
        else:
            level = 2 if q >= T18_SHARE_THRESHOLD else 1
            out.append(
                PairedAssetLabel(asset, "unlabeled", q, level, (f"T-18 level {level}",))
            )
    return out
