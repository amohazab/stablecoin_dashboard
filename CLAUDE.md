# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

An automated **stablecoin structural-risk report factory**: given a list of stablecoins (~10 target; pilot = crvUSD, GHO, LUSD), generate a comparable structural risk report for each, running unattended on a weekly schedule, published as a static site (GitHub Pages) + PDFs. The system itself — with its documented design rulings and validation gates — is the primary portfolio artifact; the reports are output samples proving it works.

Two analytical layers:
- **Layer 1 (behavioral/liquidity)** — consumed from an external API (Webacy, access pending) behind an interface; never rebuilt. Until access lands: "behavioral tier: pending" or a thin DefiLlama/Dune substitute.
- **Layer 2 (structural/backing)** — owned; the differentiator. Adapters read backing on-chain, a weighted look-through tree scores how *verifiable* that backing is, and a mechanism-specific stress model runs against it. Stress is deliberately not comparable across mechanism classes — uniform scenarios across different failure mechanisms produce comparable-looking numbers that mean different things.

## Design documents (all in `docs/context/`)

| File | Role |
|---|---|
| `stablecoin-risk-factory-brief.md` | Project-level design: architecture, work model, implementation step order, encoded failure lessons, open points. |
| `archetype-memo-1-cdp.md` | Class-level rulings for the CDP/on-chain-backed archetype (backing definition, look-through policy, pool selection, stress family, quarantine bounds, hard gates §9). |
| `intake-sheets-cdp.md` | Per-token instantiation for crvUSD, GHO, LUSD: contracts to read, collateral node tables, token-specific mechanisms, redemption rights, admin-power surface. |
| `rubic_v1.md` | Evaluator rubric v1 (filename typo is as-is; do not rename — its header checksums reference the artifact set). Deterministic entries DET-xx by stage S0→S3, LLM-judged entries, trigger table T-01…T-27, ruling index, evaluation-loop contract. |
| `phase-b-checklist.md` | Closed fact-verification record (39 items, all finalized). Historical record, not a live worklist. |

Precedence: brief → memo → sheets. A sheet instantiates memo rulings and never restates or overrides them. One owner per checkable condition; everything else cross-references by section or entry ID — never duplicate a rule into a second document.

## Design rulings are FINAL — do not re-open

The memo, intake sheets, rubric, and Phase B checklist are **closed, finalized judgment artifacts** (Phase A closed 2026-09-01; Phase B complete 2026-09-02; rubric v1 final 2026-09-03). The agent must not re-open, amend, "improve," or re-make any ruling in them — in the documents themselves or implicitly in code — without the analyst's explicit sign-off.

- If a verified fact contradicts a ruling's premise, **flag it** ("ruling X assumed Y; current state is Z — needs re-ruling") and stop; never re-rule it yourself.
- Rejected alternatives recorded in the docs ("*Rejected:* …") are part of the ruling. Do not resurrect them.
- Rubric changes go through its amendment log (§5); memo/sheet changes require refreshing the checksum stamp in the rubric header.
- Marker conventions to preserve exactly when editing: `[VERIFIED <date>: …]` (fact + source), `[FIRST-RUN READ: …]` (live value the adapter reads per run — never hardcode it), `[ANALYST-SUPPLIED <date>: …]` (staleness-tracked manual input), `[RE-SCOPED TO INTAKE: …]`. Mechanism logic carries no marker.

The core design principle: **judgment moves from runtime to design time.** Rulings are made once (memo per archetype, sheet per token) and code enforces them per run. No per-report judgment exists in production.

## Three-tier work model

- **Tier 1 — fully automated:** adapter data collection; admin-power-surface reads; deterministic validation; verifiability computation; stress runs; monitoring-brief generation; site regeneration.
- **Tier 2 — archetype-templated:** the memos. Judgment exercised once per archetype, enforced by code per coin.
- **Tier 3 — permanently manual (the analyst's):** intake gate for new tokens; deep-dive theses on flagged tokens; quarantine/semantic-flag reviews; template fixes when a report fails evaluation twice.

Interactive agent sessions (Claude Code) are the **dev environment only**. Production is scheduled deterministic scripts (GitHub Actions cron); nothing may require a live agent babysitting a run.

## Hard gates (brief §10, memo §9 — not negotiable defaults)

- **Collateral filtered by contract address, never symbol.**
- Principal separated from accrued interest in all debt reads.
- **No hardcoded market / pool / collateral / stabilizer lists.** Discovery from factory, registry, or regulator contracts (crvUSD: `ControllerFactory`; PegKeepers: `PegKeeperRegulator.peg_keepers`; GHO: `GhoToken.getFacilitatorsList()`) — or a staleness-tracked analyst-supplied list. Any static list is itself an analyst input with a date.
- **Schema/shape-change quarantine** on scraped sources — quarantine on shape change rather than publishing garbage; **semantic quarantine** (composition/count bounds) for protocol changes. Severity ladder (memo §8.1, per token, never global): Level 1 = publish with visible flag; Level 2 = this token's report not published; Level 3 = pipeline halts for this token before analysis. Every trigger declares its level where it's defined and must match the rubric's printed trigger table row-for-row, or the pipeline does not start.
- **LLM never originates numbers.** Numbers come from data artifacts; the LLM writes prose around them, via structured outputs behind validation gates.
- Mint markets (new supply against collateral) separated from lend markets (re-lending); discovery by factory/controller address class, never by symbol.
- Stabilizer netting: the stablecoin's own leg of a stabilizer LP position is never backing and never value. Position netting: stablecoin held inside a borrower position nets against that position's debt.
- Unlisted collateral node → quarantine (§8.2), never "other." The verifiability label set is closed at four states (`terminal`, `terminal_other_layer`, `recurses`, `recurses_truncated`).
- Three-way discovery cross-validation (RPC vs. DefiLlama vs. Dune); mismatch > 5% → quarantine.
- Block pinning: all Tier-1 contract reads in a run carry one `run_block`; deviation is Level 3.
- **Gate integrity / hard loop rule:** generate → evaluate → **one** revision → ship or quarantine. Second failure = template defect → fix template, rerun. Findings patch templates/rubrics/prompts, **never individual reports**. No hand-editing path exists; editing outputs instead of templates falsifies the factory claim.

## Where implementation stands

Per brief §8 step order:

- **Step 1 — DONE:** archetype memo #1 (CDP) + intake sheets for crvUSD, GHO, LUSD. Phase A + Phase B complete.
- **Step 2 — DONE:** evaluator rubric v1 (closed 2026-09-03).
- **Step 3 — NEXT:** crvUSD adapter. Factory-contract market discovery; RPC/multicall state reads including PegKeeper pools and admin-power surface; three-way cross-validation; emits the common schema. Done when two runs a day apart pass validation and match a manual spot-check.
- Then: GHO + LUSD adapters (4), verifiability module (5), CDP stress module (6), report generation + evaluation loop (7), unattended execution (8), static site v1 (9), USDe as token #4 with benchmark reconciliation against the manual report (10), expansion by archetype coverage (11), vaults phase 2 (12).

There is no code, build system, or test suite in the repo yet — do not invent commands. Adapters emit one common schema (collateral composition keyed by contract address, verifiability-split inputs, staleness, provenance, admin-power surface, counterparty enumeration). The site is static only — no backend, no live anything; it regenerates when the pipeline runs.
