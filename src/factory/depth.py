"""B-2: the stableswap invariant port and the s-depth solver. PURE — no RPC.

R-17 requires the pipeline's OWN depth function, verified against `get_dy` at
s = 2%, so this port is owed output rather than gold-plating (P-3.03's boundary
clause). It is written against the VERIFIED SOURCE of each deployed
implementation, fetched at B-2 and cited here by address and `ContractName` —
never from recall, which cost a session twice (P-3.18, P-3.20):

  * `plain_v6`  — `Vyper_contract`, vyper 0.3.7, implementation
    `0x67fe41a94e779ccfa22cff02cc2957dc9c0e4286` (crvUSD factory plain pools
    `0x390f3595…`, `0x4dece678…`). `version()` = v6.0.1.
  * `ng`        — `CurveStableSwapNG`, vyper 0.3.10, blueprint deployment
    (`0x13e12bb0…`, `0x625e9262…`, `0x635ef005…`). `version()` = v7.0.0. Its
    `get_dy` DELEGATES to the factory's views contract, so the ported form is
    `CurveStableSwapNGViews` `0xff53042865df617de4bb871bd0988e7b93439ccf`,
    vyper 0.3.10, VERSION "1.2.0".
  * `metapool`  — `Vyper_contract`, vyper 0.2.8, implementation
    `0x5f890841f657d90e081babdb532a05996af79fe6` (`0xed279fdd…` LUSD/3CRV).

THREE ROUNDING DIFFERENCES THAT ARE NOT COSMETIC, each read off the source
rather than assumed, and each of which would silently break reproduction:

  1. `get_D`'s inner term. `plain_v6`/`ng` compute `D_P = D_P * D / x` per coin
     and divide by `n**n` ONCE at the end; `metapool` divides by `x * n` per
     coin. Algebraically equal, integer-unequal.
  2. `get_dy`'s fee ordering. All three here take the fee BEFORE converting out
     of `xp` space: `(dy - fee) * PRECISION / rates[j]`. (The 3pool converts
     first and then charges — noted because the base pool is a different
     implementation, and its swap math is NOT ported: the metapool path needs
     only its `get_virtual_price()`.)
  3. The `ng` fee is DYNAMIC — `_dynamic_fee` over the midpoint of the two
     balances with `offpeg_fee_multiplier` — while the other two are flat.

The metapool's rates are `[rate_multiplier, BASE_POOL.get_virtual_price()]`,
read LIVE inside `get_dy`; the implementation caches nothing, which is why
`base_virtual_price()` reverts on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

A_PRECISION = 100
PRECISION = 10 ** 18
FEE_DENOMINATOR = 10 ** 10

Kind = Literal["plain_v6", "ng", "metapool"]


class DepthError(Exception):
    """The solver could not answer. Never a zero and never a bracket edge."""


@dataclass(frozen=True)
class PoolState:
    """One pool's state at `run_block`, as read. `amp` is the PRECISE value —
    `A() * A_PRECISION` — because every shape here divides by `A_PRECISION`
    internally; `A()` is the human figure and is never used directly."""

    address: str
    kind: Kind
    coins: tuple[str, ...]
    decimals: tuple[int, ...]
    balances: tuple[int, ...]
    amp: int
    fee: int
    rates: tuple[int, ...]
    offpeg_fee_multiplier: int | None = None
    virtual_price: int | None = None
    total_supply: int | None = None

    @property
    def n(self) -> int:
        return len(self.coins)


# ------------------------------------------------------------ invariant -----


def xp_mem(rates: tuple[int, ...], balances: tuple[int, ...]) -> list[int]:
    return [r * b // PRECISION for r, b in zip(rates, balances, strict=True)]


def get_D(xp: list[int], amp: int, kind: Kind) -> int:
    n = len(xp)
    s = sum(xp)
    if s == 0:
        return 0
    d = s
    ann = amp * n
    for _ in range(255):
        if kind == "metapool":
            d_p = d
            for x in xp:
                d_p = d_p * d // (x * n)
        else:                                   # plain_v6 and ng
            d_p = d
            for x in xp:
                d_p = d_p * d // x
            d_p //= n ** n
        d_prev = d
        d = ((ann * s // A_PRECISION + d_p * n) * d
             // ((ann - A_PRECISION) * d // A_PRECISION + (n + 1) * d_p))
        if abs(d - d_prev) <= 1:
            return d
    raise DepthError("get_D did not converge in 255 iterations")


def _newton_y(b: int, c: int, d: int) -> int:
    y = d
    for _ in range(255):
        y_prev = y
        y = (y * y + c) // (2 * y + b - d)
        if abs(y - y_prev) <= 1:
            return y
    raise DepthError("get_y did not converge in 255 iterations")


def get_y(i: int, j: int, x: int, xp: list[int], amp: int, d: int) -> int:
    """x[j] given x[i] = x. Identical in all three sources once `_D` is
    supplied; the only divergence was where `D` comes from."""
    n = len(xp)
    ann = amp * n
    c = d
    s_ = 0
    for k in range(n):
        if k == i:
            _x = x
        elif k != j:
            _x = xp[k]
        else:
            continue
        s_ += _x
        c = c * d // (_x * n)
    c = c * d * A_PRECISION // (ann * n)
    b = s_ + d * A_PRECISION // ann
    return _newton_y(b, c, d)


def _get_y_D(i: int, xp: list[int], amp: int, d: int) -> int:
    """x[i] that satisfies the invariant at a REDUCED D — the withdrawal side
    of the same quadratic. Index `i` is skipped rather than substituted."""
    n = len(xp)
    ann = amp * n
    c = d
    s_ = 0
    for k in range(n):
        if k == i:
            continue
        s_ += xp[k]
        c = c * d // (xp[k] * n)
    c = c * d * A_PRECISION // (ann * n)
    b = s_ + d * A_PRECISION // ann
    return _newton_y(b, c, d)


def dynamic_fee(xpi: int, xpj: int, fee: int, multiplier: int) -> int:
    if multiplier <= FEE_DENOMINATOR:
        return fee
    xps2 = (xpi + xpj) ** 2
    return ((multiplier * fee)
            // ((multiplier - FEE_DENOMINATOR) * 4 * xpi * xpj // xps2
                + FEE_DENOMINATOR))


def get_dy(p: PoolState, i: int, j: int, dx: int) -> int:
    """The ported `get_dy`, integer-exact against the deployed contract."""
    xp = xp_mem(p.rates, p.balances)
    d = get_D(xp, p.amp, p.kind)
    x = xp[i] + dx * p.rates[i] // PRECISION
    y = get_y(i, j, x, xp, p.amp, d)
    dy = xp[j] - y - 1
    if p.kind == "ng":
        if p.offpeg_fee_multiplier is None:
            raise DepthError(f"{p.address}: ng pool without offpeg_fee_multiplier")
        fee = dynamic_fee((xp[i] + x) // 2, (xp[j] + y) // 2,
                          p.fee, p.offpeg_fee_multiplier) * dy // FEE_DENOMINATOR
    else:
        fee = p.fee * dy // FEE_DENOMINATOR
    return (dy - fee) * PRECISION // p.rates[j]


# ------------------------------------------------------ LP flight (B-4) -----


def withdraw_one_coin(p: PoolState, lp_amount: int, i: int) -> tuple[int, PoolState]:
    """§6.1.4's SINGLE-SIDED withdrawal of one coin — `remove_liquidity_one_coin`
    semantics on the same integer path, so no second approximation enters.

    IMPLEMENTED AND UNIT-TESTED AT B-2, CONSUMED BY NO ARTIFACT FIELD UNTIL B-4
    (P-6.01 R-B2.4): the 0/30/60 haircut is a per-cell axis that DET-41 reads,
    and DET-31's four points are defined at current composition. It is NOT yet
    verified against an on-chain `calc_withdraw_one_coin` — that ground truth is
    one read per pool and belongs with the first consumption, at B-4.
    """
    if p.total_supply is None:
        raise DepthError(f"{p.address}: withdrawal needs total_supply")
    if lp_amount == 0:
        return 0, p
    n = p.n
    xp = xp_mem(p.rates, p.balances)
    d0 = get_D(xp, p.amp, p.kind)
    d1 = d0 - lp_amount * d0 // p.total_supply
    new_y = _get_y_D(i, xp, p.amp, d1)
    base_fee = p.fee * n // (4 * (n - 1))
    xp_reduced = []
    for k in range(n):
        if k == i:
            dx_expected = xp[k] * d1 // d0 - new_y
        else:
            dx_expected = xp[k] - xp[k] * d1 // d0
        xp_reduced.append(xp[k] - base_fee * dx_expected // FEE_DENOMINATOR)
    dy = xp_reduced[i] - _get_y_D(i, xp_reduced, p.amp, d1)
    dy = (dy - 1) * PRECISION // p.rates[i]
    balances = list(p.balances)
    balances[i] -= dy
    return dy, PoolState(**{**p.__dict__, "balances": tuple(balances),
                            "total_supply": p.total_supply - lp_amount})


# --------------------------------------------------------- the solver -------

# Named implementer defaults (P-6.01 R4, ruled 2026-09-12).
BISECT_TOL = 10 ** 18          # one whole token of the sold side
BISECT_MAX_ITER = 128
BRACKET_DOUBLINGS = 8


def marginal_price(p: PoolState, i: int, j: int, dx: int) -> tuple[int, int]:
    """Marginal price at `dx`, as the exact rational `(num, den)`.

    R-B2.6 (ruled 2026-09-12): the bound is evaluated in the pool's own
    RATE-SCALED space, `xp = balance * rate / PRECISION` — the space the
    contract's invariant works in — so both legs are converted by `rates`
    rather than by raw decimals. For a plain or NG pool whose assets are
    unit-priced this is the SAME NUMBER, because `rates[k]` is exactly
    `10 ** (36 - decimals[k])` there; it differs only where a rate carries real
    content, which for the pilot is the metapool's second rate, the base pool's
    `get_virtual_price()`. Counting 3CRV at its virtual price is §6.1.3's par
    applied THROUGH §4.3's composite pass-through: the LP unit is not the thing
    that counts at 1.00, its constituents are.

    Finite difference on the PORTED function; the contract's `get_dy` is ground
    truth at s = 2% only, never inside the loop.
    """
    ddx = max(BISECT_TOL, dx // 10 ** 6)
    y0 = get_dy(p, i, j, dx)
    y1 = get_dy(p, i, j, dx + ddx)
    num = (y1 - y0) * p.rates[j]
    den = ddx * p.rates[i]
    return num, den


def _below_bound(p: PoolState, i: int, j: int, dx: int, s_num: int, s_den: int) -> bool:
    """True when the marginal price at `dx` has fallen below `1 - s`."""
    try:
        num, den = marginal_price(p, i, j, dx)
    except (DepthError, ZeroDivisionError, ValueError):
        return True                       # past the pool's usable range
    return num * s_den < s_num * den


def pool_depth(p: PoolState, i: int, j: int, s_num: int, s_den: int) -> int:
    """Units of coin `i` sellable before the marginal price falls below
    `1 - s`, where `s = s_num_gap / s_den` — `s_num` is the NUMERATOR OF
    `1 - s`. Returns coin-`i` base units (R-B2.1: token base units, never
    `value_scale`)."""
    lo, hi = 0, 2 * p.balances[i]
    doublings = 0
    while not _below_bound(p, i, j, hi, s_num, s_den):
        hi *= 2
        doublings += 1
        if doublings > BRACKET_DOUBLINGS:
            raise DepthError(
                f"{p.address}: marginal price still at or above the bound after "
                f"{BRACKET_DOUBLINGS} doublings (hi = {hi}); the depth is not "
                "bracketed and the bracket edge is never returned as a depth.")
    if _below_bound(p, i, j, lo, s_num, s_den):
        return 0
    for _ in range(BISECT_MAX_ITER):
        if hi - lo <= BISECT_TOL:
            return lo
        mid = (lo + hi) // 2
        if _below_bound(p, i, j, mid, s_num, s_den):
            hi = mid
        else:
            lo = mid
    return lo


__all__ = ["A_PRECISION", "BISECT_TOL", "DepthError", "FEE_DENOMINATOR",
           "PRECISION", "PoolState", "dynamic_fee", "get_D", "get_dy", "get_y",
           "marginal_price", "pool_depth", "withdraw_one_coin", "xp_mem"]
