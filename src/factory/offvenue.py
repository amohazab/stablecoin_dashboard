"""B-9: DET-32's off-venue share (P-7.01 R4, P-7.05 S3).

`X = 1 - curve / total` over Ethereum-mainnet DEX liquidity that holds the token
(DefiLlama `underlyingTokens` contains its ADDRESS - never a symbol). DEX
membership is DefiLlama's own `category == "Dexs"` from `/protocols`, because
`/pools` carries no category; Curve is the `curve-dex` project (LlamaLend is
`Lending`). Unpinned by nature (rubric 0.5): the field records both URLs, the
UTC fetch date and the response's unix time. Any component unavailable - a
transport error, a shape change, zero matching DEX rows - is the not-computed
literal, never an `AssemblyStop`: this is a disclosure, not a discovery gate.
"""

from __future__ import annotations

import datetime as _dt
import time
from decimal import ROUND_HALF_UP, Decimal

from factory.schema import OffvenueShare

POOLS_URL = "https://yields.llama.fi/pools"
PROTOCOLS_URL = "https://api.llama.fi/protocols"
DEX_CATEGORY = "Dexs"
CURVE_PROJECT = "curve-dex"
CHAIN = "Ethereum"
NOT_COMPUTED = "off-venue share: not computed"
SOURCE = f"{POOLS_URL} + {PROTOCOLS_URL} (category {DEX_CATEGORY!r}, Curve {CURVE_PROJECT!r})"


def _default_get(url: str):
    import requests
    r = requests.get(url, timeout=180)
    r.raise_for_status()
    return r.json()


def fetch(get=None) -> dict:
    """Both payloads plus the fetch time. Raises on any transport failure; the
    caller turns that into the literal."""
    get = get or _default_get
    pools = get(POOLS_URL)
    protocols = get(PROTOCOLS_URL)
    return {"pools": pools, "protocols": protocols, "fetched_at": int(time.time())}


def _literal_x(x: Decimal) -> str:
    """R-7's printed form; NAMED DEFAULT: X as a percentage at one decimal, half-up."""
    pct = (x * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{pct}% of discovered DEX liquidity lies outside modeled venues"


def share(token_address: str, fetched: dict | None) -> OffvenueShare:
    """Pure over the fetched payloads."""
    fetched_at = int((fetched or {}).get("fetched_at") or time.time())
    date = _dt.datetime.fromtimestamp(fetched_at, _dt.UTC).date().isoformat()
    empty = OffvenueShare(dex_liquidity_total_discovered=None, curve_mainnet_liquidity=None,
                          x=None, literal=NOT_COMPUTED, source=SOURCE, date=date,
                          fetched_at=fetched_at, lineage=["offvenue_llama"])
    if not fetched:
        return empty
    try:
        cat = {p["slug"]: p.get("category") for p in fetched["protocols"] if p.get("slug")}
        rows = [x for x in fetched["pools"]["data"]
                if x["chain"] == CHAIN
                and token_address.lower() in [str(u).lower() for u in (x.get("underlyingTokens")
                                                                       or [])]
                and cat.get(x["project"]) == DEX_CATEGORY]
        total = int(sum(Decimal(str(x.get("tvlUsd") or 0)) for x in rows))
        curve = int(sum(Decimal(str(x.get("tvlUsd") or 0)) for x in rows
                        if x["project"] == CURVE_PROJECT))
    except (KeyError, TypeError, ValueError):
        return empty
    if total <= 0:
        return empty
    x = Decimal(1) - Decimal(curve) / Decimal(total)
    return OffvenueShare(dex_liquidity_total_discovered=total, curve_mainnet_liquidity=curve,
                         x=x, literal=_literal_x(x), source=SOURCE, date=date,
                         fetched_at=fetched_at, lineage=["offvenue_llama"])


def read_share(token_address: str, get=None) -> OffvenueShare:
    try:
        return share(token_address, fetch(get))
    except Exception:                       # any component unavailable -> T-22
        return share(token_address, None)
