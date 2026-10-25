# Archetype Memo #2 — Synthetic / Off-Chain-Hedged Stablecoins (signed 2026-10-25 (P-10.02))

**Status:** signed 2026-10-25 (P-10.02) — rulings P-10.01 (Q1–Q50) and P-10.02 (points 1–4, D1–D19, F1–F4); §7.3 added 2026-10-25 (P-10.04).
**Applies to:** USDe (Ethena). Archetype membership is decided at the intake gate (memo #1 §1).
**Conventions:** memo #1's markers, unchanged: `[VERIFIED <date>: …]`, `[FIRST-RUN READ: …]`, `[ANALYST-SUPPLIED <date>: …]`, `[RE-SCOPED TO INTAKE: …]`; mechanism logic carries no marker. Blank analyst tags read `[ANALYST-SUPPLIED ____-__-__: …]` until Amin fills them. **Every generic rule is memo #1's, cited by section and never restated (Q39); this memo states only the deltas.** Section numbers follow memo #1; §10 and §15 carry no archetype-#2 content.

---

## §1. Archetype definition and scope

**Definition.** A synthetic / off-chain-hedged stablecoin is one whose supply originates when a **whitelisted counterparty deposits backing into the issuer's minting contract**; the backing is **issuer-held**, split between off-exchange custody (spot plus short derivatives — basis trades) and liquid stables on-chain; there is **no on-chain liquidation path**; the holder's claim is **contractual** (Q1).

**Fit test (applied at intake).** A token passes if (i) the minting contract can be named and read, (ii) the custody perimeter can be named, and (iii) the backing composition is published on a stated cadence (Q1). A token whose sheet cannot be filled under these rulings belongs elsewhere (memo #1 §1, intake gate).

**Boundaries.**
- *Against archetype #1 (CDP):* no third-party collateral with an on-chain liquidation path — the token fails memo #1's fit test at that clause (memo #1 §1, synthetic boundary).
- *Against the fiat archetype:* the backing includes an on-chain-readable buffer and derivative hedges, not only bank and treasury reserves; the fiat archetype's backing is issuer-held bank and treasury assets verified by attestation alone.
- *Hybrids:* routed by sleeve weight through the unlisted-node rule (memo #1 §1, §8.2).

**Applies to:** USDe. Minting contract EthenaMinting V2 [VERIFIED 2026-10-24: `USDe.minter()` = 0xe3490297a08d6fc8da46edb7b6142e4f461b62d3 at block 26265302; Etherscan `EthenaMinting`; Inventory G G5]. V1 (0x2cc440b7…fc3) is retired by that read and carries one disclosure line outside the admin table (Q45).

## §2. Definition of backing

**Address gate (Q2).** Memo #1 §2 applies to every on-chain node: keyed by token contract address, never symbol. **The archetype's one exception:** the custody and basis sleeves are keyed by **disclosure category plus the attestation reference**, because no address exists for them. *Rejected:* keying by exchange.

**Source hierarchy (D15, reordering Q25).** Per-run values for composition, counterparty split and locations come from `/api/positions/current/backing-assets` (strategy → counterparty → asset → location / chain / address / value, with its timestamp), each fetch a `DisclosureSnapshot` (§9) [FIRST-RUN READ: per-run fetch, shape-validated, snapshot committed]. The monthly attestation is the independent confirmation and the staleness clock for `recurses` nodes. Analyst keys only where no route exists.

**Backing and headline (Q3).** Backing = the disclosure's total backing at disclosed value (`/api/collateralization/status`, `totalBackingAssetsInUsd`) [FIRST-RUN READ: per-run fetch, shape-validated, snapshot committed]. Headline = backing ÷ `supply_ruled`, printed beside the status `timestamp`. Nothing is re-valued by this pipeline. `supply_ruled` = mainnet `totalSupply()` (Q20) [FIRST-RUN READ: `USDe.totalSupply()` at `run_block`].

**On-chain buffer — label rows and reconciliation input (Q4, D1, D13).** Three groups, balances read at `run_block`; each asset sits under its §4.5 label row; none carries tree weight (§4).
- (i) EthenaMinting V2's custodian-address set and supported-asset set: add/remove events as POINTER, `isCustodianAddress` / `isSupportedAsset` as VERDICT; balance per asset per address [FIRST-RUN READ: sets and balances at `run_block`].
- (ii) The union of the attestation's on-chain wallet list (the Coinbase-labeled wallets, §14) and the backing-assets route's Ethereum `addressEntries` per run, each address read once (F4): the attestation list is a dated analyst-supplied list in DET-04 form, refreshed monthly [ANALYST-SUPPLIED 2026-10-25: 11 Ethereum wallets, listed on the USDe sheet, plus 2 Solana wallets disclosed only, not read; September attestation post, "Coinbase Onchain Wallets", https://ethena.fi/blog/custodian-attestations-of-assets-backing-usde-september-3; as-of 2026-09-27]; balances read on-chain.
- (iii) EthenaMinting V2's own balance of every supported asset [FIRST-RUN READ: V2 balances per supported asset]: the on-chain check of Σ `/api/stablecoin-collateral` [FIRST-RUN READ: per-run fetch], which row 3's `capacity_redeem` uses (§6); the V2 balances are a check, never an addend (F1).
An address in two groups (the first attestation wallet 0x2d4d2a… is also a V2 custodian address) is read once and carries both labels.

**Reconciliation (Q5, D17).** Σ on-chain buffer balances versus the disclosure's Liquid Stables + DeFi Lending + RWA categories, over entries with `chainSlug == ethereum` only; positions on other chains (Plasma, Mantle, Base, Solana, Robinhood, XRPL in the route at 2026-10-25) are disclosed as "balance not read by this pipeline (other chain)", labels unchanged — memo #1 §5.2's mainnet scope applied to backing. A gap beyond 5% of backing fires T-30, Level 1, with the gap printed (D5). Never a silent pick between the two.

**Reserve fund (Q6).** Outside backing; its own slice, §3.

**sUSDe (Q7).** Not a backing node and not a USDe redemption path. It appears as a supply-class line (Q24) and as the cooldown gate in stress row 3 (§6). Yield is out of scope.

## §3. The reserve-fund slice — classification and class rule

**Ruling (Q6).** The issuer's reserve fund is **outside backing**: reported as its own labeled slice, **"protocol reserve fund, discretionary"**, and **never credited** in the headline.

**Rationale.** The fund is held at the issuer's discretion with no holder claim on it; crediting it would count a buffer the holder cannot enforce. It is disclosed in full and used where it acts: as the first absorber in stress rows 1 and 2 (§6).

**Class rule.** Issuer-held discretionary buffers are reported, not credited, in every token of this archetype — the shape of memo #1 §3 (a zero-credited, fully disclosed slice), applied to a discretionary buffer instead of a stabilizer.

**Disclosure fields (adapter output).** Fund address [VERIFIED 2026-10-24: 0x2b5ab59163a6e93b4486f6055d33ca4a115dd4d5, Safe v1.3.0 4-of-10, docs.ethena.fi key-addresses "Reserve Fund"; Inventory G G5]; balance of every supported asset at `run_block` [FIRST-RUN READ: per asset]; cross-shown with `status.totalReserveFundInUsd` [FIRST-RUN READ: per-run fetch]; provenance per read.

## §4. Look-through policy

Memo #1 §4.1 (depth), §4.2 (four labels, closed), §4.3 (transparent wrappers, composite pass-through) and §4.6 (headline arithmetic) apply unchanged.

**Nodes (Q8, D1).** One node per disclosure category at its `usdAmount`; six categories today [FIRST-RUN READ: `/api/collateral-breakdown`]. **Tree weight comes from the six category nodes alone; the buffer assets by address are label rows (they give Liquid Stables its staleness) and the §2 reconciliation input, with zero tree weight.** A new category is an unlisted node → memo #1 §8.2. **Spot leg inside a basis sleeve (Q9):** not decomposed; the attested net position is the node. *Rejected:* `terminal_other_layer` for spot held at a custodian.

**Institutional Lending, per run (D14).** The node's per-run source is `/api/institutional-lending` (overcollateralisation, collateral composition, per-loan collateral, lent amount, LTV, recall days) [FIRST-RUN READ: per-run fetch]; the node note carries lent, collateral, ratio and recall days; the attestation letters stay the monthly independent confirmation.

**Valuation (Q10).** Buffer stables at par (R-16), with Chainlink reference feeds in DET-54's gap column; wrappers via memo #1 §4.3. Every disclosure-category node carries one DET-55 row: "no on-chain price source; attested value", `update_condition.type` = `attested`, `staleness_check` = `not_applicable_attested`, `assumption_applied` = `attested_value`, `counterfactual_ref` = None.

**Expected headline (Q8).** 0 / 0 / 100 — no `terminal`, no `terminal_other_layer`, all disclosure-dependent. Printed as the archetype's finding, not as a defect.

**Disclosure overdue (Q11).** Memo #1 §4.6(iii) unchanged. New: a `recurses` node whose `last_disclosure_date` is older than **2× its `disclosure_cadence`** fires Level 1 "disclosure overdue" (A-28, T-29, owner DET-18).

### 4.5 Look-through table (archetype #2)

Disclosure-category nodes (tree weight):

| Node | Keyed by | Label | Recurses into | Staleness source |
|---|---|---|---|---|
| Crypto Basis | category + attestation ref (Q2) | `recurses` | custodian attestation + weekly PoR | days since the newer of the two [ANALYST-SUPPLIED 2026-10-25: attestation as-of 2026-09-27, monthly (twenty-second monthly report, published 2026-10-10); September attestation post; as-of 2026-09-27] [FIRST-RUN READ: `/api/por` `lastUpdatedAt`] |
| Equity and RWA Basis | category + attestation ref | `recurses` | custodian attestation + weekly PoR | as Crypto Basis |
| Institutional Lending | category + attestation ref | `recurses` | custodian attestation (monthly confirmation; per-run values D14) | attestation as-of [ANALYST-SUPPLIED 2026-10-25: as-of 2026-09-27, monthly; September attestation post; as-of 2026-09-27] |
| Liquid Stables | category + attestation ref | `recurses` | each listed issuer's attestation | worst issuer cadence among its listed assets (label rows below) |
| DeFi Lending | category + attestation ref | `recurses_truncated` — reason "lending positions; underlying stables not attributed by the disclosure" | the lending positions — not analyzed | the attestation [ANALYST-SUPPLIED 2026-10-25: as-of 2026-09-27, monthly; September attestation post; as-of 2026-09-27]; the Q4(ii) wallet reads are disclosed beside it and do not relabel the category |
| RWA | category + attestation ref | `recurses_truncated` | memo #1 §4.5 tokenized-fund row (the fund's off-chain holdings, not analyzed) | NAV cadence per fund [ANALYST-SUPPLIED 2026-10-25: JAAA `nav_schedule`, heartbeat 86,436 s observed (GHO sheet JAAA oracle row, B-9 read; as-of 2026-09-13); STAC (Securitize Tokenized AAA CLO Fund, BNY custody) continuous on-chain holdings and NAV/pricing verification by Chronicle since 2026-02-05, formal NAV publication cadence not located in public materials; https://securitize.io/stac, Securitize/Chronicle announcement 2026-02-05, STAC launch announcement 2025-10-29; as-of 2026-10-25] |

Label rows (zero tree weight; D18 — every asset the route lists under Liquid Stables and DeFi Lending; an asset without a row is unlisted at its weight, memo #1 §8.2):

| Asset | Label | Recurses into | Staleness source |
|---|---|---|---|
| USDT; USDT0 (as USDT) | `recurses` | memo #1 §4.5 USDT row — Tether | [ANALYST-SUPPLIED 2026-10-25: quarterly BDO attestation, most recent reserves report as of 2026-06-30; https://tether.to/en/transparency/; as-of 2026-06-30] |
| USDC | `recurses` | memo #1 §4.5 USDC row — Circle | [ANALYST-SUPPLIED 2026-10-25: monthly, USDC Reserve Report as of 11 and 31 August 2026, Deloitte & Touche LLP (AICPA), issued 2026-09-29; https://www.circle.com/transparency; as-of 2026-08-31] |
| PYUSD | `recurses` | memo #1 §4.5 pyUSD row — Paxos | [ANALYST-SUPPLIED 2026-10-25: monthly, as of 17 and 30 September 2026, KPMG LLP New York (AICPA), issued 2026-10-23, issuer Paxos Trust Company NA (OCC); https://paxos.com/pyusd-transparency/; as-of 2026-09-30] |
| **USDtb — new row** | `recurses` | USDtb issuer reserve attestation — Anchorage Digital Bank NA | [ANALYST-SUPPLIED 2026-10-25: monthly reserve attestation, Deloitte & Touche LLP (AICPA), issuer Anchorage Digital Bank NA; latest as of 2026-08-31 (signed 2026-09-28), 529,269,213 redeemable tokens against $530,419,653 reserves (cash + BUIDL in segregated accounts); https://anchorage.com/platform/usdtb-reserve-attestations; as-of 2026-08-31] |
| **USDG — new row (D18)** | `recurses` | Paxos | [ANALYST-SUPPLIED 2026-10-25: monthly, as of 17 and 30 September 2026, KPMG LLP Singapore (SSAE 3000), issued 2026-10-23, issuers Paxos Digital Singapore (MAS) and Paxos Issuance Europe (FIN-FSA); https://paxos.com/usdg-transparency; as-of 2026-09-30] |
| **RLUSD — new row (D18)** | `recurses` | Ripple | [ANALYST-SUPPLIED 2026-10-25: monthly, "RLUSD Reserve Report August 2026" as of 17 and 31 August 2026, Deloitte & Touche LLP (AICPA), issued 2026-09-29, issuer Standard Custody & Trust Company (NYDFS); https://ripple.com/products/stablecoin/transparency/; as-of 2026-08-31] |
| **sGHO — new row (D18)** | transparent wrapper on GHO (memo #1 §4.3) | GHO → memo #1 §4.1 analyzed-set link (GHO's last published tree) | inherited |
| **Legacy FRAX 0x853d… (paired asset) — new row (Q41, RULED)** | `recurses` | Frax disclosure — none published, dated absence | [ANALYST-SUPPLIED 2026-10-25: no dedicated reserve balance sheet or transparency page located for legacy FRAX 0x853d955acef822db058eb8505911ed77f175b99e; Frax's transparency material describes frxUSD; FIP-430 (2025-04-21) established separate balance sheets and ended the guaranteed 1:1 LFRAX to frxUSD migration; the absence of a report does not establish that legacy FRAX is unbacked; pages checked: Frax Transparency page, frax.com frxUSD page, Frax docs "What is frxUSD?", "Protocol overview", "Token addresses", Frax governance FIP-430; as-of 2026-10-25]; unit-priced with the numeraire, par-eligible |
| Unlisted category or asset | **quarantine** (memo #1 §8.2) — never "other" | — | — |

## §5. Pool selection and exit liquidity

Memo #1 §5 applies whole: venue scope, chain scope, paired-asset labeling, exclusions, coverage K, frozen set and detector, sensitivity, depth metric (Q18). Three deltas:
1. **Exclusion class added to memo #1 §5.4:** pools paired with the token's own staking wrapper (sUSDe) are excluded as `self_referential_wrapper` [FIRST-RUN READ: discovery — none exist at 2026-10-24, Inventory G G7].
2. **No Member 2 in this family:** `member2_target` = None; the set file records "no Member 2 in this family".
3. **Off-venue share** disclosed per memo #1 §5.1 [FIRST-RUN READ: DET-32 — 22.1% at 2026-10-24, Inventory G G7]; T-02 is not expected below 25%.
Exit depth (memo #1 §6.1, s = 2%, existing solver) enters stress row 3 only; DET-30's K rows (memo #1 §5.7) attach to S3 (D2).

## §6. Stress scenario family — synthetic

Memo #1 §6.3's design rule applies: mechanism-behavior uncertainty is a counterfactual line, never a cell. Memo #1 §6.2.1 (shock grid) and §6.2.2 (LST axis) do not apply (Q43). Stress is not comparable with archetype #1 (brief §11.7).

| Row | Scenario → mechanism | Cells | Headline cell | Counterfactual line |
|---|---|---|---|---|
| 1 Funding reversal (Q15) | The hedge earns funding; a sustained negative rate is the loss that fits a basis book. Loss = (Crypto Basis + Equity and RWA Basis) × F × N/365, F = −25% annualised, fixed; the reserve fund absorbs first (§3). Reference point beside F: the minimum of the quarterly average funding series from `/api/funding/quarterly` (D19) [FIRST-RUN READ: series minimum and its quarter], printed with "no negative quarter observed" while none is; the page carries one sentence, "F = −25% has no analogue in the issuer's own record" (F3) | N ∈ {30, 90, 180} — 3 | post-loss backing ratio at N = 90 | issuer unwinds the basis at day 0; loss bounded by execution cost, unquantified |
| 2 Venue loss (Q16, D16) | Backing sits at named custodians and venues; losing one is the failure custody concentration implies. Both legs from the backing-assets route per run [FIRST-RUN READ: per-location and per-exchange values]: (a) the largest location total across all strategies lost in full (F2); (b) the largest exchange's hedge fails, its notional unhedged at −30%; the reserve fund absorbs first in both legs (§3) | (a), (b) — 2 | the lower post-loss backing ratio; the other printed beside it | — |
| 3 Redemptions (Q17, D2) | Redemption is whitelisted and rate-capped; a run tests the liquid buffer and the exit pools together. Exit X = 25% of mainnet free float (`totalSupply` − staked − silo − OFT escrow) in 7 days, plus 25% of staked supply when `cooldownDuration()` < 7 d; the escrow excluded with memo #1 §5.2's sentence. `capacity_redeem` = min(Σ `/api/stablecoin-collateral`, `globalMaxRedeemPerBlock` × blocks in 7 days) (F1); V2's own balances check that sum (§2 (iii)), never add to it | 1 | depeg-pressure ratio = max(0, X − `capacity_redeem`) ÷ exit depth at s = 2% (memo #1 §6.2.7 metric 3) | the cooldown branch not taken by the read |

**Post-loss backing (rows 1 and 2, D3)** = backing − max(0, loss − reserve fund); **post-loss backing ratio** = post-loss backing ÷ `supply_ruled`. Row 3 has no loss; the reserve fund is not capacity there.

The Coinbase-labeled wallets (§14) are not a route `location`, and their key custody is undisclosed (F2; §11 item 4).

Cells: 3 + 2 + 1 = **6 per run**. No LP-flight axis, no joint cell (Q17). Inputs read per run: [FIRST-RUN READ: category amounts; `totalSupply`; `USDe.balanceOf(sUSDe)`, `USDe.balanceOf(silo)`, `USDe.balanceOf(OFT adapter)`; `cooldownDuration()`; `globalMaxRedeemPerBlock`; V2 balances; reserve-fund balances; Curve exit depth].

**Bias table (Q19; `bias_table[]`).**

| Mechanism | Row | Direction | Reason |
|---|---|---|---|
| Liquid buffer treated as instantly available | 3 | overstates | the full category is redeemable within the window |
| No issuer top-up of the buffer | 3 | understates | no rebalancing from the basis book during the run |
| Funding reversal | 1 | n/a | a loss over a stated horizon, not a stock-only capacity |
| Venue loss | 2 | n/a | a balance-sheet write-down, not a stock-only capacity |

Memo #1's four ★ rows (DET-53) are archetype-#1 literals and are not required on this archetype's sheet (Q19, Q28), pending A-32 (DET-53 scope) (D10).

## §7. Timing and observation assumptions

**Shock window.** Stock-only, memo #1 §7.1 by reference; the per-row direction of error is the §6 bias table.

**Observation — attested value.** A disclosure-category node is observed at its attested value as of its disclosure's as-of date and held there until the next disclosure; no on-chain feed tracks it (Q10, `assumption_applied` = `attested_value`). Its age is the staleness printed under memo #1 §4.6(iii) and bounded by §4 (Q11).

### 7.3 Scope-outs (P-10.04)

- **Oracle manipulation:** out of scope — no oracle prices the backing; the disclosure-category nodes carry attested values (§7, Q10).
- **sUSDe yield:** out of scope (Q7).
- **Other-chain positions:** disclosed as "balance not read by this pipeline (other chain)", not read (§2, D17).
- **Sequencer / infra risk:** n/a — mainnet only (memo #1 §5.2).

## §8. Quarantine bounds

Memo #1 §8.1 (three-level ladder, per-token scope, stale-page behavior, resolution protocol, validate-before-routing) and §8.2 (unlisted node, 5%) apply unchanged. Archetype-#2 instances of §8.1.4 (Q22):
- (a) Category share shift > 10pp, or a top-3 change — Level 1.
- (b) Supply jump > 25%, two-branch — DefiLlama + Blockscout legs; confirms → Level 1, disagrees → Level 3.
- (c) Custodian or exchange count change in the attestation — addition Level 1, removal Level 2 (the market-count rows, D5).
- (d) Near bound — backing ratio < 101% or reserve fund < 0.5% of supply — Level 1 (T-07, D5).

**Scraped sources (Q29).** Outage or shape change on any Ethena endpoint = harness error ⇒ DET-85, T-25, Level 2, this token only (P-3.43 reused).

| Trigger | T | Defined at | Level |
|---|---|---|---|
| Disclosure overdue — `recurses` node older than 2× cadence (A-28) | T-29 | §4 | 1 |
| Buffer reconciliation gap > 5% of backing (D5) | T-30 | §2 | 1 |
| Unlisted category or asset < 5% / ≥ 5% | T-01 / T-09 | memo #1 §8.2 | 1 / 2 |
| Category shift > 10pp or top-3 change | T-04 | §8 (a) | 1 |
| Supply jump > 25%, cross-validation confirms / disagrees | T-05 / T-14 | §8 (b) | 1 / 3 |
| Custodian or exchange count — addition / removal | T-06 / T-12 | §8 (c) | 1 / 2 |
| Near bound | T-07 | §8 (d) | 1 |
| Off-venue share > 25% | T-02 | memo #1 §5.1 | 1 |
| Pool-set change ≥ 10% of coverage | T-10 | memo #1 §5.6 | 2 |
| Scraped-source outage or shape change | T-25 | §8 | 2 |
| Three-way discovery mismatch > 5% | T-13 | memo #1 §5.5 | 3 |

## §9. Encoded hard gates (this archetype)

Memo #1 §9 applies in full where its object exists. Three additions:
- **Address-gate exception (Q2):** custody and basis sleeves are keyed by disclosure category plus attestation reference; every on-chain node stays keyed by address.
- **Disclosure pin (Q27):** every disclosure-derived value carries a `DisclosureSnapshot` provenance {`source_url`, `as_of_date`, `published_date`, `sha256`, `fetched_at`}; the page prints as-of and fetch time.
- **Snapshot commit (Q42):** the per-run disclosure set is committed at `out/disclosures/USDe/<run_block>.json`; `raw_positions_hash` = its sha256; the verify page reads "re-fetchable from the committed snapshot".

## §11. Open points (this memo)

1. **Funding reference point — CLOSED (D19).** The worst quarterly average funding from `/api/funding/quarterly`, printed beside F (§6 row 1).
2. **Equity-basis venues.** The venues behind Equity and RWA Basis are not named in the disclosure; their custodian treatment follows the attestation.
3. **GHO's sUSDe node (Q37).** After USDe's first published tree, one `labels.toml` row switches GHO's sUSDe node to the analyzed-set link (memo #1 §4.1), effective at GHO's next monthly run.
4. **Custody of the Coinbase-labeled wallets (F2).** The wallets are not a route `location`; who holds their keys is undisclosed, so stress row 2's leg (a) cannot select them.

## §12. Redemption-rights fields

Memo #1 §12 applies (N paths, R1–R10, R8 computed). Instance, one path (Q30): R1 `module_on_chain` · R2 `whitelisted` · R3 the supported assets [FIRST-RUN READ: V2 supported-asset set] · R4 `face_value` · R5 `none` · R6 `capacity_limited` + `pausable` · R7 `globalMaxRedeemPerBlock` and Σ `/api/stablecoin-collateral` [FIRST-RUN READ: both] (F1) · R8 computed, unchanged · R9 `disclaimed` [ANALYST-SUPPLIED 2026-10-25: USDe Terms and Conditions (general, last updated August 2025) §2 "you may only utilize accepted assets to create USDe and redeem USDe directly with Ethena BVI to the extent that you are a Mint User"; §11 "Only Mint Users can redeem USDe directly with Ethena BVI"; Mint User Agreement §1, whitelisted wallet and KYC/KYB screening; docs.ethena.fi terms pages; as-of 2026-10-25] · R10 EthenaMinting V2 `redeem`. **R2 beside R8 (D7):** the page prints R2 beside R8; wording owns one sentence, "redeemable by approved counterparties only".

## §13. Admin-power surface

Memo #1 §13 applies: nine-value enum unchanged, A1–A8, delay buckets, token-level qualifier. Archetype deltas:
- **Qualifying set (Q12).** Adds `set_parameters` where its scope includes the custodian-address list or `COLLATERAL_MANAGER_ROLE` — the powers that move backing between custody and chain. The banner shows it.
- **Off-chain discretion (Q13).** Not a power row. §14 and one banner sentence: "backing held by [n] custodians under issuer discretion; on-chain keys shown below". *Rejected:* a tenth enum value.
- **Live model inputs** (memo #1 §13 pattern, third and fourth members): `cooldownDuration()` (`set_parameters` row) selects the row-3 branch; `globalMaxRedeemPerBlock` (`set_ceiling` row) bounds row-3 capacity.
- **Signers (Q14).** Safe `getOwners` / `getThreshold` per holder; identity undisclosed unless published; the fully restricted sUSDe addresses are one count line [FIRST-RUN READ: count].

## §14. Audit status and counterparty enumeration

**Audit status.** Memo #1 §14 form, analyst-keyed on the sheet [ANALYST-SUPPLIED 2026-10-25: twelve audits keyed on the USDe sheet (Zellic, Quantstamp, Spearbit, Pashov, Code4rena, Cyfrin, Chaos Labs; latest V2-contract audit Pashov 2024-05-23), page last updated about a year ago, https://docs.ethena.fi/resources/audits; bug bounty Immunefi, maximum $3,000,000, live since 2024-04-04, last updated 2026-08-11, https://immunefi.com/bug-bounty/ethena/information/; as-of 2026-10-25]; last material change audited: yes [ANALYST-SUPPLIED 2026-10-25: recorded reading — StakedUSDeV2 deployed 2023-11-14 inside the v1 audit series; EthenaMinting V2 deployed 2024-06-21, 29 days after Pashov's V2 review of 2024-05-23; byte-identity against the reviewed commit not performed; audits page; creation txs; as-of 2026-10-25].

**Counterparty enumeration (Q26, D6) — filled.** Seven entries: Copper, Ceffu, Anchorage Digital, Kraken Custody, FalconX SPV, Ripple Prime FCM, and **on-chain wallets, Coinbase-labeled** (the Q4(ii) list's source); plus the institutional-lending and basis-venue counterparties the attestation names; each with its share [ANALYST-SUPPLIED 2026-10-25: letter values — Copper Markets (Switzerland) AG $668,759,532.90 incl. unrealised P&L; Ceffu Digital Pte. Ltd. ≥ $733,212,922.85 (post headline $0.675bn); Anchorage Digital Bank NA $576,576,634 held + $81,000,000 USDC/USDT loaned under a secured lending arrangement against $145,541,292 BTC in tri-party custody (post headline $0.657bn); Kraken Financial $41,690.76; Ethena x FalconX SPV collateral $393,803,618.69 (Anchorage $137,516,667, BitGo $181,930,552, Payward/Kraken $74,408,775.45) against loans of $236,644,959.12; Ripple Prime FCM account equity $7,934,609.93; Coinbase on-chain wallets $2.620bn; MintRedeem contract $89.230m; total backing $4.953bn; reserve fund $62.095m; 101.34% incl. reserve fund; USDe supply 4.949bn; September attestation post and its custodian letters, https://ethena.fi/blog/custodian-attestations-of-assets-backing-usde-september-3; as-of 2026-09-27]. Per-run shares come from the backing-assets route (D15); the letters are the monthly confirmation. DET-73's "n/a — archetype #1" literal is scoped to archetype-#1 sheets (A-30).
