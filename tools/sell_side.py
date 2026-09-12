"""sell_side.py — sell-side capacity at ~2% price impact into USDC, Ethereum mainnet.

Run once, locally:  python sell_side.py
Needs only the standard library. Uses Paraswap's public price API (no key).
Prints the 19 rows for DET-52 (16 distinct assets; tBTC used twice, WETH/wstETH/
weETH/WBTC/cbBTC shared between crvUSD and GHO) plus a CSV, both dated today.

Definition (memo §6.3): the amount of the asset absorbable into stable markets at
<= 2% impact. Method: price impact of a trade of size X is measured against the
marginal price of a tiny reference trade; bisect X until impact ~= 2%.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import sys
import time
import urllib.parse
import urllib.error
import urllib.request

LAST_ERROR: dict[str, str] = {}

API = "https://api.paraswap.io/prices/"
USDC = ("0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", 6)
TARGET = 0.02          # 2% impact
TOL = 0.001            # accept 1.9%..2.1%
SLEEP = 0.7            # be polite to the public API
MAX_ITERS = 14

ASSETS = [
    # symbol, address, decimals, tokens it belongs to, start guess (asset units)
    ("WETH",    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", 18, "crvUSD, GHO", 5_000),
    ("wstETH",  "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0", 18, "crvUSD, GHO", 3_000),
    ("sfrxETH", "0xac3e018457b222d93114458476f3e3416abbe38f", 18, "crvUSD",      500),
    ("weETH",   "0xcd5fe23c85820f7b72d0926fc9b05b43e359b7ee", 18, "crvUSD, GHO", 1_000),
    ("rETH",    "0xae78736cd615f374d3085123a210448e74fc6393", 18, "GHO",         1_000),
    ("cbETH",   "0xbe9895146f7af43049ca1c1ae358b0541ea49704", 18, "GHO",         500),
    ("WBTC",    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599", 8,  "crvUSD, GHO", 300),
    ("cbBTC",   "0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf", 8,  "crvUSD, GHO", 100),
    ("LBTC",    "0x8236a87084f8b84306f72007f36f2618a5634494", 8,  "crvUSD",      30),
    ("tBTC",    "0x18084fba666a33d37592fa2633fd49a74dd93a88", 18, "crvUSD, GHO", 30),
    ("AAVE",    "0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9", 18, "GHO",         20_000),
    ("LINK",    "0x514910771af9ca656af840dff83e8264ecf986ca", 18, "GHO",         200_000),
    ("USCC",    "0x14d60e7fdc0d71d8611742720e4c50e7a974020c", 6,  "GHO",         100_000),
]


def quote(src: str, src_dec: int, amount_units: float) -> float | None:
    """USDC received (in USDC units) for selling `amount_units` of `src`; None if no route."""
    amount = int(amount_units * 10 ** src_dec)
    if amount <= 0:
        return None
    q = urllib.parse.urlencode({
        "srcToken": src, "destToken": USDC[0], "amount": str(amount),
        "srcDecimals": src_dec, "destDecimals": USDC[1], "side": "SELL", "network": 1,
        "maxImpact": 90, "version": "6.2",
    })
    req = urllib.request.Request(API + "?" + q, headers={"User-Agent": "sell-side-script/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:200]
        if e.code == 429:
            time.sleep(5)
            return quote(src, src_dec, amount_units)
        LAST_ERROR[src] = f"HTTP {e.code}: {body}"
        return None
    except Exception as e:  # noqa: BLE001
        LAST_ERROR[src] = str(e)[:200]
        return None
    route = data.get("priceRoute")
    if not route:
        return None
    return int(route["destAmount"]) / 10 ** USDC[1]


def impact(src: str, dec: int, size: float, ref_price: float) -> float | None:
    out = quote(src, dec, size)
    time.sleep(SLEEP)
    if out is None:
        return None
    return 1.0 - (out / size) / ref_price


def solve(symbol: str, src: str, dec: int, start: float) -> tuple[float | None, str]:
    # reference price from a small trade; shrink until the API answers
    tiny = start / 1000
    ref_out = None
    for _ in range(8):
        ref_out = quote(src, dec, tiny)
        time.sleep(SLEEP)
        if ref_out is not None:
            break
        tiny /= 4
    if ref_out is None:
        return None, f"no route on Paraswap ({LAST_ERROR.get(src, 'no detail')})"
    ref_price = ref_out / tiny

    # find a routable starting size, then grow until impact >= 2%
    size = start
    imp = None
    for _ in range(10):                      # shrink while the API refuses the size
        imp = impact(src, dec, size, ref_price)
        if imp is not None:
            break
        size /= 2
    if imp is None:
        return None, f"route fails down to {size:,.4f} ({LAST_ERROR.get(src, 'no detail')})"
    lo, hi = 0.0, size
    for _ in range(14):                      # grow until we bracket 2%
        if imp >= TARGET:
            break
        lo, hi = hi, hi * 2
        imp = impact(src, dec, hi, ref_price)
        if imp is None:                      # grew past what the API will quote
            return lo, f"route ceiling — largest quotable size (impact < 2% there)"
    else:
        return hi, f"impact still {imp:.2%} at {hi:,.0f} — deeper than probed"

    # bisect between lo (impact < 2%) and hi (impact >= 2%)
    best, best_imp = hi, imp
    for _ in range(MAX_ITERS):
        mid = (lo + hi) / 2
        imp = impact(src, dec, mid, ref_price)
        if imp is None:
            hi = mid
            continue
        if abs(imp - TARGET) < abs(best_imp - TARGET):
            best, best_imp = mid, imp
        if abs(imp - TARGET) <= TOL:
            break
        if imp < TARGET:
            lo = mid
        else:
            hi = mid
    return best, f"impact {best_imp:.2%}"


def main() -> None:
    today = dt.date.today().isoformat()
    source = f"Paraswap prices API, Ethereum mainnet, ~2% impact into USDC by bisection, {today}"
    rows = []
    print(f"{'asset':8} {'value (units)':>18}  {'note':38} tokens")
    for symbol, addr, dec, tokens, start in ASSETS:
        value, note = solve(symbol, addr, dec, start)
        shown = f"{value:,.4f}" if value is not None else "0"
        print(f"{symbol:8} {shown:>18}  {note:38} {tokens}", flush=True)
        rows.append({"asset": symbol, "address": addr, "value": value if value is not None else 0,
                     "note": note, "tokens": tokens, "source": source, "date": today})
    path = f"sell_side_{today}.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"\nwritten {path}\nsource: {source}")
    if LAST_ERROR:
        print("\nlast API error per asset (for assets that failed at some size):")
        for a, e in LAST_ERROR.items():
            print(f"  {a[:10]}…  {e}")


if __name__ == "__main__":
    main()