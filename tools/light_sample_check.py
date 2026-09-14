"""
Light-sample verification — one pinned get_dy per token through your own RPC.
B-11d: the sheets and blocks are read from the newest stress-<run_block>.md filenames.

Run from the repo root (reads ETH_RPC_URL from .env or the environment):
    python tools/light_sample_check.py

Parses the first get_dy line of §4 in each new spot-check sheet, calls get_dy(i, j, dx)
at run_block with the block pinned in the JSON-RPC body, decodes the first 32-byte word
(old-Vyper pools answer with a padded buffer), and compares to the sheet's value.
No web3 dependency; stdlib only.
"""

import json
import os
import re
import sys
import urllib.request

TOKENS = ("crvUSD", "GHO", "LUSD")


def latest_sheets():
    """B-11d: each token's newest stress spot-check sheet, block read from the
    filename `stress-<run_block>.md` - no constants to edit per run."""
    sheets, blocks = {}, {}
    for token in TOKENS:
        d = os.path.join("out", "spotcheck", token)
        found = sorted((int(m.group(1)), f) for f in (os.listdir(d) if os.path.isdir(d) else [])
                       if (m := re.fullmatch(r"stress-(\d+)\.md", f)))
        if found:
            blocks[token], name = found[-1]
            sheets[token] = os.path.join(d, name)
        else:
            sheets[token] = os.path.join(d, "stress-<none>.md")
    return sheets, blocks


LINE = re.compile(
    r"`(0x[0-9a-fA-F]{40})`\s*→\s*`get_dy\(i=(-?\d+),\s*j=(-?\d+),\s*dx=(\d+)\)`\s*=\s*(\d+)"
)
SELECTOR = "5e0d443f"  # get_dy(int128,int128,uint256)


def rpc_url():
    url = os.environ.get("ETH_RPC_URL")
    if not url and os.path.exists(".env"):
        for line in open(".env", encoding="utf-8"):
            if line.startswith("ETH_RPC_URL="):
                url = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not url:
        sys.exit("ETH_RPC_URL not set (env or .env)")
    return url


def int128_word(v: int) -> str:
    return (v & ((1 << 256) - 1)).to_bytes(32, "big").hex()


def eth_call(url, to, data, block):
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "eth_call",
        "params": [{"to": to, "data": data}, hex(block)],
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.load(r)
    if "error" in resp:
        raise RuntimeError(resp["error"])
    return resp["result"]


def main():
    url = rpc_url()
    ok_all = True
    SHEETS, BLOCKS = latest_sheets()
    for token, path in SHEETS.items():
        if not os.path.exists(path):
            print(f"{token}: sheet not found at {path}")
            ok_all = False
            continue
        text = open(path, encoding="utf-8", errors="replace").read()
        m = LINE.search(text)
        if not m:
            print(f"{token}: no get_dy line found in {path}")
            ok_all = False
            continue
        pool, i, j, dx, expected = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
        data = "0x" + SELECTOR + int128_word(i) + int128_word(j) + int128_word(dx)
        raw = eth_call(url, pool, data, BLOCKS[token])
        word = raw[2:66]  # first 32-byte word; the rest is padding on old Vyper
        got = int(word, 16)
        status = "MATCH" if got == expected else "MISMATCH"
        ok_all &= got == expected
        print(f"{token} @{BLOCKS[token]} {pool} get_dy({i},{j},{dx})")
        print(f"   sheet    = {expected}")
        print(f"   rpc      = {got}   [{status}]   (returned {len(raw)//2 - 1} bytes)")
    print("\nALL MATCHED to the wei" if ok_all else "\nAt least one mismatch — do not confirm; paste this output to the design chat")


if __name__ == "__main__":
    main()