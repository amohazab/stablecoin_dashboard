"""GHO build slice 1: the log pointer's window walk, and the facilitator /
GSM readers. Synthetic throughout — nothing here touches the network."""

from __future__ import annotations

import pytest

from factory.adapters.gho import (
    GhoAdapterIncomplete,
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
    with pytest.raises(GhoAdapterIncomplete, match="supply identity broken"):
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
