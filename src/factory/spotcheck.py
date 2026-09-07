"""B-6: the manual spot-check sheet generator (Method A, P-3.13).

**Transport rev 2** — amendment to ruling (e), proposed after the analyst's
2026-09-05 finding that Etherscan's `eth_call` proxy silently ignores `tag`
and answers every request at the chain head. Rev 1's URLs could not pin, so
rev-1 value comparisons were measured at the wrong block (indeterminate, not
failed). Rev 2 replaces the transport only; expected values, item selection
and the bindings below are unchanged.

The invariant the defect exposed, now explicit:

  **The check's data path must be independent of the adapter's.** Re-reading
  through the adapter's own Alchemy endpoint would verify replay, not provider
  honesty. Rev 2 therefore reads through two keyless third-party archive RPCs
  operated by different parties, and **requires them to agree**; a single
  aggregator could in principle route back to the adapter's upstream, so
  agreement between two distinct operators — not the choice of any one — is
  what carries the independence claim.

The four bindings, all structural rather than advisory:
  1. **No key in the emitted file.** Rev 2 satisfies this by construction: the
     transports are keyless, so no placeholder is needed and no key can leak.
     `out/spotcheck/` stays gitignored regardless (belt and braces).
  2. **Checker independence on item 4** — the pre-filled borrower is chosen
     deterministically, and the sheet states the checker may substitute ANY row
     from the raw dump.
  3. **Both value forms** — raw hex as the endpoint returns it, and decoded.
  4. **Item 5's keeper address comes from the bundle**, never a constant in
     this generator (P4 applies to tooling too).

And one added by the defect:
  5. **The sheet proves its own transport before it is trusted.** Item 0 is a
     pin self-test: the same call at run_block and at a far older block must
     return *different* values. If item 0 does not pin, no other row means
     anything and the checker stops. Rev 1 shipped with no such test, which is
     why a broken transport reached the analyst.
"""

from __future__ import annotations

import pathlib

from eth_utils import function_signature_to_4byte_selector

from factory.schema import Bundle

# Two independent keyless archive endpoints, different operators and clients
# (Tenderly's own infrastructure; Pocket Network via nodies, reth). Both were
# pin-tested at proposal time. DRPC is a verified spare, listed in the sheet
# but not emitted: it is a load-balancing aggregator whose upstream is not
# disclosed, which is the weakest independence claim of the three.
PRIMARY = "https://gateway.tenderly.co/public/mainnet"
SECOND = "https://eth-pokt.nodies.app"
SPARE = "https://eth.drpc.org"

# Far-past block for the item-0 pin self-test. Any block old enough that live
# state has certainly moved; fixed here so the test is deterministic per run.
PIN_TEST_BLOCK = 24117248

EIP1967_IMPL = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"


def _calldata(signature: str, arg_addr: str | None = None) -> str:
    sel = function_signature_to_4byte_selector(signature).hex()
    if arg_addr is None:
        return "0x" + sel
    return "0x" + sel + arg_addr[2:].rjust(64, "0")


def _hexint(v: int) -> str:
    return "0x" + f"{v:064x}"


def _body(method: str, params: str) -> str:
    return f'{{"jsonrpc":"2.0","id":1,"method":"{method}","params":[{params}]}}'


def _call_body(to: str, data: str, block: int) -> str:
    return _body("eth_call", f'{{"to":"{to}","data":"{data}"}},"0x{block:x}"')


def _storage_body(addr: str, slot: str, block: int) -> str:
    return _body("eth_getStorageAt", f'"{addr}","{slot}","0x{block:x}"')


def _cmd(url: str, body: str) -> str:
    """A PowerShell one-liner. Single-quoted body needs no escaping, and
    `.result` prints the bare hex so the checker compares strings directly."""
    return (f"(Invoke-RestMethod {url} -Method Post "
            f"-ContentType application/json -Body '{body}').result")


def generate(bundle: Bundle, crvusd: str, controller_factory: str,
             biggest_position: dict | None) -> str:
    """Render the sheet for one run. Deterministic: same bundle, same sheet."""
    b, rb = bundle, bundle.header.run_block
    m = max(bundle.markets, key=lambda x: x.gross_debt_sum)
    # binding 4: from the bundle, never a constant here
    keeper = max(b.stabilizer.operations, key=lambda o: o.current_debt, default=None)

    L = [
        f"# Spot-check — crvUSD @ run_block {rb}",
        "",
        f"Bundle `{b.header.bundle_hash[:16]}…` · block timestamp "
        f"{b.header.block_timestamp} · DET-83 freshness {b.header.det83_delta_s}s",
        "",
        "## Transport (rev 2)",
        "",
        "Two keyless third-party archive RPCs, run by different operators:",
        "",
        f"- **A** `{PRIMARY}`",
        f"- **B** `{SECOND}`",
        f"- spare (verified, not emitted) `{SPARE}`",
        "",
        "**Both must return the same value**, and that value is what you compare "
        "to the expected column. Agreement between two independent operators is "
        "the point — a single provider could be reading from the same upstream "
        "the adapter used, which would verify replay rather than honesty.",
        "",
        "Commands are PowerShell one-liners; the block is pinned **inside the "
        "JSON-RPC body**, where it is honoured, not in a query parameter. "
        "**No API key appears anywhere in this file** — the transports need "
        "none. `out/spotcheck/` remains gitignored.",
        "",
        "> Rev 1 used Etherscan's `eth_call` proxy with `tag=<block>`. That "
        "> parameter is silently ignored — `latest`, this run's block, and an "
        "> eight-month-old block all return byte-identical results. Any rev-1 "
        "> comparison was measured at the head: **indeterminate, not failed**.",
        "",
        "## Item 0 — pin self-test (run this first)",
        "",
        "The transport must be proven to pin before any row below means "
        f"anything. These two commands differ only in the block — `0x{rb:x}` "
        f"(this run) against `0x{PIN_TEST_BLOCK:x}` (block {PIN_TEST_BLOCK}). "
        "**They must return different values.** If they return the same value, "
        "the transport is not pinning: stop, and no other row is executable.",
        "",
        "```powershell",
        "# at this run's block — expect " + _hexint(b.supply.total_supply),
        _cmd(PRIMARY, _call_body(crvusd, _calldata("totalSupply()"), rb)),
        "",
        f"# at block {PIN_TEST_BLOCK} — must be DIFFERENT",
        _cmd(PRIMARY, _call_body(crvusd, _calldata("totalSupply()"), PIN_TEST_BLOCK)),
        "```",
        "",
        "## Items",
        "",
        "**Any mismatch is a flag, never a correction.** The bundle is not "
        "edited and the adapter is not 'fixed to match' without diagnosis; the "
        "finding is recorded as a pipeline bug or a data change and chased to "
        "one of them. A mismatch against a Phase-B `[VERIFIED …]` value is "
        "reported as *\"verified value was X (source, date); live read is Y at "
        "block N\"* and that point stops.",
        "",
        "| # | what | expected (decoded) | expected (raw hex) | A=B? | pass/fail |",
        "|---|---|---|---|---|---|",
    ]

    cmds: list[str] = []

    def item(i, what, decoded, raw, body=None):
        L.append(f"| {i} | {what} | `{decoded}` | `{raw}` |  |  |")
        if body:
            # the labels are comments; the commands are NOT. The block is meant
            # to be pasted and run as-is.
            cmds.append(f"# --- item {i} --- expect {raw}")
            cmds.append('"item ' + str(i) + ' A"')
            cmds.append(_cmd(PRIMARY, body))
            cmds.append('"item ' + str(i) + ' B"')
            cmds.append(_cmd(SECOND, body))
            cmds.append("")

    item(1, "crvUSD `totalSupply()`", f"{b.supply.total_supply}",
         _hexint(b.supply.total_supply),
         _call_body(crvusd, _calldata("totalSupply()"), rb))
    item(2, f"{m.symbol} Controller `total_debt()`",
         f"{m.position_completeness.controller_total_debt}",
         _hexint(m.position_completeness.controller_total_debt),
         _call_body(m.address, _calldata("total_debt()"), rb))
    L.append(f"| 3 | DET-82 for {m.symbol}: Σ position `gross_debt` vs item 2 | "
             f"`{m.gross_debt_sum}` | rel_diff "
             f"`{m.position_completeness.relative_diff}` ≤ 1e-9 | n/a — "
             f"bundle-internal |  |")
    if biggest_position:
        u = biggest_position["user"]
        item(4, f"{m.symbol} `user_state({u[:10]}…)` — **substitutable: use ANY "
                f"row from `out/raw/{rb}` (binding 2)**",
             f"collateral={biggest_position['collateral']}, "
             f"stablecoin={biggest_position['stablecoin_in_position']}, "
             f"debt={biggest_position['gross_debt']}",
             "(4 words, 64 hex chars each)",
             _call_body(m.address, _calldata("user_state(address)", u), rb))
    if keeper:
        item(5, f"PegKeeper `{keeper.operation_address[:10]}…` `debt()` "
                f"(address from the bundle, binding 4)",
             f"{keeper.current_debt}", _hexint(keeper.current_debt),
             _call_body(keeper.operation_address, _calldata("debt()"), rb))
        item("5b", "its `debt_ceiling(pk)` on ControllerFactory",
             f"{keeper.debt_ceiling}", _hexint(keeper.debt_ceiling),
             _call_body(controller_factory,
                        _calldata("debt_ceiling(address)", keeper.operation_address), rb))
    mint_row = next((r for r in b.admin_surface if r.power == "mint"), None)
    if mint_row:
        # an absence row carries no holder; the call is still worth running,
        # and the expected column says so rather than fabricating a word.
        h = mint_row.holder_address
        item(6, "`ControllerFactory.admin()`", f"{h}",
             ("0x" + h[2:].rjust(64, "0")) if h else "(no holder recorded)",
             _call_body(controller_factory, _calldata("admin()"), rb))
    up = next((r for r in b.admin_surface if r.power == "upgrade"), None)
    if up:
        # rev 2 change beyond transport: rev 1 sent the checker to Etherscan's
        # Storage tab, which shows head state and cannot be pinned at all. The
        # same fact is available as a pinned eth_getStorageAt.
        item(7, f"EIP-1967 impl slot on {m.symbol} Controller (absence check) "
                f"— `{up.upgradeability}`",
             "all-zero slot", _hexint(0),
             _storage_body(m.address, EIP1967_IMPL, rb))
    orow = next((r for r in b.oracle_rows if r.market_or_reserve_address == m.address),
                None)
    if orow:
        L.append(f"| 8 | {m.symbol} `ema_window_s` (transitive max, P-3.32) | "
                 f"`{orow.update_condition.ema_window_s}` | see constituents | "
                 f"n/a — per-hop provenance on the oracle row |  |")
    if b.supply.bridges:
        br = b.supply.bridges[0]
        item(9, f"crvUSD `balanceOf({br.bridge_address[:10]}…)`", f"{br.amount}",
             _hexint(br.amount),
             _call_body(crvusd, _calldata("balanceOf(address)", br.bridge_address), rb))
    else:
        L.append(f"| 9 | bridge balance | — | — | n/a | "
                 f"{b.supply.bridge_disclosure} |")
    L.append("| 10 | *Informational — no threshold, no pass/fail.* DefiLlama "
             "Ethereum circulating, recorded **beside** `origination_sum` | "
             f"`{b.supply.origination_sum}` | — | n/a | *record observed* |")

    L += ["", "```powershell", *cmds, "```", "",
          "## Item 10 — informational only",
          "",
          "Source: `stablecoins.llama.fi` (crvUSD, Ethereum). **Record the "
          "observed figure; do not compare it to `totalSupply()` and do not "
          "mark it pass or fail.**",
          "",
          "Rev 1 asserted agreement with `totalSupply()` within 5%. That is "
          "wrong twice over. The quantities are not comparable — DefiLlama "
          "reports a circulating convention that excludes protocol-held "
          "inventory, while `totalSupply()` includes it, and for crvUSD the "
          "inventory is most of the supply. And the 5% figure was borrowed "
          "from the *discovery* cross-validation gate, which does not own "
          "supply; no rubric entry creates a supply-level agreement gate, and "
          "none is created here.",
          "",
          "`origination_sum` is printed beside it as the protocol-origination "
          "figure. Note it already **includes** the stabilizer leg — DET-15(b) "
          "defines it as Σ principal + Σ stabilizer debt — so it is shown "
          "alone, not summed with the stabilizer line again.",
          "",
          "**Checker notes:**", "", "```", "", "```", ""]
    return "\n".join(L)


def write(bundle: Bundle, out_dir: pathlib.Path, **kw) -> pathlib.Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{bundle.header.run_block}.md"
    p.write_text(generate(bundle, **kw), encoding="utf-8", newline="")
    return p
