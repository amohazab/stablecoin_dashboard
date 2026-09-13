"""B-9 tests (P-7.01 R4, P-7.03's fixes, P-7.05's rulings): one test per declared
row family and per registered check - the mirror parses, the two new read
modules, and DET-05 / 15 / 32 / 32-lineage / 55's enums / 71 / 76e."""

from __future__ import annotations

import pathlib
from decimal import Decimal
from types import SimpleNamespace

import pytest

import tests.test_schema as ts
from factory import mirror
from factory.config import load
from factory.disclosure import DisclosureStop, disclosure_fields
from factory.feeds import FeedStop, condition_from_row
from factory.offvenue import NOT_COMPUTED, share
from factory.provenance import AbsenceRead, AnalystSupplied, ContractRead
from factory.schema import OffvenueShare, ResidualCause
from factory.stress import _label_of
from factory.validate.harness import (
    CHECKS,
    Level3,
    det_05,
    det_15,
    det_32,
    det_32_lineage,
    det_55,
    det_71,
    det_76e,
)

REPO = pathlib.Path(__file__).resolve().parents[1]
SHEET = REPO / "docs/context/intake-sheets-cdp.md"
RB = ts.RB


# --- the registry ------------------------------------------------------------------


def test_b9_registers_six_rows():
    ids = {c.entry_id: (c.stage, c.consumer) for c in CHECKS}
    assert len(CHECKS) >= 66                          # B-10 adds DET-84 (test_b10)
    assert ids["DET-71"] == ("S1", "tree") and ids["DET-76e"] == ("S1", "tree")
    assert {ids[k] for k in ("DET-05", "DET-15", "DET-32")} == {("S2", "tree")}
    assert ids["DET-32-lineage"] == ("S2", "stress")
    assert "DET-81" not in ids                         # P-7.05 S8: A-16's list


# --- mirror parses (DET-73, DET-76(e), DET-54/55) -----------------------------------


def test_audit_blocks_parse_as_signed():
    got = {t: mirror.parse_audit_status(SHEET, t) for t in ("crvUSD", "GHO", "LUSD")}
    assert [len(got[t]["audits"]) for t in got] == [6, 12, 2]
    assert got["crvUSD"]["bug_bounty"] == {"platform": "Curve (self-run, docs.curve.finance/"
                                           "developer/security)", "max": "USD 250,000"}
    assert got["LUSD"]["audits"][0] == {"firm": "Trail of Bits", "date": "2021-01",
                                        "scope": "Liquity v1 security assessment"}
    assert {g["last_material_change_audited"] for g in got.values()} == {"yes"}
    assert {g["staleness_date"] for g in got.values()} == {"2026-09-13"}
    assert mirror.parse_counterparties(SHEET, "LUSD").endswith(
        "no WBTC custodian exposure — no WBTC node in the LUSD tree.")


def test_disclosure_rows_join_to_addresses():
    g = load(REPO / "config", "GHO")
    sym = {g.labels[a].symbol: d for a, d in g.disclosures.items()}
    assert set(sym) == {"WBTC", "USDC", "USDT", "cbETH", "cbBTC", "sUSDe",
                        "waEthUSDC", "waEthUSDT"}
    assert sym["waEthUSDT"]["last_disclosure_date"] == "2026-06-30"
    assert sym["waEthUSDT"]["inherited_from"] == "USDT"
    assert len(load(REPO / "config", "crvUSD").disclosures) == 3
    assert load(REPO / "config", "LUSD").disclosures == {}


def test_feed_table_parses_21_and_1():
    rows = mirror.parse_oracle_feeds(SHEET, "GHO")
    assert len(rows) == 21 and len(mirror.parse_oracle_feeds(SHEET, "LUSD")) == 1
    by = {r["symbol"]: r for r in rows}
    assert by["AAVE"]["deviation_bps"] == 100 and by["USDS"]["deviation_bps"] == 30
    assert by["JAAA"]["type"] == "nav_schedule"
    assert by["JAAA"]["heartbeat_form"] == "observed_max"
    assert "heartbeat_s" not in by["JAAA"]
    assert mirror.parse_oracle_feeds(SHEET, "crvUSD") == []


# --- DET-32 ------------------------------------------------------------------------------

ADDR = "0x40d16fc0246ad3160ccc09b8d0d3a2cd28ae6c2f"
PROTOCOLS = [{"slug": "curve-dex", "category": "Dexs"}, {"slug": "uniswap-v4", "category": "Dexs"},
             {"slug": "aave-v3", "category": "Lending"}]


def _pool(project, tvl, chain="Ethereum", tokens=(ADDR,)):
    return {"chain": chain, "project": project, "tvlUsd": tvl, "underlyingTokens": list(tokens)}


def test_offvenue_share_counts_dexes_on_mainnet_only():
    pools = {"data": [_pool("curve-dex", 25.5), _pool("uniswap-v4", 74.9),
                      _pool("aave-v3", 1e9), _pool("uniswap-v4", 1e9, chain="Arbitrum"),
                      _pool("uniswap-v4", 1e9, tokens=("0x" + "1" * 40,))]}
    o = share(ADDR, {"pools": pools, "protocols": PROTOCOLS, "fetched_at": 1789300000})
    assert (o.dex_liquidity_total_discovered, o.curve_mainnet_liquidity) == (100, 25)
    assert o.x == Decimal("0.75") and o.literal.startswith("75.0% of discovered DEX")
    assert o.date == "2026-09-13" and o.lineage == ["offvenue_llama"]
    for broken in (None, {"pools": {"data": []}, "protocols": PROTOCOLS, "fetched_at": 1},
                   {"pools": {}, "protocols": PROTOCOLS, "fetched_at": 1}):
        e = share(ADDR, broken)
        assert e.x is None and e.literal == NOT_COMPUTED


def _with_share(**kw):
    base = dict(dex_liquidity_total_discovered=100, curve_mainnet_liquidity=25,
                x=Decimal("0.75"), literal="75.0% of discovered DEX liquidity lies outside "
                "modeled venues", source="s", date="2026-09-13", fetched_at=1,
                lineage=["offvenue_llama"])
    base.update(kw)
    return ts.a_bundle(offvenue_share=OffvenueShare(**base))


def test_det32_routes_and_replays():
    t = SimpleNamespace(root=SimpleNamespace(supply_ruled=0))
    assert det_32(_with_share(), t).startswith("T-02 (L1)")
    assert "no trigger" in det_32(_with_share(curve_mainnet_liquidity=80, x=Decimal("0.2"),
                                              literal="20.0% of discovered DEX liquidity "
                                              "lies outside modeled venues"), t)
    none = _with_share(dex_liquidity_total_discovered=None, curve_mainnet_liquidity=None,
                       x=None, literal=NOT_COMPUTED)
    assert det_32(none, t).startswith("T-22 (L1)")
    for bad in (ts.a_bundle(), _with_share(x=Decimal("0.5")),
                _with_share(dex_liquidity_total_discovered=None)):
        with pytest.raises(Level3, match="DET-32"):
            det_32(bad, t)


def test_det32_lineage_refuses_an_offvenue_source():
    from tests.test_stress import _report
    r = _report()
    assert "no offvenue_" in det_32_lineage(None, None, r)
    r2 = r.model_copy(update={"exit_depth": r.exit_depth.model_copy(
        update={"reads": {"yields.llama.fi/pools": AnalystSupplied(source="x",
                                                                   date="2026-09-13")}})})
    with pytest.raises(Level3, match="off-venue fetch"):
        det_32_lineage(None, None, r2)


# --- DET-15 ------------------------------------------------------------------------------


def _supply_bundle(residual_causes, unexplained, **kw):
    b = ts.a_bundle()
    cause_reads = {"balance": ts.cr("balanceOf(address)")}
    sp = b.supply.model_copy(update={
        "residual_causes": [ResidualCause(family="f", address=ts.CTRL, amount=a,
                                          reads=cause_reads) for a in residual_causes],
        "residual_unexplained": unexplained, **kw})
    return b.model_copy(update={"supply": sp})


def test_det15_named_causes_close_within_the_bound():
    t = SimpleNamespace(root=SimpleNamespace(supply_ruled=2_104_809))
    b = _supply_bundle([104_800], 9, origination_sum=2_000_000)
    b = b.model_copy(update={"markets": [b.markets[0].model_copy(
        update={"principal_sum": 2_000_000, "gross_debt_sum": 2_000_000 + 0,
                "accrued_interest_sum": 0})]})
    assert "unexplained 9" in det_15(b, t)
    with pytest.raises(Level3, match="unexplained"):
        det_15(_supply_bundle([100_000], 4_809).model_copy(update={"markets": b.markets}), t)
    with pytest.raises(Level3, match="residual_unexplained"):
        det_15(_supply_bundle([104_800], 0).model_copy(update={"markets": b.markets}), t)
    with pytest.raises(Level3, match="DET-15\\(b\\)"):
        det_15(_supply_bundle([104_800], 9, origination_sum=1), t)


# --- DET-05 ------------------------------------------------------------------------------


def test_det05_replays_net_and_residual():
    b = ts.a_bundle()
    usdc = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
    crv = "0xf939e0a03fb07f59a73314e73794be0e57ac1b4e"
    lp, sup, p6, stable = 10, 40, 3_000_000, 5 * 10 ** 18
    net = lp * p6 * 10 ** 12 // sup
    op = b.stabilizer.operations[0].model_copy(update={
        "paired_asset_address": usdc, "pool_composition": {usdc: p6, crv: stable},
        "coin_decimals": {usdc: 6, crv: 18}, "lp_balance": lp, "lp_total_supply": sup,
        "protocol_lp_share": Decimal("0.25"), "net_non_self_referential_value": net,
        "residual": lp * (p6 * 10 ** 12 + stable) // sup - 0})
    ok = b.model_copy(update={"stabilizer": b.stabilizer.model_copy(update={"operations": [op]})})
    assert "replay at par" in det_05(ok, None)
    bad = op.model_copy(update={"residual": 1})
    with pytest.raises(Level3, match="DET-05\\(d\\)"):
        det_05(ok.model_copy(update={"stabilizer": ok.stabilizer.model_copy(
            update={"operations": [bad]})}), None)
    with pytest.raises(Level3, match="position fields absent"):
        det_05(b, None)


# --- DET-55's enums, DET-71, DET-76(e) --------------------------------------------------


def test_det55_sets_the_counterfactual_per_token():
    b = ts.a_bundle()
    det_55(b, {})
    tellor = b.oracle_rows[0].model_copy(update={"counterfactual_ref": "Tellor_fallback"})
    with pytest.raises(Level3, match="off crvUSD"):
        det_55(b.model_copy(update={"oracle_rows": [tellor]}), {})


def _lusd_surface(**row_kw):
    b = ts.a_bundle()
    owner = {"owner:" + ts.CTRL: ContractRead(source_contract=ts.CTRL, function="owner()",
                                             block=RB),
             "owner:" + ts.CF: AbsenceRead(contract=ts.CF, method="selector_absence_scan",
                                           evidence="owner() absent", block=RB)}
    rows = [r.model_copy(update={"upgradeability": "immutable", "reads": owner, **row_kw})
            for r in b.admin_surface]
    return b.model_copy(update={"admin_surface": rows,
                                "header": b.header.model_copy(update={"token": "LUSD"})})


def test_det71_control_surface():
    assert det_71(ts.a_bundle(), {}) is None            # not the control: not applicable
    assert det_71(_lusd_surface(), {}) is None
    with pytest.raises(Level3, match="A6"):
        det_71(_lusd_surface(upgradeability=None), {})
    with pytest.raises(Level3, match="no owner"):
        det_71(_lusd_surface(reads={}), {})


def test_det76e_needs_the_pair_with_provenance():
    b = ts.a_bundle()
    assert det_76e(b, {}) is None
    n = b.nodes[0]
    for upd, msg in (({"last_disclosure_date": None}, "staleness uncomputable"),
                     ({"disclosure_cadence": None}, "no disclosure_cadence"),
                     ({"reads": {"balance": n.reads["balance"]}}, "without provenance")):
        with pytest.raises(Level3, match=msg):
            det_76e(b.model_copy(update={"nodes": [n.model_copy(update=upd)]}), {})


# --- the read modules --------------------------------------------------------------------


class _R:
    def __init__(self, value, ok=True):
        self.ok, self.value = ok, (value if isinstance(value, tuple) else (value,))
        self.provenance = ContractRead(source_contract=ts.CF, function="f()", block=RB)

    def one(self):
        return self.value[0]


class _Rpc:
    run_block, block_timestamp = RB, 1_789_300_000

    def __init__(self, answers):
        self.answers = answers

    def read(self, calls):
        return [self.answers[c.signature] for c in calls]


def _cfg(row, por=()):
    return SimpleNamespace(disclosures={ts.COL: row}, por_feeds=list(por))


def test_disclosure_read_forms():
    dated = {"disclosure_cadence": "monthly", "last_disclosure_date": "2026-07-31",
             "source": "ANALYST-SUPPLIED 2026-09-13: page", "inherited_from": "USDC"}
    d, n = disclosure_fields(_cfg(dated), _Rpc({}), ts.COL)
    assert (d["last_disclosure_date"], n) == ("2026-07-31", 0)
    assert str(d["reads"]["last_disclosure_date"].date) == "2026-09-13"
    por_row = {"disclosure_cadence": "continuous", "last_disclosure_date": "per-run read",
               "source": "ANALYST-SUPPLIED 2026-09-13: x"}
    por = {"node_address": ts.COL, "feed_address": ts.CF, "description": "WBTC PoR",
           "heartbeat": 86400}
    rpc = _Rpc({"description()": _R("WBTC PoR"),
                "latestRoundData()": _R((1, 1, 0, 1_789_200_000, 1))})
    d, n = disclosure_fields(_cfg(por_row, [por]), rpc, ts.COL)
    assert d["last_disclosure_date"] == "2026-09-12" and "age 100000 s" in d["flags"][0]
    assert "older than heartbeat" in d["flags"][0]
    rpc.answers["description()"] = _R("WBTC Proof of Reserves")
    with pytest.raises(DisclosureStop, match="description"):
        disclosure_fields(_cfg(por_row, [por]), rpc, ts.COL)


def test_feed_row_identity_and_forms():
    row = {"symbol": "WBTC", "feed": ts.CF, "type": "deviation_heartbeat", "deviation_bps": 50,
           "heartbeat_s": 3600, "heartbeat_form": "documented", "source": "dir",
           "date": "2026-09-13"}
    uc = condition_from_row(row, ts.CF, 1, 2, [])
    assert (uc.deviation.value_bps, uc.heartbeat_s.value, uc.heartbeat_s.form) == (50, 3600,
                                                                                   "documented")
    with pytest.raises(FeedStop, match="signed feed"):
        condition_from_row(row, ts.CTRL, 1, 2, [])
    nav = dict(row, type="nav_schedule", heartbeat_form="observed_max")
    with pytest.raises(FeedStop, match="without a read"):
        condition_from_row(nav, ts.CF, 1, 2, [])


# --- R18: the stress label reads the tree ----------------------------------------------


def test_label_of_prefers_the_trees_row():
    cfg = SimpleNamespace(paired={ts.COL: SimpleNamespace(label="recurses_truncated")},
                          labels={})
    flags: list = []
    assert _label_of(cfg, ts.COL, flags) == "recurses_truncated"
    assert _label_of(cfg, ts.COL, flags, {ts.COL: "linked"}) == "linked"
    assert _label_of(cfg, ts.CF, flags, {ts.COL: "linked"}) == "unlabeled"


# --- P-7.05's ruling on S1: the off-mainnet facilitator line ------------------------


def test_gho_tree_names_the_off_mainnet_line_outside_the_bars():
    from factory.tree import OFF_MAINNET_LITERAL, latest_bundle, latest_tree
    from factory.validate.harness import det_19
    b, t = latest_bundle(REPO, "GHO"), latest_tree(REPO, "GHO")
    om = t.off_mainnet_line
    assert om.amount == 150_000_000 * 10 ** 18 and om.literal == OFF_MAINNET_LITERAL
    assert om.share_of_supply_ruled == Decimal(150) / Decimal(699)
    assert t.denominators["off_mainnet_line.share_of_supply_ruled"] == "supply_ruled"
    assert {x.denominator for x in t.bars} == {"backing_value"}
    det_19(b, t)
    bad = t.model_copy(update={"off_mainnet_line": om.model_copy(
        update={"share_of_supply_ruled": Decimal("0.5")})})
    with pytest.raises(Level3, match="off-mainnet line"):
        det_19(b, bad)
    assert latest_tree(REPO, "crvUSD").off_mainnet_line is None
