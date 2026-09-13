"""GHO build slice 1: the log pointer's window walk, and the facilitator /
GSM readers. Synthetic throughout — nothing here touches the network."""

from __future__ import annotations

import pytest

from factory.adapters.gho import (
    GhoAdapterStop,
    check_supply_identity,
    read_facilitators,
    read_gsms,
)
from factory.logs_pointer import PAGE_SIZE, PointerError, get_logs
from factory.provenance import ContractRead
from factory.rpc import Call, ReadResult

GHO = "0x40d16fc0246ad3160ccc09b8d0d3a2cd28ae6c2f"
REGISTRY = "0x167527db01325408696326e3580cd8e55d99dc1a"
MINTER = "0x5513224daaeabca31af5280727878d52097afa05"
FUNDER = "0xe9ac5231faecb633da0fe85fcb2785b8363427d2"
FLASH = "0xb639d208bcf0589d54fac24e655c79ec529762b8"
POOL = "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2"
GSM = "0x882285e62656b9623af136ce3078c6bdcc33f5e3"
WAUSDT = "0x7bc3485026ac48b6cf9baf0a377477fff5703af8"
ZERO = "0x0000000000000000000000000000000000000000"
RB = 25930871
E = 10 ** 18


class FakeRpc:
    """Same posture as `test_discovery.FakeRpc`: an unmodelled read comes back
    as a FAILURE, never a zero. The DET-28 probe relies on that — a selector
    the contract does not expose must not look like an answer."""

    def __init__(self, table: dict, run_block: int = RB):
        self.table = table
        self.run_block = run_block

    def read(self, calls: list[Call]) -> list[ReadResult]:
        out = []
        for c in calls:
            key = (c.target.lower(), c.signature, tuple(str(a) for a in c.args))
            prov = ContractRead(source_contract=c.target.lower(), function=c.signature,
                                args=[str(a) for a in c.args], block=self.run_block)
            if key in self.table:
                out.append(ReadResult(c, True, self.table[key], prov))
            else:
                out.append(ReadResult(c, False, None, prov, "call reverted"))
        return out


# --- the pointer's window walk -----------------------------------------------


def _rows(n: int, start_block: int):
    return [{"topics": ["0xaa", "0xbb", "0x" + "0" * 24 + f"{i:040x}"[-40:]],
             "data": "0x", "blockNumber": hex(start_block + i)} for i in range(n)]


def test_pointer_rewindows_at_the_ten_thousand_row_cap():
    """P-4.04 probe (b): Etherscan caps `page x offset <= 10000`, so a full
    window must re-anchor at `fromBlock = last + 1` rather than page on."""
    seen = []

    def http_get(url, params):
        seen.append((params["fromBlock"], params["page"]))
        if params["fromBlock"] == 100:
            # ten full pages -> the window is saturated
            return {"status": "1", "result": _rows(PAGE_SIZE, 100 + params["page"] * 1000)}
        if params["fromBlock"] > 100 and params["page"] == 1:
            return {"status": "1", "result": _rows(7, 20_000)}
        return {"status": "0", "message": "No records found", "result": []}

    ptr = get_logs("0xabc", ["0xaa", None], 100, 30_000, http_get, "KEY")
    assert ptr.windows == 2 and ptr.row_count == PAGE_SIZE * 10 + 7
    assert [p for f, p in seen if f == 100] == list(range(1, 11))   # ten pages, then stop
    reanchor = next(f for f, p in seen if f != 100)
    assert reanchor == 11_100                                       # last block + 1
    rec = ptr.record()
    assert "apikey" not in str(rec) and "KEY" not in str(rec)       # P-3.39 binding 1
    assert rec["row_count"] == ptr.row_count and rec["windows"] == 2


def test_pointer_shape_change_is_a_stop_not_a_shrug():
    def http_get(url, params):
        return {"status": "1", "result": [{"data": "0x", "blockNumber": "0x1"}]}

    with pytest.raises(PointerError, match="SHAPE CHANGE"):
        get_logs("0xabc", ["0xaa"], 1, 2, http_get, "KEY")


# --- facilitators -------------------------------------------------------------


def _fac_table():
    t = {
        (GHO, "getFacilitatorsList()", ()): ([MINTER, FUNDER, FLASH],),
        (GHO, "getFacilitator(address)", (MINTER,)): ((250 * E, 135 * E, "CoreGhoDirectMinter"),),
        (GHO, "getFacilitatorBucket(address)", (MINTER,)): (250 * E, 135 * E),
        (GHO, "getFacilitator(address)", (FUNDER,)): ((310 * E, 310 * E, "GSMs Mainnet"),),
        (GHO, "getFacilitatorBucket(address)", (FUNDER,)): (310 * E, 310 * E),
        (GHO, "getFacilitator(address)", (FLASH,)): ((0, 0, "FlashMinter Facilitator"),),
        (GHO, "getFacilitatorBucket(address)", (FLASH,)): (0, 0),
        # what each one ANSWERS is the whole classification (DET-28)
        (MINTER, "POOL()", ()): (POOL,),
        (MINTER, "GHO_TOKEN()", ()): (GHO,),
        (FUNDER, "GHO_TOKEN()", ()): (GHO,),
        (FLASH, "maxFlashLoan(address)", (GHO,)): (2 * E,),
        (FLASH, "GHO_TOKEN()", ()): (GHO,),
    }
    return t


def test_facilitator_class_comes_from_the_selector_probe_not_the_label():
    rows, n = read_facilitators(FakeRpc(_fac_table()), GHO)
    by = {r.address: r for r in rows}
    assert by[MINTER].facilitator_class == "direct_minter"
    assert by[MINTER].pool_address == POOL
    assert by[FLASH].facilitator_class == "flash_minter"
    # THE FINDING (P-4.06): the GSM funder and the off-mainnet facilitators
    # answer only `GHO_TOKEN()`, so the probe cannot separate them. It says so
    # rather than reading "GSMs Mainnet" out of the label string.
    assert by[FUNDER].facilitator_class == "unresolved"
    assert by[FUNDER].class_evidence == ["GHO_TOKEN()"]
    assert by[FUNDER].pool_address is None
    assert n == 1 + 3 * (2 + 4)


def test_zero_capacity_facilitator_takes_the_o1_absence():
    rows, _ = read_facilitators(FakeRpc(_fac_table()), GHO)
    flash = next(r for r in rows if r.address == FLASH)
    assert flash.utilization is None and flash.utilization_na_reason == "ceiling_zero"


def test_supply_identity_is_never_reconciled_away():
    rows, _ = read_facilitators(FakeRpc(_fac_table()), GHO)
    check_supply_identity(rows, 445 * E)                     # 135 + 310 + 0
    assert sum(r.bucket_level for r in rows) == 445 * E


def test_supply_identity_mismatch_stops():
    rows, _ = read_facilitators(FakeRpc(_fac_table()), GHO)
    with pytest.raises(GhoAdapterStop, match="supply identity broken"):
        check_supply_identity(rows, 446 * E)


# --- GSMs ---------------------------------------------------------------------


def test_gsm_row_reads_state_and_leaves_h2_present_and_empty():
    """With no pointer injected the freezer is not guessed: the H2 fields stay
    None rather than being filled from a configured address."""
    t = {
        (REGISTRY, "getGsmList()", ()): ([GSM],),
        (GSM, "UNDERLYING_ASSET()", ()): (WAUSDT,),
        (GSM, "getExposureCap()", ()): (85_000_000_000_000,),
        (GSM, "getAvailableLiquidity()", ()): (23_287_192_725_515,),
        (GSM, "getAvailableUnderlyingExposure()", ()): (61_712_807_274_485,),
        (GSM, "getIsFrozen()", ()): (False,),
        (GSM, "getIsSeized()", ()): (False,),
        (GSM, "PRICE_STRATEGY()", ()): (ZERO,),
        (GSM, "getFeeStrategy()", ()): (ZERO,),
        (GSM, "getGhoTreasury()", ()): (ZERO,),
    }
    (row,), n = read_gsms(FakeRpc(t), REGISTRY)
    assert row.address == GSM and row.underlying_asset == WAUSDT
    assert row.available_liquidity == 23_287_192_725_515
    assert row.is_frozen is False and row.is_seized is False
    assert row.freezer_address is None and row.freezer_role_confirmed is False
    assert set(row.reads) == {sig for sig, _ in
                              __import__("factory.adapters.gho", fromlist=["x"]).GSM_READS}
    assert n == 1 + 9


# --- positions, principal, attribution (2a) -----------------------------------


def _pos(**kw):
    from factory.schema import GhoPosition
    base = dict(borrower=MINTER, instance=POOL, gross_debt=100, principal=60,
                accrued_interest=40, gho_debt_base=100, total_debt_base=200,
                collateral={WAUSDT: 1000})
    base.update(kw)
    return GhoPosition(**base)


def test_principal_never_exceeds_gross_on_a_position_row():
    """P-4.04-A1's invariant, proven on all 2,142 live positions, as a row
    validator: R7 without `LiquidationCall` would put 128 of them here."""
    with pytest.raises(Exception, match="principal 140 > gross"):
        _pos(principal=140, accrued_interest=-40)


def test_attribution_is_pro_rata_not_the_whole_collateral():
    """memo §11.1: half the borrower's debt is GHO, so half the collateral is
    credited. Crediting all of it is the upper bound, not the attribution."""
    from factory.adapters.gho import attribute_nodes
    assert attribute_nodes([_pos()])[WAUSDT] == 500
    assert attribute_nodes([_pos(gho_debt_base=200)])[WAUSDT] == 1000   # share caps at 1
    assert attribute_nodes([_pos(total_debt_base=0)]) == {}             # no denominator, no claim


def test_det03_gho_clause_reads_the_facilitator_rows():
    """Dispatched on the table the token carries, not on the token name."""
    from factory.schema import Facilitator
    from factory.validate.harness import Level3, det_03

    def fac(**kw):
        base = dict(address=MINTER, label="x", bucket_capacity=10, bucket_level=5,
                    utilization=None, facilitator_class="direct_minter",
                    class_evidence=["POOL()"], pool_address=POOL,
                    principal_sum=60, accrued_interest_sum=40, gross_debt_sum=100,
                    reads={})
        base.update(kw)
        base["utilization"] = None if base["bucket_capacity"] == 0 else 1
        base["utilization_na_reason"] = "ceiling_zero" if base["bucket_capacity"] == 0 else None
        return base

    class B:
        markets: list = []
        facilitators: list = []
    b = B()
    ok = Facilitator(**fac(reads={
        "principal": ContractRead(source_contract=POOL, function="Borrow", args=[], block=RB),
        "gross_debt": ContractRead(source_contract=GSM, function="balanceOf(address)",
                                   args=[], block=RB)}))
    b.facilitators = [ok]
    det_03(b, {})                                            # two distinct reads: passes
    b.facilitators = [ok.model_copy(update={"reads": {
        "principal": ContractRead(source_contract=POOL, function="Borrow", args=[], block=RB)}})]
    with pytest.raises(Level3, match="anti-tautology"):
        det_03(b, {})


# --- 2b surfaces --------------------------------------------------------------


def test_role_holders_uses_logs_as_pointer_and_hasrole_as_verdict():
    """P-4.04 R5. A holder that was granted then revoked must NOT come back;
    a holder revoked then re-granted MUST — which is only true if the verdict
    is a state read rather than a replay of the log."""
    from factory.adapters.gho import ROLE_GRANTED, ROLE_REVOKED, role_holders
    A = "0x1111111111111111111111111111111111111111"
    B = "0x2222222222222222222222222222222222222222"
    role = b"" * 32
    rows = {ROLE_GRANTED: [A, B], ROLE_REVOKED: [A]}

    def http_get(url, params):
        who = rows.get(params.get("topic0"), [])
        return {"status": "1", "result": [
            {"topics": [params["topic0"], params["topic1"],
                        "0x" + "0" * 24 + w[2:]], "data": "0x",
             "blockNumber": "0x1"} for w in who]}

    rpc = FakeRpc({(GSM, "hasRole(bytes32,address)", (str(role), B)): (True,),
                   (GSM, "hasRole(bytes32,address)", (str(role), A)): (False,)})
    held, ptrs, n = role_holders(GSM, role, rpc, http_get, "KEY", 0)
    assert held == [B] and n == 2 and len(ptrs) == 2


def test_unlabeled_config_row_emits_unlisted_and_keeps_its_reason():
    """The tree's label set is closed (memo §4.2), so an `unlabeled` config row
    cannot introduce a fifth state: it emits §8.2's `unlisted` and its reason
    rides in `flags`, so 'ruling owed' stays distinguishable from 'no row'."""
    import datetime as dt
    from pathlib import Path

    from factory.adapters.gho import _nodes
    from factory.config import Config, LabelRow, LendFactories, LendState
    node = "0x5a0f93d040de44e78f251b03c43be9cf317dcf64"
    cfg = Config(token="GHO", frozen_set_path=Path("x"), roots={},
                 labels={node: LabelRow(node, "JAAA", "volatile", False, "P-4.08",
                                        dt.date(2026, 9, 8), "unlabeled",
                                        "no memo 4.5 row", "3.973%")},
                 paired={}, lend=LendFactories(LendState.EXPLICIT_EMPTY), sheet={})
    rpc = FakeRpc({(node, "decimals()", ()): (18,),
                   (POOL, "getAssetPrice(address)", (node,)): (10 ** 8,)})
    rows, _ = _nodes(cfg, {node: 10 ** 18}, {node: [POOL]}, rpc, [POOL], {POOL: POOL})
    (r,) = rows
    assert r.label == "unlisted"                      # never a fifth state
    assert "no memo 4.5 row" in r.flags[0] and "3.973%" in r.flags[0]


def test_det55_dispatches_on_the_update_condition_type():
    """P-4.08, widened at B-9: DET-55 dispatches on the update-condition type.
    A `deviation_heartbeat` row needs both a heartbeat `{form, value,
    provenance}` and a class-I `deviation`; a `nav_schedule` row (A-19) needs
    only the heartbeat; the present-and-empty branch is gone."""
    import tests.test_schema as ts
    from factory.provenance import AnalystSupplied
    from factory.schema import Deviation, DeviationHeartbeat, HeartbeatS, NavSchedule
    from factory.validate.harness import Level3, det_55
    b = ts.a_bundle()
    row = b.oracle_rows[0]
    signed = AnalystSupplied(source="fixture", date="2026-09-13")
    hb = HeartbeatS(form="documented", value=3600, provenance=signed)
    dev = DeviationHeartbeat(heartbeat_s=hb, provenance=[],
                             deviation=Deviation(value_bps=50, analyst_supplied=signed))
    for uc in (dev, NavSchedule(heartbeat_s=hb, provenance=[])):
        det_55(b.model_copy(update={"oracle_rows": [row.model_copy(
            update={"update_condition": uc, "staleness_check": None})]}), {})
    for uc, msg in ((dev.model_copy(update={"deviation": None}), "deviation absent"),
                    (dev.model_copy(update={"heartbeat_s": None}), "heartbeat_s absent")):
        with pytest.raises(Level3, match=msg):
            det_55(b.model_copy(update={"oracle_rows": [row.model_copy(
                update={"update_condition": uc})]}), {})


# --- C2: the boxed-asset walk and its nodes -----------------------------------


AUSDT = "0x23878914efe38d27c4d67ab83ed1b93a74d4086a"
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"


def _gsm_row(**kw):
    from factory.schema import Gsm
    base = dict(address=GSM, underlying_asset=WAUSDT, exposure_cap=85 * 10 ** 12,
                available_liquidity=1_000_000, available_underlying_exposure=0,
                is_frozen=False, is_seized=False, price_strategy=ZERO,
                fee_strategy=ZERO, gho_treasury=ZERO, reads={})
    base.update(kw)
    return Gsm(**base)


def _walk_table(atoken_underlying: str = USDT, **over):
    t = {
        (WAUSDT, "asset()", ()): (USDT,),
        (WAUSDT, "aToken()", ()): (AUSDT,),
        (WAUSDT, "symbol()", ()): ("waEthUSDT",),
        (WAUSDT, "decimals()", ()): (6,),
        (WAUSDT, "convertToAssets(uint256)", ("1000000",)): (1_174_832,),
        (AUSDT, "UNDERLYING_ASSET_ADDRESS()", ()): (atoken_underlying,),
        (AUSDT, "symbol()", ()): ("aEthUSDT",),
        (AUSDT, "decimals()", ()): (6,),
        (USDT, "symbol()", ()): ("USDT",),
        (USDT, "decimals()", ()): (6,),
    }
    t.update(over)
    return t


def test_the_boxed_walk_closes_and_is_confirmed_from_both_ends():
    """R-C2.1: the accessors come from `StataTokenV2`'s verified ABI, and the
    aToken's own `UNDERLYING_ASSET_ADDRESS()` must agree with the wrapper's
    `asset()` — one end could be a mislabelled wrapper; two cannot."""
    from factory.adapters.gho import boxed_asset_walk
    (w,), n = boxed_asset_walk(FakeRpc(_walk_table()), [_gsm_row()])
    assert (w["wrapper"], w["atoken"], w["underlying"]) == (WAUSDT, AUSDT, USDT)
    assert w["converted"] == 1_174_832 and w["shares"] == 1_000_000
    assert w["symbol"] == "waEthUSDT" and w["underlying_symbol"] == "USDT"
    assert n == 10


def test_a_walk_that_disagrees_at_its_two_ends_stops_the_run():
    from factory.adapters.gho import boxed_asset_walk
    t = _walk_table(atoken_underlying=GHO)
    with pytest.raises(GhoAdapterStop, match="disagrees at its two ends"):
        boxed_asset_walk(FakeRpc(t), [_gsm_row()])


def test_a_wrapper_that_does_not_answer_the_erc4626_walk_stops():
    """A GSM whose boxed asset is the bare stable answers no `asset()`. That is
    an identity the run does not have, never a fallback to the wrapper."""
    from factory.adapters.gho import boxed_asset_walk
    t = {k: v for k, v in _walk_table().items() if k[1] != "asset()"}
    with pytest.raises(GhoAdapterStop, match="does not answer the ERC-4626 walk"):
        boxed_asset_walk(FakeRpc(t), [_gsm_row()])


def _cfg_with(rows: dict):
    from pathlib import Path

    from factory.config import Config, LendFactories, LendState
    return Config(token="GHO", frozen_set_path=Path("x"), roots={}, labels=rows,
                  paired={}, lend=LendFactories(LendState.EXPLICIT_EMPTY), sheet={})


def _row(addr, symbol, label="recurses"):
    import datetime as dt

    from factory.config import LabelRow
    return LabelRow(addr, symbol, "stable", False, "C2 row", dt.date(2026, 9, 12), label)


def test_the_boxed_node_is_wrapper_keyed_and_labelled_from_its_own_row():
    """R-C2.4 / R-C2.6: the node's address is the WRAPPER's, its label comes
    from the wrapper's own dated row (DET-02 forbids sourcing across an
    address), and its VALUE is the converted amount at the underlying's price —
    `getAssetPrice(wrapper)` would be zero, the wrapper being no reserve."""
    from factory.adapters.gho import _nodes, boxed_asset_walk
    cfg = _cfg_with({WAUSDT: _row(WAUSDT, "waEthUSDT"), USDT: _row(USDT, "USDT")})
    rpc = FakeRpc({**_walk_table(), (POOL, "getAssetPrice(address)", (USDT,)): (10 ** 8,)})
    walk, _ = boxed_asset_walk(rpc, [_gsm_row()])
    rows, _ = _nodes(cfg, {}, {}, rpc, [POOL], {POOL: POOL}, None, walk)
    (r,) = rows
    assert r.address == WAUSDT and r.label_source_address == WAUSDT    # DET-02
    assert r.symbol == "waEthUSDT" and r.label == "recurses"
    assert r.value == 117_483_200            # 1.174832 USDT at $1.00, 8-dp USD
    assert r.share_of_backing == 1 and r.lineage == ["gsm_read", "price_read"]
    assert "aEthUSDT" in r.flags[0] and "convert" in r.reads


def test_a_boxed_asset_without_its_own_dated_row_stops_on_det_02():
    from factory.adapters.gho import _nodes, boxed_asset_walk
    cfg = _cfg_with({USDT: _row(USDT, "USDT")})
    rpc = FakeRpc(_walk_table())
    walk, _ = boxed_asset_walk(rpc, [_gsm_row()])
    with pytest.raises(GhoAdapterStop, match="no dated label row"):
        _nodes(cfg, {}, {}, rpc, [POOL], {POOL: POOL}, None, walk)
