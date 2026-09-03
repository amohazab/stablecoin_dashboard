# Archetype Memo #1 — CDP / On-Chain-Backed Stablecoins
 
**Phase A CLOSED — 2026-09-01.** Design complete; implementer test passed.
**Phase B COMPLETE — 2026-09-02.** 18 analyst-supplied values with staleness dates (FIX 2026-09-02: header previously read 19; one entry — frxUSD keeper paired-asset labeling — was re-scoped to intake under P4 after the count was taken); 2 contradictions resolved by ruling (H1, H2); 6 candidate points dispositioned. Design verified; code pending.
**Applies to:** crvUSD, GHO, LUSD (pilot set). Archetype membership is decided at the intake gate; a token whose intake sheet cannot be filled under these rulings belongs to a different archetype.
**Conventions:** `[VERIFIED <date>: …]` = fact verified in Phase B, source inline. `[FIRST-RUN READ: …]` = live-state quantity read per run by the adapter — an input, not an assumption. `[ANALYST-SUPPLIED <date>: …]` = staleness-tracked analyst input per the graceful-degradation rule. `[RE-SCOPED TO INTAKE: …]` = resolved at intake/freeze time. Mechanism logic carries no marker. Rulings are the analyst's; this memo records them once and code enforces them per run.
 
---
 
## §1. Archetype definition and scope
 
**Definition.** A CDP / on-chain-backed stablecoin is one whose supply originates from **on-chain collateral pledged by third parties**, held in protocol contracts, with an **on-chain liquidation path** that converts that collateral into the stablecoin or its repayment when the position deteriorates. The backing is readable at a block; the claim against it is enforced by code.
 
**Fit test (applied at intake).** *Supply originates from on-chain collateral pledged by third parties with an on-chain liquidation path; any supply that does not is classified under §3 (stabilizer debt) or excluded from the archetype.* A token passes if the intake sheet's collateral-node table can be filled from contract reads, its redemption-rights block (§12) can be filled from contract functions or the absence thereof, and its stress hooks (§6.3) map onto the CDP family. A token whose sheet **cannot be filled under these rulings belongs elsewhere** — possibly to a new archetype. That is the intake gate working as designed.
 
**Boundaries.**
- *Against the synthetic archetype (off-chain-hedged):* backing consists of on-chain collateral plus off-exchange hedges whose value depends on custodian and venue disclosures; the liquidation path is a hedging desk, not a contract. Such a token fails the fit test at "on-chain liquidation path."
- *Against the fiat archetype (issuer-held reserves):* backing is held by an issuer in bank and treasury assets; the claim is legal, not mechanical; verification is attestation-only. Such a token fails at "on-chain collateral pledged by third parties."
- *Hybrids:* a token with a CDP core plus a material off-chain sleeve is routed by the sleeve's weight — the §8.2 unlisted-node rule fires on any node the §4 table cannot label, which is what forces the archetype question at intake rather than at runtime.
**Pilot set.** crvUSD (LLAMMA controllers; PegKeeper stabilizer debt under §3), GHO (Aave V3 facilitator with shared-pool attribution under §11.1; GSM asset-in-a-box under §3 exclusion), LUSD (Liquity v1 troves; the simplicity control — if the schema is awkward for LUSD, the schema is wrong).
 
**Sub-mechanisms accommodated without leaving the archetype:** protocol stabilizer debt (§3, zero-credited); asset-in-a-box swap modules (§3 exclusion, §5.10 venue); facilitator-style minting against a shared collateral pool (§11.1 attribution). Each is a bounded modification captured on the intake sheet, not a new archetype.
 
## §2. Definition of backing
 
Backing is defined by **contract address, never symbol**. A unit of supply is backed to the extent that a third-party claim exists against it: collateral pledged by a borrower with a liquidation path, or a third-party asset held outright 1:1 by a swap module. Supply that has neither is not backed, whatever asset the protocol happens to hold against it (see §3).
 
Principal and accrued interest are separated in all debt reads. Supply origination (new units minted against collateral) is distinguished from re-lending of existing units (see §9, hard gates).
 
**The token never counts as its own backing.** Where no third-party claim exists (stabilizer LP positions, §3) the token's own leg is worth zero. Where a third-party claim *does* exist — a borrower position that holds the stablecoin after soft liquidation — the held stablecoin is **netted against that position's debt**: the borrower owes the debt, and stablecoin sitting in the position is functionally pre-repayment. Netting is correct; zeroing would show a fully soft-liquidated, fully solvent position as 0% collateralized; counting it as collateral would be circular. Hard gate in §9.
 
## §3. Stabilizer-minted supply — classification and class rule
 
**Ruling.** Stablecoin supply created by protocol-owned market operations against no third-party collateral is credited at **zero backing** in the headline supply decomposition and reported as a labeled slice: **"protocol stabilizer debt."**
 
**Rationale.** The only asset behind such supply is a protocol-owned position in a liquidity pool. That position fails the definition of backing on two grounds. (a) *No third-party claim:* no borrower owes the debt, no collateral is pledged against it, and no liquidation path exists — the protocol holds a position, not a claim. (b) *Pro-cyclical value:* the position's only non-self-referential content is the paired external asset, which is exactly the asset that exits the pool first in a confidence crisis. An asset with no enforcement path whose value shrinks under the scenario the stress model exists to capture is not backing. It is credited at zero and disclosed in full.
 
**Class rule (archetype-wide, protocol-agnostic).** Protocol-owned market operations that mint the stablecoin against no third-party collateral are credited at zero backing and reported as a labeled slice with: debt ceiling, current utilization, and net non-self-referential position value (the stablecoin's own leg netted out). Expected members: Curve PegKeepers (crvUSD); Frax AMO-style operations [ANALYST-SUPPLIED 2026-09-01: frxUSD not in pilot; note that frxUSD IS a live crvUSD PegKeeper paired asset (docs deployments) and needs a §4 row as a paired asset — candidate open point].
 
**Exclusion — asset-in-a-box modules.** 1:1 swap modules that hold a third-party asset against each unit minted (GHO GSM, PSM-style modules) are **not** in this class. There is no circularity (the boxed asset is not the stablecoin) and no third-party-claim gap (the boxed asset is held outright). They are backed by the boxed asset, subject to the look-through table (§4).
 
**Sub-decisions, fixed.**
 
a. *Netting — hard gate.* The stablecoin's own leg of any stabilizer LP position never counts as backing or as value. Listed with the encoded failure lessons (§9).
b. *Exit-liquidity allocation.* None required. Because stabilizer debt is credited at zero, all non-stablecoin liquidity in stabilizer pools is exit depth in the stress model. This removes the backing-vs-exit-depth double-counting trap by construction rather than by allocation rule. Stabilizer debt is likewise **excluded from forced-sell volume** (§6.2.7) in every cell: it sits inside the protocol's LP position, not in holders' wallets, and is not sellable by anyone.
c. *Ceilings.* Per-operation debt ceilings and their aggregate are Tier-1 parameters, reported as the upper bound of the stabilizer-debt slice.
d. *Valuation.* Backing is zero at spot and zero under stress; no stressed valuation applies. The disclosed net position value is reported at spot only, captioned "pro-cyclical, non-credited."
e. *Placement.* Classification and class rule live here (memo, class level). Token intake sheets instantiate them with specific contracts, paired pools, and ceilings.
 
**Disclosure fields (adapter output, per stabilizer operation).**
 
- operation contract address; paired pool address; paired asset address
- debt ceiling; current debt; utilization (debt / ceiling)
- protocol LP share of pool; pool composition at block
- net non-self-referential value = paired-asset leg attributable to the protocol's LP share, valued via look-through (§4) — reported, not credited
- residual = LP position value − debt (accrued stabilizer P&L; informational)
- provenance: source, block, timestamp
**Stress-model treatment.** Stabilizer operations enter the CDP stress family (§6) as a flow mechanic, not a balance-sheet item, on two paths modeled separately:
 
- *Collateral-crash path:* liquidation converts collateral into stablecoin → stablecoin demand rises → price above peg → stabilizer mints. The stabilizer-debt slice grows during the crash; its trajectory toward the ceiling is reported.
- *Confidence-crisis path:* stablecoin below peg → holders exit through pools → external legs drain → stabilizer withdraws and burns. Stabilizing at the margin; burn capacity = outstanding debt, not ceiling. Pool drain is modeled against external selling pressure.
Note: the design-paper "self-unwinding via borrow-rate response" channel is [VERIFIED 2026-09-01: confirmed in code and news: AggMonetaryPolicy4 introduces an EMA of the PegKeeper debt ratio (debt_ratio_ema_time, settable) into the rate formula; Curve News 'Inside crvUSD Borrow Rate' (Dec 2025) and Jan 2026 rate changes — unwind channel smoothed; supports zero-credit].
 
## §4. Look-through policy
 
The verifiability decomposition is a weighted tree over collateral nodes. Each node answers one question: *can the value behind this node be checked on-chain in real time, or does it depend on an off-chain disclosure at some staleness?* The tree measures **checkability, not quality**. A volatile governance token held as collateral is fully verifiable and fully volatile; volatility is the concern of the stress model (§6) and the structural grade, not of this tree.
 
### 4.1 Depth policy — one hop, fixed terminals, truncation labeled
 
Recursion stops after one hop regardless of what lies beneath. Where the node reached is itself partly disclosure-dependent (e.g., DAI/USDS → Sky reserves), the tree does not pretend the node is terminal: it carries the label `recurses_truncated`, the exposure weight behind the truncation, and the reason ("depth truncated at [node]; node's own backing not analyzed by this pipeline").
 
*Rejected — full recursion:* would require a reserve-composition adapter for every stablecoin that appears as collateral; scope creep with no Step-5 requirement behind it.
*Rejected — recursion with decay:* there is no observable to calibrate a decay factor against; it fails the evaluator's "traceable to a data field" criterion.
 
*Analyzed-set tokens as nodes or paired assets — linked, not re-analyzed.* When a node or a paired asset (§5.3) is itself a token analyzed by this pipeline, it inherits that token's label distribution pro-rata from the token's **last published tree** — not the current run's, which avoids intra-run ordering dependency and survives the other token being quarantined this run. If no published tree exists yet (first runs), it is treated as `recurses_truncated` with reason "analyzed token, tree pending" and flagged (§8.1 Level 1). When a currently truncated node's token later enters the analyzed set (e.g., DAI/USDS), the same rule links it in — a config change, not a policy change. *Rejected:* `terminal` by fiat for analyzed tokens — false for any analyzed token with disclosure-dependent backing.
 
### 4.2 Label scheme — four states, exhaustive
 
| Label | Definition |
|---|---|
| `terminal` | Value verifiable on-chain by this pipeline, in real time. |
| `terminal_other_layer` | Value verifiable in principle on a layer this pipeline does not read (consensus layer, another chain). No recursion, no staleness, no attestation; the tree states that the pipeline did not itself verify the underlying balances. |
| `recurses` | Value depends on an off-chain disclosure. Source and staleness are recorded. |
| `recurses_truncated` | One hop taken; the node reached is itself partly disclosure-dependent; depth cut. Exposure weight and reason recorded. |
 
There is no fifth state and no "other." An asset that fits none of these is an unlisted node and triggers the quarantine rule (§8.2).
 
### 4.3 Transparent-wrapper rule
 
A wrapper passes through to its underlying without consuming a level if it is **redeemable 1:1 for the underlying by anyone, on-chain, with no counterparty and no notice period.** Passes: WETH → ETH; aTokens → underlying; wstETH ↔ stETH unwrap; sDAI/sUSDS → DAI/USDS. Fails: WBTC and any custodial wrapper.
 
Edge case: aToken pass-through assumes withdrawable liquidity; at 100% pool utilization, redemption queues. This is a stress-model concern (exit timing), not a verifiability concern — the claim is still on-chain and enforceable.
 
**Composite pass-through.** An LP token of a pool whose constituents are *all* §4-labeled passes through pro-rata to those constituents at the pool's current composition (a data field read at the run's block), each constituent keeping its own label. Example: 3CRV → DAI/USDS (`recurses_truncated`) + USDC (`recurses`) + USDT (`recurses`), weighted by basepool balances [VERIFIED 2026-09-01: basepool composition readable directly from the 3pool contract balances(i) — no metaregistry dependency needed]. Guard: if any constituent is unlisted, the LP token is unlisted (§8.2). Member 2 consequence: the shocked-stable share of a composite paired asset is shocked. *Rejected:* labeling the LP token `recurses_truncated` — discards composition data that is on-chain readable.
 
### 4.4 Verifiability boundary — hard cases
 
- **Liquid staking tokens (wstETH, rETH, sfrxETH):** `terminal_other_layer`. Value is verifiable via consensus-layer validator balances, which this pipeline's execution-layer adapter does not read.
- **WBTC and custodial-wrapped assets:** `recurses` → custodian attestation. The custodian's published reserve-address list is a disclosure; value verification depends on trusting it before any chain can be read. Consistent with §3's principle (disclosure-dependent → say so) and avoids a single-asset category. Staleness source: custodian proof-of-reserve cadence.
- **tBTC:** deferred pending [VERIFIED 2026-09-01: tBTC: Threshold signer set, permissionless redemption (eco.com 2026-05; TokenBrice). Live crvUSD mint-market collateral: YES (Curve News wk32 2026: tBTC borrow +$1.33M). Reserve locatability without disclosure: tBTC v2 wallet registry is on-chain — [FIRST-RUN READ: WalletRegistry read to confirm before applying branch 1 (terminal_other_layer)] — label applied provisionally as branch 1 per §4.4]. If confirmed threshold-controlled with reserves locatable on-chain without any disclosure: `terminal_other_layer` (Bitcoin chain). If any custodian or committee disclosure is required to locate reserves: `recurses`, as WBTC.
- **Liquid restaking tokens (weETH, rsETH, ezETH, osETH, ETHx, tETH):** `terminal_other_layer` — LRT family row (ruled 2026-09-02, P1/P2). Value verifiable via consensus-layer and EigenLayer/restaking contracts; not read by this pipeline. **cbETH:** validator set not published → `recurses` (Coinbase disclosure) [RE-SCOPED TO INTAKE: cbETH attestation cadence]. **cbBTC and other custodial BTC wrappers (LBTC, eBTC, FBTC, BTCb):** `recurses` → custodian attestation, as WBTC (ruled 2026-09-02, P1) [RE-SCOPED TO INTAKE: cadence per custodian].
### 4.5 Look-through table (pilot set)
 
*Phase-B sens. (historical)* column: **L** = a Phase-B finding could have flipped the label; **P** = could have removed/added the row (presence) but not changed the label; **–** = stable. Phase B checked **L** rows first. Retained as record.
 
| Collateral node | Held by | Label | Recurses into | Staleness source | Phase-B sens. (historical) |
|---|---|---|---|---|---|
| ETH (native) | LUSD; crvUSD via WETH; GHO via aWETH | `terminal` | — | — | – |
| WETH | crvUSD, GHO | transparent → ETH | — | — | – |
| wstETH / rETH / sfrxETH | crvUSD, GHO | `terminal_other_layer` | — | — | – |
| WBTC | crvUSD, GHO | `recurses` | custodian PoR + address disclosure [VERIFIED 2026-09-01: since 2026-05-01 BiT Global Trust (HK) is custodian holding 2 of 3 keys (HK, SG); BitGo (US) holds 1 key + infrastructure. PoR: wbtc.network continuous dashboard; Chainlink WBTC PoR feed ~10-min checks, 1% deviation (Spark, secondary). Source: WBTC Network Medium 2026-03-02] | custodian PoR cadence [FIRST-RUN READ: live value] | **L** (custodian structure) |
| tBTC | crvUSD [VERIFIED 2026-09-01: yes — Curve News week 32, 2026] | **deferred** — both branches recorded (§4.4) | — | — | **L** |
| USDC | GHO (GSM, aUSDC); PegKeeper pools (disclosure only) | `recurses` | Circle attestation | monthly [VERIFIED 2026-09-01: USDC monthly (Deloitte; one secondary source says Grant Thornton — conflict recorded, cadence agreed). Sources: eco.com/Spark/stablecoininsider 2026] | – |
| USDT | GHO (aUSDT); PegKeeper pools (disclosure only) | `recurses` | Tether attestation | quarterly [FIRST-RUN READ: live value] | – |
| pyUSD | PegKeeper pool [FIRST-RUN READ: attribution] | `recurses` | Paxos attestation | monthly [FIRST-RUN READ: live value] | P |
| DAI / USDS (incl. sDAI/sUSDS via 4.3) | GHO (aDAI/aUSDS) [VERIFIED 2026-09-01: DAI, sDAI, USDS all enabled reserves (bgd-labs/aave-address-book main (GhoEthereum.sol, AaveV3Ethereum.sol, GovernanceV3Ethereum.sol)); attributed weight [FIRST-RUN READ: attribution]] | `recurses_truncated` | Sky reserves — not analyzed | on-chain readable; RWA leg attested [ANALYST-SUPPLIED 2026-09-01: Sky reserves ≈ USDC-via-LitePSM + RWA; note only, not analyzed] | P |
| aTokens (any) | GHO | transparent → underlying | — | — | – |
| Governance / volatile tokens (CRV, AAVE, LINK) | GHO (Aave); crvUSD only if a *mint* market accepts them [VERIFIED 2026-09-01: no governance-token mint markets; lend markets excluded] | `terminal` | — | — | P |
| weETH / LRT family (rsETH, ezETH, osETH, ETHx, tETH) | crvUSD (weETH mint market); GHO | `terminal_other_layer` (ruled 2026-09-02) | — | — | – |
| cbETH | GHO | `recurses` (ruled 2026-09-02) | Coinbase disclosure | [RE-SCOPED TO INTAKE: cadence] | – |
| cbBTC (and LBTC / eBTC / FBTC / BTCb as custodial BTC wrappers) | crvUSD (cbBTC mint market — largest borrow flow, Curve News wk32 2026); GHO | `recurses` (ruled 2026-09-02, P1) | custodian PoR + attestation (Coinbase for cbBTC) | [RE-SCOPED TO INTAKE: cadence per custodian] | – |
| Basepool LP tokens (3CRV-type) as paired assets | LUSD, others via metapools | composite pass-through (§4.3) → constituents | — | per constituent | – |
| Analyzed-set tokens (crvUSD, GHO) as paired assets or nodes | GHO/crvUSD pools | linked to last published tree (§4.1); `recurses_truncated` + L1 until first publication | — | inherited | – |
| Unlisted node | any | **quarantine** (§8.2) — never "other" | — | — | — |
 
**Node enumeration scope (ruled 2026-09-02, P2).** For pooled-collateral facilitators (GHO on Aave), the reserve-node enumeration is the set of reserves with **non-zero attributed backing at pool-set freeze time** (§5.6), refreshed with the quarterly freeze. Between freezes, newcomers route via §8.2 as designed (≥ 5% Level 2, < 5% Level 1). A sheet's node list is a freeze-time artifact, not a static list.
 
### 4.6 Headline arithmetic
 
**(i) Denominators — two statements, never blended.** Headline verifiability percentages are computed over **backing value** — the tree's natural denominator ("what is the composition of what backs this?"). A separate headline line is computed over **supply**: "X% of supply is zero-credited stabilizer debt" (§3). Tree root: supply → [backed branch → nodes] + [stabilizer branch → zero]; percentages inside the backed branch are over backing value.
 
**(ii) Three-way headline.** `terminal_other_layer` is its own bar: (1) verified by this pipeline (`terminal`); (2) verifiable on another layer, not verified here (`terminal_other_layer`); (3) disclosure-dependent (`recurses` + `recurses_truncated`, with the truncated share flagged inside the bar). The label exists so the pipeline never claims verification it did not perform; folding it into (1) undoes that; folding it into (3) is false.
 
**(iii) Staleness summary.** Exposure-weighted **average** staleness across disclosure-dependent nodes is the summary figure, printed **with the worst node and its weight** beside it (e.g., "weighted staleness 21d; worst: WBTC PoR, 30d, 4% of backing"), and the per-node list in the table. Average alone drowns a small very stale slice; max alone lets a 1% slice set the headline; together they cannot mislead in either direction. `terminal_other_layer` nodes carry no staleness and are excluded from this figure.
 
## §5. Pool selection and exit liquidity
 
Exit liquidity is the set of pools through which holders can leave the stablecoin. The selection rule determines the exit-depth input to the stress model (§6); because the rule choice moves results, it is fixed here and its sensitivity is measured on every run.
 
### 5.1 Venue scope — Curve stableswap only, with detection guard
 
Modeled venues are Curve stableswap pools on Ethereum mainnet. One depth model (the stableswap invariant) applies across the archetype; a second depth model would produce numbers that look comparable and are not.
 
*Guard:* discovery still enumerates off-Curve DEX liquidity (DefiLlama pools API [ANALYST-SUPPLIED 2026-09-01: DefiLlama pools API (yields.llama.fi/pools) — coverage of Balancer/Uniswap confirmed by product docs, not tested]); every report states "X% of discovered DEX liquidity lies outside modeled venues." This is a disclosure field, not an input to exit depth.
 
*Extension trigger:* if X exceeds 25% for any token, adding Uniswap v3 concentrated liquidity becomes a scoped config extension with its own depth definition, raised as an open point at that time. Not built now. *Pilot handling:* if the trigger fires on a pilot token (expected for GHO via Balancer), the report **publishes** with the off-venue share disclosed (§8.1 Level 1) and the extension is logged as a dated open point. Firing does not block publication during the pilot; the pilot proves the pipeline, and a second depth model is a post-launch extension.
 
*Rejected permanently:* aggregator quotes (1inch/0x at size) — third-party API in the Tier-1 path, not block-reproducible.
 
### 5.2 Chain scope — Ethereum mainnet only
 
Backing (controllers, facilitators, troves) is on mainnet; bridged supply exits on mainnet last and is bridge-latency-dependent. Disclosure field per report: bridged/L2 supply as a figure and % of total [VERIFIED 2026-09-01: GHO bridged-out = GHO balance of CCIP token pool 0x06179f7C1be40863405f374E7f5F8806c728660A; crvUSD bridges per docs deployments x-dao/crvusd-bridges; LUSD negligible].
 
### 5.3 Paired-asset treatment — label and disclose
 
The §4 look-through label is applied to the paired side of every modeled pool, and the report states the paired-asset concentration of exit depth (e.g., "82% of exit depth is paired with USDC — `recurses`, Circle"). Nothing is discounted at this stage. A correlated paired-stable depeg (March 2023 shape) is a candidate scenario in §6.
 
### 5.4 Exclusions
 
Excluded regardless of size: (i) non-market contracts (e.g., Liquity Stability Pool — liquidation capacity, not a market); (ii) pools whose paired asset is a **volatile** collateral node of the same token (e.g., crvUSD/wstETH, GHO/WETH-type) — circular under the collateral-crash path. Stablecoin collateral nodes (e.g., USDC for GHO) are **not** circular for this purpose: their failure is modeled under the paired-stable-depeg scenario (§6), not by exclusion. Included in full: PegKeeper/stabilizer pools (§3.b — the non-stablecoin leg is exit depth; the protocol's own LP share is not carved out).
 
### 5.5 Rule form — coverage threshold
 
The **frozen set** (§5.6) is built at freeze time to cover **K = 95%** of the token's total discovered on-Curve liquidity (after §5.4 exclusions), subject to a per-pool **dust floor of $500,000 TVL** — the widest K ever needed. The **headline** exit depth uses the **K = 90%** subset of the frozen set, re-ranked by TVL at the run's block, with K applied to the frozen set's own total (so K = 95% is always the full frozen set and always reachable).
 
*Denominator protection:* total discovered liquidity is established by three-way discovery — Curve metaregistry [ANALYST-SUPPLIED 2026-09-01: metaregistry address not surfaced; Curve deployments.json is the canonical registry export — use it + factory enumeration; basepool composition via pool.balances(i)] + DefiLlama pools API + a third source [ANALYST-SUPPLIED 2026-09-01: third source = on-chain factory enumeration (deterministic); Curve API as fallback]. Mismatch beyond 5% of total → discovery quarantine (§8.1 Level 3; run halts before analysis).
 
*Rationale — rule form:* the comparable spine spans tokens two orders of magnitude apart in liquidity. Top-N breaks exactly there; an absolute floor scales with pool size rather than token size. Coverage-K is self-scaling and its sensitivity is directly measurable. Explainability cost accepted: one sentence per report.
 
*Rationale — parameters:* the measured tail is 10% of the frozen set plus the disclosed ~5% of freeze-time liquidity left outside it; the unfrozen share is monitored by the §5.6 detector and disclosed per run. The $500k floor excludes dust without excluding any pool that could plausibly matter for LUSD-scale tokens [RE-SCOPED TO INTAKE: LUSD floor check at first discovery run — supply ≈ $27M (CoinGecko 2026); ≥ 2 pools ≥ $500k plausible, unconfirmed (checklist 4.9)].
 
### 5.6 Cadence and discovery — frozen set + detector
 
The modeled pool set is **frozen** and refreshed on a quarterly schedule or on a manual intake trigger. Per run: read the frozen pools' state; additionally run full discovery and a detector that flags (i) a new pool above the dust floor not in the frozen set, (ii) a frozen pool fallen below the floor, (iii) any frozen pool with TVL change > 50% since the last run.
 
*Semantic-quarantine link (§8.1):* a detected new pool that would represent ≥ 10% of coverage, or the disappearance of a frozen pool ≥ 10% of coverage, halts the run for template/intake review (§8.1 Level 2). The set is never silently updated.
 
*Rationale:* exit-depth figures must move for liquidity reasons, not list-membership reasons.
 
### 5.7 Sensitivity — automated, Tier-1, small
 
Every report carries a three-row sensitivity table: K = 80% / 90% / 95% → modeled exit depth → headline stress outcome, generated per run. Rows are produced by **re-ranking within the frozen set** (80 and 90 are subsets; 95 is the full set). No fresh discovery feeds the sidebar; the freeze is never violated. The report's exit-depth one-liner reads: *"modeled pools: the largest pools covering 90% of the frozen set, which itself covered 95% of discovered on-Curve liquidity at freeze time ([freeze date])."* A memo-level static sensitivity analysis is rejected: it goes stale, contradicts the factory principle, and invites "when was this last true?"
 
### 5.8 Depth metric
 
Discovery, coverage, and the dust floor are computed on raw TVL (what discovery can observe). Exit depth for the stress model is a price-impact measure, defined in §6.1.
 
### 5.9 Anticipated objections
 
*"Why Curve only?"* A single depth model within the archetype; the off-venue share is disclosed on every report; a 25% off-venue share triggers a scoped extension. Precision within the modeled venue is preferred over coverage with incomparable depth definitions.
 
*"Why 90%?"* The excluded tail is measured, not assumed, and the 80/90/95 sensitivity table on every report shows whether the choice matters for that token on that run.
 
*"Why freeze the set?"* So that a change in exit depth between runs is a liquidity event, not a list-membership event. Membership changes are reviewed, dated, and logged.
 
### 5.10 Deterministic exit venues (GSM-type addendum)
 
A 1:1 swap module holding a third-party asset (§3 exclusion class) is a **deterministic market** for the stablecoin: depth = boxed-asset balance, price = 1 − fee, no curve. Such a venue is included in exit depth at s = 2% **iff its fee < 2%** [VERIFIED 2026-09-01: 0.2% at launch (AIP-8, Jan 2024); current [FIRST-RUN READ: fee strategy] — inclusion condition (<2%) satisfied unless changed]; its contribution is the boxed balance, listed separately from pool depth in the report. Member 2 behavior — the venue holds the depegging asset and its freezer closes the valve — is specified in §6.3 (H2); when the freezer trips, this venue's contribution to exit depth is removed.
 
## §6. Stress scenario family — CDP
 
Family = correlated collateral crash × liquidation-capacity exhaustion (Member 1), plus a paired-stable depeg (Member 2). Structure: §6.1 depth metric → §6.2 family, grids, outputs → §6.3 token mechanism hooks → §7 timing and oracle assumptions.
 
### 6.1 Depth metric
 
**6.1.1 Definition and slippage bound.** Depth(s) = amount of the stablecoin sellable into the modeled pool set (§5) such that the marginal price does not fall below (1 − s). Every run computes and publishes the depth curve at s ∈ {0.5%, 1%, 2%, 5%}. The **s = 2%** value is the headline and the input to the stress model.
 
*Rationale:* 2% is the conventional depeg threshold and matches observed holder behavior — a stablecoin at 0.98 is universally treated as depegged. The published curve makes the choice disclosed and revisable without a re-run. Consistency with the behavioral tier's depeg thresholds is a deferred check (§11).
 
**6.1.2 Aggregation across pools.** Per-pool depths are summed at the same final marginal price. Given a common numeraire this is equivalent to optimal routing across pools, not an approximation. Paired-asset heterogeneity is handled by §5.3 disclosure; no further adjustment.
 
**6.1.3 Numeraire — par.** Paired assets are counted at 1.00 for depth measurement. Consistent with §5.3 (label, don't discount); using market prices would import a paired-stable depeg into the baseline depth, which belongs in the scenario, not the metric. Baselines clean; stress in stress.
 
**6.1.4 Static baseline, LP-flight modifier.** Headline exit depth is computed on each pool's current composition, with the assumption printed alongside: *"LP capital assumed sticky."* LP flight enters the stress family as a named scenario modifier with an **assumed haircut grid: 0% / 30% / 60%** of paired-asset liquidity withdrawn. These are disclosed scenario assumptions, not data-derived parameters; the report shows exit depth and the headline stress outcome at each level so the reader sees how much the result depends on LPs staying put.
 
*Modeling rule:* LP flight in a tilted stableswap pool is modeled as **single-sided withdrawal of the scarce (paired) asset**, not proportional withdrawal. Proportional withdrawal understates the damage.
 
*Calibration — future work (§11):* the haircut grid is a placeholder for a calibrated LP-flight haircut. The candidate observable is the ~985-day USDe on-chain calibration dataset, which contains real pool-tilt and LP-withdrawal episodes. That dataset is calibrated on a synthetic (off-chain-hedged) stablecoin; transfer to CDP-archetype pools requires a stated justification not yet available. Not a pilot dependency; the pilot ships on the assumed grid.
 
### 6.2 Scenario family
 
The CDP family has two members. Each opens, in the published report, with a scenario→mechanism rationale: why this shock is the one that fits this mechanism class.
 
**Member 1 — correlated collateral crash × liquidation-capacity exhaustion.**
**Member 2 — paired-stable depeg (no collateral crash).**
**Joint cell — one compound scenario, printed once.**
 
**6.2.1 Shock magnitude — fixed grid, disclosed reference point.** Volatile collateral nodes are shocked by a fixed grid: **−20% / −35% / −50% / −70%**, identical for every token and every run. Alongside each grid point, per volatile node, one historical reference point is printed: the node's worst 7-day drawdown within the pipeline's price-history window [ANALYST-SUPPLIED 2026-09-01: DefiLlama coins API as disclosure-only source; block-reproducible alternative = Chainlink round history (getRoundData) — implementer choice]. Reference points are context, never inputs; they do not alter the grid.
 
*Rationale:* a fixed grid gives comparability and run-to-run stability (the §5.6 principle applied to shocks); the reference point pre-empts "is −50% realistic?" without letting accumulating history drift the model. −70% is retained as the tail cell because bad debt appears there. *Rejected:* calibrated grid — needs price-history adapters as inputs and moves results for non-fundamental reasons.
 
**6.2.2 Correlation — uniform shock, LST-discount modifier.** All volatile collateral nodes fall by the grid percentage. LST and LRT nodes carry an additional discount to their underlying — **0% / 5% / 10%** — representing collateral trading below redemption value during the crash (stETH-2022 shape), applied on top of the uniform shock and printed as a modifier axis, not folded into the headline. Stablecoin collateral nodes (USDC/USDT/DAI-type held against GHO) are not shocked in Member 1; their failure is Member 2.
 
*Rationale:* targets the one correlation effect that has actually damaged CDP protocols, without a beta table whose values are least reliable in exactly the crashes being modeled. Exact for LUSD (ETH only); mildly conservative for GHO's diversified book. *Rejected:* beta-scaled — maintained table, unstable under stress.
 
**6.2.3 Speed.** Shock applied instantaneously; liquidations are processed under the timing and oracle assumptions of §7. Speed and oracle observation are decided together in §7 and nowhere else.
 
**6.2.4 Liquidation channel and capacity.** Common four-step structure: (1) shock → positions breach liquidation thresholds or enter/exit LLAMMA bands; (2) liquidation generates stablecoin demand or collateral selling; (3) absorption capacity is consumed; (4) exhaustion → bad debt and/or forced selling into the §5 pools → depeg pressure.
 
Capacity is defined **per token by its mechanism** (§6.3): LLAMMA band depth + arbitrage appetite + PegKeeper mint headroom (crvUSD); Stability Pool → redistribution → Recovery Mode regimes (LUSD); liquidator appetite bounded by collateral-to-stable exit depth and liquidation bonus (GHO).
 
**Common unit — mandatory.** Every token's capacity is expressed as *stablecoin-denominated absorption available within the shock window*. Mechanism-specific sources, identical units, so the §6.2.6 outputs are computed identically for all tokens. This is the seam that keeps "mechanism-specific" from becoming "incomparable."
 
**6.2.5 Member 2 — paired-stable depeg.** The **single paired stable with the largest share of exit depth**, determined at pool-set freeze time (§5.6) and refreshed quarterly with the set — the scenario definition does not flicker week to week; the chosen stable is printed in every report. It depegs with no collateral crash. Grid: **0.97 / 0.93 / 0.88** (March 2023 shape at the low end). The shock is applied to every §5 pool's paired asset according to its §4 label (composite paired assets: their shocked-stable share, §4.3); exit depth is recomputed at s = 2% in par terms against the shocked paired asset. **One additional compound tail cell:** all `recurses`-labeled paired stables jointly at 0.93, printed once and labeled as such. An analyzed CDP token appearing as a paired asset (§4.1) is **not** shocked — it is not a `recurses` stable; its own stress is its own report. *Rejected:* one-at-a-time per stable — multiplies cells for little information; joint-only as headline — not attributable and not the observed historical shape (March 2023 was a single issuer).
 
**Structural-insulation finding.** For a token with no stable-collateral node and no boxed asset (crvUSD, LUSD), the Member 2 depeg-pressure ratio is **zero by construction** (§6.2.7): a paired-stable depeg does not impair the claim, only the liquidity. This is a finding — *"structurally insulated; exposed through exit venues only"* — and the Member 2 story for such tokens is told by (i) the recomputed exit-depth curve (§6.1.1), printed prominently in Member 2, and (ii) metric 4 (e.g., PegKeeper LP share stuck in the depegging asset). A zero ratio is never presented as "nothing happened." In this member, asset-in-a-box and stabilizer mechanisms are **contagion channels, not stabilizers**: the GSM holds the depegging asset (GHO); PegKeeper pools are stuffed with it (crvUSD). §6.3 specifies each mechanism's behavior on this path as well as on the crash path.
 
*Joint cell:* collateral −50% and paired stable 0.93, LST discount 0%, LP flight 0% — labeled as a compound scenario. Answers the "March 2023 plus a crash" question without contaminating either headline.
 
*Rationale:* a separate member is attributable; it converts the §5.3 concentration disclosure into a number. *Forward note, not a commitment:* it is the one scenario with a cross-archetype analogue (fiat-backed reserve impairment); the brief otherwise forbids cross-archetype stress comparability (§11). *Rejected:* modifier-only — bundles two events with different causes into a number nobody can attribute.
 
**6.2.6 Scenario table and cell count.**
 
| Member | Axis 1 | Axis 2 | Axis 3 | Cells |
|---|---|---|---|---|
| 1 — collateral crash | shock −20/−35/−50/−70% | LST discount 0/5/10% | LP flight 0/30/60% (§6.1.4) | 36 |
| 2 — paired-stable depeg | target stable 0.97/0.93/0.88 | — | LP flight 0/30/60% | 9 |
| 2 — compound tail | all `recurses` stables 0.93 | — | 0% | 1 |
| Joint | −50% × 0.93 | 0% | 0% | 1 |
| **Total per token per run** | | | | **47** |
 
For LUSD (no LST nodes) the LST axis collapses: 12 + 9 + 1 + 1 = 23 cells. All cells are printed in full; no summarization needed under ~100. The §5.7 sensitivity table (K = 80/90/95%) and the §6.1.1 depth curve are computed for the headline cell only (Member 1, −50%, LST 0%, LP flight 0%) and add 3 + 4 evaluations.
 
**6.2.7 Output metrics — four, no composite.** For every cell:
 
1. **Post-shock collateralization** — system-wide ratio (external collateral over net debt, §9), and share of supply below 100%. Printed as **two readings per cell**: *pre-liquidation* (pure price shock, before any mechanism acts) and *post-liquidation* (after liquidations are processed and capacity consumed). **Post is the headline reading**, consistent with metrics 2 and 3. The gap between the readings is the liquidation mechanism's measured contribution — the reason both are shown. Two readings of one metric, not a fifth metric. *(solvency)*
2. **Bad debt** — uncovered debt after capacity (§6.2.4) is exhausted; figure and % of supply. *(solvency)*
3. **Depeg-pressure ratio** = forced-sell volume ÷ exit depth at s = 2% (§6.1). > 1 means the modeled pools cannot absorb the flow within the peg band. **Headline number** in the stress panel and on the site. *(liquidity)*
   **Forced-sell volume** = circulating supply that has lost its full-value enforceable claim after the shock — the amount a rational holder exits because the token is no longer fully backed. *Member 1:* = bad debt (metric 2) — uncovered supply after capacity is exhausted; metric 3 then reads "can the exit absorb the unbacked slice?", a direct link between the solvency and liquidity metrics. *Member 2:* = supply whose backing **is** the shocked stable, taken as the full slice, not value-weighted (a holder backed by USDC at 0.93 exits the whole token, not 7% of it): GSM-boxed supply plus the pro-rata slice attributed to shocked stable-collateral nodes via §11.1 (GHO); zero for crvUSD and LUSD (§6.2.5 finding). *Joint cell:* the sum. Stabilizer debt is excluded in every cell (§3.b). Supply quantities in the numerator; backing quantities never — the same discipline that separates backing from exit depth in §3.
4. **Mechanism trajectory** — token-specific content under a common heading: PegKeeper debt vs. ceiling (crvUSD); GSM utilization and facilitator bucket levels (GHO); Stability Pool balance and regime (LUSD). *(mechanism state)*
A fifth headline — "hours-to-depeg" or any composite — is refused on false-comparability grounds (brief §11.7; not reopened). The four together are the comparable spine of the stress section.
 
**6.2.8 Anticipated objections.**
 
*"Why fixed shocks?"* Comparability across tokens and stability across runs; realism is addressed by the printed historical reference point, not by letting history drive the grid.
 
*"Why no betas?"* Betas are least reliable in exactly the crashes being modeled. The LST-discount modifier targets the one correlation effect that has actually caused CDP losses.
 
*"Why is the ratio the headline?"* It is a single readable exit-holds-or-not figure, traceable to exactly two model outputs (forced-sell volume, exit depth), each of which is itself traceable to data fields.
 
### 6.3 Token mechanism hooks
 
**Design rule — switches become counterfactual lines, never cells.** Mechanism-behavior uncertainty (gating works or doesn't; a freezer trips or doesn't) is expressed as one primary modeling choice plus a printed counterfactual line under metric 4 — never as an additional scenario axis. Scenario axes are for states of the world; counterfactual lines are for uncertainty about mechanism behavior. This keeps the cell count flat and puts each uncertainty next to the number it moves.
 
**Collateral-sell-side bound (applies to H1 and H5).** Liquidation on the crash path requires converting collateral into stable markets. Until collateral→stable discovery exists (§11), this bound is an **analyst-supplied capacity parameter per volatile collateral node** — "amount of [node] absorbable into stable markets within the shock window at ≤ 2% impact" — staleness-tracked and printed on every report as a disclosed assumption with source and date [ANALYST-SUPPLIED 2026-09-01: not set in Phase B — requires live depth observation at implementation time; source + date to be recorded per value (Step 6 input)]. This is the brief's graceful-degradation shape: the manual path as another adapter with tracked staleness. LUSD is exempt (Stability Pool depositors receive collateral; no forced sale). *Rejected:* ignoring the bound — it leaves capacity unbounded at the −70% cell, exactly where bad debt lives; a stress test that cannot fail where it matters.
 
**H1 — PegKeeper (crvUSD).**
*Crash path — state-conditional capacity (ruled 2026-09-02; C1 resolved).* Capacity is **effective deployable headroom**, computed per run from on-chain state, not ceiling − debt.
 
**CHECK (per PegKeeper, per run, at the run's block):** (1) `is_killed` on the regulator (Provide flag) — a killed keeper contributes **zero**; (2) read α and β from the regulator and compute each live keeper's deployable amount under the deployment formula at current peer-debt levels: allowed = (α + β·Σ√r_others)² × (debt + balance) − debt, where r = debt/(debt + balance) of each other keeper. That figure — not ceiling − debt — is the keeper's crash-path capacity contribution.
 
**ROUTING.** Capacity contribution = Σ effective deployable headroom over live, unkilled keepers. **Metric 4 reports both figures** — effective vs. naive ceiling-headroom — so the gap is visible. **Counterfactual line (residual):** discretionary kill exercised mid-crash (admin or Emergency DAO) → zero PegKeeper contribution. State reads resolve configuration; the counterfactual carries only governance action during the event.
 
*Rationale.* "Full headroom" was an assumption about mutable state (kill flags) **and** about arithmetic now verified wrong: with deployed α = 0.5, β = 0.25 the regulator caps a keeper whose peers are idle at 25% of its allocation — a 4× overstatement in the current configuration (confirmed live: the USDT keeper stopped at $33.75M of $135M, July 2026). Both are data fields; read them. This is the §8.1 validate-before-routing principle extended to model premises — second instance, mirroring H2. *Rejected:* full headroom plus disclosure — publishes known-wrong arithmetic with a footnote; zero contribution — assumes a live, unkilled mechanism does nothing, evidence-free.
 
*Phase B facts consumed (verified 2026-09-01):* PegKeeperRegulator.vy (curvefi/curve-stablecoin) + verified deploy 0x36a04CAffc681fa179558B2Aaba30395CDdd855f — `set_killed` callable by admin or emergency_admin; `_get_max_ratio` = (α + β·Σ√r)²; deployed defaults α = 0.5, β = 0.25, worst_price_threshold 0.03%, price_deviation 0.05%; Curve News July 2026 recap. Ceilings remain the reported upper bound of the stabilizer slice (§3c); USDT $135M verified, others read per run from `ControllerFactory.debt_ceiling(pk)`.
*Depeg path (Member 2):* **primary** = V2 gating effective — no new mint; the pool tilts; the PegKeeper's existing LP share is stuck in the depegging asset, disclosed under metric 4. **Counterfactual line:** V1 behavior — contagion mint sized by remaining headroom. [VERIFIED 2026-09-01: provide_allowed() returns 0 if ANY of: (1) is_killed includes Provide — settable by admin (Curve DAO ownership agent) OR emergency_admin, discretionary; (2) aggregator.price() < 1; (3) this pool's spot vs. its own EMA oracle deviates > price_deviation (deployed default 0.05%; spam guard); (4) this pool's crvUSD price exceeds the largest price among the OTHER keepers' pools by > worst_price_threshold (deployed default 0.03%) — i.e., mint is blocked into any pool whose paired stable has fallen relative to the others. Test test_price_order confirms orientation. Amount allowed = (α + β·Σ√r_others)²·(debt+balance) − debt, α=0.5, β=0.25 deployed; a lone keeper may deploy 25% of allocation (confirmed live: USDT keeper stopped at $33.75M of $135M, Curve News July 2026). withdraw_allowed() returns 0 if is_killed includes Withdraw or aggregator.price() > 1. Source: PegKeeperRegulator.vy (curvefi/curve-stablecoin master) + verified deploy 0x36a04CAffc681fa179558B2Aaba30395CDdd855f (Etherscan)]
 
**H2 — GSM (GHO).**
*Crash path:* both effects included. (i) **Mint-side capacity:** liquidators mint GHO from the boxed asset up to exposure-cap headroom — the only mint-side capacity in the pilot with real backing behind it [VERIFIED 2026-09-01: addresses per sheet; AIP-8 set 0.2% flat buy/sell fee at launch; current fee/exposure cap [FIRST-RUN READ: GSM.getExposureCap(), fee strategy]; GSM steward 0xD1E856a9… can adjust within bounds. Sources: AIP-8; bgd-labs/aave-address-book main (GhoEthereum.sol, AaveV3Ethereum.sol, GovernanceV3Ethereum.sol)]. (ii) **Holder exit** GHO→boxed asset at 1 − fee: recorded in §5.10 as a deterministic exit venue, not a stress hook; §6 consumes it through exit depth.
*Depeg path (Member 2) — state-conditional primary (ruled 2026-09-02).* The primary is determined **per run** by an adapter read of the GSM's access-control state, not assumed.
 
**CHECK (per GSM, per run, at the run's block):** (1) does an automated OracleSwapFreezer-type contract currently hold the freezer role on this GSM? [GSM role-registry read: `getRoleMember(SWAP_FREEZER_ROLE)`]; (2) if yes, are its freeze bands set such that the freeze would trip within the Member 2 shock range, i.e., freeze lower bound ≥ 0.88 (the deepest Member 2 cell)? [freezer `getFreezeBound()` / `getUnfreezeBound()` read]. A freezer with bands that cannot trip in the modeled range is functionally absent: the check fails.
 
**ROUTING.** *Check passes* → **primary = freezer effective**: contagion capped at the current GSM balance, **and the exit valve closes when the freezer trips** — GHO's Member 2 exit depth drops by the GSM contribution (the safety mechanism and the liquidity loss are the same event; the report states this). **Counterfactual line (retained):** freezer fails to act in time — arbitrage mint to exposure-cap headroom, supply expansion backed at the shocked price. The counterfactual now covers *residual* uncertainty (a role-holding freezer not called in time), not role-configuration uncertainty, which is resolved by data. *Check fails* → **primary = freezer fails** (the former counterfactual becomes the primary); "freezer effective" is printed as the counterfactual instead; **and a §8.1 Level 1 flag fires:** *"automated freeze protection not currently in place / not effective in modeled range (checked at block N)."*
 
*Rationale.* (i) "Freezer effective" was silently an assumption about **mutable state** — roles are grantable and revocable by governance — not about protocol design; an assumption about mutable state must be a per-run data field (every claim traceable to a data field). (ii) This is the §8.1 "validate before routing" principle extended from data anomalies to model premises: check the state, then pick the branch. (iii) *Rejected:* unconditional "effective" — hard-codes mutable state; a role change would silently falsify the published Member 2 result, the exact failure mode this project criticizes in behavioral monitors; unconditional "fails" — assumes a deployed, role-holding safety mechanism does not work, without evidence. (iv) The report sentence this buys: *"GHO depeg contagion is capped because an automated freezer currently holds the role, with bands verified effective in the modeled range (block N)"* — and if the role ever lapses, the pipeline surfaces it as a flag. The admin-power surface (§13) conditioning a safety mechanism's worth is the project thesis instantiated.
 
*Design-rule consistency.* No new cells. This remains mechanism-behavior treatment under the §6.3 design rule — the switch is resolved by data where data exists (role + bands), with one counterfactual line for the residual behavioral uncertainty. The cell count (§6.2.6: 47 / LUSD 23) stands.
 
*Phase B facts consumed (verified 2026-09-01):* OracleSwapFreezer is a Chainlink-Automation-compatible contract (checkUpkeep/performUpkeep) holding the GSM freezer role; the original USDC-GSM instance 0xef6beCa8… was deployed with freeze 0.99/1.01, unfreeze 0.995/1.005, allowUnfreeze = true (Etherscan constructor args; contract has never fired); the Aave DAO executor is the second freezer entity (AIP-8); current GSMs 0x3A386889… (USDC) / 0x882285E6… (USDT) use freezers 0x6e51936e… / 0x733AB16… (aave-address-book) — same contract type. Band values on the current instances are now a **per-run adapter read**, not a static fact. Chainlink Automation upkeep registration/funding is not on-chain-verifiable from the GSM side; that residual is what the counterfactual line carries.
 
**H3 — LUSD three-regime capacity.**
Capacity in the common unit = **Stability Pool balance only.** Redistribution is reallocation, not absorption; counting it would flatter LUSD against tokens whose capacity means debt actually extinguished. The redistribution tail is reported under metric 4; **bad debt** is defined as redistributed positions falling below 100% CR; Recovery Mode entry (TCR threshold) is reported as a regime flag under metric 4. [VERIFIED 2026-09-01: CCR (Recovery Mode) = 150%, MCR = 110%, LUSD_GAS_COMPENSATION = 200 LUSD, PERCENT_DIVISOR = 200 (0.5%), MIN_NET_DEBT = 1800 — LiquityBase.sol; SP balance via StabilityPool.getTotalLUSDDeposits(); CR distribution via SortedTroves iteration + TroveManager.getCurrentICR. Source: liquity/dev main — PriceFeed.sol, TroveManager.sol, LiquityBase.sol]
*SP depositor flight:* the §6.1.4 LP-flight haircut grid applies to SP deposits, **tied to the same axis** — a cell's haircut level applies to pool LPs and SP depositors simultaneously. One flight assumption across the archetype; zero new cells. Independent flight axes rejected: why would LPs flee but SP depositors stay?
 
**H4 — LUSD redemption arbitrage.**
Modeled on **Member 2 only.** Capacity = LUSD redeemable at face for ETH before the dynamic redemption fee exceeds s = 2%, computed from the base-rate schedule [VERIFIED 2026-09-01: baseRate += redeemedLUSDFraction / BETA (BETA=2); decays by MINUTE_DECAY_FACTOR 0.999037758833783 per minute (12h half-life); REDEMPTION_FEE_FLOOR 0.5%; fee = (baseRate + 0.5%) × ETHdrawn, capped so fee < redeemed amount; redemptions blocked when TCR < MCR (110%) and during 14-day bootstrap. Source: TroveManager.sol]. The crash-path effect (redemptions raising weakest-trove CRs) is excluded as a conservative simplification — it requires below-peg LUSD, which the crash path does not produce; exclusion noted here. **State gate:** when the §12 `state_conditional` gate is active (TCR < MCR [FIRST-RUN READ: live value]), H4 capacity is zero. This cannot occur in Member 2 alone; it can in the joint cell — the model checks the gate per cell.
**Contrast (illustrates §3):** both PegKeepers and LUSD redemptions act below peg, but redemptions burn supply against *pledged collateral* with a liquidation-grade third-party claim, while PegKeepers unwind a *protocol-owned LP position* with no claim behind it. The §3 zero-credit ruling, shown by mechanism.
 
**H5 — GHO liquidator appetite.**
Capacity = **min( GHO sourceable, collateral sellable )**, both within the liquidation bonus: GHO sourceable = §5 pool buy-side depth + GSM mint headroom (H2.i); collateral sellable = the analyst parameter above. Whichever side binds first is capacity; **which side binds is reported per cell under metric 4.** [FIRST-RUN READ: PoolDataProvider.getReserveConfigurationData per reserve; eMode categories via Pool.getEModeCategoryData] Facilitator bucket caps bound recovery minting, not liquidation (liquidation burns GHO); metric 4 item [FIRST-RUN READ: GhoToken.getFacilitatorsList() + getFacilitatorBucket(); GHO bucket steward 0x46Aa1063… adjusts caps].
 
## §7. Oracle-execution and timing assumptions
 
### 7.1 Shock window — stock-only capacity
 
Capacity (§6.2.4) is measured as **stocks available at the run's block**: Stability Pool balance, PegKeeper mint headroom, GSM balance and cap headroom, pool depth, the collateral-sell-side analyst parameter. No rate modeling; no time parameter.
 
*Rationale:* every stock is an on-chain data field; every rate (liquidator recycling speed, arbitrage flow) would be an invented parameter with no observable behind it. The evaluator criterion — every quantitative claim traceable to a data field — decides this.
 
**Bias note — per mechanism, mandatory.** Stock-only is *not* uniformly conservative, and this memo does not claim it is. It **overstates** capacity where a stock cannot all act within a crash timeframe (the full collateral-sell-side bound treated as immediately available; the full GSM cap headroom treated as instantly mintable). It **understates** capacity where flows would replenish stocks (liquidators recycling capital through multiple rounds; Stability Pool refills between liquidation waves). The defensible position: cruder but fully traceable; direction of error disclosed per mechanism. *Rejected:* T = 24h with rate parameters — every rate is unverifiable; pure instantaneous framing without this note — hides a known modeling error.
 
### 7.2 Observation assumption — instant primary, crvUSD EMA counterfactual
 
**Primary:** all price feeds track the shock instantly; liquidation mechanisms see spot at t = 0.
 
*Per-token justification.* Chainlink-fed systems (GHO via Aave's price oracle; LUSD via its PriceFeed): deviation thresholds of ~0.5–1% fire immediately in any crash cell, so the instant assumption is nearly exact (feed parameters: intake sheets). crvUSD: the instant assumption is **knowingly optimistic** — LLAMMA prices off an EMA-smoothed internal oracle that lags spot in a fast crash; soft liquidation trails the market, arbitrageurs trade against a stale-high oracle, and band losses are worse than the instant assumption implies (EMA parameters: intake sheet).
 
**crvUSD counterfactual line** (metric 4, per the §6.3 design rule — oracle lag is mechanism behavior, not a state of the world): *"band losses under EMA lag at [verified window]: +X% additional collateral erosion."* Implemented as a **bounded approximation** — additional band erosion under the stated lag against the shock path — explicitly labeled as an approximation, not full EMA band-crossing dynamics, and it must not claim to be.
 
*Rejected:* full mechanism-faithful lag modeling as the factory default — large standing complexity that mostly moves one term; instant-everywhere with no counterfactual — silently optimistic for the pilot's flagship token.
 
### 7.3 Failure-mode scope
 
- **Oracle manipulation** (flash-loan spot games, malicious feed): out of scope — an attack on a specific market, not a scenario family. Feed control is reported under the admin-power surface, which is where a reader assesses it.
- **Oracle failure/staleness:** out of scope for crvUSD and GHO (same one-sentence treatment). **LUSD carries one counterfactual line** — Tellor fallback engaged [VERIFIED 2026-09-01: PriceFeed status machine: Chainlink treated as broken (revert/0/bad round) or frozen (>TIMEOUT 14400s = 4h since update) or deviant (>50% vs previous round) → switch to Tellor; Tellor frozen (>4h) or broken → statuses usingChainlinkTellorUntrusted / bothOraclesUntrusted (last good price used); return to Chainlink when both within 5% (MAX_PRICE_DIFFERENCE_BETWEEN_ORACLES). Ownership renounced in setAddresses. Logic unchanged (v1 immutable). Counterfactual line RETAINED — no downgrade. Source: liquity/dev main — PriceFeed.sol, TroveManager.sol, LiquityBase.sol]. Rationale: nearly free; the simplicity control demonstrating even its one exotic feature strengthens the control role; and it sets up the §7 ↔ admin-surface contrast — **LUSD is the pilot token with no admin keys but with an automated on-chain fallback, the inverse of the usual pattern.** *Downgrade path:* if Phase B shows the fallback conditions are murkier than documented, this line becomes a scope-out sentence at zero cost.
- **Sequencer / infra risk:** n/a — mainnet only (§5.2).
### 7.4 Oracle-dependency table — reference, don't restate
 
§7 references the intake sheets' oracle entries; it does not restate them. Each published report prints an **oracle-dependency table** (brief §12 requirement): feed/source per collateral node; update condition (deviation + heartbeat, or EMA window); and the §7 assumption applied — with the crvUSD EMA row and the LUSD fallback row carrying their counterfactual-line references.
 
## §8. Quarantine bounds
 
### 8.1 General semantic quarantine
 
**8.1.1 Severity ladder — three levels, per-token scope.**
 
| Level | Name | Consequence | Resolver | Meaning |
|---|---|---|---|---|
| **1** | Flag | Report publishes; a visible, persistent flag sits in the affected section until resolved. | Analyst, async batch review. | The numbers are right; a human should look. |
| **2** | Report quarantine | This token's report is not published this run; other tokens unaffected. | Analyst review → template / intake / config fix → rerun. | The model cannot classify what the data says. |
| **3** | Run quarantine | Pipeline halts for this token *before* analysis; nothing downstream computes. | Analyst review → data-source or adapter fix → rerun. | The data itself is untrusted; numbers derived from known-bad data are never produced, let alone published. |
 
*Distinction, verbatim:* Level 2 = the model can't classify what the data says; Level 3 = the data itself is untrusted.
 
**Declare-your-level rule.** Every trigger in this memo — existing or added later — states its level where it is defined. Trigger map:
 
| Trigger | Defined at | Level |
|---|---|---|
| Unlisted collateral node < 5% of backing | §8.2 | 1 |
| Off-venue liquidity share > 25% (pilot handling) | §5.1 | 1 |
| GHO attribution fallback, first run | §11.1 | 1 |
| Composition shift > 10pp or top-3 change | §8.1.4(a) | 1 |
| Supply jump > 25%, cross-validation confirms | §8.1.4(b) | 1 |
| Market addition with known node | §8.1.4(c) | 1 |
| Mechanism near bound (> 80% of capacity) | §8.1.4(d) | 1 |
| GSM freezer check failed — role absent or bands ineffective in modeled range (GHO) | §6.3 H2 | 1 |
| Unlisted collateral node ≥ 5% (single or cumulative) | §8.2 | 2 |
| Pool-set change ≥ 10% of coverage | §5.6 | 2 |
| GHO attribution fallback, second consecutive run | §11.1 | 2 |
| Market removal | §8.1.4(c) | 2 |
| Three-way discovery mismatch > 5% | §5.5 | 3 |
| Supply jump > 25%, cross-validation disagrees | §8.1.4(b) | 3 |
| Any market-count change on an immutable protocol (LUSD) | §8.1.4(c) | 3 |
 
**Scope.** Quarantines are **per token**. One token's quarantine never blocks another's publication — that is what "factory" means. No global quarantine mechanism exists; a shared-source failure (e.g., DefiLlama down) fires Level 3 for each token independently, which makes the effect global without a global rule.
 
**8.1.2 Stale-page behavior.** When a token's current run is Level 2/3-quarantined, the site keeps the last successfully published report up and shows a banner with two facts: *"Last successful run: [date]"* and *"Current run: quarantined — [trigger category]."* **Staleness cap:** after 4 consecutive quarantined weekly runs, the token page switches to *"Under review — last successful run [date]"* with the report withdrawn. A month-old report presented as current is worse than no report.
 
*Rationale:* the site's pitch is "produced unattended, gates passed"; a quarantine shown honestly is evidence for that pitch, a hidden one, if noticed, destroys it. *Rejected:* silent stale page (hides trouble); immediate blanking (turns every hiccup into a public alarm and loses the last good analysis).
 
**8.1.3 Resolution protocol and public log.** A quarantine resolves **only** by (i) template / intake-sheet / config change, or (ii) confirmed upstream data correction. Never by hand-editing an output, and never by overriding a gate for one run — the brief's loop rule applied to gates. Every quarantine event, Level 1 included, is logged: date, token, trigger, level, resolution type, resolution date. **The log is public**, on the methodology page: it is the strongest available evidence that the factory claim is real — anyone can say "gated"; showing the gates firing proves it. Entries are at category level (trigger, level, resolution type, dates), never debugging narrative. A governance log, not a diary.
 
**8.1.4 Semantic bounds.**
 
*Principle — validate before routing.* Where a trigger could indicate either a real event or a data error, the pipeline cross-validates first and routes by the result. A confirmed large move is exactly when a reader most wants the report published; blocking it would be the gate working against its purpose.
 
**(a) Composition shift — Level 1.** Any collateral node's share of backing moves > 10 percentage points since the last successful run, or any node enters or leaves the top-3 by share. The numbers remain correct; only the template's narrative frame may be stale, and stale prose is a batch-review job, not a publication blocker. If batch review finds the scenario rationale invalidated, the analyst escalates via the resolution protocol (template fix); no separate Level 2 trigger is needed. 10pp over 5pp: for small tokens 5pp fires on ordinary growth and becomes noise; a flag nobody reads is worse than no flag.
 
**(b) Supply jump — two-branch.** Total supply changes > 25% between consecutive runs. *Supply* here = mainnet `totalSupply()` **plus bridged-out supply where the bridge is burn-and-mint** (lock-and-mint supply is already inside `totalSupply()`); otherwise a bridging wave on a burn-and-mint facilitator would false-trigger [VERIFIED 2026-09-01: GHO: lock-and-mint on Ethereum (locked in CCIP token pool 0x06179f7C…; totalSupply unaffected) — aave.com/help/gho-stablecoin/bridging-gho; crvUSD: LayerZero bridges listed in docs deployments (avax/ftm/bnb/kava/sonic-lz) — [FIRST-RUN READ: lock vs burn: check mainnet bridge contract crvUSD balance]; LUSD: canonical L2 bridges (lock-mint), negligible]. Cross-validation (DefiLlama + Dune) **disagrees** with the jump → **Level 3** (data corruption — adapter decimals/unit bug, bad RPC read). Cross-validation **confirms** the jump → **Level 1** (real event — facilitator ramp, bridge incident, mass repayment; publish with flag). 25% over 50%: real events worth flagging often land in 25–50%; adapter bugs are orders of magnitude and are caught by either.
 
**(c) Market-count change.** Change in mint-market count (crvUSD), enabled-collateral count with non-zero GHO backing (GHO), or GSM/facilitator count (GHO) between runs. **Addition with a known collateral node → Level 1**: cheap to glance at, and the intake gate should see a new market before it has grown, not after (an addition with an unknown node already routes via §8.2). **Removal → Level 2**: a market disappearing means supply migrated or something was shut down — narrative- and possibly rationale-relevant. **Immutable protocols (LUSD): any count change → Level 3** — it can only be an adapter bug. *Rejected:* folding into (a) — loses early-stage additions; Level 1 on everything — removals deserve review, not a flag.
 
**(d) Mechanism near bound — Level 1 class rule, mirrored in the monitoring brief.** A protocol mechanism approaching its own capacity bound in **live base data** raises a Level 1 flag. Per-token instances live in the intake sheets (PegKeeper debt vs. ceiling; GSM utilization and facilitator bucket levels; LUSD TCR vs. Recovery Mode threshold), at 80% of the bound unless the sheet states otherwise. Placement is both §8 (makes it a rule) and the Tier-1 monitoring brief (makes it visible). Every input is already read — near-zero cost — and "the safety mechanism is running out of room" is arguably the single most decision-relevant flag for a reader. *Relationship to metric 4:* metric 4 reports these quantities under scenarios; this bound watches them in base data. Both, different questions.
 
### 8.2 Verifiability-specific instance — unlisted collateral node
 
Weight-thresholded at **5% of a token's backing** (by value, at the run's block):
 
- Unlisted node ≥ 5%: **report-level quarantine (§8.1 Level 2)** — the token's report is not published; node queued for intake; analyst notified.
- Unlisted node < 5%: report publishes **(§8.1 Level 1)**; the verifiability section carries a visible flag "N% of backing unclassified — pending intake"; node queued for intake; the flag persists across runs until resolved.
- Cumulative rule: multiple unlisted nodes that together reach ≥ 5% are treated as Level 2.
*Rationale:* 5% is large enough that misclassification would visibly move the verifiability score, small enough that a newly added minor collateral does not halt a weekly run. Defensible range 3–10%; 5% chosen.
 
## §9. Encoded hard gates (this archetype)
 
- Collateral filtered by address, never symbol.
- Principal vs. accrued interest separated.
- No hardcoded market / pool / collateral / stabilizer lists — discovery from factory, registry, or regulator contracts, or staleness-tracked analyst input. *Stabilizer instance (ruled 2026-09-02, P4):* the PegKeeper set is read per run from `PegKeeperRegulator.peg_keepers` (0x36a04CAf…); a keeper whose paired asset has no §4 label routes via §8.2.
- **Stabilizer netting:** the stablecoin's own leg of any stabilizer LP position never counts as backing or as value (§3a).
- **Position netting:** the stablecoin held inside a borrower position (e.g., crvUSD acquired through LLAMMA soft liquidation) is netted against that position's debt. It is never counted as collateral value and never appears as a backing node in the §4 tree (§2).
- **Supply origination:** MINT markets (new units created against collateral) are separated from LEND markets (existing units re-lent). Lend-market collateral does not back the stablecoin. Discovery by factory/controller address class, never by asset symbol. (crvUSD-specific form of the Morpho lesson; see crvUSD intake sheet.)
- Unlisted collateral node → §8.2, never "other."
- **Discovery reconciliation:** three-way pool discovery mismatch > 5% of total → discovery quarantine (§5.5).
- **Frozen pool set:** membership changes only via quarterly refresh or intake trigger; detector flags never auto-update the set (§5.6).
- **Paired-asset labeling:** every paired asset of a modeled pool carries a §4 label; an unlabeled paired asset is an unlisted node under §8.2.
- **Declare-your-level:** every quarantine trigger states its §8.1 level where it is defined.
- **Gate integrity:** quarantines resolve only by template / intake / config change or confirmed data correction — never by output edit or one-run gate override (§8.1.3).
## §10. Anticipated objections
 
*"This penalizes a peg-defense feature."* Zero-crediting is not a grade penalty; the stabilizer's contribution is captured in the stress model, where it belongs, as a flow that mints into crashes and burns into depegs. What is refused is counting a pro-cyclical, non-recourse position as backing in a report whose stress section would then contradict its own headline.
 
*"Would you treat Frax or Maker the same?"* Yes, by construction — the rule is stated protocol-agnostically and names Frax AMO operations as the expected next member. Maker/Sky PSM and GHO GSM fall outside the class because they hold a third-party asset 1:1 with no circular leg, and are backed by that asset subject to look-through.
 
## §11. Open points (this memo)
 
1. **GHO collateral attribution — RESOLVED.** The Aave facilitator mints GHO against pooled Aave V3 collateral shared with other borrowing. Ruling: **(a) pro-rata per position is primary** — for each GHO borrower, collateral value × (GHO debt ÷ that borrower's total debt), summed across all GHO borrowers. **(b) protocol-level ratio** — aggregate Aave V3 Ethereum collateral ÷ aggregate debt, applied to Aave-facilitator GHO supply — is an automated cross-check, always computed and reported alongside. Divergence beyond 10% relative (pilot tolerance; revisit after first runs) is reported as a finding ("GHO borrowers are systematically more/less collateralized than the Aave average"), not suppressed. Fallback: if per-position reads fail on a run, publish on (b) with a visible flag "attribution: protocol-level fallback" (§8.1 Level 1); two consecutive fallback runs → report quarantine (§8.1 Level 2). (c) full attribution rejected: overstates by construction. The rule generalizes to any facilitator-style mint against a shared collateral pool.
2. **LRT / cbETH rows — RESOLVED 2026-09-02 (P1/P2).** LRT family → `terminal_other_layer`; cbETH → `recurses`; cbBTC and custodial BTC wrappers → `recurses` (§4.4/4.5).
3. **tBTC label** — deferred pending [FIRST-RUN READ: live value] (§4.4).
4. **Behavioral-tier depeg-threshold consistency.** The headline slippage bound (s = 2%, §6.1.1) should align with the behavioral tier's depeg-tier thresholds so the two layers agree on when a token is off peg [ANALYST-SUPPLIED 2026-09-01: deferred — no API access]. Log as a consistency check for when the behavioral tier lands.
5. **LP-flight haircut calibration — future work.** The 0/30/60% grid (§6.1.4) is assumed. Candidate observable: the ~985-day USDe calibration dataset; transfer from a synthetic to CDP-archetype pools needs a stated justification. Step-6 enhancement and candidate standalone research note ("do CDP pools behave like synthetic pools under tilt?"). Not a pilot dependency.
6. **Off-venue extension (dated, per token).** Logged when the §5.1 25% trigger fires on a run; expected first for GHO.
7. **Price-history source for reference drawdowns** [ANALYST-SUPPLIED 2026-09-01: Chainlink round history preferred; DefiLlama fallback] (§6.2.1). Disclosure-only dependency; a missing source prints "reference point unavailable," it does not block the run.
8. **Cross-archetype analogue of Member 2 — forward note.** The paired-stable depeg has a structural analogue in fiat-backed reserve impairment. Recorded as a possible future cross-archetype comparable; not a commitment, and the brief's prohibition on cross-archetype stress comparability stands until a defensible middle is shown (brief §11.7).
9. **Collateral→stable discovery extension — dated, post-launch.** §5-style discovery over collateral→stable pools would replace the analyst-supplied collateral-sell-side parameter (§6.3) behind the same interface. Logged 2026-08; not a pilot dependency.
10. **Collateral-sell-side parameter values — Phase B.** [ANALYST-SUPPLIED 2026-09-01: deferred to implementation; live depth observation]
11. **Per-node admin qualifier (§13 option b, full form).** The pilot ships the token-level qualifier. Revisit after first runs, when it is known whether token-level suffices or nodes behind different admin surfaces (e.g., GSM vs. Aave facilitator within GHO) need per-node decoration.
12. **Off-venue share sourcing — logged 2026-09-02 (P5).** A Step-3 implementation task, not a memo matter. Licensed fallback: if not reliably computable on a run, publish "off-venue share: not computed" with a §8.1 Level 1 flag. Never guessed.
13. **Collateral-sell-side parameter values — deferred as designed (P6).** Set at pool-set freeze (first-run setup) from observable market depth on that date, staleness-dated. Not a Phase B item.
## §12. Redemption-rights fields
 
**Scope — holder redemption only.** R1–R9 describe what a **holder** of the stablecoin can claim. Borrower repayment (repay debt, withdraw collateral) is the mechanism, not a right, and is out of scope for these fields. The LUSD-vs-crvUSD contrast is the illustration: LUSD holders redeem at face against troves; crvUSD holders have no redemption path — only borrowers close positions. Recording that difference is the field set's entire purpose. *"Backing you can't claim isn't backing in a run."*
 
**N paths.** The schema allows any number of redemption paths per token; each path is a full R1–R10 block. A "best path" summary would lose exactly the fact that a path can close (GHO's GSM, §6.3 H2). Later archetypes need this too (issuer redemption vs. secondary market).
 
| # | Field | Type |
|---|---|---|
| R1 | Redemption path exists | `direct_on_chain` / `module_on_chain` / `issuer_offchain` / `none` |
| R2 | Who may redeem | `anyone` / `whitelisted` / `borrowers_only` / `no_one` |
| R3 | What is received | asset address(es) |
| R4 | Rate | `face_value` / `face_minus_fee(range)` / `market` |
| R5 | Minimum size | figure or `none` |
| R6 | Gates / notice | `none` / `pausable` / `capacity_limited` / `state_conditional(condition)` / `notice_period(N)` (combinable) — `state_conditional` = a gate that opens and closes on protocol state without admin action and without capacity change |
| R7 | Capacity bound | data-field reference or `unbounded` |
| R8 | On-chain enforceability | **computed** (rule below) |
| R9 | Legal claim independent of contract | `yes` / `no_pure_protocol` / `disclaimed` |
| R10 | Provenance | contract + function, or document + date |
 
**R8 derivation rule — computed, never hand-keyed.**
- R1 = `none` → R8 = `n/a`
- R1 ∈ {`direct_on_chain`, `module_on_chain`} and R6 = `none` → `enforceable`
- R1 ∈ {`direct_on_chain`, `module_on_chain`} and R6 ∈ {`pausable`, `capacity_limited`} → `enforceable_unless_paused` (`capacity_limited` adds a note pointing to R7)
- R1 ∈ {`direct_on_chain`, `module_on_chain`} and R6 includes `state_conditional(C)` → `enforceable_unless_[C]` (combinable with the line above)
- R1 = `issuer_offchain` → `discretionary` (regardless of R6), except R9 = `yes` and R6 = `none` → `enforceable_offchain` (reserved for later archetypes)
- R6 includes `notice_period(N)` → the path's value with "(N-day notice)" appended.
*Rationale:* a verdict field that cannot drift from its inputs because it is never typed. R6 stays as the descriptive input; the judgment leak is closed.
 
**R9 enum — legal vs. mechanical recourse.**
- `yes` — legal terms grant holders a claim on reserves.
- `no_pure_protocol` — no legal terms exist; the on-chain claim (R8) is the operative and only claim. **This is a strength, not a gap**, for this archetype (crvUSD, LUSD, GHO).
- `disclaimed` — legal terms exist and limit, condition, or disclaim redemption (expected in the fiat archetype; encoded now so the schema does not change later).
*Rejected:* `n/a_no_terms` — makes the strongest position look like missing data; mapping protocol-state gates to `capacity_limited` — misdescribes the mechanism (capacity unchanged; the door shuts), and the gate type recurs in other CDP designs.
 
## §13. Admin-power surface
 
**Purpose.** Backing is only as strong as the keys that can rewrite the rules. The surface is on-chain readable → Tier 1. It is reported per token as a table (A1–A8) and summarized as a **token-level qualifier** attached to the verifiability tree.
 
| # | Field | Type |
|---|---|---|
| A1 | Power | one row per power, from the fixed enum below |
| A2 | Holder | address + type: `eoa` / `multisig(m-of-n)` / `dao_governance` / `timelock` / `none` |
| A3 | Signer set (if multisig) | count; identity status `disclosed` / `partial` / `undisclosed` |
| A4 | Delay | timelock in seconds **and** bucket: `none` / `<24h` / `1–7d` / `>7d` |
| A5 | Veto / guardian | address + power (`cancel` / `pause`) or `none` |
| A6 | Upgradeability | `immutable` / `proxy_upgradeable(admin = A2)` |
| A7 | Scope of power | contracts / markets reached (address list) |
| A8 | Provenance | contract + function read; block |
 
**Power enum — fixed at memo level, nine values:** `mint`, `set_ceiling`, `upgrade`, `pause`, `freeze_asset`, `blacklist_address`, `set_oracle`, `set_parameters`, `seize`. A token maps any number of concrete functions to one enum value (listed under A7/A8); a token **never adds an enum value** — that is a memo change, dated and visible. Same discipline as the §4 label scheme.
 
**Delay buckets.** Raw seconds are always printed alongside the bucket. Buckets are a categorization of a data field, not a governance judgment; a reader who disagrees with the bucket edges has the raw number beside it. No binary "effectively none" verdict exists.
 
**Qualifying powers — how the surface conditions verifiability.** Powers that can change or extract backing: **`mint`, `upgrade`, `set_oracle`, `seize`.** Non-qualifying: `pause`, `freeze_asset`, `blacklist_address` (they affect redemption rights → captured in §12 R6/R8); `set_ceiling`, `set_parameters` (reported, not qualifying).
 
**Token-level qualifier block.** For each qualifying power held by anyone: power / holder type (A2) / signer disclosure (A3) / delay bucket (A4) / veto (A5). Machine-readable, attached to the tree artifact, rendered on the site as a banner above the tree — e.g., *"Verifiability conditional on: upgrade — DAO + timelock, 1–7d; mint — DAO, 1–7d."* If no qualifying power exists: *"No admin power can alter backing — immutable."* No binary verdict, no per-node decoration, no score change.
 
*Rationale:* every element is a data field (holder address, delay seconds); attaching it to the tree makes it evaluator-checkable and site-renderable — the difference from plain disclosure; honest about what a timelock does and does not buy; a fraction of the cost of per-node decoration. *Rejected:* numeric haircut — invented factor, fails traceable-to-data; disclosure alone — delivers brief §2.3 only weakly. Full per-node qualifier: §11.11.
 
**Live model inputs — a pattern, two members.** Some admin-surface fields are consumed as **live model inputs** by the stress model, not as disclosure only. (1) GHO: the GSM freezer-role assignment and freezer bands (`pause` row) select the §6.3 H2 Member 2 primary per run. (2) crvUSD: the PegKeeper regulator's `is_killed` flag and α/β debt parameters (`pause` / `set_parameters` rows) determine the §6.3 H1 crash-path capacity per run. Any later field consumed this way must be marked in its table row as a live model input, and the consuming section named.
 
**Control case.** LUSD's surface is expected empty (immutable v1 contracts, no owner, no proxy, no pause) [VERIFIED 2026-09-01: LUSD immutability confirmed — see LUSD sheet §13 table]. It is the schema control: if the A1–A8 table cannot cleanly express "nothing," the schema is wrong. It also sets up the §7.3 contrast — no admin keys, but an automated on-chain oracle fallback.
 
## §14. Audit status and counterparty enumeration
 
**Audit status.** One static line per token: audits [firm, date, scope]; bug bounty [platform, max]; last material change audited yes/no. Analyst-keyed, staleness-dated, never scored.
 
**Counterparty enumeration.** Schema field present on every sheet, value *"n/a — archetype #1 holds no off-chain counterparties,"* with the note that a custodial-wrapped collateral node's custodian (WBTC) is captured in §4 look-through, not here. Present and empty, never absent — the synthetic and fiat sheets fill the same field.
 
## §15. Phase B record (2026-09-01/02)
 
**Method.** Facts only; sources in preference order (contract source / verified deploy → official docs → governance → GitHub); every replaced tag carries value, source, date. Live-state quantities (balances, ceilings other than USDT, TVLs, per-position data) are marked FIRST-RUN READ — Tier-1 adapter reads, not assumptions. Six items are ANALYST-SUPPLIED with staleness 2026-09-01 per the brief's graceful-degradation rule.
 
### 15.1 Contradiction flags — pending ruling
 
**C1 — §6.3 H1 crash path.** *Ruling assumed:* PegKeeper crash-path capacity = full mint headroom (ceiling − debt), conditional on V2 gating being price/aggregator-triggered only with no discretionary block. *Verified state:* (a) `PegKeeperRegulator.set_killed()` lets the admin (Curve DAO ownership agent) **or** the emergency_admin block Provide and/or Withdraw at any time — a discretionary kill switch exists; (b) the regulator caps each keeper's deployable amount at (α + β·Σ√r_others)² × allocation with deployed α = 0.5, β = 0.25 — a keeper whose peers are idle can deploy only **25%** of its allocation, rising as peers deploy (confirmed live: USDT keeper stopped at $33.75M of $135M, July 2026). Sources: PegKeeperRegulator.vy + verified deploy 0x36a04CAf…; Curve News July 2026. *Affected:* §6.3 H1 crash path; crvUSD sheet H1; metric-4 headroom trajectory. *Options:* (i) capacity = regulator-formula fixed point with all keepers minting together (computable from stocks; counterfactual = zero); (ii) capacity = 25%-of-allocation floor as primary, formula fixed point as counterfactual; (iii) keep full headroom as an upper bound, print the formula-bounded amount as the primary line. The kill switch is an admin-surface item (§13, `pause` on stabilizer) under any option.
 
**§15.1 status: RESOLVED.** C1 ruled 2026-09-02 (option iii — effective deployable headroom from per-run regulator reads; recorded at §6.3 H1). Item 1.2 ruled 2026-09-02 (state-conditional H2; recorded at §6.3 H2). §15 is a closed verification appendix and is retained as the record.
 
**Item 1.2 — RESOLVED WITH RULING (2026-09-02).** The H2 depeg-path primary was amended to a state-conditional form (role + band check per run, routing, Level 1 flag on failure); sources: Etherscan verified OracleSwapFreezer source + constructor args; AIP-8; aave-address-book. Freezer band values need no further verification — they are a per-run adapter read.
 
*Not contradictions (premises confirmed):* §6.3 H1 depeg path — V2 gating effective, and stronger than assumed (aggregator < 1 blocks all provides; cross-pool 0.03% threshold blocks provides into a pool whose paired stable has fallen; 0.05% spam guard). §6.3 H2 depeg path — freezer is automatic (Chainlink Automation) with 0.99/1.01 freeze and 0.995/1.005 unfreeze bounds on the original instance; current-instance bounds are a first-run read; Aave DAO is the second freezer. §7.3 — LUSD fallback logic verified exactly (4h timeout, 50% deviation, 5% reconciliation); **counterfactual line retained, no downgrade.** §3 note — AggMonetaryPolicy4 confirms the debt-ratio EMA smoothing (supports zero-credit).
 
### 15.2 Candidate open points — dispositions (2026-09-02)
 
| # | Point | Disposition | Where recorded |
|---|---|---|---|
| P1 | crvUSD live collateral without §4 rows (cbBTC, weETH) | **Ruled:** cbBTC → `recurses` (custodial; Coinbase attestation, cadence re-scoped to intake); weETH → `terminal_other_layer` (LRT family row). No design change. | §4.4, §4.5; crvUSD sheet |
| P2 | GHO Aave reserve universe (synthetics, LRTs, custodial BTC, PT tokens) | **Ruled:** scoping rule — enumeration = reserves with non-zero attributed GHO backing at freeze time, refreshed quarterly; between-freeze newcomers via §8.2. Sheet node list = freeze-time artifact. | §4.5 note; GHO sheet |
| P3 | GHO as crvUSD PegKeeper asset (source conflict); GSM variants | **Ruled:** generalize — every live GSM gets its own R-block (§12 N-paths) and its own H2 freezer check; live-GSM enumeration at freeze; variant parameters re-scoped to intake. Keeper set resolved by P4. | §6.3 H2, §12; GHO sheet |
| P4 | frxUSD (and any other) PegKeeper paired asset without a §4 row | **Ruled:** keeper set discovered per run from the regulator registry, never hardcoded; unlabeled paired asset routes via §8.2. | §9 gate; crvUSD sheet |
| P5 | Off-venue share sourcing (Balancer/Uniswap coverage) | **Logged** — Step-3 task; fallback "not computed" + L1. | §11.12 |
| P6 | Collateral-sell-side parameter values | **Deferred as designed** — set at freeze, staleness-dated. | §11.13 |
 
### 15.3 Resolution counts
 
**Counting units (reconciliation).** 18 = ANALYST-SUPPLIED value tags across memo (10) and sheets (8); 6 = distinct analyst-supplied items in the §15 method note; 3 = checklist rows whose interim (2026-09-01) status was analyst-supplied (4.5, 5.7, 6.5), all of which carry the FINAL state RE-SCOPED-TO-INTAKE. All three are consistent. *(Note: the ruling text proposed "memo (11) / sheets (7)" and "4 checklist rows"; the artifacts count 10/8 and 3 — recorded as counted, not as proposed.)*
 
Tier 1: 2/2 resolved (C1 flagged on the adjacent H1 crash-path premise, checklist 2.4). Tier 2: 4/4 resolved (EMA windows are per-market first-run reads by design). Tier 3: 4 resolved, 1 conditional (tBTC branch 1 provisional pending WalletRegistry read). Tier 4: 6 resolved, 3 partial (pool sets / lend factory / metaregistry → first-run discovery). Tier 5: 6 resolved, 3 partial (ceilings other than USDT, GSM current fee/caps, Aave reserve params → first-run reads), 1 analyst-supplied (collateral-sell-side values — deferred to implementation). Tier 6: 5 resolved, 3 partial, 1 deferred (Webacy).