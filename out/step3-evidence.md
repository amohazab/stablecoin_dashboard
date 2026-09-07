# Step 3 — done-condition evidence: crvUSD adapter

Two runs, 55.73 h apart, under byte-identical config. Generated from the committed bundles; every figure is derived, none hand-entered.

| | run 1 | run 2 |
|---|---|---|
| `run_block` | `25906587` | `25923250` |
| `block_timestamp` | `1788556607` | `1788757235` |
| `run_start_time` | `1788556690` | `1788757313` |
| `first_run` | `True` | `False` |
| `sheet_hash` | `a6d8f12a` | `a6d8f12a` |
| `frozen_set_hash` | `80d87407` | `80d87407` |
| `freeze_date` | `2026-09-04` | `2026-09-04` |
| `pipeline_version` | `0.1.0` | `0.1.0` |
| DET-83 freshness (s) | `83` | `78` |
| `raw_positions_hash` | `fbd54de19ee84422c79e7b275afa3e497dc21e5099a568ddff89c95e2a5b7559` | `4a8747b8acf0fea211044aebac1713c54eebbc75c30461f0360c2612d6b683d4` |
| `bundle_hash` | `51f2548b9c7ee9b8799424ef11653e86ed0699c5e215845e991773bd8f6a0035` | `314fd4feecf199786fe66405b66934604a9ec516b8f60539876b24e312073f68` |

## 1. Gate evaluation, side by side

| entry | run 1 | run 2 |
|---|---|---|
| DET-02 | pass | pass |
| DET-12 | pass | pass |
| DET-77 | pass | pass |
| DET-83 | pass | pass |
| DET-86 | pass | pass |
| DET-01 | pass | pass |
| DET-03 | pass | pass |
| DET-04 | pass | pass |
| DET-07 | pass | pass |
| DET-20 | pass | pass |
| DET-21 | pass | pass |
| DET-33 | pass | pass |
| DET-55 | pass | pass |
| DET-61 | pass | pass |
| DET-62 | pass | pass |
| DET-63 | pass | pass |
| DET-65 | pass | pass |
| DET-68 | pass | pass |
| DET-08 | pass | pass |
| DET-82 | pass | pass |

**20 entries, 20 pass in each run, 0 fail, 0 error, 0 not_applicable, zero triggers, `worst_level 0` both runs.** Identical entry list and order.

### Disclosure — two ruled entries have no harness owner

**DET-10** (S1) was ruled Full at P-3.09 — clauses (a)(b)(c)(e)(f) checked, (d) a no-op at run 1. **DET-66** (S1, Level 3) was in the P-3.07 S1 set. Neither is in `CHECKS`, and neither appears anywhere in `src/factory/`. Neither ran, in either run. The 20-count above is the harness **as built**, not the harness as ruled, and this line is part of the verdict rather than a footnote to it.

The substance both entries exist to gate is independently evidenced in §4 below and is **asserted by comparison, which is not the same thing as gated**: the frozen set file is byte-identical across the pair (`frozen_set_hash 80d87407` both runs, membership unchanged, no re-freeze), and the emitted redemption block matches DET-66's `R1 = none` clause exactly — one path, `r2_who = no_one`, R3–R7 `n/a`, `r6_gates = [{kind: none}]` with `none` exclusive, `r9_legal_claim` present, `r10_provenance` an `AbsenceRead`. DET-10(c)'s detector fields are **absent from both bundles**, so DET-10 would fail today if implemented as written.

Remedy (ruled, P-3.40): both implemented **post-pair**, then demonstrated at the next ordinary run. The completed pair is not re-opened.

## 2. The seven flips — literal beside computed

**(1) DET-86 — prior retrieval.** run 1 `first_run = true`, literals present → run 2 `first_run = false`, `first_run_literals = None`. Prior located: `out/bundles/crvUSD/25906587.json`, the highest `run_block` below 25923250. The state store is real — run 2 read run 1's committed bundle off disk, the exact dependency Step 8's cron rests on.

**(2) DET-62 — supply jump.** literal `'first run - no prior supply'` → computed: prior 2,104,809,204.98 → current 2,104,809,204.98; `jump = 0E-8`; threshold 0.25 **not exceeded**, confirmation branch not entered, figures computed and disclosed regardless per the letter.

**(3) DET-65 — composition shift**, literal `'first run - no prior composition'` → computed against real prior shares, bound 0.10:

| node | run 1 share | run 2 share | Δ |
|---|---|---|---|
| wstETH | 43.9697% | 44.1655% | 0.001958 |
| WBTC | 37.3017% | 37.2288% | 0.000729 |
| tBTC | 6.7806% | 6.6697% | 0.001109 |
| cbBTC | 4.5530% | 4.6446% | 0.000915 |
| WETH | 4.0066% | 3.8933% | 0.001133 |
| sfrxETH | 2.9770% | 2.9850% | 0.000080 |
| weETH | 0.4114% | 0.4132% | 0.000018 |
| LBTC | 0.0000% | 0.0000% | 0.000000 |

max Δshare **0.001958** against the 0.10 bound; no node added, none absent. The deltas are genuinely live — the machinery ran on real data.

**(4) DET-63 — market-count delta.** literal `'first run - no trigger, disclosed'` → computed: mint 9 → 9 (Δ 0); lend `unknown - no lend exclusion data configured` (logged, never triggered). No routing fired.

**(5) DET-10(d) — pool-set detector. NOT EXECUTED — no harness owner** (§1). By comparison: `frozen_set_hash` identical, set file byte-identical, 5 pools, membership unchanged.

**(6) DET-59 — quarantine counter.** No triggers fired in either run, so the counter stays 0 and there are no log entries to write. DET-59 is an **S3** entry (site stage) — correctly outside a Step-3 adapter harness, exercised only when a Level 2/3 actually fires.

**(7) T-27 — bridged component.**

| escrow | type | run 1 | run 2 | Δ |
|---|---|---|---|---|
| `0x3154cf16ccdb4c6d…` | lock_and_mint | 372,820.75 | 372,820.75 | +0.00 |
| `0x99c9fc46f92e8a1c…` | lock_and_mint | 540,734.59 | 540,734.59 | +0.00 |
| `0xa3a7b6f88361f484…` | lock_and_mint | 1,072,255.50 | 1,047,251.44 | -25,004.06 |

burn_and_mint component 0.00 → 0.00. DET-62's bridged clause runs over burn_and_mint rows only (DET-33), so **T-27 did not fire and structurally cannot** while every escrow is lock-and-mint.

**Two flips are stated rather than claimed:** DET-62's confirmation branch (the jump was exactly zero, so the ≥ 0.25 path never opened) and T-27 (no burn-and-mint escrow exists). Both are wired; neither is exercised by evidence. The zero jump is structural, not a stall: crvUSD `totalSupply` equals Σ debt ceilings, so it is piecewise-constant and moves only on a governance ceiling change, never when borrowers draw.

## 3. Must-not-change — equality asserted

| field | value | |
|---|---|---|
| `header.sheet_hash` | `a6d8f12a` | EQUAL |
| `header.frozen_set_hash` | `80d87407` | EQUAL |
| `header.freeze_date` | `2026-09-04` | EQUAL |
| `header.pipeline_version` | `0.1.0` | EQUAL |
| `header.token` | `crvUSD` | EQUAL |
| `counts.mint_market_count` | `9` | EQUAL |
| `counts.lend_market_count` | `unknown - no lend exclusion data configured` | EQUAL |
| `attribution_method` | `direct` | EQUAL |
| node address set | `set of 8, identical` | EQUAL |
| node label set | `set of 8, identical` | EQUAL |
| market address set | `set of 9, identical` | EQUAL |
| stabilizer operation set | `set of 5, identical` | EQUAL |
| bridge address set | `set of 3, identical` | EQUAL |
| `admin_surface` powers | `set of 9, identical` | EQUAL |
| `admin_surface` veto addresses | `set of 9, identical` | EQUAL |
| config `discovery_roots.toml` | `0538f3ca` | EQUAL |
| config `labels.toml` | `96ec22cc` | EQUAL |
| config `crvusd_sheet.toml` | `d3d836a1` | EQUAL |
| config `frozen_set_crvusd.json` | `80d87407` | EQUAL |

**All 19 hold.**

## 4. Must-change — inequality asserted

| field | run 1 | run 2 | |
|---|---|---|---|
| `header.run_block` | `25906587` | `25923250` | DIFFERS |
| `header.block_timestamp` | `1788556607` | `1788757235` | DIFFERS |
| `header.run_start_time` | `1788556690` | `1788757313` | DIFFERS |
| `header.bundle_hash` | `51f2548b9c7ee9b8799424ef…` | `314fd4feecf199786fe66405…` | DIFFERS |
| `header.raw_positions_hash` | `fbd54de19ee84422c79e7b27…` | `4a8747b8acf0fea211044aeb…` | DIFFERS |
| `header.first_run` | `True` | `False` | DIFFERS |
| `first_run_literals` | `present` | `None` | DIFFERS |

**All 7 hold. No crossovers between the two tables.** Block delta 16663; elapsed 55.73 h (200628 s) against the ≥ 24 h bound; run 2's block strictly later, so no archive replay of run 1's state.

**The freeze holds.** `frozen_set_hash` and `freeze_date` identical, membership unchanged, set file byte-identical — run 2 **read** the freeze rather than re-freezing it. Memo §5.6's "never silently updated" is now an observed fact rather than a claim.

## 5. Spot-checks

| run | sheet | transport | result |
|---|---|---|---|
| 1 | `out/spotcheck/25906587.md` | rev 2 | **10/10 PASS**, items 0–9, item 10 informational — executed by the analyst 2026-09-05 |
| 2 | `out/spotcheck/25923250.md` | rev 2 | **PASS**, items 0–9, item 10 informational — executed by the analyst, reported 2026-09-07 |

Run 1's sheet was first executed under the rev-1 transport, which was found defective: Etherscan's `eth_call` proxy ignores `tag` and answers every request at the chain head. Those readings were **indeterminate, not failed** — no value comparison had occurred. The sheet was re-emitted under rev 2 (two independent keyless archive RPCs, agreement required, block pinned inside the JSON-RPC body, item 0 a pin self-test) and re-executed clean. **No value mismatch exists under rev 2.**

## 6. Verdict — four conjuncts, each ticked separately

| # | conjunct | |
|---|---|---|
| 1 | two runs ≥ 24 h apart | **CARRIES** — 55.73 h, strictly later block |
| 2 | both pass S0/S1 | **CARRIES AS BUILT** — 20/20 twice, zero triggers; **DET-10 and DET-66 were never implemented and did not run** (§1) |
| 3 | both spot-checks clean or dispositioned | **CARRIES** — run 1 10/10 PASS; run 2 items 0–9 PASS, no mismatch in either |
| 4 | must-change / must-not-change partition holds | **CARRIES** — 19 equal, 7 differing, no crossovers |

### OVERALL TICK — the done-condition is met, with conjunct 2 disclosed

All four conjuncts carry. Brief §8's Step-3 done-condition — *two runs a day apart pass validation and match a manual spot-check* — is satisfied on the evidence above.

**The tick is issued on the harness as built, and says so.** Conjunct 2 carries against 20 implemented checks; DET-10 and DET-66 were ruled in Step-3 scope and never implemented, so they did not run. Their substance is evidenced by comparison in sections 3 and 4 — asserted, not gated. Both are implemented post-pair and demonstrated at the next ordinary run. A reader who needs the distinction has it here rather than having to find it.

