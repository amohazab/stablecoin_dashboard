# Token Intake Sheets — Archetype #1 (CDP / On-Chain-Backed)
 
**Phase A CLOSED — 2026-09-01.** Design complete; implementer test passed.
**Phase B COMPLETE — 2026-09-02.** 18 analyst-supplied values with staleness dates (FIX 2026-09-02: header previously read 19; one entry — frxUSD keeper paired-asset labeling — was re-scoped to intake under P4 after the count was taken); 2 contradictions resolved by ruling (H1, H2); 6 candidate points dispositioned. Design verified; code pending.
**Conventions:** `[VERIFIED <date>: …]` = fact verified in Phase B, source inline. `[FIRST-RUN READ: …]` = live-state quantity read per run by the adapter — an input, not an assumption. `[ANALYST-SUPPLIED <date>: …]` = staleness-tracked analyst input per the graceful-degradation rule. `[RE-SCOPED TO INTAKE: …]` = resolved at intake/freeze time. Mechanism logic carries no marker. Rulings are the analyst's; the memo records them once and code enforces them per run. Each sheet instantiates memo #1 rulings; it never restates or overrides them.
 
---
 
## crvUSD
 
**Archetype assignment:** #1, CDP / on-chain-backed. Fit test: supply originates from LLAMMA controllers minting against pledged collateral with a soft-liquidation path — passes.
 
**Contracts to read** [FIRST-RUN READ: TroveManager address from Liquity deployment registry]:
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
| tBTC | tBTC | deferred (§4.4) |
| cbBTC (largest mint-market borrow flow, Curve News wk32 2026) | cbBTC / custodial BTC | `recurses` (Coinbase custody attestation) [RE-SCOPED TO INTAKE: attestation cadence] |
| weETH | LRT family | `terminal_other_layer` |
| Any other mint-market collateral | — | unlisted → §8.2 quarantine rule |
 
Expected verifiability result (Step-5 done-condition): majority `terminal` / `terminal_other_layer`, with WBTC **and cbBTC** as the `recurses` slices (cbBTC is currently the largest mint market — the crvUSD split is no longer trivially ~100% verifiable; "boring, correct" now reads as a defensible custodial-BTC share).
 
**Token-specific mechanism: PegKeepers** (memo §3 instance)
 
- Classification: protocol stabilizer debt, zero-credited. Class rule applies unmodified.
- Discovery: active PegKeeper set read from the PegKeeper regulator / registry contract, never hardcoded [VERIFIED 2026-09-01: regulator 0x36a04CAffc681fa179558B2Aaba30395CDdd855f exposes peg_keepers (DynArray of PegKeeperInfo) — discovery source confirmed. Source: PegKeeperRegulator.vy (curvefi/curve-stablecoin master) + verified deploy 0x36a04CAffc681fa179558B2Aaba30395CDdd855f (Etherscan)].
- Version: [VERIFIED 2026-09-01: all four docs-listed keepers are V2 under the regulator: USDC 0x9201da0D97CaAAff53f01B2fB56767C7072dE340, USDT 0xFb726F57d251aB5C731E5C64eD4F5F94351eF9F3, pyUSD 0x3fA20eAa107DE08B38a8734063D605d5842fe09C, frxUSD 0x338Cb2D827112d989A861cDe87CD9FfD913A1f9D. Source: docs.curve.finance static/deployments.json (snapshot 2026-08-21)].
- Instances [FIRST-RUN READ: TroveManager address from Liquity deployment registry]:
  - crvUSD/USDC keeper — pool [FIRST-RUN READ: live value]; ceiling [ANALYST-SUPPLIED 2026-09-01: USDC ceiling not web-resolvable (history: 25M 2024 → 45M by Aug 2025 → raised Oct 2025 vote, ×3 claimed); [FIRST-RUN READ: debt_ceiling]]
  - crvUSD/USDT keeper — pool [FIRST-RUN READ: live value]; ceiling [VERIFIED 2026-09-01: USDT ceiling $135M — Curve News July 2026 recap]
  - crvUSD/pyUSD keeper — [VERIFIED 2026-09-01: pyUSD keeper active (docs deployments 2026-08-21); ceiling history 15M→5M (Sept 2024)→15M (Aug 2025) → current [FIRST-RUN READ: debt_ceiling]]
  - Other keepers added since 2025 — [FIRST-RUN READ: live value]
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
 
**Pool set (exit liquidity):** Rule: memo §5. Frozen set established at first run by three-way discovery; §5.4 exclusions apply (crvUSD/wstETH, crvUSD/WETH-type pools excluded as circular; PegKeeper pools included in full). Expected pools [FIRST-RUN READ: discovery; expected incl. PegKeeper pools USDC/USDT/pyUSD/frxUSD (frxUSD needs §4 row)], crvUSD/USDe or other synthetic pairs [RE-SCOPED TO INTAKE: frxUSD and any other keeper paired asset gets its §4 row at freeze; unlabeled → §8.2 (memo §9 stabilizer instance, P4)], any tricrypto-style pools (paired with volatile assets)]. Off-venue share and bridged/L2 supply disclosed per §5.1–5.2 [FIRST-RUN READ: bridge contract balances; lock-vs-burn per bridge].
 
**Stress hooks (memo §6.3):**
- H1 crash path — **state-conditional capacity (memo §6.3 H1, ruled 2026-09-02).** Per keeper, per run: (1) regulator `is_killed` Provide flag → killed keeper contributes zero; (2) read α, β (`regulator.alpha()`, `regulator.beta()`), each keeper's `debt()` and crvUSD balance; deployable = (α + β·Σ√r_others)² × (debt + balance) − debt. Capacity = Σ over live keepers. **Metric 4 prints both:** effective deployable headroom vs. naive ceiling − debt. Counterfactual: discretionary kill mid-crash → zero. Verified 2026-09-01: regulator 0x36a04CAffc681fa179558B2Aaba30395CDdd855f, deployed α = 0.5, β = 0.25 (source + Etherscan); USDT ceiling $135M (Curve News July 2026); other ceilings `ControllerFactory.debt_ceiling(pk)` per run.
- H1 depeg path (Member 2) — primary: V2 gating effective, no new mint, LP share stuck in depegging asset (metric 4). Counterfactual: V1 contagion mint sized by headroom. [VERIFIED 2026-09-01: see memo §6.3 H1 — four-condition block incl. cross-pool worst_price_threshold 0.03%; discretionary kill switch exists (admin or Emergency DAO). Source: PegKeeperRegulator.vy (curvefi/curve-stablecoin master) + verified deploy 0x36a04CAffc681fa179558B2Aaba30395CDdd855f (Etherscan)]
- LLAMMA band depth + arbitrage appetite as primary capacity [FIRST-RUN READ: AMM.A(), Controller.n (per loan), AMM.bands_x/bands_y]. Arbitrage sell-side bounded by the §6.3 collateral-sell-side parameter per node.
- Volatile nodes for Member 1: WETH, wstETH, sfrxETH (LST axis applies), WBTC, tBTC. Cells: 47.
- Member 2 target stable: set at pool-set freeze (memo §6.2.5) — expected USDC or USDT (set at first freeze; not a Phase B item). Forced-sell numerator zero by construction → structural-insulation finding; Member 2 told via exit-depth curve + metric 4 (PegKeeper LP share).
**Quarantine instances (memo §8.1):**
- (c) Market-count: mint-market count from the controller factory. Addition with known node → L1; removal → L2. Lend-market count changes are logged but do not trigger (excluded by the supply-origination gate).
- (d) Mechanism near bound → L1: any PegKeeper debt > 80% of its ceiling, or aggregate PegKeeper debt > 80% of aggregate ceiling [ANALYST-SUPPLIED 2026-09-01: USDT $135M (Curve News July 2026); others first-run read]. Mirrored in the monitoring brief.
- (a), (b): archetype defaults (10pp / 25% two-branch).
**Oracle sources (memo §7):** per-market price oracle contracts [FIRST-RUN READ: AMM.price_oracle_contract() per market], crvUSD price aggregator [VERIFIED 2026-09-01: AggregateStablePrice v3 0x18672b1b0c623a30089A280Ed9256379fb0E4E62; composition [FIRST-RUN READ: price_pairs()]; frxUSD pool oracle added Aug 2025 (Curve News)], LLAMMA EMA smoothing [VERIFIED 2026-09-01: crvUSD market oracles are CryptoWithStablePrice*/CryptoFromPool* contracts with MA_EXP_TIME as an immutable constructor argument (bounds 30s–365d), read per market via the oracle's MA_EXP_TIME()/ma_exp_time getter. Values are per deployment — [FIRST-RUN READ: Controller.amm().price_oracle_contract() → MA_EXP_TIME]. Aggregator: AggregateStablePrice v3 0x18672b1b0c623a30089A280Ed9256379fb0E4E62 (TVL_MA_TIME 50000s), legacy 0xe5Afcf332a5457E8FafCD668BcE3dF953762Dfe7. Source: curvefi/curve-stablecoin price_oracles/*.vy; docs.curve.finance static/deployments.json (snapshot 2026-08-21)]. §7 assumption: instant observation primary, knowingly optimistic for LLAMMA; EMA counterfactual line under metric 4 (bounded approximation, labeled).
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
 
**Qualifier block (memo §13):** expected — `mint` — DAO, [bucket VERIFY], veto: Emergency DAO; `set_oracle` — DAO, [bucket VERIFY]; `upgrade` — none (immutable); `seize` — none. Final content follows Phase B.
 
**Audit status (memo §14):** audits [VERIFIED 2026-09-01: crvUSD infrastructure: MixBytes 2023-06-05, ChainSecurity 2024-01-24, ChainSecurity 2025-02-21; PegKeeperV2: ChainSecurity 2023-12-12; FastBridge (cross-chain crvUSD): ChainSecurity 2024-10-25; LlamaLend: MixBytes 2024 — docs.curve.finance/developer/security]; bug bounty [ANALYST-SUPPLIED 2026-09-01: Curve: bug bounty program stated on docs (platform/max not surfaced); GHO: Immunefi (LlamaRisk Mar 2026); Liquity: active bounty (TokenBrice) — max values first-run analyst entry]; last material change audited [ANALYST-SUPPLIED 2026-09-01: LlamaLend V2 audit status not surfaced — analyst entry]. Staleness date: set at Phase B. Never scored.
 
**Counterparty enumeration (memo §14):** n/a — archetype #1 holds no off-chain counterparties. WBTC custodian captured in §4 look-through.
 
---
 
## GHO
 
**Archetype assignment:** #1, CDP / on-chain-backed — with two facilitator sub-mechanisms. Fit test: primary supply originates from the Aave V3 facilitator minting against pledged collateral with a liquidation path — passes. GSM supply is asset-in-a-box (memo §3 exclusion), backed by the boxed asset via look-through.
 
**Contracts to read** [FIRST-RUN READ: addresses per Liquity deployment registry]:
- GHO token; GhoToken facilitator registry — facilitator discovery (list, bucket caps, current levels); hardcoded lists forbidden.
- Aave V3 Ethereum Pool, PoolDataProvider — per-reserve and per-position reads.
- GSM contracts per boxed asset [VERIFIED 2026-09-01: USDC and USDT GSMs live (addresses above); a GHO_DIRECT_FACILITATOR_MAINNET_GSMS 0xE9ac5231… exists (address book) — facilitator list [FIRST-RUN READ: GhoToken.getFacilitatorsList()]].
- **Per-run H2 reads (memo §6.3 H2):** per GSM — `getRoleMember(SWAP_FREEZER_ROLE, i)` on the GSM (role registry) to confirm an OracleSwapFreezer-type holder; on the freezer: `getFreezeBound()`, `getUnfreezeBound()`, `getCanUnfreeze()`, `GSM()`; GSM `getIsFrozen()`, `getIsSeized()`. Addresses per H2 bullet (aave-address-book, 2026-09-01). Output feeds the Member 2 primary selection and the L1 flag.
- Other facilitators [VERIFIED 2026-09-01: FlashMinter facilitator 0xb639D208Bcf0589D54FaC24E655C79EC529762B8 (transient, exclude); CCIP token pool = lock-and-mint on Ethereum (see §8.1.4(b))].
**Node enumeration scope (memo §4.5 note, ruled 2026-09-02, P2):** this table is a **freeze-time artifact** — reserves with non-zero attributed GHO backing at pool-set freeze, refreshed quarterly; between-freeze newcomers route via §8.2. Reserve universe enumerated from aave-address-book (2026-09-01) includes synthetics, LRTs, custodial BTC wrappers, XAUt, other analyzed stables, and Pendle PT tokens — rows added at freeze per §4 rules; unlabeled nodes → §8.2.
 
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
| aweETH / other LRTs | LRT | **row needed** — memo open point 2 [FIRST-RUN READ: attribution] |
| acbETH | cbETH | **row needed** — memo open point 2 [FIRST-RUN READ: attribution] |
| GSM boxed USDC / USDT | USDC / USDT | `recurses` |
| Any other | — | unlisted → §8.2 quarantine rule |
 
Expected verifiability result (Step-5 done-condition): a defensible non-trivial split — meaningful `recurses` weight via stables and WBTC, one `recurses_truncated` slice, remainder `terminal` / `terminal_other_layer`.
 
**Token-specific mechanisms:**
- *Facilitator caps* — per-facilitator bucket capacity and level are Tier-1 parameters; the Aave facilitator cap bounds CDP-originated supply, GSM exposure caps bound boxed supply.
- *GSM* — memo §3 exclusion applies: backed 1:1 by boxed asset, look-through per §4.5. Record: fee, price strategy, exposure cap, freeze/seize status [FIRST-RUN READ: live value].
- *Collateral attribution* — memo §11.1 (resolved). **Primary: pro-rata per position** — for each GHO borrower, collateral value × (GHO debt ÷ borrower's total debt), summed. Position enumeration via Aave V3 subgraph + multicall verification [ANALYST-SUPPLIED 2026-09-01: Aave V3 subgraph availability not verified; PoolDataProvider 0x…(AAVE_PROTOCOL_DATA_PROVIDER in address book) getUserReserveData is the on-chain path; position enumeration needs an indexer — implementer choice at Step 4]. **Cross-check: protocol-level ratio** — Aave V3 Ethereum aggregate collateral ÷ aggregate debt applied to Aave-facilitator GHO supply — always computed and reported. Divergence > 10% relative → reported finding. **Fallback:** per-position reads fail → publish on protocol-level with visible flag "attribution: protocol-level fallback"; two consecutive fallback runs → semantic quarantine. The GHO adapter is designed per-position.
**Pool set (exit liquidity):** Rule: memo §5. Frozen set established at first run; §5.4 exclusions apply — GHO pools paired with a *volatile* Aave collateral node held against GHO (e.g., GHO/WETH-type) are circular and excluded; stable-paired pools (GHO/USDC-type) are included per §5.4(ii), with the paired-stable failure modeled under the §6 paired-stable-depeg scenario. Expected pools [FIRST-RUN READ: discovery; GHO/crvUSD pool → analyzed-token rule]. Off-venue share disclosed per §5.1 [FIRST-RUN READ: discovery; Balancer GHO pools exist (Coinstancy 2026) — trigger likely]. Bridged/L2 supply via CCIP facilitators disclosed per §5.2 [FIRST-RUN READ: live value].
 
**Stress hooks (memo §6.3):**
- H2 crash path — (i) mint-side capacity: liquidators mint GHO from boxed asset up to exposure-cap headroom [VERIFIED 2026-09-01: see memo §6.3 H2; launch fee 0.2% (AIP-8)]; (ii) holder exit → §5.10 venue line below.
- H2 depeg path (Member 2) — **state-conditional primary (memo §6.3 H2, ruled 2026-09-02).** Per run, per GSM: CHECK (1) an automated OracleSwapFreezer-type contract holds SWAP_FREEZER_ROLE [role-registry read]; (2) its freeze lower bound ≥ 0.88 [freezer band read]. Pass → primary = freezer effective (contagion capped at GSM balance; GSM exit contribution removed from exit depth — same event); counterfactual = freezer fails to act in time (arb mint to exposure-cap headroom, supply backed at shocked price). Fail → primary = freezer fails; "effective" printed as counterfactual; **L1 flag** "automated freeze protection not in place / not effective in modeled range (block N)". Verified 2026-09-01: freezers 0x6e51936e0ED4256f9dA4794B536B619c88Ff0047 (USDC GSM 0x3A3868898305f04beC7FEa77BecFf04C13444112), 0x733AB16005c39d07FD3D9d1A350AA6768D10125b (USDT GSM 0x882285E62656b9623AF136Ce3078c6BdCc33F5E3) — aave-address-book; reference bounds on original instance 0.99/1.01 freeze, 0.995/1.005 unfreeze (Etherscan). Aave DAO executor is second freezer (AIP-8).
- H5 liquidator appetite — capacity = min(GHO sourceable = §5 buy-side depth + GSM mint headroom; collateral sellable = §6.3 analyst parameter per node), within the liquidation bonus; binding side reported per cell (metric 4). [FIRST-RUN READ: PoolDataProvider reads]
- Facilitator bucket caps bound recovery minting only (metric 4) [FIRST-RUN READ: GhoToken reads; bucket steward 0x46Aa1063e5265b43663E81329333B47c517A5409].
- Volatile nodes for Member 1: WETH, wstETH/rETH (LST axis), WBTC, governance tokens, LRTs/cbETH if present. Stable nodes shocked only in Member 2. Cells: 47.
- Member 2 target stable: set at pool-set freeze (memo §6.2.5; set at first freeze, not a Phase B item). Forced-sell numerator = GSM-facilitator bucket level for the shocked boxed asset + the §11.1 pro-rata slice attributed to shocked stable-collateral nodes (aUSDC/aUSDT/aDAI-type as applicable), full slice, not value-weighted.
- Paired-asset notes: GHO/crvUSD-type pools — crvUSD linked to its last published tree (memo §4.1), not shocked in Member 2; any 3CRV-type composite paired asset passes through pro-rata (memo §4.3).
**§5.10 venue line:** GSM counts as a deterministic exit venue — depth = boxed balance, price = 1 − fee, included at s = 2% iff sell fee < 2% [VERIFIED 2026-09-01: 0.2% at launch (AIP-8); current first-run read]; listed separately from pool depth; removed from exit depth when the freezer trips (Member 2 primary).
 
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
| R2 who | `anyone` [VERIFIED 2026-09-01: GSM sellAsset is permissionless per GSM design (docs.gho.xyz); freezer/seize are the only gates] | `no_one` |
| R3 received | boxed asset address [VERIFIED 2026-09-01: GSM_USDC 0x3A3868898305f04beC7FEa77BecFf04C13444112, GSM_USDT 0x882285E62656b9623AF136Ce3078c6BdCc33F5E3 (current, yield-bearing stata-based variants per Pharos Jul 2026); GSM registry 0x167527DB01325408696326e3580cd8e55D99Dc1A; GHO 0x40D16FC0246aD3160Ccc09B8D0D3A2cD28aE6C2f; FlashMinter 0xb639D208Bcf0589D54FaC24E655C79EC529762B8; CCIP token pool 0x06179f7C1be40863405f374E7f5F8806c728660A. Source: bgd-labs/aave-address-book main (GhoEthereum.sol, AaveV3Ethereum.sol, GovernanceV3Ethereum.sol)] | — |
| R4 rate | `face_minus_fee(sell fee [FIRST-RUN READ: live value])` | — |
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
| `mint` | Aave Governance executor [VERIFIED 2026-09-01: GhoToken FACILITATOR_MANAGER_ROLE / BUCKET_MANAGER_ROLE held by Executor Lvl-1 and delegated to GHO stewards (bucket steward 0x46Aa1063…, Aave-core steward 0x98217A06…, GSM steward 0xD1E856a9…) per AIP-61 'Activate GHO Stewards'; exact role holders [FIRST-RUN READ: GhoToken.getRoleMember]] | n/a (DAO) | [VERIFIED 2026-09-01: Level 1 = 1 day (86,400s; bucket 1–7d), Level 2 = 7 days (604,800s; bucket 1–7d) — aave.com/security; EXECUTOR_LVL_1 0x5300A1a15135EA4dc7aD5a167152C01EFc9b192A (also ACL_ADMIN), EXECUTOR_LVL_2 0x17Dd33Ed0e3dD2a80E37489B8A63063161BE6957 (bgd-labs/aave-address-book main (GhoEthereum.sol, AaveV3Ethereum.sol, GovernanceV3Ethereum.sol))] | Aave Guardian [VERIFIED 2026-09-01: Governance Guardian 0xCe52ab41C40575B072A18C9700091Ccbe4A06710 can cancel proposals/payloads; 5-of-9, signers disclosed in ARFC addendum (aave.com/help/governance); Granular Guardian 0x4457cA11… — bgd-labs/aave-address-book main (GhoEthereum.sol, AaveV3Ethereum.sol, GovernanceV3Ethereum.sol)] | — | GhoToken facilitator list | GhoToken role reads [FIRST-RUN READ: live value] |
| `set_ceiling` | Governance / role holder of `BUCKET_MANAGER_ROLE` [FIRST-RUN READ: live value]; GSM exposure cap setter [FIRST-RUN READ: live value]; risk steward for reserve caps [FIRST-RUN READ: live value] | | as above / steward: none? [FIRST-RUN READ: live value] | Guardian | — | facilitator buckets; GSM caps; supply/borrow caps | [FIRST-RUN READ: live value] |
| `upgrade` | Aave Governance [VERIFIED 2026-09-01: Aave V3 Pool 0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2 is a proxy administered via PoolAddressesProvider (Executor Lvl-1); GSMs are upgradeable (LlamaRisk cites 'upgradeable token' reviews); GhoToken upgradeability [FIRST-RUN READ: proxy admin slot] — GHO token was redeployed upgradeable per Immunefi scope note (LlamaRisk Mar 2026)] | n/a | executor timelock [FIRST-RUN READ: live value] | Guardian | `proxy_upgradeable(admin = executor)` for Pool/GSM [FIRST-RUN READ: live value]; GhoToken `immutable` [FIRST-RUN READ: live value] | Pool, GSMs | proxy admin reads [FIRST-RUN READ: live value] |
| `pause` | Aave Guardian (emergency pause of Pool / reserves) [VERIFIED 2026-09-01: Protocol Emergency Guardian 5-of-9 holds EMERGENCY_ADMIN (aave.com/help/governance/aave-community)]; GSM `SWAP_FREEZER_ROLE` [VERIFIED 2026-09-01: OracleSwapFreezer contracts (automation) + Aave DAO executor (AIP-8)] | multisig [FIRST-RUN READ: live value] | none (emergency) [FIRST-RUN READ: live value] | — | — | Pool, reserves, GSM swaps | [FIRST-RUN READ: live value] |
| `freeze_asset` | Guardian / risk steward (reserve freeze) [FIRST-RUN READ: live value] | | none [FIRST-RUN READ: live value] | | | reserves | [FIRST-RUN READ: live value] |
| `blacklist_address` | `none` expected on GhoToken [FIRST-RUN READ: live value] | | | | | | |
| `set_oracle` | Aave Governance (AaveOracle source setter) [FIRST-RUN READ: live value]; GSM price strategy setter [FIRST-RUN READ: live value] | n/a | executor timelock [FIRST-RUN READ: live value] | Guardian | — | all reserve feeds; GSM | [FIRST-RUN READ: live value] |
| `set_parameters` | Governance and risk steward (LTV, LT, bonus, caps within steward bounds) [VERIFIED 2026-09-01: Risk stewards / GHO stewards act within governance-set bounds, 1-of-1 multisig per aave.com/help; no timelock (bucket: none)]; GSM fee strategy [FIRST-RUN READ: live value] | | timelock / steward: [FIRST-RUN READ: live value] | Guardian | — | reserves; GSM | [FIRST-RUN READ: live value] |
| `seize` | GSM `LIQUIDATOR_ROLE` — `seize` after freeze [VERIFIED 2026-09-01: GSM seize by LIQUIDATOR_ROLE (DAO); proceeds to GHO treasury per GSM design (docs.gho.xyz) — role holder [FIRST-RUN READ: GSM.getRoleMember]] | [FIRST-RUN READ: live value] | none [FIRST-RUN READ: live value] | | | GSM boxed assets | [FIRST-RUN READ: live value] |
 
**Qualifier block (memo §13):** expected — `mint` — DAO + timelock, [bucket VERIFY], veto: Guardian; `upgrade` — DAO + timelock, [bucket VERIFY], veto: Guardian; `set_oracle` — DAO + timelock, [bucket VERIFY]; `seize` — role (GSM liquidator), none. Final content follows Phase B. Note for §11.11: GSM and facilitator sit under different holders/delays — the first test of whether token-level suffices.
 
**Audit status (memo §14):** audits [VERIFIED 2026-09-01: GSM: SigmaPrime, Certora, independent review by Emanuele Ricci (AIP-8, Jan 2024); GHO token/stewards audits enumerated on Aave Immunefi page (LlamaRisk Mar 2026)]; bug bounty [ANALYST-SUPPLIED 2026-09-01: Curve: bug bounty program stated on docs (platform/max not surfaced); GHO: Immunefi (LlamaRisk Mar 2026); Liquity: active bounty (TokenBrice) — max values first-run analyst entry]; last material change audited [ANALYST-SUPPLIED 2026-09-01: stata-based GSM variant audit not surfaced]. Staleness date: set at Phase B. Never scored.
 
**Counterparty enumeration (memo §14):** n/a — archetype #1 holds no off-chain counterparties. WBTC custodian captured in §4 look-through.
 
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
- Member 2 target stable: set at first freeze (not a Phase B item) — expected USDC via the 3CRV composite. Forced-sell numerator zero by construction → structural-insulation finding; Member 2 told via exit-depth curve (H4 redemption capacity is the notable line). Joint cell checks the `state_conditional` gate (H4 capacity zero if TCR < MCR).
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