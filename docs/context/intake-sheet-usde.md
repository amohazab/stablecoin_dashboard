# Token Intake Sheet — Archetype #2 (Synthetic / Off-Chain-Hedged): USDe (signed 2026-10-25 (P-10.02))

**Status:** signed 2026-10-25 (P-10.02) — rulings P-10.01 (Q1–Q50) and P-10.02 (points 1–4, D1–D19, F1–F4).
**Conventions:** memo #1's markers, unchanged. Blank analyst tags read `[ANALYST-SUPPLIED ____-__-__: …]` until Amin fills them. This sheet instantiates memo #2 rulings; it never restates or overrides them; a bare "memo §" in a heading the mirror parses is memo #2's. Addresses below were confirmed by reads at block 26265302 (Inventory G, G5) unless stated.

---

## USDe

**Archetype assignment:** #2, synthetic / off-chain-hedged. Fit test (memo #2 §1): the minting contract is named and read (EthenaMinting V2, by `USDe.minter()`); the custody perimeter is named (§14 below); the composition is published per run (`/api/positions/current/backing-assets`) and attested monthly with a weekly PoR — passes. It fails memo #1's fit test at "on-chain liquidation path" (memo #1 §1).

**Contracts to read** (pointer → evidence, P-3.28 form):

| Contract | Address | Etherscan name | Pointer | Evidence |
|---|---|---|---|---|
| USDe | 0x4c9edd5852cd905f086c759e8383e09bff1e68b3 | `USDe` | docs.ethena.fi key-addresses "USDe Token" | `name()`, `symbol()`, `minter()` |
| StakedUSDeV2 (sUSDe) | 0x9d39a5de30e57443bff2a8307a4256c8797a3497 | `StakedUSDeV2` | key-addresses "Staking Contract" | `asset()` = USDe; `cooldownDuration()`, `silo()` |
| USDeSilo | 0x7fc7c91d556b400afa565013e3f32055a0713425 | `USDeSilo` | `sUSDe.silo()` | Etherscan name + the `silo()` return |
| EthenaMinting V2 | 0xe3490297a08d6fc8da46edb7b6142e4f461b62d3 | `EthenaMinting` | key-addresses "Mint and Redeem V2" | `usde()` = USDe; `USDe.minter()` = this |
| Reserve Fund (Safe) | 0x2b5ab59163a6e93b4486f6055d33ca4a115dd4d5 | `GnosisSafeProxy` | key-addresses "Reserve Fund" | `VERSION()`, `getOwners()`, `getThreshold()` |
| USDeOFTAdapter | 0x5d3a1ff2b6bab83b63cd9ad0787074081a52ef34 | `USDeOFTAdapter` | L2 USDe OFT `peers(30101)` (not on docs.ethena.fi) | `token()` = USDe; `approvalRequired()` |
| EthenaTimelockController | 0xe8dc0fab349ea169283c48ccfd09d797e6db7c94 | `EthenaTimelockController` | `USDe.owner()` | owner of USDe, sUSDe, V2, adapter |
| Dev Multisig (Safe) | 0x3b0aaf6e6fcd4a7ceef8c92c32dfea9e64dc1862 | `GnosisSafeProxy` | key-addresses "Dev Multisig"; role logs | Safe getters |
| sUSDe Payout / Rewards (Safe) | 0x71e4f98e8f20c88112489de3dded4489802a3a87 | `GnosisSafeProxy` | role logs; two docs labels differ | Safe getters |
| StakingRewardsDistributor | 0xf2fa332bd83149c66b09b45670bce64746c6b439 | `StakingRewardsDistributor` | sUSDe REWARDER_ROLE logs | not a Safe |

EthenaMinting V1 0x2cc440b721d2cafd6d64908d6d8c4acc57f8afc3: retired by the `minter()` read; holds live roles and cannot mint — one disclosure line, outside the admin table (memo #2 §1, Q45).

**Reads per contract**, all at `run_block`:
- USDe: `owner()`, `pendingOwner()` [FIRST-RUN READ: USDe owner]; `minter()` [FIRST-RUN READ: USDe minter]; `totalSupply()` [FIRST-RUN READ: USDe totalSupply].
- sUSDe: `cooldownDuration()` [FIRST-RUN READ: sUSDe cooldownDuration]; `totalAssets()`, `totalSupply()` [FIRST-RUN READ: sUSDe totalAssets and totalSupply]; `USDe.balanceOf(sUSDe)` [FIRST-RUN READ: staked balance].
- Silo: `USDe.balanceOf(silo)`, silo from `sUSDe.silo()` [FIRST-RUN READ: silo balance].
- Adapter: `USDe.balanceOf(adapter)`, `approvalRequired()` [FIRST-RUN READ: adapter balance and lock flag].
- V2: `globalConfig()` [FIRST-RUN READ: V2 globalConfig]; `tokenConfig(asset)` per supported asset [FIRST-RUN READ: V2 tokenConfig per asset]; custodian set — `CustodianAddressAdded`/`Removed` as POINTER, `isCustodianAddress` as VERDICT [FIRST-RUN READ: V2 custodian set]; supported-asset set — `AssetAdded`/`Removed` as POINTER, `isSupportedAsset` as VERDICT [FIRST-RUN READ: V2 supported-asset set]; role holders — `RoleGranted`/`RoleRevoked` as POINTER, `hasRole` as VERDICT (P-4.04 R5) [FIRST-RUN READ: V2 role holders]; V2's own balance of every supported asset (D13) [FIRST-RUN READ: V2 balances per supported asset].
- sUSDe roles, same form [FIRST-RUN READ: sUSDe role holders]; `FULL_RESTRICTED_STAKER_ROLE` holders as one count [FIRST-RUN READ: restricted-address count].
- Timelock: `getMinDelay()` [FIRST-RUN READ: timelock getMinDelay]; PROPOSER / EXECUTOR / CANCELLER holders, logs → `hasRole` [FIRST-RUN READ: timelock role holders].
- Every Safe holder: `getOwners()`, `getThreshold()` [FIRST-RUN READ: Safe owners and threshold].
- EIP-1967 implementation / admin / beacon slots on USDe, sUSDe, V2, adapter [FIRST-RUN READ: EIP-1967 slots].
- Reserve Fund: balance of every supported asset, USDe and sUSDe [FIRST-RUN READ: reserve-fund balances].

**Supported-asset list (V2):** PYUSD 0x6c3ea9036406852006290770bedfcaba0e23a0e8 · USDtb 0xc139190f447e929f090edeb554d95abb8b18ac1c · USDG 0xe343167631d89b6ffc58b88d6b7fb0228795491d — each with its label row below (USDG's row lands now, D18). USDm 0xec2af1c8b110a61fd9c3fa6a554a031ca9943926: supported on V2, no §4 row, zero balance at 26265302; a non-zero balance routes via §8.2 (≥ 5% Level 2, < 5% Level 1) and the row is added at that intake (P-3.24 R-3 form).

**Disclosure sources per run** (memo #2 §2 source hierarchy, D15; each fetch a `DisclosureSnapshot`): `/api/positions/current/backing-assets` — strategy → counterparty → asset → location / chain / address / value, with `timestamp` [FIRST-RUN READ: backing-assets route]; `/api/collateral-breakdown` [FIRST-RUN READ: category usdAmount per category]; `/api/collateralization/status` [FIRST-RUN READ: status backing, reserve fund and supply in USD, timestamp]; `/api/por` [FIRST-RUN READ: `/api/por` lastUpdatedAt]; `/api/institutional-lending` (D14) [FIRST-RUN READ: institutional-lending route]; `/api/stablecoin-collateral` (D13) [FIRST-RUN READ: stablecoin-collateral route]; `/api/funding/quarterly` (D19) [FIRST-RUN READ: funding quarterly route]. The monthly attestation is the independent confirmation and the staleness clock.

**Backing nodes** (memo #2 §4; tree weight from these six alone, D1):

| Node | Memo #2 §4.5 row | Label |
|---|---|---|
| Crypto Basis | Crypto Basis | `recurses` (custodian attestation + weekly PoR; staleness = days since the newer); `disclosure_cadence` = monthly attestation + weekly PoR; `last_disclosure_date` = 2026-09-27 [ANALYST-SUPPLIED 2026-10-25: monthly (twenty-second monthly report, published 2026-10-10); September attestation post, https://ethena.fi/blog/custodian-attestations-of-assets-backing-usde-september-3; as-of 2026-09-27] |
| Equity and RWA Basis | Equity and RWA Basis | `recurses` (as Crypto Basis; collateral as bStocks at Ceffu); `disclosure_cadence` = monthly attestation + weekly PoR; `last_disclosure_date` = 2026-09-27 [ANALYST-SUPPLIED 2026-10-25: monthly; September attestation post; as-of 2026-09-27] |
| Institutional Lending | Institutional Lending | `recurses` (attestation letters as monthly confirmation; per-run note: lent, collateral, overcollateralisation, recall days from the institutional-lending route, D14); `disclosure_cadence` = monthly attestation; `last_disclosure_date` = 2026-09-27 [ANALYST-SUPPLIED 2026-10-25: monthly; September attestation post; as-of 2026-09-27] |
| Liquid Stables | Liquid Stables | `recurses` (staleness = the worst issuer cadence among its label rows below) |
| DeFi Lending | DeFi Lending | `recurses_truncated` — "lending positions; underlying stables not attributed by the disclosure" (P-10.02 point 3); `disclosure_cadence` = monthly attestation; `last_disclosure_date` = 2026-09-27 [ANALYST-SUPPLIED 2026-10-25: monthly; September attestation post; as-of 2026-09-27]; the Q4(ii) wallet reads are disclosed beside it and do not relabel the category |
| RWA (JAAA, STAC) | RWA (memo #1 §4.5 tokenized-fund row) | `recurses_truncated`; `disclosure_cadence` = NAV per fund — JAAA `nav_schedule`, STAC continuous on-chain verification; `last_disclosure_date` = 2026-10-25 [ANALYST-SUPPLIED 2026-10-25: JAAA `nav_schedule`, heartbeat 86,436 s observed (GHO sheet JAAA oracle row, B-9 read; as-of 2026-09-13); STAC (Securitize Tokenized AAA CLO Fund, BNY custody) continuous on-chain holdings and NAV/pricing verification by Chronicle since 2026-02-05, formal NAV publication cadence not located in public materials; https://securitize.io/stac, Securitize/Chronicle announcement 2026-02-05, STAC launch announcement 2025-10-29; as-of 2026-10-25] |
| Any other category | — | unlisted → memo #1 §8.2 quarantine rule |

**On-chain buffer assets (label rows, no tree weight; reconciliation input)** (memo #2 §2, §4.5; D1, D18). Balances at `run_block` for group (i), V2 custodian addresses [FIRST-RUN READ: buffer balances at V2 custodian addresses], and group (iii), V2's own balances (FR-U33); `chainSlug == ethereum` entries only (D17):

| Node | Memo §4.5 row | Label |
|---|---|---|
| USDT 0xdac17f958d2ee523a2206206994597c13d831ec7; USDT0 (as USDT — route lists it on Plasma and Mantle only, other chain) | memo #1 USDT | `recurses` (Tether); `disclosure_cadence` = quarterly BDO attestation; `last_disclosure_date` = 2026-06-30 [ANALYST-SUPPLIED 2026-10-25: most recent reserves report as of 2026-06-30; https://tether.to/en/transparency/; as-of 2026-06-30] |
| USDC 0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48 | memo #1 USDC | `recurses` (Circle); `disclosure_cadence` = monthly, Deloitte & Touche LLP (AICPA); `last_disclosure_date` = 2026-08-31 [ANALYST-SUPPLIED 2026-10-25: USDC Reserve Report as of 11 and 31 August 2026, issued 2026-09-29; https://www.circle.com/transparency; as-of 2026-08-31] |
| PYUSD 0x6c3ea9036406852006290770bedfcaba0e23a0e8 | memo #1 pyUSD | `recurses` (Paxos); `disclosure_cadence` = monthly, KPMG LLP New York (AICPA); `last_disclosure_date` = 2026-09-30 [ANALYST-SUPPLIED 2026-10-25: as of 17 and 30 September 2026, issued 2026-10-23, issuer Paxos Trust Company NA (OCC); https://paxos.com/pyusd-transparency/; as-of 2026-09-30] |
| USDtb 0xc139190f447e929f090edeb554d95abb8b18ac1c | memo #2 USDtb (new) | `recurses` (Anchorage Digital Bank NA); `disclosure_cadence` = monthly reserve attestation, Deloitte & Touche LLP (AICPA); `last_disclosure_date` = 2026-08-31 [ANALYST-SUPPLIED 2026-10-25: signed 2026-09-28, 529,269,213 redeemable tokens against $530,419,653 reserves (cash + BUIDL in segregated accounts); https://anchorage.com/platform/usdtb-reserve-attestations; as-of 2026-08-31] |
| USDG 0xe343167631d89b6ffc58b88d6b7fb0228795491d | memo #2 USDG (new, D18) | `recurses` (Paxos); `disclosure_cadence` = monthly, KPMG LLP Singapore (SSAE 3000); `last_disclosure_date` = 2026-09-30 [ANALYST-SUPPLIED 2026-10-25: as of 17 and 30 September 2026, issued 2026-10-23, issuers Paxos Digital Singapore (MAS) and Paxos Issuance Europe (FIN-FSA); https://paxos.com/usdg-transparency; as-of 2026-09-30] |
| RLUSD 0x8292bb45bf1ee4d140127049757c2e0ff06317ed (`symbol()` at 26269287) | memo #2 RLUSD (new, D18) | `recurses` (Ripple); `disclosure_cadence` = monthly, Deloitte & Touche LLP (AICPA); `last_disclosure_date` = 2026-08-31 [ANALYST-SUPPLIED 2026-10-25: "RLUSD Reserve Report August 2026" as of 17 and 31 August 2026, issued 2026-09-29, issuer Standard Custody & Trust Company (NYDFS); https://ripple.com/products/stablecoin/transparency/; as-of 2026-08-31] |
| sGHO (address not located: the route lists it with chain null) | memo #2 sGHO (new, D18) | transparent wrapper on GHO (memo #1 §4.3) → GHO, memo #1 §4.1 analyzed-set link |
| Any other asset | — | unlisted at its weight → memo #1 §8.2 |

Group (ii) — the union of the attestation's eleven wallets (the dated list below, DET-04 form, refreshed monthly) and the backing-assets route's Ethereum `addressEntries` per run (FR-U36), each address read once (F4); balances read on-chain [FIRST-RUN READ: buffer balances at group-(ii) wallets]. At 2026-10-25, 7 of the 11 were absent from the route (0x3feaa…5459, 0x3e99…623d, 0x1a52…cc8e, 0xc1f0…0e58, 0x61e6…acdae, 0xb127…1e0b, 0xa13f…4174), and the route's three Morpho wallets 0x3feaa7483fcfba130e68b41369dd78ff30465461, …462 and …463 were absent from the attestation. 0x2d4d2a025b10c09bdbd794b4fce4f7ea8c7d7bb4 is also a V2 custodian address: read once, both labels (D13). Source for every row [ANALYST-SUPPLIED 2026-10-25: September attestation post, "Coinbase Onchain Wallets", https://ethena.fi/blog/custodian-attestations-of-assets-backing-usde-september-3; as-of 2026-09-27]:

| Wallet | Chain | Read |
|---|---|---|
| 0x2d4d2a025b10c09bdbd794b4fce4f7ea8c7d7bb4 · 0xb8734a14fbd4aa2d44e6aa830405ffc861ba313c · 0x1c3b25019ed4e4876e7af7903cc3e1e23287c337 · 0x2bf5d9a2326ad3c5ef8208f91af79c3ca1f0f67c · 0x3feaa7483fcfba130e68b41369dd78ff30465459 · 0x3e9924b65eb75d05b7448305e66d1f490e70623d · 0x1a52abd3de0caceb71c5871386bec4f6eb80cc8e · 0xc1f00a3b50cbf62d91a0bed27e978eaed0470e58 · 0x61e614ec5e2f282ca42f313afacb45738ddacdae · 0xb127f6f301de26c72a4f4b65f2f15e12fae31e0b · 0xa13fee3e98808fe0ab4ae86509c6a068b3d24174 | Ethereum | balance per supported asset at `run_block` |
| C23FGxQB2LsoTbZsQr5w3R7b3sw5saxPLGJ4ujvyH34L · 4FaQc6QZ5skFjcDF64mKcXRhtCCsnArZcr1xumPNrbtN | Solana | disclosed only, not read (D17) |

**Token-specific mechanisms:**
- *Mint / redeem* (memo #2 §1, §12): whitelisted through V2; caps `globalConfig` and `tokenConfig`; MINTER, REDEEMER, GATEKEEPER roles; V1 retired (Q45).
- *Staking cooldown* (memo #2 §2 Q7, §6 row 3): `cooldownDuration()` selects row 3's branch; a live model input (memo #2 §13).
- *Reserve fund* (memo #2 §3): reported, never credited; absorbs first in rows 1 and 2.
- *OFT lock* (Q20): the adapter locks USDe on mainnet; bridge row `bridge_type` = `lock_and_mint` [ANALYST-SUPPLIED 2026-10-25: https://governance.aave.com/t/usde-usde-on-aave-monad-assessments/25255; G5 `approvalRequired()` = true; as-of 2026-10-24].

**Supply decomposition** (Q21, Q24; DET-15(b) synthetic form, A-29): O = `totalSupply()`, with `minter()` uniqueness as evidence; residual zero by construction. Classes: staked = `USDe.balanceOf(sUSDe)` · cooling = `USDe.balanceOf(silo)` · bridged escrow = `USDe.balanceOf(adapter)` · free float = O − the three (derived, `lineage`). Denominator `supply_ruled` = O for every "% of supply" (Q23); `cooldownDuration` printed beside staked.

**Pool set (exit liquidity):** memo #2 §5 (memo #1 §5 whole, three deltas). [VERIFIED 2026-10-24: two USDe Curve pools above the $500k floor — FRAXUSDe 0x5dc1BF6f1e983C0b21EfB003c105133736fA0743 (FRAX) and "Curve Strategic Ethena Reserves" 0x5B03CcCAb7BA3010fA5CAd23746cbf0794938e96 (USDT), both factory-stable-ng; no sUSDe-paired pool; USDe/crvUSD 0xF55B0f6F2Da5ffDDb104b58a60F2862745960442 below floor; off-venue 22.1% (DefiLlama, DET-32 filter) — Curve API and DefiLlama, Inventory G G7]. Frozen set at first freeze [FIRST-RUN READ: three-way discovery and frozen set]; off-venue share per run [FIRST-RUN READ: DET-32 off-venue share]. `member2_target` = None; the set file records "no Member 2 in this family".
- Paired asset legacy FRAX 0x853d955acef822db058eb8505911ed77f175b99e (Q41, RULED): `recurses` → Frax disclosure — none published [ANALYST-SUPPLIED 2026-10-25: no dedicated reserve balance sheet or transparency page located for legacy FRAX; Frax's transparency material describes frxUSD; FIP-430 (2025-04-21) established separate balance sheets and ended the guaranteed 1:1 LFRAX to frxUSD migration; the absence of a report does not establish that legacy FRAX is unbacked; pages checked: Frax Transparency page, frax.com frxUSD page, Frax docs "What is frxUSD?", "Protocol overview", "Token addresses", Frax governance FIP-430; as-of 2026-10-25]; unit-priced with the numeraire, par-eligible.

**Stress inputs** (memo #2 §6; ids are this sheet's `first_run_reads[]` rows):
- *Row 1 — funding reversal.* Inputs: `cat.crypto_basis`, `cat.equity_rwa_basis` (FR-U20); reserve fund `rf.balances` (FR-U19), `status.reserve_fund_usd` (FR-U21); `backing.total_usd` (FR-U21); `supply_ruled` (FR-U03); F = −25%, N ∈ {30, 90, 180} (memo); reference point = the series minimum, with "no negative quarter observed" while none is (FR-U37, F3). Headline cell `S1-n90`; cells `S1-n30`, `S1-n90`, `S1-n180`. Counterfactual line `cf.basis_unwind_day0`.
- *Row 2 — venue loss.* Inputs per run from the backing-assets route (FR-U36): the largest location total across all strategies (leg a, F2) and the largest exchange's hedge notional (leg b, ×30%); reserve fund (FR-U19, FR-U21); backing (FR-U21); `supply_ruled` (FR-U03). Cells `S2-a`, `S2-b`; headline = the lower post-loss backing ratio. No counterfactual line.
- *Row 3 — redemptions.* Inputs: O (FR-U03), staked (FR-U06), silo (FR-U07), escrow (FR-U08), `cooldownDuration` (FR-U04), `globalMaxRedeemPerBlock` (FR-U09), Σ `/api/stablecoin-collateral` (FR-U35) for `capacity_redeem`, checked on-chain by V2's own balances (FR-U33), never an addend (F1), Curve exit depth at s = 2% [FIRST-RUN READ: exit depth at s = 2% from the frozen set]; DET-30's K rows attach to `S3` (D2). Cell `S3`, headline = depeg-pressure ratio. Counterfactual line `cf.cooldown_branch`.
- No `m4` line (Q19, Q28).

**stock-only capacity — direction of error per mechanism** (DET-53; `bias_table[]`; memo #2 §6; no ★ rows on this sheet, pending A-32)

| Mechanism | Token | Direction | Reason |
|---|---|---|---|
| Row 3 — liquid buffer treated as instantly available | USDe | overstates | the full category is redeemable within the window |
| Row 3 — no issuer top-up of the buffer | USDe | understates | no rebalancing from the basis book during the run |
| Row 1 — funding reversal | USDe | n/a | a loss over a stated horizon, not a stock-only capacity |
| Row 2 — venue loss | USDe | n/a | a balance-sheet write-down, not a stock-only capacity |

**Quarantine instances** (memo #2 §8; Q22, D5):
- (a) category share shift > 10pp, or a top-3 change — L1 (T-04).
- (b) supply jump > 25% between runs: DefiLlama + Blockscout confirm → L1 (T-05), disagree → L3 (T-14).
- (c) custodian or exchange count change in the attestation or the route: addition L1 (T-06), removal L2 (T-12).
- (d) near bound — backing ratio < 101%, or reserve fund < 0.5% of supply — L1 (T-07).
- Disclosure overdue — a `recurses` node older than 2× its `disclosure_cadence` — L1, **T-29** (A-28, owner DET-18).
- Buffer reconciliation gap > 5% of backing, `chainSlug == ethereum` only — L1, **T-30**, gap printed (memo #2 §2).
- Ethena endpoint outage or shape change — DET-85, T-25, L2, USDe only (Q29).

**Oracle rows (Q10).** Category nodes, one DET-55 row each:

| node | update_condition.type | staleness_check | assumption_applied | counterfactual_ref |
|---|---|---|---|---|
| Crypto Basis · Equity and RWA Basis · Institutional Lending · Liquid Stables · DeFi Lending · RWA (one row each) | `attested` — "no on-chain price source; attested value" | `not_applicable_attested` | `attested_value` | None |

**Oracle feed table (DET-54 / DET-55; buffer assets at par, R-16, reference feeds in DET-54's gap column)** [ANALYST-SUPPLIED 2026-10-25: PYUSD, RLUSD, USDG, USDtb from the Chainlink feed directory, `description()` and `symbol()` verified on-chain at 26269287; USDT and USDC rows reused from the GHO sheet; as-of 2026-10-25]. Reference-feed reads at `run_block` [FIRST-RUN READ: reference feed latestRoundData per buffer asset].

| node | symbol | feed_or_source | class · description() | update_condition.type | deviation | heartbeat_s (form documented unless stated) | source | date |
|---|---|---|---|---|---|---|---|---|
| 0x6c3ea9036406852006290770bedfcaba0e23a0e8 | PYUSD | 0x8f1df6d7f2db73eece86a18b4381f4707b918fb1 | raw · PYUSD / USD | `deviation_heartbeat` | 0.3% | 86400 | Chainlink feed directory (data.chain.link), fetched 2026-10-25 | 2026-10-25 |
| 0x8292bb45bf1ee4d140127049757c2e0ff06317ed | RLUSD | 0x26c46b7ad0012ca71f2298ada567dc9af14e7f2a | raw · RLUSD / USD | `deviation_heartbeat` | 0.3% | 86400 | Chainlink feed directory (data.chain.link), fetched 2026-10-25 | 2026-10-25 |
| 0xe343167631d89b6ffc58b88d6b7fb0228795491d | USDG | 0x14f0737d6b705259e521ea6e9e3506ac78dbd311 | raw · USDG / USD | `deviation_heartbeat` | 0.25% | 86400 | Chainlink feed directory (data.chain.link), fetched 2026-10-25 | 2026-10-25 |
| 0xc139190f447e929f090edeb554d95abb8b18ac1c | USDtb | 0x66704dad467a7ca508b3be15865d9b9f3e186c90 | raw · USDtb / USD | `deviation_heartbeat` | 0.5% | 86400 | Chainlink feed directory (data.chain.link), fetched 2026-10-25 | 2026-10-25 |
| 0xdac17f958d2ee523a2206206994597c13d831ec7 | USDT | 0x3e7d1eab13ad0104d2750b8863b489d65364e32d | raw · USDT / USD | `deviation_heartbeat` | 0.25% | 86400 | Chainlink feed directory (data.chain.link), fetched 2026-10-25; `description()` verified at 26271959 | 2026-10-25 |
| 0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48 | USDC | 0x8fffffd4afb6115b954bd326cbe7b4ba576818f6 | raw · USDC / USD | `deviation_heartbeat` | 0.25% | 82800 | Chainlink feed directory (data.chain.link), fetched 2026-10-25; `description()` verified at 26271959 | 2026-10-25 |

**Redemption-rights (memo #2 §12) — holder paths: 1**

| Field | Path 1 — EthenaMinting V2 |
|---|---|
| R1 path | `module_on_chain` |
| R2 who | `whitelisted` (REDEEMER_ROLE holders, FR-U13) |
| R3 received | the supported assets (FR-U12) |
| R4 rate | `face_value` |
| R5 minimum | `none` |
| R6 gates | `capacity_limited` + `pausable` (GATEKEEPER_ROLE) |
| R7 capacity | `globalMaxRedeemPerBlock` (FR-U09) and Σ `/api/stablecoin-collateral` (FR-U35) (F1) |
| R8 (computed) | computed per memo #1 §12, unchanged |
| R9 legal claim | `disclaimed` [ANALYST-SUPPLIED 2026-10-25: USDe Terms and Conditions (general, last updated August 2025) §2 "you may only utilize accepted assets to create USDe and redeem USDe directly with Ethena BVI to the extent that you are a Mint User"; §11 "Only Mint Users can redeem USDe directly with Ethena BVI"; Mint User Agreement §1, whitelisted wallet and KYC/KYB screening; docs.ethena.fi terms pages; as-of 2026-10-25] |
| R10 provenance | EthenaMinting V2 `redeem` [FIRST-RUN READ: V2 redeem selector present] |

Note (D7): R8 is unchanged; the page prints R2 beside R8, and wording owns one sentence, "redeemable by approved counterparties only".

**Admin-power surface (memo #2 §13)** — holders by address and type; A4 = timelock `getMinDelay()` (FR-U15); A3 counts from FR-U17, identity undisclosed unless published:

| A1 power | A2 holder | A3 signers | A4 delay | A5 veto | A6 upgradeability | A7 scope | A8 provenance |
|---|---|---|---|---|---|---|---|
| `mint` | timelock 0xe8dc…7c94 (`USDe.owner`, via `setMinter`); controller: PROPOSER/EXECUTOR holders (FR-U16) | n/a | FR-U15 | CANCELLER holders (FR-U16), else `none` | — | V2; MINTER_ROLE EOAs (FR-U13) | FR-U01, FR-U13 |
| `set_ceiling` | timelock (`globalConfig` / `tokenConfig` setters) | n/a | FR-U15 | as `mint` | — | V2 per-block caps | FR-U09, FR-U10 |
| `set_parameters` | timelock (`cooldownDuration`, custodian and supported-asset lists); Dev Multisig 0x3b0a…1862 `multisig` (COLLATERAL_MANAGER_ROLE transfers) | FR-U17 | FR-U15; Dev Multisig none | as `mint` | — | sUSDe; V2 custody lists | FR-U13, FR-U14 |
| `pause` | GATEKEEPER_ROLE, four `eoa` (V2 disable) | — | none | — | — | V2 mint and redeem | FR-U13 |
| `freeze_asset` | timelock (`tokenConfig.isActive` per asset) | n/a | FR-U15 | as `mint` | — | V2 supported assets | FR-U10 |
| `blacklist_address` | BLACKLIST_MANAGER_ROLE on sUSDe: two `eoa` + Dev Multisig | FR-U17 | none | — | — | sUSDe | FR-U14 |
| `seize` | timelock as DEFAULT_ADMIN (`redistributeLockedAmount`) | n/a | FR-U15 | as `mint` | — | sUSDe restricted balances | FR-U14 [FIRST-RUN READ: redistributeLockedAmount selector present] |
| `upgrade` | `none` | — | — | — | `immutable` (FR-U18) | — | FR-U18 |
| `set_oracle` | `none` — no oracle setter [FIRST-RUN READ: oracle-setter selector absence on USDe, sUSDe, V2] | — | — | — | — | — | absence scan |

**Qualifier block (memo #2 §13):** `mint` — timelock; `seize` — timelock; `set_parameters` (custody scope: custodian list, COLLATERAL_MANAGER_ROLE) — timelock + Dev Multisig; `upgrade` — none (immutable); `set_oracle` — none. Banner sentence: "backing held by [n] custodians under issuer discretion; on-chain keys shown below". Fully restricted sUSDe addresses: one count line (FR-U32). EthenaMinting V1: one line, outside this table (Q45).

**Audit status (memo §14)** — structured (DET-73; memo #2 §14):
- `audits[]` [ANALYST-SUPPLIED 2026-10-25: https://docs.ethena.fi/resources/audits, page last updated about a year ago; also listed, without a full date on the page: Zellic (v1, 2023) and Chaos Labs (economic risk: LST, perpetuals, on-chain liquidity); as-of 2026-10-25]: Quantstamp 2023-10-18, v1 · Spearbit 2023-10-18, v1 · Pashov 2023-10-22, v1 · Code4rena 2023-11-13, v1 (public) · Pashov 2023-12-22, ENA and LP staking · Pashov 2024-05-23, V2 contracts · Pashov 2024-09-02, sENA · Pashov 2024-10-20, USDtb · Quantstamp 2024-10-25, USDtb · Cyfrin 2024-10-31, USDtb
- `bug_bounty` = {platform: Immunefi, max: USD 3,000,000} [ANALYST-SUPPLIED 2026-10-25: live since 2024-04-04, last updated 2026-08-11; https://immunefi.com/bug-bounty/ethena/information/; as-of 2026-10-25]
- `last_material_change_audited` = yes [ANALYST-SUPPLIED 2026-10-25: recorded reading — StakedUSDeV2 deployed 2023-11-14 inside the v1 audit series; EthenaMinting V2 deployed 2024-06-21, 29 days after Pashov's V2 review of 2024-05-23; byte-identity against the reviewed commit not performed; audits page; creation txs; as-of 2026-10-25]
- `staleness_date` = 2026-10-25. Never scored.

**Counterparty enumeration (memo §14):** filled per memo #2 §14 (Q26, D6) — direct custodians Copper, Ceffu, Anchorage Digital Bank, Kraken Financial; lending counterparties FalconX International Lending Opportunities SPC (loans $236.64m, over-collateralised ~166% by BTC/ETH/SOL/XRP/USD/USDC at Anchorage, BitGo, Kraken under account-control agreements) and one unnamed borrower under Anchorage's secured lending arrangement ($81m against $145.54m BTC); derivatives Ripple Prime (Hidden Road Partners CIV US LLC d/b/a Ripple Prime), FCM for CME and Coinbase Derivatives Exchange; basis-hedge exchanges Binance (via Ceffu), OKX, Bybit, Deribit (via Copper), CDE (via Hidden Road); on-chain wallets, Coinbase-labeled; per-run shares from the backing-assets route (FR-U36), letters as monthly confirmation [ANALYST-SUPPLIED 2026-10-25: letter values — Copper Markets (Switzerland) AG $668,759,532.90 incl. unrealised P&L; Ceffu Digital Pte. Ltd. ≥ $733,212,922.85 (post headline $0.675bn); Anchorage Digital Bank NA $576,576,634 held + $81,000,000 USDC/USDT loaned against $145,541,292 BTC in tri-party custody (post headline $0.657bn); Kraken Financial $41,690.76; Ethena x FalconX SPV collateral $393,803,618.69 (Anchorage $137,516,667, BitGo $181,930,552, Payward/Kraken $74,408,775.45) against loans of $236,644,959.12; Ripple Prime FCM account equity $7,934,609.93; Coinbase on-chain wallets $2.620bn; MintRedeem contract $89.230m; total backing $4.953bn; reserve fund $62.095m; 101.34% incl. reserve fund; USDe supply 4.949bn; September attestation post and its custodian letters, https://ethena.fi/blog/custodian-attestations-of-assets-backing-usde-september-3; route https://app.ethena.fi/api/positions/current/backing-assets read 2026-10-25; as-of 2026-09-27]

**`first_run_reads[]` (DET-75 / R-45)** — registry of every FIRST-RUN READ tag on this sheet, resolved to a concrete read. **Count identity: 37 literal tags = 37 open rows.** All reads at `run_block`. Shorthand: **USDE** = 0x4c9edd5852cd905f086c759e8383e09bff1e68b3 · **SUSDE** = 0x9d39a5de30e57443bff2a8307a4256c8797a3497 · **V2** = 0xe3490297a08d6fc8da46edb7b6142e4f461b62d3 · **TL** = 0xe8dc0fab349ea169283c48ccfd09d797e6db7c94 · **OFT** = 0x5d3a1ff2b6bab83b63cd9ad0787074081a52ef34 · **RF** = 0x2b5ab59163a6e93b4486f6055d33ca4a115dd4d5 · **APP** = https://app.ethena.fi.

| tag_id | sheet_location | bundle_field_path | read_spec | status |
|---|---|---|---|---|
| FR-U01 | USDe § Reads — USDe | `admin_surface[mint].holder` | `USDE.owner()`, `pendingOwner()` | open |
| FR-U02 | USDe § Reads — USDe | `supply.minter` | `USDE.minter()` | open |
| FR-U03 | USDe § Reads — USDe | `supply.total_supply` | `USDE.totalSupply()` | open |
| FR-U04 | USDe § Reads — sUSDe | `staking.cooldown_duration_s` | `SUSDE.cooldownDuration()` | open |
| FR-U05 | USDe § Reads — sUSDe | `staking.{total_assets, total_supply}` | `SUSDE.totalAssets()`, `totalSupply()` | open |
| FR-U06 | USDe § Reads — sUSDe | `supply.classes.staked` | `USDE.balanceOf(SUSDE)` | open |
| FR-U07 | USDe § Reads — Silo | `supply.classes.cooling` | `USDE.balanceOf(SUSDE.silo())` | open |
| FR-U08 | USDe § Reads — Adapter | `supply.classes.bridged_escrow`, `supply.bridges[]` | `USDE.balanceOf(OFT)`; `OFT.approvalRequired()` | open |
| FR-U09 | USDe § Reads — V2 | `minting.global_config` | `V2.globalConfig()` | open |
| FR-U10 | USDe § Reads — V2 | `minting.token_config[]` | `V2.tokenConfig(a)` ∀ supported a | open |
| FR-U11 | USDe § Reads — V2 | `minting.custodians[]` | `CustodianAddressAdded`/`Removed` logs (POINTER); `V2.isCustodianAddress(c)` (VERDICT) | open |
| FR-U12 | USDe § Reads — V2 | `minting.supported_assets[]` | `AssetAdded`/`Removed` logs (POINTER); `V2.isSupportedAsset(a)` (VERDICT) | open |
| FR-U13 | USDe § Reads — V2 | `admin_surface[].holders` (V2 roles) | `RoleGranted`/`RoleRevoked` logs (POINTER); `V2.hasRole(r, h)` (VERDICT) | open |
| FR-U14 | USDe § Reads — sUSDe roles | `admin_surface[].holders` (sUSDe roles) | as FR-U13 on SUSDE | open |
| FR-U15 | USDe § Reads — Timelock | `admin_surface[].delay_s` | `TL.getMinDelay()` | open |
| FR-U16 | USDe § Reads — Timelock | `admin_surface[].controller` | TL PROPOSER/EXECUTOR/CANCELLER: logs (POINTER), `TL.hasRole` (VERDICT) | open |
| FR-U17 | USDe § Reads — Safes | `admin_surface[].signers` | `getOwners()`, `getThreshold()` per Safe holder | open |
| FR-U18 | USDe § Reads — EIP-1967 | `admin_surface[upgrade].upgradeability` | `eth_getStorageAt` impl/admin/beacon slots on USDE, SUSDE, V2, OFT | open |
| FR-U19 | USDe § Reads — Reserve Fund | `reserve_fund.balances[]` | `balanceOf(RF)` ∀ supported asset, USDe, sUSDe; ETH balance | open |
| FR-U20 | USDe § Disclosure sources | `nodes[category].value_usd` | GET APP `/api/collateral-breakdown`; `DisclosureSnapshot` | open |
| FR-U21 | USDe § Disclosure sources | `backing.total_usd`, `reserve_fund.disclosed_usd`, `backing.as_of` | GET APP `/api/collateralization/status`; `DisclosureSnapshot` | open |
| FR-U22 | USDe § Disclosure sources | `nodes[*_basis].por_last_updated` | GET APP `/api/por` `lastUpdatedAt`; `DisclosureSnapshot` | open |
| FR-U23 | USDe § On-chain buffer assets | `buffer.balances[]` (group i) | `balanceOf(c)` ∀ asset ∀ FR-U11 custodian | open |
| FR-U24 | USDe § On-chain buffer assets — Q4(ii) | `buffer.balances[]` (group ii) | `balanceOf(w)` ∀ asset ∀ address in the union of the dated list and FR-U36's Ethereum `addressEntries`, each once (F4) | open |
| FR-U25 | USDe § Pool set | `discovered_pools[]`, `frozen_set` | three-way discovery; `pool.balances(i)` at par | open |
| FR-U26 | USDe § Pool set — off-venue | `offvenue_share` | DET-32 `X = 1 − curve/total` | open |
| FR-U27 | USDe § Stress inputs — row 3 | `exit_depth.s2` | depth solver at s = 2% over the frozen set | open |
| FR-U28 | USDe § Oracle feed table | `oracle[].reference_round` | `latestRoundData()` per reference feed | open |
| FR-U29 | USDe § Redemption-rights R10 | `redemption_paths[0].r10_provenance` | selector-presence scan for `redeem` over `eth_getCode(V2)` | open |
| FR-U30 | USDe § Admin surface — `seize` | `admin_surface[seize].reads` | selector-presence scan for `redistributeLockedAmount` over `eth_getCode(SUSDE)` | open |
| FR-U31 | USDe § Admin surface — `set_oracle` | `admin_surface[set_oracle].holder` | selector-absence scan over USDE, SUSDE, V2 → `none` | open |
| FR-U32 | USDe § Reads — sUSDe roles | `admin_surface[blacklist_address].restricted_count` | count of FULL_RESTRICTED_STAKER_ROLE holders: logs (POINTER), `SUSDE.hasRole` (VERDICT) | open |
| FR-U33 | USDe § Reads — V2 | `buffer.balances[]` (group iii) | `balanceOf(V2)` ∀ supported asset — the on-chain check of FR-U35's sum (F1) | open |
| FR-U34 | USDe § Disclosure sources | `nodes[institutional_lending].note` | GET APP `/api/institutional-lending` `totals`, `counterparties[]`; `DisclosureSnapshot` (D14) | open |
| FR-U35 | USDe § Disclosure sources | `buffer.disclosed_by_symbol[]` | GET APP `/api/stablecoin-collateral`; `DisclosureSnapshot` (D13) | open |
| FR-U36 | USDe § Disclosure sources | `disclosure.backing_assets` | GET APP `/api/positions/current/backing-assets` `strategies[]`, `timestamp`; `DisclosureSnapshot` (D15) | open |
| FR-U37 | USDe § Disclosure sources | `stress.row1.reference_point` | GET APP `/api/funding/quarterly`, minimum `value`; `DisclosureSnapshot` (D19) | open |
