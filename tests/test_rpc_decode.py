"""B-2 decode tests (P-3.04's ruled fixture-based pair).

The aggregate3 return blobs are built with eth_abi's canonical encoder rather
than pasted from a live node — no RPC access exists yet. That makes these
round-trip tests against the reference encoder; a blob recorded from Alchemy
replaces the synthetic one at first contact (noted in the B-2 proposal).
"""

from __future__ import annotations

import pytest
from eth_abi import encode as abi_encode

from factory.provenance import ContractRead
from factory.rpc import Call, RpcClient, RpcReadError, encode_aggregate3, encode_call

CF = "0xc9332fdcb1c491dcc683bae86fe3cb70360738bc"
CRVUSD = "0xf939e0a03fb07f59a73314e73794be0e57ac1b4e"
RUN_BLOCK = 21_000_000


def _client() -> RpcClient:
    """An RpcClient with no network: decoding is pure, so bypass __init__."""
    c = RpcClient.__new__(RpcClient)
    c._run_block = RUN_BLOCK
    c._block_timestamp = 1_700_000_000
    c._run_start_time = 1_700_000_100
    return c


def _blob(entries: list[tuple[bool, bytes]]) -> bytes:
    return abi_encode(["(bool,bytes)[]"], [entries])


def test_failed_call_surfaces_as_failure_never_zero():
    """A reverted sub-call must not decode to 0 — the P-3.04 aggregate3 ground."""
    calls = [
        Call(CRVUSD, "totalSupply()", ("uint256",)),
        Call(CF, "debt_ceiling(address)", ("uint256",), (CRVUSD,)),
    ]
    raw = _blob(
        [
            (True, abi_encode(["uint256"], [123_456_789_000_000_000_000_000])),
            (False, b""),  # reverted
        ]
    )
    ok, bad = _client().decode_aggregate3(calls, raw)

    assert ok.ok is True
    assert ok.one() == 123_456_789_000_000_000_000_000

    assert bad.ok is False
    assert bad.value is None  # the whole point: not 0
    assert bad.error == "call reverted"
    with pytest.raises(RpcReadError, match="debt_ceiling"):
        bad.require()  # fails closed rather than yielding a default


def test_every_result_carries_provenance_pinned_to_run_block():
    """DET-04 / R-13: provenance present per read, block == run_block, always."""
    calls = [
        Call(CRVUSD, "totalSupply()", ("uint256",)),
        Call(CF, "debt_ceiling(address)", ("uint256",), (CRVUSD,)),
    ]
    raw = _blob([(True, abi_encode(["uint256"], [1])), (False, b"")])
    results = _client().decode_aggregate3(calls, raw)

    for r, call in zip(results, calls, strict=True):
        assert isinstance(r.provenance, ContractRead)
        assert r.provenance.block == RUN_BLOCK  # even on the failed read
        assert r.provenance.source_contract == call.target.lower()
        assert r.provenance.function == call.signature

    assert results[1].provenance.args == [CRVUSD]

    # calldata is selector + args, and the batch marks every call allowFailure
    assert calls[0].calldata == encode_call("totalSupply()")
    assert encode_aggregate3(calls).startswith(
        bytes.fromhex("82ad56cb")  # aggregate3((address,bool,bytes)[])
    )
