"""B-3a synthetic tests: discovery routing, provenance, DET-07/DET-21, lend states.

These prove the routing. Only the live execution proves the data (P-3.17).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from factory.adapters.crvusd import (
    AddressReconciliation,
    DiscoveredKeeper,
    confirm_node_addresses,
    discover_lend_markets,
    discover_mint_markets,
    discover_pegkeepers,
)
from factory.config import Config, LabelRow, LendFactories, LendState, Root, load
from factory.provenance import ContractRead
from factory.rpc import Call, ReadResult, RpcReadError

CF = "0xc9332fdcb1c491dcc683bae86fe3cb70360738bc"
REG = "0x36a04caffc681fa179558b2aaba30395cddd855f"
CRVUSD = "0xf939e0a03fb07f59a73314e73794be0e57ac1b4e"
RUN_BLOCK = 21_000_000

WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
CBBTC = "0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf"
UNKNOWN = "0x1111111111111111111111111111111111111111"


class FakeRpc:
    """Canned reads. Anything not in the table comes back as a FAILURE, which
    is the correct default: unmodelled reads must not silently yield zeros."""

    def __init__(self, table: dict, run_block: int = RUN_BLOCK):
        self.table = table
        self.run_block = run_block

    def read(self, calls: list[Call]) -> list[ReadResult]:
        out = []
        for c in calls:
            key = (c.target.lower(), c.signature, tuple(str(a) for a in c.args))
            prov = ContractRead(
                source_contract=c.target.lower(),
                function=c.signature,
                args=[str(a) for a in c.args],
                block=self.run_block,
            )
            if key in self.table:
                out.append(ReadResult(c, True, self.table[key], prov))
            else:
                out.append(ReadResult(c, False, None, prov, "call reverted"))
        return out


def _market_table(collaterals: list[str]) -> dict:
    t = {(CF, "n_collaterals()", ()): (len(collaterals),)}
    for i, col in enumerate(collaterals):
        t[(CF, "controllers(uint256)", (str(i),))] = (f"0xC0{i:038x}",)
        t[(CF, "amms(uint256)", (str(i),))] = (f"0xA0{i:038x}",)
        t[(CF, "collaterals(uint256)", (str(i),))] = (col,)
    return t


def _cfg(labels: dict[str, LabelRow] | None = None, lend: LendFactories | None = None) -> Config:
    roots = {
        "controller_factory": Root(
            "controller_factory", CF, "mint-market discovery",
            "deployments.json", dt.date(2026, 9, 1),
        ),
        "pegkeeper_regulator": Root(
            "pegkeeper_regulator", REG, "keeper discovery", "regulator source", dt.date(2026, 9, 1)
        ),
        "crvusd_token": Root("crvusd_token", CRVUSD, "token", "sheet", dt.date(2026, 9, 1)),
    }
    return Config(
        token="crvUSD", frozen_set_path=Path("config/frozen_set_crvusd.json"),
        roots=roots,
        labels=labels or {},
        paired={},
        lend=lend or LendFactories(LendState.NOT_CONFIGURED),
        sheet={},
    )


# --- DET-07 / DET-01 / DET-04 ------------------------------------------------


def test_origination_class_assigned_from_factory_address_in_provenance():
    """DET-07: assignment source is the factory ADDRESS, never a symbol."""
    rpc = FakeRpc(_market_table([WETH, CBBTC]))
    markets = discover_mint_markets(rpc, _cfg())

    assert [m.collateral for m in markets] == [WETH, CBBTC]
    for m in markets:
        assert m.origination_class == "mint"
        # the assignment is readable back out of provenance
        assert m.origination_provenance.source_contract == CF
        assert m.origination_provenance.function == "controllers(uint256)"
        assert m.origination_provenance.block == RUN_BLOCK  # DET-04 / R-13
        assert m.controller == m.controller.lower()  # DET-01 lowercase


def test_discovery_fails_closed_when_a_read_reverts():
    """A missing read is a failure, not an empty market list."""
    table = _market_table([WETH])
    del table[(CF, "collaterals(uint256)", ("0",))]
    with pytest.raises(RpcReadError, match="collaterals"):
        discover_mint_markets(FakeRpc(table), _cfg())


def test_duplicate_controller_address_rejected():
    """DET-01: no duplicate address within a table."""
    table = _market_table([WETH, CBBTC])
    table[(CF, "controllers(uint256)", ("1",))] = table[(CF, "controllers(uint256)", ("0",))]
    with pytest.raises(ValueError, match="duplicate controller"):
        discover_mint_markets(FakeRpc(table), _cfg())


# --- DET-20 / DET-21 ---------------------------------------------------------


def test_pegkeepers_discovered_from_regulator_with_per_read_provenance():
    """P4: the set comes from the regulator. DET-20: provenance per read."""
    pk = "0x9201da0d97caaaff53f01b2fb56767c7072de340"
    pool = "0xd0e0000000000000000000000000000000000001"
    table = {
        (REG, "peg_keepers(uint256)", ("0",)): (pk, pool, False, True),
        (pk, "debt()", ()): (25_000_000,),
        (CRVUSD, "balanceOf(address)", (pk,)): (75_000_000,),
        (CF, "debt_ceiling(address)", (pk,)): (100_000_000,),
    }
    (k,) = discover_pegkeepers(FakeRpc(table), _cfg())

    assert k.operation_address == pk and k.paired_pool_address == pool
    assert k.discovery_provenance.source_contract == REG
    assert k.discovery_provenance.function == "peg_keepers(uint256)"
    for fld in ("current_debt", "balance", "debt_ceiling"):
        assert k.reads[fld].block == RUN_BLOCK
    assert k.reads["debt_ceiling"].source_contract == CF  # ControllerFactory, per A-4
    assert k.utilization == pytest.approx(0.25)
    assert k.utilization_na_reason is None


def test_utilization_ceiling_zero_branch_holds_no_prose():
    """DET-21 / R-11 / O-1: None + reason code; the literal is rendered, not stored."""
    k = DiscoveredKeeper(
        operation_address=CRVUSD,
        paired_pool_address=CRVUSD,
        debt_ceiling=0,
        current_debt=5,
        balance=1,
        discovery_provenance=ContractRead(
            source_contract=REG, function="peg_keepers(uint256)", args=[], block=RUN_BLOCK
        ),
    )
    assert k.utilization is None
    assert k.utilization_na_reason == "ceiling_zero"


# --- three-state lend design (P-3.17) ---------------------------------------


@pytest.mark.parametrize(
    "lend,expected",
    [
        (LendFactories(LendState.NOT_CONFIGURED), "unknown - no lend exclusion data configured"),
        (LendFactories(LendState.EXPLICIT_EMPTY), "n/a - no lend factories exist"),
        (LendFactories(LendState.POPULATED, ("0xabc",)), 1),
    ],
)
def test_lend_states_are_three_not_two(lend, expected):
    assert lend.market_count_field == expected
    assert lend.det07_exercisable is (lend.state is LendState.POPULATED)
    # the absent/empty cases must never read as "no lend markets exist"
    if lend.state is not LendState.POPULATED:
        assert "no lend markets exist" != lend.market_count_field


# --- node-address confirmation (P-3.15 follow-up 1) --------------------------


def test_node_address_confirmation_reports_both_directions():
    labels = {
        WETH: LabelRow(
            WETH, "WETH", "volatile", False, "memo 4.5", dt.date(2026, 9, 1), "terminal"
        ),
        CBBTC: LabelRow(
            CBBTC, "cbBTC", "volatile", False, "P1", dt.date(2026, 9, 2), "recurses"
        ),
    }
    rpc = FakeRpc(_market_table([WETH, UNKNOWN]))
    rec = confirm_node_addresses(discover_mint_markets(rpc, _cfg(labels)), _cfg(labels))

    assert rec.matched == (WETH,)
    assert rec.config_not_onchain == (CBBTC,)       # config row nothing on chain matches
    assert rec.onchain_not_in_config == (UNKNOWN,)  # becomes an unlisted node (§8.2/DET-08)
    assert rec.clean is False


def test_reconciliation_clean_when_sets_agree():
    labels = {
        WETH: LabelRow(WETH, "WETH", "volatile", False, "memo 4.5", dt.date(2026, 9, 1), "terminal")
    }
    rec = confirm_node_addresses(
        discover_mint_markets(FakeRpc(_market_table([WETH])), _cfg(labels)), _cfg(labels)
    )
    assert rec.clean and rec.matched == (WETH,)


# --- config loading against the real repo config -----------------------------


def test_lend_market_enumeration_counts_the_chain_not_the_rows():
    """3.1b: the count is the on-chain total across both signed factories, and
    the two factories use DIFFERENT index getters - which is why the signature
    is per-row config. The rows' `vaults` field is provenance, never a figure.
    """
    f1 = "0xea6876dde9e3467564acbee1ed5bac88783205e0"
    f2 = "0x8f6b56ec5ddf1f2691a1059f1d3cd97ac9eab0bd"
    m = ["0x%040x" % (0xA0 + i) for i in range(3)]      # 2 under f1, 1 under f2
    table = {
        (f1, "market_count()", ()): (2,),
        (f1, "vaults(uint256)", ("0",)): (m[1],),
        (f1, "vaults(uint256)", ("1",)): (m[0],),
        (f2, "market_count()", ()): (1,),
        (f2, "markets(uint256)", ("0",)): (m[2],),
    }
    cfg = Config(
        token="crvUSD", frozen_set_path=Path("config/frozen_set_crvusd.json"),
        roots={}, labels={}, paired={}, sheet={}, wallet_registries=[],
        reference_feeds=[], oracle_constituents={}, bridges=[],
        lend=LendFactories(
            LendState.POPULATED, (f1, f2),
            ({"address": f1, "count_getter": "market_count()",
              "market_getter": "vaults(uint256)", "vaults": 48},
             {"address": f2, "count_getter": "market_count()",
              "market_getter": "markets(uint256)", "vaults": 4})))
    got = discover_lend_markets(FakeRpc(table), cfg)
    assert len(got) == 3                       # the CHAIN total, not 2 factories
    assert [a for a, _f, _i in got] == sorted(m)          # address-sorted
    assert {f for _a, f, _i in got} == {f1, f2}
    # the rows' provenance fields are never the emitted figure
    assert sum(r["vaults"] for r in cfg.lend.rows) == 52 != len(got)


def test_repo_config_loads_and_lend_is_populated():
    cfg = load(Path(__file__).resolve().parents[1] / "config", "crvUSD")
    assert {"controller_factory", "pegkeeper_regulator", "price_aggregator",
            "crvusd_token"} <= set(cfg.roots)
    assert len([r for r in cfg.roots if r.startswith("pool_factory_")]) == 6  # P-3.23
    assert len(cfg.labels) == 8  # 7 at B-1 + LBTC (P-3.22 F1)
    assert cfg.labels["0x8236a87084f8b84306f72007f36f2618a5634494"].label == "recurses"
    assert cfg.labels[CBBTC].lst_discount_applies is False
    weeth = "0xcd5fe23c85820f7b72d0926fc9b05b43e359b7ee"
    assert cfg.labels[weeth].lst_discount_applies is True  # A3
    tbtc = "0x18084fba666a33d37592fa2633fd49a74dd93a88"
    assert cfg.labels[tbtc].label is None  # A5: resolved per run by FR-36
    # P-3.39 ruling 4, applied 2026-09-07: the two lend factories are signed,
    # so the three-state has advanced from NOT_CONFIGURED to POPULATED and
    # DET-07's exclusion is exercisable against real rows.
    assert cfg.lend.state is LendState.POPULATED
    assert cfg.lend.addresses == (
        "0xea6876dde9e3467564acbee1ed5bac88783205e0",
        "0x8f6b56ec5ddf1f2691a1059f1d3cd97ac9eab0bd")
    assert cfg.lend.det07_exercisable is True
    assert len(cfg.paired) == 7  # P-3.24: 7 labeled; pmUSD deliberately unlabeled
    assert cfg.paired["0xcea18a8752bb7e7817f9ae7565328fe415c0f2ca"].label == "terminal"
    assert "0xc0c17dd08263c16f6b64e772fb9b723bf1344ddf" not in cfg.paired  # pmUSD
    assert cfg.sheet["sheet_hash"] == "ad7c35c2"  # B-3b signed edit, 2026-09-13
    assert len(cfg.sheet["first_run_read"]) == 34


def test_isinstance_guard_for_reconciliation_type():
    assert isinstance(
        AddressReconciliation((), (), ()), AddressReconciliation
    )  # shape is a value object, not a dict


# --- 1b: the pointer source's shape-change gate ------------------------------


def test_pointer_shape_change_and_empty_class_halt_before_analysis():
    """Ruled P-3.46 R1: a shape change, an empty in-scope class and a transport
    failure all halt the token BEFORE analysis. No trigger ID accompanies them
    because the printed T-table has none, and DET-12 halts the pipeline on a
    runtime table that differs from the printed one."""
    from factory.discovery import AssemblyStopFromDiscovery, fetch_candidates

    def missing_field(_url):
        return {"data": {}}                       # `poolData` gone

    def empty_class(_url):
        return {"data": {"poolData": []}}

    def dead(_url):
        raise ConnectionError("pointer source down")

    for stub, needle in ((missing_field, "SHAPE CHANGE"),
                         (empty_class, "EMPTY pool list"),
                         (dead, "unavailable")):
        with pytest.raises(AssemblyStopFromDiscovery, match=needle):
            fetch_candidates(stub, ["factory-crvusd"])
