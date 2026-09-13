# Evaluator Rubric v1 — Archetype #1 (CDP / On-Chain-Backed)
 
**Status:** v1 FINAL — Step 2 CLOSED 2026-09-03; self-test (a)-list empty.
**Date:** 2026-09-03.
**Checksum algorithm (declared 2026-09-03):** SHA-256, first 8 hex digits, over the raw bytes of the LF-normalized file. The stamp is computed over LF-normalised bytes; on-disk line endings (CRLF on Windows) do not affect it.
 
**Governing artifacts (checksums):** `archetype-memo-1-cdp.md` 17553d7b · `intake-sheets-cdp.md` 32f8aa5d · `phase-b-checklist.md` 54620383 — all at status "Phase B COMPLETE — 2026-09-02".
 
**Historical checksums — unreproducible, retained (2026-09-03):** the previous values `f65f5f72` · `976085c9` · `6c7c6708` reproduce under no tested scheme: 0 of 3 files matched across 126 scheme × byte-form combinations (14 schemes — CRC-32, Adler-32, and first-8/last-8 of MD5, SHA-1, SHA-256, SHA3-256, BLAKE2b, BLAKE2s — over 9 byte forms). The three values were authored during the Step-2 design sessions in a chat environment where no byte-level hash of the repository files was ever computed; the working explanation is that the stamps were authored, not machine-computed over these bytes. Pre-import drift is not excluded by evidence, but under either explanation the values are unrecoverable. Provenance boundary: commit 5aef7c4 (2026-09-03), clean tree for `docs/context/` — bytes as committed are the earliest verifiable state. Retained, never deleted.
**Place in the pipeline (brief §7):** deterministic checks in plain code run first, in stage order; then one LLM-as-judge call with structured output. generate → evaluate → one revision → ship or quarantine.
 
The rubric is the analyst's judgment artifact. It records rulings once; code enforces them per run. A criterion with no source is a design rule and carries its ruling ID as its source. Every checkable condition has exactly one owning entry; other entries cross-reference and never restate (assembly rule, P-2).
 
---
 
## 0. Preamble — definitions and rubric-wide rules
 
**0.1 Evaluator input (S-A).** Deterministic entries see the **report bundle**: rendered report + site page, adapter output (common schema), model output, frozen-set file, label config, intake sheet (stamped), gate-evaluation record, quarantine log, prior bundles. LLM-judged entries see the **rendered report + the flat data table (DET-57/DET-84) only** — no adapter internals, logs, or gate records.
 
**0.2 Stage map and consequences (S-B).**
 
| Stage | Runs on | Failure consequence |
|---|---|---|
| S0 | config integrity at pipeline start (label config, trigger table, sheet schema) | pipeline does not start |
| S1 | adapter output, before analysis | §8.1 Level 3 — data untrusted; nothing downstream computes |
| S2 | verifiability / model output, after computation | Level 2 — report not published; other tokens unaffected |
| S3 | rendered report and site page | data-consistency → Level 2; prose-only → fix-in-revision (one shot) |
 
**0.3 I-1 (ruled).** "Prose-only" = content of LLM-generated text sections. Anything template-rendered from data — bars, tables, flag strings, headline lines, per-cell figures — is data-consistency → Level 2. Revision re-prompts the LLM against an unchanged bundle; a template-rendered element regenerates byte-identical from the same bundle, so routing a template defect to revision burns the single revision on a no-op, guarantees the second failure, and misdiagnoses a template defect as a prose defect. Brief §6: numbers never originate from an LLM, so a wrong number is never a prose problem.
 
**0.4 Tolerances.** Replay of an arithmetic identity from identical inputs: relative 1e-6 (implementer default) unless the entry states exact/integer. Any tolerance comparing independently sourced quantities is a ruling and is cited by ID. **Rounding (R-7):** headline percentages at p = 1 decimal, **half-up** (round half away from zero) — named implementer default, applied identically by template and harness. Rendered-figure formatting per DET-89.
 
**0.5 Block pinning (R-13).** All Tier-1 contract reads in a run carry one block number (`run_block`); any deviation = Level 3. Scope: contract reads only — DefiLlama/Dune cross-validation is unpinned by nature; analyst-supplied and FIRST-RUN-VERIFY values are dated, not blocked.
 
**0.6 Definitions.** `supply_ruled` = mainnet `totalSupply()` + bridged-out supply on burn-and-mint bridges (§8.1.4(b)); "circulating supply" in memo §6.2.7 reads as `supply_ruled` (R-28). `backing_value` = Σ node values in the backed branch, unlisted weight U inside (R-6). `pinned block` = `run_block`. Lineage tags (R-15): every field feeding `backing_value`, metric 1, 2, or 3 carries a `lineage` tag naming its source chain; exclusion checks are written positively over lineage.
 
**0.7 Staleness principle (R-1, R-26, R-42).** Staleness bounds attach to inputs (enumerations and source config: 92 d → Level 1; freeze-coupled parameters: `date ≥ freeze_date` else Level 2); self-dating display metadata gets none.
 
**0.8 Present-and-empty (§14, R-9, R-38).** Schema slots exist on every token; absence is never the expression of "none". No `not_applicable` gate results except where an entry declares a token-scope condition.
 
---
 
## 1. Deterministic entries — execution order (S0 → S1 → S2 → S3; DET-13 last)
 
Entry format: **Checked** / **Pass** / **Type · Stage** / **Consequence** / **Source**.
 
### S0 — Config integrity
 
**DET-02 — Label config address-keyed; node classification fields (R-21)**
Checked: the §4 label lookup and node classification are address-keyed config. Pass: every config row has a unique `address`; node rows record `label_source_address` = own `address` (a match on any other field = fail); rows carry `node_class ∈ {volatile, stable}` and `lst_discount_applies ∈ {true,false}`, dated (DET-04 regime); (i) `lst_discount_applies = true ⇒ node_class = volatile`; (ii) every tree node with share > 0 has a `node_class`. Type: DET · S0 (S2 for the match record). Consequence: pipeline does not start / Level 2. Source: §9 gate 1 applied to §4.5; R-21.
 
**DET-12 — Declare-your-level: closed trigger table**
Checked: every quarantine event maps to a trigger in the printed table (§3 of this rubric) at its declared level. Pass: S0 — the runtime trigger table equals the printed table T-01…T-27 row for row (IDs, levels, `section`); S3 — every log entry has `trigger ∈` the table and `level` equal to the table's level for that trigger. Type: DET · S0 / S3. Consequence: pipeline does not start / Level 2. Source: §9 gate 11; §8.1.1 map; A-2.
 
**DET-77 — Sheet fields present, typed, dated; sheet version stamped (R-47)**
Checked: every sheet field another entry reads exists in ruled form on the stamped sheet version. Pass: report header `sheet_hash` equals the sheet version at the last logged `freeze` / `intake_trigger`; fields with owners: `near_bound_threshold` (DET-61), `m4_fields[]` = exact per-cell `m4` key set (DET-38), `sell_side_capacity` per volatile node (DET-52), `member2_target` (DET-50), `counterparties` literal (DET-73), `bias_table[]` (DET-53), `node_class` / `lst_discount_applies` (DET-02), `deviation` per feed (DET-55), `disclosure_cadence` / `last_disclosure_date` per recurses node (DET-76e), `first_run_reads[]` (DET-75), `origination_class` factory map (DET-07), `bridge_type` provenance (DET-33); a field consumed by any lineage but absent from the stamped version = fail. Type: DET · S0 / S1. Consequence: Level 3. Source: §4.5 P2 (sheets are freeze-time artifacts); §8.1.3; R-47.
 
### S1 — Adapter output, before analysis
 
**DET-83 — Pinned block freshness**
Pass: `run_start_time − block_timestamp(run_block) ≤ 3600 s` (named default); header prints both. Consequence: Level 3 (R-13 class). Source: G-4.
 
**DET-86 — First-run path gated on the log**
Pass: `first_run = true` only if the log has no published entry for the token; a published entry with no retrievable prior bundle ⇒ Level 3. Source: G-7.
 
**DET-01 — Address-keyed entities**
Checked: every enumerated row (collateral node, mint/lend market, frozen-set pool, paired asset, stabilizer operation, GSM, facilitator) is keyed by contract address. Pass: `address` matches `^0x[0-9a-fA-F]{40}$` on every row (lowercase compare); no row with null `address` and a set `symbol`; no duplicate `address` within a table. Symbol is display only. Consequence: Level 3. Source: §9 gate 1; §2; brief §10.
 
**DET-03 — Principal / interest separation (anti-tautology, C-2)**
Pass: per position and market-aggregate row: `principal`, `accrued_interest`, `gross_debt` present, ≥ 0, `gross_debt == principal + accrued_interest` exactly in integer base units; `gross_debt` (or its source pair) carries contract-read provenance; at least one of `principal` / `accrued_interest` carries its own read provenance — all three tracing to one read plus arithmetic = fail; no-accrual debt classes: `accrued_interest = 0` explicit with the read establishing no accrual. Consequence: Level 3. Source: §9 gate 2; §2.
 
**DET-04 — Enumeration provenance (checkable form of "no hardcoded lists")**
Pass: every DET-01 row carries exactly one of `discovery_provenance {source_contract, function, block = run_block}` or `analyst_supplied {source, date}`; PegKeeper rows: `source_contract` = regulator, `function = peg_keepers`; LUSD contract set = the permitted analyst-supplied form, dated; analyst-supplied enumeration with `date` older than 92 d ⇒ Level 1 `enumeration source stale` (T-16), persisting until refreshed. Consequence: Level 3 (missing provenance). Source: §9 gate 3; brief §6/§10; P4; R-1. Note: the code property "no list literal in the adapter" is unchecked by design (Appendix).
 
**DET-20 — Stabilizer operation rows complete; ceilings per-run reads (O8/A-4)**
Pass: per PegKeeper in the regulator-read set: `operation_address`, `paired_pool_address`, `paired_asset_address`, `debt_ceiling`, `current_debt`, `utilization`, `protocol_lp_share ∈ [0,1]`, `pool_composition_at_block[]`, `net_non_self_referential_value`, `residual`, `provenance` per read; keeper without row / row without keeper = fail; every `debt_ceiling` has contract-read provenance `ControllerFactory.debt_ceiling(pk)` at `run_block` (the Phase-B USDT figure is a first-run reconciliation point only); header `run_block` equals every Tier-1 provenance block (B-list patch). Consequence: Level 3. Source: §3 disclosure fields; §3c; P4; R-13.
 
**DET-09 — Discovery reconciliation (R-3)**
Pass: three totals with source IDs (deployments.json; DefiLlama; factory enumeration); `M = (max − min) / max` (denominator max — stated choice; median rule rejected: sources 1 and 3 overlap, O2); `M > 5%` ⇒ no report and Level 3 `discovery mismatch` (T-13); a report existing with `M > 5%` in its bundle ⇒ fail and DET-13 escalation. Consequence: Level 3. Source: §9 gate 8; §5.5; R-3.
 
**DET-10 — Frozen set integrity (C-1, D-1, R-4)**
Pass: (a) header `freeze_date`, `frozen_set_hash`; set-file hash equals the hash at the last log entry of type `freeze` / `intake_trigger`; (b) every modeled pool ∈ frozen set; (c) detector fields `new_pool_above_floor[]`, `frozen_pool_below_floor[]`, `frozen_pool_tvl_change_gt_50pct[]` present; (d) Level 2 `pool-set change` (T-10) for exactly two events: a detected new pool ≥ 10% of frozen-set coverage; a frozen pool that has **disappeared** — absent from on-chain factory enumeration at `run_block` (off-chain absence is DET-09 territory) — whose last-run share ≥ 10%; (e) below-floor and TVL-change detections disclosed as pool-table annotations, no further consequence — an undisclosed detection = fail; (f) `run_date − freeze_date > 100 d` ⇒ Level 1 `freeze overdue` (T-17). Consequence: (a) Level 3; (b)(d)(e) Level 2; (f) Level 1. Source: §9 gate 9; §5.5; §5.6; R-4; D-1.
 
**DET-29(a) — Frozen set file properties (R-16, R-20)**
Pass: set file fields `freeze_date`, `freeze_block`, `freeze_discovery_total`, `freeze_coverage`, per-pool `freeze_tvl`, `chain_id = 1`; TVL and coverage computed from on-chain pool balances at par (DefiLlama TVL never an input to selection); non-stabilizer pools `freeze_tvl ≥ 500,000` (stabilizer pools exempt, P-4); `freeze_coverage ≥ 0.95` — below without a waiver ⇒ Level 3 (malformed freeze); with a waiver record `{date, reason: "coverage unreachable at floor", achieved_coverage}` ⇒ per-run Level 1 `freeze coverage below target: N%` (T-20). Linkage: anticipates checklist 4.9 (LUSD floor check). Source: §5.5; §5.6; §5.2; R-16; R-20.
 
**DET-33 — Bridged / L2 supply disclosure (R-18, D-3)**
Pass: one row per bridge `{bridge_address, bridge_type ∈ {lock_and_mint, burn_and_mint, unresolved}, amount, provenance}`; `bridge_type` provenance mandatory — contract-property read (preferred) or `analyst_supplied {source, date}` under DET-04 — neither = fail; totals printed as figure and % of `supply_ruled`; Σ `burn_and_mint` amounts equals the bridged component of `supply_ruled` exactly; `lock_and_mint` disclosed, not added; `unresolved`: excluded from `supply_ruled`, row disclosed with amount, Level 1 `bridge type unresolved` (T-19), literal "supply may be understated by [amount]", persists until intake classifies; LUSD rows present even if negligible. Consequence: Level 3 (provenance) / Level 2. Source: §5.2; §8.1.4(b); R-18; D-3.
 
**DET-52 — Collateral-sell-side bound as disclosed assumption (R-26)**
Pass: every `node_class = volatile` node of crvUSD and GHO has `sell_side_capacity {value, source, date}`; printed as an analyst-supplied assumption with source and date; `date ≥ freeze_date` else Level 2; LUSD: literal "exempt — Stability Pool depositors receive collateral; no forced sale", no numeric; lineage of H1/H5 `collateral_sellable` ∈ {`sell_side_parameter`}; a volatile node without a parameter = Level 3. Source: §6.3 sell-side bound; §11.13; R-26.
 
**DET-55 — Oracle-dependency table complete (R-14b, R-46, O14)**
Pass: rows keyed `(node_address, market_or_reserve_address)` (default: crvUSD per mint market; GHO/LUSD per node); every tree node with share > 0 has a row; every GSM boxed asset has a row for its R-14(b) Chainlink feed (feed address on the DET-28 node row equals the row's `feed_address`); fields: `feed_or_source`, `update_condition {type ∈ {deviation_heartbeat, ema_window}, deviation, heartbeat_s | ema_window_s}`, `assumption_applied ∈ {instant, instant_optimistic_counterfactual, instant_with_fallback_counterfactual}`, `counterfactual_ref` (`EMA_lag` on every crvUSD row; `Tellor_fallback` on every LUSD row), `market_vs_protocol_oracle_gap` (R-49 column: protocol-oracle price vs. Chainlink at `run_block`, per node), `provenance`; `deviation` carries `analyst_supplied {source, date}` (class I); `heartbeat_s` = `{form ∈ {observed_max, documented}, value, provenance}`, `observed_max` preferred, neither = fail; `ema_window_s` contract read. Consequence: Level 3 (missing row for a priced node) / Level 2 (rendered incompletely). Source: §7.4; brief §12; R-14(b); R-46; R-49; O14.
 
**DET-62 — Supply jump, two-branch (R-36, R-53)**
Pass: `jump = |totalSupply_t − totalSupply_{t−1}| / totalSupply_{t−1}` on the mainnet `totalSupply` component only, unrounded, previous = last successful run; `jump > 0.25` ⇒ DefiLlama and Dune mainnet-`totalSupply` figures present (comparand = mainnet `totalSupply`, the one convention all three sources can be pinned to — stated on the sheet as a dated source note); confirms iff each is within 5% of `totalSupply_t` ⇒ Level 1 `supply jump, confirmed` (T-05), publish; either outside or either unavailable ⇒ Level 3 `supply jump, unconfirmed` (T-14); first run ⇒ no trigger, literal "first run — no prior supply"; `jump ≤ 0.25` ⇒ no trigger, figures still computed and disclosed. Bridged component: `|bridged_t − bridged_{t−1}| / bridged_{t−1} > 0.25` over burn-and-mint rows (DET-33) ⇒ Level 1 `bridged supply jump` (T-27); a logged bridge reclassification (`unresolved` → `burn_and_mint`) is the expected cause and the flag discloses it. Consequence: per branch; wrong route = Level 2. Source: §8.1.4(b); R-36; R-53.
 
**DET-63 — Market-count change, three-way**
Pass: count fields — crvUSD `mint_market_count` (lend counts logged, never triggered); GHO `collateral_reserves_with_nonzero_backing_count`, `gsm_count`, `facilitator_count`; LUSD `contract_set_count`; delta vs. last successful run: addition with node `address` in the label config ⇒ Level 1 `market addition, known node` (T-06); addition with unknown node ⇒ DET-08; removal ⇒ Level 2 `market removal` (T-12); LUSD any delta ⇒ Level 3 `count change, immutable protocol` (T-15); first run ⇒ no trigger, disclosed. Consequence: per route; wrong route = Level 2. Source: §8.1.4(c); crvUSD sheet.
 
**DET-66 — R-blocks complete per path (I-2 on record)**
Pass: `paths[]` per token; GHO `module_on_chain` paths = `gsm_count` (one per live GSM, P3; GSM identity by the DET-28 interface probe); LUSD one `direct_on_chain`; crvUSD one path `R1 = none` (present-and-empty). Per path: R1, R2 ∈ enum; R3 address list or `n/a` iff R1 = none; R4 ∈ {`face_value`, `face_minus_fee(range)`, `market`}; R5 figure or `none`; R6 ⊆ {`none`, `pausable`, `capacity_limited`, `state_conditional(C)`, `notice_period(N)`} with `none` exclusive; `C` references a bundle field; R7 resolvable field ref or `unbounded`; R9 ∈ enum; R10 `{contract, function}` + provenance or `{document, date}`; R1 = none ⇒ R2 = `no_one`, R3–R7 `n/a`, R9 present. Ruled contents: LUSD R6 = {`state_conditional(TCR<MCR)`, `capacity_limited`}; GHO GSM R6 = {`pausable`, `capacity_limited`}. Consequence: Level 3 (missing block) / Level 2. Source: §12; N-paths; P3; I-2.
 
**DET-68 — A1–A8 table complete, enum closed (R-38, R-39, R-40, A-7)**
Pass: all nine A1 rows always present, none-filled where unheld; one row per (power, holder) pair, A2–A5 scalar; A1 ∈ {`mint`, `set_ceiling`, `upgrade`, `pause`, `freeze_asset`, `blacklist_address`, `set_oracle`, `set_parameters`, `seize`} exactly; A2 = `{address, type ∈ {eoa, multisig(m-of-n), dao_governance, timelock, contract_automated, none}}`, `m ≤ n`; `contract_automated` holders carry an interface-probe provenance (DET-46 `checkUpkeep` or equivalent); A3 present iff multisig `{count = n, identity ∈ {disclosed, partial, undisclosed}}`; A4 `{seconds, bucket}` with bucket replay: `0 → none`; `[1, 86399] → <24h`; `[86400, 604800] → 1–7d`; `> 604800 → >7d`; A5 `{address, power ∈ {cancel, pause}}` or `none`; A6 ∈ {`immutable`, `proxy_upgradeable`}, proxy `admin` equals the `upgrade` row's A2 address; A7 address list, non-empty where A2 ≠ none; A8 `{contract, function, block = run_block}`; each concrete function maps to exactly one A1 value. Consequence: Level 3 (rows/provenance) / Level 2 (replays). Source: §13; R-38; R-39; R-40; A-7.
 
**DET-71 — LUSD empty-surface control (R-41)**
Pass: nine rows with A2 = none, A6 = `immutable`, A8 = reads establishing absence (no `owner()`, EIP-1967 slots zero, no pause function) at `run_block`; qualifier = immutable literal. Any LUSD row with A2.type ≠ none, or any missing row ⇒ Level 3 (immutable-protocol impossibility class). Source: §13 control case; §14; R-41 (extending §8.1.4(c)).
 
**DET-75 — FIRST-RUN READ tags resolved to reads (R-45)**
Pass: the sheet section `first_run_reads[]` (produced at intake, dated, versioned under R-47) lists `{tag_id, sheet_location, bundle_field_path, read_spec, status ∈ {open, resolved{first_run_date}}}`; for every row the bundle field exists, is non-null, and carries `{source_contract, function, block = run_block}`; `analyst_supplied` or absent provenance = fail; count of `status = open` rows equals the count of FIRST-RUN READ tags on the stamped sheet version (resolved rows persist after prose tags retire); O18: the USDC keeper row carries only the `debt_ceiling` read. Named coverage: controller factory enumeration; per-market oracle contract and `MA_EXP_TIME`; `AMM.A()`/bands; lend factory addresses; PegKeeper set and ceilings; regulator `emergency_admin`; bridge balances and lock-vs-burn; attribution reads; `getFacilitatorsList`/`getFacilitatorBucket`; `getExposureCap` / exit-direction fee; GSM role members and freezer bands; Aave reserve configuration and eMode; per-feed heartbeats; Liquity registry addresses; `TroveManager.priceFeed()`; all admin-surface `[live value]` cells; tBTC WalletRegistry read; LUSD discovery / floor check. Consequence: Level 3. Source: sheet conventions; §15 method; brief §6; R-45.
 
**DET-76 — FIRST-RUN-VERIFY items**
Pass: (a) GHO bucket identity (R-8): first run computes `Σ facilitator bucket levels − totalSupply()` at `run_block`; 0 ⇒ sheet field `gho_bucket_identity {verified: true, block, date}`; ≠ 0 ⇒ Level 2 (DET-15) and `verified: false` with residual. (b) feed parameters per DET-55 (deviation class I; heartbeat per R-46). (c) tBTC: WalletRegistry read recorded with provenance; label on every run ∈ {`terminal_other_layer`, `recurses`} with `label_provenance = WalletRegistry read @ block`. (d) LUSD floor check: first discovery run records `pools_above_floor_count`, `achievable_coverage`; `< 0.95` requires the R-20 waiver (DET-29a). (e) every `recurses` node has `disclosure_cadence` and `last_disclosure_date` with provenance (on-chain PoR read where available; else analyst-supplied dated, class I) — missing = Level 3 (staleness uncomputable). Source: R-8 directive; O14; §4.4; §5.5 bracket; R-20.
 
**DET-82 — Position-set completeness (crvUSD, LUSD, GHO secondary)**
Pass: per crvUSD market `Σ position gross_debt` vs `Controller.total_debt()`; LUSD `Σ trove debt` vs `ActivePool.getLUSDDebt() + DefaultPool.getLUSDDebt()`; GHO per reserve `Σ position collateral` vs `aToken.totalSupply()`; relative tolerance 1e-9 (named default: same contract's rate-multiplier arithmetic vs. orders-of-magnitude enumeration miss). Beyond ⇒ Level 3. Source: G-3.
 
### S2 — Verifiability and model output
 
**DET-05 — Stabilizer netting (R-14a)**
Pass: (a) no backed-branch node with `address` = the token's own address or a stabilizer operation address; (b) stabilizer slice `credited_backing_value == 0` exactly; (c) `net_non_self_referential_value = protocol_lp_share × paired_asset_balance_at_block × 1.00` (par), 1e-6; (d) `residual = lp_position_value − debt`, 1e-6; (e) owned by DET-25. Consequence: Level 2. Source: §9 gate 4; §3a; §3d; R-14(a).
 
**DET-06 — Position netting (R-2)**
Pass: (a) token's own address in no §4 node row; (b) `net_debt = max(gross_debt − stablecoin_in_position, 0)`; `surplus = max(stablecoin_in_position − gross_debt, 0)`; (c) base-state collateralization replays as `Σ external_collateral_value / Σ net_debt` (floored), 1e-6; (d) Σ `stablecoin_in_position` and Σ `surplus` disclosed ("held stablecoin exceeding debt, not netted"); surplus never reduces any aggregate. Consequence: Level 2. Source: §9 gate 5; §2; R-2.
 
**DET-07 — Supply origination (mint vs. lend)**
Pass: every market row `origination_class ∈ {mint, lend}` assigned from the factory address in its provenance (assignment from any non-address field = fail); backed branch sums collateral over `mint` rows only; `lend` rows present in the bundle and in the disclosed lend-market count, in no backing, supply, or stress input; `lend_market_count = n/a` explicit where no lend class. Consequence: Level 2. Source: §9 gate 6; crvUSD sheet; brief §10.
 
**DET-08 — Unlisted node routing (R-6)**
Pass: `label ∈ {terminal, terminal_other_layer, recurses, recurses_truncated, unlisted}` case-exact (any other value = fail); U = Σ `unlisted` share of `backing_value` (U inside the denominator, R-6); U ≥ 5% ⇒ no report, Level 2 `unlisted node ≥ 5%` (T-09); 0 < U < 5% ⇒ report exists, literal "N% of backing unclassified — pending intake" (N = U at p = 1), Level 1 (T-01), persists across runs; U = 0 ⇒ no flag. Cumulative rule inherent (U is a sum). Consequence: Level 2 — routing and the template-rendered flag literal alike (I-1, AP-1); the prose explanation of the flag is LLM-05's. Source: §9 gate 7; §8.2; §4.2; R-6.
 
**DET-11 — Paired-asset labeling (R-5, R-27)**
Pass: per pool, each paired-asset row: `address` + label from the four, or `label = composite` with constituent rows (weights Σ = 1 ± 1e-6; any unlisted constituent ⇒ LP token unlisted, §4.3 guard), or `label = linked` with `source_tree = <token>@<publication date>` (last published tree) or `recurses_truncated` + Level 1 "analyzed token, tree pending"; unlabeled: `q` = share of frozen-set exit depth at s = 2% on K-subset(0.90); `q ≥ 5%` ⇒ Level 2 `unlabeled paired asset` (T-18), no report; `q < 5%` ⇒ Level 1 (T-18), pool stays modeled, row `label = unlabeled` disclosed, shock factors per DET-42 (par in target cells, 0.93 in the compound tail — R-27), flag persists until labeled; concentration line present (largest paired asset, share of exit depth, label, disclosure source). Consequence: per branch; missing concentration line = Level 2 (template-rendered). Source: §9 gate 10; §5.3; §4.1; §4.3; §5.6; R-5; R-27.
 
**DET-81 — Collateral-node pricing source (R-49)**
Pass: every node value in `backing_value` and every position collateral value is priced by the protocol's own oracle at `run_block` (LLAMMA `price_oracle()` per market; `AaveOracle.getAssetPrice`; Liquity `PriceFeed` `lastGoodPrice`) with `price_source` provenance per node, lineage `price_read`; R-14 scopes stand (par for stabilizer disclosed values; Chainlink at `run_block` for GSM boxed assets); the per-node market-vs-protocol-oracle gap is disclosed in DET-55's column. Staleness of any credited price read: `block_time − round_updatedAt ≤ 2 × heartbeat_s` (2× named default) else Level 1 `credited price feed stale` (T-26). Consequence: Level 2 (source/provenance); Level 1 (staleness). Source: R-49; R-50; R-14.
 
**DET-14 — Backed-branch composition sums (R-6, R-7, D-2)**
Pass: (a) Σ node `value` (backed branch) = `backing_value`, 1e-6; (b) `Σ classified shares + U = 1 ± 1e-6`; (c) printed sum of rendered segments within `n × 0.05` of 100, n = rendered segments (three bars + U segment iff U > 0); (d) each printed value = `round_half_up(share, 1)`. Type: DET · S2 (a,b) / S3 (c,d). Consequence: Level 2. Source: §4.6(i); brief §7; R-6; R-7.
 
**DET-15 — Supply decomposition and reconciliation (R-8)**
Pass: (a) `supply_ruled` replays from `totalSupply` read + Σ burn-and-mint bridged reads (DET-33), each with provenance; (b) origination sum `O` per token: crvUSD Σ `principal` + Σ stabilizer `debt`; GHO Σ facilitator bucket levels; LUSD Σ trove `gross_debt` incl. gas compensation — terms traceable to DET-03/DET-05 fields; (c) `residual = supply_ruled − O` printed with named causes per token; unexplained part (residual − disclosed cause fields) ≤ 0.1% of `supply_ruled`; GHO override 0 (identity claim FIRST-RUN-VERIFY, DET-76a); (d) one `supply_ruled` field is the sole denominator behind every "% of supply" line (stabilizer line, metric 2 %, bridged %; the §8.2 N is over backing). Consequence: Level 2. Source: §4.6(i); §3; §8.1.4(b); R-8; R-28.
 
**DET-16 — Stabilizer-over-supply line (R-9)**
Pass: `X = Σ stabilizer debt / supply_ruled`, 1e-6; printed per R-7; appears in no bar and no backed-branch share; distinct from the three-bar headline; present on every token unconditionally — tokens with no stabilizer class print exactly "0% — no stabilizer mechanism"; no `not_applicable` permitted. Consequence: Level 2. Source: §4.6(i); §3; R-9.
 
**DET-19 — Denominator discipline**
Pass: every percentage in the headline block carries `denominator ∈ {backing_value, supply_ruled}` in the flat table; backed-branch shares and bars → `backing_value`; stabilizer line, metric 2 %, bridged % → `supply_ruled`; a headline figure without a denominator field, or not replaying against its declared denominator, = fail. Consequence: Level 2. Source: §4.6(i).
 
**DET-21 — Utilization, LP share, residual replay (R-11, R-14a)**
Pass: `utilization = current_debt / debt_ceiling`, 1e-6, except `debt_ceiling = 0` ⇒ row prints "n/a — ceiling 0", ratio replay skipped, other field checks apply; utilization > 1 permitted and disclosed as > 100%; `protocol_lp_share = keeper_lp_balance / pool_lp_total_supply`, 1e-6; `residual` per DET-05(d), sign unconstrained; disclosed values valued at par with the rendered caption "valued at par". Consequence: Level 2. Source: §3 fields; §3d; R-11; R-14(a).
 
**DET-23 — Zero-credit in every aggregate (P-2, P-3, R-15)**
Pass: (a) owned by DET-05(b); (b) no `operation_address`, `paired_pool_address`, or keeper LP token address in the §4 node table, the backing sum, or any per-cell `collateral_value` input; (c) every field feeding `backing_value`, metric 1, 2, 3 carries `lineage`; the lineage set of each aggregate ⊆ {`collateral_read`, `debt_read`, `price_read`, `attribution`, `model_*`} and contains no `stabilizer_*` [source: R-15]; (d) the slice sits inside `supply_ruled` and outside `backing_value` — decomposition owned by DET-15. Consequence: Level 2. Source: §3; §3a; §3d; §9 gate 4; R-15.
 
**DET-24 — Stabilizer pools enter exit depth in full (P-4)**
Pass: for every stabilizer paired pool: depth-model input balances equal `pool_composition_at_block` exactly (no LP-share reduction); a stabilizer pool absent from the frozen set = fail with no permitted exclusion reason (neither §5.4 nor the §5.5 floor — stabilizer pools are floor-exempt); `paired_asset_address` labeled per DET-11 (frxUSD expected to route to T-18 on the first crvUSD run — the gate working). Consequence: Level 2. Source: §3b; §5.4; P-4.
 
**DET-25 — Stabilizer debt excluded from forced-sell volume, every cell (R-15)**
Pass: for all cells, the lineage set of `forced_sell_volume` contains no `stabilizer_*` source; Member 1 `forced_sell_volume = bad_debt` identity, 1e-6 (bad-debt arithmetic: DET-40). Sole owner of the per-cell exclusion. Consequence: Level 2. Source: §3b; §6.2.7; R-15.
 
**DET-26 — Crash-path trajectory (Member 1)**
Pass: every Member 1 cell and the joint cell: `m4.stabilizer_debt_post_cell`, `ceiling_aggregate`, `utilization_post_cell` (replay 1e-6); `stabilizer_debt_post_cell ≥ current_debt`. Consequence: Level 2. Source: §3 crash path; §6.2.7 m4.
 
**DET-27 — Confidence-crisis burn capacity (Member 2) (R-12)**
Pass: every Member 2 cell and compound tail: `m4.burn_capacity == current_debt` at `run_block` (exact integer); any derivation from `debt_ceiling` = fail; `withdraw_allowed` state reads present; metric 4 prints quantities only (LP share, paired-asset units held, pool tilt post-cell) — any shocked-price USD figure = fail. Consequence: Level 2. Source: §3 confidence-crisis path; §3d; R-12.
 
**DET-28 — Asset-in-a-box exclusion honored (R-14b)**
Pass: no GSM address in the stabilizer table; each live GSM's boxed asset is a backed-branch node with its §4 label and `value = boxed_asset_balance × chainlink_price`, both reads with provenance at `run_block`, feed address recorded on the node row (DET-55 row required); GSM-minted supply inside `backed_supply` (DET-15); `gsm_count = 0` explicit where no GSM class. A facilitator is classified as a 1:1 swap module iff it answers a GSM-signature staticcall probe (`getExposureCap` / `getAvailableLiquidity`-class functions respond at `run_block`), probe result recorded with provenance (PQ-1 ruled; a probe-miss errs conservative in every direction — no credited boxed asset, no venue, no §12 path — and DET-63's `facilitator_count` T-06 puts a human eye on any new facilitator). Consequence: Level 2. Source: §3 exclusion; §5.10; §14; R-14(b).
 
**DET-22 — Stabilizer slice, ceiling bound, labels (R-12)**
Pass: supply-decomposition row labeled exactly "protocol stabilizer debt" with `value = Σ current_debt` (1e-6) and % of supply per DET-16; `ceiling_aggregate = Σ debt_ceiling` printed as figure and % of `supply_ruled`, captioned as the slice's upper bound; per-operation rows list ceiling and utilization (table may be empty under R-9); net position value line carries "pro-cyclical, non-credited" and "valued at par"; no scenario-conditional or shocked-price value of the position anywhere, no exception. Type: DET · S2 / S3. Consequence: Level 2. Source: §3; §3c; §3d; §4.6(i); R-12.
 
**DET-29(b)(c) — K-subset selection replay and coverage figures**
Pass: (b) pools in F sorted by `tvl_at_run_block` (on-chain balances at par) descending, tie-break ascending address (named default); K-subset(K) = shortest prefix with Σ tvl ≥ K × Σ_F tvl; headline modeled set = K-subset(0.90) exactly; (c) printed K-subset share ≥ 90% (1e-6) and the §5.7 one-liner with `[freeze date]` = `freeze_date`, template text exact. Type: DET · S2 / S3. Consequence: Level 2. Source: §5.5; §5.7; R-16.
 
**DET-30 — Sensitivity table: exactly three rows, headline cell only**
Pass: rows K ∈ {80, 90, 95} in order; each row = exit depth at s = 2% and headline metric 3 (Member 1, −50%, LST 0%, LP 0%); row sets = K-subset(K), all ⊆ F; row 95 = F; depth(80) ≤ depth(90) ≤ depth(95) exact; row 90 equals the main report's headline figures exactly; no sensitivity rows for any other cell; no pool outside F. Consequence: Level 2. Source: §5.7; §6.2.6.
 
**DET-31 — Depth curve: four points, s = 2% headline (R-17)**
Pass: exactly s ∈ {0.005, 0.01, 0.02, 0.05}; `depth(s)` non-decreasing; computed on K-subset(0.90) at current composition, par numeraire; `depth(0.02)` equals the headline cell's `exit_depth` (1e-6); per-pool depths sum to the printed total (1e-6). Verification: at s = 2%, `eth_call get_dy` per pool at `run_block` around the pipeline's per-pool depth (finite difference); implied marginal price ∈ [1 − s − ε, 1 − s + ε], ε = 0.05%; at the other three points the harness re-invokes the pipeline's depth function (wiring check); a `get_dy` revert or unsupported interface at `run_block` ⇒ Level 3. Consequence: Level 2 / Level 3 as stated. Source: §6.1.1–6.1.3; §5.8; R-17.
 
**DET-32 — Off-venue share and 25% trigger (O9)**
Pass: `dex_liquidity_total_discovered`, `curve_mainnet_liquidity`, `X = 1 − curve/total` (1e-6), mainnet-only on both sides (L2 DEX liquidity never enters); literal "X% of discovered DEX liquidity lies outside modeled venues" per R-7; unrounded `X > 0.25` ⇒ Level 1 `off-venue share > 25%` (T-02), publish, dated open-point entry (§11.6); any component unavailable ⇒ literal "off-venue share: not computed", no numeric X, Level 1 `off-venue share not computed` (T-22); `exit_depth` lineage contains no `offvenue_*`. Consequence: Level 2 for a missing line, X without components, or a wrong route. Source: §5.1; §11.6; §11.12; O9.
 
**DET-34 — §5.4 exclusion reasons per excluded pool**
Pass: every discovered on-Curve pool (≥ floor, mainnet) not in F carries exactly one `exclusion_reason ∈ {non_market_contract, volatile_collateral_circular, tail_beyond_freeze_coverage, added_since_freeze}`; `volatile_collateral_circular` valid only if the paired asset's `address` is a `node_class = volatile` node of the token — a stablecoin-collateral pool carrying it = fail; `non_market_contract` only for non-pool addresses; `added_since_freeze` disclosed via DET-10; stabilizer pools owned by DET-24; below-floor pools at freeze recorded in `excluded_at_freeze[]` with `below_dust_floor`. Consequence: Level 2. Source: §5.4; §5.5; §5.6.
 
**DET-35 — §5.10 GSM deterministic venue (R-19, PQ-2, R-25)**
Pass: per live GSM: `fee_exit` (fee on stablecoin → boxed asset) read from the fee strategy at `run_block` (both directions disclosed if they differ); included at each curve point s iff `fee_exit < s` (strict; at 0.2% the GSM enters all four points); contribution = boxed balance read, listed under "deterministic venue (GSM)", not inside the pool-depth line; `total_exit_depth(s) = pool_depth(s) + Σ gsm_contribution(s)` (1e-6); excluded ⇒ literal "GSM [addr] excluded — fee ≥ [s]"; Member 2 cells with H2 routing `freezer_effective`: cell `exit_depth` lineage contains no `gsm_*` and the report states the removal; `freezer_fails`: contribution remains; `is_frozen` or `is_seized` at `run_block` ⇒ excluded in all cells incl. base, literal "GSM [addr] frozen at block N — venue closed" ("seized" wording), Level 1 `GSM frozen at base` (T-21), report publishes; base-frozen is not a routing contradiction. Consequence: Level 2 / Level 1 as stated. Source: §5.10; §6.3 H2; R-19 (rubric-level generalization); PQ-2; R-25.
 
**DET-37 — Cell set exact (47 / 23)**
Pass: unique cell IDs; Member 1 shock {−0.20, −0.35, −0.50, −0.70} × LST {0, 0.05, 0.10} × LP {0, 0.30, 0.60} = 36; Member 2 target {0.97, 0.93, 0.88} × LP {0, 0.30, 0.60} = 9; compound tail 1; joint 1; total 47; LST axis collapses (Member 1 = 12, total 23) iff no node with `lst_discount_applies = true` and share > 0; other count = fail; joint and compound cells labeled "compound scenario", printed once; no axis beyond the four; a counterfactual ID as an axis = fail. Consequence: Level 2. Source: §6.2.6; §6.3 design rule; R-21.
 
**DET-38 — Four metrics per cell, no composite**
Pass: per cell `m1 = {pre: {ratio, share_below_100}, post: {…}}`, `m2 = {bad_debt, pct_supply}`, `m3 = {ratio, forced_sell_volume, exit_depth}`, `m4 = {…}` = the sheet's `m4_fields[]` key set exactly; no composite field (`hours_to_depeg` or any cross-metric aggregate) anywhere; `m3.ratio` marked panel headline; `m1.post` marked headline reading. Consequence: Level 2. Source: §6.2.7; brief §11.7.
 
**DET-39 — Metric 1: two readings, post headline, gap visible**
Pass: `m1.pre.ratio = Σ_mint-positions collateral × f_node / Σ net_debt_base` with `f = (1 + shock)(1 − d)` for volatile nodes (d only where `lst_discount_applies`), `f = 1` for stable nodes in Member 1, `f = target` for shocked-stable nodes in Member 2 — replay 1e-6; denominator = DET-06 floored net debt, identical to base; `m1.pre.share_below_100` = supply-weighted share of positions with CR < 1 under the same factors; `m1.post.*` wiring-check; `gap = post − pre` printed; post carries the headline mark; denominators' lineage ⊆ {`debt_read`, `position_netting`}. Consequence: Level 2. Source: §6.2.7 m1; §6.2.2; §9.
 
**DET-40 — Metric 2: bad debt (R-29)**
Pass: `bad_debt ≥ 0`; `pct_supply = bad_debt / supply_ruled` (1e-6); definition per token via lineage (LUSD: redistributed positions below 100% CR, DET-51); monotonicity gate: `bad_debt` non-decreasing along the shock, LST, and LP axes at fixed other axes (exact) [source: R-29]. Consequence: Level 2. Source: §6.2.7 m2; §6.2.1; R-29.
 
**DET-41 — Metric 3: depeg-pressure ratio per cell (R-29 extension)**
Pass: `m3.ratio = forced_sell_volume / exit_depth_cell` (1e-6); Member 1 numerator: DET-25; other cells: DET-42; `exit_depth_cell`: Member 1 = depth(2%) on K-subset(0.90) after single-sided withdrawal of the cell's LP-flight share (wiring-check; LP-0 equals DET-31 `depth(0.02)` exactly); Member 2 = par-terms recomputation against shocked paired assets (wiring-check), GSM per DET-35; lineage ⊆ {`depth_model`, `gsm_read`}, no `offvenue_*`; ratio > 1 rendered with the panel mark; headline-cell `m3` = DET-30 row 90; monotonicity: `m3.ratio` non-decreasing along the LP axis (fixed shock, LST) and along the Member 1 shock axis (fixed LST, LP) [source: R-29]. Consequence: Level 2. Source: §6.2.7 m3; §6.1.4; §6.2.5; R-29.
 
**DET-42 — A2 numerator rules (R-27, R-28)**
Pass: Member 2 target cell: `forced_sell = gsm_boxed_supply(shocked stable) + attributed_slice(shocked stable-collateral nodes)` (§11.1 pro-rata, DET-64), full slice — lineage contains no price or depeg factor; crvUSD/LUSD: 0 with `reason = structurally_insulated`; compound tail: the same over all `recurses` paired stables, incl. unlabeled; joint: `bad_debt_joint + m2_slice_joint` within the cell (1e-6); factor rows: linked (analyzed-set) paired assets 1.0 in every Member 2 cell; unlabeled paired assets 1.0 in target cells and 0.93 in the compound tail; compound-tail literal "compound scenario — all disclosure-dependent paired stables, incl. unlabeled [addr]" (the `incl.` clause iff an unlabeled asset exists); numerator lineage ⊆ {`supply_attribution`, `gsm_supply`, `liquidation_model`} — any `backing_*`/`collateral_*` = fail; `pct_supply` and every stress-panel "% of supply" over `supply_ruled`; no `circulating_*` field exists. Consequence: Level 2. Source: §6.2.7 forced-sell; §6.2.5; §11.1; R-15; R-27; R-28.
 
**DET-43 — Structural-insulation presentation (R-22)**
Pass: tokens with no `node_class = stable` node and `gsm_count = 0`: all Member 2 and compound `m3.ratio = 0` exactly; literal "structurally insulated; exposed through exit venues only"; three four-point recomputed depth curves (targets 0.97/0.93/0.88, LP 0), twelve values, each replaying against the corresponding cell's `exit_depth` at s = 2% (1e-6), s = 2% marked; `m4` mechanism quantities per DET-27 / DET-51. Prose obligation: LLM-06. Consequence: Level 2. Source: §6.2.5; R-22.
 
**DET-44 — Counterfactual lines: present, under metric 4, never cells (R-23, R-24)**
Pass: `counterfactual_lines[]` per cell `{id, assumption_text, metric_affected, value_primary, value_counterfactual, approximation_flag}`; required IDs: crvUSD `H1_kill` (Member 1 + joint; counterfactual = zero PegKeeper contribution; replay of the cell's m2/m3 with capacity 0 — wiring-check), `H1_v1_contagion` (Member 2 + compound + joint), `EMA_lag` (Member 1 + joint; literal "bounded approximation — not full EMA band-crossing dynamics", `approximation_flag = true`, window = the per-market `MA_EXP_TIME` read); GHO `H2_freezer` (Member 2 + compound + joint; direction per DET-46); LUSD `Tellor_fallback`: content = the three verified constants (14400 s; 50%; 5%) with contract-constant provenance + literal "modeled outcome unchanged under primary; fallback engaged does not alter stock-only capacity", `metric_affected = none`, rendered once per member (the R-24 exception). All other lines render per cell in the full table, headline cell's lines repeated in the panel. Missing required ID = fail; an ID as a cell axis = fail. Consequence: Level 2. Source: §6.3 design rule; H1; H2; §7.2; §7.3; R-23; R-24.
 
**DET-45 — H1 effective vs. naive headroom (O12/A-5)**
Pass: per keeper at `run_block`: `is_killed` (Provide, Withdraw), `alpha`, `beta`, `debt_i`, `balance_i` with provenance; `r_j = debt_j / (debt_j + balance_j)` (0 where denominator 0); `allowed_i = min((α + β·Σ_j√r_j)² × (debt_i + balance_i) − debt_i, debt_ceiling_i − debt_i)`, floored at 0; killed-Provide keepers contribute 0; `effective = Σ_live allowed_i`; `naive = Σ max(debt_ceiling_i − debt_i, 0)`; both printed under metric 4 with the literal "effective vs. naive ceiling headroom"; `effective ≤ naive` exact; killed keepers listed; every Member 1 cell's crash-path capacity term = `effective` (1e-6). Consequence: Level 2 (Level 3 if a read is missing). Source: §6.3 H1 (C1 option iii); §15.1; O12; A-5.
 
**DET-46 — H2 state-conditional routing (PQ-4, R-25)**
Pass: per live GSM: `freezer_role_holders[]` (all `getRoleMember(SWAP_FREEZER_ROLE, i)`), `automated_freezer_present` = at least one holder is a contract answering a `checkUpkeep` STATICCALL at `run_block` (probe recorded with provenance; upkeep registration/funding not checked — carried by the counterfactual line), `freeze_lower_bound`, `freeze_upper_bound`, `unfreeze_bounds`, `can_unfreeze`, `is_frozen`, `is_seized`; `check_pass = automated_freezer_present ∧ freeze_lower_bound ≥ 0.88`; `routing = freezer_effective` iff `check_pass` (base-frozen GSM: trivially `freezer_effective`), else `freezer_fails`; DET-44 `H2_freezer` primary/counterfactual labels in the routing's direction; any `check_pass = false` ⇒ Level 1 `GSM freezer check failed` (T-08) with the literal "automated freeze protection not currently in place / not effective in modeled range (checked at block N)"; pass ⇒ template sentence "…automated freezer currently holds the role, with bands verified effective in the modeled range (block N)"; depth removal owned by DET-35. Consequence: Level 2. Source: §6.3 H2 (Item 1.2); P3; PQ-4; R-25.
 
**DET-47 — H5 which side binds (PQ-5, D-4)**
Pass: per Member 1 and joint cell: `gho_sourceable = pool_buy_side_depth + gsm_mint_headroom` (mint-direction fee and `getExposureCap()` reads; buy-side depth bounded by the minimum liquidation bonus across the cell's shocked reserves, each from `getReserveConfigurationData`, bound and source printed in the assumptions line); `collateral_sellable = Σ_shocked-nodes sell_side_parameter`; `capacity = min(...)` (1e-6); `binding_side` = argmin, printed under metric 4; tie (exact equality) ⇒ `collateral_sellable`, equality noted (named default); facilitator bucket levels/caps printed under metric 4, not in `capacity` lineage. Consequence: Level 2. Source: §6.3 H5; PQ-5; D-4.
 
**DET-48 — Shock grid exact; reference points context-only**
Pass: every `node_class = volatile` node receives the cell's shock; `stable` nodes none in Member 1; per volatile node a reference row `{worst_7d_drawdown, window_start, window_end, source, provenance}` with the source's asset resolved by address (never symbol; B-list patch), or literal "reference point unavailable" (no block, no flag); lineage of every metric contains no `reference_*`. Consequence: Level 2 (missing row without the literal); pass with the literal. Source: §6.2.1; §6.2.2; §11.7; R-15; R-21.
 
**DET-49 — LST-discount axis as modifier**
Pass: `d ∈ {0, 0.05, 0.10}` applied as `× (1 − d)` only where `lst_discount_applies = true`; other nodes identical `f_node` across the LST axis (exact); headline cell and panel use `d = 0`; axis rendered as a labeled modifier column; no headline line references a `d > 0` cell; LUSD: axis absent, no `d` field rendered. Consequence: Level 2. Source: §6.2.2; §6.2.6; R-21.
 
**DET-50 — Target stable, compound tail, joint cell**
Pass: `member2_target` recorded in the set file at freeze = the `recurses` paired stable (directly or via composite constituents) with the largest share of frozen-set exit depth at freeze; printed in every report with the freeze date; not re-selected per run (identity with set file); compound tail: every `recurses` paired stable at 0.93, LP 0, once, with the DET-42 literal; joint cell axes exactly (−0.50, 0.93, LST 0, LP 0) with "compound scenario — collateral crash × paired-stable depeg"; linked paired assets unshocked in both (factor check owned by DET-42). Consequence: Level 2. Source: §6.2.5; §6.2.6.
 
**DET-51 — LUSD H3 / H4 specifics**
Pass: Member 1 capacity lineage = {`sp_balance_read`} (`StabilityPool.getTotalLUSDDeposits()` at `run_block`); `sp_effective_cell = sp_balance × (1 − LP_cell)` (1e-6); per cell under m4: `redistributed_debt`, `redistributed_positions_below_100 → bad_debt` (identity with `m2.bad_debt`, 1e-6), `tcr_post`, `recovery_mode_flag = (tcr_post < 1.50)`; CCR = 1.50, MCR = 1.10 as contract-constant reads; H4: `redemption_capacity` present in Member 2, compound, and joint only (Member 1: absent or `0, reason = "crash path excluded"`); capacity = LUSD redeemable before `baseRate + 0.5% > 2%` from the base-rate schedule (wiring-check; `baseRate` read); state gate: `tcr_cell < 1.10` ⇒ `redemption_capacity = 0, reason = "TCR < MCR"` (exact). Consequence: Level 2. Source: §6.3 H3, H4; §12 `state_conditional`.
 
**DET-61 — Mechanism near bound (R-34, R-35)**
Pass: utilization `u` of any bound with `u = 1` at the bound (upper: `debt / ceiling`; lower: `CCR / TCR`), fires at `u ≥ near_bound_threshold` (sheet field, default 0.80) ⇒ Level 1 `mechanism near bound` (T-07) naming the instance; instances: crvUSD `pk_keeper_[addr]` and `pk_aggregate` (texts "keeper [addr] at N% of ceiling" / "aggregate stabilizer utilization at N%"; ceiling-0 keepers skipped); GHO `gsm_[addr]` (exposure / cap), `facilitator_[addr]` (bucket level / cap); LUSD `recovery_mode` (`1.50 / TCR ≥ 0.80`, i.e., TCR ≤ 187.5%). Consequence: Level 2 for a missed fire. Source: §8.1.4(d); R-34; R-35.
 
**DET-64 — GHO collateral attribution (§11.1; R-37)**
Pass: `attribution_method ∈ {per_position, protocol_level_fallback, direct}` printed (crvUSD/LUSD: `direct`); primary `backing_value = Σ_positions collateral × (gho_debt / total_debt)`, 1e-6 from per-position reads (`getUserReserveData` verification); completeness `|Σ gho_debt(positions) − aave_facilitator_bucket_level| / bucket_level ≤ 0.001`, beyond ⇒ route to the protocol-level fallback; cross-check `protocol_ratio = aggregate_collateral / aggregate_debt`, `protocol_level_backing = protocol_ratio × aave_facilitator_gho_supply`, always computed and printed; `divergence = |primary − protocol_level| / protocol_level` (denominator: named default); > 0.10 ⇒ finding literal "GHO borrowers are systematically [more | less] collateralized than the Aave average (divergence N%)" — never suppressed, no trigger; ≤ 0.10 ⇒ "within 10% tolerance (N%)"; fallback: `backing_value` from `protocol_level_backing`, literal "attribution: protocol-level fallback", Level 1 (T-03); previous successful run also fallback ⇒ Level 2 (T-11), no report; lineage consistency with the printed method. Consequence: Level 2. Source: §11.1; GHO sheet; R-37.
 
**DET-65 — Composition shift (D-5)**
Pass: per node, `share_t` vs. share at the last successful run; `|Δshare| > 0.10` on any node or a changed top-3 set ⇒ Level 1 `composition shift` (T-04) naming the node(s); unrounded shares; first run ⇒ literal "first run — no prior composition". Consequence: Level 2 for a missed fire. Source: §8.1.4(a).
 
**DET-67 — R8 computed, never hand-keyed (I-2, R-43)**
Pass: `r8_source = computed`; derivation: R1 = none ⇒ `n/a`; R1 ∈ {direct, module}: base `enforceable`; `pausable ∈ R6` ⇒ append `_unless_paused`; `state_conditional(C) ∈ R6` ⇒ append `_unless_[C]` (joined as `_unless_paused_or_[C]` when both); `capacity_limited ∈ R6` ⇒ append ` (see R7)` regardless of other members; `notice_period(N)` ⇒ ` (N-day notice)` last; R1 = issuer_offchain ⇒ `discretionary`, or `enforceable_offchain` iff R9 = yes ∧ R6 = none; string equality. Verified: GHO GSM → `enforceable_unless_paused (see R7)`; LUSD → `enforceable_unless_TCR<MCR (see R7)`; crvUSD → `n/a`. Consequence: Level 2. Source: §12 R8 rule; I-2; R-43.
 
**DET-69 — Live-model-input rows marked, lineage-consistent**
Pass: rows with `live_model_input = true` carry `consumed_by`; the marked set equals the set of §13-sourced fields in any lineage of capacity, routing, or metrics this run (crvUSD regulator `pause` → `is_killed`; `set_parameters` → α, β; GHO GSM `pause` → freezer role/bands); either direction mismatch = fail. Consequence: Level 2. Source: §13 live model inputs; R-15.
 
**DET-70 — Token-level qualifier consistent with the table (R-40)**
Pass: qualifying set {`mint`, `upgrade`, `set_oracle`, `seize`}; `qualifier[]` = one item per (power, holder) row with A1 in the set and A2.type ≠ none: `{power, holder_type, signer_disclosure | n/a, delay_bucket, veto}` exact replay; banner "Verifiability conditional on: [power] — [holder_type] + [delay_bucket]; …" per holder row in table order; empty set ⇒ "No admin power can alter backing — immutable." (unconditional under R-38); non-qualifying powers absent from the block; no node row carries a qualifier field; no verdict/score field; `tree.qualifier` attached, machine-readable; verifiability shares byte-identical with the block removed. Consequence: Level 2. Source: §13 qualifier; R-38; R-40.
 
**DET-72 — Non-qualifying powers ↔ R6 gates (R-40)**
Pass: for each on-chain path P: `pausable ∈ R6(P)` ⇔ ∃ row (power ∈ {`pause`, `freeze_asset`, `blacklist_address`}, holder ≠ none) whose A7 includes P's R10 contract or its governing freezer; every such row with a matching A7 has its path marked, and every marked path has ≥ 1 such row; `set_ceiling` / `set_parameters` rows present as reported-not-qualifying (DET-68). Consequence: Level 2. Source: §13; §12.
 
**DET-84 — Flat table replays from the bundle (D-9)**
Pass: every flat-table `{field_id, label, value, unit, denominator, section, owner_entry}` replays from its owner field in the bundle (1e-6 numerics; string equality otherwise); the table's hash is a component of `bundle_hash`; a table field with no owner = fail; the site page and its headline panel draw only from fields in this table. Consequence: Level 2. Source: G-5; D-9; brief §7.
 
### S3 — Rendered report and site page (data-consistency unless marked prose-only)
 
**DET-17 — Three-bar headline, exact mapping (R-6, D-2)**
Pass: bars ordered (1) `terminal`, (2) `terminal_other_layer`, (3) `recurses + recurses_truncated`; values replay from DET-14 shares (1e-6); bar 3 sub-annotation `truncated_share = Σ recurses_truncated shares` with §4.1 reason strings per truncated node; no merging; a 0% bar rendered as 0%, present; segment set = three bars + "unclassified — pending intake" segment iff U > 0 (no permanent empty segment); n for the R-7 slack counts rendered segments. Consequence: Level 2. Source: §4.6(ii); §4.1; R-6; R-7.
 
**DET-18 — Staleness pair (R-10)**
Pass: D = nodes labeled `recurses`; per node `staleness_days = run_date − last_disclosure_date` (DET-76e); `weighted = Σ_D share_i × staleness_i / Σ_D share_i`; `worst = argmax` with its share as % of backing; printed format contains weighted days, worst node name, worst days, worst weight; `terminal`, `terminal_other_layer`, `recurses_truncated` excluded (a staleness value on any = fail); per-node staleness column for every node in D; D empty ⇒ literal "no disclosure-dependent nodes"; companion line when Σ truncated share > 0: "N% of backing depth-truncated — staleness not assessed" (N at p = 1), omitted when 0. Consequence: Level 2. Source: §4.6(iii); §4.2; R-10; A-3.
 
**DET-36 — LP-flight assumption line**
Pass: headline exit-depth line carries "LP capital assumed sticky"; grid printed `0% / 30% / 60%` with "assumed scenario modifier, not data-derived"; modeling-rule sentence "single-sided withdrawal of the paired asset" once; per-cell application owned by DET-41/DET-51. Consequence: Level 2. Source: §6.1.4; §11.5.
 
**DET-53 — Bias note per mechanism (R-31)**
Pass: `bias_table[]` (sheet field, analyst-keyed, dated) rendered with heading "stock-only capacity — direction of error per mechanism"; coverage: every mechanism with a `capacity` lineage entry has a row; enum `{overstates, understates, both}`, no `neutral`; four memo-derived rows mandatory as literals: sell-side bound → overstates; GSM cap headroom → overstates; liquidator recycling (H5) → understates; Stability Pool refills (H3) → understates. Seed for remaining rows: Appendix C. Consequence: Level 2. Source: §7.1; R-31.
 
**DET-54 — Observation assumption per token, data-conditioned (R-30)**
Pass: GHO, LUSD: X = max `deviation` across DET-55 rows; X ≤ 1% ⇒ literal "instant observation — nearly exact: Chainlink deviation triggers ≤ X%"; X > 1% ⇒ "instant observation — weaker for [nodes with deviation > 1%]: deviation X%; shock cells at ≥ 20% still trigger immediately; residual error ≤ X%" (no flag); crvUSD: "instant observation — knowingly optimistic: LLAMMA prices off an EMA oracle; see counterfactual line EMA_lag" with per-market EMA windows listed. Consequence: Level 2. Source: §7.2; R-30.
 
**DET-56 — Failure-mode scope-out sentences**
Pass: all tokens: "oracle manipulation out of scope — feed control reported under the admin-power surface" cross-referencing the `set_oracle` rows; crvUSD, GHO: "oracle failure/staleness out of scope"; LUSD: reference to the `Tellor_fallback` line instead; all: "sequencer/infra risk n/a — mainnet only". Consequence: Level 2. Source: §7.3; §5.2.
 
**DET-57 — Assumptions block complete per token**
Pass: `assumptions[]` with required IDs: `stock_only`, `observation` (DET-54), `lp_sticky` + `lp_grid` (DET-36), `sell_side_bound` per volatile node (DET-52; LUSD exempt literal), `h5_slippage_bound` (GHO), `gsm_fee_exit` (GHO), `par_numeraire` ("paired assets counted at 1.00 for depth"), `shock_grid_fixed`, `lst_discount_grid` (crvUSD/GHO), `member2_target`, `freeze_reference` (DET-29c one-liner); each row `data_ref` (flat-table field) or `rule_ref` (memo section); the flat table for the judge = this block + the metric/headline fields (DET-84). Consequence: Level 2. Source: §7; brief §7.
 
**DET-58 — Flags rendered where triggers fired**
Pass: every log entry `{token, level = 1, resolution_date = null}` has a flag element in the section named by its trigger's `section`, with the trigger's literal text, the entry id, and the original fire date; a flag with no open entry = fail; an open entry with no flag = fail. Consequence: Level 2. Source: §8.1.1; §8.2.
 
**DET-59 — Stale-page banner, staleness cap, behavioral-tier literal (R-33)**
Pass: open Level 2/3 entry this run ⇒ page body = last published report (matching `bundle_hash`), banner literals "Last successful run: [date]" and "Current run: quarantined — [trigger category]"; `consecutive_quarantined_runs` (from the log) ≥ 4 ⇒ page = "Under review — last successful run [date]", no report body; a published run resets the counter; (b) "behavioral tier: pending" literal present until the behavioral tier lands (B-list patch). Consequence: page not regenerated (page-level Level 2); a quarantined run whose page shows a current-dated report ⇒ `gate integrity` (T-23). Source: §8.1.2; brief §6; R-33.
 
**DET-60 — Log entries complete, category-level, public**
Pass: every fired trigger this run has exactly one entry `{date, token, trigger, level, resolution_type | null, resolution_date | null}`; closed schema (any additional field = fail); `level` per DET-12; methodology-page rendered row count equals the log's entry count; `resolution_date` and `resolution_type` set together. Judge-side events (`judge_span_not_found`) live in the gate-evaluation record, not this log. Consequence: Level 2. Source: §8.1.3.
 
**DET-73 — §14 audit line and counterparty field (R-42)**
Pass: `audits[] = {firm, date, scope}` (≥ 1 or `none`), `bug_bounty = {platform, max}` or `none`, `last_material_change_audited ∈ {yes, no}`, `staleness_date` printed on its face (no bound); no `audit_*` in any lineage; `counterparties` literal "n/a — archetype #1 holds no off-chain counterparties" with the WBTC note, on every sheet. Consequence: Level 2. Source: §14; R-42.
 
**DET-74 — Analyst-supplied tags: presence, provenance, staleness by class (R-44)**
Pass: class I (M3 DefiLlama pools API — date = when coverage was last verified; M4 deployments.json; M5 factory enumeration; M6/M9 price-history source): `{value, source, date}`, > 92 d ⇒ Level 1 `enumeration source stale` (T-16); class D (M2 Sky note; S3/S6/S8 bug bounty — one shared tag instantiated thrice, each independently dated; S4, S7 audit notes): date printed, no bound; class F (M7/M10 → per-node sell-side parameters): DET-52; class S (M1 frxUSD note; S1 USDC ceiling history; S2 USDT ceiling): the tag must be absent from the consumed sheet version — a superseded tag still consumed = fail; class N (M8 behavioral threshold; S5 subgraph note): Appendix. Consequence: Level 3 (consumed value without provenance); per class otherwise. Source: brief §6; R-1; R-26; R-42; R-44; E-4.
 
**DET-79 — Template-artifact string leak**
Pass: zero matches over report and site page for `{{`, `}}`, `{%`, `[TODO`, `TBD`, `lorem`, `XXX`, `<placeholder`, `[FIRST-RUN READ`, `[ANALYST-SUPPLIED`, `[VERIFIED`, `[RE-SCOPED`, `[VERIFY]`, the tag shape `\[[A-Z][A-Z -]+:`, and every unresolved ruled placeholder (`[addr]`, `[date]`, `[freeze date]`, `block N`, `N%`) from the substitution list emitted with the template. Consequence: Level 2. Source: brief §7; memo conventions.
 
**DET-80 — Required prose slots present, non-empty, bounded**
Pass: template `prose_slots[]` (verifiability narrative; Member 1 opening; Member 2 opening; flag explanations; counterfactual explanations; admin-surface narrative; structural summary) each present and non-empty; no LLM text inside a template-rendered element. Consequence: Level 2. Source: brief §6; I-1.
 
**DET-88 — No grade, score, letter, or verdict field (R-52)**
Pass: no field of that type anywhere in bundle, report, or site page until a memo amendment defines a derivation (a future grade arrives with its own rule and DET entry). Consequence: Level 2. Source: R-52; DET-70 generalized; O19.
 
**DET-89 — Rendered-figure formatting and units (D-9)**
Pass: every rendered numeric figure on report and site page equals `format(bundle_value, unit, decimals)`; token decimals from a `decimals()` read with provenance; display rule (thousands separators; 2 decimals for USD ≥ 1k; 4 for token amounts < 1) emitted with the template as the named default. Consequence: Level 2. Source: G-10; D-9.
 
**DET-87 — Resolution evidence (R-51)**
Pass: a resolved log entry requires the corresponding artifact hash to differ between the fire run and the resolution run: `intake_change` → `sheet_hash`; `config_change` → label-config / set-file hash; `template_change` → `template_hash`; `rubric_change` → rubric header checksum; `code_fix` → `pipeline_version`; `data_correction` → the re-read value differs from the fired value; header fields `template_hash` and `pipeline_version` mandatory. Consequence: Level 2, logged as `gate integrity` (T-23). Source: R-51; §8.1.3.
 
**DET-85 — Fail-closed harness**
Pass: the gate-evaluation record has an entry for every DET and LLM ID; a missing entry or `result = error` (exception, RPC failure mid-evaluation, invalid judge output schema, timeout) ⇒ no publication, Level 2 `harness error` (T-25); an error is never `pass` and never `not_applicable`. Source: G-6 ("a gate that opens when it breaks").
 
**DET-13 — Gate integrity (last; C-3, A-1, A-8)**
Pass: (a) report embeds `bundle_hash` matching the bundle (which includes the flat table, DET-84); (b) `revision_count ∈ {0, 1}`; (c) gate-evaluation record lists every DET/LLM ID with `result ∈ {pass, fail, not_applicable, error}`, no `skipped`/`overridden`, `not_applicable` only under a declared token-scope condition; (d) no report for a token/run with an open Level 2/3 entry; (e) `resolution_type ∈ {template_change, intake_change, config_change, data_correction, code_fix, rubric_change}` — no override or output-edit value exists; (f) a report whose bundle shows a Level-3 condition unquarantined (DET-09) counts here; (g) `revision_count = 1` ⇒ `revision_cause` cites only S3 prose-only failures (LLM IDs); a revision against any S1/S2/S3-data failure = fail; `bundle_hash` unchanged across the revision. Consequence: Level 2, logged as `gate integrity` (T-23). Source: §9 gate 12; §8.1.3; brief §7; C-3; A-1; A-8.
 
---
 
## 2. LLM-judged entries
 
**2.1 Judge contract.** Input: rendered report text + the flat data table (DET-57/DET-84), nothing else (S-A). Output envelope: `{rubric_version, report_id, bundle_hash (as printed), judge_model, prompt_schema_version, criteria: [LLM-01…LLM-06], overall_pass}`; each criterion `{id, pass, items[], defects[]}`; each defect `{kind, location: {section_id, paragraph_index, quoted_span}, table_ref | figure_ref | null, reason}`, `quoted_span` verbatim. Harness post-check: a defect whose span is not found verbatim at the stated section is discarded and logged in the gate-evaluation record as `judge_span_not_found` (an instability signal for R-48(b)). Named defaults: temperature 0; model string and prompt hash in the gate-evaluation record; full judge output stored in the bundle. Consequence of any surviving defect: fix-in-revision (one shot), `revision_cause` cites the LLM IDs (DET-13g).
 
**2.2 Judge loop (R-48).** (a) A judge-only revision is re-evaluated by a fresh full judgment **and** a separate remediation call that receives the pass-1 defect list and answers `addressed ∈ {yes, no}` per item; pass requires both. (b) Two consecutive judge-only failures: same `(kind, section)` on both passes ⇒ template defect (the brief's loop); differing findings, or any `judge_span_not_found` on either pass ⇒ Level 2 `judge instability` (T-24) and Tier-3 judge/rubric-defect review — the analyst diagnoses whether the finding is wrong (→ rubric/prompt patch, `resolution_type = rubric_change`) or the prose is (→ template patch). Findings patch templates, rubrics, or prompts — never the report; only the diagnosis is routed to a human. (c) Auditability = verbatim spans + section ids + matched `field_id` + stated reason + span post-check + model id / prompt hash / temperature 0 / stored output; no confidence numbers; judge-disagreement measurement is a periodic Tier-3 audit on sampled runs, not a per-run gate.
 
**LLM-01 — Quantitative-claim traceability**
Checked: every quantitative claim in prose (figure, percentage, count, ranking, magnitude comparison, date) corresponds to a flat-table field with the right denominator within display rounding. Why not deterministic: claims arrive in natural language ("roughly a third", "the largest keeper", "more than doubled"); mapping a phrase to which quantity it asserts is semantic; extraction alone cannot distinguish correct rounding from a wrong denominator or a right number on the wrong object (DET-19 makes the table's denominators unambiguous; DET-79 catches literal leaks; the residual is meaning). Schema items: `{quoted_span, section_id, claimed_value, claimed_object, matched_field_id | null, table_value, match ∈ {exact, rounded_ok, approximate_ok, mismatch, wrong_denominator, untraceable}}`; `approximate_ok` only for explicitly hedged phrasing within ±1 display unit at p = 1. Defects: `mismatch`, `wrong_denominator`, `untraceable` (an untraceable number is LLM-originated by definition, brief §6). Forward note: when Step 6 anchors prose numbers with `data_ref`s, the anchored subset moves to a DET entry; LLM-01 covers the remainder.
 
**LLM-02 — Mechanism rationale opens each member**
Checked: Member 1 and Member 2 openings state why this shock fits this token's mechanism class, naming the actual mechanism (LLAMMA/PegKeeper; Aave liquidation + GSM; Stability Pool/redemptions), before any result. Why not deterministic: DET-80 proves the slot is filled; whether the text is a scenario→mechanism rationale, token-specific, and precedes results is a judgment about content and order of ideas. Schema (per member): `{member, rationale_present_at_open, links_shock_to_mechanism, names_token_mechanism, first_result_sentence_span}`; defect where any bool is false.
 
**LLM-03 — No cross-section contradiction**
Checked: no prose statement contradicts another statement or a rendered figure elsewhere (e.g., "fully verifiable" vs. a 40% bar 3; "exit absorbs the flow" vs. ratio > 1; "freezer protects" vs. the freezer-check-failed flag; "no admin can alter backing" vs. a qualifier listing `upgrade`). Why not deterministic: contradiction is a relation between meanings across arbitrary phrasings. Schema items: `{span_a, section_a, counterpart ∈ {span_b + section_b | figure_ref}, nature ∈ {direct_negation, magnitude_conflict, direction_conflict, state_conflict}}`; pass iff empty.
 
**LLM-04 — Semantic boilerplate (remainder after DET-79)**
Checked: each prose slot is tied to this token's data and mechanism; no paragraph would be equally true of any CDP token; no sentence merely restates the methodology page. Why not deterministic: genericity is a property of what a sentence commits to, not of its tokens. Schema (per slot): `{slot_id, token_specific, references_field_ids[], generic_spans[]}`; defect per slot with `token_specific = false` or any generic span.
 
**LLM-05 — Flags, counterfactual lines, and printed findings explained, not just printed**
Checked: for every flag element, counterfactual line (headline panel and full table), and printed finding (e.g., DET-64's attribution divergence), adjacent prose explains what fired or what the line means and what the reader should take from it, and does so without misstating the mechanism (checkable against the on-page A1–A8 table and metric 4). Why not deterministic: DET-58/DET-44/DET-64 own presence; whether nearby prose refers to a given item, explains rather than restates, and is mechanistically correct is semantic. Schema items: `{item_id, section_id, explained ∈ {adequate, restates_only, absent, wrong}, explanation_span | null, reason}`; defects = items not `adequate`. The `wrong` category is the rubric's only catch for confidently incorrect narrative.
 
**LLM-06 — Zero by construction never narrated as "nothing happened"**
Checked: for structurally insulated tokens (DET-43), Member 2 prose frames the zero ratio as exposure through exit venues, points to the recomputed depth curves and metric 4 quantities, and contains no statement equivalent to "unaffected / no impact / nothing happens". Why not deterministic: the paraphrase space of "nothing happened" is open; the positive obligation is a content judgment; DET-43 owns the literal and the curves. Schema: `{applicable, negation_spans[], positive_framing, curve_referenced, m4_referenced}`; defect if any negation span or any bool false when applicable; `applicable = false` ⇒ pass by rule (the judge still runs and returns `applicable`).
 
Consciously merged: assumptions-narrative fidelity → LLM-01 + LLM-03; "stress section states rationale" → LLM-02; "reads as this token's" → LLM-04.
 
---
 
## 3. Trigger table (DET-12 S0 binds to this table; D-5 computing owners; A-2)
 
`section = —` is the ruled form for every Level 2/3 row (T-09…T-15, T-23…T-25): those events produce no published report, so no section exists for a flag; their visibility surface is the public log and DET-59's banner; DET-58 scopes to open Level 1 entries (ruled 2026-09-03).
 
| ID | Trigger | Level | Section (flag renders) | Defined | Computing owner |
|---|---|---|---|---|---|
| T-01 | unlisted node < 5% | 1 | verifiability | §8.2 | DET-08 |
| T-02 | off-venue share > 25% | 1 | exit liquidity | §5.1 | DET-32 |
| T-03 | GHO attribution fallback, first run | 1 | verifiability | §11.1 | DET-64 |
| T-04 | composition shift | 1 | verifiability | §8.1.4(a) | DET-65 |
| T-05 | supply jump, confirmed | 1 | supply | §8.1.4(b) | DET-62 |
| T-06 | market addition, known node | 1 | verifiability | §8.1.4(c) | DET-63 |
| T-07 | mechanism near bound | 1 | mechanism state | §8.1.4(d) | DET-61 |
| T-08 | GSM freezer check failed | 1 | stress (Member 2) | §6.3 H2 | DET-46 |
| T-09 | unlisted node ≥ 5% | 2 | — | §8.2 | DET-08 |
| T-10 | pool-set change ≥ 10% | 2 | — | §5.6 | DET-10 |
| T-11 | GHO attribution fallback, second consecutive | 2 | — | §11.1 | DET-64 |
| T-12 | market removal | 2 | — | §8.1.4(c) | DET-63 |
| T-13 | discovery mismatch > 5% | 3 | — | §5.5 | DET-09 |
| T-14 | supply jump, unconfirmed | 3 | — | §8.1.4(b) | DET-62 |
| T-15 | count change, immutable protocol | 3 | — | §8.1.4(c) | DET-63 |
| T-16 | enumeration source stale | 1 | header | R-1 (rubric) | DET-04 (enumerations); DET-74 (class-I sources) — two conditions, one trigger |
| T-17 | freeze overdue | 1 | exit liquidity | R-4 | DET-10(f) |
| T-18 | unlabeled paired asset | 2 (≥ 5% exit depth) / 1 (< 5%) | exit liquidity | R-5 | DET-11 |
| T-19 | bridge type unresolved | 1 | supply | R-18 | DET-33 |
| T-20 | freeze coverage below target | 1 | exit liquidity | R-20 | DET-29(a) |
| T-21 | GSM frozen at base | 1 | exit liquidity | R-25 | DET-35 |
| T-22 | off-venue share not computed | 1 | exit liquidity | §11.12 (memo map omitted it) | DET-32 |
| T-23 | gate integrity | 2 | — | §8.1.3 / brief §7 | DET-13; DET-87; DET-59 |
| T-24 | judge instability | 2 | — | R-48(b) | judge loop (§2.2) |
| T-25 | harness error | 2 | — | G-6 | DET-85 |
| T-26 | credited price feed stale | 1 | oracle table | R-50 | DET-81 |
| T-27 | bridged supply jump | 1 | supply | R-53 | DET-62 |
| T-28 | gate failure | 2 | — | A-17 (rubric) | report stage |
 
All rows have a computing owner. Non-computable properties are in Appendix A. Judge-side events (`judge_span_not_found`) are gate-evaluation-record events, not rows here.
 
---
 
## 4. Ruling index
 
**Structural:** S-A evaluator input split by check type; S-B stage map (S0 in scope); I-1 prose-only definition; I-2 R8 derivation (capacity_limited contributes only the "(see R7)" note).
 
| ID | Subject | Ruling |
|---|---|---|
| R-1 | analyst-supplied enumeration staleness | (b) > 92 d → L1 `enumeration source stale` |
| R-2 | negative net debt | (a) floor at 0; surplus disclosed |
| R-3 | discovery mismatch | (a) (max − min)/max, > 5%; median rejected |
| R-4 | freeze age | (b) > 100 d → L1 `freeze overdue` |
| R-5 | unlabeled paired asset | (a) exit-depth share ≥ 5% L2 / < 5% L1; pool stays modeled; distinct trigger |
| R-6 | unlisted weight U | (a) inside backing_value; conditional fourth segment |
| R-7 | rounding vs. sum | (a) two-layer, p = 1, half-up default |
| R-8 | supply residual tolerance | (a) 0.1%; GHO 0 (FIRST-RUN-VERIFY); L2 |
| R-9 | stabilizer line on non-stabilizer tokens | (a) present: "0% — no stabilizer mechanism" |
| R-10 | truncated nodes in staleness | (a) excluded; companion weight line |
| R-11 | utilization > 100% | (a) permitted; ceiling-0 edge "n/a — ceiling 0" |
| R-12 | metric 4 under Member 2 | (a) quantities only |
| R-13 | block atomicity | (a) one block; contract reads only |
| R-14 | paired/boxed asset pricing | split: stabilizer par; GSM boxed Chainlink at run_block |
| R-15 | lineage tags | in; positive lineage checks |
| R-16 | ranking TVL | (a) on-chain balances at par |
| R-17 | depth verification | hybrid: get_dy at s = 2% (symmetric ε = 0.05%); wiring elsewhere |
| R-18 | unresolved bridge | (c) exclude, disclose, L1 |
| R-19 | GSM at other curve points | (a) include iff fee_exit < s |
| R-20 | freeze coverage recheck | (a) + waiver (L1 with record) |
| R-21 | node classification fields | (a) config fields; two sub-checks |
| R-22 | Member 2 curve scope | (a) three four-point curves |
| R-23 | Tellor line content | (a) constants + scope statement; once per member |
| R-24 | counterfactual rendering | (a) per cell in full table |
| R-25 | base-frozen GSM | (a) excluded, disclosed, L1 |
| R-26 | sell-side staleness | (a) date ≥ freeze_date else L2 |
| R-27 | unlabeled asset in Member 2 | (ii) compound tail only (reverses Block-2 lean) |
| R-28 | circulating supply | (a) = supply_ruled |
| R-29 | monotonicity gates | (a) in, extended to m3 |
| R-30 | feeds > 1% deviation | (a) caveat variant, no flag |
| R-31 | bias-table source | (b) sheet field; four literals mandatory |
| R-32 | — | not assigned (reserved for the enum `section` field; resolved as rubric-internal declaration) |
| R-33 | site page in scope | (a) in |
| R-34 | PegKeeper near-bound | (c) per keeper and aggregate |
| R-35 | LUSD near-bound | (a) TCR ≤ 187.5% (u = CCR/TCR) |
| R-36 | supply-jump confirmation | (a) each source within 5%; unavailable = disagree |
| R-37 | GHO position completeness | (a) 0.1% + fallback route |
| R-38 | A1 row set | (a) nine rows always |
| R-39 | bucket edges | (a) [86400, 604800] → 1–7d |
| R-40 | row granularity | (a) per (power, holder) |
| R-41 | non-empty LUSD surface | (a) Level 3 |
| R-42 | audit-line staleness | (a) none |
| R-43 | combined R8 string | (a) canonical order |
| R-44 | 18-tag classing | accepted; T-16 reused |
| R-45 | first-run-read manifest | (a) sheet section |
| R-46 | heartbeat form | (c) either; observed_max preferred |
| R-47 | sheet version stamp | (a) in |
| R-48 | judge loop | (a) iii; (b) iii + `rubric_change`; (c) i + sampled audit |
| R-49 | collateral-node pricing | (c) protocol oracle + gap column |
| R-50 | credited price staleness | (a) L1 `credited price feed stale` |
| R-51 | resolution evidence | (a) in; `template_hash`, `pipeline_version` |
| R-52 | grade fields | (a) forbidden until defined |
| R-53 | supply-jump comparand / bridged component | (i) jump on mainnet `totalSupply`, comparand mainnet `totalSupply`; bridged > 25% → L1 `bridged supply jump` (T-27) |
 
**Parked-question dispositions:** PQ-1 closed (GSM-signature interface probe, DET-28); PQ-2 closed (exit-direction fee); PQ-3 closed (ascending-address tie-break, default); PQ-4 closed (`checkUpkeep` probe); PQ-5 closed (minimum liquidation bonus); PQ-6 closed (formula floor at 0, default).
 
**ID notes:** DET-29 is split into (a) S1 set-file properties and (b)(c) S2 selection replay; DET-78 (bias-table seed review) was never a check and is retired into Appendix C — the number is reserved, not reused.
 
**Directives applied:** C-1…C-3; D-1…D-10; P-2…P-4; C-H1, C-H4 (seed corrections); AP-1, AP-2 (close-out patches). **Self-test (2026-09-03):** D-10 cross-entry pass clean after two assembly fixes (DET-11 aligned to R-27; DET-75 counts `status = open` rows); (a)-list closed by PQ-1, R-53, and the `section` ruling; (b)-list closed as implementer-resolvable.
 
## 5. Amendment log (memo, next revision) and editorial log
 
- **A-1** §8.1.3 resolution types gain `code_fix` (O1).
- **A-2** §8.1.1 trigger map 15 → 27 rows (T-16…T-27); each addition is the declare-your-level rule catching a consequence-bearing event the map had not tabulated. Counting unit: memo-map rows preserved as-is (the unlisted-node pair stays T-01/T-09); rubric-added threshold-split triggers use one row (T-18).
- **A-3** §4.6(iii) "disclosure-dependent nodes" → "staleness-recorded nodes (recurses)".
- **A-4** §6.3 H1 ceiling wording: all ceilings are per-run reads (O8).
- **A-5** §6.3 H1 formula gains the explicit ceiling min (O12).
- **A-6** §13 "one row per power" → "one row per (power, holder)" (O15).
- **A-7** §13 A2.type gains `contract_automated` (O16).
- **A-8** §8.1.3 resolution types gain `rubric_change` (R-48b).
- **E-1** §5.4/§5.5 floor interaction wording (stabilizer pools floor-exempt, P-4).
- **E-2** §6.2.7 "circulating supply" → "supply (§8.1.4(b) definition)".
- **E-3** §12 R8 rule second line: separate pausable's string from capacity_limited's note (I-2).
- **E-4** memo header "18 analyst-supplied values" → "tags" (O17).
- **O19** memo §4 "structural grade" phrase has no defining section — define or remove (R-52).
- **A-9** §5.5 / DET-29(b) K = 95% reads as the full frozen set F by construction, not the prefix (P-6.01 R5).
- **A-10** §6.2.5 / DET-50 counts §5.10 venue contributions in the exit-depth share, the boxed asset resolving through §4.3; and the share is measured at the fill block on the set in force, not "at freeze" — no depth exists at a freeze block (P-6.01 R6, R7; P-3.09-A1).
- **A-11** §3b / DET-24's comparand is the recorded scope condition, `pool_composition_at_block` having no bundle field (P-6.01 R-B2.5).
- **A-12** §6.3 H1 / DET-45: the regulator's `is_killed` is global; the flag applies to every keeper (P-6.01 R8).
- **A-13** §6.3 H1 / DET-45: `r_j` carries the deployed regulator's `+1` denominator guard — `get_ratio` is `debt * ONE // (1 + debt + balance)`, not `debt / (debt + balance)`; the guard is in the deployed source and the model ports it rather than the algebraic form (P-6.01 R-B4.2, P-6.08).
- **A-14** §7.2 / DET-44: `EMA_lag`'s window is the bundle's `ema_window_s` — the transitive maximum over an oracle's constituent pools — because no `MA_EXP_TIME` getter exists on the deployed AMMs to read (P-3.31; P-6.01 R-B4.8, P-6.09).
- **A-15** §6.2.7 m3 / DET-41: at zero exit depth with a positive numerator the ratio is undefined, stored `null`, rendered ∞, and treated as +∞ along the LP axis so R-29's monotonicity holds by ruling rather than by luck (P-6.01 R-B4.14, P-6.09).
- **A-16** §8.1.3 / DET-85, DET-13(c): for as long as any rubric entry is unregistered in the harness, the gate-evaluation record's completeness is measured over the registered entries; every unregistered entry is enumerated by ID with its queue item in the gate record and their count is printed on the methodology page; an unregistered entry is not a gate result — no `result` value is added and `not_applicable` keeps its token-scope meaning; the enumeration shrinks only by registration, and the amendment is spent when it is empty (P-7.01 R1).
- **A-17** §8.1.1 / §3 / DET-12, DET-59: the trigger table gains **T-28 "gate failure"**, Level 2, section —, computing owner = the report stage, so a failed deterministic check is logged and DET-59's banner has a category; counting per A-2 (one row), table 27 → 28 rows (P-7.01 R15).
- **A-18** §2.1: "Named defaults: temperature 0; model string and prompt hash in the gate-evaluation record" reads "Named defaults: model default; sampling parameters not settable — recorded null; thinking setting, model string and prompt hash in the gate-evaluation record" (P-7.01 R12).
- **A-19** §1 / DET-55, DET-54, DET-81: DET-55's `update_condition.type` enum gains `nav_schedule`; rows of that type are excluded from DET-54's X and from DET-81's T-26 staleness test, and carry `heartbeat_s = {form = documented, value = the documented NAV publication interval, provenance}` (P-7.03).
## 6. Evaluation-loop contract
 
1. Deterministic stages run in order S0 → S1 → S2 → S3; a failure at a stage stops at that stage's consequence (Level 3 / Level 2); S3 data-consistency failures are Level 2; DET-13 runs last.
2. Only S3 prose-only failures (LLM-01…06) enter the revision path: one revision, regenerating prose against an unchanged bundle; `revision_cause` cites the failing IDs.
3. Second failure: same `(kind, section)` ⇒ template defect → fix template, rerun; differing findings or any `judge_span_not_found` ⇒ `judge instability` (L2) → Tier-3 diagnosis (R-48b).
4. Findings patch templates, rubrics, or prompts — never individual reports. No hand-editing path exists; quarantines resolve only by logged template / intake / config / rubric / code change or confirmed data correction, each evidenced by a hash or value change (DET-87).
5. Fail-closed: any harness or judge error ⇒ no publication (DET-85).
6. One owner per checkable condition; cross-reference, never restate.
7. Every enum row (T-01…T-27) has a computing owner (D-5); the enum grows only through the amendment log.
8. Audit chain: report → `bundle_hash` (incl. flat table) → `sheet_hash`, `template_hash`, `pipeline_version` → governing-artifact checksums (this header).
## Appendix A — Unchecked by design
 
| Item | Reason |
|---|---|
| "No list literal in the adapter" (code property) | Source-code property; report-checkable form is DET-04 provenance. Step-3 code review. |
| §8.1.1 per-token scope paragraph | Organizational property of the pipeline; per-token enforcement via DET-13(d) only (D-8). |
| PQ-3 ranking tie-break | Resolved as a named default (ascending address). |
| M8 behavioral-tier threshold consistency | No report field until the behavioral tier lands; logged for that day (§11.4). |
| S5 Aave subgraph availability | Implementation note (Step 4); DET-64/DET-82 make the indexer's identity irrelevant to the report. |
| Audit-line staleness | By ruling R-42: self-dating display metadata gets no bound. |
| Tellor line arithmetic | By ruling R-23: verified constants + scope statement, no computed value. |
| Aave-paused reserve liquidation capacity | Tier 3 / Step 6 modeling refinement. |
| Pool fee inside the depth solver | Implementer; verified at s = 2% by R-17 ground truth. |
| K-choice divergence | Disclosed by DET-30 by design. |
| LLM prose non-determinism | Not a defect; gated by LLM-01…06. |
| Judge disagreement measurement | Tier-3 periodic audit on sampled runs (R-48c). |
| Language / style / section ordering | Template. |
 
## Appendix B — Forward notes (Step 6 / next memo revision)
 
- When Step 6 anchors prose numbers with flat-table `data_ref`s, the anchored subset of LLM-01 becomes a DET check (anchor resolution + value/denominator match); LLM-01 covers hedged and unanchored phrasing.
- O19: define or remove "structural grade" (§4); DET-88 forbids any grade field until defined.
- Class-S tags (M1, S1, S2, M7 prose form) retire from the sheets at the next intake edit; the class-S gate enforces it.
## Appendix C — Bias-table seed (R-31; sheet content, not rubric content)
 
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
 