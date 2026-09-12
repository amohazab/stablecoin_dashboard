"""B-4a: H1's state-conditional capacity, and the LLAMMA band state it needs.

TWO HALVES, deliberately separated. The arithmetic is PURE and reproduces the
deployed regulator exactly; the readers take an `RpcClient` pinned to the
bundle's own block (R-13) and do nothing but fetch.

THE ARITHMETIC IS A PORT, not a paraphrase. From the VERIFIED source of the
deployed `Peg Keeper Regulator` (vyper 0.3.10, `0x36a04caf…`), lines 163-178:

    def _get_ratio(_peg_keeper: PegKeeper) -> uint256:
        \"\"\"
        @return debt ratio limited up to 1
        \"\"\"
        debt: uint256 = _peg_keeper.debt()
        return debt * ONE / (1 + debt + STABLECOIN.balanceOf(_peg_keeper.address))

    def _get_max_ratio(_debt_ratios: DynArray[uint256, MAX_LEN]) -> uint256:
        rsum: uint256 = 0
        for r in _debt_ratios:
            rsum += isqrt(r * ONE)
        return (self.alpha + self.beta * rsum / ONE) ** 2 / ONE

THREE THINGS THAT FORM SETTLES, each of which was open before it was read:

  * the denominator carries a **+1 wei guard** (R-B4.2). DET-45's printed form
    is `debt_j / (debt_j + balance_j)`; the deployed form differs by that one
    wei and is what a replay must use, or the replay is a near-miss rather
    than an identity. A-13 is queued to say so in the rubric.
  * the root is `isqrt` on the 1e18-scaled ratio (R-B4.3), integer throughout.
    A `Decimal` root at any precision disagrees in the last wei; `Decimal`
    appears here only where a ratio is PRINTED.
  * `provide_allowed` has NO ceiling term - it returns
    `max_ratio * total / ONE - debt` and stops. The `min(…, ceiling - debt)`
    below is the MEMO's, amendment A-5 (R-B4.4), so a reader comparing our
    number to the contract's view finds the difference named rather than
    unexplained.

`j != i` is the source's own: `provide_allowed` skips the subject keeper
(`if info.peg_keeper.address == _pk: … continue`) before appending its ratio.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import isqrt

from factory.rpc import Call

ONE = 10 ** 18

# Per-market state, 9 reads, SPLIT BY CONTRACT — a B-4a finding, measured.
# The proposal put all nine on the AMM; `loan_discount()` and
# `liquidation_discount()` revert on ALL NINE AMMs and answer on the
# CONTROLLER, with real per-market values (0.09/0.06 on most, 0.1429/0.0921 on
# WETH, 0.07/0.04 on weETH, 0.065/0.035 on cbBTC and LBTC). This is P-3.31's
# shape again: a getter assumed onto the wrong contract of a pair. Uniform
# reverts across every instance are the tell — a market-specific problem would
# not hit all nine identically.
AMM_READS: tuple[tuple[str, str], ...] = (
    ("active_band()", "int256"),
    ("get_p()", "uint256"),
    ("price_oracle()", "uint256"),
    ("get_base_price()", "uint256"),
    ("A()", "uint256"),
    ("fee()", "uint256"),
    ("admin_fee()", "uint256"),
)
CONTROLLER_READS: tuple[tuple[str, str], ...] = (
    ("loan_discount()", "uint256"),
    ("liquidation_discount()", "uint256"),
)
MARKET_READS = AMM_READS + CONTROLLER_READS      # the 9, for counting
BAND_READS: tuple[tuple[str, str], ...] = (
    ("bands_x(int256)", "uint256"),
    ("bands_y(int256)", "uint256"),
    ("p_oracle_up(int256)", "uint256"),
)


class LlammaError(Exception):
    """A read the band model cannot proceed without."""


@dataclass(frozen=True)
class Keeper:
    """One PegKeeper's state, TAKEN FROM THE BUNDLE (R-B4.5), never re-read."""

    address: str
    debt: int
    balance: int
    ceiling: int
    killed_provide: bool
    killed_withdraw: bool


def scale_alpha_beta(alpha, beta) -> tuple[int, int]:
    """The bundle stores α and β in HUMAN units (0.5, 0.25); the chain holds
    them at 1e18. One scaling site, so the port and the checks cannot drift."""
    if alpha is None or beta is None:
        raise LlammaError("the bundle carries no alpha/beta; DET-45 cannot replay")
    return int(Decimal(alpha) * ONE), int(Decimal(beta) * ONE)


def get_ratio(k: Keeper) -> int:
    """`debt * ONE / (1 + debt + balance)` - the source's line 168, +1 included."""
    return k.debt * ONE // (1 + k.debt + k.balance)


def get_max_ratio(ratios: list[int], alpha: int, beta: int) -> int:
    """`(alpha + beta * Σ isqrt(r * ONE) / ONE) ** 2 / ONE`, integer throughout."""
    rsum = 0
    for r in ratios:
        rsum += isqrt(r * ONE)
    return (alpha + beta * rsum // ONE) ** 2 // ONE


def allowed(keepers: list[Keeper], i: int, alpha: int, beta: int) -> tuple[int, int]:
    """`(allowed_i, max_ratio_i)` for one keeper, floored at 0.

    A killed-Provide keeper contributes ZERO by DET-45's letter, and it is
    tested before the arithmetic rather than after: a killed keeper's ratio
    still enters its PEERS' sums, because the chain keeps it in `peg_keepers`
    and `_get_ratio` reads its debt regardless of the flag.
    """
    subject = keepers[i]
    ratios = [get_ratio(k) for j, k in enumerate(keepers) if j != i]
    mx = get_max_ratio(ratios, alpha, beta)
    if subject.killed_provide:
        return 0, mx
    total = subject.debt + subject.balance
    raw = mx * total // ONE - subject.debt
    head = subject.ceiling - subject.debt          # A-5's min, the memo's not the chain's
    return max(0, min(raw, head)), mx


def headroom(keepers: list[Keeper], alpha: int, beta: int) -> tuple[int, int, dict]:
    """`(effective, naive, per_keeper)`. DET-45: `effective <= naive` exact."""
    per: dict[str, dict] = {}
    eff = 0
    for i, k in enumerate(keepers):
        a, mx = allowed(keepers, i, alpha, beta)
        eff += a
        per[k.address] = {"r": get_ratio(k), "max_ratio": mx, "allowed": a,
                          "debt": k.debt, "balance": k.balance,
                          "ceiling": k.ceiling, "killed_provide": k.killed_provide,
                          "killed_withdraw": k.killed_withdraw}
    naive = sum(max(k.ceiling - k.debt, 0) for k in keepers)
    return eff, naive, per


# ------------------------------------------------------------- the readers ---


def read_ticks(rpc, amm: str, users: list[str], reads: dict) -> dict[str, tuple[int, int]]:
    """`read_user_tick_numbers(user)` per position. A revert stops the run: a
    position whose bands are unknown cannot be modeled, and skipping it would
    silently shrink the crash path."""
    res = rpc.read([Call(amm, "read_user_tick_numbers(address)", ("int256", "int256"),
                         (u,)) for u in users])
    out = {}
    for u, r in zip(users, res, strict=True):
        if not r.ok:
            raise LlammaError(f"{amm}: read_user_tick_numbers({u}) reverted")
        n1, n2 = (int(x) for x in r.require())
        out[u] = (min(n1, n2), max(n1, n2))
    reads[f"{amm}.read_user_tick_numbers"] = res[0].provenance if res else None
    return out


def band_union(ticks: dict[str, tuple[int, int]]) -> list[int]:
    """The distinct bands the positions occupy, sorted.

    R11's gate turns on this: at 25963950 the union is 1,543 bands against a
    Σ N of 9,565 - 16.1% - because neighbouring positions share bands. Reading
    per position instead would cost 28,695 band reads and fail the gate four
    times over (P-6.01 F23, measured).
    """
    seen: set[int] = set()
    for lo, hi in ticks.values():
        seen.update(range(lo, hi + 1))
    return sorted(seen)
