"""B-10: the flat table (DET-84) - one per token, rows copied from the bundle, the
tree, the stress report and the sheet mirror by `source_path`.

Row: `{field_id, label, value, unit, denominator, section, owner_entry,
source_path}`. Every value is RESOLVED from its `source_path`, never computed
here: no rubric entry names the table as the owner of a figure, so the table
owns none (P-7.01 R3; inventory C.1). The page's headline panel and the judge's
table are drawn from these rows (DET-84, DET-57); the full 47-cell grid is not
a row set yet (the d = 0 panel and the headline cell are).

`table_hash` = sha256 over the canonical JSON of `{token, run_block, rows,
assumptions}` (sorted keys, tight separators, UTF-8) - the fourth component of
`report_hash` (R3).

NAMED DEFAULTS (B-10): `unit` vocabulary - `base_units` (the token's 18-dp base
units, R-B2.1), `value_scale_units` (tree node values in the tree's
`value_scale`), `usd_whole`, `ratio`, `bps`, `seconds`, `days`, `date`,
`unix_s`, `block`, `count`, `address`, `hash`, `literal`, `boolean`, `list`,
`token_units`, `denominator`, `null`; inferred by value type only for the m4
map, whose keys vary by mechanism. `section` is the trigger table's section name
where one exists (DET-58), otherwise the page section the row renders in.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from factory.report.paths import resolve

ADDR = re.compile(r"^0x[0-9a-f]{40}$")
HEADLINE = "M1-s50-d0-lp0"                     # memo §6.2.6, DET-38's headline cell

# m4 keys -> owning entry (the rest are DET-38's key set, generically)
M4_OWNER = {
    "alpha": "DET-45", "beta": "DET-45", "effective": "DET-45", "naive": "DET-45",
    "is_killed": "DET-45", "provide_allowed": "DET-45", "withdraw_allowed": "DET-45",
    "burn_capacity": "DET-27", "pegkeeper_lp_share": "DET-27", "paired_units_held": "DET-27",
    "pool_tilt_post_cell": "DET-27", "ceiling_aggregate": "DET-26",
    "stabilizer_debt_post_cell": "DET-26", "utilization_post_cell": "DET-26",
    "binding_side": "DET-47", "gho_sourceable": "DET-47", "collateral_sellable": "DET-47",
    "gsm_mint_headroom": "DET-47", "facilitator_bucket_levels": "DET-47",
    "freezer_state": "DET-46",
    "sp_effective_cell": "DET-51", "redistributed_debt": "DET-51",
    "redistributed_positions_below_100": "DET-51", "tcr_post": "DET-51",
    "recovery_mode_flag": "DET-51", "redemption_capacity": "DET-51",
    "counterfactual_ref": "DET-44", "oracle_spot_gap": "DET-48",
    "exit_depth_cell": "DET-42", "lp_flight_share": "DET-42",
}


def _unit_of(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "base_units"
    if isinstance(v, list):
        return "list"
    if isinstance(v, str):
        if ADDR.match(v):
            return "address"
        try:
            float(v)
            return "ratio"
        except ValueError:
            return "literal"
    return "literal"


class TableBuilder:
    def __init__(self, sources: dict[str, Any]):
        self.sources = sources
        self.rows: list[dict] = []
        self.ids: set[str] = set()

    def add(self, field_id: str, label: str, path: str, unit: str | None, section: str,
            owner: str, denominator: str | None = None) -> str:
        if field_id in self.ids:
            raise ValueError(f"duplicate field_id {field_id}")
        value = resolve(self.sources, path)
        self.rows.append({"field_id": field_id, "label": label, "value": value,
                          "unit": unit or _unit_of(value), "denominator": denominator,
                          "section": section, "owner_entry": owner, "source_path": path})
        self.ids.add(field_id)
        return field_id

    def walk(self, prefix: str, label: str, path: str, section: str, owner_of,
             denominator: str | None = None) -> None:
        """One row per scalar under a nested map (the m4 map, keeper dicts)."""
        node = resolve(self.sources, path)
        if isinstance(node, dict):
            for k in sorted(node):
                self.walk(f"{prefix}.{k}", f"{label} · {k}", f"{path}/{k}", section,
                          owner_of, denominator)
        else:
            self.add(prefix, label, path, None, section, owner_of(prefix), denominator)


def build_rows(bundle: dict, tree: dict, stress: dict, mirror: dict) -> list[dict]:
    """The row set, token-shaped by what the artifacts carry."""
    t = TableBuilder({"bundle": bundle, "tree": tree, "stress": stress, "mirror": mirror})

    # ---- header (DET-83/87, R3) --------------------------------------------------------
    for k, u, own in (("token", "literal", "DET-83"), ("run_block", "block", "DET-83"),
                      ("block_timestamp", "unix_s", "DET-83"), ("sheet_hash", "hash", "DET-77"),
                      ("bundle_hash", "hash", "DET-13"), ("pipeline_version", "literal", "DET-87"),
                      ("freeze_date", "date", "DET-29")):
        t.add(f"header.{k}", k.replace("_", " "), f"bundle/header/{k}", u, "header", own)
    t.add("header.tree_hash", "tree hash", "tree/tree_hash", "hash", "header", "DET-84")
    t.add("header.stress_hash", "stress hash", "stress/header/stress_hash", "hash", "header",
          "DET-84")

    # ---- verifiability (DET-17 / 14 / 18 / 70 / 11) -----------------------------------
    for i, bar in enumerate(tree["bars"]):
        t.add(f"verif.bar.{bar['name']}", f"bar {i + 1}: {bar['name']}",
              f"tree/bars/[name={bar['name']}]/share", "ratio", "verifiability", "DET-17",
              "backing_value")
    t.add("verif.truncated_share", "depth-truncated share of bar 3", "tree/truncated_share",
          "ratio", "verifiability", "DET-17", "backing_value")
    for n in tree["truncated_nodes"]:
        base = f"tree/truncated_nodes/[address={n['address']}]"
        t.add(f"verif.truncated.{n['address']}.share", f"truncated: {n['symbol']}",
              f"{base}/share", "ratio", "verifiability", "DET-17", "backing_value")
        t.add(f"verif.truncated.{n['address']}.reason", f"truncated reason: {n['symbol']}",
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
        base = f"tree/staleness/D/[address={n['address']}]"
        for k, u, d in (("last_disclosure_date", "date", None), ("staleness_days", "days", None),
                        ("share", "ratio", "backing_value")):
            t.add(f"verif.staleness.{n['address']}.{k}", f"{n['symbol']} {k.replace('_', ' ')}",
                  f"{base}/{k}", u, "verifiability", "DET-18", d)
    t.add("verif.banner", "admin qualifier banner", "tree/banner", "literal", "verifiability",
          "DET-70")
    for k in sorted(tree["denominators"]):
        t.add(f"denominator.{k}", f"denominator of {k}", f"tree/denominators/{k}", "denominator",
              "verifiability", "DET-19")

    # ---- supply (DET-15 / 16, the off-mainnet line) ------------------------------------
    for k in ("total_supply", "supply_ruled", "origination_sum", "residual",
              "residual_unexplained"):
        t.add(f"supply.{k}", k.replace("_", " "), f"bundle/supply/{k}", "base_units", "supply",
              "DET-15")
    t.add("supply.stabilizer_over_supply", "stabilizer debt / supply_ruled",
          "bundle/supply/stabilizer_over_supply", "ratio", "supply", "DET-16", "supply_ruled")
    for c in bundle["supply"]["residual_causes"]:
        base = f"bundle/supply/residual_causes/[address={c['address']}]"
        t.add(f"supply.cause.{c['address']}.amount", f"named cause: {c['family'][:40]}",
              f"{base}/amount", "base_units", "supply", "DET-15")
        t.add(f"supply.cause.{c['address']}.family", "named cause family", f"{base}/family",
              "literal", "supply", "DET-15")
    for k, u in (("backing_value", "value_scale_units"), ("value_scale", "count"),
                 ("backed_supply", "base_units"), ("perimeter", "literal")):
        t.add(f"tree.root.{k}", k.replace("_", " "), f"tree/root/{k}", u, "supply", "DET-15")
    if tree.get("off_mainnet_line"):
        om = "tree/off_mainnet_line"
        t.add("supply.off_mainnet.amount", "minted against off-mainnet facilitators",
              f"{om}/amount", "base_units", "supply", "DET-19")
        t.add("supply.off_mainnet.share", "off-mainnet share of supply_ruled",
              f"{om}/share_of_supply_ruled", "ratio", "supply", "DET-19", "supply_ruled")
        t.add("supply.off_mainnet.literal", "off-mainnet line", f"{om}/literal", "literal",
              "supply", "DET-19")

    # ---- the headline cell, the d = 0 panel (DET-38..44) -------------------------------
    cell = f"stress/cells/[id={HEADLINE}]"
    for k, u, d, own in (("m1/pre/ratio", "ratio", None, "DET-39"),
                         ("m1/post/ratio", "ratio", None, "DET-39"),
                         ("m1/pre/share_below_100", "ratio", None, "DET-39"),
                         ("m1/post/share_below_100", "ratio", None, "DET-39"),
                         ("m1/gap", "ratio", None, "DET-39"),
                         ("m2/bad_debt", "base_units", None, "DET-40"),
                         ("m2/pct_supply", "ratio", "supply_ruled", "DET-40"),
                         ("m3/forced_sell_volume", "base_units", None, "DET-41"),
                         ("m3/exit_depth", "base_units", None, "DET-41"),
                         ("m3/ratio", "ratio", "exit_depth", "DET-41")):
        t.add(f"headline.{k.replace('/', '.')}", f"headline {k.replace('/', ' ')}",
              f"{cell}/{k}", u, "stress (Member 1)", own, d)
    t.walk("headline.m4", "headline m4", f"{cell}/m4", "mechanism state",
           lambda fid: M4_OWNER.get(fid.split(".")[2], "DET-38"))
    head = next(c for c in stress["cells"] if c["id"] == HEADLINE)
    for line in head["counterfactual_lines"]:
        base = f"{cell}/counterfactual_lines/[id={line['id']}]"
        for k in ("value_primary", "value_counterfactual", "metric_affected"):
            t.add(f"headline.cf.{line['id']}.{k}", f"counterfactual {line['id']} {k}",
                  f"{base}/{k}", None, "stress (Member 1)", "DET-44")
    panel = [c for c in stress["cells"] if c["member"] == "M1" and c["id"].split("-")[2] == "d0"]
    for c in panel:
        base = f"stress/cells/[id={c['id']}]"
        for k, u, d, own in (("m1/post/ratio", "ratio", None, "DET-39"),
                             ("m2/bad_debt", "base_units", None, "DET-40"),
                             ("m3/ratio", "ratio", "exit_depth", "DET-41"),
                             ("m3/exit_depth", "base_units", None, "DET-41")):
            t.add(f"panel.{c['id']}.{k.replace('/', '.')}", f"{c['id']} {k.replace('/', ' ')}",
                  f"{base}/{k}", u, "stress (Member 1)", own, d)

    # ---- exit liquidity (DET-30 / 31 / 35 / 36 / 11 / 50 / 32) --------------------------
    ed = "stress/exit_depth"
    for r in stress["exit_depth"]["sensitivity_rows"]:
        t.add(f"exit.sensitivity.K{r['k']}.depth", f"K-subset {r['k']}% depth at s = 2%",
              f"{ed}/sensitivity_rows/[k={r['k']}]/depth_at_2pct", "base_units",
              "exit liquidity", "DET-30")
        t.add(f"exit.sensitivity.K{r['k']}.share_of_F", f"K-subset {r['k']}% share of F",
              f"{ed}/sensitivity_rows/[k={r['k']}]/share_of_F", "ratio", "exit liquidity",
              "DET-30", "frozen_set_tvl")
    for p in stress["exit_depth"]["depth_curve"]:
        for k, own in (("total", "DET-31"), ("pool_depth", "DET-31"),
                       ("gsm_contribution", "DET-35")):
            t.add(f"exit.curve.s{p['s']}.{k}", f"depth curve s = {p['s']} {k}",
                  f"{ed}/depth_curve/[s={p['s']}]/{k}", "base_units", "exit liquidity", own)
    for v in stress["exit_depth"]["gsm_venues"]:
        base = f"{ed}/gsm_venues/[gsm={v['gsm']}]"
        for k, u in (("fee_exit", "ratio"), ("balance", "base_units"), ("enters", "boolean")):
            t.add(f"exit.gsm.{v['gsm']}.{k}", f"GSM venue {k}", f"{base}/{k}", u,
                  "exit liquidity", "DET-35")
    t.add("exit.lp_flight_literal", "LP-flight assumption line", f"{ed}/lp_flight_literal",
          "literal", "exit liquidity", "DET-36")
    if stress["exit_depth"]["concentration"]:
        for k, u, d in (("largest_paired_asset", "address", None),
                        ("share_of_exit_depth", "ratio", "exit_depth"), ("label", "literal", None)):
            t.add(f"exit.concentration.{k}", f"concentration {k.replace('_', ' ')}",
                  f"{ed}/concentration/{k}", u, "exit liquidity", "DET-11", d)
    t.add("exit.member2_target", "Member-2 target", "stress/member2_target", "address",
          "stress (Member 2)", "DET-50")
    for addr in sorted(stress["exit_depth"]["base_virtual_price"]):
        t.add(f"exit.base_virtual_price.{addr}", "base pool virtual price (par numeraire)",
              f"{ed}/base_virtual_price/{addr}", "base_units", "exit liquidity", "DET-31")
    o = "bundle/offvenue_share"
    for k, u in (("dex_liquidity_total_discovered", "usd_whole"),
                 ("curve_mainnet_liquidity", "usd_whole"), ("x", "ratio"),
                 ("literal", "literal"), ("source", "literal"), ("date", "date")):
        t.add(f"exit.offvenue.{k}", f"off-venue {k.replace('_', ' ')}", f"{o}/{k}",
              u if bundle["offvenue_share"][k] is not None else "null", "exit liquidity",
              "DET-32", "dex_liquidity_total_discovered" if k == "x" else None)

    # ---- Member 2 and mechanism (DET-43 / 45 / 46 / 47 / 51 / 53) ----------------------
    curves = stress["assumptions"].get("m2_curves")
    if isinstance(curves, dict):
        for target in sorted(curves):
            for s in sorted(curves[target]):
                t.add(f"m2.curve.t{target}.s{s}", f"structural-insulation curve target {target} "
                      f"s = {s}", f"stress/assumptions/m2_curves/{target}/{s}", "base_units",
                      "stress (Member 2)", "DET-43")
    mech = stress["mechanism"]
    for k in ("effective_headroom", "naive_headroom", "burn_capacity", "ceiling_aggregate",
              "gate_reason", "sp_balance", "base_rate", "redemption_capacity"):
        if mech.get(k) is not None:
            t.add(f"mech.{k}", k.replace("_", " "), f"stress/mechanism/{k}", None,
                  "mechanism state", {"effective_headroom": "DET-45", "naive_headroom": "DET-45",
                                      "gate_reason": "DET-45", "burn_capacity": "DET-27",
                                      "ceiling_aggregate": "DET-26"}.get(k, "DET-51"))
    for g in sorted(mech.get("h2_routing", {})):
        t.add(f"mech.h2_routing.{g}", "H2 freezer routing", f"stress/mechanism/h2_routing/{g}",
              "literal", "mechanism state", "DET-46")
    for key in sorted(mech.get("reserve_params", {})):
        t.add(f"mech.reserve.{key}.liquidation_bonus", "reserve liquidation bonus",
              f"stress/mechanism/reserve_params/{key}/liquidation_bonus", "bps",
              "mechanism state", "DET-47")
    for i, r in enumerate(mirror.get("bias_table", [])):
        t.add(f"bias.{i}.direction", f"bias: {r['mechanism']}",
              f"mirror/bias_table/{i}/direction", "literal",
              "stress (Member 1)", "DET-53")

    # ---- assumption text rows (Step 6's keys, kept as additional rows) ---------------
    for k in sorted(stress["assumptions"]):
        if isinstance(stress["assumptions"][k], str):
            t.add(f"assumption.{k}", f"assumption: {k}", f"stress/assumptions/{k}", "literal",
                  "assumptions", "DET-57")

    # ---- nodes: sell-side bound (DET-52) ------------------------------------------------
    for n in bundle["nodes"]:
        if n.get("sell_side_capacity"):
            t.add(f"node.{n['address']}.sell_side", f"sell-side bound: {n['symbol']}",
                  f"bundle/nodes/[address={n['address']}]/sell_side_capacity/value",
                  "token_units", "stress (Member 1)", "DET-52")

    # ---- oracle table (DET-55 / 54) ------------------------------------------------------
    for r in bundle["oracle_rows"]:
        sel = (f"bundle/oracle_rows/[node_address={r['node_address']},"
               f"market_or_reserve_address={r['market_or_reserve_address']}]")
        rid = f"oracle.{r['node_address']}.{r['market_or_reserve_address']}"
        uc = r["update_condition"]
        t.add(f"{rid}.type", "update condition type", f"{sel}/update_condition/type", "literal",
              "oracle table", "DET-55")
        if uc["type"] == "ema_window":
            t.add(f"{rid}.ema_window_s", "EMA window", f"{sel}/update_condition/ema_window_s",
                  "seconds", "oracle table", "DET-54")
        else:
            t.add(f"{rid}.heartbeat_s", "heartbeat", f"{sel}/update_condition/heartbeat_s/value",
                  "seconds", "oracle table", "DET-55")
            t.add(f"{rid}.heartbeat_form", "heartbeat form",
                  f"{sel}/update_condition/heartbeat_s/form", "literal", "oracle table", "DET-55")
            if uc.get("deviation"):
                t.add(f"{rid}.deviation_bps", "deviation",
                      f"{sel}/update_condition/deviation/value_bps", "bps", "oracle table",
                      "DET-54")

    # ---- admin surface A1-A8 (DET-68) -----------------------------------------------------
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
        prov = r["provenance"]
        t.add(f"{rid}.A8", f"{r['power']} A8 provenance", f"{sel}/provenance/kind", "literal",
              "admin surface", "DET-68")
        if prov.get("function"):
            t.add(f"{rid}.A8.function", f"{r['power']} A8 function", f"{sel}/provenance/function",
                  "literal", "admin surface", "DET-68")

    # ---- DET-73's audit line -----------------------------------------------------------
    sm = bundle["static_metadata"]
    if isinstance(sm["audits"], list):
        for i in range(len(sm["audits"])):
            for k in ("firm", "date", "scope"):
                t.add(f"audit.{i}.{k}", f"audit {k}", f"bundle/static_metadata/audits/{i}/{k}",
                      "date" if k == "date" else "literal", "static metadata", "DET-73")
    else:
        t.add("audit.none", "audits", "bundle/static_metadata/audits", "literal",
              "static metadata", "DET-73")
    for k in ("platform", "max"):
        t.add(f"audit.bug_bounty.{k}", f"bug bounty {k}", f"bundle/static_metadata/bug_bounty/{k}",
              "literal", "static metadata", "DET-73")
    for k, u in (("last_material_change_audited", "literal"), ("staleness_date", "date"),
                 ("counterparties", "literal")):
        t.add(f"audit.{k}", k.replace("_", " "), f"bundle/static_metadata/{k}", u,
              "static metadata", "DET-73")
    return t.rows


def table_hash(doc: dict) -> str:
    payload = {k: doc[k] for k in ("token", "run_block", "rows", "assumptions")}
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
