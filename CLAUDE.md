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

## Session protocol

Every session begins by reading this file **and `PROGRESS.md`** (repo root) before proposing anything. `PROGRESS.md` is the implementation record: what has been decided, built, and verified, in confirmation order.

Its rules bind every session and are stated in the file itself. Two of them govern behaviour before you have read it: **entries are appended only on Amin's explicit confirmation — the agent never self-confirms**, and **confirmed entries are immutable** — never edited, reworded, renumbered, or deleted, not even for typos; an instructed change is a new `AMEND` entry referencing the original, which stands. Confirmed entries are settled: they are not re-opened, re-litigated, or contradicted by later work without an explicit AMEND instruction.

Working rhythm: numbered blocks, one topic per block, **exactly one open proposal at a time**. Per point — propose (with rationale, and real alternatives where a choice exists) → Amin rules → implement exactly what was confirmed → append the `PROGRESS.md` entry → show the appended entry verbatim. Corrections, directives, and rulings are recorded as stated, as-counted not as-proposed. Sessions close with a block listing confirmed points, open points, and flagged items awaiting ruling.

Ask when a choice is a **ruling** (design, scope, thresholds, document content); decide when it is an **implementer default** — and name it as such in the code and docs the way the rubric does, so it is auditable. Never mark your own work done. Never write to `PROGRESS.md` without confirmation. Never touch `docs/context/` without explicit instruction. When a read or an output contradicts a Phase-B `[VERIFIED …]` value, that is a flag, not a correction: report "verified value was X (source, date); live read is Y at block N" and stop that point.

**Stack ruling.** All pipeline code is Python (ruled 2026-09-03, P-3.01). Tooling and version per the P-3 stack entry.

**Scope discipline** (ruled 2026-09-03, P-3.03). This is a portfolio/demo project, not production software. The goal is a working, presentable end-to-end system — not robustness to every edge case. Rules:

1. When choosing between a simple approach and a more "correct" but complex one, default to the simple one unless the difference is visible in the final output.
2. Don't gold-plate: no extensive error handling, config abstraction, test coverage, or optimization unless Amin asks for it.
3. A minor issue or edge case with marginal impact gets one sentence and moves on — never solved unprompted.
4. A task ballooning in scope stops for an is-it-worth-it question instead of absorbing the effort silently.

**Boundary — this directive never overrides:** the hard gates, the rulings in the closed artifacts, or any condition owned by a rubric entry. The system's documented rulings and validation gates ARE the portfolio artifact (brief §1); a check the rubric demands is required output, never gold-plating, and fail-closed behavior where ruled is not "extensive error handling." The directive governs everything the rulings leave open: engineering style, abstraction depth, error handling beyond ruled fail-closed points, test breadth beyond the ruled done-conditions, optimization, and tooling weight. Where the directive and a ruling appear to conflict, that is a flag for Amin, not a judgment call.

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
- **Step 3 — DONE (P-3.41, 2026-09-07):** crvUSD adapter. Discovery from `ControllerFactory`; frozen exit-liquidity set (`config/frozen_set_crvusd.json`, `80d87407`); pinned reads; Pydantic bundle with deterministic hashing; fail-closed S0/S1 harness; quarantine log; spot-check protocol rev 2. Done-condition met on two runs 55.73 h apart, both 20/20, both spot-checked; evidence at `out/step3-evidence.md`. Post-pair application DONE at P-3.47 (2026-09-08).
- **Step 4 — DONE (P-4.20, 2026-09-11):** GHO + LUSD adapters against the same memo and the same harness (brief §8.4; LUSD is the simplicity control). Three adapters, one harness: each token met the two-runs-a-day-apart done-condition with both spot-checks matching — crvUSD P-3.41, GHO P-4.14, LUSD P-4.19. `len(CHECKS)` = 22.
- **Step 5 — DONE (P-5.04, 2026-09-11):** the verifiability module. `uv run python -m factory.tree <TOKEN>` folds the latest promoted bundle into `out/trees/<TOKEN>/<run_block>.json` with no RPC; a tree failing its four S2 checks (DET-14/19/70/11, run by `factory.tree` only) goes to `out/rehearsal/`. Shares are over `backing_value` only; `supply_ruled` stays parked at P-4.01 #3, so the root line carries amounts. crvUSD's and GHO's trees link each other by `token@block`. `len(CHECKS)` = 26. C1–C4 carry the tree's owed inputs.
- **Step 6 — DONE (P-6.12, 2026-09-13):** the CDP stress module (memo §6). `uv run python -m factory.stress <TOKEN>` folds the latest promoted bundle and its tree into `out/stress/<TOKEN>/<run_block>.json`, making pinned reads at the bundle's own `run_block` (R-13) — the first module that reads. Three promoted artifacts, each meeting R17's done-condition with a hand-verified spot-check sheet (all three verified 2026-09-13): `out/stress/crvUSD/25963950.json` (`1617c079`, 47 cells) · `out/stress/GHO/25963961.json` (`f5529480`, 47 cells) · `out/stress/LUSD/25963959.json` (`1db98f26`, 23 cells), all 25/25. Sheets at `out/spotcheck/crvUSD/stress-25963950.md` · `out/spotcheck/GHO/stress-25963961.md` · `out/spotcheck/LUSD/stress-25963959.md` (gitignored, regenerated on promotion). `len(CHECKS)` = 52. Three mechanisms, one cell set and four metrics: crvUSD's LLAMMA bands, GHO's Aave health factors, LUSD's Stability Pool and redistribution. T-02/DET-32's off-venue share is still pending its P5 pointer and moves to Step 7.
- Then: verifiability module (5), CDP stress module (6), report generation + evaluation loop (7), unattended execution (8), static site v1 (9), USDe as token #4 with benchmark reconciliation against the manual report (10), expansion by archetype coverage (11), vaults phase 2 (12).

Code lives in `src/factory/`; config in `config/`; run artifacts in `out/` (bundles committed; raw dumps and spot-check sheets gitignored); tests in `tests/`. Toolchain per P-3.04: Python 3.12, `uv` + `uv.lock`. Invocations that work: `uv run python -m pytest` (not `uv run pytest` — collection fails, P-3.39); `ruff check src tests`; a run is `uv run python -m factory.run <TOKEN>` — one required positional token, `sys.argv[1]`, no default and no env var (P-4.02) — which reads `ETH_RPC_URL` from the environment or from `.env` at the repo root (entry point `execute(repo, rpc_url, token)`, `src/factory/run.py`). Pilot tokens are crvUSD, GHO and LUSD, and **all three have adapters** — the last `OWED` row was deleted at P-4.17, so `OWED` is now empty and an unknown token stops with `AssemblyStop` before any RPC call, which is the shape a fourth token (USDe, Step 10) will use. Rehearsal artifacts — bundles produced by a crashed or aborted run — live in `out/rehearsal/<TOKEN>/`, untracked, and never in `out/bundles/`, which is what `is_first_run` and `load_prior` read (P-3.38, P-4.11). Adapters emit one common schema (collateral composition keyed by contract address, verifiability-split inputs, staleness, provenance, admin-power surface, counterparty enumeration). The site is static only — no backend, no live anything; it regenerates when the pipeline runs.
