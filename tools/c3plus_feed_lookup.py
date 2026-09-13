"""
C3+ feed lookup — fills the Chainlink columns of step7-c3plus-signature-draft.md §(2).

Run in JupyterLab:   %run c3plus_feed_lookup.py
or from a shell:     python c3plus_feed_lookup.py

What it does
  1. Downloads Chainlink's public feed directory for Ethereum mainnet (the JSON behind
     data.chain.link) and pulls deviation threshold + heartbeat for the 8 base pairs.
  2. Maps them onto the 22 rows of §(2) and prints a markdown table in the file's column
     order, plus writes c3plus_feed_values_<date>.csv next to this script.
  3. Lists the Proof-of-Reserve feeds for WBTC / cbBTC / LBTC (for §(1)'s read form).
  4. Optional: if ETH_RPC_URL is set (env or .env), reads description() and the last
     updatedAt from every feed_or_source address so you can confirm the mechanism.

Everything printed carries its source and the fetch date — copy the rows into the
signature file with those two columns as they are.
"""

import csv
import json
import os
import sys
import urllib.request
from datetime import date, datetime, timezone

TODAY = date.today().isoformat()

# Chainlink's reference directory (the data source of data.chain.link / docs.chain.link).
DIRECTORY_URL = "https://reference-data-directory.vercel.app/feeds-mainnet.json"
DOCS_URL = "https://data.chain.link/feeds/ethereum/mainnet/"

# §(2) rows as drafted — row, symbol, class, feed_or_source, base pair (None for NAV).
ROWS = [
    ("2.1", "WBTC", "capo-rate", "0xdaa4b74c6bac4e25188e64ebc68db5050b690cac", "BTC / USD"),
    ("2.2", "cbETH", "capo-rate", "0x889399c34461b25d70d43931e6ce9e40280e617b", "ETH / USD"),
    ("2.3", "rETH", "capo-rate", "0x6929706c42d637df5ebf7f0bcff2af47f84ea69d", "ETH / USD"),
    ("2.4", "sUSDe", "capo-rate", "0x42bc86f2f08419280a99d8fbea4672e7c30a86ec", "USDT / USD"),
    ("2.5", "weETH", "capo-rate", "0x87625393534d5c102cadb66d37201df24cc26d4c", "ETH / USD"),
    ("2.6", "wstETH", "capo-rate", "0xe1d97bf61901b075e9626c8a2340a7de385861ef", "ETH / USD"),
    ("2.7", "USDC", "capo-stable", "0x3f73f03aa83b2a48ed27e964ed0fdb590332095b", "USDC / USD"),
    ("2.8", "USDT", "capo-stable", "0x260326c220e469358846b187ee53328303efe19c", "USDT / USD"),
    ("2.9", "waEthUSDC", "capo-stable", "0x3f73f03aa83b2a48ed27e964ed0fdb590332095b", "USDC / USD"),
    ("2.10", "waEthUSDT", "capo-stable", "0x260326c220e469358846b187ee53328303efe19c", "USDT / USD"),
    ("2.11", "WETH", "raw", "0x5424384b256154046e9667ddfaaa5e550145215e", "ETH / USD"),
    ("2.12", "cbBTC", "raw", "0xb41e773f507f7a7ea890b1afb7d2b660c30c8b0a", "BTC / USD"),
    ("2.13", "tBTC", "raw", "0xb41e773f507f7a7ea890b1afb7d2b660c30c8b0a", "BTC / USD"),
    ("2.14", "sDAI", "capo-rate", "0xf83b85205241c3bcca0a09d32fae65c16e0cf236", "DAI / USD"),
    ("2.15", "DAI", "capo-stable", "0x5c66322ca59bb61e867b28195576dbd8da4b08de", "DAI / USD"),
    ("2.16", "USDS", "capo-stable", "0x94c7fd62fd0506e71d8142e9d36687fc72a86b02", "USDS / USD"),
    ("2.17", "AAVE", "raw", "0xf02c1e2a3b77c1cacc72f72b44f7d0a4c62e4a85", "AAVE / USD"),
    ("2.18", "LINK", "raw", "0xc7e9b623ed51f033b32ae7f1282b1ad62c28c183", "LINK / USD"),
    ("2.19", "JAAA", "nav", "0xf77f2537dba4ffd60f77facdfb2c1706364fa03d", None),
    ("2.20", "USCC", "nav", "0x14cb2e810eb93b79363f489d45a972b609e47230", None),
    ("2.21", "USTB", "nav", "0x5ae4d93b9b9626dc3289e1afb14b821fd3c95f44", None),
    ("2.22", "ETH (LUSD)", "raw", "0x5f4ec3df9cbd43714fe2740f5e3616155c5b8419", "ETH / USD"),
]
BASE_PAIRS = sorted({r[4] for r in ROWS if r[4]})

# Manual lookups the script cannot do — printed as a checklist at the end.
MANUAL = {
    "NAV intervals (rows 2.19–2.21)": [
        "USTB, USCC: Superstate fund pages — NAV publication cadence (business days)",
        "JAAA: Centrifuge / Janus Henderson Anemoy fund page — NAV cadence",
    ],
    "§(1) disclosure rows": [
        "WBTC: BitGo transparency page; or the Chainlink WBTC PoR feed printed below",
        "USDC / waEthUSDC: Circle monthly attestation page (latest report date)",
        "USDT / waEthUSDT: Tether transparency page + latest quarterly attestation date",
        "cbETH: Coinbase cbETH page (on-chain verifiable; say so if no attestation exists)",
        "sUSDe: Ethena transparency page — latest custodian attestation date",
    ],
    "§(3) audits": [
        "crvUSD: Curve GitHub audits folder; Immunefi Curve program (max bounty)",
        "GHO: Aave GitHub audits (GSM: SigmaPrime, Certora dates); Immunefi Aave program",
        "LUSD: Liquity docs audits page (Trail of Bits, Coinspect dates); Liquity bounty",
    ],
}


def _norm(s):
    return "".join(s.lower().split())


def fetch_directory():
    req = urllib.request.Request(DIRECTORY_URL, headers={"User-Agent": "c3plus-lookup"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def find_feed(directory, pair):
    """Exact name match first (e.g. 'BTC / USD'); returns the list of matching entries."""
    want = _norm(pair)
    hits = [f for f in directory if _norm(f.get("name", "")) == want]
    # Prefer the plain price feed over PoR / other variants when several share a name.
    hits.sort(key=lambda f: (str(f.get("feedType", "")).lower() != "crypto", f.get("proxyAddress", "")))
    return hits


def por_feeds(directory):
    out = []
    for f in directory:
        name = f.get("name", "")
        docs = f.get("docs", {}) or {}
        is_por = "por" in str(docs.get("porType", "")).lower() or "reserve" in name.lower() or " por" in name.lower()
        if is_por and any(k in name.lower() for k in ("wbtc", "cbbtc", "lbtc", "lombard")):
            out.append(f)
    return out


def onchain_check(addresses):
    """Optional: description() + updatedAt for each address via ETH_RPC_URL."""
    rpc = os.environ.get("ETH_RPC_URL")
    if not rpc and os.path.exists(".env"):
        for line in open(".env", encoding="utf-8"):
            if line.startswith("ETH_RPC_URL="):
                rpc = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not rpc:
        print("\n(on-chain check skipped: ETH_RPC_URL not set)")
        return {}
    try:
        from web3 import Web3
    except ImportError:
        print("\n(on-chain check skipped: web3 not installed)")
        return {}
    w3 = Web3(Web3.HTTPProvider(rpc))
    abi = [
        {"name": "description", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "string"}]},
        {"name": "latestRoundData", "type": "function", "stateMutability": "view", "inputs": [],
         "outputs": [{"type": "uint80"}, {"type": "int256"}, {"type": "uint256"}, {"type": "uint256"}, {"type": "uint80"}]},
        {"name": "decimals", "type": "function", "stateMutability": "view", "inputs": [], "outputs": [{"type": "uint8"}]},
    ]
    block = w3.eth.block_number
    print(f"\nOn-chain check via your RPC at block {block} ({TODAY}):")
    print("| address | description() | last updatedAt (UTC) | answer / 10^decimals |")
    print("|---|---|---|---|")
    results = {}
    for addr in addresses:
        c = w3.eth.contract(address=Web3.to_checksum_address(addr), abi=abi)
        try:
            desc = c.functions.description().call(block_identifier=block)
        except Exception:
            desc = "(no description())"
        try:
            _, ans, _, upd, _ = c.functions.latestRoundData().call(block_identifier=block)
            dec = c.functions.decimals().call(block_identifier=block)
            ts = datetime.fromtimestamp(upd, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
            val = f"{ans / 10**dec:,.6f}"
        except Exception:
            ts, val = "(no latestRoundData())", ""
        results[addr] = (desc, ts, val)
        print(f"| {addr} | {desc} | {ts} | {val} |")
    return results


def main():
    print(f"C3+ feed lookup — {TODAY}\nSource: {DIRECTORY_URL}\n")
    try:
        directory = fetch_directory()
    except Exception as e:  # network or moved endpoint
        print(f"Could not fetch the Chainlink directory ({e}).")
        print("Fallback: open data.chain.link → Ethereum → each base pair and read")
        print("'Deviation threshold' and 'Heartbeat' by hand for:", ", ".join(BASE_PAIRS))
        sys.exit(1)

    # 1. Base pairs
    base = {}
    print("## Base pairs (Chainlink Ethereum mainnet)\n")
    print("| pair | deviation | heartbeat_s | proxy | docs |")
    print("|---|---|---|---|---|")
    for pair in BASE_PAIRS:
        hits = find_feed(directory, pair)
        if not hits:
            print(f"| {pair} | NOT FOUND | | | look up by hand |")
            continue
        f = hits[0]
        thr = f.get("threshold")
        hb = f.get("heartbeat")
        proxy = f.get("proxyAddress") or f.get("contractAddress")
        base[pair] = (f"{thr}%" if thr is not None else "?", hb, proxy)
        print(f"| {pair} | {thr}% | {hb} | {proxy} | {DOCS_URL}{f.get('path','')} |")
        if len(hits) > 1:
            print(f"|   ↳ {len(hits)-1} other entr(y/ies) share this name — check the proxy above is the price feed | | | | |")

    # 2. Per-row table in the signature file's column order
    src = f"Chainlink feed directory (data.chain.link), fetched {TODAY}"
    print("\n## §(2) rows — paste-ready (deviation / heartbeat columns)\n")
    print("| # | symbol | base | deviation | deviation source | deviation date | heartbeat_s | heartbeat source | heartbeat date |")
    print("|---|---|---|---|---|---|---|---|---|")
    rows_out = []
    for row, sym, cls, addr, pair in ROWS:
        if pair is None:
            dev, hb = "n/a — excluded from X (A-19)", "____ (NAV publication interval, issuer page)"
            dsrc, hsrc = "A-19", "____"
        elif pair in base:
            dev, hb, _ = base[pair]
            dsrc = hsrc = src
        else:
            dev, hb, dsrc, hsrc = "____", "____", "____", "____"
        print(f"| {row} | {sym} | {pair or '—'} | {dev} | {dsrc} | {TODAY} | {hb} | {hsrc} | {TODAY} |")
        rows_out.append([row, sym, cls, addr, pair or "", dev, dsrc, TODAY, hb, hsrc, TODAY])

    out = f"c3plus_feed_values_{TODAY}.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["row", "symbol", "class", "feed_or_source", "base_pair", "deviation", "deviation_source",
                    "deviation_date", "heartbeat_s", "heartbeat_source", "heartbeat_date"])
        w.writerows(rows_out)
    print(f"\nWritten: {out}")

    # 3. PoR feeds for §(1)
    print("\n## Proof-of-Reserve feeds (for §(1)'s read form)\n")
    pf = por_feeds(directory)
    if not pf:
        print("None matched WBTC/cbBTC/LBTC by name — search data.chain.link for 'Proof of Reserve'.")
    else:
        print("| name | proxy | heartbeat_s | docs |")
        print("|---|---|---|---|")
        for f in pf:
            print(f"| {f.get('name')} | {f.get('proxyAddress') or f.get('contractAddress')} | {f.get('heartbeat')} | {DOCS_URL}{f.get('path','')} |")

    # 4. Optional on-chain confirmation of each feed_or_source
    onchain_check(sorted({r[3] for r in ROWS}))

    # 5. Manual checklist
    print("\n## Still manual\n")
    for section, items in MANUAL.items():
        print(f"- {section}")
        for it in items:
            print(f"    - {it}")


if __name__ == "__main__":
    main()