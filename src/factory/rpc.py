"""RPC layer: one pinned block per run, Multicall3 batching, provenance per read.

Three rules this module exists to enforce:
  * every Tier-1 read carries `block_identifier = run_block` (rubric 0.5, R-13);
  * a failed read is surfaced as a failure, never as a zero (P-3.04 aggregate3);
  * every value comes back with its own ContractRead provenance (DET-04, DET-20).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from eth_abi import decode as abi_decode
from eth_abi import encode as abi_encode
from eth_utils import function_signature_to_4byte_selector
from web3 import Web3

from factory.provenance import ContractRead

# Multicall3, same address on every chain it is deployed to. This is tooling
# infrastructure, not an enumerable protocol entity, so it is a named constant
# rather than a discovery root; no market/pool/collateral/stabilizer list is
# involved (memo section 9).
MULTICALL3 = "0xca11bde05977b3631167028862be2a173976ca11"

# Named implementer defaults ------------------------------------------------
# Reorg margin: a block at the chain head can be reorged out, which would make
# the run's pinned block — and every provenance record citing it — unverifiable
# after the fact. Six blocks is ~72 s on mainnet, far past typical post-merge
# reorg depth, and negligible against DET-83's 3600 s freshness bound.
RUN_BLOCK_SAFETY_MARGIN = 6
# Sub-calls per aggregate3. Bounded by the provider's eth_call gas ceiling, not
# by us: 150 x ~30k gas is ~4.5M, comfortably inside typical limits.
MAX_BATCH = 150


def _arg_types(signature: str) -> list[str]:
    inner = signature[signature.index("(") + 1 : signature.rindex(")")]
    return [t.strip() for t in inner.split(",") if t.strip()]


def encode_call(signature: str, args: tuple[Any, ...] = ()) -> bytes:
    """Selector + ABI-encoded args. Explicit, so no web3 API-version drift."""
    types = _arg_types(signature)
    if len(types) != len(args):
        raise ValueError(f"{signature}: expected {len(types)} args, got {len(args)}")
    return function_signature_to_4byte_selector(signature) + abi_encode(types, list(args))


@dataclass(frozen=True)
class Call:
    """One contract read, described by its canonical signature."""

    target: str
    signature: str
    outputs: tuple[str, ...]
    args: tuple[Any, ...] = ()

    @property
    def calldata(self) -> bytes:
        return encode_call(self.signature, self.args)


@dataclass(frozen=True)
class ReadResult:
    """A read's outcome. `ok is False` means the call reverted or returned junk.

    `value` is None on failure — never a zero-value stand-in. Callers that need
    the value use `require()`, which fails closed.
    """

    call: Call
    ok: bool
    value: tuple[Any, ...] | None
    provenance: ContractRead
    error: str | None = None

    def require(self) -> tuple[Any, ...]:
        if not self.ok:
            raise RpcReadError(f"{self.call.target} {self.call.signature}: {self.error}")
        assert self.value is not None
        return self.value

    def one(self) -> Any:
        """Single-output convenience."""
        return self.require()[0]


class RpcReadError(RuntimeError):
    """A read that failed. Never swallowed into a default value."""


@dataclass
class RpcClient:
    """Client whose every read is pinned to one block for the run's lifetime."""

    url: str
    _w3: Web3 = field(init=False)
    _run_block: int = field(init=False)
    _block_timestamp: int = field(init=False)
    _run_start_time: int = field(init=False)

    def __init__(self, url: str, run_block: int | None = None):
        self.url = url
        self._w3 = Web3(Web3.HTTPProvider(url))
        self._run_start_time = int(time.time())
        if run_block is None:
            run_block = self._w3.eth.block_number - RUN_BLOCK_SAFETY_MARGIN
        self._run_block = run_block
        self._block_timestamp = self._w3.eth.get_block(run_block)["timestamp"]

    # DET-83 header pair -----------------------------------------------------
    @property
    def run_block(self) -> int:
        return self._run_block

    @property
    def block_timestamp(self) -> int:
        return self._block_timestamp

    @property
    def run_start_time(self) -> int:
        return self._run_start_time

    def _provenance(self, call: Call) -> ContractRead:
        return ContractRead(
            source_contract=call.target.lower(),
            function=call.signature,
            args=[str(a) for a in call.args],
            block=self._run_block,
        )

    # Batched reads ----------------------------------------------------------
    def read(self, calls: list[Call]) -> list[ReadResult]:
        """Execute calls in aggregate3 batches, all at `run_block`."""
        results: list[ReadResult] = []
        for i in range(0, len(calls), MAX_BATCH):
            chunk = calls[i : i + MAX_BATCH]
            raw = self._w3.eth.call(
                {"to": Web3.to_checksum_address(MULTICALL3), "data": encode_aggregate3(chunk)},
                block_identifier=self._run_block,
            )
            results.extend(self.decode_aggregate3(chunk, raw))
        return results

    def storage(self, address: str, slot: str) -> str:
        """One raw storage slot at `run_block` — the F4 `eip1967_slot_read`
        shape's evidence (P-3.07 ruling (i) branch 2)."""
        v = self._w3.eth.get_storage_at(Web3.to_checksum_address(address), slot,
                                        block_identifier=self._run_block)
        h = v.hex()
        return h if h.startswith("0x") else "0x" + h

    def code(self, address: str) -> str:
        """Deployed bytecode at `run_block` — the selector-absence scan's input."""
        c = self._w3.eth.get_code(Web3.to_checksum_address(address),
                                  block_identifier=self._run_block).hex()
        return c if c.startswith("0x") else "0x" + c

    def decode_aggregate3(self, calls: list[Call], raw: bytes) -> list[ReadResult]:
        (entries,) = abi_decode(["(bool,bytes)[]"], raw)
        if len(entries) != len(calls):
            raise RpcReadError(f"aggregate3 returned {len(entries)} results for {len(calls)} calls")
        out: list[ReadResult] = []
        for call, (success, data) in zip(calls, entries, strict=True):
            prov = self._provenance(call)
            if not success:
                out.append(ReadResult(call, False, None, prov, "call reverted"))
                continue
            try:
                value = tuple(abi_decode(list(call.outputs), data))
            except Exception as exc:  # decode failure is a failure, not a zero
                out.append(ReadResult(call, False, None, prov, f"decode failed: {exc}"))
                continue
            out.append(ReadResult(call, True, value, prov))
        return out


def encode_aggregate3(calls: list[Call]) -> bytes:
    """aggregate3((address,bool,bytes)[]) with allowFailure=True on every call.

    allowFailure is what keeps one bad read from reverting the batch — and what
    lets a failure arrive as a failure rather than as a zero.
    """
    selector = function_signature_to_4byte_selector("aggregate3((address,bool,bytes)[])")
    payload = [(Web3.to_checksum_address(c.target), True, c.calldata) for c in calls]
    return selector + abi_encode(["(address,bool,bytes)[]"], [payload])
