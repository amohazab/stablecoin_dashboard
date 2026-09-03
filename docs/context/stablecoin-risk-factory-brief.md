# Stablecoin Structural Risk Factory — Project Brief
 
**Status:** Design complete, implementation not started. Nothing below is immutable, but all of it has been deliberately decided unless listed under Open Points.
**Owner:** Amin — quantitative credit risk analyst (IRB/IFRS9 background), PhD economics, building an independent DeFi-risk research portfolio (Medium + GitHub) targeted at DeFi/crypto-native risk roles and industry visibility.
**Prior work this builds on:** a well-received 16-page manual structural risk assessment of Ethena's USDe/sUSDe — nine-pool stableswap stress model, ~985 days of on-chain calibration, reproducible Dune queries. Thesis: behavioral monitors catch market-led failures but miss backing-led ones.
 
---
 
## 1. What the project is
 
Turn that one-off manual report into an **automated report factory**: given a list of stablecoins (~10 target), generate a comparable (not identical) structural risk report for each, running unattended on a schedule, published as a static website + PDFs. **The system itself — with documented design rulings and validation gates — is the primary portfolio artifact; the reports are output samples proving it works.** Vaults (ERC-4626) are the phase-2 extension, designed to be a config change rather than a rewrite.
 
Working audience: "certain people in the industry" — independent research positioning (survives any single job application; grades publish as the data dictates, including unflattering ones for USDC/USDT).
 
## 2. Core analytical ideas (the theses the artifact demonstrates)
 
1. **Two-layer analysis.** Layer 1 (behavioral/liquidity — peg behavior, liquidity, holder concentration, flows) is *consumed* from Webacy's API, attributed, never rebuilt. Layer 2 (structural/backing — what backs the token and how verifiable that backing is) is *owned* and is the differentiator. Note: the one Webacy dataset addressing backing-led failure (Backing Map) is dashboard-only, not in their API — the differentiation layer is precisely what their API can't provide.
2. **Verifiability is scored, not treated as missing.** Every token gets a verifiability decomposition: % of backing verifiable on-chain in real time vs. % dependent on issuer disclosure at N days staleness. Implemented as a **weighted look-through tree**, not a flat split (e.g., GHO's GSM holds USDC → recurses one level into Circle's fiat-attestation staleness; wstETH → terminal, verifiable). Look-through policy is a maintained table per archetype, applied automatically. "On-chain readable ≠ value verifiable."
3. **Admin-power surface conditions verifiability** *(added from LlamaRisk gap analysis)*. Who can mint, upgrade, pause, freeze, blacklist; multisig composition; timelock delays. On-chain readable → Tier 1 automatable. Backing is only as strong as the keys that can rewrite the rules; a verifiable balance behind a 2-of-3 upgradeable proxy is conditionally verifiable.
4. **Automation strategy is an archetype property.** How a coin holds its backing determines how its analysis automates: on-chain-backed → direct RPC (zero manual); off-chain-hedged synthetics → transparency-dashboard endpoint scraping with quarantine gates; fiat-backed → attestation-PDF extraction or analyst-keyed disclosure. The manual path survives as just another adapter ("analyst-supplied disclosure") with tracked staleness — graceful degradation.
5. **Stress testing is mechanism-specific — stated as a named methodological principle.** Uniform scenarios across different failure mechanisms produce comparable-looking numbers that mean different things (the same failure mode the USDe thesis attributes to behavioral monitors). The comparable spine across tokens = behavioral tier + verifiability decomposition + structural grade; stress sections are explicitly mechanism-specific, each opening with a scenario→mechanism rationale.
6. **Judgment moves from runtime to design time.** Analyst rulings are made once per archetype (memo) and once per token at intake (sheet); code enforces them per run. No per-report judgment in production.
## 3. Documentation model (two levels — this resolves "one memo per archetype?")
 
- **Archetype design memo** (one per archetype, ~2 pages, written before any code for that archetype): class-level rulings — definition of backing (address-based, never symbol-based); look-through policy table; pool-selection rule (+ sensitivity note, since the rule choice moves results); stress **scenario family**; oracle-dependency assumptions; quarantine bounds (schema/shape changes AND semantic bounds — composition or market-count shifts beyond limits halt publication for template review).
- **Token intake sheet** (one per token, ~half page, filled at the manual intake gate): archetype assignment; specific contracts to read; token-specific mechanisms deviating from the archetype default (crvUSD: PegKeepers + ruling; GHO: GSM facilitator; LUSD: user-facing instant redemptions); oracle sources; redemption-rights fields (who may redeem, minimums, gates/notice, whether ToS grants a claim on reserves) — the legal core of backing-led failure, as structured fields not legal opinions; counterparty enumeration (custodians/venues + concentration) for off-chain archetypes; audit status (static metadata line).
- If filling an intake sheet reveals the archetype rulings don't fit, the token belongs to a different (possibly new) archetype — that is the intake gate working as designed.
## 4. Stress model structure (three levels — this resolves "per archetype or per token?")
 
- **Scenario family** (archetype memo): the attack that fits the mechanism class. CDP: correlated collateral crash × liquidation-capacity exhaustion. Synthetic: funding-rate inversion + custodian/redemption stress. Fiat: reserve impairment + redemption run.
- **Token-specific mechanisms** (intake sheet): bounded modifications — PegKeeper dynamics for crvUSD (including the double-counting trap: PegKeeper pool liquidity cannot count as both backing and exit depth), GSM capacity for GHO, redemption-arbitrage stabilization for LUSD. ~20–30% of stress design; captured once at intake.
- **Parameters** (per run, fully automated): live composition, pool depths, thresholds, band health from adapters.
- Published stress sections cite all three: family (memo §), mechanisms (intake sheet), parameters as-of date. Oracle-execution assumptions stated explicitly.
## 5. Three-tier work model
 
- **Tier 1 — fully automated:** adapter data collection; admin-power-surface reads; deterministic validation; verifiability computation; stress runs; monitoring-brief generation; site regeneration.
- **Tier 2 — archetype-templated:** the memos. Judgment exercised once per archetype, enforced by code per coin.
- **Tier 3 — permanently manual:** intake gate for new tokens; deep-dive theses on flagged tokens (batch-reviewed async); quarantine/semantic-flag reviews; template fixes when a report fails evaluation twice.
## 6. Architecture
 
- **Adapters (Layer 2 collectors), common output schema:** collateral composition (keyed by contract address), verifiability split inputs, staleness, provenance (source, block, timestamp), admin-power surface, counterparty enumeration (where applicable).
  - *On-chain-backed* (crvUSD, GHO, LUSD, frxUSD): market **discovery from factory/registry contracts — hardcoded lists are forbidden** (generalized Morpho lesson: hardcoded lists rot; any static list must itself be an "analyst-supplied" staleness-tracked input). RPC + multicall; cross-validation three ways: RPC vs. DefiLlama (free API) vs. existing Dune queries via Dune execution API; mismatch beyond tolerance → quarantine.
  - *Off-chain-hedged synthetics* (USDe-class): transparency dashboards are frontends over undocumented JSON endpoints — scrape those with schema-validation gates that **quarantine on shape change rather than publishing garbage**.
  - *Fiat-backed:* monthly attestation PDFs → LLM extraction with structured outputs + validation bounds + human review on anomalies. Timeboxed; fallback = manually keyed analyst-supplied disclosure with tracked staleness (itself an honest statement about fiat verifiability).
- **Behavioral tier (Layer 1) behind an interface:** Webacy adapter when access lands; until then "behavioral tier: pending" or a thin DefiLlama/Dune substitute (peg deviation, liquidity depth, supply trend). Nothing upstream depends on which implementation is behind the interface.
- **LLM usage in production:** synthesis/prose only, via API calls with structured outputs and validation gates. **Numbers never originate from an LLM** — they come from artifacts; the LLM writes around them. Interactive agent sessions = dev environment; scheduled deterministic scripts = production.
- **Scheduling:** GitHub Actions cron (weekly) or cheap VPS; Webacy DEPEG_TIER_CHANGE webhooks as free event triggers later. Secrets in Actions secrets. Run log + failure notifications. Nothing requires a live agent babysitting.
## 7. Multi-agent production model
 
- **Builder** (Claude Code, interactive, supervised): writes adapters, templates, queries. Dev only.
- **Evaluator** (production): *not a chat personality — a checklist executed mechanically.* Deterministic checks in plain code first (sums to 100%, address-keyed rows, staleness bounds, DefiLlama reconciliation within tolerance, no placeholder text), then LLM-as-judge API call with structured output for judgment criteria (every quantitative claim traceable to a data field; stress section states mechanism rationale; no internal contradictions). Fresh-context evaluation is a structural advantage: the judge sees only what's on the page, like a reader.
- **Human:** writes memos and rubrics; handles intake, quarantines, deep-dives; batch review.
- **Hard loop rule:** generate → evaluate → **one** revision → ship or quarantine. Second failure = template defect → fix template, rerun. Evaluator findings patch templates/rubrics, **never** individual reports. No hand-editing path exists. (This is the anti-micro-optimization mechanism: you stop when gates pass, and new quality criteria only apply to the next run.)
- Honest failure signal: editing outputs instead of templates = you've left the factory model and are quietly falsifying the "reproducible factory" claim.
## 8. Implementation steps (in order)
 
1. **Archetype memo #1 (CDP/on-chain-backed) + intake sheets for crvUSD, GHO, LUSD.** First real decision: the PegKeeper ruling (backed / unbacked / separate category + double-counting treatment). Include look-through table, pool-selection rule, stress family, oracle assumptions, quarantine bounds. Done when another analyst could implement without questions. *(Owner: Amin, manually — explicitly not delegated.)*
2. **Evaluator rubric v1.** Concrete pass/fail criteria, split deterministic vs. LLM-judged, each with failure consequence (fix vs. quarantine). Done when every criterion is mechanically checkable.
3. **crvUSD adapter.** Factory-contract market discovery; RPC/multicall state reads incl. PegKeeper pools and admin-power surface; three-way cross-validation; emits common schema. Done when two runs a day apart pass validation and match a manual spot-check.
4. **GHO + LUSD adapters.** GHO exercises look-through machinery (GSM/USDC) and facilitator caps; LUSD is the simplicity control — if the schema is awkward for LUSD, the schema is wrong.
5. **Verifiability decomposition module.** Weighted look-through tree from adapter output + memo table. Done when crvUSD ≈ 100% (boring, correct) and GHO shows a defensible non-trivial split.
6. **Stress module, CDP family.** Shock grid → band health/collateralization → liquidation flow vs. selected-pool liquidity → bad debt / depeg pressure. Token mechanisms wired from intake sheets (PegKeeper without double-counting; GSM capacity; LUSD redemption arb). Outputs include the "why this scenario" rationale.
7. **Report generation + evaluation loop.** Template → HTML + PDF; structured-output LLM prose; rubric gates wired; one-revision rule enforced in code; quarantine path. Done when a deliberately broken input actually blocks publication.
8. **Unattended execution.** Weekly GitHub Actions cron for the full chain. Done when two consecutive scheduled runs complete untouched.
9. **Publish v1 — static site (GitHub Pages).** Token selector; per token: verifiability tree (visual centerpiece), structural summary, mechanism-specific stress + rationale, staleness indicators, admin-power surface, behavioral tier (or "pending"), links to memo + intake sheet. Methodology page stating the named stress principle and factory design. **Static only — no backend, no live anything; the site regenerates when the pipeline runs.** Ships before any harder adapter is built.
10. **USDe as token #4.** Archetype memo #2 (synthetic); scraping adapter with shape-change quarantine; **benchmark gate: reconcile automated output against the manual 16-page report; chase every divergence to "pipeline bug" or "data changed."** Publish a short reproduction note (strong portfolio content).
11. **Expand toward ~10 by archetype coverage** (not popularity): 3–4 CDP-style, 1–2 synthetics, 2–3 fiat-backed (memo #3; attestation-PDF adapter timeboxed with analyst-keyed fallback), 1 hybrid oddity to stress the intake gate. Publish incrementally; the growing set demonstrates the factory claim. 10 is a ceiling; publishing starts at 3.
12. **Phase 2: vaults.** New memo + adapter config on ERC-4626. Out of scope until stablecoins done.
## 9. Webacy status and plan
 
- Endpoints identified from their OpenAPI spec (44 endpoints; paths as recorded by Amin — re-verify before quoting externally): /rwa (universe list, scores/tiers), /rwa/{address} (16-signal decomposition + history + depeg events), /rwa/supply (issuance/redemption flows), /rwa/hci (holder concentration), /v3/rwa/* (A–F structural grades; batch structural-health ≤100 tokens), DEPEG_TIER_CHANGE webhooks; vault surface exists (phase 2). "RWA" is their route naming for pegged assets generally, not RWA-only — but per-token coverage of the chosen 10 must be checked against /rwa on first access.
- Dashboard-only (no API): Backing Map, Yield Scores, Peg Canary Score, Graveyard.
- **Access:** developer portal blocks personal emails; Maika Isogawa (CEO) replied personally asking for the use case; concise builder-framed reply sent (endpoints named, weekly batch pulls, ~10 tokens, attributed, non-commercial). Awaiting response.
- **Decision: build Steps 1–9 without Webacy, launch the site, then approach Maika with a running system** — upgrades the ask from "I plan to build" to "it's running, here's the repo." Job application exists but project positioning is independent research regardless.
## 10. Encoded failure lessons (hard gates)
 
- Collateral filtered by **address, never symbol** (Morpho lesson #1).
- Principal vs. accrued interest separated (Morpho lesson #2).
- No hardcoded market/pool/collateral lists — discovery or staleness-tracked analyst input (Morpho generalized).
- Schema/shape-change quarantine (scraped sources); semantic quarantine (composition/count bounds) for protocol changes.
- Benchmark reconciliation gate (USDe vs. manual report; per-archetype first-token manual spot-check).
- LLM never originates numbers.
## 11. Open points
 
1. ~~Webacy access terms~~ → in progress via Maika thread; build proceeds independently.
2. PegKeeper ruling — first Tier-2 decision, unmade. (Step 1, Amin.)
3. Pool-selection rule exact form (top-N, threshold, refresh cadence) + sensitivity treatment.
4. Look-through depth: one level (working assumption) vs. recursive with decay; where USDC terminates.
5. Evaluator rubric v1 contents (Step 2).
6. Fiat attestation adapter: build vs. analyst-keyed fallback — timebox decision deferred until after USDe.
7. Common stress abstraction ("hours-to-depeg") — rejected as false comparability; revisit only if a defensible middle emerges.
8. Name for the mechanism-specific-stress methodological principle.
9. Site scope guardrail: static only; revisit only if purpose changes from portfolio to product.
10. Webacy coverage diff: on first API access, diff the chosen ~10 against /rwa universe; a missing token = early test of graceful degradation (behavioral tier "unavailable," structural layer publishes).
11. LlamaRisk line-by-line audit pending (URL not accessible from build environment; framework-level gap analysis done → items in §2.3 and §3; paste report text into a session for literal verification).
## 12. Additions from LlamaRisk gap analysis (2026-08, framework-level)
 
Included as necessary: admin-power surface (Tier 1, schema + verifiability conditioning); oracle dependency enumeration (intake sheet + memo stress assumptions); redemption-rights structured fields (intake sheet; "backing you can't claim isn't backing in a run"); counterparty enumeration as schema field (off-chain archetypes); audit status as static metadata. Excluded as not absolutely useful for this system: legal-opinion depth, governance-token analysis, social/adoption metrics.