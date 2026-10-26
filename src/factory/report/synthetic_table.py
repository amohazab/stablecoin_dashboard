"""P-10.10: the flat table for archetype #2 (memo #2; Q24, Q26, A-28, A-30, A-35, A-39,
A-45, A-50, A-51, ruling K).

Same row shape and the same rule as `table.build_rows`: every value is RESOLVED from
its `source_path` in the bundle, tree, stress report, mirror or wording - never
computed here. A category node is keyed by its slug (`tree.node.crypto_basis.*`),
where an archetype-#1 node is keyed by its address (A-44's exactly-one-of-two).
"""

from __future__ import annotations

import re

from factory.report.table import TableBuilder

SR = "stress/synthetic"
# Q12: the role each held-by-many power is exercised through (V2 FR-U13, sUSDe FR-U14)
ROLE_OF = {"pause": ("FR-U13", "GATEKEEPER_ROLE"),
           "blacklist_address": ("FR-U14", "BLACKLIST_MANAGER_ROLE")}
READS = "bundle/synthetic/reads"


def slug(category: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", category.lower()).strip("_")


def build_rows(bundle: dict, tree: dict, stress: dict, mirror: dict,
               wording: dict | None = None, gate: dict | None = None) -> list[dict]:
    """`gate` carries figures an S1 entry owns and computes (DET-90's `det90_figures`),
    replayed by the report stage from the same bundle - their `source_path` reads
    `gate/DET-90/...`."""
    t = TableBuilder({"bundle": bundle, "tree": tree, "stress": stress, "mirror": mirror,
                      "wording": wording or {}, "gate": gate or {}})
    syn, reads = stress["synthetic"], bundle["synthetic"]["reads"]

    # ---- header (DET-83/87, R3) ---------------------------------------------------------
    for k, u, own in (("token", "literal", "DET-83"), ("run_block", "block", "DET-83"),
                      ("block_timestamp", "unix_s", "DET-83"), ("sheet_hash", "hash", "DET-77"),
                      ("bundle_hash", "hash", "DET-13"), ("pipeline_version", "literal", "DET-87"),
                      ("freeze_date", "date", "DET-29")):
        t.add(f"header.{k}", k.replace("_", " "), f"bundle/header/{k}", u, "header", own)
    t.add("header.tree_hash", "tree hash", "tree/tree_hash", "hash", "header", "DET-84")
    t.add("header.stress_hash", "stress hash", "stress/header/stress_hash", "hash", "header",
          "DET-84")
    t.add("header.disclosure_as_of", "disclosure as-of (status route)",
          f"{READS}/FR-U21/value/as_of", "literal", "header", "DET-74")
    t.add("header.archetype", "archetype", "wording/synthetic/archetype_name", "literal",
          "header", "DET-83")

    # ---- verifiability: 0 / 0 / 100 over the six categories (DET-17 / 14 / 18 / 70) -----
    for i, bar in enumerate(tree["bars"]):
        t.add(f"verif.bar.{bar['name']}", f"bar {i + 1}: {bar['name']}",
              f"tree/bars/[name={bar['name']}]/share", "ratio", "verifiability", "DET-17",
              "backing_value")
    t.add("verif.truncated_share", "depth-truncated share of bar 3", "tree/truncated_share",
          "ratio", "verifiability", "DET-17", "backing_value")
    for n in tree["truncated_nodes"]:
        s, base = slug(n["category"]), f"tree/truncated_nodes/[category={n['category']}]"
        t.add(f"verif.truncated.{s}.share", f"truncated: {n['symbol']}", f"{base}/share",
              "ratio", "verifiability", "DET-17", "backing_value")
        t.add(f"verif.truncated.{s}.reason", f"truncated reason: {n['symbol']}",
              f"{base}/reason", "literal", "verifiability", "DET-17")
    t.add("verif.unlisted_share", "unclassified — pending intake (U)", "tree/shares/unlisted",
          "ratio", "verifiability", "DET-17", "backing_value")
    t.add("verif.unclassified_literal", "unclassified literal", "tree/unclassified_literal",
          None, "verifiability", "DET-17")
    st = tree["staleness"]
    for k, u in (("weighted_days", "days"), ("status", "literal"), ("companion", "literal")):
        t.add(f"verif.staleness.{k}", f"staleness {k.replace('_', ' ')}", f"tree/staleness/{k}",
              u if st[k] is not None else "null", "verifiability", "DET-18")
    if st["worst"]:
        for k, u in (("symbol", "literal"), ("days", "days"), ("share", "ratio")):
            t.add(f"verif.staleness.worst.{k}", f"worst node {k}", f"tree/staleness/worst/{k}",
                  u, "verifiability", "DET-18", "backing_value" if k == "share" else None)
    for n in st["D"]:
        s, base = slug(n["category"]), f"tree/staleness/D/[category={n['category']}]"
        for k, u, d in (("last_disclosure_date", "date", None), ("staleness_days", "days", None),
                        ("share", "ratio", "backing_value")):
            t.add(f"verif.staleness.{s}.{k}", f"{n['symbol']} {k.replace('_', ' ')}",
                  f"{base}/{k}", u, "verifiability", "DET-18", d)
    for i in range(len(tree["synthetic"]["t29"])):
        for k, u in (("category", "literal"), ("cadence", "literal"), ("age_days", "days"),
                     ("overdue", "boolean")):
            t.add(f"verif.t29.{i}.{k}", f"disclosure cadence {k.replace('_', ' ')}",
                  f"tree/synthetic/t29/{i}/{k}", u, "verifiability", "DET-18")
    t.add("verif.banner", "admin qualifier banner", "tree/banner", "literal", "verifiability",
          "DET-70")
    for n in tree["nodes"]:
        s, base = slug(n["category"]), f"tree/nodes/[category={n['category']}]"
        t.add(f"tree.node.{s}.symbol", "disclosure category", f"{base}/symbol", "literal",
              "verifiability", "DET-17")
        t.add(f"tree.node.{s}.label", "node label", f"{base}/label", "literal",
              "verifiability", "DET-17")
        t.add(f"tree.node.{s}.bar", "backing class of the node",
              f"wording/tree/node_bar/{n['label']}", "literal", "verifiability", "DET-17")
        t.add(f"tree.node.{s}.share", f"{n['symbol']} share of backing", f"{base}/share",
              "ratio", "verifiability", "DET-17", "backing_value")
        t.add(f"tree.node.{s}.usd", f"{n['symbol']} attested value",
              f"{READS}/FR-U20/value/{n['category']}", "usd", "verifiability", "DET-17")
    for i, r in enumerate(tree["synthetic"]["label_rows"]):
        base = f"tree/synthetic/label_rows/{i}"
        for k, u in (("symbol", "literal"), ("label", "literal"), ("recurses_into", "literal"),
                     ("chain", "literal"), ("roles", "list")):
            t.add(f"tree.label_row.{i}.{k}", f"label row {k.replace('_', ' ')}",
                  f"{base}/{k}", u, "verifiability", "DET-17")
        t.add(f"tree.label_row.{i}.last_disclosure_date", "label row last disclosure",
              f"{base}/last_disclosure_date", "date" if r["last_disclosure_date"] else "null",
              "verifiability", "DET-18")
    rf = "tree/synthetic/reserve_fund"
    t.add("verif.reserve_fund.slice", "reserve fund", f"{rf}/slice", "literal", "verifiability",
          "DET-19")
    t.add("verif.reserve_fund.credited", "reserve fund credited as backing", f"{rf}/credited",
          "boolean", "verifiability", "DET-19")
    t.add("verif.reserve_fund.disclosed_usd", "reserve fund (status route)",
          f"{rf}/disclosed_usd", "usd", "verifiability", "DET-19")
    for k in sorted(tree["denominators"]):
        t.add(f"denominator.{k}", f"denominator of {k}", f"tree/denominators/{k}", "denominator",
              "verifiability", "DET-19")

    # ---- supply: the four classes, cooldownDuration beside staked (Q24, A-29) -----------
    for k in ("total_supply", "supply_ruled", "origination_sum", "residual",
              "residual_unexplained"):
        t.add(f"supply.{k}", k.replace("_", " "), f"bundle/supply/{k}", "base_units", "supply",
              "DET-15")
    t.add("supply.stabilizer_over_supply", "stabilizer debt / supply_ruled",
          "bundle/supply/stabilizer_over_supply", "ratio", "supply", "DET-16", "supply_ruled")
    for k in ("staked", "cooling", "bridged_escrow", "free_float"):
        t.add(f"supply.class.{k}", f"supply class: {k.replace('_', ' ')}",
              f"tree/synthetic/supply_classes/{k}", "base_units", "supply", "DET-15")
    t.add("supply.cooldown_s", "sUSDe cooldownDuration()", f"{READS}/FR-U04/value", "seconds",
          "supply", "DET-15")
    t.add("supply.bridge_disclosure", "bridge line", "bundle/supply/bridge_disclosure", "literal",
          "supply", "DET-33")
    for k, u in (("backing_value", "usd"), ("value_scale", "count"),
                 ("backed_supply", "base_units"), ("perimeter", "literal")):
        t.add(f"tree.root.{k}", k.replace("_", " "), f"tree/root/{k}", u, "supply", "DET-15")
    t.add("tree.root.status_backing", "backing (status route totalBackingAssetsInUsd)",
          "tree/synthetic/status_backing_usd", "usd", "supply", "DET-15")
    # ruling K: the six categories' sum (collateral-breakdown) against the headline's
    # status backing, signed, beside the headline; no trigger
    t.add("tree.root.backing_difference", "sum of categories less status backing",
          "difference:tree/root/backing_value|tree/synthetic/status_backing_usd", "usd",
          "supply", "DET-15")
    t.add("stabilizer.slice.debt", "protocol stabilizer debt", "tree/stabilizer_slice/debt",
          "base_units", "supply", "DET-22")
    t.add("stabilizer.slice.ceiling_aggregate", "stabilizer ceiling aggregate",
          "tree/stabilizer_slice/ceiling_aggregate", "base_units", "supply", "DET-22")
    t.add("stabilizer.slice.ceiling_share", "stabilizer ceiling aggregate / supply_ruled",
          "tree/stabilizer_slice/ceiling_share_of_supply_ruled", "ratio", "supply", "DET-22",
          "supply_ruled")

    # ---- DET-90's reconciliation line (A-50) --------------------------------------------
    # The gap's figures are DET-90's (`det90_figures`); the rows below are what the page
    # prints of them, from the gate record's stored inputs - the route and the buffer reads.
    # P-10.10 NAMED IMPLEMENTER DEFAULT: DET-61's row (A-37), from the entry's own figures
    for k, lab in (("backing_ratio", "backing / supply_ruled"),
                   ("backing_ratio_bound", "backing ratio bound (T-07 below it)"),
                   ("reserve_fund_ratio", "reserve fund / supply_ruled"),
                   ("reserve_fund_ratio_bound", "reserve fund ratio bound (T-07 below it)")):
        t.add(f"near_bound.{k}", lab, f"gate/DET-61/{k}", "ratio", "mechanism state", "DET-61",
              "supply_ruled")
    g = "gate/DET-90"
    for k, lab in (("buffer_onchain", "on-chain buffer at par"),
                   ("disclosure_onchain", "route Liquid Stables, Ethereum entries"),
                   ("gap", "reconciliation gap"), ("not_reconciled_total",
                                                   "disclosed, not reconciled (receipt tokens)")):
        t.add(f"recon.{k}", lab, f"{g}/{k}", "usd", "verifiability", "DET-90")
    t.add("recon.gap_share", "gap / backing", f"{g}/gap_share", "ratio", "verifiability",
          "DET-90", "backing")
    t.add("recon.buffer_share", "on-chain buffer / backing", f"{g}/buffer_share", "ratio",
          "verifiability", "DET-90", "backing")
    for k in sorted((gate or {}).get("DET-90", {}).get("not_reconciled", {})):
        t.add(f"recon.not_reconciled.{slug(k)}", f"not reconciled: {k}",
              f"{g}/not_reconciled/{k}", "usd", "verifiability", "DET-90")

    # ---- stress: the three rows (memo #2 §6; Q15-Q17, D3, D16, F1, E8) ------------------
    for k, u in (("basis", "usd"), ("F", "ratio"), ("backing", "usd"),
                 ("reserve_fund", "usd"), ("supply_ruled", "usd")):
        t.add(f"stress.input.{k}", f"stress input {k.replace('_', ' ')}",
              f"{SR}/inputs/{k}", u, "stress", "DET-57", "per_year" if k == "F" else None)
    for k, u in (("quarter", "literal"), ("value_pct", "ratio"),
                 ("negative_quarter_observed", "boolean")):
        t.add(f"stress.refpoint.{k}", f"funding reference point {k.replace('_', ' ')}",
              f"{SR}/inputs/reference_point/{k}", u, "stress", "DET-48")
    for k in ("row1", "row2", "row2_beside", "row3"):
        t.add(f"stress.headline.{k}", f"headline cell, {k.replace('_', ' ')}",
              f"{SR}/headlines/{k}", "literal", "stress", "DET-38")
    units = {"N": "count", "loss": "usd", "post_loss_backing": "usd", "post_loss_ratio": "ratio",
             "location": "literal", "location_total": "usd", "exchange": "literal",
             "notional": "usd", "X": "usd", "free_float": "usd", "staked": "usd",
             "cooldown_s": "seconds", "branch": "literal", "capacity_redeem": "usd",
             "stablecoin_collateral": "usd", "rate_cap_7d": "usd", "exit_depth_2pct": "usd",
             "depeg_pressure_ratio": "ratio"}
    for c in syn["cells"]:
        base = f"{SR}/cells/[id={c['id']}]"
        for k in (k for k in units if k in c):
            t.add(f"cell.{c['id']}.{k}", f"{c['id']} {k.replace('_', ' ')}", f"{base}/{k}",
                  units[k], "stress", "DET-41" if c["row"] == 3 else "DET-39",
                  "supply_ruled" if k == "post_loss_ratio" else None)
        if c["row"] in (1, 2):            # D3: the reserve fund absorbs first, up to its size
            t.add(f"cell.{c['id']}.rf_absorbed", f"{c['id']} reserve fund absorbed",
                  f"min:{base}/loss|{SR}/inputs/reserve_fund", "usd", "stress", "DET-39")
        for ln in c["counterfactual_lines"]:
            lb = f"{base}/counterfactual_lines/[id={ln['id']}]"
            for k in (k for k in ("literal", "branch", "X", "value_counterfactual") if k in ln):
                t.add(f"cell.{c['id']}.cf.{ln['id']}.{k}", f"{c['id']} counterfactual {k}",
                      f"{lb}/{k}", ("usd" if k == "X" else "ratio" if k == "value_counterfactual"
                                    and ln[k] is not None else "null"
                                    if ln[k] is None else "literal"), "stress", "DET-44")
        for r in c.get("k_rows", []):
            kb = f"{base}/k_rows/[k={r['k']}]"
            t.add(f"cell.{c['id']}.K{r['k']}.depth_at_2pct", f"K-subset {r['k']}% depth",
                  f"{kb}/depth_at_2pct", "usd", "stress", "DET-30")
            t.add(f"cell.{c['id']}.K{r['k']}.ratio", f"K-subset {r['k']}% depeg-pressure ratio",
                  f"{kb}/ratio", "ratio", "stress", "DET-30")
    for k in sorted(syn["assumptions"]):
        t.add(f"assumption.{k}", f"assumption: {k}", f"{SR}/assumptions/{k}", "literal",
              "assumptions", "DET-57")

    # ---- exit liquidity (DET-30 / 31 / 11 / 32 / 36), one frozen pool -------------------
    ed = "stress/exit_depth"
    for r in stress["exit_depth"]["sensitivity_rows"]:
        t.add(f"exit.sensitivity.K{r['k']}.depth", f"K-subset {r['k']}% depth at s = 2%",
              f"{ed}/sensitivity_rows/[k={r['k']}]/depth_at_2pct", "base_units",
              "exit liquidity", "DET-30")
        t.add(f"exit.sensitivity.K{r['k']}.share_of_F", f"K-subset {r['k']}% share of F",
              f"{ed}/sensitivity_rows/[k={r['k']}]/share_of_F", "ratio", "exit liquidity",
              "DET-30", "frozen_set_tvl")
    for p in stress["exit_depth"]["depth_curve"]:
        t.add(f"exit.curve.s{p['s']}.s", f"depth curve price impact {p['s']}",
              f"{ed}/depth_curve/[s={p['s']}]/s", "ratio", "exit liquidity", "DET-31",
              "price_impact")
        t.add(f"exit.curve.s{p['s']}.total", f"depth curve s = {p['s']} total",
              f"{ed}/depth_curve/[s={p['s']}]/total", "base_units", "exit liquidity", "DET-31")
    t.add("exit.lp_flight_literal", "LP-flight assumption line", f"{ed}/lp_flight_literal",
          "literal", "exit liquidity", "DET-36")
    if stress["exit_depth"]["concentration"]:
        for k, u, d in (("largest_paired_asset", "address", None),
                        ("share_of_exit_depth", "ratio", "exit_depth"), ("label", "literal", None)):
            t.add(f"exit.concentration.{k}", f"concentration {k.replace('_', ' ')}",
                  f"{ed}/concentration/{k}", u, "exit liquidity", "DET-11", d)
    for p in bundle["pools"]:
        if p["in_frozen_set"]:
            t.add(f"exit.pool.{p['address']}.tvl", "frozen pool TVL at par",
                  f"bundle/pools/[address={p['address']}]/tvl_at_par", "usd_whole",
                  "exit liquidity", "DET-10")
    o = "bundle/offvenue_share"
    for k, u in (("dex_liquidity_total_discovered", "usd_whole"),
                 ("curve_mainnet_liquidity", "usd_whole"), ("x", "ratio"),
                 ("literal", "literal"), ("source", "literal"), ("date", "date")):
        t.add(f"exit.offvenue.{k}", f"off-venue {k.replace('_', ' ')}", f"{o}/{k}",
              u if bundle["offvenue_share"][k] is not None else "null", "exit liquidity",
              "DET-32", "dex_liquidity_total_discovered" if k == "x" else None)

    # ---- the bias table (DET-53, A-32: no ★ rows, `n/a` with its reason) ---------------
    for i in range(len(mirror.get("bias_table", []))):
        for k, u in (("direction", "literal"), ("mechanism", "literal"), ("tokens", "list"),
                     ("reason", "literal")):
            t.add(f"bias.{i}.{k}", f"bias {k}", f"mirror/bias_table/{i}/{k}", u, "stress",
                  "DET-53")

    # ---- redemption: R1-R9, R2 beside R8 (DET-66, A-39, D7) -----------------------------
    rp = "bundle/redemption_paths/0"
    for k, u in (("r1_path", "literal"), ("r2_who", "literal"), ("r3_received", "list"),
                 ("r4_rate", "literal"), ("r5_minimum", "literal"), ("r7_capacity", "literal"),
                 ("r8", "literal"), ("r9_legal_claim", "literal")):
        t.add(f"redemption.{k}", f"redemption {k[:2].upper()}", f"{rp}/{k}", u, "redemption",
              "DET-66")
    t.add("redemption.r2_words", "who can redeem, in words",
          f"wording/synthetic/r2/{bundle['redemption_paths'][0]['r2_who']}", "literal",
          "redemption", "DET-66")
    for i in range(len(bundle["redemption_paths"][0]["r6_gates"])):
        t.add(f"redemption.r6.{i}", "redemption R6 gate",
              f"{rp}/r6_gates/{i}/kind", "literal", "redemption", "DET-66")

    # ---- DET-55 attested rows and the buffer reference feeds (A-35, A-46) ---------------
    for cat in sorted(tree["synthetic"]["attested_rows"]):
        s, base = slug(cat), f"tree/synthetic/attested_rows/{cat}"
        for k in sorted(tree["synthetic"]["attested_rows"][cat]):
            t.add(f"oracle.attested.{s}.{k}", f"{cat} oracle row {k.replace('_', ' ')}",
                  f"{base}/{k}", None, "oracle table", "DET-55")
    for sym in sorted(reads["FR-U28"]["value"]):
        base = f"{READS}/FR-U28/value/{sym}"
        t.add(f"oracle.feed.{sym}.answer", f"{sym} Chainlink reference answer",
              f"{base}/answer", "decimal8", "oracle table", "DET-54")
        t.add(f"oracle.feed.{sym}.updated_at", f"{sym} reference updated at",
              f"{base}/updated_at", "unix_s", "oracle table", "DET-54")
    for i in range(len(mirror.get("oracle_feed", []))):
        for k, u in (("symbol", "literal"), ("feed", "address"), ("deviation_bps", "bps"),
                     ("heartbeat_s", "seconds")):
            t.add(f"oracle.sheet.{i}.{k}", f"reference feed {k.replace('_', ' ')}",
                  f"mirror/oracle_feed/{i}/{k}", u, "oracle table", "DET-54")

    # ---- admin surface A1-A8 (DET-68) and the banner sentence (A-51) --------------------
    for r in bundle["admin_surface"]:
        sel = f"bundle/admin_surface/[power={r['power']},holder_address={r['holder_address']}]"
        rid = f"admin.{r['power']}.{r['holder_address']}"
        for k, a, u in (("holder_address", "A2 holder", "address"),
                        ("holder_type", "A2 type", "literal"),
                        ("delay_seconds", "A4 delay", "seconds"),
                        ("delay_bucket", "A4 bucket", "literal"),
                        ("veto_address", "A5 veto", "address"),
                        ("upgradeability", "A6", "literal"), ("scope", "A7 scope", "list")):
            t.add(f"{rid}.{k}", f"{r['power']} {a}", f"{sel}/{k}",
                  u if r[k] is not None else "null", "admin surface", "DET-68")
        t.add(f"{rid}.A8", f"{r['power']} A8 provenance", f"{sel}/provenance/kind", "literal",
              "admin surface", "DET-68")
        if r["provenance"].get("function"):
            t.add(f"{rid}.A8.function", f"{r['power']} A8 function", f"{sel}/provenance/function",
                  "literal", "admin surface", "DET-68")
    t.add("admin.restricted_count", "fully restricted sUSDe addresses", f"{READS}/FR-U32/value",
          "count", "admin surface", "DET-68")
    # P-10.10 r7: every holder of the role a power is held through (Q12), a Safe's
    # threshold beside it (FR-U17)
    safes = reads["FR-U17"]["value"]
    for power, (tag, role) in ROLE_OF.items():
        for i, a in enumerate(reads[tag]["value"].get(role, [])):
            t.add(f"admin.role.{power}.{i}.holder", f"{power} role holder ({role})",
                  f"{READS}/{tag}/value/{role}/{i}", "address", "admin surface", "DET-68")
            if a in safes:
                for k in ("threshold", "owners"):
                    t.add(f"admin.role.{power}.{i}.safe_{k}", f"{power} holder Safe {k}",
                          f"{READS}/FR-U17/value/{a}/{k}", "count" if k == "threshold"
                          else "list", "admin surface", "DET-68")

    # ---- §14: counterparties, audits (DET-73 A-30, DET-74 A-40) ------------------------
    route = reads["FR-U36"]["value"]
    for loc in sorted(route["location_totals"]):
        t.add(f"counterparty.location.{slug(loc)}", f"custody location {loc}",
              f"{READS}/FR-U36/value/location_totals/{loc}", "usd", "audit", "DET-73")
    for ex in sorted(route["exchange_notional"]):
        t.add(f"counterparty.exchange.{slug(ex)}", f"hedge exchange {ex}",
              f"{READS}/FR-U36/value/exchange_notional/{ex}", "usd", "audit", "DET-73")
    sm = bundle["static_metadata"]
    for i in range(len(sm["audits"])):
        for k in ("firm", "date", "scope"):
            t.add(f"audit.{i}.{k}", f"audit {k}", f"bundle/static_metadata/audits/{i}/{k}",
                  "date" if k == "date" else "literal", "static metadata", "DET-73")
    for k in ("platform", "max"):
        t.add(f"audit.bug_bounty.{k}", f"bug bounty {k}", f"bundle/static_metadata/bug_bounty/{k}",
              "literal", "static metadata", "DET-73")
    for k, u in (("last_material_change_audited", "literal"), ("staleness_date", "date"),
                 ("counterparties", "literal")):
        t.add(f"audit.{k}", k.replace("_", " "), f"bundle/static_metadata/{k}", u,
              "static metadata", "DET-73")
    for k in sorted(mirror.get("audit_tag_date", {})):
        t.add(f"audit.tag_date.{k}", f"{k} analyst-supplied date",
              f"mirror/audit_tag_date/{k}", "date", "audit", "DET-74")
    return t.rows
