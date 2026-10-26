"""P-10.07: the archetype-#2 tree fold, DET-90's figures (J1) and A-28's cadence rule,
on a hand-built bundle - no network, no stored USDe artifact."""

import pathlib
from decimal import Decimal
from types import SimpleNamespace as NS

from factory.config import load
from factory.synthetic_tree import cadence_days, fold_synthetic
from factory.validate.harness import det90_figures, det_90

REPO = pathlib.Path(__file__).resolve().parents[1]
CFG = load(REPO / "config", "USDe")
PYUSD = "0x6c3ea9036406852006290770bedfcaba0e23a0e8"
USDE18 = 10 ** 18


def _r(v):
    return NS(value=v)


def bundle(liquid_disclosed="700"):
    cats = {"Crypto Basis": 150, "Equity and RWA Basis": 10, "Institutional Lending": 150,
            "Liquid Stables": 270, "DeFi Lending": 350, "RWA": 70}
    reads = {
        "FR-U02": _r("0xe3490297a08d6fc8da46edb7b6142e4f461b62d3"),
        "FR-U06": _r(300 * USDE18), "FR-U07": _r({"balance": 10 * USDE18}),
        "FR-U08": _r({"balance": 200 * USDE18}),
        "FR-U19": _r({"balances": {}, "eth": 0}),
        "FR-U20": _r(cats),
        "FR-U21": _r({"backing_usd": "1000", "reserve_fund_usd": "6", "supply_usd": "999"}),
        "FR-U23": _r({"0x" + "1" * 40: {PYUSD: 500 * 10 ** 6}}),
        "FR-U24": _r({"addresses": [], "balances": {"0x" + "2" * 40: {PYUSD: 200 * 10 ** 6}},
                      "decimals": {PYUSD: 6}}),
        "FR-U33": _r({}),
        "FR-U36": _r({"locations": ["Ceffu", "Copper"],
                      "ethereum_by_strategy": {"Liquid Stables": liquid_disclosed,
                                               "DeFi Lending": "300", "RWA": "0"}}),
    }
    return NS(synthetic=NS(reads=reads),
              header=NS(token="USDe", run_block=1, bundle_hash="h",
                        block_timestamp=1792933308),                      # 2026-10-25
              supply=NS(total_supply=999 * USDE18, supply_ruled=999 * USDE18,
                        origination_sum=999 * USDE18, residual=0),
              admin_surface=[], pools=[])


def test_fold_is_0_0_100_over_the_six_categories():
    t = fold_synthetic(bundle(), CFG)
    assert [str(b.share) for b in t.bars][:2] == ["0", "0"] and t.bars[2].share == 1
    assert t.root.backing_value == 1000 and len(t.nodes) == 6
    assert {n.category for n in t.truncated_nodes} == {"DeFi Lending", "RWA"}
    assert all(x["weight"] == "0" for x in t.synthetic["label_rows"])
    assert t.synthetic["supply_classes"]["free_float"] == 489 * USDE18
    assert t.staleness.worst.symbol == "Liquid Stables"                  # derived from USDT
    assert "2 custodians under issuer discretion" in t.banner


def test_det90_reconciles_liquid_stables_only():
    ctx = {"label_rows": CFG.label_rows}
    f = det90_figures(bundle("700"), ctx)
    assert f["buffer_onchain"] == 700 and f["gap"] == 0 and not f["fires"]
    assert f["not_reconciled"] == {"DeFi Lending": Decimal(300), "RWA": Decimal(0)}
    assert det_90(bundle("700"), ctx) is None                          # S1: tuple or None
    assert det_90(bundle("800"), ctx) == ("T-30", 1)                   # gap 100 > 5% of 1000


def test_a28_cadence_measures_against_the_dating_source():
    assert cadence_days("monthly attestation + weekly PoR") == 30
    assert cadence_days("quarterly BDO attestation") == 92
    assert cadence_days("NAV per fund") is None
    t = fold_synthetic(bundle(), CFG)
    assert {x["category"]: x["overdue"] for x in t.synthetic["t29"]} == {
        "Crypto Basis": False, "Equity and RWA Basis": False,
        "Institutional Lending": False, "Liquid Stables": False}
