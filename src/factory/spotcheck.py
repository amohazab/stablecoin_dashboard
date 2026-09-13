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
# keccak("SWAP_FREEZER_ROLE"), for GHO item 5's hasRole calldata
SWAP_FREEZER_ROLE_HEX = ("6dac4cc0544e34aa1a4ed2862f6de78290e3f18f00fe77179ee8ef34de9dfa24")


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


def generate_gho(bundle: Bundle, gho: str) -> str:
    """GHO's ten items, rev-2 transport (P-3.13 as amended at P-3.39).

    The four bindings hold unchanged: no key in the file (the transports are
    keyless by construction), both value forms, item 0 the standing pin
    self-test, and **every address comes from the bundle** — no facilitator,
    GSM, borrower or pool address is a constant in this generator, which is the
    no-hardcoded-lists gate applied to tooling.
    """
    b = bundle
    rb = b.header.run_block
    L = [f"# Spot-check — GHO @ run_block {rb}",
         "",
         f"Bundle `{b.header.bundle_hash[:16]}…`, block **{rb}**, "
         f"sheet `{b.header.sheet_hash}`, frozen set `{b.header.frozen_set_hash}`.",
         "",
         "Two keyless archive RPCs, **A and B must agree** — a single endpoint "
         "could route back to the adapter's own upstream, so agreement between "
         "two operators is what carries independence, not either one alone.",
         "",
         f"* A = `{PRIMARY}`",
         f"* B = `{SECOND}` (spare: `{SPARE}`)",
         "",
         "**Item 0 first.** It proves the transport pins the block; until it "
         "passes, no other answer means anything (P-3.39).",
         "",
         "| # | what | expected (decoded) | expected (raw hex) | A=B? | pass/fail |",
         "|---|---|---|---|---|---|"]
    cmds: list[str] = []

    def item(i, what, decoded, raw, body=None):
        L.append(f"| {i} | {what} | `{decoded}` | `{raw}` |  |  |")
        if body:
            cmds.append(f"# --- item {i} --- expect {raw}")
            cmds.append('"item ' + str(i) + ' A"')
            cmds.append(_cmd(PRIMARY, body))
            cmds.append('"item ' + str(i) + ' B"')
            cmds.append(_cmd(SECOND, body))
            cmds.append("")

    supply_call = _call_body(gho, _calldata("totalSupply()"), rb)
    item(0, "PIN SELF-TEST — `totalSupply()` at the run block, then at "
            f"{PIN_TEST_BLOCK}. **They must DIFFER.**",
         "the two must differ", _hexint(b.supply.total_supply), supply_call)
    cmds.append(f"# --- item 0, old block {PIN_TEST_BLOCK}: must DIFFER from the above")
    cmds.append(_cmd(PRIMARY, _call_body(gho, _calldata("totalSupply()"), PIN_TEST_BLOCK)))
    cmds.append("")

    item(1, "GHO `totalSupply()`", f"{b.supply.total_supply}",
         _hexint(b.supply.total_supply), supply_call)

    # 2: the largest facilitator bucket - address FROM THE BUNDLE
    fac = max(b.facilitators, key=lambda f: f.bucket_level)
    item(2, f"`getFacilitatorBucket({fac.address[:10]}…)` level "
            f"(largest of {len(b.facilitators)})",
         f"cap {fac.bucket_capacity} / level {fac.bucket_level}",
         _hexint(fac.bucket_capacity) + " then " + _hexint(fac.bucket_level),
         _call_body(gho, _calldata("getFacilitatorBucket(address)", fac.address), rb))

    # 3: a GSM's boxed underlying
    if b.gsms:
        g = max(b.gsms, key=lambda x: x.available_liquidity)
        item(3, f"GSM `{g.address[:10]}…` `getAvailableLiquidity()`",
             f"{g.available_liquidity}", _hexint(g.available_liquidity),
             _call_body(g.address, _calldata("getAvailableLiquidity()"), rb))
        item(4, f"GSM `{g.address[:10]}…` `getExposureCap()`",
             f"{g.exposure_cap}", _hexint(g.exposure_cap),
             _call_body(g.address, _calldata("getExposureCap()"), rb))
        if g.freezer_address:
            item(5, f"`hasRole(SWAP_FREEZER_ROLE, {g.freezer_address[:10]}…)` on that GSM "
                    "— the freezer discovered from role logs, confirmed on-chain",
                 "true", _hexint(1),
                 _body("eth_call",
                       f'{{"to":"{g.address}","data":"0x91d14854'
                       f'{SWAP_FREEZER_ROLE_HEX}{g.freezer_address[2:].rjust(64, "0")}"}},'
                       f'"0x{rb:x}"'))

    # 6: the largest direct minter's drawn debt, read off its own debt token
    mint = [f for f in b.facilitators if f.debt_token_address]
    if mint:
        m = max(mint, key=lambda f: f.gross_debt_sum or 0)
        item(6, f"`{m.debt_token_address[:10]}…` `totalSupply()` — the instance's GHO "
                "debt; DET-82 compares the position sum to exactly this",
             f"{m.position_completeness.controller_total_debt}",
             _hexint(m.position_completeness.controller_total_debt),
             _call_body(m.debt_token_address, _calldata("totalSupply()"), rb))
        item(7, f"`{m.atoken_address[:10]}…` GHO balance — undrawn inventory",
             f"{m.inventory}", _hexint(m.inventory or 0),
             _call_body(gho, _calldata("balanceOf(address)", m.atoken_address), rb))

    # 8: the frozen pool's GHO-side balance
    frozen = [p for p in b.pools if p.in_frozen_set]
    if frozen:
        item(8, f"frozen pool `{frozen[0].address[:10]}…` `balances(0)` — the GHO side "
                "of the only pool in F",
             "compare to the set file's tvl_at_par",
             "(read; the sheet does not pre-state it)",
             _call_body(frozen[0].address, _calldata("balances(uint256)") + "0" * 64, rb))

    # 9: the bridged component
    if b.supply.bridges:
        br = b.supply.bridges[0]
        item(9, f"CCIP pool `{br.bridge_address[:10]}…` GHO balance — the bridged "
                "component, amount only (C-1)",
             f"{br.amount}", _hexint(br.amount),
             _call_body(gho, _calldata("balanceOf(address)", br.bridge_address), rb))

    # 10: GhoToken's implementation slot
    item(10, "GhoToken EIP-1967 implementation slot — the `upgrade` row's evidence",
         "all-zero => immutable at the standard slot", "0x" + "0" * 64,
         _storage_body(gho, EIP1967_IMPL, rb))

    L += ["", "## Commands", "", "```powershell", *cmds, "```", ""]
    return "\n".join(L)


def write_gho(bundle: Bundle, out_dir: pathlib.Path, **kw) -> pathlib.Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{bundle.header.run_block}.md"
    p.write_text(generate_gho(bundle, **kw), encoding="utf-8", newline="")
    return p


def generate_lusd(bundle: Bundle, lusd: str, extra: dict | None = None) -> str:
    """LUSD's ten items, rev-2 transport (P-3.13 as amended at P-3.39).

    The four bindings hold: no key in the file, both value forms, item 0 the
    standing pin self-test, and **every address comes from the bundle** - the
    trove system, the pools, the escrow and the feed are all read off the
    emitted tables, never written as constants here.
    """
    b = bundle
    rb = b.header.run_block
    m = b.markets[0]
    L = [f"# Spot-check - LUSD @ run_block {rb}",
         "",
         f"Bundle `{b.header.bundle_hash[:16]}...`, block **{rb}**, "
         f"sheet `{b.header.sheet_hash}`, frozen set `{b.header.frozen_set_hash}`.",
         "",
         "Two keyless archive RPCs, **A and B must agree** - a single endpoint "
         "could route back to the adapter's own upstream, so agreement between "
         "two operators is what carries independence, not either one alone.",
         "",
         f"* A = `{PRIMARY}`",
         f"* B = `{SECOND}` (spare: `{SPARE}`)",
         "",
         "**Item 0 first.** It proves the transport pins the block; until it "
         "passes, no other answer means anything (P-3.39).",
         "",
         "| # | what | expected (decoded) | expected (raw hex) | A=B? | pass/fail |",
         "|---|---|---|---|---|---|"]
    cmds: list[str] = []

    def item(i, what, decoded, raw, body=None):
        L.append(f"| {i} | {what} | `{decoded}` | `{raw}` |  |  |")
        if body:
            cmds.append(f"# --- item {i} --- expect {raw}")
            cmds.append('"item ' + str(i) + ' A"')
            cmds.append(_cmd(PRIMARY, body))
            cmds.append('"item ' + str(i) + ' B"')
            cmds.append(_cmd(SECOND, body))
            cmds.append("")

    supply_call = _call_body(lusd, _calldata("totalSupply()"), rb)
    item(0, "PIN SELF-TEST - `totalSupply()` at the run block, then at "
            f"{PIN_TEST_BLOCK}. **They must DIFFER.**",
         "the two must differ", _hexint(b.supply.total_supply), supply_call)
    cmds.append(f"# --- item 0, old block {PIN_TEST_BLOCK}: must DIFFER from the above")
    cmds.append(_cmd(PRIMARY, _call_body(lusd, _calldata("totalSupply()"), PIN_TEST_BLOCK)))
    cmds.append("")

    item(1, "LUSD `totalSupply()`", f"{b.supply.total_supply}",
         _hexint(b.supply.total_supply), supply_call)

    tm = m.address
    item(2, f"TroveManager `{tm[:10]}...` `getTroveOwnersCount()` - the "
            "enumeration this run walked",
         f"{m.n_positions}", _hexint(m.n_positions),
         _call_body(tm, _calldata("getTroveOwnersCount()"), rb))

    # 3: one trove, address FROM THE RUN's own owner list
    troves = (extra or {}).get("troves") or []
    if troves:
        t = max(troves, key=lambda x: x["debt"])
        item(3, f"largest trove `{t['owner'][:10]}...` `getEntireDebtAndColl` - "
                "debt then coll",
             f"debt {t['debt']} / coll {t['coll']}",
             _hexint(t["debt"]) + " then " + _hexint(t["coll"]),
             _call_body(tm, _calldata("getEntireDebtAndColl(address)", t["owner"]), rb))

    ap = m.reads["collateral"].source_contract
    item(4, f"ActivePool `{ap[:10]}...` `getETH()` - with DefaultPool this is "
            "the whole of backing",
         f"{m.external_collateral_sum}", _hexint(m.external_collateral_sum),
         _call_body(ap, _calldata("getETH()"), rb))

    item(5, f"`getTCR(price)` at this run's price - compare to `system_tcr` "
            f"{b.system_tcr}",
         "> 1.60 keeps the (d) near-bound quiet", "(read; decimal 1e18)",
         None)

    pf = b.oracle_rows[0].update_condition.provenance[1].source_contract
    item(6, f"PriceFeed `{pf[:10]}...` `status()` - 0 = chainlinkWorking",
         "0", _hexint(0), _call_body(pf, _calldata("status()"), rb))

    item(7, f"PriceFeed `{pf[:10]}...` `lastGoodPrice()` - the protocol's last "
            "recorded price; it LAGS the feed by design",
         "compare to the sheet's disclosure line", "(read)",
         _call_body(pf, _calldata("lastGoodPrice()"), rb))

    frozen = [p for p in b.pools if p.in_frozen_set]
    if frozen:
        item(8, f"frozen pool `{frozen[0].address[:10]}...` `balances(0)` - the "
                "LUSD side of the only pool in F",
             "compare to the set file's tvl_at_par",
             "(read; the sheet does not pre-state it)",
             _call_body(frozen[0].address, _calldata("balances(uint256)") + "0" * 64, rb))

    if b.supply.bridges:
        br = max(b.supply.bridges, key=lambda x: x.amount)
        item(9, f"largest escrow `{br.bridge_address[:10]}...` LUSD balance - "
                "the bridged component, amount only (C-1)",
             f"{br.amount}", _hexint(br.amount),
             _call_body(lusd, _calldata("balanceOf(address)", br.bridge_address), rb))

    item(10, "LUSDToken EIP-1967 implementation slot - the `upgrade` row's "
             "evidence, and the whole admin surface's premise",
         "all-zero => immutable at the standard slot", "0x" + "0" * 64,
         _storage_body(lusd, EIP1967_IMPL, rb))

    L += ["", "## Commands", "", "```powershell", *cmds, "```", ""]
    return "\n".join(L)


def write_lusd(bundle: Bundle, out_dir: pathlib.Path, **kw) -> pathlib.Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{bundle.header.run_block}.md"
    p.write_text(generate_lusd(bundle, **kw), encoding="utf-8", newline="")
    return p


# ------------------------------------------------------------ the tree ------
# P-5.04: the analyst's check of a TREE is a label check, not a read check -
# every node's label against its config row and the memo row that row cites,
# the qualifying holders on Etherscan, and the paired rows against their
# config source. No transport, so no item 0; every figure comes from the tree
# or the bundle it folded.


def generate_tree(bundle: Bundle, tree, cfg, labels_file: str) -> str:
    t, b = tree, bundle
    scale = t.root.value_scale
    per_node = {n.address: n for n in b.nodes}
    out = [f"# Tree spot-check — {t.token} @ {t.run_block}", "",
           f"- tree_hash `{t.tree_hash}`", f"- source_bundle_hash `{t.source_bundle_hash}`",
           "- checks: " + ", ".join(f"{r.entry_id} {r.result}" for r in t.checks),
           f"- value_scale {scale} (divide `value` by it for USD)", "",
           "## Nodes — label vs config row vs memo row", "",
           "| address | symbol | label | config row | memo row (config `label_source`) "
           "| value | share of backing |", "|---|---|---|---|---|---|---|"]
    for a in sorted(per_node):
        n = per_node[a]
        row = cfg.labels.get(a)
        src = row.label_source if row else "— no config row —"
        cfg_ref = f"`config/{labels_file}` [[node]] {a[:10]}…" if row else "—"
        out.append(f"| `{a}` | {n.symbol} | `{n.label}` | {cfg_ref} | {src} | "
                   f"{n.value} | {n.share_of_backing} |")
    out += ["", "## Qualifying admin rows (DET-70) — verify holders on Etherscan", ""]
    q = [r for r in b.admin_surface if r.power in ("mint", "upgrade", "set_oracle", "seize")
         and r.holder_type != "none"]
    if not q:
        out.append("None: " + t.banner)
    else:
        out += ["| power | holder_address | holder_type | delay_seconds | delay_bucket | veto |",
                "|---|---|---|---|---|---|"]
        out += [f"| {r.power} | `{r.holder_address}` | {r.holder_type} | {r.delay_seconds} | "
                f"{r.delay_bucket} | {r.veto_address or '—'} |" for r in q]
        out += ["", f"Banner: {t.banner}"]
    out += ["", "## Paired assets (DET-11) — label vs config source", "",
            "| pool | address | symbol | label | config source | source_tree |",
            "|---|---|---|---|---|---|"]
    out += [f"| `{p.pool}` | `{p.address}` | {p.symbol} | `{p.label}` | {p.source} | "
            f"{p.source_tree or '—'} |" for p in t.paired_assets]
    return "\n".join(out) + "\n"


def write_tree(bundle: Bundle, tree, cfg, labels_file: str, out_dir: pathlib.Path) -> pathlib.Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"tree-{tree.run_block}.md"
    p.write_text(generate_tree(bundle, tree, cfg, labels_file), encoding="utf-8", newline="")
    return p


def _price_source(bundle, report) -> str:
    """Where the cell's price actually came from, per token shape."""
    if bundle.gsms:
        return "per (instance, reserve) from that instance's own AaveOracle (DET-81)"
    if bundle.stabilizer.operations:
        return "in `mechanism.llamma.markets[].oracle`"
    return ("the bundle's own `external_collateral_value / "
            "external_collateral_sum`, NOT a re-simulated `fetchPrice()`")


def _bad_debt_source(bundle) -> str:
    if bundle.gsms:
        return ("Σ (debt − value) over unabsorbed positions with hf < 1, "
                "attributed to GHO pro-rata by `gho_debt_base / total_debt_base`")
    if bundle.stabilizer.operations:
        return "Σ (debt − value) over unabsorbed positions with CR < 1"
    return ("Σ (debt − collateral × price) over REDISTRIBUTED troves with "
            "CR < 100% — DET-51's `redistributed_positions_below_100` identity, "
            "not the receiving troves' post-CR")


def _m2_source(bundle) -> str:
    if bundle.gsms:
        return "boxed holdings + the attributed slice"
    return "zero by construction — no stable node and no GSM (DET-43)"


def _trove_table(bundle, report, repo: pathlib.Path) -> list[str]:
    """B-7's subtotal requirement, applied early for LUSD: the whole trove book,
    so `m1.pre` is a hand sum rather than an assertion.

    72 rows is small enough to print entire, which is the reason this lands at
    B-6 for LUSD and stays owed for the other two — crvUSD's book is thousands
    of positions and needs per-market subtotals instead.
    """
    from decimal import Decimal as D

    raw = repo / "out/raw" / f"{bundle.header.run_block}.json"
    if not raw.exists():
        return []
    import json as _json
    rows = _json.loads(raw.read_text(encoding="utf-8"))
    if not rows or "owner" not in rows[0]:
        return []
    m = bundle.markets[0]
    price = (D(m.external_collateral_value) * D(10 ** 18)
             // D(m.external_collateral_sum))
    head = next((c for c in report.cells if c.id == "M1-s50-d0-lp0"), None)
    shock = head.shock if head else D("-0.50")
    shocked = int(D(price) * (D(1) + shock))
    out = ["", f"## 2b. The whole trove book, so `m1.pre` is a hand sum "
               f"({len(rows)} rows)", "",
           f"Price basis `external_collateral_value / external_collateral_sum` "
           f"= {D(price) / D(10 ** 18):,.8f} per ETH; the headline cell shocks it "
           f"by {shock} to {D(shocked) / D(10 ** 18):,.8f}. ICR is at the SHOCKED "
           f"price, MCR = 1.10 — no row reaches it, which is R-B6.1.", "",
           "| owner | debt (LUSD) | coll (ETH) | coll × shocked price | ICR |",
           "|---|---|---|---|---|"]
    td, tc, tv = 0, 0, 0
    for r in sorted(rows, key=lambda x: -x["debt"]):
        v = r["coll"] * shocked // 10 ** 18
        td += r["debt"]
        tc += r["coll"]
        tv += v
        out.append(f"| `{r['owner']}` | {D(r['debt']) / D(10 ** 18):,.2f} | "
                   f"{D(r['coll']) / D(10 ** 18):,.4f} | "
                   f"{D(v) / D(10 ** 18):,.2f} | "
                   f"{D(r['coll']) * D(shocked) / (D(r['debt']) * D(10 ** 18)):.4f} |")
    out += [f"| **total** | **{D(td) / D(10 ** 18):,.2f}** | "
            f"**{D(tc) / D(10 ** 18):,.4f}** | **{D(tv) / D(10 ** 18):,.2f}** | "
            f"**{D(tv) / D(td):.10f}** |", "",
            f"That last cell IS `m1.pre.ratio` = "
            f"{head.m1.pre.ratio if head else '—'}."]
    return out


def _reproduce_calls(bundle, report) -> list[str]:
    """The mechanism section's own reads, as pasteable pinned `eth_call`s.

    Sourced from the artifact's recorded provenance — `args` carries the real
    argument, so the asset in `getReserveConfigurationData` is the one actually
    read, never an example. `getAvailableLiquidity` is the bundle's GSM read
    rather than the stress module's; it is here because the M2 cell's depth
    turns on it.
    """
    rb = bundle.header.run_block
    out: list[str] = []
    for g in bundle.gsms:
        out.append(f"- GSM `{g.address}` `getAvailableLiquidity()` — expect "
                   f"`{g.available_liquidity}`")
        out.append("  ```powershell")
        out.append("  " + _cmd(PRIMARY, _call_body(
            g.address, _calldata("getAvailableLiquidity()"), rb)))
        out.append("  ```")
    reads = report.mechanism.reads
    up = next(((k, v) for k, v in sorted(reads.items())
               if v.function.startswith("checkUpkeep")), None)
    if up:
        out.append(f"- freezer `{up[1].source_contract}` "
                   "`checkUpkeep(bytes)` — DET-46's automation probe: the call "
                   "**answering at all** is the signal (an address that is not "
                   "an automation-compatible keeper reverts)")
        out.append("  ```powershell")
        out.append("  " + _cmd(PRIMARY, _body(
            "eth_call",
            f'{{"to":"{up[1].source_contract}","data":"'
            # dynamic `bytes`: head word is the OFFSET (0x20), then the length.
            # Probed 2026-09-13: an offset of 0 also answers here, because it
            # points at a zero word that decodes as an empty `bytes`. The
            # canonical encoding is emitted anyway — the sheet should not rely
            # on a decoder's tolerance to say whether the freezer is automated.
            + _calldata("checkUpkeep(bytes)")
            + f"{32:064x}" + f"{0:064x}" + f'"}},"0x{rb:x}"')))
        out.append("  ```")
    rc = next(((k, v) for k, v in sorted(reads.items())
               if v.function.startswith("getReserveConfigurationData")), None)
    if rc:
        asset = rc[1].args[0]
        out.append(f"- data provider `{rc[1].source_contract}` "
                   f"`getReserveConfigurationData({asset})` — one of the "
                   "37 (instance, reserve) pairs; word 3 is the liquidation "
                   "threshold in bps, which is what the health factor weights by")
        out.append("  ```powershell")
        out.append("  " + _cmd(PRIMARY, _call_body(
            rc[1].source_contract,
            _calldata("getReserveConfigurationData(address)", asset), rb)))
        out.append("  ```")
    return out


def write_stress(bundle, report, out_dir: pathlib.Path) -> pathlib.Path:
    """R17's hand-verification sheet for a promoted stress artifact (B-4b).

    Every figure traces to a bundle field, a raw-dump row or a recorded read,
    so Amin can check the headline cell by hand against Etherscan without
    re-running anything. Gitignored with the rest of `out/spotcheck/`.
    """
    from decimal import Decimal

    E = Decimal(10 ** 18)
    head = next((c for c in report.cells if c.id == "M1-s50-d0-lp0"),
                report.cells[0])
    m = report.mechanism
    ks = report.exit_depth.k_subsets.get("90", [])
    _p2 = next((p for p in report.exit_depth.depth_curve
                if p.s == Decimal("0.02")), None)
    d31 = 0 if _p2 is None else (_p2.total if report.exit_depth.gsm_venues
                                 else _p2.pool_depth)
    lines = [
        f"# Stress spot-check — {bundle.header.token} @ {bundle.header.run_block}",
        "",
        f"- bundle `{bundle.header.bundle_hash[:8]}` · tree "
        f"`{report.header.source_tree_hash[:8]}` · stress "
        f"`{report.header.stress_hash[:8]}`",
        f"- cells {len(report.cells)} · checks "
        f"{sum(1 for c in report.checks if c.result == 'pass')}/"
        f"{len(report.checks)} · headline **{head.id}** (memo §6.2.6)",
        "",
        "## 1. The headline cell, by hand",
        "",
        "| quantity | value | where it comes from |",
        "|---|---|---|",
        f"| m1.pre.ratio | {head.m1.pre.ratio:.6f} | Σ collateral × "
        f"(1+shock)(1−d) × price ÷ Σ net debt; collateral and debt per position "
        f"in `out/raw/<block>.json`, price {_price_source(bundle, report)} |",
        f"| m1.post.ratio | {head.m1.post.ratio:.6f} | the same over the book "
        "left after absorption |",
        f"| m1.gap | {head.m1.gap:.6f} | post − pre, the mechanism's measured "
        "contribution (DET-39) |",
        f"| m2.bad_debt | {Decimal(head.m2.bad_debt) / E:,.2f} "
        f"{bundle.header.token} | {_bad_debt_source(bundle)}; base units "
        f"`{head.m2.bad_debt}` |",
        f"| m2.pct_supply | {head.m2.pct_supply:.10f} | ÷ `supply.supply_ruled` "
        f"= {Decimal(bundle.supply.supply_ruled) / E:,.2f} |",
        f"| m3.forced_sell_volume | {Decimal(head.m3.forced_sell_volume) / E:,.2f}"
        " | = bad_debt, DET-25's Member-1 identity |",
        f"| m3.exit_depth | {Decimal(head.m3.exit_depth) / E:,.2f} | LP-0, so "
        f"equal to DET-31 depth(0.02) = {Decimal(d31) / E:,.2f} |",
        f"| m3.ratio | {head.m3.ratio} | forced_sell ÷ exit_depth |",
        "",
    ]
    if m.effective_headroom is not None:
        lines += [
            "## 2. DET-45, from the bundle's own keeper rows", "",
            f"- effective **{Decimal(m.effective_headroom) / E:,.2f}** "
            f"≤ naive **{Decimal(m.naive_headroom) / E:,.2f}**",
            f"- gate views: provide_allowed "
            f"{set(m.provide_allowed.values())}, withdraw_allowed "
            f"{len(m.withdraw_allowed)} × 2²⁵⁶−1; "
            f"reason `{m.gate_reason}`", "",
            "| keeper | debt | balance | ceiling | r | max_ratio | allowed |",
            "|---|---|---|---|---|---|---|"]
        for a, row in sorted((m.llamma.keeper_state if m.llamma else {}).items()):
            lines.append(
                f"| `{a[:10]}` | {Decimal(row['debt']) / E:,.2f} | "
                f"{Decimal(row['balance']) / E:,.2f} | "
                f"{Decimal(row['ceiling']) / E:,.2f} | "
                f"{Decimal(row['r']) / E:.8f} | "
                f"{Decimal(row['max_ratio']) / E:.6f} | "
                f"{Decimal(row['allowed']) / E:,.2f} |")
    elif m.h2_routing:
        # GHO has no PegKeepers: its mechanism section is DET-46's routing
        # and DET-47's binding side, which is what a hand check needs.
        lines += ["## 2. DET-46 routing, and DET-47's binding side", "",
                  "`check_pass = automated_freezer_present ∧ freeze_lower_bound "
                  ">= 0.88`. Both inputs are the bundle's own GSM rows; the "
                  "automation probe is a successful `checkUpkeep(bytes)` call, "
                  "not a returned flag.", "",
                  "| GSM | freezer | freeze band | automated | routing |",
                  "|---|---|---|---|---|"]
        gsm_of = {g.address: g for g in bundle.gsms}
        for a, route in sorted(m.h2_routing.items()):
            g = gsm_of.get(a)
            lo = Decimal(g.freeze_bound_lo or 0) / Decimal(10 ** 8) if g else 0
            hi = Decimal(g.freeze_bound_hi or 0) / Decimal(10 ** 8) if g else 0
            lines.append(
                f"| `{a}` | `{(g.freezer_address or '—') if g else '—'}` | "
                f"[{lo}, {hi}] | {'yes' if route == 'freezer_effective' else 'no'} "
                f"| **{route}** |")
        lines += ["",
                  f"- `gho_sourceable` {head.m4.get('gho_sourceable')}",
                  f"- `collateral_sellable` "
                  f"{head.m4.get('collateral_sellable')}",
                  f"- `gsm_mint_headroom` {head.m4.get('gsm_mint_headroom')}",
                  f"- **`binding_side` {head.m4.get('binding_side')}**"]
    else:
        # LUSD: no stabilizer and no GSM. The mechanism section is DET-51's
        # H3/H4 — what the Stability Pool would absorb, and what H4 lets a
        # redeemer take before the fee gate closes.
        comp = next((c for c in report.cells if c.id == "M2-compound"), head)
        rc = comp.m4.get("redemption_capacity") or {}
        lines += [
            "## 2. DET-51 — H3 absorption and H4 redemption", "",
            "| quantity | value | where it comes from |", "|---|---|---|",
            f"| sp_balance | {Decimal(bundle.supply.stability_pool_deposits) / E:,.2f}"
            " | `StabilityPool.getTotalLUSDDeposits()`, the bundle's own read "
            "(DET-51's capacity lineage is `{sp_balance_read}`) |",
            f"| sp_effective_cell (headline, LP {head.lp}) | "
            f"{Decimal(head.m4.get('sp_effective_cell', 0)) / E:,.2f} | "
            f"`sp_balance × (1 − {head.lp})` — the LP axis is DEPOSITOR flight |",
            f"| tcr_post (headline) | {head.m4.get('tcr_post')} | Σ surviving "
            "collateral × shocked price ÷ Σ surviving debt |",
            f"| recovery_mode_flag | {head.m4.get('recovery_mode_flag')} | "
            "`tcr_post < CCR` (1.50), reported not modeled (P-6.01 R12) |",
            f"| redistributed_debt | {head.m4.get('redistributed_debt')} | debt "
            "the Pool could not offset, pushed pro rata onto survivors |",
            f"| redemption_capacity (compound) | "
            f"{Decimal(rc.get('value', 0)) / E:,.2f} | {rc.get('reason', '')} |",
            "",
            "Member-1 cells carry `redemption_capacity = 0, reason = \"crash "
            "path excluded\"`, which is the entry's own wording.",
        ]
    lines += _trove_table(bundle, report, out_dir)
    # The Member-2 headline and its counterfactual pair. For GHO this is the
    # cell that carries the report's largest finding — the GSM leaving the
    # venue set — so it is printed in full rather than left to the artifact.
    m2h = next((c for c in report.cells if c.id.startswith("M2-t0.93")), None)
    if m2h is not None:
        lines += [
            "", f"## 3. The Member-2 headline cell — {m2h.id}", "",
            "| quantity | value | where it comes from |", "|---|---|---|",
            f"| m3.forced_sell_volume | "
            f"{Decimal(m2h.m3.forced_sell_volume) / E:,.2f} | {_m2_source(bundle)}"
            f"; base units `{m2h.m3.forced_sell_volume}` |",
            f"| m3.exit_depth | {Decimal(m2h.m3.exit_depth) / E:,.2f} | the "
            "cell's own venue set, DET-35 |",
            f"| m3.ratio | {'undefined (R-B4.14)' if m2h.m3.ratio is None else m2h.m3.ratio}"
            " | forced_sell ÷ exit_depth |",
        ]
        for ln in m2h.counterfactual_lines:
            # A line may be qualitative — crvUSD's `H1_v1_contagion` carries no
            # sized pair — and the sheet says so rather than inventing a zero.
            if ln.value_primary is None or ln.value_counterfactual is None:
                lines += ["", f"**Counterfactual `{ln.id}`** — carried "
                          f"unsized on this cell: {ln.assumption_text}"]
                continue
            lines += [
                "",
                f"**Counterfactual `{ln.id}`** — primary "
                f"{Decimal(ln.value_primary) / E:,.2f}, counterfactual "
                f"{Decimal(ln.value_counterfactual) / E:,.2f}. The difference is "
                "what the routing decision is worth on this cell.",
            ]
    lines += [
        "",
        "## 4. The pinned reads to reproduce",
        "",
        f"**Every call below is a pinned read at `run_block` "
        f"{bundle.header.run_block}** — the same block the bundle was assembled "
        "at (R-13). Pin the block inside the JSON-RPC body; a `tag` query "
        "parameter is silently ignored by some proxies (P-3.39).",
        "",
        f"The depth m3 divides by is the sum over K-subset(0.90) = {len(ks)} "
        "pools. On each, call `get_dy` with the recorded `dx` — **`i` and `j` "
        "are the recorded argument values, not placeholders** — and check the "
        "implied marginal price sits at 1 − s = 0.98 ± ε:",
        "",
    ]
    dy_args = {k.split(".", 1)[0]: v.args
               for k, v in report.exit_depth.reads.items()
               if k.endswith(".get_dy")}
    for g in report.exit_depth.ground_truth:
        a = dy_args.get(g.pool)
        ij = f"i={a[0]}, j={a[1]}" if a and len(a) >= 2 else "i, j (see `reads`)"
        lines.append(f"- `{g.pool}` → `get_dy({ij}, dx={g.dx})` = "
                     f"{g.onchain_dy_at_dx}; implied {g.implied_price} "
                     f"(within ε: {g.within_epsilon})")
    extra = _reproduce_calls(bundle, report)
    if extra:
        lines += ["", "And the three reads the mechanism section rests on, as "
                  "`eth_call` targets:", "", *extra]
    lines += ["", "## 5. Assumptions carried on this artifact", ""]
    for k, v in sorted(report.assumptions.items()):
        lines.append(f"- **{k}** — {v}")
    path = out_dir / "out/spotcheck" / bundle.header.token / \
        f"stress-{bundle.header.run_block}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
