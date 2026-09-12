"""B-4b tests: the band-linear model, R-B4.15's allocation, R-B4.14's infinity.

Hand-built throughout — a two-band position whose arithmetic can be checked on
paper, so a refactor that changes the conversion fails here rather than in a
47-cell fold where one number among hundreds moves.
"""

from __future__ import annotations

from decimal import Decimal

from factory.liquidation import (
    ONE,
    BandPrices,
    Position,
    allocate,
    convert_position,
    is_eligible,
    position_value,
    run_cell,
)

AMM = "0x" + "a" * 40
MKT = "0x" + "c" * 40
# two bands: n=0 spans [200, 220], n=1 spans [180, 200]
PRICES = BandPrices(up={0: 220 * ONE, 1: 200 * ONE, 2: 180 * ONE})


def pos(coll: int, debt: int, n1: int = 0, n2: int = 1, x: int = 0) -> Position:
    return Position(user="0x" + "1" * 40, market=MKT, amm=AMM, collateral=coll,
                    debt=debt, n1=n1, n2=n2, x_pos=x)


def test_the_band_interval_is_read_from_both_endpoints():
    """`p_oracle_down(n)` IS `p_oracle_up(n+1)` — the source's own identity, so
    a band whose upper neighbour was not read is a HOLE and raises rather than
    interpolating."""
    assert PRICES.interval(0) == (200 * ONE, 220 * ONE)
    assert PRICES.interval(1) == (180 * ONE, 200 * ONE)
    try:
        PRICES.interval(2)
    except KeyError as e:
        assert "unread" in str(e)
    else:                                              # pragma: no cover
        raise AssertionError("a missing boundary band must raise")


def test_conversion_is_untouched_above_full_below_and_pro_rata_inside():
    p = pos(coll=10 * ONE, debt=0)
    bands = {0: (0, 5 * ONE), 1: (0, 5 * ONE)}          # equal y, so 5 each

    crv, left = convert_position(p, PRICES, 230 * ONE, bands)
    assert (crv, left) == (0, 10 * ONE)                 # wholly above: untouched

    crv, left = convert_position(p, PRICES, 170 * ONE, bands)
    assert left == 0                                    # wholly below: converted
    assert crv == 5 * 210 * ONE + 5 * 190 * ONE         # at each band's midpoint

    crv, left = convert_position(p, PRICES, 210 * ONE, bands)
    # band 0 is half-crossed (210 of [200,220]); band 1 is untouched
    assert left == Decimal("2.5") * ONE + 5 * ONE
    assert crv == Decimal("2.5") * 215 * ONE            # midpoint of [210, 220]


def test_allocation_is_proportional_to_the_bands_recorded_y():
    """R-B4.15. An even spread hands an already-converted position its crvUSD
    leg twice; proportional allocation gives a fully-converted band none."""
    p = pos(coll=9 * ONE, debt=0)
    assert allocate(p, {0: (0, 2 * ONE), 1: (0, 1 * ONE)}) == {0: 6 * ONE, 1: 3 * ONE}
    # band 0 fully converted already -> it carries none of the collateral
    assert allocate(p, {0: (500 * ONE, 0), 1: (0, 1 * ONE)}) == {0: 0, 1: 9 * ONE}
    # every band converted -> nothing to allocate
    assert allocate(p, {0: (1, 0), 1: (1, 0)}) == {0: 0, 1: 0}


def test_the_crvusd_leg_is_value_and_the_shock_does_not_touch_it():
    bands = {0: (0, 5 * ONE), 1: (0, 5 * ONE)}
    plain = position_value(pos(10 * ONE, 0), PRICES, 230 * ONE, bands)
    withx = position_value(pos(10 * ONE, 0, x=1234), PRICES, 230 * ONE, bands)
    assert withx - plain == 1234


def test_collateral_decimals_scale_before_any_price_meets_them():
    """R-B4.17, the defect's own test. A BTC market's raw collateral is 8-dp;
    the model works in 18. Unscaled, 30 BTC reads as 3e9 wei of an 18-dp asset
    — 3e-10 of a coin — the position looks empty and its whole debt falls out
    as bad debt. That is how B-4b's first fold produced 29.8M of
    shock-invariant bad debt across four markets."""
    raw_btc = 30 * 10 ** 8                              # 30 WBTC, 8 decimals
    scaled = raw_btc * 10 ** (18 - 8)
    assert scaled == 30 * ONE
    bands = {0: (0, 15 * ONE), 1: (0, 15 * ONE)}
    unscaled_value = position_value(pos(raw_btc, ONE), PRICES, 190 * ONE, bands)
    scaled_value = position_value(pos(scaled, ONE), PRICES, 190 * ONE, bands)
    assert scaled_value // unscaled_value == 10 ** 10   # out by exactly 1e10
    assert scaled_value > 5000 * ONE                    # 30 units at ~200
    assert unscaled_value < ONE // 1000                 # under a thousandth of one


def test_eligibility_uses_the_markets_own_liquidation_discount():
    disc = 92_100_000_000_000_000                        # WETH's 0.0921
    assert is_eligible(100 * ONE, 95 * ONE, disc) is True       # 90.79 < 95
    assert is_eligible(100 * ONE, 80 * ONE, disc) is False      # 90.79 > 80


def test_run_cell_absorbs_ascending_by_cr_and_floors_bad_debt():
    bands = {AMM: {0: (0, 5 * ONE), 1: (0, 5 * ONE)}}
    weak = pos(10 * ONE, 3000 * ONE)                     # deeply underwater
    strong = pos(10 * ONE, 100 * ONE)
    res = run_cell([strong, weak], {AMM: PRICES}, {MKT: 170 * ONE},
                   {MKT: 92_100_000_000_000_000}, {MKT: 0}, bands)
    assert res["bad_debt"] > 0
    assert res["eligible"] == 1                          # only the weak one
    assert all(r["cr"] >= 0 for r in res["rows"])
    res2 = run_cell([strong], {AMM: PRICES}, {MKT: 170 * ONE},
                    {MKT: 92_100_000_000_000_000}, {MKT: 10 ** 30}, bands)
    assert res2["bad_debt"] == 0                         # never negative
