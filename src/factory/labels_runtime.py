"""The A5 run-time label resolver, shared by every adapter.

Lifted out of `run.py` at P-4.10 so GHO can call the SAME resolver crvUSD
does rather than a second copy - the one-owner rule applied to code. Nothing
in it is token-specific: the `[[wallet_registry]]` config row carries the
addresses, and the read is the label authority (P-3.37 binding 2).
"""

from __future__ import annotations

from factory.provenance import ContractRead
from factory.rpc import Call


def _cr(contract: str, fn: str, block: int) -> ContractRead:
    return ContractRead(source_contract=contract.lower(), function=fn, args=[],
                        block=block)


def resolve_wallet_registry_label(rpc, entry: dict) -> tuple[str, ContractRead] | None:
    """DET-76(c): the per-run read IS the label authority (P-3.37 binding 2).

    Memo 4.4 branch 1 - reserves locatable on-chain without any disclosure ->
    `terminal_other_layer` (verifiable on the Bitcoin chain, which this pipeline
    does not read). Branch 2 - a custodian or committee disclosure is required
    to locate them -> `recurses`, as WBTC. An unreachable read returns None:
    unlabeled-in-run, routed via 8.2 / DET-08, never a default label (A5).
    """
    rb = rpc.run_block
    locator = rpc.read([Call(entry["bridge_address"], "activeWalletPubKeyHash()",
                             ("bytes20",))])[0]
    if not locator.ok:
        return None
    pkh = locator.one()
    if not any(pkh):                      # zero hash locates nothing
        return None
    owner = rpc.read([Call(entry["registry_address"], "walletOwner()", ("address",))])[0]
    if not owner.ok or owner.one().lower() != entry["bridge_address"]:
        return None                       # closure broken -> do not trust the branch
    return "terminal_other_layer", _cr(entry["bridge_address"],
                                       "activeWalletPubKeyHash()", rb)
