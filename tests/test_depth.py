"""B-2 tests: the invariant port, the K-subset rule, R-19, and the solver.

The three reproduction tests run against `tests/fixtures_depth_recorded.json` —
pool state and the contract's own `get_dy` answers, recorded once at each
token's `run_block` (the `fixtures_aggregate3_recorded.hex` precedent, P-3.20).
The suite stays offline; R-17's live ground truth is the stress module's, not
the test suite's.
"""

from __future__ import annotations

import json
import pathlib
from decimal import Decimal

import pytest

from factory.depth import (
    PRECISION,
    DepthError,
    PoolState,
    get_dy,
    marginal_price,
    pool_depth,
    withdraw_one_coin,
)
from factory.schema import GsmVenue, PoolRow
from factory.stress import gsm_enters, k_subsets

REPO = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = json.loads(
    (REPO / "tests/fixtures_depth_recorded.json").read_text(encoding="utf-8"))
S_DEN = 10 ** 6


def _states(kind: str) -> list[tuple[dict, PoolState]]:
    out = []
    for tok in FIXTURE.values():
        for p in tok["pools"]:
            if p["kind"] != kind:
                continue
            out.append((p, PoolState(
                address=p["address"], kind=p["kind"], coins=tuple(p["coins"]),
                decimals=tuple(p["decimals"]), balances=tuple(p["balances"]),
                amp=p["amp"], fee=p["fee"], rates=tuple(p["rates"]),
                offpeg_fee_multiplier=p["offpeg_fee_multiplier"],
                virtual_price=p["virtual_price"], total_supply=p["total_supply"])))
    return out


@pytest.mark.parametrize("kind", ["plain_v6", "ng", "metapool"])
def test_the_port_reproduces_get_dy_exactly(kind):
    """R-17's substance: the pipeline's own function against the deployed
    contract's, at three sizes per pool, integer-exact."""
    rows = _states(kind)
    assert rows, f"no recorded pool of shape {kind}"
    for raw, p in rows:
        for probe in raw["probes"]:
            got = get_dy(p, raw["i"], raw["j"], probe["dx"])
            assert got == probe["onchain"], (
                f"{p.address} {kind} {probe['label']}: ported {got} vs onchain "
                f"{probe['onchain']}")


def _row(addr: str, tvl: int) -> PoolRow:
    return PoolRow(address=addr, in_frozen_set=True, tvl_at_par=tvl,
                   ratio_to_frozen_coverage=Decimal(0))


def test_k_subsets_take_the_shortest_prefix_with_an_address_tie_break():
    a, b, c = "0x" + "a" * 40, "0x" + "b" * 40, "0x" + "c" * 40
    ks = k_subsets([_row(a, 50), _row(b, 50), _row(c, 1)])
    assert ks["80"] == [a, b]          # 100/101 clears 80%; ties on address
    assert ks["90"] == [a, b]


def test_k95_is_f_by_construction_even_when_the_prefix_is_shorter():
    """R5: memo §5.5's intent governs — 95 is the full frozen set, not
    DET-29(b)'s prefix, which would drop a small tail."""
    a, b = "0x" + "a" * 40, "0x" + "b" * 40
    ks = k_subsets([_row(a, 97), _row(b, 3)])
    assert ks["90"] == [a]
    assert sorted(ks["95"]) == sorted([a, b])


def _venue(fee: str) -> GsmVenue:
    return GsmVenue(gsm="0x" + "1" * 40, boxed_asset="0x" + "2" * 40,
                    underlying="0x" + "3" * 40, fee_exit=Decimal(fee),
                    exchange_rate=Decimal(1), balance=10, enters=True, reason="t")


def test_a_gsm_enters_iff_its_exit_fee_is_strictly_below_s():
    assert gsm_enters(_venue("0.001"), Decimal("0.005")) is True
    assert gsm_enters(_venue("0.005"), Decimal("0.005")) is False   # strict
    assert gsm_enters(_venue("0.02"), Decimal("0.005")) is False
    closed = _venue("0.001").model_copy(update={"enters": False})
    assert gsm_enters(closed, Decimal("0.05")) is False


def test_pool_depth_is_non_decreasing_in_s():
    raw, p = _states("plain_v6")[0]
    prev = -1
    for s in ("0.005", "0.01", "0.02", "0.05"):
        d = pool_depth(p, raw["i"], raw["j"], int((1 - Decimal(s)) * S_DEN), S_DEN)
        assert d >= prev
        prev = d


def test_the_bound_is_evaluated_in_rate_scaled_space():
    """R-B2.6, on the pool that distinguishes the two spaces.

    LUSD/3CRV in LP units prices LUSD at ~0.9716 — below 0.98 at zero size, so
    a bound in LP units would report zero depth. In the pool's own rate-scaled
    space the received side carries the base pool's virtual price and the same
    point is ~1.0103, LUSD above par, with real depth before 0.98. The six
    single-asset pools are unaffected because their rates ARE the decimals
    scale, which the second assertion pins.
    """
    raw, p = _states("metapool")[0]
    i, j = raw["i"], raw["j"]
    num, den = marginal_price(p, i, j, 0)
    assert Decimal(num) / Decimal(den) > Decimal("1.00")
    in_lp_units = (Decimal(num) * Decimal(10 ** p.decimals[j]) * Decimal(PRECISION)
                   / (Decimal(den) * Decimal(10 ** p.decimals[i]) * Decimal(p.rates[j])))
    assert in_lp_units < Decimal("0.98")
    assert pool_depth(p, i, j, int(Decimal("0.98") * S_DEN), S_DEN) > 0
    for _, q in _states("plain_v6") + _states("ng"):
        assert q.rates == tuple(10 ** (36 - d) for d in q.decimals)


def test_withdraw_one_coin_takes_the_scarce_side_and_reduces_it():
    raw, p = _states("ng")[0]
    i = raw["i"]
    dy, after = withdraw_one_coin(p, p.total_supply // 100, i)
    assert dy > 0
    assert after.balances[i] == p.balances[i] - dy
    assert after.balances[1 - i] == p.balances[1 - i]        # single-sided
    assert after.total_supply < p.total_supply
    assert withdraw_one_coin(p, 0, i)[0] == 0


def test_an_unbracketed_depth_raises_rather_than_returning_the_edge(monkeypatch):
    """The guard, exercised directly. It cannot be provoked through a real pool
    at a real bound: a `get_dy` that fails at an absurd size is TREATED as past
    the range, which brackets it — correctly. So the bound is stubbed to one
    that is never breached, and the solver must raise rather than hand back the
    bracket edge as if it were a depth."""
    import factory.depth as d
    raw, p = _states("plain_v6")[0]
    monkeypatch.setattr(d, "_below_bound", lambda *a, **k: False)
    with pytest.raises(DepthError, match="not bracketed"):
        d.pool_depth(p, raw["i"], raw["j"], int(Decimal("0.98") * S_DEN), S_DEN)
