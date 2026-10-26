"""P-10.09: archetype #2's three stress rows on a hand-built bundle - D3's post-loss
arithmetic, F1's capacity_redeem with E8's 50,400 blocks, the cooldown branch."""

from decimal import Decimal
from types import SimpleNamespace as NS

from factory.synthetic_cells import BLOCKS_7D, build

WAD = 10 ** 18


def _r(v):
    return NS(value=v)


def bundle(cooldown=86_400, stable_sum="100"):
    reads = {
        "FR-U04": _r(cooldown), "FR-U06": _r(200 * WAD),
        "FR-U07": _r({"balance": 0}), "FR-U08": _r({"balance": 0}),
        "FR-U09": _r({"global_max_redeem_per_block": 1 * WAD}),
        "FR-U20": _r({"Crypto Basis": 300, "Equity and RWA Basis": 65}),
        "FR-U21": _r({"backing_usd": "1000", "reserve_fund_usd": "10"}),
        "FR-U35": _r({"sum_usd": stable_sum}),
        "FR-U36": _r({"location_totals": {"Copper": "300", "Ceffu": "200"},
                      "exchange_notional": {"Binance": "400", "Okx": "100"}}),
        "FR-U37": _r({"quarter": "2022-Q3", "value_pct": "0.1",
                      "negative_quarter_observed": False}),
    }
    return NS(synthetic=NS(reads=reads),
              supply=NS(total_supply=1000 * WAD, supply_ruled=1000 * WAD))


def depth(total_usd=50):
    return NS(depth_curve=[NS(s=Decimal("0.02"), total=total_usd * WAD)],
              sensitivity_rows=[NS(k=k, depth_at_2pct=total_usd * WAD) for k in ("80", "90", "95")])


def test_rows_1_and_2_post_loss_backing_per_d3():
    s = build(bundle(), depth())
    c = {x["id"]: x for x in s["cells"]}
    assert Decimal(c["S1-n90"]["loss"]) == Decimal(365) * Decimal("0.25") * 90 / 365
    assert Decimal(c["S1-n90"]["post_loss_backing"]) == 1000 - (Decimal("22.5") - 10)
    assert c["S2-a"]["location"] == "Copper" and Decimal(c["S2-a"]["post_loss_backing"]) == 710
    assert c["S2-b"]["exchange"] == "Binance" and Decimal(c["S2-b"]["loss"]) == 120
    assert s["headlines"] == {"row1": "S1-n90", "row2": "S2-a", "row2_beside": "S2-b",
                              "row3": "S3"}


def test_row3_capacity_branch_and_ratio():
    s = build(bundle(stable_sum="100"), depth(50))
    c = s["cells"][-1]
    # free float 800, staked 200: X = 25% x 800 + 25% x 200 = 250 (cooldown 1 d < 7 d)
    assert Decimal(c["X"]) == 250 and c["branch"] == "free float + staked"
    assert Decimal(c["capacity_redeem"]) == 100 and Decimal(c["rate_cap_7d"]) == BLOCKS_7D
    assert Decimal(c["depeg_pressure_ratio"]) == 3                 # (250 - 100) / 50
    assert Decimal(c["counterfactual_lines"][0]["X"]) == 200       # free float only
    assert [Decimal(k["ratio"]) for k in c["k_rows"]] == [3, 3, 3]
    long = build(bundle(cooldown=8 * 86_400), depth(50))["cells"][-1]
    assert long["branch"] == "free float only" and Decimal(long["X"]) == 200
    assert build(bundle(stable_sum="900"), depth(50))["cells"][-1]["depeg_pressure_ratio"] == "0"
