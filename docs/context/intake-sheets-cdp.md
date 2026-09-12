# Token Intake Sheets — Archetype #1 (CDP / On-Chain-Backed)
 
**Phase A CLOSED — 2026-09-01.** Design complete; implementer test passed.
**Phase B COMPLETE — 2026-09-02.** 18 analyst-supplied values with staleness dates (FIX 2026-09-02: header previously read 19; one entry — frxUSD keeper paired-asset labeling — was re-scoped to intake under P4 after the count was taken); 2 contradictions resolved by ruling (H1, H2); 6 candidate points dispositioned. Design verified; code pending.
**Conventions:** `[VERIFIED <date>: …]` = fact verified in Phase B, source inline. `[FIRST-RUN READ: …]` = live-state quantity read per run by the adapter — an input, not an assumption. `[ANALYST-SUPPLIED <date>: …]` = staleness-tracked analyst input per the graceful-degradation rule. `[RE-SCOPED TO INTAKE: …]` = resolved at intake/freeze time. Mechanism logic carries no marker. Rulings are the analyst's; the memo records them once and code enforces them per run. Each sheet instantiates memo #1 rulings; it never restates or overrides them.
 
---
 
## crvUSD
 
**Archetype assignment:** #1, CDP / on-chain-backed. Fit test: supply originates from LLAMMA controllers minting against pledged collateral with a soft-liquidation path — passes.
 
**Contracts to read**:
- Controller factory (crvUSD mint markets) — market discovery; hardcoded market lists forbidden.
- Per-market: Controller, LLAMMA (AMM), collateral token address, monetary policy contract.
- PegKeeper regulator / registry; per-PegKeeper contracts (below).
- crvUSD token; price aggregator (crvUSD/USD aggregate used by PegKeeperV2 and monetary policy).
- LlamaLend lend-market factory — read only to *exclude* (supply-origination gate below).
**Collateral nodes currently held** [VERIFIED 2026-09-01: live mint markets include cbBTC (largest borrow flow), tBTC, wstETH, WBTC (Curve News wk32 2026), plus WETH, sfrxETH, weETH (Pharos Jun 2026, secondary) — cbBTC and weETH have NO §4 row → §8.2 will fire on first run; candidate open point. Full list [FIRST-RUN READ: factory.n_collaterals()/controllers(i)]]:
 
| Node | Memo §4.5 row | Label |
|---|---|---|
| WETH | WETH → ETH | transparent → `terminal` |
| wstETH | LST | `terminal_other_layer` |
| sfrxETH | LST | `terminal_other_layer` |
| WBTC | WBTC | `recurses` (custodian PoR) |
| tBTC | tBTC | deferred (§4.4) — [FIRST-RUN READ: WalletRegistry read; label ∈ {`terminal_other_layer`, `recurses`} per DET-76(c); unreachable ⇒ unlabeled-in-run → §8.2] |
| cbBTC (largest mint-market borrow flow, Curve News wk32 2026) | cbBTC / custodial BTC | `recurses` (Coinbase custody attestation); `disclosure_cadence` = continuous — Chainlink PoR feed (Ethereum) + Coinbase PoR page, near-real-time refresh; `last_disclosure_date` = per-run read of the Ethereum PoR feed `updatedAt` [ANALYST-SUPPLIED 2026-09-03: Chainlink PoR adopted for cbBTC 2025-05-29 (Coinbase/Chainlink announcements); Coinbase CDP docs state ~per-minute refresh; page coinbase.com/cbbtc/proof-of-reserves] |
| weETH | LRT family | `terminal_other_layer` |
| LBTC (live mint market, found at first contact 2026-09-04) | cbBTC / custodial BTC | `recurses` (Lombard custody attestation); `disclosure_cadence` = continuous — Chainlink PoR (Ethereum) + Lombard PoR page, real-time verification; `last_disclosure_date` = per-run read of the LBTC PoR feed's `updatedAt` [ANALYST-SUPPLIED 2026-09-04: Chainlink PoR on Ethereum for LBTC announced 2026-02-05 (Chainlink/Lombard); partnership incl. PoR 2024-10 (lombard.finance blog). Feed 0x70c158c7731Da2C14BC84aEBa39A4FF703DDc7d2, chain-verified description() = 'Lombard Proof of Reserves' — Lombard-wide, broader than LBTC specifically. Memo §4.4/§4.5 name LBTC in the custodial-BTC class (P1)] |
| Any other mint-market collateral | — | unlisted → §8.2 quarantine rule |
 
Expected verifiability result (Step-5 done-condition): majority `terminal` / `terminal_other_layer`, with WBTC **and cbBTC** as the `recurses` slices (cbBTC is currently the largest mint market — the crvUSD split is no longer trivially ~100% verifiable; "boring, correct" now reads as a defensible custodial-BTC share).
 
**Token-specific mechanism: PegKeepers** (memo §3 instance)
 
- Classification: protocol stabilizer debt, zero-credited. Class rule applies unmodified.
- Discovery: active PegKeeper set read from the PegKeeper regulator / registry contract, never hardcoded [VERIFIED 2026-09-01: regulator 0x36a04CAffc681fa179558B2Aaba30395CDdd855f exposes peg_keepers (DynArray of PegKeeperInfo) — discovery source confirmed. Source: PegKeeperRegulator.vy (curvefi/curve-stablecoin master) + verified deploy 0x36a04CAffc681fa179558B2Aaba30395CDdd855f (Etherscan)].
- Version: [VERIFIED 2026-09-01: all four docs-listed keepers are V2 under the regulator: USDC 0x9201da0D97CaAAff53f01B2fB56767C7072dE340, USDT 0xFb726F57d251aB5C731E5C64eD4F5F94351eF9F3, pyUSD 0x3fA20eAa107DE08B38a8734063D605d5842fe09C, frxUSD 0x338Cb2D827112d989A861cDe87CD9FfD913A1f9D. Source: docs.curve.finance static/deployments.json (snapshot 2026-08-21)].
- Instances:
  - crvUSD/USDC keeper — pool [FIRST-RUN READ: live value]; ceiling [ANALYST-SUPPLIED 2026-09-01: USDC ceiling not web-resolvable (history: 25M 2024 → 45M by Aug 2025 → raised Oct 2025 vote, ×3 claimed); [FIRST-RUN READ: debt_ceiling]]
  - crvUSD/USDT keeper — pool [FIRST-RUN READ: live value]; ceiling [VERIFIED 2026-09-01: USDT ceiling $135M — Curve News July 2026 recap]
  - crvUSD/pyUSD keeper — [VERIFIED 2026-09-01: pyUSD keeper active (docs deployments 2026-08-21); ceiling history 15M→5M (Sept 2024)→15M (Aug 2025) → current [FIRST-RUN READ: debt_ceiling]]
  - Other keepers added since 2025 — [FIRST-RUN READ: live value]
  - crvUSD/GHO keeper — [VERIFIED 2026-09-04: a **fifth keeper** 0x53876b157decf04389eed66c7c29d73863f8c50b, pool 0x635ef0056a597d13863b73825cca297236578595 (GHO/crvUSD), is registered in the regulator and read live at index 4; `debt_ceiling` = 0 and `debt()` = 0 at block 25905210. This **settles the P4 source conflict** recorded above — Pharos and LlamaRisk indicated a GHO PegKeeper, the docs list did not — in favour of existence. Discovered by the per-run registry read, never a list, which is what P4 exists for. Its zero ceiling exercises DET-21/R-11's ceiling-zero branch live]
  - Retired keepers (USDP, TUSD) — [VERIFIED 2026-09-01: USDP/TUSD not in docs keeper list — retired (TUSD ceiling→0 Sept 2024); USDM keeper (added Oct 2024, 10M) also absent from 2026-08-21 docs list — treat as retired, confirm via regulator.peg_keepers(). CONFLICT: Pharos (Jun 2026) and LlamaRisk (Mar 2026 onboarding review) indicate a GHO PegKeeper — not in docs list; see candidate open point]
- Aggregate ceiling: [FIRST-RUN READ: live value]. Reported as upper bound of the stabilizer slice.
- Reads per keeper per run: debt(), LP balance, pool balances, pool virtual price, ceiling, regulator status. Provenance: block + timestamp.
- **Per-run H1 reads (memo §6.3 H1):** `regulator.is_killed()`, `regulator.alpha()`, `regulator.beta()`, `regulator.peg_keepers()` (discovery — P4, never hardcoded), per keeper `debt()` and `STABLECOIN.balanceOf(keeper)`, `ControllerFactory.debt_ceiling(keeper)`. Feeds the effective-vs-naive dual figure under metric 4.
- Paired-asset look-through (disclosure value only, nothing credited): USDC → Circle; USDT → Tether; pyUSD → Paxos (memo §4.5).
- Stress: flow mechanic on two paths per memo §3; burn capacity = outstanding debt.
**Per-position reads (memo §9 position netting):** for every open position in every mint market — band range, external collateral, crvUSD held in bands, gross debt [VERIFIED 2026-09-01: Controller exposes user_state(user) → (collateral, stablecoin, debt, N) and AMM read_user_tick_numbers; loans enumerable via loans(i)/n_loans. Source: curvefi/curve-stablecoin controller.vy]. Metric 1 uses external collateral over net debt; band-held crvUSD never enters the §4 tree.
 
**Supply-origination gate (crvUSD-specific form of the Morpho lesson)**
 
[VERIFIED 2026-09-01: confirmed — Curve News July 2026 recap: LlamaLend V2 on mainnet 21 July 2026 (sDOLA, sfrxUSD, syrupUSDC markets). Mint markets remain under ControllerFactory 0xC9332fdCB1C491Dcc683bAe86Fe3cb70360738BC (MintController); lend factories separate ([FIRST-RUN READ: lending factory addresses from docs deployments.json /ethereum/lending]). Gate ACTIVE] If confirmed, the adapter separates:
- **MINT markets** — crvUSD controllers minting new crvUSD against collateral: supply origination; collateral counts as backing.
- **LEND markets** — existing crvUSD deposited by lenders and re-lent: no supply creation; collateral (CRV, others) backs lenders' claims, **not** crvUSD supply.
Discovery by factory/controller address class [VERIFIED 2026-09-01: mint = ControllerFactory 0xC9332fdCB1C491Dcc683bAe86Fe3cb70360738BC (docs.curve.finance static/deployments.json (snapshot 2026-08-21)); lend = OneWayLendingFactory + V2 factory [FIRST-RUN READ: deployments.json]], never by asset symbol. Lend-market crvUSD counted as minted supply is a double-count. If the V2 claim is not confirmed, the gate is still recorded and applied to LlamaLend V1 crvUSD lend markets vs. mint markets, which already share the distinction.
 
**Supply comparand note (DET-62)** [ANALYST-SUPPLIED 2026-09-03: DefiLlama reports Ethereum-chain *circulating* for crvUSD; the ruled comparand is mainnet `totalSupply()`. DefiLlama's figure is **accepted as the comparand within the ruled 5% tolerance** — convention mismatch acknowledged and absorbed by the tolerance, never equated. Source: stablecoins.llama.fi, coverage verified 2026-09-03]
 
**Pool set (exit liquidity):** Rule: memo §5. Frozen set established at first run by three-way discovery; §5.4 exclusions apply (crvUSD/wstETH, crvUSD/WETH-type pools excluded as circular; PegKeeper pools included in full). Expected pools [FIRST-RUN READ: discovery; expected incl. PegKeeper pools USDC/USDT/pyUSD/frxUSD (frxUSD needs §4 row)], crvUSD/USDe or other synthetic pairs [RE-SCOPED TO INTAKE: frxUSD and any other keeper paired asset gets its §4 row at freeze; unlabeled → §8.2 (memo §9 stabilizer instance, P4)], any tricrypto-style pools (paired with volatile assets)]. Off-venue share and bridged/L2 supply disclosed per §5.1–5.2 [FIRST-RUN READ: bridge contract balances; lock-vs-burn per bridge].
 
**Stress hooks (memo §6.3):**
- H1 crash path — **state-conditional capacity (memo §6.3 H1, ruled 2026-09-02).** Per keeper, per run: (1) regulator `is_killed` Provide flag → killed keeper contributes zero; [ANALYST-SUPPLIED 2026-09-12: `PegKeeper.is_killed()` REVERTS on all five keepers; the flag is ONE regulator-level value applied to every keeper. Verified source, `Peg Keeper Regulator` vyper 0.3.10 at 0x36a04CAffc681fa179558B2Aaba30395CDdd855f, lines 65-67: `enum Killed: Provide  # 1 / Withdraw  # 2` — a bit flag, decoded into `is_killed_provide` / `is_killed_withdraw` with the regulator's own read as provenance. Live value 0 at 25956063. P-6.01 R8; P-6.06 R-B3.3.] (2) read α, β (`regulator.alpha()`, `regulator.beta()`), each keeper's `debt()` and crvUSD balance; deployable = (α + β·Σ√r_others)² × (debt + balance) − debt. Capacity = Σ over live keepers. **Metric 4 prints both:** effective deployable headroom vs. naive ceiling − debt. Counterfactual: discretionary kill mid-crash → zero. Verified 2026-09-01: regulator 0x36a04CAffc681fa179558B2Aaba30395CDdd855f, deployed α = 0.5, β = 0.25 (source + Etherscan); USDT ceiling $135M (Curve News July 2026); other ceilings `ControllerFactory.debt_ceiling(pk)` per run.
- H1 depeg path (Member 2) — primary: V2 gating effective, no new mint, LP share stuck in depegging asset (metric 4). Counterfactual: V1 contagion mint sized by headroom. [VERIFIED 2026-09-01: see memo §6.3 H1 — four-condition block incl. cross-pool worst_price_threshold 0.03%; discretionary kill switch exists (admin or Emergency DAO). Source: PegKeeperRegulator.vy (curvefi/curve-stablecoin master) + verified deploy 0x36a04CAffc681fa179558B2Aaba30395CDdd855f (Etherscan)]
- PegKeeper `price_deviation` — RECORDED, not modeled (P-6.01 R9): a metric-4 disclosure line, no model term. [ANALYST-SUPPLIED 2026-09-12: verified 0.05% on 2026-09-01; the live read at 25956063 is 1e18. The two are not reconciled here — the value is disclosed at the run block and enters no capacity term. The 2026-09-01 verification stands as written; this note records the divergence rather than resolving it.]
- LLAMMA band depth + arbitrage appetite as primary capacity [FIRST-RUN READ: AMM.A(), Controller.n (per loan), AMM.bands_x/bands_y]. Arbitrage sell-side bounded by the §6.3 collateral-sell-side parameter per node.
- Volatile nodes for Member 1: WETH, wstETH, sfrxETH, weETH (LST/LRT axis applies), WBTC, tBTC, cbBTC, LBTC. Cells: 47. [ANALYST-SUPPLIED 2026-09-12: LBTC added — live mint-market collateral found at first contact 2026-09-04 (P-3.28), after this line was written; `labels.toml` has carried its row since 2026-09-08.]

**Metric-4 field set (DET-38; `m4_fields[]`)** — the PER-TOKEN UNION: every cell carries every key, and a key not applicable to a cell's member carries `0` with a `reason` literal naming it (e.g. `reason = "not applicable — Member 1"`), the form DET-51 already uses for `redemption_capacity` on the crash path.

crvUSD (18): effective, naive, is_killed, alpha, beta, provide_allowed, withdraw_allowed, burn_capacity, stabilizer_debt_post_cell, ceiling_aggregate, utilization_post_cell, pegkeeper_lp_share, paired_units_held, pool_tilt_post_cell, exit_depth_cell, lp_flight_share, oracle_spot_gap, counterfactual_ref.

NAMED DEFAULTS (implementer, not rubric): `pegkeeper_lp_share`, `paired_units_held` and `pool_tilt_post_cell` are the Builder's names for the three quantities DET-27 describes in prose without naming — "metric 4 prints quantities only (LP share, paired-asset units held, pool tilt post-cell)". Every other key is the rubric's own identifier. `sp_balance_read` is a lineage key (DET-51 Member-1 capacity), not an `m4` key, and is deliberately absent.

**stock-only capacity — direction of error per mechanism** (DET-53; `bias_table[]`, Appendix C seed)

| Mechanism | Token | Direction | Reason |
|---|---|---|---|
| Collateral-sell-side bound ★ | crvUSD, GHO | overstates | full bound treated as immediately absorbable |
| GSM cap headroom (H2.i) ★ | GHO | overstates | full cap headroom treated as instantly mintable |
| Liquidator recycling (H5) ★ | GHO | understates | no multi-round capital recycling |
| Stability Pool refills (H3) ★ | LUSD | understates | no SP deposits between liquidation waves |
| PegKeeper effective headroom (H1) | crvUSD | overstates | full effective headroom treated as deployed within the window; peer co-deployment dynamics omitted — runs conservative |
| H4 redemption capacity | LUSD | overstates | full schedule capacity treated as immediately available; base-rate decay (regenerative, 12h half-life) omitted — runs conservative |
| H5 liquidator appetite (composite) | GHO | both | two named opposite-sign terms; DET-47 `binding_side` states per cell which dominates |
| Pool exit depth — no LP inflow | all | understates | no LP inflow modeled |
| Pool exit depth — LP sticky at flight-0 | all | overstates | static composition; spread disclosed by the LP-flight grid |

★ = mandatory literal (DET-53).

**Collateral-sell-side capacity (memo §6.3, §11.13; DET-52)** — "amount of [node] absorbable into stable markets within the shock window at ≤ 2% impact".

| Tag | Address | Value | Source | Date |
|---|---|---|---|---|
| SS-WETH | 0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2 | 13750.0000 | Paraswap prices API v6.2, Ethereum mainnet, ~2% price impact into USDC by bisection against a small reference quote; tools/sell_side.py run by Amin, 2026-09-12 | 2026-09-12 |
| SS-wstETH | 0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0 | 609.3750 | Paraswap prices API v6.2, Ethereum mainnet, ~2% price impact into USDC by bisection against a small reference quote; tools/sell_side.py run by Amin, 2026-09-12 | 2026-09-12 |
| SS-sfrxETH | 0xac3e018457b222d93114458476f3e3416abbe38f | 10.2539 | Paraswap prices API v6.2, Ethereum mainnet, ~2% price impact into USDC by bisection against a small reference quote; tools/sell_side.py run by Amin, 2026-09-12 | 2026-09-12 |
| SS-weETH | 0xcd5fe23c85820f7b72d0926fc9b05b43e359b7ee | 5000.0000 | Paraswap prices API v6.2, Ethereum mainnet, ~2% price impact into USDC by bisection against a small reference quote; tools/sell_side.py run by Amin, 2026-09-12 | 2026-09-12 |
| SS-WBTC | 0x2260fac5e5542a773aa44fbcfedf7c193bc2c599 | 131.2500 | Paraswap prices API v6.2, Ethereum mainnet, ~2% price impact into USDC by bisection against a small reference quote; tools/sell_side.py run by Amin, 2026-09-12 | 2026-09-12 |
| SS-cbBTC | 0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf | 34.3750 | Paraswap prices API v6.2, Ethereum mainnet, ~2% price impact into USDC by bisection against a small reference quote; tools/sell_side.py run by Amin, 2026-09-12 | 2026-09-12 |
| SS-LBTC | 0x8236a87084f8b84306f72007f36f2618a5634494 | 17.8125 | Paraswap prices API v6.2, Ethereum mainnet, ~2% price impact into USDC by bisection against a small reference quote; tools/sell_side.py run by Amin, 2026-09-12 | 2026-09-12 |
| SS-tBTC | 0x18084fba666a33d37592fa2633fd49a74dd93a88 | 28.1250 | Paraswap prices API v6.2, Ethereum mainnet, ~2% price impact into USDC by bisection against a small reference quote; tools/sell_side.py run by Amin, 2026-09-12 | 2026-09-12 |
- Member 2 target stable: set at pool-set freeze (memo §6.2.5) — expected USDC or USDT (set at first freeze; not a Phase B item). Forced-sell numerator zero by construction → structural-insulation finding; Member 2 told via exit-depth curve + metric 4 (PegKeeper LP share).
**Quarantine instances (memo §8.1):**
- (c) Market-count: mint-market count from the controller factory. Addition with known node → L1; removal → L2. Lend-market count changes are logged but do not trigger (excluded by the supply-origination gate).
- (d) Mechanism near bound → L1: any PegKeeper debt > 80% of its ceiling, or aggregate PegKeeper debt > 80% of aggregate ceiling [ANALYST-SUPPLIED 2026-09-01: USDT $135M (Curve News July 2026); others first-run read]. Mirrored in the monitoring brief.
- (a), (b): archetype defaults (10pp / 25% two-branch).
**Oracle sources (memo §7):** per-market price oracle contracts [FIRST-RUN READ: AMM.price_oracle_contract() per market], crvUSD price aggregator [VERIFIED 2026-09-01: AggregateStablePrice v3 0x18672b1b0c623a30089A280Ed9256379fb0E4E62; composition [FIRST-RUN READ: price_pairs()]; frxUSD pool oracle added Aug 2025 (Curve News)], LLAMMA EMA smoothing [VERIFIED 2026-09-01, CORRECTED 2026-09-04: the 2026-09-01 note said the window is read from the oracle's own MA_EXP_TIME()/ma_exp_time getter. **No such getter exists on any of the nine deployed market oracles** — all four spellings revert (P-3.31). The EMA architecture is real but the parameter sits one level down: **price-EMA smoothing lives on the constituent pools** (`ma_time`/`ma_exp_time`), while the oracle's own `TVL_MA_TIME` smooths the pool-weighting series — a different quantity, not substituted. `ema_window_s` per market is the **transitive max** over the constituent chain; constituents come from the oracle's address getters where exposed, from `POOLS(i)`/`POOL_COUNT` for `CryptoFromPool`-class oracles, and from the verified deploy's constructor arguments where the ABI advertises immutables the bytecode does not expose. Values are per deployment — [FIRST-RUN READ: Controller.amm().price_oracle_contract() → constituent windows, transitive max]. Aggregator: AggregateStablePrice v3 0x18672b1b0c623a30089A280Ed9256379fb0E4E62 (TVL_MA_TIME 50000s), legacy 0xe5Afcf332a5457E8FafCD668BcE3dF953762Dfe7. Source: curvefi/curve-stablecoin price_oracles/*.vy; docs.curve.finance static/deployments.json (snapshot 2026-08-21)]. §7 assumption: instant observation primary, knowingly optimistic for LLAMMA; EMA counterfactual line under metric 4 (bounded approximation, labeled).
**Redemption-rights (memo §12) — holder paths: 1 (none)**
 
| Field | Path 1 |
|---|---|
| R1 path | `none` — no holder redemption function exists on any crvUSD contract [VERIFIED 2026-09-01: no holder redemption function on MintController/factory/token — curve-stablecoin source review (controller.vy, Stablecoin.vy)] |
| R2 who | `no_one` |
| R3–R5 | — |
| R6 gates | — |
| R7 capacity | — |
| R8 (computed) | `n/a` |
| R9 legal claim | `no_pure_protocol` — no terms of service; the on-chain mechanism is the only claim, and for holders it grants none |
| R10 provenance | absence of function; contract set as listed above [FIRST-RUN READ: live value] |
 
Note: PegKeeper pools and Curve pools are markets, not redemption (§5); holder exit is exit depth, not a right. Borrower close-out is the mechanism, out of scope (§12).
 
**Admin-power surface (memo §13)** — every holder, delay, and function [FIRST-RUN READ: live value]:
 
| A1 power | A2 holder | A3 signers | A4 delay (s / bucket) | A5 veto | A6 upgradeability | A7 scope | A8 provenance |
|---|---|---|---|---|---|---|---|
| `mint` | Curve DAO (ownership agent) [FIRST-RUN READ: live value] — adding a PegKeeper or raising `rug_debt_ceiling`-type factory mint to a controller creates supply capacity | n/a (DAO) | DAO vote period ≈ 7d [VERIFIED 2026-09-01: 7-day vote (30% quorum / 51% support for ownership votes); execution permissionless immediately after the vote passes — no post-vote timelock. Raw 604,800s; bucket 1–7d (at edge). Sources: docs.curve.finance/governance/overview; resources.curve.finance] | Emergency DAO multisig [VERIFIED 2026-09-01: Emergency DAO 5-of-9 multisig 0x6d447e544D01a59cb0774763bf15526574CffFeD (agent 0x467947EE34aF926cF1DCac093870f613C96B1E0c); powers limited to emergency actions — kill gauges, crvUSD price-stability actions (regulator set_killed). Sources: resources.curve.finance governance overview; Blockworks transparency filing; docs.curve.finance static/deployments.json (snapshot 2026-08-21)] | — | factory, PegKeeper regulator [FIRST-RUN READ: live value] | factory admin functions [FIRST-RUN READ: live value] |
| `set_ceiling` | Curve DAO [FIRST-RUN READ: live value] | n/a | as above | Emergency DAO (reduce only?) [FIRST-RUN READ: live value] | — | per-controller debt ceilings; PegKeeper ceilings | factory `set_debt_ceiling`; PegKeeper/regulator [FIRST-RUN READ: live value] |
| `upgrade` | `none` expected — Vyper contracts deployed without proxies; new implementations affect future markets only [VERIFIED 2026-09-01: crvUSD contracts are Vyper deployments without proxies; the factory can set new implementations for FUTURE markets only ('Implementation contracts are upgradable' — docs.curve.finance/deployments/crvusd) → A6 = immutable per live market, upgrade power = new-market implementations] | — | — | — | `immutable` [FIRST-RUN READ: live value] | — | bytecode / no admin-upgrade function [FIRST-RUN READ: live value] |
| `pause` | [VERIFIED 2026-09-01: Emergency DAO can kill PegKeeper Provide/Withdraw via regulator.set_killed (if set as emergency_admin — [FIRST-RUN READ: regulator.emergency_admin()]); market-level halt powers (set_debt_ceiling to 0) are ownership-agent functions — map `pause` to Emergency DAO for stabilizer only] | | | | | | |
| `freeze_asset` | `none` expected [FIRST-RUN READ: live value] | | | | | | |
| `blacklist_address` | `none` expected [FIRST-RUN READ: live value] | | | | | | |
| `set_oracle` | Curve DAO [VERIFIED 2026-09-01: Controller.set_price_oracle-type setters exist on MintController (curve-stablecoin controller.vy, admin = factory admin = DAO); regulator.set_aggregator by admin] | n/a | as `mint` | Emergency DAO? [FIRST-RUN READ: live value] | — | per-market oracles; aggregator | [FIRST-RUN READ: live value] |
| `set_parameters` | Curve DAO [VERIFIED 2026-09-01: factory.set_monetary_policy/set_fee etc. (DAO); regulator set_worst_price_threshold / set_price_deviation / set_debt_parameters / set_aggregator (admin only); AggMonetaryPolicy4 adds set_debt_ratio_ema_time — curve-stablecoin source] | n/a | as `mint` | Emergency DAO [FIRST-RUN READ: live value] | — | all markets; regulator | [FIRST-RUN READ: live value] |
| `seize` | `none` expected [FIRST-RUN READ: live value] | | | | | | |
 
**Qualifier block (memo §13):** expected — `mint` — DAO, veto: Emergency DAO; `set_oracle` — DAO; `upgrade` — none (immutable); `seize` — none. Delay buckets are per-run reads (DET-68 A4). Final content follows Phase B.
 
**Audit status (memo §14):** audits [VERIFIED 2026-09-01: crvUSD infrastructure: MixBytes 2023-06-05, ChainSecurity 2024-01-24, ChainSecurity 2025-02-21; PegKeeperV2: ChainSecurity 2023-12-12; FastBridge (cross-chain crvUSD): ChainSecurity 2024-10-25; LlamaLend: MixBytes 2024 — docs.curve.finance/developer/security]; bug bounty [ANALYST-SUPPLIED 2026-09-01: Curve: bug bounty program stated on docs (platform/max not surfaced); GHO: Immunefi (LlamaRisk Mar 2026); Liquity: active bounty (TokenBrice) — max values first-run analyst entry]; last material change audited [ANALYST-SUPPLIED 2026-09-01: LlamaLend V2 audit status not surfaced — analyst entry]. Staleness date: set at Phase B. Never scored.
 
**Counterparty enumeration (memo §14):** n/a — archetype #1 holds no off-chain counterparties. WBTC custodian captured in §4 look-through.
 
 
**`first_run_reads[]` (DET-75 / R-45)** — registry of every FIRST-RUN READ tag on this sheet, resolved to a concrete read. **Count identity: 35 literal tags − 2 (misplaced Liquity tags deleted by this edit) + 1 (tBTC tag added by this edit) = 34 tags = 34 open rows, FR-36 included.** All reads at `run_block`. Shorthand: **CF** = ControllerFactory 0xC9332fdCB1C491Dcc683bAe86Fe3cb70360738BC · **REG** = PegKeeperRegulator 0x36a04CAffc681fa179558B2Aaba30395CDdd855f · **AGG** = AggregateStablePrice 0x18672b1b0c623a30089A280Ed9256379fb0E4E62 · **CRVUSD** = 0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E. `sheet_location` is a section anchor rather than a line number, so the registry survives later edits.
 
| tag_id | sheet_location | bundle_field_path | read_spec | status |
|---|---|---|---|---|
| FR-02 | crvUSD § Collateral nodes | `markets[]` | `CF.n_collaterals()`; `CF.controllers(i)` / `amms(i)` / `collaterals(i)` ∀i | open |
| FR-04 | crvUSD § PegKeepers — USDC instance | `stabilizers[USDC].paired_pool_address` | `REG.peg_keepers()[i].pool` | open |
| FR-05 | crvUSD § PegKeepers — USDC instance | `stabilizers[USDC].debt_ceiling` | `CF.debt_ceiling(pk)` (O18: this row carries the ceiling read) | open |
| FR-06 | crvUSD § PegKeepers — USDT instance | `stabilizers[USDT].paired_pool_address` | `REG.peg_keepers()[i].pool` | open |
| FR-07 | crvUSD § PegKeepers — pyUSD instance | `stabilizers[pyUSD].debt_ceiling` | `CF.debt_ceiling(pk)` | open |
| FR-08 | crvUSD § PegKeepers — other keepers | `stabilizers[]` (completeness) | `REG.peg_keepers(uint256)` walked from index 0 until the getter reverts — a Vyper DynArray public getter is an INDEXED accessor, not an array return; the struct is 4-member `(address peg_keeper, address pool, bool is_inverse, bool include_index)`. Corrected 2026-09-04 (P-3.20): the zero-arg form reverts. Retired keepers absent by construction | open |
| FR-09 | crvUSD § PegKeepers — aggregate ceiling | `stabilizer.ceiling_aggregate` | Σ over per-keeper `CF.debt_ceiling(pk)`; derived — carries `lineage`, not provenance | open |
| FR-10 | crvUSD § Supply-origination gate | `lend_factories[]` | dated `discovery_roots.toml` entry + on-chain confirmation (code present, enumerates markets) | open |
| FR-11 | crvUSD § Supply-origination gate | `lend_factories[].origination_class` | as FR-10; feeds DET-07 | open |
| FR-12 | crvUSD § Pool set | `discovered_pools[]`, `frozen_set` | three-way discovery; `pool.balances(i)` at par for TVL and coverage | open |
| FR-13 | crvUSD § Pool set | `supply.bridges[]` | `CRVUSD.balanceOf(bridge)` — **amount only**; `bridge_type` from the DET-33 menu, never inferred from a balance | open |
| FR-14 | crvUSD § Stress hooks | `markets[].{a_coefficient, band_range_occupied, collateral_in_bands}` | `AMM.A()`; `AMM.bands_x(i)`/`bands_y(i)` over the occupied range | open |
| FR-15 | crvUSD § Oracle sources | `markets[].oracle_address` | `Controller.amm()` → `AMM.price_oracle_contract()` | open |
| FR-16 | crvUSD § Oracle sources | `aggregator.price_pairs[]` | `AGG.price_pairs(i)` + count | open |
| FR-17 | crvUSD § Oracle sources | `markets[].ema_window_s` | **transitive max over the oracle's constituent price-EMA windows** (P-3.31/P-3.32/P-3.33): constituent pools via the oracle's own address getters where exposed, via `POOLS(i)`/`POOL_COUNT` for `CryptoFromPool`-class oracles, and via the verified deploy's constructor arguments where the ABI advertises immutables the bytecode does not expose (config `[[oracle_constituents]]`, addresses only — windows read on-chain per run); each pool's `ma_time()`/`ma_exp_time()` at `run_block`; a chained oracle recurses and its chain contributes to the same max | open |
| FR-18 | crvUSD § Redemption-rights R10 | `redemption_paths[0].r10_provenance` | selector-absence scan over `eth_getCode(CRVUSD)`, `eth_getCode(CF)` | open |
| FR-19 | crvUSD § Admin-power surface (header) | `admin_surface[]` | umbrella — A1–A8 table present, nine powers | open |
| FR-20 | crvUSD § Admin surface — `mint` A2 | `admin_surface[mint].holder` | `CF.admin()` | open |
| FR-21 | crvUSD § Admin surface — `mint` A7 | `admin_surface[mint].scope` | `{CF, REG}` addresses | open |
| FR-22 | crvUSD § Admin surface — `mint` A8 | `admin_surface[mint].reads` | provenance of the FR-20 read | open |
| FR-23 | crvUSD § Admin surface — `set_ceiling` A2 | `admin_surface[set_ceiling].holder` | `CF.admin()` | open |
| FR-24 | crvUSD § Admin surface — `set_ceiling` A5 | `admin_surface[set_ceiling].veto` | `REG.emergency_admin()` | open |
| FR-25 | crvUSD § Admin surface — `set_ceiling` A8 | `admin_surface[set_ceiling].reads` | provenance of the FR-23 / FR-24 reads | open |
| FR-26 | crvUSD § Admin surface — `upgrade` A6 | `admin_surface[upgrade].upgradeability` | `eth_getStorageAt` EIP-1967 implementation slot = 0 ∀ live market contract | open |
| FR-27 | crvUSD § Admin surface — `upgrade` A8 | `admin_surface[upgrade].reads` | slot reads + `eth_getCode` hash | open |
| FR-28 | crvUSD § Admin surface — `pause` A2 | `admin_surface[pause].holder` | `REG.emergency_admin()` | open |
| FR-29 | crvUSD § Admin surface — `freeze_asset` A2 | `admin_surface[freeze_asset].holder` | selector-absence scan → `none` | open |
| FR-30 | crvUSD § Admin surface — `blacklist_address` A2 | `admin_surface[blacklist_address].holder` | selector-absence scan → `none` | open |
| FR-31 | crvUSD § Admin surface — `set_oracle` A5 | `admin_surface[set_oracle].veto` | `REG.emergency_admin()` | open |
| FR-32 | crvUSD § Admin surface — `set_oracle` A8 | `admin_surface[set_oracle].reads` | provenance of the FR-31 read | open |
| FR-33 | crvUSD § Admin surface — `set_parameters` A5 | `admin_surface[set_parameters].veto` | `REG.emergency_admin()` | open |
| FR-34 | crvUSD § Admin surface — `set_parameters` A8 | `admin_surface[set_parameters].reads` | provenance of the FR-33 read | open |
| FR-35 | crvUSD § Admin surface — `seize` A2 | `admin_surface[seize].holder` | selector-absence scan → `none` | open |
| FR-36 | crvUSD § Collateral nodes — tBTC row (tag added by this edit) | `nodes[tBTC].label`, `nodes[tBTC].label_provenance` | tBTC `WalletRegistry` read; label ∈ {`terminal_other_layer`, `recurses`} per DET-76(c); unreachable ⇒ unlabeled-in-run → §8.2 | open |
 
*FR-01 and FR-03 are retired with the misplaced Liquity tags deleted by this edit; their ids are reserved, not reused.*
---
 
## GHO
 
**Archetype assignment:** #1, CDP / on-chain-backed — with two facilitator sub-mechanisms. Fit test: primary supply originates when a borrower draws GHO against pledged collateral with a liquidation path — passes [VERIFIED 2026-09-01, CORRECTED 2026-09-08: the aToken-facilitator form is gone. `GhoToken.getFacilitatorsList()` at block 25930871 returns EIGHT facilitators; three are `*GhoDirectMinter` contracts that PRE-MINT GHO into three Aave instances as supply — `CoreGhoDirectMinter` 0x5513224d… -> Pool 0x87870Bca…, `LidoGhoDirectMinter` 0x2ce01c87… -> 0x4e033931…, `HorizonGhoDirectMinter` 0xe10c78a3… -> 0xae05cd22…. Circulating GHO originates on the BORROWER DRAW; the undrawn pre-minted balance is protocol-held inventory. Archetype #1 stands and all three instances enter the adapter; the three minters are `facilitators[]` rows with `facilitator_class = direct_minter`, each carrying pool, bucket capacity/level and drawn debt with principal and accrued interest separated, and `markets[]` is empty for GHO (P-4.04 R1)]. GSM supply is asset-in-a-box (memo §3 exclusion), backed by the boxed asset via look-through.
 
**Contracts to read**:
- GHO token; GhoToken facilitator registry — facilitator discovery (list, bucket caps, current levels); hardcoded lists forbidden.
- Aave V3 Ethereum Pool, PoolDataProvider — per-reserve and per-position reads.
- GSM contracts per boxed asset [VERIFIED 2026-09-01: USDC and USDT GSMs live (addresses above); a GHO_DIRECT_FACILITATOR_MAINNET_GSMS 0xE9ac5231… exists (address book) — facilitator list [FIRST-RUN READ: GhoToken.getFacilitatorsList()]].
- **Per-run H2 reads (memo §6.3 H2):** per GSM — `getRoleMember(SWAP_FREEZER_ROLE, i)` on the GSM (role registry) to confirm an OracleSwapFreezer-type holder; on the freezer: `getFreezeBound()`, `getUnfreezeBound()`, `getCanUnfreeze()`, `GSM()`; GSM `getIsFrozen()`, `getIsSeized()`. Addresses per H2 bullet (aave-address-book, 2026-09-01). Output feeds the Member 2 primary selection and the L1 flag.
- Other facilitators [VERIFIED 2026-09-01: FlashMinter facilitator 0xb639D208Bcf0589D54FaC24E655C79EC529762B8 (transient, exclude); CCIP token pool = lock-and-mint on Ethereum (see §8.1.4(b))].
**Node enumeration scope (memo §4.5 note, ruled 2026-09-02, P2):** this table is a **freeze-time artifact** — reserves with non-zero attributed GHO backing at pool-set freeze, refreshed quarterly; between-freeze newcomers route via §8.2. Reserve universe enumerated across ALL THREE Aave instances [VERIFIED 2026-09-01, CORRECTED 2026-09-08: the universe is not one Aave V3 Ethereum reserve list but three — Core 67 reserves, Lido/Prime 9, Horizon 11, 75 distinct addresses, of which 34 are in use as GHO-borrower collateral at block 25930871 across 37 instance-reserve slots. Nodes are keyed by UNDERLYING ASSET ADDRESS across instances; the instance is recorded on each read (P-4.04 R1)] and includes synthetics, LRTs, custodial BTC wrappers, XAUt, other analyzed stables, and Pendle PT tokens — rows added at freeze per §4 rules; unlabeled nodes → §8.2.
 
**Collateral nodes currently held** [VERIFIED 2026-09-01: Aave V3 Ethereum reserve list (bgd-labs/aave-address-book main (GhoEthereum.sol, AaveV3Ethereum.sol, GovernanceV3Ethereum.sol)) includes, beyond expected nodes: USDe/sUSDe/eUSDe/USDtb (synthetic), rsETH/ezETH/weETH/osETH/ETHx/tETH (LRT/LST), cbBTC/LBTC/eBTC/FBTC/BTCb (custodial or bridged BTC), XAUt, EURC, RLUSD, PYUSD, crvUSD, LUSD, and multiple Pendle PT tokens — most have NO §4 row; attributed weights [FIRST-RUN READ: attribution]; §8.2 likely fires → candidate open point]:
 
| Node | Memo §4.5 row | Label |
|---|---|---|
| aWETH → WETH → ETH | aTokens / WETH | transparent → `terminal` |
| awstETH / arETH → LST | LST | `terminal_other_layer` |
| aWBTC → WBTC | WBTC | `recurses` |
| aUSDC → USDC | USDC | `recurses` (Circle) |
| aUSDT → USDT | USDT | `recurses` (Tether) |
| aDAI / aUSDS / asDAI → DAI/USDS | DAI/USDS | `recurses_truncated` (Sky) [FIRST-RUN READ: attribution] |
| aLINK, aAAVE, other governance tokens | governance/volatile | `terminal` |
| aweETH / other LRTs | LRT | `terminal_other_layer` — memo §4.5 LRT-family row (ruled 2026-09-02; §11 item 2 resolved) [FIRST-RUN READ: attribution] |
| acbETH | cbETH | `recurses` — memo §4.5 cbETH row (ruled 2026-09-02; §11 item 2 resolved); disclosure cadence re-scoped to this sheet by that row and still owed [FIRST-RUN READ: attribution] |
| GSM boxed waEthUSDC / waEthUSDT | USDC / USDT via memo §4.3 | `recurses` [ANALYST-SUPPLIED 2026-09-12: the GSMs' `UNDERLYING_ASSET()` is `waEthUSDC` 0xd4fa2d31b7968e448877f69a96de69f5de8cd23e and `waEthUSDT` 0x7bc3485026ac48b6cf9baf0a377477fff5703af8 — `StataTokenV2` (ERC-4626) behind proxies on verified implementation 0x487c2c53c0866f0a73ae317bd1a28f63adcd9ad1, NOT bare USDC/USDT. The walk wrapper → aToken → underlying closes at USDC and USDT and is a production read every run; balances are SHARES and convert at `convertToAssets` (1.185074933 / 1.174832582 at 25946240). Memo §4.3 pass-through, no level consumed. P-6.05; Inventory B F14.] |
| Any other | — | unlisted → §8.2 quarantine rule |
 
Expected verifiability result (Step-5 done-condition): a defensible non-trivial split — meaningful `recurses` weight via stables and WBTC, one `recurses_truncated` slice, remainder `terminal` / `terminal_other_layer`.
 
**Token-specific mechanisms:**
- *Facilitator caps* — per-facilitator bucket capacity and level are Tier-1 parameters; the Aave facilitator cap bounds CDP-originated supply, GSM exposure caps bound boxed supply.
- *GSM* — memo §3 exclusion applies: backed 1:1 by boxed asset, look-through per §4.5. Record: fee, price strategy, exposure cap, freeze/seize status [FIRST-RUN READ: live value].
- *Collateral attribution* — memo §11.1 (resolved). **Primary: pro-rata per position** — for each GHO borrower, collateral value × (GHO debt ÷ borrower's total debt), summed. Position enumeration via Aave V3 subgraph + multicall verification [ANALYST-SUPPLIED 2026-09-01: Aave V3 subgraph availability not verified; PoolDataProvider 0x…(AAVE_PROTOCOL_DATA_PROVIDER in address book) getUserReserveData is the on-chain path; position enumeration needs an indexer — implementer choice at Step 4]. **Cross-check: protocol-level ratio** — Aave V3 Ethereum aggregate collateral ÷ aggregate debt applied to Aave-facilitator GHO supply — always computed and reported. Divergence > 10% relative → reported finding. **Fallback:** per-position reads fail → publish on protocol-level with visible flag "attribution: protocol-level fallback"; two consecutive fallback runs → semantic quarantine. The GHO adapter is designed per-position.
**Pool set (exit liquidity):** Rule: memo §5. Frozen set established at first run; §5.4 exclusions apply — GHO pools paired with a *volatile* Aave collateral node held against GHO (e.g., GHO/WETH-type) are circular and excluded; stable-paired pools (GHO/USDC-type) are included per §5.4(ii), with the paired-stable failure modeled under the §6 paired-stable-depeg scenario. Expected pools [FIRST-RUN READ: discovery; GHO/crvUSD pool → analyzed-token rule]. Off-venue share disclosed per §5.1 [FIRST-RUN READ: discovery; Curve-only modeling in Step 4 (P-4.04 R4)] [VERIFIED 2026-09-01, CORRECTED 2026-09-08: Balancer v2 holds $120,227 at block 25930871 — below the $500k floor. The off-venue mass is Fluid DEX $25.83M (78% of GHO's $32.93M Ethereum DEX liquidity), Uniswap v4 $4.76M, Curve $2.13M. Curve-only modeling gives |F| = 1 and X ~ 0.94, so T-02 fires every run at Level 1, published, with a dated §11.6 open-point entry, and the Fluid pointer source IS that open point (P-4.04 R4)]. Bridged/L2 supply via CCIP facilitators disclosed per §5.2 [FIRST-RUN READ: live value].
 
**Stress hooks (memo §6.3):**
- H2 crash path — (i) mint-side capacity: liquidators mint GHO from boxed asset up to exposure-cap headroom [VERIFIED 2026-09-01: see memo §6.3 H2; launch fee 0.2% (AIP-8)]; (ii) holder exit → §5.10 venue line below.
- H2 depeg path (Member 2) — **state-conditional primary (memo §6.3 H2, ruled 2026-09-02).** Per run, per GSM: CHECK (1) an automated OracleSwapFreezer-type contract holds SWAP_FREEZER_ROLE [role-registry read]; (2) its freeze lower bound ≥ 0.88 [freezer band read]. Pass → primary = freezer effective (contagion capped at GSM balance; GSM exit contribution removed from exit depth — same event); counterfactual = freezer fails to act in time (arb mint to exposure-cap headroom, supply backed at shocked price). Fail → primary = freezer fails; "effective" printed as counterfactual; **L1 flag** "automated freeze protection not in place / not effective in modeled range (block N)". Verified 2026-09-01: freezers 0x6e51936e0ED4256f9dA4794B536B619c88Ff0047 (USDC GSM 0x3A3868898305f04beC7FEa77BecFf04C13444112), 0x733AB16005c39d07FD3D9d1A350AA6768D10125b (USDT GSM 0x882285E62656b9623AF136Ce3078c6BdCc33F5E3) — aave-address-book; reference bounds on original instance 0.99/1.01 freeze, 0.995/1.005 unfreeze (Etherscan). Aave DAO executor is second freezer (AIP-8).
- H5 liquidator appetite — capacity = min(GHO sourceable = §5 buy-side depth + GSM mint headroom; collateral sellable = §6.3 analyst parameter per node), within the liquidation bonus; binding side reported per cell (metric 4). [FIRST-RUN READ: PoolDataProvider reads]
- Facilitator bucket caps bound recovery minting only (metric 4) [FIRST-RUN READ: GhoToken reads; bucket steward 0x46Aa1063e5265b43663E81329333B47c517A5409].
- Volatile nodes for Member 1: WETH, wstETH/rETH (LST axis), WBTC, governance tokens, LRTs/cbETH if present. Stable nodes shocked only in Member 2. Cells: 47.

**Metric-4 field set (DET-38; `m4_fields[]`)** — the PER-TOKEN UNION: every cell carries every key, and a key not applicable to a cell's member carries `0` with a `reason` literal naming it (e.g. `reason = "not applicable — Member 1"`), the form DET-51 already uses for `redemption_capacity` on the crash path.

GHO (9): gho_sourceable, collateral_sellable, gsm_mint_headroom, binding_side, facilitator_bucket_levels, freezer_state, exit_depth_cell, lp_flight_share, counterfactual_ref.

NAMED DEFAULTS (implementer, not rubric): `pegkeeper_lp_share`, `paired_units_held` and `pool_tilt_post_cell` are the Builder's names for the three quantities DET-27 describes in prose without naming — "metric 4 prints quantities only (LP share, paired-asset units held, pool tilt post-cell)". Every other key is the rubric's own identifier. `sp_balance_read` is a lineage key (DET-51 Member-1 capacity), not an `m4` key, and is deliberately absent.

**stock-only capacity — direction of error per mechanism** (DET-53; `bias_table[]`, Appendix C seed)

| Mechanism | Token | Direction | Reason |
|---|---|---|---|
| Collateral-sell-side bound ★ | crvUSD, GHO | overstates | full bound treated as immediately absorbable |
| GSM cap headroom (H2.i) ★ | GHO | overstates | full cap headroom treated as instantly mintable |
| Liquidator recycling (H5) ★ | GHO | understates | no multi-round capital recycling |
| Stability Pool refills (H3) ★ | LUSD | understates | no SP deposits between liquidation waves |
| PegKeeper effective headroom (H1) | crvUSD | overstates | full effective headroom treated as deployed within the window; peer co-deployment dynamics omitted — runs conservative |
| H4 redemption capacity | LUSD | overstates | full schedule capacity treated as immediately available; base-rate decay (regenerative, 12h half-life) omitted — runs conservative |
| H5 liquidator appetite (composite) | GHO | both | two named opposite-sign terms; DET-47 `binding_side` states per cell which dominates |
| Pool exit depth — no LP inflow | all | understates | no LP inflow modeled |
| Pool exit depth — LP sticky at flight-0 | all | overstates | static composition; spread disclosed by the LP-flight grid |

★ = mandatory literal (DET-53).

**Collateral-sell-side capacity (memo §6.3, §11.13; DET-52)** — "amount of [node] absorbable into stable markets within the shock window at ≤ 2% impact".

| Tag | Address | Value | Source | Date |
|---|---|---|---|---|
| SS-wstETH | 0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0 | 609.3750 | Paraswap prices API v6.2, Ethereum mainnet, ~2% price impact into USDC by bisection against a small reference quote; tools/sell_side.py run by Amin, 2026-09-12 | 2026-09-12 |
| SS-WETH | 0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2 | 13750.0000 | Paraswap prices API v6.2, Ethereum mainnet, ~2% price impact into USDC by bisection against a small reference quote; tools/sell_side.py run by Amin, 2026-09-12 | 2026-09-12 |
| SS-WBTC | 0x2260fac5e5542a773aa44fbcfedf7c193bc2c599 | 131.2500 | Paraswap prices API v6.2, Ethereum mainnet, ~2% price impact into USDC by bisection against a small reference quote; tools/sell_side.py run by Amin, 2026-09-12 | 2026-09-12 |
| SS-AAVE | 0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9 | 3750.0000 | Paraswap prices API v6.2, Ethereum mainnet, ~2% price impact into USDC by bisection against a small reference quote; tools/sell_side.py run by Amin, 2026-09-12 | 2026-09-12 |
| SS-weETH | 0xcd5fe23c85820f7b72d0926fc9b05b43e359b7ee | 5000.0000 | Paraswap prices API v6.2, Ethereum mainnet, ~2% price impact into USDC by bisection against a small reference quote; tools/sell_side.py run by Amin, 2026-09-12 | 2026-09-12 |
| SS-cbBTC | 0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf | 34.3750 | Paraswap prices API v6.2, Ethereum mainnet, ~2% price impact into USDC by bisection against a small reference quote; tools/sell_side.py run by Amin, 2026-09-12 | 2026-09-12 |
| SS-tBTC | 0x18084fba666a33d37592fa2633fd49a74dd93a88 | 28.1250 | Paraswap prices API v6.2, Ethereum mainnet, ~2% price impact into USDC by bisection against a small reference quote; tools/sell_side.py run by Amin, 2026-09-12 | 2026-09-12 |
| SS-USCC | 0x14d60e7fdc0d71d8611742720e4c50e7a974020c | 0 | Paraswap prices API v6.2, Ethereum mainnet, ~2% price impact into USDC by bisection against a small reference quote; tools/sell_side.py run by Amin, 2026-09-12 — no route on Paraswap — 404 no routes with enough liquidity | 2026-09-12 |
| SS-rETH | 0xae78736cd615f374d3085123a210448e74fc6393 | 968.7500 | Paraswap prices API v6.2, Ethereum mainnet, ~2% price impact into USDC by bisection against a small reference quote; tools/sell_side.py run by Amin, 2026-09-12 | 2026-09-12 |
| SS-LINK | 0x514910771af9ca656af840dff83e8264ecf986ca | 425000.0000 | Paraswap prices API v6.2, Ethereum mainnet, ~2% price impact into USDC by bisection against a small reference quote; tools/sell_side.py run by Amin, 2026-09-12 | 2026-09-12 |
| SS-cbETH | 0xbe9895146f7af43049ca1c1ae358b0541ea49704 | 87.8906 | Paraswap prices API v6.2, Ethereum mainnet, ~2% price impact into USDC by bisection against a small reference quote; tools/sell_side.py run by Amin, 2026-09-12 | 2026-09-12 |
- Member 2 target stable: set at pool-set freeze (memo §6.2.5; set at first freeze, not a Phase B item). Forced-sell numerator = GSM-facilitator bucket level for the shocked boxed asset + the §11.1 pro-rata slice attributed to shocked stable-collateral nodes (aUSDC/aUSDT/aDAI-type as applicable), full slice, not value-weighted.
- Paired-asset notes: GHO/crvUSD-type pools — crvUSD linked to its last published tree (memo §4.1), not shocked in Member 2; any 3CRV-type composite paired asset passes through pro-rata (memo §4.3).
**§5.10 venue line:** GSM counts as a deterministic exit venue — depth = boxed balance, price = 1 − fee, included at s = 2% iff sell fee < 2% [VERIFIED 2026-09-01: 0.2% at launch (AIP-8); current first-run read] [ANALYST-SUPPLIED 2026-09-12: the exit fee is the GSM's **BUY** fee, `getFeeStrategy().getBuyFee(amount)`, not its sell fee: a GHO holder leaving into the boxed asset BUYS that asset. Live at 25946240 — sell fee 0, buy fee 0.1% (USDC GSM) and 0.15% (USDT GSM); the artifact's `fee_exit` carries these. P-6.01 R15; Inventory B F12.]; listed separately from pool depth; removed from exit depth when the freezer trips (Member 2 primary).
 
**Quarantine instances (memo §8.1):**
- (c) Market-count: enabled-collateral count with non-zero GHO backing; GSM count; facilitator count. Addition with known node → L1; removal → L2.
- (d) Mechanism near bound → L1: any GSM utilization > 80% of exposure cap; any facilitator bucket level > 80% of capacity [FIRST-RUN READ: GSM.getExposureCap(); GhoToken.getFacilitatorBucket()]. Mirrored in the monitoring brief.
- Attribution fallback: first run L1, second consecutive run L2 (memo §11.1).
- GSM freezer check failed (role absent or bands ineffective in modeled range) → L1 (memo §6.3 H2), per GSM instance.
- (a), (b): archetype defaults.
**Oracle sources (memo §7):** Aave price oracle → Chainlink feed per reserve [VERIFIED 2026-09-01: Aave V3 Ethereum price sources per reserve are in the address book (e.g., WETH_ORACLE 0x5424384B…, wstETH 0xe1D97bF6…, WBTC 0xDaa4B74C…, USDC 0x3f73F03a…, USDT 0x260326c2…, cbETH 0x889399C3…, rETH 0x6929706c…); several are CAPO/SVR adapters over Chainlink. Underlying Chainlink deviation bands: ETH/USD 0.5%, BTC/USD 0.5%, USDC/USD 0.25%, USDT/USD 0.25%, cbBTC/USD 2% (data.chain.link; yearn/monitoring PR #310). Heartbeats [FIRST-RUN READ: per feed]. Instant-observation assumption holds for ≤1% bands. Sources: bgd-labs/aave-address-book main (GhoEthereum.sol, AaveV3Ethereum.sol, GovernanceV3Ethereum.sol); data.chain.link]. §7 assumption: instant observation, nearly exact given ~0.5–1% deviation triggers.
 
**Redemption-rights (memo §12) — holder paths: 1 + N GSMs** (ruled 2026-09-02, P3: every live GSM gets its own R-block and its own H2 freezer check; live-GSM enumeration at freeze; GSM variant parameters [RE-SCOPED TO INTAKE: fee/price strategy, exposure cap, 4626 allocation per instance]; one block shown)
 
| Field | Path 1 — GSM (per instance) | Path 2 — Aave facilitator |
|---|---|---|
| R1 path | `module_on_chain` | `none` |
| R2 who | `anyone` [VERIFIED 2026-09-01: GSM sellAsset is permissionless per GSM design (docs.gho.xyz); freezer/seize are the only gates [ANALYST-SUPPLIED 2026-09-12: the HOLDER's exit function is `buyAsset` — the holder buys the boxed asset with GHO; `sellAsset` is the MINT direction. P-6.01 R15; Inventory B F12.]] | `no_one` |
| R3 received | boxed asset address [VERIFIED 2026-09-01: GSM_USDC 0x3A3868898305f04beC7FEa77BecFf04C13444112, GSM_USDT 0x882285E62656b9623AF136Ce3078c6BdCc33F5E3 (`StataTokenV2` ERC-4626 wrappers on verified impl 0x487c2c53c0866f0a73ae317bd1a28f63adcd9ad1, passing through to USDC/USDT per memo §4.3 — P-6.05); GSM registry 0x167527DB01325408696326e3580cd8e55D99Dc1A; GHO 0x40D16FC0246aD3160Ccc09B8D0D3A2cD28aE6C2f; FlashMinter 0xb639D208Bcf0589D54FaC24E655C79EC529762B8; CCIP token pool 0x06179f7C1be40863405f374E7f5F8806c728660A. Source: bgd-labs/aave-address-book main (GhoEthereum.sol, AaveV3Ethereum.sol, GovernanceV3Ethereum.sol)] | — |
| R4 rate | `face_minus_fee(buy fee [FIRST-RUN READ: live value])` | — |
| R5 minimum | `none` [FIRST-RUN READ: live value] | — |
| R6 gates | `capacity_limited` + `pausable` (freezer / swap-freeze roles [VERIFIED 2026-09-01: automatic (Chainlink Automation keeper) + Aave DAO as second freezer; bounds 0.99/1.01 freeze, 0.995/1.005 unfreeze on original instance — see memo §6.3 H2]) | — |
| R7 capacity | GSM boxed-asset balance (data field) | — |
| R8 (computed) | `enforceable_unless_paused` (capacity: see R7) | `n/a` |
| R9 legal claim | `no_pure_protocol` | `no_pure_protocol` |
| R10 provenance | GSM `sellAsset` [VERIFIED 2026-09-01: GSM.sellAsset(amount, receiver); GSM_USDC 0x3A386889…, GSM_USDT 0x882285E6…] | absence of function on GhoToken / facilitator |
 
Note: Path 1 can close (freezer, §6.3 H2) — this is why paths are recorded separately.
 
**Admin-power surface (memo §13)** — every holder, delay, and function [FIRST-RUN READ: live value]:
 
| A1 power | A2 holder | A3 signers | A4 delay (s / bucket) | A5 veto | A6 upgradeability | A7 scope | A8 provenance |
|---|---|---|---|---|---|---|---|
| `mint` | Aave Governance executor [VERIFIED 2026-09-01: GhoToken FACILITATOR_MANAGER_ROLE / BUCKET_MANAGER_ROLE held by Executor Lvl-1 and delegated to GHO stewards (bucket steward 0x46Aa1063…, Aave-core steward 0x98217A06…, GSM steward 0xD1E856a9…) per AIP-61 'Activate GHO Stewards'; exact role holders [FIRST-RUN READ: GhoToken `RoleGranted` / `RoleRevoked` logs as POINTER, `GhoToken.hasRole(role, holder)` at `run_block` as VERDICT (P-4.04 R5)]] | n/a (DAO) | [VERIFIED 2026-09-01: Level 1 = 1 day (86,400s; bucket 1–7d), Level 2 = 7 days (604,800s; bucket 1–7d) — aave.com/security; EXECUTOR_LVL_1 0x5300A1a15135EA4dc7aD5a167152C01EFc9b192A (also ACL_ADMIN), EXECUTOR_LVL_2 0x17Dd33Ed0e3dD2a80E37489B8A63063161BE6957 (bgd-labs/aave-address-book main (GhoEthereum.sol, AaveV3Ethereum.sol, GovernanceV3Ethereum.sol))] | Aave Guardian [VERIFIED 2026-09-01: Governance Guardian 0xCe52ab41C40575B072A18C9700091Ccbe4A06710 can cancel proposals/payloads; 5-of-9, signers disclosed in ARFC addendum (aave.com/help/governance); Granular Guardian 0x4457cA11… — bgd-labs/aave-address-book main (GhoEthereum.sol, AaveV3Ethereum.sol, GovernanceV3Ethereum.sol)] | — | GhoToken facilitator list | GhoToken role reads [FIRST-RUN READ: live value] |
| `set_ceiling` | Governance / role holder of `BUCKET_MANAGER_ROLE` [FIRST-RUN READ: live value]; GSM exposure cap setter [FIRST-RUN READ: live value]; risk steward for reserve caps [FIRST-RUN READ: live value] | | as above / steward: none? [FIRST-RUN READ: live value] | Guardian | — | facilitator buckets; GSM caps; supply/borrow caps | [FIRST-RUN READ: live value] |
| `upgrade` | Aave Governance [VERIFIED 2026-09-01: Aave V3 Pool 0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2 is a proxy administered via PoolAddressesProvider (Executor Lvl-1); GSMs are upgradeable (LlamaRisk cites 'upgradeable token' reviews); GhoToken upgradeability [FIRST-RUN READ: proxy admin slot] — GHO token was redeployed upgradeable per Immunefi scope note (LlamaRisk Mar 2026)] | n/a | executor timelock [FIRST-RUN READ: live value] | Guardian | `proxy_upgradeable(admin = executor)` for Pool/GSM [FIRST-RUN READ: live value]; GhoToken `immutable` [FIRST-RUN READ: live value] | Pool, GSMs | proxy admin reads [FIRST-RUN READ: live value] |
| `pause` | Aave Guardian (emergency pause of Pool / reserves) [VERIFIED 2026-09-01: Protocol Emergency Guardian 5-of-9 holds EMERGENCY_ADMIN (aave.com/help/governance/aave-community)]; GSM `SWAP_FREEZER_ROLE` [VERIFIED 2026-09-01: OracleSwapFreezer contracts (automation) + Aave DAO executor (AIP-8)] | multisig [FIRST-RUN READ: live value] | none (emergency) [FIRST-RUN READ: live value] | — | — | Pool, reserves, GSM swaps | [FIRST-RUN READ: live value] |
| `freeze_asset` | Guardian / risk steward (reserve freeze) [FIRST-RUN READ: live value] | | none [FIRST-RUN READ: live value] | | | reserves | [FIRST-RUN READ: live value] |
| `blacklist_address` | `none` expected on GhoToken [FIRST-RUN READ: live value] | | | | | | |
| `set_oracle` | Aave Governance (AaveOracle source setter) [FIRST-RUN READ: live value]; GSM price strategy setter [FIRST-RUN READ: live value] | n/a | executor timelock [FIRST-RUN READ: live value] | Guardian | — | all reserve feeds; GSM | [FIRST-RUN READ: live value] |
| `set_parameters` | Governance and risk steward (LTV, LT, bonus, caps within steward bounds) [VERIFIED 2026-09-01: Risk stewards / GHO stewards act within governance-set bounds, 1-of-1 multisig per aave.com/help; no timelock (bucket: none)]; GSM fee strategy [FIRST-RUN READ: live value] | | timelock / steward: [FIRST-RUN READ: live value] | Guardian | — | reserves; GSM | [FIRST-RUN READ: live value] |
| `seize` | GSM `LIQUIDATOR_ROLE` — `seize` after freeze [VERIFIED 2026-09-01: GSM seize by LIQUIDATOR_ROLE (DAO); proceeds to GHO treasury per GSM design (docs.gho.xyz) — role holder [FIRST-RUN READ: GSM `RoleGranted` / `RoleRevoked` logs as POINTER, `GSM.hasRole(LIQUIDATOR_ROLE, holder)` at `run_block` as VERDICT (P-4.04 R5)]] | [FIRST-RUN READ: live value] | none [FIRST-RUN READ: live value] | | | GSM boxed assets | [FIRST-RUN READ: live value] |
 
**Qualifier block (memo §13):** expected — `mint` — DAO + timelock, 1–7 d (A4, verified 2026-09-01), veto: Guardian; `upgrade` — DAO + timelock, 1–7 d (A4, verified 2026-09-01), veto: Guardian; `set_oracle` — DAO + timelock, 1–7 d (A4, verified 2026-09-01); `seize` — role (GSM liquidator), none. Final content follows Phase B. Note for §11.11: GSM and facilitator sit under different holders/delays — the first test of whether token-level suffices.
 
**Audit status (memo §14):** audits [VERIFIED 2026-09-01: GSM: SigmaPrime, Certora, independent review by Emanuele Ricci (AIP-8, Jan 2024); GHO token/stewards audits enumerated on Aave Immunefi page (LlamaRisk Mar 2026)]; bug bounty [ANALYST-SUPPLIED 2026-09-01: Curve: bug bounty program stated on docs (platform/max not surfaced); GHO: Immunefi (LlamaRisk Mar 2026); Liquity: active bounty (TokenBrice) — max values first-run analyst entry]; last material change audited [ANALYST-SUPPLIED 2026-09-01: stata-based GSM variant audit not surfaced]. Staleness date: set at Phase B. Never scored.
 
**Counterparty enumeration (memo §14):** n/a — archetype #1 holds no off-chain counterparties. WBTC custodian captured in §4 look-through.
 
**`first_run_reads[]` (DET-75 / R-45)** — registry of every FIRST-RUN READ tag on this sheet's GHO section, resolved to a concrete read. **Count identity: 46 literal tags = 46 open rows.** All reads at `run_block`. Shorthand: **GHO** = 0x40D16FC0246aD3160Ccc09B8D0D3A2cD28aE6C2f · **GSMREG** = 0x167527DB01325408696326e3580cd8e55D99Dc1A · **POOL_C / POOL_L / POOL_H** = 0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2 (Core) / 0x4e033931ad43597d96d6bcc25c280717730b58b1 (Lido-Prime) / 0xae05cd22df81871bc7cc2a04becfb516bfe332c8 (Horizon) · **PDP_C** = 0x0a16f2fcc0d44fae41cc54e079281d84a363becd · **AP_C** = 0x2f39d218133AFaB8F2B819B1066c7E434Ad94E9e. `sheet_location` is a section anchor rather than a line number, so the registry survives later edits.
 
| tag_id | sheet_location | bundle_field_path | read_spec | status |
|---|---|---|---|---|
| FR-G01 | GHO § Contracts to read | `facilitators[]` | `GHO.getFacilitatorsList()`; per entry `GHO.getFacilitator(a)` -> `(bucketCapacity, bucketLevel, label)` | open |
| FR-G02 | GHO § Collateral nodes — header | `nodes[].attributed_weight` | pro-rata per position (memo §11.1, Route A): borrower set from the GHO variable-debt token's mint-side `Transfer` logs per instance (Etherscan v2 `logs/getLogs` as POINTER); per borrower `Pool.getUserConfiguration(u)` bitmap, then `aToken.balanceOf(u)` per set collateral bit and `variableDebtToken.balanceOf(u)` per set borrow bit, all at `run_block` (VERDICT); weight = collateral × (GHO debt ÷ total debt) | open |
| FR-G03 | GHO § Collateral nodes — aDAI/aUSDS/asDAI | `nodes[DAI,USDS,sDAI].attributed_weight` | as FR-G02, restricted to those reserve addresses | open |
| FR-G04 | GHO § Collateral nodes — aweETH / LRTs | `nodes[weETH,…].attributed_weight` | as FR-G02, restricted to the LRT reserve addresses | open |
| FR-G05 | GHO § Collateral nodes — acbETH | `nodes[cbETH].attributed_weight` | as FR-G02, restricted to the cbETH reserve address | open |
| FR-G06 | GHO § Token-specific mechanisms — GSM | `gsms[].{sell_fee, price_strategy, exposure_cap, is_frozen, is_seized}` | per GSM: `getFeeStrategy()`, `PRICE_STRATEGY()`, `getExposureCap()`, `getIsFrozen()`, `getIsSeized()` | open |
| FR-G07 | GHO § Pool set | `discovered_pools[]`, `frozen_set` | Curve API catalog as POINTER per registry class, `pool.balances(i)` at par on-chain as VERDICT (the P-3.28 pattern); GHO/crvUSD routes to the analyzed-token rule (memo §4.1) | open |
| FR-G08 | GHO § Pool set — off-venue | `offvenue_share` | DET-32 `X = 1 − curve/total` over the disclosed Ethereum DEX venue set; Curve-only modeling in Step 4 (P-4.04 R4) | open |
| FR-G09 | GHO § Pool set — bridged | `supply.bridges[]` | `GHO.balanceOf(ccip_pool)` — **amount only**; `bridge_type` from the DET-33 menu, never inferred from a balance (C-1) | open |
| FR-G10 | GHO § Stress hooks — H5 | `nodes[].liquidation_params` | `PoolDataProvider.getReserveConfigurationData(asset)` per reserve, per instance | open |
| FR-G11 | GHO § Stress hooks — facilitator caps | `facilitators[].{bucket_capacity, bucket_level}` | `GHO.getFacilitatorBucket(a)` over every facilitator | open |
| FR-G12 | GHO § Quarantine instances (d) | `near_bound[]` | `GSM.getExposureCap()` vs `GSM.getAvailableUnderlyingExposure()`; `GHO.getFacilitatorBucket(a)` level ÷ capacity | open |
| FR-G13 | GHO § Oracle sources | `oracle_rows[].heartbeat_s` | heartbeat is not on-chain state — dated per-feed analyst value in the DET-04 form (data.chain.link) | open |
| FR-G14 | GHO § Redemption-rights R4 | `redemption_paths[i].r4_rate` | `GSM.getFeeStrategy()` -> strategy `getBuyFee(amount)` | open |
| FR-G15 | GHO § Redemption-rights R5 | `redemption_paths[i].r5_minimum` | `GSM.getFeeStrategy()`; minimum absent => `none`, recorded as an absence read | open |
| FR-G16 | GHO § Admin-power surface — header | `admin_surface[]` | the nine A1 rows below, every read at `run_block` | open |
| FR-G17 | GHO § Admin surface — `mint` A2 | `admin_surface[mint].holder` | GhoToken `RoleGranted` / `RoleRevoked` logs as POINTER (Etherscan v2 `logs/getLogs`), `GHO.hasRole(FACILITATOR_MANAGER_ROLE / BUCKET_MANAGER_ROLE, holder)` at `run_block` as VERDICT (P-4.04 R5) | open |
| FR-G18 | GHO § Admin surface — `mint` A8 | `admin_surface[mint].reads` | provenance of the FR-G17 reads | open |
| FR-G19 | GHO § Admin surface — `set_ceiling` A2 (bucket) | `admin_surface[set_ceiling].holder` | as FR-G17, `BUCKET_MANAGER_ROLE` | open |
| FR-G20 | GHO § Admin surface — `set_ceiling` A2 (GSM cap) | `admin_surface[set_ceiling].holder_gsm` | as FR-G17 against each GSM, `CONFIGURATOR_ROLE` | open |
| FR-G21 | GHO § Admin surface — `set_ceiling` A2 (risk steward) | `admin_surface[set_ceiling].holder_steward` | `PoolAddressesProvider.getACLManager()` -> ACLManager `RoleGranted` logs as pointer, `hasRole(RISK_ADMIN, holder)` at `run_block` as verdict | open |
| FR-G22 | GHO § Admin surface — `set_ceiling` A4 | `admin_surface[set_ceiling].delay_s` | executor `getDelay()`; steward path carries `none` | open |
| FR-G23 | GHO § Admin surface — `set_ceiling` A8 | `admin_surface[set_ceiling].reads` | provenance of the FR-G19…FR-G21 reads | open |
| FR-G24 | GHO § Admin surface — `upgrade` A2 | `admin_surface[upgrade].holder` | EIP-1967 admin slot on GhoToken, each Pool and each GSM (F4 absence shape where zero) | open |
| FR-G25 | GHO § Admin surface — `upgrade` A4 | `admin_surface[upgrade].delay_s` | executor `getDelay()` | open |
| FR-G26 | GHO § Admin surface — `upgrade` A6 (Pool/GSM) | `admin_surface[upgrade].upgradeability` | EIP-1967 implementation slot on the three Pools and both GSMs | open |
| FR-G27 | GHO § Admin surface — `upgrade` A6 (GhoToken) | `admin_surface[upgrade].upgradeability_token` | EIP-1967 implementation slot on GhoToken; all-zero => `immutable`, recorded as an absence read | open |
| FR-G28 | GHO § Admin surface — `upgrade` A8 | `admin_surface[upgrade].reads` | provenance of the FR-G24…FR-G27 reads | open |
| FR-G29 | GHO § Admin surface — `pause` A3 | `admin_surface[pause].signers` | Guardian Safe `getThreshold()` / `getOwners()` | open |
| FR-G30 | GHO § Admin surface — `pause` A4 | `admin_surface[pause].delay_s` | emergency path => `0`, recorded as an absence read | open |
| FR-G31 | GHO § Admin surface — `pause` A8 | `admin_surface[pause].reads` | provenance of the FR-G29…FR-G30 reads | open |
| FR-G32 | GHO § Admin surface — `freeze_asset` A2 | `admin_surface[freeze_asset].holder` | ACLManager `RoleGranted` logs as pointer, `hasRole(POOL_ADMIN / EMERGENCY_ADMIN / RISK_ADMIN, holder)` at `run_block` as verdict | open |
| FR-G33 | GHO § Admin surface — `freeze_asset` A4 | `admin_surface[freeze_asset].delay_s` | `none`, recorded as an absence read | open |
| FR-G34 | GHO § Admin surface — `freeze_asset` A8 | `admin_surface[freeze_asset].reads` | provenance of the FR-G32 reads | open |
| FR-G35 | GHO § Admin surface — `blacklist_address` A2 | `admin_surface[blacklist_address].holder` | selector-absence scan over `eth_getCode(GHO)` (F4 shape) | open |
| FR-G36 | GHO § Admin surface — `set_oracle` A2 (Aave) | `admin_surface[set_oracle].holder` | `PoolAddressesProvider.getPriceOracle()`; ACLManager `hasRole(ASSET_LISTING_ADMIN / POOL_ADMIN, holder)` by FR-G21's route | open |
| FR-G37 | GHO § Admin surface — `set_oracle` A2 (GSM) | `admin_surface[set_oracle].holder_gsm` | as FR-G20, `CONFIGURATOR_ROLE` (GSM price-strategy setter) | open |
| FR-G38 | GHO § Admin surface — `set_oracle` A4 | `admin_surface[set_oracle].delay_s` | executor `getDelay()` | open |
| FR-G39 | GHO § Admin surface — `set_oracle` A8 | `admin_surface[set_oracle].reads` | provenance of the FR-G36…FR-G37 reads | open |
| FR-G40 | GHO § Admin surface — `set_parameters` A2 | `admin_surface[set_parameters].holder` | `GSM.getFeeStrategy()`; ACLManager steward roles by FR-G21's route | open |
| FR-G41 | GHO § Admin surface — `set_parameters` A4 | `admin_surface[set_parameters].delay_s` | executor `getDelay()`; steward path carries `none` | open |
| FR-G42 | GHO § Admin surface — `set_parameters` A8 | `admin_surface[set_parameters].reads` | provenance of the FR-G40 reads | open |
| FR-G43 | GHO § Admin surface — `seize` A2 | `admin_surface[seize].holder` | GSM `RoleGranted` / `RoleRevoked` logs as POINTER, `GSM.hasRole(LIQUIDATOR_ROLE, holder)` at `run_block` as VERDICT (P-4.04 R5) | open |
| FR-G44 | GHO § Admin surface — `seize` A3 | `admin_surface[seize].signers` | holder Safe `getThreshold()` / `getOwners()` | open |
| FR-G45 | GHO § Admin surface — `seize` A4 | `admin_surface[seize].delay_s` | `none`, recorded as an absence read | open |
| FR-G46 | GHO § Admin surface — `seize` A8 | `admin_surface[seize].reads` | provenance of the FR-G43 reads | open |
 
---
 
## LUSD
 
**Archetype assignment:** #1, CDP / on-chain-backed — **simplicity control**. Fit test: supply originates from troves minting against ETH with a liquidation path — passes. If the common schema is awkward for LUSD, the schema is wrong.
 
**Contracts to read** [FIRST-RUN READ: addresses per Liquity deployment registry]: TroveManager, ActivePool, DefaultPool, StabilityPool, CollSurplusPool, PriceFeed, LUSD token. Liquity v1 is immutable — no factory; the "discovery" input is a single analyst-supplied, staleness-tracked address set (permitted by memo §9 because the protocol has no registry and cannot change).
 
[VERIFIED 2026-09-01: BOLD launched 2025-01-23 as a separate immutable protocol/token; v1 unaffected — Curve gov proposal 2025-01-24; TokenBrice]
 
**Collateral nodes currently held:**
 
| Node | Memo §4.5 row | Label |
|---|---|---|
| ETH (native, in ActivePool + DefaultPool) | ETH | `terminal` |
 
Expected verifiability result: 100% `terminal`. Any second node is an unlisted node → quarantine (would indicate an adapter bug, since v1 accepts ETH only).
 
**Token-specific mechanisms:**
- *User-facing instant redemptions* — any holder may redeem LUSD for ETH at face value (minus a dynamic fee) against the riskiest troves. This is a third-party claim on collateral enforceable on-chain with no gate and no notice period: it is the strongest redemption-rights profile in the pilot set and the reference point for the redemption-rights fields (agenda item 6).
- *Stability Pool* — LUSD deposited by users to absorb liquidations. It is **not** backing (it is a liability being extinguished) and **not** exit liquidity (it is not a market). Recorded as a liquidation-capacity parameter for the stress model (agenda item 4).
- *Recovery Mode* — system-wide TCR threshold changing liquidation rules [VERIFIED 2026-09-01: CCR = 150% — LiquityBase.sol (immutable)]; stress-model parameter.
**Pool set (exit liquidity):** Rule: memo §5. Frozen set established at first run; §5.4 exclusions apply (Stability Pool excluded — liquidation capacity, not a market; LUSD/ETH-type pools excluded as circular). Expected pools [FIRST-RUN READ: discovery; LUSD supply ≈ $27M (CoinGecko 2026) — LUSD/3CRV and LUSD/crvUSD active (Curve gov Jan 2025); floor check likely borderline]. 3CRV as paired asset → composite pass-through to DAI/USDC/USDT at basepool composition (memo §4.3) [VERIFIED 2026-09-01: 3pool balances(i) direct read]. **Floor check (memo §5.5):** if the $500k floor leaves LUSD with fewer than 2 modeled pools, flag at Phase B (checklist 4.9) — the rule-form parameters would then need re-ruling for the simplicity control, which is exactly the "schema awkward for LUSD → schema is wrong" test. Off-venue share disclosed per §5.1 [FIRST-RUN READ: discovery]. Bridged/L2 supply expected negligible [FIRST-RUN READ: live value].
 
**Stress hooks (memo §6.3):**
- H3 capacity = Stability Pool balance only; redistribution tail and Recovery Mode flag under metric 4; bad debt = redistributed positions < 100% CR. [VERIFIED 2026-09-01: CCR 150%, MCR 110%, gas comp 200 LUSD + 0.5% — liquity/dev main — PriceFeed.sol, TroveManager.sol, LiquityBase.sol]
- SP depositor flight tied to the LP-flight axis — a cell's haircut applies to pool LPs and SP depositors simultaneously (memo §6.3 H3); no new cells, 23 per run.
- H4 redemption arbitrage — Member 2 only: capacity = LUSD redeemable before the dynamic fee exceeds 2% [VERIFIED 2026-09-01: BETA=2; decay 0.999037758833783/min (12h half-life); floor 0.5%; cap = must be < redeemed amount — TroveManager.sol]. Crash-path effect excluded (conservative; noted in memo).
- Member 2 — no boxed asset, no stabilizer pool; only §5 pool set paired stables affected.
- Volatile node for Member 1: ETH only; LST axis does not apply. Cells: 23.

**Metric-4 field set (DET-38; `m4_fields[]`)** — the PER-TOKEN UNION: every cell carries every key, and a key not applicable to a cell's member carries `0` with a `reason` literal naming it (e.g. `reason = "not applicable — Member 1"`), the form DET-51 already uses for `redemption_capacity` on the crash path.

LUSD (9): sp_effective_cell, redistributed_debt, redistributed_positions_below_100, tcr_post, recovery_mode_flag, redemption_capacity, exit_depth_cell, lp_flight_share, counterfactual_ref.

NAMED DEFAULTS (implementer, not rubric): `pegkeeper_lp_share`, `paired_units_held` and `pool_tilt_post_cell` are the Builder's names for the three quantities DET-27 describes in prose without naming — "metric 4 prints quantities only (LP share, paired-asset units held, pool tilt post-cell)". Every other key is the rubric's own identifier. `sp_balance_read` is a lineage key (DET-51 Member-1 capacity), not an `m4` key, and is deliberately absent.

**stock-only capacity — direction of error per mechanism** (DET-53; `bias_table[]`, Appendix C seed)

| Mechanism | Token | Direction | Reason |
|---|---|---|---|
| Collateral-sell-side bound ★ | crvUSD, GHO | overstates | full bound treated as immediately absorbable |
| GSM cap headroom (H2.i) ★ | GHO | overstates | full cap headroom treated as instantly mintable |
| Liquidator recycling (H5) ★ | GHO | understates | no multi-round capital recycling |
| Stability Pool refills (H3) ★ | LUSD | understates | no SP deposits between liquidation waves |
| PegKeeper effective headroom (H1) | crvUSD | overstates | full effective headroom treated as deployed within the window; peer co-deployment dynamics omitted — runs conservative |
| H4 redemption capacity | LUSD | overstates | full schedule capacity treated as immediately available; base-rate decay (regenerative, 12h half-life) omitted — runs conservative |
| H5 liquidator appetite (composite) | GHO | both | two named opposite-sign terms; DET-47 `binding_side` states per cell which dominates |
| Pool exit depth — no LP inflow | all | understates | no LP inflow modeled |
| Pool exit depth — LP sticky at flight-0 | all | overstates | static composition; spread disclosed by the LP-flight grid |

★ = mandatory literal (DET-53).

**Collateral-sell-side capacity (memo §6.3; DET-52)** — LUSD is exempt.

| Tag | Address | Value | Source | Date |
|---|---|---|---|---|
| SS-ETH | 0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee | exempt — Stability Pool depositors receive collateral; no forced sale | memo §6.3 sell-side bound; DET-52 | 2026-09-12 |
- Member 2 target stable: set at first freeze (not a Phase B item) — expected USDC via the 3CRV composite. [ANALYST-SUPPLIED 2026-09-12: the computed target is **USDT** 0xdac17f958d2ee523a2206206994597c13d831ec7 at 52.16% of exit depth at s = 2%, against USDC's 23.26% and DAI's 24.58%, from the 3pool composition read at 25955393 (P-6.04 C4). The "expected USDC" reading predates the depth solver; the fill is computed, never assumed (P-6.01 R7).] Forced-sell numerator zero by construction → structural-insulation finding; Member 2 told via exit-depth curve (H4 redemption capacity is the notable line). Joint cell checks the `state_conditional` gate (H4 capacity zero if TCR < MCR).
**Quarantine instances (memo §8.1):**
- (c) Market-count: immutable protocol; any change in the contract set or collateral count → L3 (adapter bug by definition).
- (d) Mechanism near bound → L1: TCR within 10pp of the Recovery Mode threshold, i.e., TCR < 160% given the 150% threshold [VERIFIED 2026-09-01: CCR = 150% — LiquityBase.sol]. Mirrored in the monitoring brief.
- (a): composition shift cannot fire (single node); (b) supply jump: archetype default, two-branch.
**Oracle sources (memo §7):** LUSD PriceFeed — Chainlink ETH/USD primary, Tellor fallback [VERIFIED 2026-09-01: logic per memo §7.3 (4h timeout, 50% deviation, 5% reconciliation); PriceFeed address [FIRST-RUN READ: TroveManager.priceFeed()]; Chainlink ETH/USD 0.5% deviation (data.chain.link). Counterfactual line retained. Source: liquity/dev main — PriceFeed.sol, TroveManager.sol, LiquityBase.sol]. §7 assumption: instant observation, nearly exact; one fallback-engaged counterfactual line under metric 4.
 
**Redemption-rights (memo §12) — holder paths: 1 — the reference profile**
 
| Field | Path 1 — trove redemption |
|---|---|
| R1 path | `direct_on_chain` |
| R2 who | `anyone` |
| R3 received | ETH (native; from lowest-CR troves) |
| R4 rate | `face_minus_fee(base rate + 0.5% floor [VERIFIED 2026-09-01: floor 0.5%; effective cap: fee must be < amount redeemed (revert otherwise) — TroveManager.sol])` |
| R5 minimum | `none` [VERIFIED 2026-09-01: no minimum; partial redemption of the last trove is skipped if it would leave net debt < MIN_NET_DEBT (1800 LUSD) — TroveManager.sol] |
| R6 gates | `state_conditional(TCR < MCR)` — redemptions disabled when TCR < MCR (110%) [VERIFIED 2026-09-01: _requireTCRoverMCR: redemptions revert when TCR < MCR = 110% — TroveManager.sol] |
| R7 capacity | ActivePool + DefaultPool ETH at oracle price (redeemable collateral) |
| R8 (computed) | `enforceable_unless_[TCR<MCR]` |
| R9 legal claim | `no_pure_protocol` |
| R10 provenance | TroveManager `redeemCollateral` [FIRST-RUN READ: TroveManager address from Liquity deployment registry] |
 
**Admin-power surface (memo §13) — expected EMPTY (control case)** [VERIFIED 2026-09-01: v1 immutable: setAddresses renounces ownership (PriceFeed.sol _renounceOwnership); no proxies, no pause — liquity/dev main — PriceFeed.sol, TroveManager.sol, LiquityBase.sol; independently stated by TokenBrice audit summary]:
 
| A1 power | A2 holder | A3 | A4 | A5 | A6 | A7 | A8 |
|---|---|---|---|---|---|---|---|
| `mint` | `none` [FIRST-RUN READ: live value] | — | — | — | `immutable` [FIRST-RUN READ: live value] | — | absence of admin functions; bytecode [FIRST-RUN READ: live value] |
| `set_ceiling` | `none` | — | — | — | — | — | — |
| `upgrade` | `none` [FIRST-RUN READ: live value] | — | — | — | `immutable` | — | — |
| `pause` | `none` [FIRST-RUN READ: live value] | — | — | — | — | — | — |
| `freeze_asset` | `none` | — | — | — | — | — | — |
| `blacklist_address` | `none` | — | — | — | — | — | — |
| `set_oracle` | `none` [VERIFIED 2026-09-01: fixed in setAddresses then ownership renounced; status machine autonomous — PriceFeed.sol] | — | — | — | — | — | — |
| `set_parameters` | `none` | — | — | — | — | — | — |
| `seize` | `none` | — | — | — | — | — | — |
 
**Qualifier block (memo §13):** *"No admin power can alter backing — immutable."* [FIRST-RUN READ: live value]. Contrast (memo §7.3): no admin keys, but an automated on-chain oracle fallback.
 
**Audit status (memo §14):** audits [VERIFIED 2026-09-01: Trail of Bits (with invariants), Coinspect (2021-03) — coinspect.com; TokenBrice summary]; bug bounty [ANALYST-SUPPLIED 2026-09-01: Curve: bug bounty program stated on docs (platform/max not surfaced); GHO: Immunefi (LlamaRisk Mar 2026); Liquity: active bounty (TokenBrice) — max values first-run analyst entry]; last material change audited: n/a — immutable, no changes since deployment [FIRST-RUN READ: live value]. Staleness date: set at Phase B. Never scored.
 
**Counterparty enumeration (memo §14):** n/a — archetype #1 holds no off-chain counterparties.
 
**`first_run_reads[]` (DET-75 / R-45)** — registry of every FIRST-RUN READ tag on this sheet's LUSD section, resolved to a concrete read. **Count identity: 13 literal tags = 13 open rows.** All reads at `run_block`. Liquity v1 has no factory and no registry: the set is reached by CONTRACT CLOSURE from one analyst-supplied anchor, the LUSD token itself, every other address being a getter on a contract already in the set (memo §9's analyst-supplied branch). Shorthand: **LUSD** = 0x5f98805A4E8be255a32880FDeC7F6728C6568bA0 · **TM** = TroveManager, from `LUSD.troveManagerAddress()` · **AP / DP / SP / PF / ST** = `TM.activePool()` / `TM.defaultPool()` / `TM.stabilityPool()` / `TM.priceFeed()` / `TM.sortedTroves()` · **CSP** = CollSurplusPool, reached in REVERSE — `collSurplusPool` is non-public on both TroveManager and BorrowerOperations, so CSP's own `troveManagerAddress()`, `activePoolAddress()` and `borrowerOperationsAddress()` are its closure evidence. `sheet_location` is a section anchor rather than a line number, so the registry survives later edits.
 
| tag_id | sheet_location | bundle_field_path | read_spec | status |
|---|---|---|---|---|
| FR-L01 | LUSD § Contracts to read | `markets[0].address` plus `config/lusd_roots.toml` | anchor `LUSD` analyst-supplied and dated; `LUSD.troveManagerAddress()`, then `TM.activePool()`, `TM.defaultPool()`, `TM.stabilityPool()`, `TM.priceFeed()`, `TM.sortedTroves()` and `TM.lusdToken()` closing back on the anchor; CSP by reverse closure | open |
| FR-L02 | LUSD § Pool set | `pools[]`, `frozen_set` | Curve API catalog as POINTER per declared registry class, `pool.balances(i)` at par on-chain as VERDICT (the P-3.28 pattern); 3CRV routes to the composite pass-through (memo §4.3), crvUSD to the analyzed-token rule (memo §4.1) | open |
| FR-L03 | LUSD § Pool set — off-venue | `offvenue_share` | DET-32 `X = 1 − curve/total` over the disclosed Ethereum DEX venue set; Curve-only modeling in Step 4 (P-4.04 R4), so present-and-empty | open |
| FR-L04 | LUSD § Pool set — bridged | `supply.bridges[]` | `LUSD.balanceOf(escrow)` per SIGNED bridge row — amount only; `bridge_type` from the DET-33 menu, never inferred from a balance (C-1) | open |
| FR-L05 | LUSD § Oracle sources | `oracle_rows[0].feed_or_source` | `TM.priceFeed()`, then `PF.priceAggregator()`, `PF.tellorCaller()`, `PF.status()` and `PF.lastGoodPrice()`; the aggregator's `latestRoundData()` and `decimals()`; the price itself from a `PF.fetchPrice()` eth_call simulation at `run_block` (P-4.13 R4) | open |
| FR-L06 | LUSD § Redemption-rights R10 | `redemption_paths[0].r10_provenance` | TroveManager address by FR-L01's closure; `redeemCollateral` selector present in `eth_getCode(TM)` | open |
| FR-L07 | LUSD § Admin surface — `mint` A2 | `admin_surface[mint].holder` | the only minter is the immutable `LUSD.borrowerOperationsAddress()`; holder `none` evidenced by a selector-absence scan over `eth_getCode(LUSD)` for any setter or role-grant function (F4 shape) | open |
| FR-L08 | LUSD § Admin surface — `mint` A6 | `admin_surface[mint].upgradeability` | EIP-1967 implementation slot on LUSD; all-zero => `immutable`, recorded as an absence read | open |
| FR-L09 | LUSD § Admin surface — `mint` A8 | `admin_surface[mint].reads` | provenance of the FR-L07 and FR-L08 reads | open |
| FR-L10 | LUSD § Admin surface — `upgrade` A2 | `admin_surface[upgrade].holder` | EIP-1967 admin slot on each of the seven contracts; all-zero => `none`, recorded as absence reads | open |
| FR-L11 | LUSD § Admin surface — `pause` A2 | `admin_surface[pause].holder` | selector-absence scan over `eth_getCode` of the seven for `pause`, `unpause` and `setPaused`; ownership renounced, evidenced by a storage-slot read of the owner slot returning zero | open |
| FR-L12 | LUSD § Qualifier block | `admin_surface[].holder_type` all `none` | the nine A1 rows jointly; the qualifier is asserted only if every row's holder is `none` under FR-L07 to FR-L11's absence evidence | open |
| FR-L13 | LUSD § Audit status | `static_metadata.last_material_change_audited` | `no` by construction — no code change is possible; evidenced by FR-L08's and FR-L10's zero slots rather than asserted | open |