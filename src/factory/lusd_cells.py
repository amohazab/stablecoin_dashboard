"""B-6: LUSD's 23 cells. The third mechanism, the same four metrics.

WHY THIS IS NOT crvUSD's OR GHO's CODE. crvUSD converts collateral inside
LLAMMA bands; GHO liquidates whole Aave positions against a collateral-weighted
threshold. Liquity v1 does neither: a trove below MCR is **offset** against the
Stability Pool while the Pool has LUSD, and whatever the Pool cannot take is
**redistributed** — debt and collateral both — pro rata by collateral onto every
surviving trove. Nothing is sold. That is why LUSD is exempt from the sell-side
bound (DET-52): Stability Pool depositors receive the collateral, so no forced
sale happens on the absorption path at all.

TWO THINGS THE SHAPE FORCES, both named rather than assumed:

  * **`bad_debt` IS THE REDISTRIBUTED TROVES' OWN SHORTFALL** (DET-51). The
    entry writes `redistributed_positions_below_100 → bad_debt` as an identity,
    and "redistributed positions" are the positions that WERE redistributed —
    the liquidated troves whose debt was pushed onto the survivors — not the
    troves that received the redistribution. A liquidated trove at CR < 100%
    contributes less collateral than debt, and that gap is the loss the
    surviving book carries. Reading it as the receivers' post-CR instead would
    count the same shortfall again on every trove it landed on. The reading is
    the entry's; it is named here because both readings are grammatical.
  * **THE LP AXIS IS DEPOSITOR FLIGHT, NOT LIQUIDITY FLIGHT** (DET-51).
    `sp_effective_cell = sp_balance × (1 − LP_cell)`: the same 0/30/60 grid that
    haircuts pool LP elsewhere haircuts the Stability Pool here, because the
    Pool is what absorbs. The exit-depth side of the cell keeps its own §6.1.4
    haircut on the LUSD/3CRV pool; the two uses of the grid are separate and
    both are applied.

R-B6.1: at 25963959 no trove reaches MCR on any point of §6.2's grid — the
minimum ICR is 5.9683 against an MCR of 1.10 — so every Member-1 cell is zero
by the data, not by a shortcut. The code paths above are exercised by unit
fixtures instead, and `assumptions.engagement_thresholds` says at what shock
the mechanism would first engage.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

ONE_E18 = 10 ** 18
SHOCKS = (Decimal("-0.20"), Decimal("-0.35"), Decimal("-0.50"), Decimal("-0.70"))
LPS = (Decimal("0"), Decimal("0.30"), Decimal("0.60"))
TARGETS = (Decimal("0.97"), Decimal("0.93"), Decimal("0.88"))
HEADLINE_M1 = "M1-s50-d0-lp0"
HEADLINE_M2 = "M2-t0.93-lp0"

# DET-51's nine, in the entry's own order. `redemption_capacity` is the one
# that carries a reason beside its value, because H4's state gate has to say
# WHY a zero is a zero.
M4_KEYS = ("sp_effective_cell", "redistributed_debt",
           "redistributed_positions_below_100", "tcr_post",
           "recovery_mode_flag", "redemption_capacity", "exit_depth_cell",
           "lp_flight_share", "counterfactual_ref")

TROVE_MANAGER_READS = (
    ("baseRate()", "uint256"), ("lastFeeOperationTime()", "uint256"),
    ("BETA()", "uint256"), ("MINUTE_DECAY_FACTOR()", "uint256"),
    ("REDEMPTION_FEE_FLOOR()", "uint256"), ("MCR()", "uint256"),
    ("CCR()", "uint256"), ("getEntireSystemColl()", "uint256"),
    ("getEntireSystemDebt()", "uint256"), ("L_ETH()", "uint256"),
    ("L_LUSDDebt()", "uint256"))
PRICE_FEED_READS = (
    ("TIMEOUT()", "uint256"),
    ("MAX_PRICE_DEVIATION_FROM_PREVIOUS_ROUND()", "uint256"),
    ("MAX_PRICE_DIFFERENCE_BETWEEN_ORACLES()", "uint256"),
    ("status()", "uint8"), ("lastGoodPrice()", "uint256"))

REDEMPTION_FEE_CEILING = Decimal("0.02")     # H4's gate: baseRate + floor > 2%

ABSORPTION_LITERAL = (
    "absorption is the Stability Pool, not a sale: a trove below MCR is offset "
    "against the Pool (debt burned, collateral paid to depositors) and the "
    "remainder is REDISTRIBUTED pro rata by collateral onto surviving troves. "
    "LUSD is therefore exempt from the sell-side bound (DET-52) - no forced "
    "sale exists on the absorption path - and the LP axis haircuts the Pool "
    "(`sp_effective_cell = sp_balance x (1 - LP_cell)`, DET-51)."
)
BAD_DEBT_LITERAL = (
    "`bad_debt` = the REDISTRIBUTED troves' own shortfall: sum over liquidated "
    "troves with CR < 100% of (debt - collateral x price), per DET-51's "
    "`redistributed_positions_below_100 -> bad_debt` identity. The receiving "
    "troves' post-redistribution CR is NOT the definition; reading it that way "
    "would count one shortfall once per trove it landed on."
)
ORACLE_LITERAL = (
    "LUSD carries no EMA_lag line: Liquity v1 has no LLAMMA and no per-market "
    "price EMA. Section 7's assumption for LUSD is instant observation of the "
    "PriceFeed at `run_block`, and the price basis is the bundle's own "
    "`external_collateral_value / external_collateral_sum` - NOT a re-simulated "
    "`fetchPrice()`. `lastGoodPrice()` is read and disclosed beside it and lags "
    "by design, because only `fetchPrice()` rewrites it (P-6.01 R13)."
)
TELLOR_LITERAL = (
    "modeled outcome unchanged under primary; fallback engaged does not alter "
    "stock-only capacity"
)
INSULATION_LITERAL = "structurally insulated; exposed through exit venues only"
NA = "not applicable - {member}"


class LusdError(Exception):
    """A contract constant the model cannot proceed without."""


@dataclass(frozen=True)
class Trove:
    owner: str
    debt: int                                  # entire debt, gas comp included
    coll: int                                  # wei


def _ratio(n: int, d: int) -> Decimal:
    return Decimal(n) / Decimal(d) if d else Decimal(0)


def cell_id(member: str, **kw) -> str:
    if member == "M1":
        return (f"M1-s{int(abs(kw['shock']) * 100)}-d0"
                f"-lp{int(kw['lp'] * 100)}")
    if member == "M2":
        return f"M2-t{kw['target']}-lp{int(kw['lp'] * 100)}"
    return "M2-compound" if member == "M2_COMPOUND" else "JOINT"


# -------------------------------------------------------------- the model ----


def icr(t: Trove, price: int) -> Decimal:
    """Collateral value over debt, both at 1e18. Liquity's own ratio."""
    return _ratio(t.coll * price, t.debt * ONE_E18)


def redistribute(liquidated: list[Trove], survivors: list[Trove]
                 ) -> tuple[list[Trove], int, int]:
    """Liquity's rule: debt and collateral pro rata by COLLATERAL share.

    Conservation is exact by construction, not by rounding luck: the pro-rata
    shares are floored and the whole remainder is assigned to the largest
    survivor, so `sum(after) == sum(before) + sum(redistributed)` as integers.
    That identity is what DET-51's wiring check asserts.
    """
    d_total = sum(t.debt for t in liquidated)
    c_total = sum(t.coll for t in liquidated)
    if not survivors or (d_total == 0 and c_total == 0):
        return survivors, d_total, c_total
    basis = sum(t.coll for t in survivors)
    if basis == 0:
        raise LusdError("redistribution basis is zero: surviving troves hold "
                        "no collateral, so Liquity's pro-rata rule is undefined")
    out, d_given, c_given = [], 0, 0
    for t in survivors:
        d = d_total * t.coll // basis
        c = c_total * t.coll // basis
        d_given += d
        c_given += c
        out.append(Trove(owner=t.owner, debt=t.debt + d, coll=t.coll + c))
    # the floor remainder, to the largest survivor by collateral
    k = max(range(len(out)), key=lambda i: survivors[i].coll)
    out[k] = Trove(owner=out[k].owner,
                   debt=out[k].debt + (d_total - d_given),
                   coll=out[k].coll + (c_total - c_given))
    return out, d_total, c_total


def crash_path(troves: list[Trove], price: int, mcr: Decimal,
               sp_effective: int) -> dict:
    """One Member-1 cell: eligibility, Stability Pool offset, redistribution.

    Eligibility is ICR < MCR in EVERY regime (P-6.01 R12) - recovery mode is
    reported, never modeled, so the 1.50 branch of Liquity's own liquidation
    logic is deliberately not taken here and `recovery_mode_flag` carries the
    fact instead.
    """
    rows = sorted(troves, key=lambda t: icr(t, price))
    eligible = [t for t in rows if icr(t, price) < mcr]
    survivors = [t for t in rows if icr(t, price) >= mcr]

    left = sp_effective
    offset, redistributed = [], []
    for t in eligible:
        if left >= t.debt:                      # offset whole, or not at all
            left -= t.debt
            offset.append(t)
        else:
            redistributed.append(t)

    after, r_debt, r_coll = redistribute(redistributed, survivors)
    bad = sum(max(t.debt * ONE_E18 - t.coll * price, 0) // ONE_E18
              for t in redistributed if icr(t, price) < 1)
    pre_c = sum(t.coll for t in rows)
    pre_d = sum(t.debt for t in rows)
    post_c = sum(t.coll for t in after)
    post_d = sum(t.debt for t in after)
    under = sum(t.debt for t in rows if icr(t, price) < 1)
    return {
        "eligible": len(eligible), "offset": len(offset),
        "redistributed": len(redistributed),
        "redistributed_debt": r_debt, "redistributed_coll": r_coll,
        "redistributed_below_100": bad,
        "bad_debt": bad,
        "sp_left": left,
        "pre_ratio": _ratio(pre_c * price, pre_d * ONE_E18),
        "post_ratio": _ratio(post_c * price, post_d * ONE_E18),
        "tcr_post": _ratio(post_c * price, post_d * ONE_E18),
        "share_below_100": _ratio(under, pre_d),
        "conserved": (post_d == sum(t.debt for t in survivors) + r_debt
                      and post_c == sum(t.coll for t in survivors) + r_coll),
    }


def decayed_base_rate(base_rate: int, minute_decay_factor: int,
                      last_fee_op_time: int, block_timestamp: int) -> Decimal:
    """Liquity's `_calcDecayedBaseRate` at `run_block`.

    WHY THIS IS NOT A TIME PARAMETER (§7.1). The decay is not a horizon the
    model chooses - it is the contract's own state at the block everything else
    is read at. `baseRate()` returns the value as of `lastFeeOperationTime`, and
    the fee a redeemer would actually pay at `run_block` is the decayed one. Not
    applying it would report a stale rate as if it were current.
    """
    minutes = max(block_timestamp - last_fee_op_time, 0) // 60
    return (Decimal(base_rate) / ONE_E18) * \
        ((Decimal(minute_decay_factor) / ONE_E18) ** minutes)


def redemption_capacity(decayed: Decimal, floor: Decimal, beta: int,
                        total_supply: int) -> int:
    """H4: LUSD redeemable before `baseRate + 0.5% > 2%` (DET-51).

    `_updateBaseRateFromRedemption` moves the rate by
    `redeemedLUSDFraction / BETA`, so the headroom in rate terms times BETA is
    the redeemable fraction of supply. A rate already above the ceiling yields
    zero, not a negative capacity.
    """
    headroom = REDEMPTION_FEE_CEILING - floor - decayed
    if headroom <= 0:
        return 0
    return int(headroom * Decimal(beta) * Decimal(total_supply))


# --------------------------------------------------------------- the reads ---


def read_state(rpc, b, reads, _cr) -> dict:
    """Every contract constant the mechanism needs, at the bundle's block.

    `getTotalLUSDDeposits()` is NOT re-read: it is already a `Supply` field on
    the bundle at this same block (R-B4.5's reuse rule), and DET-51's capacity
    lineage is `{sp_balance_read}` - the bundle's read, whose provenance the
    bundle carries.
    """
    from factory.rpc import Call

    rb = rpc.run_block
    tm = b.markets[0].address
    pf = b.markets[0].reads["collateral_price"].source_contract
    out: dict[str, int] = {}
    for addr, sigs in ((tm, TROVE_MANAGER_READS), (pf, PRICE_FEED_READS)):
        res = rpc.read([Call(addr, s, (o,)) for s, o in sigs])
        for (s, _), r in zip(sigs, res, strict=True):
            if not r.ok:
                raise LusdError(f"{addr}: {s} reverted - the mechanism cannot "
                                "proceed without it")
            out[s] = int(r.one())
            reads[f"{addr}.{s}"] = _cr(addr, s, rb)
    out["_trove_manager"] = tm
    out["_price_feed"] = pf
    return out


# --------------------------------------------------------------- the cells ---


def build(b, cfg, rpc, raw_bytes, mech, states, numeraire, venues, reads, _cr,
          depth_after_flight, shocked_depth, k90) -> tuple[list, list, dict, dict]:
    """LUSD's 23 cells under R-B6.1. Returns `(cells, refs, notes, assumptions)`."""
    import json as _json

    from factory.schema import (
        Cell,
        CounterfactualLine,
        MetricOne,
        MetricReading,
        MetricThree,
        MetricTwo,
    )
    from factory.stress import m3_ratio

    rows = _json.loads(raw_bytes.decode("utf-8"))
    troves = [Trove(owner=r["owner"].lower(), debt=r["debt"], coll=r["coll"])
              for r in rows]
    st = read_state(rpc, b, reads, _cr)
    mcr = Decimal(st["MCR()"]) / ONE_E18
    ccr = Decimal(st["CCR()"]) / ONE_E18

    m = b.markets[0]
    # R12's price basis, stated: the bundle's own derived ETH price. NOT a
    # re-simulated `fetchPrice()` - the bundle already read it and a second
    # simulation could answer at a different round.
    base_price = int(Decimal(m.external_collateral_value) * ONE_E18
                     // Decimal(m.external_collateral_sum))
    supply_ruled = b.supply.supply_ruled
    sp_balance = b.supply.stability_pool_deposits

    decayed = decayed_base_rate(st["baseRate()"], st["MINUTE_DECAY_FACTOR()"],
                                st["lastFeeOperationTime()"],
                                int(b.header.block_timestamp))
    floor = Decimal(st["REDEMPTION_FEE_FLOOR()"]) / ONE_E18
    cap_full = redemption_capacity(decayed, floor, st["BETA()"],
                                   b.supply.total_supply)

    cells, notes = [], {}

    def m4(member, extra):
        return {k: extra.get(k, {"value": 0, "reason": NA.format(member=member)})
                for k in M4_KEYS}

    def redemption(tcr_cell: Decimal, member: str):
        """DET-51's H4 field: present on Member 2, compound and joint only, and
        gated on the cell's own TCR."""
        if member == "M1":
            return {"value": 0, "reason": "crash path excluded"}
        if tcr_cell < mcr:
            return {"value": 0, "reason": "TCR < MCR"}
        return {"value": cap_full,
                "reason": f"redeemable before baseRate + {floor} > "
                          f"{REDEMPTION_FEE_CEILING} at the decayed rate "
                          f"{decayed:.18f}"}

    def tellor_line():
        """R-23 / DET-44: verified constants and a scope statement, no computed
        value. `metric_affected = none` is the entry's own, and the line is
        rendered once per member (the R-24 exception)."""
        return CounterfactualLine(
            id="Tellor_fallback", metric_affected="none",
            assumption_text=(
                f"PriceFeed contract constants at block {b.header.run_block}: "
                f"TIMEOUT {st['TIMEOUT()']} s; "
                f"MAX_PRICE_DEVIATION_FROM_PREVIOUS_ROUND "
                f"{Decimal(st['MAX_PRICE_DEVIATION_FROM_PREVIOUS_ROUND()']) / ONE_E18:.0%}; "
                f"MAX_PRICE_DIFFERENCE_BETWEEN_ORACLES "
                f"{Decimal(st['MAX_PRICE_DIFFERENCE_BETWEEN_ORACLES()']) / ONE_E18:.0%}; "
                f"status() = {st['status()']} (0 = chainlinkWorking). "
                + TELLOR_LITERAL),
            value_primary=None, value_counterfactual=None,
            approximation_flag=False)

    # ---- Member 1: 4 shocks x 3 LP ------------------------------------------
    for shock in SHOCKS:
        price = int(Decimal(base_price) * (Decimal(1) + shock))
        for lp in LPS:
            sp_eff = int(Decimal(sp_balance) * (Decimal(1) - lp))
            res = crash_path(troves, price, mcr, sp_eff)
            if not res["conserved"]:
                raise LusdError("redistribution did not conserve debt and "
                                "collateral exactly")
            depth = depth_after_flight(states, numeraire, k90, lp,
                                       Decimal("0.02"))
            bad = res["bad_debt"]
            cid = cell_id("M1", shock=shock, lp=lp)
            cells.append(Cell(
                id=cid, member="M1", shock=shock, lst=Decimal(0), lp=lp,
                target=None,
                m1=MetricOne(
                    pre=MetricReading(ratio=res["pre_ratio"],
                                      share_below_100=res["share_below_100"]),
                    post=MetricReading(ratio=res["post_ratio"],
                                       share_below_100=res["share_below_100"]),
                    gap=res["post_ratio"] - res["pre_ratio"]),
                m2=MetricTwo(bad_debt=bad, pct_supply=_ratio(bad, supply_ruled)),
                m3=MetricThree(ratio=m3_ratio(bad, depth),
                               forced_sell_volume=bad, exit_depth=depth),
                m4=m4("M1", {
                    "sp_effective_cell": sp_eff,
                    "redistributed_debt": res["redistributed_debt"],
                    "redistributed_positions_below_100": res["redistributed_below_100"],
                    "tcr_post": str(res["tcr_post"]),
                    "recovery_mode_flag": res["tcr_post"] < ccr,
                    "redemption_capacity": redemption(res["tcr_post"], "M1"),
                    "exit_depth_cell": depth, "lp_flight_share": str(lp),
                    "counterfactual_ref": ["Tellor_fallback"]}),
                counterfactual_lines=[tellor_line()],
                lineage=["liquidation_model", "depth_model", "price_read",
                         "collateral_read", "debt_read"]))
            notes.setdefault("eligible", {})[cid] = res["eligible"]

    # ---- Member 2, compound: DET-43, LUSD is structurally insulated ----------
    # No `node_class = stable` node and `gsm_count = 0`, so no supply's backing
    # IS the shocked stable: the numerator is zero by construction and the ratio
    # is EXACTLY zero, not a rounded one.
    base = crash_path(troves, base_price, mcr, sp_balance)
    # DET-43's three FOUR-point curves, on DET-31's own s grid (B-7).
    from factory.stress import S_POINTS
    curves = {str(t): {str(s): shocked_depth(states, numeraire, k90, t,
                                             Decimal(0), s)
                       for s in S_POINTS}
              for t in TARGETS}

    def insulated(cid, member, target, lp):
        # R-B7.1: the paired stable AT ITS TARGET, LP haircut on top. At lp = 0
        # this is DET-43's recomputed curve for that target, which is what the
        # entry's replay asserts against.
        depth = shocked_depth(states, numeraire, k90, target, lp, Decimal("0.02"))
        return Cell(
            id=cid, member=member, shock=None, lst=None, lp=lp, target=target,
            m1=MetricOne(
                pre=MetricReading(ratio=base["pre_ratio"],
                                  share_below_100=base["share_below_100"]),
                post=MetricReading(ratio=base["post_ratio"],
                                   share_below_100=base["share_below_100"]),
                gap=Decimal(0)),
            m2=MetricTwo(bad_debt=0, pct_supply=Decimal(0)),
            m3=MetricThree(ratio=Decimal(0), forced_sell_volume=0,
                           exit_depth=depth),
            m4=m4(member, {
                "sp_effective_cell": sp_balance,
                "redistributed_debt": 0, "redistributed_positions_below_100": 0,
                "tcr_post": str(base["tcr_post"]),
                "recovery_mode_flag": base["tcr_post"] < ccr,
                "redemption_capacity": redemption(base["tcr_post"], member),
                "exit_depth_cell": depth, "lp_flight_share": str(lp),
                "counterfactual_ref": ["Tellor_fallback"]}),
            counterfactual_lines=[tellor_line()],
            lineage=["depth_model", "supply_attribution"])

    for target in TARGETS:
        for lp in LPS:
            cells.append(insulated(cell_id("M2", target=target, lp=lp), "M2",
                                   target, lp))
    cells.append(insulated("M2-compound", "M2_COMPOUND", Decimal("0.93"),
                           Decimal(0)))

    # ---- the joint cell: -50% x 0.93 ----------------------------------------
    # DET-42: `forced_sell = bad_debt_joint + m2_slice`. LUSD's Member-2 slice
    # is zero by DET-43, so the numerator IS the crash-path bad debt; the exit
    # depth is the SHOCKED curve, because the paired asset is depegged here too.
    shock, target = Decimal("-0.50"), Decimal("0.93")
    jprice = int(Decimal(base_price) * (Decimal(1) + shock))
    jres = crash_path(troves, jprice, mcr, sp_balance)
    jdepth = curves[str(target)]["0.02"]
    jbad = jres["bad_debt"]
    cells.append(Cell(
        id="JOINT", member="JOINT", shock=shock, lst=Decimal(0), lp=Decimal(0),
        target=target,
        m1=MetricOne(
            pre=MetricReading(ratio=jres["pre_ratio"],
                              share_below_100=jres["share_below_100"]),
            post=MetricReading(ratio=jres["post_ratio"],
                               share_below_100=jres["share_below_100"]),
            gap=jres["post_ratio"] - jres["pre_ratio"]),
        m2=MetricTwo(bad_debt=jbad, pct_supply=_ratio(jbad, supply_ruled)),
        m3=MetricThree(ratio=m3_ratio(jbad, jdepth), forced_sell_volume=jbad,
                       exit_depth=jdepth),
        m4=m4("JOINT", {
            "sp_effective_cell": sp_balance,
            "redistributed_debt": jres["redistributed_debt"],
            "redistributed_positions_below_100": jres["redistributed_below_100"],
            "tcr_post": str(jres["tcr_post"]),
            "recovery_mode_flag": jres["tcr_post"] < ccr,
            "redemption_capacity": redemption(jres["tcr_post"], "JOINT"),
            "exit_depth_cell": jdepth, "lp_flight_share": "0",
            "counterfactual_ref": ["Tellor_fallback"]}),
        counterfactual_lines=[tellor_line()],
        lineage=["liquidation_model", "depth_model", "supply_attribution",
                 "price_read", "collateral_read", "debt_read"]))

    # ---- notes, references, assumptions -------------------------------------
    lo = sorted(troves, key=lambda t: icr(t, base_price))
    notes["icr_tail"] = [(t.owner, str(icr(t, base_price)), t.debt)
                         for t in lo[:10]]
    notes["curves"] = curves
    notes["base"] = {"tcr": str(base["tcr_post"]), "eligible": base["eligible"],
                     "min_icr": str(icr(lo[0], base_price)),
                     "price": base_price, "troves": len(troves)}
    notes["h4"] = {"base_rate": st["baseRate()"], "decayed": str(decayed),
                   "capacity": cap_full, "beta": st["BETA()"],
                   "floor": str(floor),
                   "last_fee_operation_time": st["lastFeeOperationTime()"],
                   "block_timestamp": int(b.header.block_timestamp)}
    notes["constants"] = st
    notes["engagement"] = _thresholds(icr(lo[0], base_price), base["tcr_post"],
                                      mcr, ccr, len(troves))
    refs = [{"node": n.address, "symbol": n.symbol,
             "literal": "reference point unavailable"}
            for n in b.nodes if n.node_class == "volatile"]
    return cells, refs, notes, {
        "absorption": ABSORPTION_LITERAL,
        "bad_debt_definition": BAD_DEBT_LITERAL,
        "oracle_assumption": ORACLE_LITERAL,
        "engagement_thresholds": notes["engagement"],
        "structural_insulation": INSULATION_LITERAL,
        "m2_curves": curves,
    }


def _thresholds(min_icr: Decimal, tcr: Decimal, mcr: Decimal, ccr: Decimal,
                n: int) -> str:
    """R-B6.1's literal, derived from the measured distribution rather than
    written by hand: at what ETH shock the mechanism would first engage."""
    def pct(ratio_now: Decimal, bound: Decimal) -> str:
        return f"{(Decimal(1) - bound / ratio_now) * 100:.2f}%"
    return (f"no trove reaches MCR on the ruled grid; first liquidation at an "
            f"ETH shock of -{pct(min_icr, mcr)} (min ICR {min_icr:.4f} -> "
            f"{mcr}), recovery mode at -{pct(tcr, ccr)} (TCR {tcr:.4f} -> "
            f"{ccr}), TCR below MCR at -{pct(tcr, mcr)}; Liquity v1 is wound "
            f"down to {n} troves")
