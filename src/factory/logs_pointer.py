"""The event-log POINTER — Etherscan v2 `logs/getLogs` (ruled P-4.04 R3).

Pointer, never verdict. Nothing this module returns is a value the bundle
carries: it returns the SET of addresses and amounts to go and read on-chain,
and every number that reaches a bundle field is a pinned read at `run_block`.
That is the same discipline the pool discovery uses — the Curve catalog points,
the chain decides (P-3.28) — applied to an event history the configured RPC
cannot serve: Alchemy's free tier answers `eth_getLogs` over a **10-block**
range, so enumerating GHO's borrower set that way is 1,555,180 requests.

WINDOWING. Etherscan caps a query at `page x offset <= 10000` and says so in
its own error text. A window is therefore walked page by page at `offset =
1000` and, when a full 10,000 rows come back, re-anchored at
`fromBlock = last + 1`. **No cursor and no persisted ledger**: every run
re-walks the full range (P-4.04-A1), which costs 59-89 requests for GHO and
keeps the pointer stateless.

THE KEY reaches no bundle, no log and no spot-check sheet — it is read through
the same `_env` helper DET-62's legs use and appears only in the request URL
(P-3.39 binding 1).
"""

from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError

BASE = "https://api.etherscan.io/v2/api"
PAGE_SIZE = 1000
MAX_PAGES = 10                        # Etherscan: page x offset <= 10000


class PointerError(Exception):
    """The pointer could not be walked. Callers re-raise as `AssemblyStop`:
    an incomplete borrower set is not a smaller borrower set."""


class LogRow(BaseModel, extra="ignore"):
    """Only what the pointer is for. `extra="ignore"` for the same reason
    `discovery.PoolEntry` carries it: a provider adding fields is not a shape
    change; a field this model REQUIRES going missing is (P-3.46)."""

    topics: list[str]
    data: str
    blockNumber: str

    @property
    def block(self) -> int:
        return int(self.blockNumber, 16)


@dataclass
class PointerRead:
    """Provenance for one pointer walk, in the shape DET-62's off-chain legs
    use: what was asked, of whom, over which range, and how much came back.
    Carries no key and no value — it provenances a POINTER, not a number."""

    source: str
    address: str
    topics: list[str | None]
    from_block: int
    to_block: int
    row_count: int
    requests: int
    windows: int
    rows: list[LogRow] = field(default_factory=list)

    def record(self) -> dict:
        return {"source": self.source, "address": self.address,
                "topics": [t for t in self.topics], "from_block": self.from_block,
                "to_block": self.to_block, "row_count": self.row_count,
                "requests": self.requests, "windows": self.windows}


def _params(address: str, topics: list[str | None], frm: int, to: int,
            page: int, key: str) -> dict:
    p = {"chainid": 1, "module": "logs", "action": "getLogs", "address": address,
         "fromBlock": frm, "toBlock": to, "page": page, "offset": PAGE_SIZE,
         "apikey": key}
    for i, t in enumerate(topics):
        if t is not None:
            p[f"topic{i}"] = t
    # Etherscan requires an explicit operator for every adjacent indexed pair.
    for i in range(len(topics) - 1):
        if topics[i] is not None and topics[i + 1] is not None:
            p[f"topic{i}_{i + 1}_opr"] = "and"
    return p


def get_logs(address: str, topics: list[str | None], from_block: int,
             to_block: int, http_get, key: str) -> PointerRead:
    """Walk one address/topic filter over a block range. `http_get(url, params)`
    is injected so the walk is stubbable and this module imports no transport —
    the same seam DET-62's legs use (P-3.45)."""
    out: list[LogRow] = []
    reqs = windows = 0
    frm = from_block
    while frm <= to_block:
        windows += 1
        page, last, in_window = 1, None, 0
        while page <= MAX_PAGES:
            payload = http_get(BASE, _params(address, topics, frm, to_block, page, key))
            reqs += 1
            if not isinstance(payload, dict):
                raise PointerError(f"pointer returned {type(payload).__name__}, not an object")
            result = payload.get("result")
            if not isinstance(result, list):
                # Etherscan reports "no records" and every real failure the same
                # way; an empty window ends the walk, anything else is a stop.
                msg = str(payload.get("message", "")).lower()
                if "no records" in msg or "no logs" in msg:
                    return PointerRead("etherscan_v2_logs", address, topics, from_block,
                                       to_block, len(out), reqs, windows, out)
                raise PointerError(f"pointer error: {payload.get('message')!r} "
                                   f"{str(payload.get('result'))[:120]}")
            if not result:
                page = MAX_PAGES + 1
                break
            try:
                rows = [LogRow(**r) for r in result]
            except ValidationError as exc:
                raise PointerError(
                    f"pointer SHAPE CHANGE: {exc.error_count()} validation error(s). "
                    "Quarantine rather than publish garbage (brief hard gate)."
                ) from exc
            out.extend(rows)
            in_window += len(rows)
            last = rows[-1].block
            if len(rows) < PAGE_SIZE:
                page = MAX_PAGES + 1
                break
            page += 1
        if last is None or in_window < PAGE_SIZE * MAX_PAGES:
            break
        frm = last + 1
    return PointerRead("etherscan_v2_logs", address, topics, from_block, to_block,
                       len(out), reqs, windows, out)


def env(repo: pathlib.Path, name: str) -> str:
    """Environment first, then the `<name>=` line of `.env` at the repo root.
    Generalised from `_rpc_url` (0.5(c)) when DET-62's Etherscan leg needed
    `ETHERSCAN_API_KEY` by the same route (P-3.19). Returns "" if unset."""
    val = os.environ.get(name, "").strip()
    if val:
        return val
    dotenv = repo / ".env"
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip()
    return ""




def default_transport(repo: pathlib.Path):
    """The pointer's own transport, keyed from `.env`. Two arguments — `(url,
    params)` — because that is what Etherscan takes; the CATALOG transport in
    `discovery.py` takes one. Handing one to the other broke GHO's first pool
    pass, so they are named apart and each module owns its own (P-4.11).

    The key reaches only the request; it is never returned or recorded
    (P-3.39 binding 1).
    """
    key = env(repo, "ETHERSCAN_API_KEY")

    def get(url: str, params: dict) -> dict:
        import requests
        p = dict(params)
        p["apikey"] = key
        r = requests.get(url, params=p, timeout=120)
        r.raise_for_status()
        return r.json()

    return get


__all__ = ["BASE", "LogRow", "PointerError", "PointerRead", "default_transport",
           "env", "get_logs"]
