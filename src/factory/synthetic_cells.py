"""Step 10, commit 6 (P-10.09): archetype #2's three stress rows (memo #2 §6).

Row 1, funding reversal: loss = (Crypto Basis + Equity and RWA Basis) × F × N/365,
F = −25%, N ∈ {30, 90, 180}; the reserve fund absorbs first (D3).
Row 2, venue loss: (a) the largest location total lost in full (F2); (b) the largest
exchange's hedge fails, its notional unhedged at −30% (D16); the reserve fund absorbs
first in both legs.
Row 3, redemptions: X = 25% of free float in 7 days, plus 25% of staked supply when
`cooldownDuration()` < 7 d; `capacity_redeem` = min(Σ /api/stablecoin-collateral,
`globalMaxRedeemPerBlock` × 50,400) (F1, E8); depeg-pressure ratio = max(0, X −
capacity_redeem) ÷ exit depth at s = 2%; DET-30's K rows attach here (D2).
Post-loss backing = backing − max(0, loss − reserve fund); ratio = ÷ `supply_ruled` (D3).
Every amount is whole USD at par (R-16); token amounts divide by 10**18.
"""

from __future__ import annotations

from decimal import Decimal

F = Decimal("-0.25")
NS = (30, 90, 180)
VENUE_SHOCK = Decimal("-0.30")
REDEMPTION_FRACTION = Decimal("0.25")
SEVEN_DAYS = 7 * 86_400
BLOCKS_7D = 7 * 86_400 // 12                       # 50,400 (E8)
WAD = Decimal(10) ** 18
UNWIND_LITERAL = "issuer unwinds the basis at day 0; loss bounded by execution cost, unquantified"


def _s(x) -> str:
    return str(x)


def build(b, exit_depth) -> dict:
    r = b.synthetic.reads
    cats = r["FR-U20"].value
    basis = Decimal(cats.get("Crypto Basis", 0)) + Decimal(cats.get("Equity and RWA Basis", 0))
    st = r["FR-U21"].value
    backing, rf = Decimal(st["backing_usd"]), Decimal(st["reserve_fund_usd"])
    supply = Decimal(b.supply.supply_ruled) / WAD

    def post(loss: Decimal) -> dict:
        pb = backing - max(Decimal(0), loss - rf)
        return {"loss": _s(loss), "post_loss_backing": _s(pb), "post_loss_ratio": _s(pb / supply)}

    cells = []
    for n in NS:
        loss = basis * -F * Decimal(n) / Decimal(365)
        cells.append({"id": f"S1-n{n}", "row": 1, "N": n, **post(loss),
                      "counterfactual_lines": [{"id": "cf.basis_unwind_day0",
                                                "value_counterfactual": None,
                                                "literal": UNWIND_LITERAL}]})
    route = r["FR-U36"].value
    loc = max(route["location_totals"].items(), key=lambda kv: (Decimal(kv[1]), kv[0]))
    ex = max(route["exchange_notional"].items(), key=lambda kv: (Decimal(kv[1]), kv[0]))
    cells.append({"id": "S2-a", "row": 2, "location": loc[0], "location_total": loc[1],
                  **post(Decimal(loc[1])), "counterfactual_lines": []})
    cells.append({"id": "S2-b", "row": 2, "exchange": ex[0], "notional": ex[1],
                  **post(Decimal(ex[1]) * -VENUE_SHOCK), "counterfactual_lines": []})

    total = b.supply.total_supply
    staked, cooling = r["FR-U06"].value, r["FR-U07"].value["balance"]
    escrow = r["FR-U08"].value["balance"]
    free = Decimal(total - staked - cooling - escrow) / WAD
    cooldown = int(r["FR-U04"].value)
    branch = cooldown < SEVEN_DAYS

    def x_of(with_staked: bool) -> Decimal:
        return REDEMPTION_FRACTION * free + (REDEMPTION_FRACTION * Decimal(staked) / WAD
                                             if with_staked else Decimal(0))

    sc = Decimal(r["FR-U35"].value["sum_usd"])
    rate = Decimal(r["FR-U09"].value["global_max_redeem_per_block"]) / WAD * BLOCKS_7D
    capacity = min(sc, rate)
    head = next(p for p in exit_depth.depth_curve if p.s == Decimal("0.02"))
    depth = Decimal(head.total) / WAD

    def ratio(x: Decimal, d: Decimal) -> Decimal | None:
        if d <= 0:
            return None
        return Decimal(0) if x <= capacity else (x - capacity) / d

    x, x_other = x_of(branch), x_of(not branch)
    k_rows = [{"k": row.k, "depth_at_2pct": _s(Decimal(row.depth_at_2pct) / WAD),
               "ratio": _s(ratio(x, Decimal(row.depth_at_2pct) / WAD))}
              for row in exit_depth.sensitivity_rows]
    cells.append({"id": "S3", "row": 3, "X": _s(x), "free_float": _s(free),
                  "staked": _s(Decimal(staked) / WAD), "cooldown_s": cooldown,
                  "branch": "free float + staked" if branch else "free float only",
                  "capacity_redeem": _s(capacity), "stablecoin_collateral": _s(sc),
                  "rate_cap_7d": _s(rate), "exit_depth_2pct": _s(depth),
                  "depeg_pressure_ratio": _s(ratio(x, depth)), "k_rows": k_rows,
                  "counterfactual_lines": [{"id": "cf.cooldown_branch",
                                            "branch": ("free float only" if branch
                                                       else "free float + staked"),
                                            "X": _s(x_other),
                                            "value_counterfactual": _s(ratio(x_other, depth))}]})
    s2 = sorted((c for c in cells if c["row"] == 2), key=lambda c: Decimal(c["post_loss_ratio"]))
    q = r["FR-U37"].value
    return {
        "cells": cells,
        "headlines": {"row1": "S1-n90", "row2": s2[0]["id"], "row2_beside": s2[1]["id"],
                      "row3": "S3"},
        "inputs": {"basis": _s(basis), "F": _s(F), "backing": _s(backing),
                   "reserve_fund": _s(rf), "supply_ruled": _s(supply),
                   "reference_point": {"quarter": q["quarter"], "value_pct": q["value_pct"],
                                       "negative_quarter_observed":
                                           q["negative_quarter_observed"]}},
        "assumptions": {
            "stock_only": "memo #1 §7.1; per-row direction in the bias table",
            "observation": "attested value (memo #2 §7)",
            "par_numeraire": "paired assets counted at 1.00 for depth",
            "funding_reversal_rate": "F = -25% annualised, N in {30, 90, 180}",
            "venue_loss_shock": "-30% on the largest exchange's unhedged notional",
            "redemption_fraction": "25% of free float in 7 days (+25% of staked when "
                                   "cooldownDuration() < 7 d)",
            "blocks_7d": "50,400 = 7 × 86,400 ÷ 12",
            "freeze_reference": "the frozen set at its freeze block"},
    }
