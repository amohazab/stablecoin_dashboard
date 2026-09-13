"""B-10: DET-57's assumptions block, per token (inventory D).

Each row is `{id, required, data_ref: [field_id, ...], rule_ref}`: `data_ref`
names flat-table rows, `rule_ref` a memo section; at least one is present.
Required IDs per DET-57's letter; `h5_slippage_bound` and `gsm_fee_exit` are
GHO's, `lst_discount_grid` crvUSD's and GHO's, and LUSD's `sell_side_bound` is
the exempt literal. Step 6's own assumption keys follow as additional rows,
each pointing at its `assumption.<key>` row (inventory D's subsumption list is
B-11's rendering choice, not a deletion here).
"""

from __future__ import annotations

REQUIRED_ALL = ("stock_only", "observation", "lp_sticky", "lp_grid", "sell_side_bound",
                "par_numeraire", "shock_grid_fixed", "member2_target", "freeze_reference")


class AssumptionsIncomplete(ValueError):
    """A required DET-57 ID with neither a data_ref nor a rule_ref."""


def _ids(rows: list[dict], prefix: str) -> list[str]:
    return [r["field_id"] for r in rows if r["field_id"].startswith(prefix)]


def build(token: str, rows: list[dict]) -> list[dict]:
    have = {r["field_id"] for r in rows}
    out: list[dict] = []

    def add(aid: str, data_ref: list[str] | None, rule_ref: str | None, required=True):
        refs = [f for f in (data_ref or []) if f in have]
        if data_ref and len(refs) != len(data_ref):
            missing = sorted(set(data_ref) - have)
            raise AssumptionsIncomplete(f"{token} {aid}: data_ref absent from the table {missing}")
        if required and not refs and not rule_ref:
            raise AssumptionsIncomplete(f"{token} {aid}: no data_ref and no rule_ref")
        out.append({"id": aid, "required": required, "data_ref": refs or None,
                    "rule_ref": rule_ref})

    add("stock_only", _ids(rows, "bias."), "memo §7.1")
    if token == "crvUSD":
        add("observation", [f for f in _ids(rows, "oracle.") if f.endswith(".ema_window_s")],
            "memo §7.2")
    else:
        add("observation", [f for f in _ids(rows, "oracle.") if f.endswith(".deviation_bps")],
            "memo §7.2")
    add("lp_sticky", ["exit.lp_flight_literal"], "memo §6.1.4")
    add("lp_grid", ["exit.lp_flight_literal"], "memo §6.1.4")
    if token == "LUSD":
        add("sell_side_bound", _ids(rows, "node.") + ["assumption.absorption"], "memo §6.3")
    else:
        add("sell_side_bound", _ids(rows, "node."), "memo §6.3")
    if token == "GHO":
        add("h5_slippage_bound", _ids(rows, "mech.reserve."), "memo §6.3 H5")
        add("gsm_fee_exit", [f for f in _ids(rows, "exit.gsm.") if f.endswith(".fee_exit")],
            "memo §5.10")
    add("par_numeraire", _ids(rows, "exit.base_virtual_price."), "memo §6.1.3")
    add("shock_grid_fixed", None, "memo §6.2.1")
    if token in ("crvUSD", "GHO"):
        add("lst_discount_grid", None, "memo §6.2.2")
    add("member2_target", ["exit.member2_target"], "memo §6.2.5")
    add("freeze_reference", ["header.freeze_date"], "memo §5.7")
    for f in sorted(_ids(rows, "assumption.")):
        out.append({"id": f.split(".", 1)[1], "required": False, "data_ref": [f],
                    "rule_ref": None})
    required = set(REQUIRED_ALL) | ({"h5_slippage_bound", "gsm_fee_exit"} if token == "GHO"
                                    else set()) | ({"lst_discount_grid"}
                                                   if token in ("crvUSD", "GHO") else set())
    got = {a["id"] for a in out if a["required"]}
    if got != required:
        raise AssumptionsIncomplete(f"{token}: required IDs {sorted(required ^ got)}")
    return out
