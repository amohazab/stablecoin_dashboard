"""B-4b: the crash-path liquidation model, band-linear (R11), and the cells.

PURE. Every input is already in the artifact or the bundle by the time this
runs: the band union and per-position ticks from `LlammaState` (B-4a), the
positions from the raw dump whose hash was asserted at fold, the per-node
sell-side bound from the sheet (B-3b), the per-market `liquidation_discount`
from the Controller (B-4a's split).

THE BAND RELATION IS READ, NEVER COMPUTED. From the verified `LLAMMA - crvUSD
AMM` source, `_p_oracle_up`'s own comment (line 368 in the 0.3.7 build):

    # p_oracle_up(n) = p_base * ((A - 1) / A) ** n
    # p_oracle_down(n) = p_base * ((A - 1) / A) ** (n + 1) = p_oracle_up(n+1)

and `p_oracle_down(n)` returns `self._p_oracle_up(n + 1)` (line 465). So a
band's price interval is `[p_oracle_up(n+1), p_oracle_up(n)]` with BOTH
endpoints read from the chain. The exp implementation, its solmate constants
and `LOG_A_RATIO` are not ported: porting an exp is the one piece of this work
with no exact-reproduction guarantee, and reading removes the need. The three
deployed compiler versions (0.3.7 / 0.3.9 / 0.3.10) carry the relation
identically, checked line by line.

TWO NAMED SIMPLIFICATIONS, both R11's, both in `assumptions`:

  * a position's collateral is allocated across its bands IN PROPORTION TO
    EACH BAND'S RECORDED `y` (R-B4.15). Per-user band shares are not read —
    that is 514 x N calls and fails R11's gate — so a position sharing a band
    is assumed to hold that band's own mix. The first cut spread collateral
    evenly and handed already-converted positions their crvUSD leg twice.
  * conversion inside a crossed band is LINEAR IN PRICE, so its average
    execution price is the interval's midpoint. The AMM's own curve is not
    linear; this is the "band-linear" R11 ruled, and the direction of the
    error is not claimed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

ONE = 10 ** 18

BAND_LINEAR_LITERAL = (
    "crash-path conversion modeled band-linear (P-6.01 R11): a position's "
    "collateral is allocated across its bands in proportion to each band's "
    "recorded `y` (P-6.09 R-B4.15) - per-user band shares are not read - and "
    "conversion inside a crossed band is linear in price at the interval "
    "midpoint. Band prices are READ (`p_oracle_up(n)`, `p_oracle_up(n+1)`), "
    "never computed; LLAMMA's own curve inside a band is not reproduced."
)
UNDEFINED_RATIO_LITERAL = (
    "exit depth exhausted at this LP-flight level - ratio undefined (infinity)"
)
CAPACITY_LITERAL = (
    "absorption = Σ_nodes sell_side_capacity × shocked price, in crvUSD base "
    "units (P-6.08 R-B4.11). PegKeeper `effective` headroom is metric 4's "
    "mechanism trajectory and is NOT absorption — a keeper providing crvUSD "
    "into a crvUSD/stable pool does not buy collateral from a liquidator; "
    "DET-23(c) and DET-25 forbid `stabilizer_*` in the metric-1/2/3 and "
    "forced-sell lineages. Band conversion is uncapacitated."
)


@dataclass(frozen=True)
class Position:
    user: str
    market: str                  # controller address
    amm: str
    collateral: int              # scaled to 18 dp by the market's `decimals`
    debt: int                    # net debt, crvUSD base units (DET-06 floored)
    n1: int
    n2: int
    x_pos: int = 0               # `stablecoin_in_position`: the crvUSD leg


@dataclass(frozen=True)
class BandPrices:
    """`p_up[n]` for every band of a market, INCLUDING the +1 boundary bands.

    `down(n)` is `up(n + 1)` by the source's own identity, so a band whose
    upper neighbour was not read is a hole, and a hole is a stop rather than
    an interpolation.
    """

    up: dict[int, int]

    def interval(self, n: int) -> tuple[int, int]:
        lo, hi = self.up.get(n + 1), self.up.get(n)
        if lo is None or hi is None:
            raise KeyError(f"band {n}: price interval unread ({lo}, {hi})")
        return lo, hi


def allocate(p: Position, bands: dict[int, tuple[int, int]]) -> dict[int, int]:
    """R-B4.15: the position's collateral across its bands, PROPORTIONAL TO
    EACH BAND'S RECORDED `y`, not spread evenly.

    A band holding no collateral carries none of the position's — which is the
    whole point: a position already partly soft-liquidated sits in bands whose
    `y` has gone to crvUSD, and an even spread would hand it that leg twice.

    NAMED APPROXIMATION: per-USER band shares are not read (LLAMMA exposes
    them only through `get_sum_xy`-class calls per user per band, which is
    514 × N reads and fails R11's gate). The allocation is proportional to the
    BAND TOTALS, so a position sharing a band with others is assumed to hold
    the same mix that band holds.
    """
    ns = list(range(p.n1, p.n2 + 1))
    weights = {n: bands.get(n, (0, 0))[1] for n in ns}
    total = sum(weights.values())
    if total == 0:                       # every band is fully crvUSD already
        return {n: 0 for n in ns}
    out, given = {}, 0
    for n in ns[:-1]:
        out[n] = p.collateral * weights[n] // total
        given += out[n]
    out[ns[-1]] = p.collateral - given   # the remainder, to the lowest band
    return out


def convert_position(p: Position, prices: BandPrices, p_shocked: int,
                     bands: dict[int, tuple[int, int]] | None = None
                     ) -> tuple[int, int]:
    """`(crvusd_from_conversion, collateral_remaining)` at the shocked oracle.

    As the oracle falls, LLAMMA converts collateral to crvUSD from the top
    band down. A band whose whole interval sits at or above `p_shocked` is
    fully crossed; the band containing `p_shocked` is partial; bands below are
    untouched. Integer floor throughout.
    """
    if bands is None:                    # the pre-R-B4.15 even spread, tests only
        n_bands = p.n2 - p.n1 + 1
        per = p.collateral // n_bands
        alloc = {n: per for n in range(p.n1, p.n2 + 1)}
        alloc[p.n1] += p.collateral - per * n_bands
    else:
        alloc = allocate(p, bands)
    crvusd, left = 0, 0
    for n in range(p.n1, p.n2 + 1):
        y = alloc[n]
        lo, hi = prices.interval(n)
        if p_shocked >= hi:                              # untouched, still collateral
            left += y
        elif p_shocked <= lo:                            # fully crossed
            crvusd += y * ((lo + hi) // 2) // ONE
        else:                                            # the partial band
            frac_num, frac_den = hi - p_shocked, hi - lo
            converted = y * frac_num // frac_den
            crvusd += converted * ((p_shocked + hi) // 2) // ONE
            left += y - converted
    return crvusd, left


def position_value(p: Position, prices: BandPrices, p_shocked: int,
                   bands: dict[int, tuple[int, int]] | None = None) -> int:
    """Post-shock value in crvUSD base units: converted crvUSD + what is left,
    marked at the shocked oracle, PLUS the position's own crvUSD leg.

    `x_pos` is the position's `stablecoin_in_position` — crvUSD it already
    holds inside the AMM because it has been soft-liquidated before this run.
    It is value, it is already in crvUSD, and the shock does not touch it.
    """
    crvusd, left = convert_position(p, prices, p_shocked, bands)
    return crvusd + left * p_shocked // ONE + p.x_pos


def is_eligible(value: int, debt: int, liquidation_discount: int) -> bool:
    """The Controller's hard-liquidation condition: value discounted by the
    market's own `liquidation_discount` no longer covers the debt."""
    return value * (ONE - liquidation_discount) // ONE < debt


def run_cell(positions: list[Position], prices: dict[str, BandPrices],
             shocked: dict[str, int], discount: dict[str, int],
             capacity: dict[str, int],
             bands: dict[str, dict[int, tuple[int, int]]] | None = None) -> dict:
    """One cell's crash path. Returns the aggregates DET-39/40 consume.

    Absorption is ASCENDING BY CR (R12's named default) and per NODE: a
    position's collateral can only be sold into its own asset's market, so
    each market's positions draw on that node's bound and no other.
    """
    rows = []
    converted_total = 0
    for p in positions:
        crv, _left = convert_position(p, prices[p.amm], shocked[p.market],
                                      (bands or {}).get(p.amm))
        converted_total += crv
        v = position_value(p, prices[p.amm], shocked[p.market],
                           (bands or {}).get(p.amm))
        cr = Decimal(v) / Decimal(p.debt) if p.debt else Decimal(0)
        rows.append({"p": p, "value": v, "cr": cr,
                     "eligible": is_eligible(v, p.debt, discount[p.market])})
    left = dict(capacity)
    bad_debt, absorbed, forced = 0, [], 0
    for row in sorted(rows, key=lambda r: r["cr"]):
        if not row["eligible"]:
            continue
        p, v = row["p"], row["value"]
        if left.get(p.market, 0) >= v:
            left[p.market] -= v
            absorbed.append(row)
            if v < p.debt:
                bad_debt += p.debt - v
        elif row["cr"] < 1:
            bad_debt += p.debt - v
            forced += 1
    gone = {id(r["p"]) for r in absorbed}
    rem_v = sum(r["value"] for r in rows if id(r["p"]) not in gone)
    rem_d = sum(r["p"].debt for r in rows if id(r["p"]) not in gone)
    return {"rows": rows, "bad_debt": bad_debt, "absorbed": len(absorbed),
            # R-B4.18: crvUSD realised in CROSSED bands, at the band price.
            # EMA_lag's counterfactual erodes exactly this - it is the slice a
            # lagging oracle would have let cross at a stale, higher price.
            "converted": converted_total,
            "unabsorbed_insolvent": forced,
            "eligible": sum(1 for r in rows if r["eligible"]),
            "eligible_debt": sum(r["p"].debt for r in rows if r["eligible"]),
            "post_value": rem_v, "post_debt": rem_d,
            "capacity_left": left}


def ratio(numerator: int, denominator: int) -> Decimal:
    return Decimal(numerator) / Decimal(denominator) if denominator else Decimal(0)


def share_below_100(rows: list[dict], supply_weight: str = "debt") -> Decimal:
    """DET-39's supply-weighted share of positions under 100% CR."""
    total = sum(r["p"].debt for r in rows)
    under = sum(r["p"].debt for r in rows if r["cr"] < 1)
    return ratio(under, total)
