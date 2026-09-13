"""B-5: GHO's 47 cells. A different mechanism, the same four metrics.

WHY THIS IS NOT crvUSD's CODE. crvUSD liquidates through LLAMMA bands against
one collateral per market; GHO borrows sit on three Aave instances, each
position holding a BASKET of reserves under a collateral-weighted liquidation
threshold that an eMode category can replace. And the two Members differ in
kind: crvUSD's Member 2 was zero by construction (DET-43), while GHO's is the
point of the token — a depeg of USDT hits the GSM's boxed supply and the
attributed USDT collateral, both real.

UNITS, once: Aave's base currency is USD at 8 dp, so `getAssetPrice`,
`total_debt_base` and `gho_debt_base` are all 8 dp and compare directly.
Collateral is in each reserve's own decimals and is divided by them. Metric
figures are published in GHO base units (1e18) at GHO's own par, so the 8-dp
base total is scaled by 1e10 — GHO's supply_ruled is 1e18-scaled and the
metrics must divide into it.
"""

from __future__ import annotations

from decimal import Decimal

from factory.aave import HF_LITERAL, TAIL_LITERAL, GhoPos, health

BASE_TO_WEI = 10 ** 10                # 8-dp USD -> 1e18 GHO at par
SHOCKS = (Decimal("-0.20"), Decimal("-0.35"), Decimal("-0.50"), Decimal("-0.70"))
LSTS = (Decimal("0"), Decimal("0.05"), Decimal("0.10"))
LPS = (Decimal("0"), Decimal("0.30"), Decimal("0.60"))
TARGETS = (Decimal("0.97"), Decimal("0.93"), Decimal("0.88"))
HEADLINE_M1 = "M1-s50-d0-lp0"
HEADLINE_M2 = "M2-t0.93-lp0"

M4_KEYS = ("gho_sourceable", "collateral_sellable", "gsm_mint_headroom",
           "binding_side", "facilitator_bucket_levels", "freezer_state",
           "exit_depth_cell", "lp_flight_share", "counterfactual_ref")
NA = "not applicable — {member}"

ORACLE_LITERAL = (
    "GHO carries no EMA_lag line: there is no LLAMMA and no per-market price "
    "EMA. Section 7's assumption for GHO is instant observation of the Aave "
    "oracle - Chainlink feeds and CAPO adapters read at `run_block` - and the "
    "per-feed staleness surface is the oracle table's (DET-55/DET-81), not a "
    "counterfactual line's (P-6.01 R13)."
)
FREEZER_LITERAL = (
    "freezer_effective: the automated freezer holds SWAP_FREEZER_ROLE and its "
    "lower band is at or above 0.88, so in a depeg cell the GSM freezes and "
    "its exit contribution leaves exit depth (memo 6.3 H2, same event). The "
    "boxed supply does NOT leave the forced-sell numerator - a holder whose "
    "backing is the shocked stable still exits; what it loses is the venue."
)


def cell_id(member: str, **kw) -> str:
    if member == "M1":
        return (f"M1-s{int(abs(kw['shock']) * 100)}-d{int(kw['lst'] * 100)}"
                f"-lp{int(kw['lp'] * 100)}")
    if member == "M2":
        return f"M2-t{kw['target']}-lp{int(kw['lp'] * 100)}"
    return "M2-compound" if member == "M2_COMPOUND" else "JOINT"


def factors(shock: Decimal, lst: Decimal, volatile: set[str], lst_nodes: set[str],
            assets: set[str], nodes: set[str]) -> dict[str, Decimal]:
    """DET-39's `f`: `(1 + shock)(1 − d)` on volatile nodes, `d` only where the
    LST flag is set; `1` on stable nodes in Member 1 (DET-48).

    R-B5.1: a TAIL reserve — one with no node at all — takes the cell's
    volatile factor with no LST discount. Collateral of unknown class in a
    collateral-crash scenario is shocked, which overstates bad debt wherever a
    tail reserve is in fact a stable; the direction is named in `assumptions`
    rather than claimed to be neutral.
    """
    out = {}
    for a in assets:
        if a not in nodes:                       # tail: shocked as volatile
            out[a] = Decimal(1) + shock
        elif a in volatile:
            d = lst if a in lst_nodes else Decimal(0)
            out[a] = (Decimal(1) + shock) * (Decimal(1) - d)
        else:
            out[a] = Decimal(1)
    return out


def crash_path(positions: list[GhoPos], params: dict, decimals: dict,
               factor: dict, emode_lt: dict, nodes: set[str],
               capacity: int) -> dict:
    """One Member-1 cell's liquidation pass.

    Eligibility is the WHOLE position's health factor (memo §11.1 attributes
    the RESULT, not the inputs); absorption is ascending by health factor,
    R12's named default read onto a token whose CR is Aave's HF; and a
    position's shortfall is attributed to GHO by its debt share.
    """
    rows = []
    for p in positions:
        total, _w, hf = health(p, params, decimals, factor, emode_lt, nodes)
        rows.append({"p": p, "value": total, "hf": hf})
    left = capacity
    bad, absorbed = 0, 0
    for row in sorted(rows, key=lambda r: r["hf"]):
        p, v = row["p"], row["value"]
        if row["hf"] >= 1:
            continue
        short = max(p.total_debt_base - v, 0)
        if left >= v:
            left -= v
            absorbed += 1
        bad += int(Decimal(short) * p.gho_share)
    gone = absorbed
    post_c = sum(r["value"] for r in rows if r["hf"] >= 1)
    post_d = sum(r["p"].total_debt_base for r in rows if r["hf"] >= 1)
    pre_c = sum(r["value"] for r in rows)
    pre_d = sum(r["p"].total_debt_base for r in rows)
    under = sum(r["p"].gho_debt_base for r in rows if r["hf"] < 1)
    allg = sum(r["p"].gho_debt_base for r in rows) or 1
    return {"bad_debt": bad * BASE_TO_WEI, "eligible": sum(1 for r in rows
                                                           if r["hf"] < 1),
            "absorbed": gone, "capacity_left": left,
            "pre_ratio": _ratio(pre_c, pre_d), "post_ratio": _ratio(post_c, post_d),
            "share_below_100": _ratio(under, allg),
            "eligible_debt": sum(r["p"].total_debt_base for r in rows
                                 if r["hf"] < 1) * BASE_TO_WEI}


def member2_numerator(target_asset: str, boxed: dict[str, int],
                      positions: list[GhoPos], params: dict, decimals: dict,
                      exposed: set[str]) -> tuple[int, int, int]:
    """DET-42's Member-2 numerator: `gsm_boxed_supply + attributed_slice`.

    The two are DISJOINT and that is worth stating: `boxed` is GSM INVENTORY,
    which never entered `attribute_nodes`, while the slice is borrower
    COLLATERAL attributed to GHO by §11.1. Nothing is counted twice.

    `exposed` is the set of reserves whose backing IS the shocked stable —
    the stable itself and anything passing through to it under §4.3, which is
    how `waEthUSDT` counts as USDT exposure.
    """
    boxed_supply = sum(v for u, v in boxed.items() if u == target_asset)
    slice_base = 0
    for p in positions:
        for asset, amount in p.collateral.items():
            if asset not in exposed:
                continue
            res = params.get((p.instance, asset))
            if res is None:
                continue
            val = int(Decimal(amount) * Decimal(res.price)
                      / Decimal(10 ** decimals.get(asset, 18)))
            slice_base += int(Decimal(val) * p.gho_share)
    slice_wei = slice_base * BASE_TO_WEI
    return boxed_supply + slice_wei, boxed_supply, slice_wei


def _ratio(n: int, d: int) -> Decimal:
    return Decimal(n) / Decimal(d) if d else Decimal(0)


# ------------------------------------------------------------- the reads ----


def read_state(rpc, b, rows, nodes, reads, _cr) -> dict:
    """Everything Aave publishes that the model needs, at the bundle's block.

    Per instance: its addresses provider, price oracle and data provider. Per
    (instance, reserve) with a node: the risk parameters and the price. Per
    position: `getUserEMode`. Per live eMode category: its collateral config,
    whose liquidation threshold replaces the per-reserve one.
    """
    from factory.aave import read_reserve_params
    from factory.rpc import Call

    rb = rpc.run_block
    insts = sorted({r["instance"].lower() for r in rows})
    oracle_of, provider_of = {}, {}
    for inst in insts:
        ap = rpc.read([Call(inst, "ADDRESSES_PROVIDER()", ("address",))])[0].one()
        o, p = rpc.read([Call(ap, "getPriceOracle()", ("address",)),
                         Call(ap, "getPoolDataProvider()", ("address",))])
        oracle_of[inst], provider_of[inst] = o.one().lower(), p.one().lower()
        reads[f"{inst}.ADDRESSES_PROVIDER()"] = _cr(inst, "ADDRESSES_PROVIDER()", rb)
        reads[f"{ap}.getPriceOracle()"] = _cr(ap, "getPriceOracle()", rb)
        reads[f"{ap}.getPoolDataProvider()"] = _cr(ap, "getPoolDataProvider()", rb)

    # R-B5.1: EVERY reserve a position holds, tail included — solvency is
    # Aave's fact and needs Aave's price and LT for all of it. `nodes` still
    # separates the two sets for ABSORPTION, which is ours.
    pairs = sorted({(r["instance"].lower(), a) for r in rows
                    for a in r["collateral"]})
    params = read_reserve_params(rpc, provider_of, pairs, oracle_of, reads)

    decimals = {}
    for _i, asset in pairs:
        if asset in decimals:
            continue
        d = rpc.read([Call(asset, "decimals()", ("uint8",))])[0]
        decimals[asset] = int(d.one()) if d.ok else 18
        reads[f"{asset}.decimals()"] = _cr(asset, "decimals()", rb)

    emodes = {}
    for inst in insts:
        users = sorted({r["borrower"].lower() for r in rows
                        if r["instance"].lower() == inst})
        got = rpc.read([Call(inst, "getUserEMode(address)", ("uint256",), (u,))
                        for u in users])
        for u, g in zip(users, got, strict=True):
            emodes[(inst, u)] = int(g.one()) if g.ok else 0
        if got:
            reads[f"{inst}.getUserEMode"] = got[0].provenance
    emode_lt = {}
    for inst in insts:
        for cat in sorted({c for (i, _u), c in emodes.items() if i == inst and c}):
            g = rpc.read([Call(inst, "getEModeCategoryCollateralConfig(uint8)",
                               ("(uint16,uint16,uint16)",), (cat,))])[0]
            if not g.ok:
                raise AaveConfigMissing(f"{inst}: eMode {cat} has no collateral config")
            emode_lt[(inst, cat)] = int(g.require()[0][1])
            reads[f"{inst}.getEModeCategoryCollateralConfig({cat})"] = g.provenance

    positions = [GhoPos(borrower=r["borrower"].lower(),
                        instance=r["instance"].lower(),
                        collateral=dict(r["collateral"]),
                        gho_debt_base=r["gho_debt_base"],
                        total_debt_base=r["total_debt_base"],
                        emode=emodes.get((r["instance"].lower(),
                                          r["borrower"].lower()), 0))
                 for r in rows]
    return {"positions": positions, "params": params, "decimals": decimals,
            "emode_lt": emode_lt, "oracle_of": oracle_of,
            "provider_of": provider_of, "pairs": pairs,
            "emode_categories": sorted({c for c in emodes.values() if c})}


class AaveConfigMissing(Exception):
    """An eMode category a position claims but the instance cannot describe."""


def det46_routing(b, rpc, reads, _cr) -> dict:
    """DET-46's per-GSM routing. `check_pass = automated ∧ lower >= 0.88`."""
    from factory.rpc import Call

    rb = rpc.run_block
    out = {}
    for g in b.gsms:
        holder = g.freezer_address
        automated = False
        if holder:
            probe = rpc.read([Call(holder, "checkUpkeep(bytes)",
                                   ("bool", "bytes"), (b"",))])[0]
            automated = probe.ok
            reads[f"{holder}.checkUpkeep"] = _cr(holder, "checkUpkeep(bytes)", rb)
        lo = Decimal(g.freeze_bound_lo or 0) / Decimal(10 ** 8)
        hi = Decimal(g.freeze_bound_hi or 0) / Decimal(10 ** 8)
        passed = bool(automated and lo >= Decimal("0.88"))
        out[g.address] = {"automated_freezer_present": automated,
                          "freeze_lower_bound": str(lo),
                          "freeze_upper_bound": str(hi),
                          "can_unfreeze": g.can_unfreeze,
                          "is_frozen": g.is_frozen, "is_seized": g.is_seized,
                          "check_pass": passed,
                          "routing": "freezer_effective" if passed
                          else "freezer_fails"}
    return out


# ------------------------------------------------------------- the cells ----


def build(b, cfg, rpc, raw_bytes, mech, states, numeraire, venues, reads, _cr,
          depth_after_flight, k90) -> tuple[list, list, dict, dict]:
    """GHO's 47 cells under R-B5.1. Returns `(cells, refs, notes, assumptions)`."""
    import json as _json

    from factory.schema import (
        Cell,
        CounterfactualLine,
        MetricOne,
        MetricReading,
        MetricThree,
        MetricTwo,
    )

    rows = _json.loads(raw_bytes.decode("utf-8"))
    nodes = {n.address: n for n in b.nodes}
    st = read_state(rpc, b, rows, set(nodes), reads, _cr)
    positions, params, decimals = st["positions"], st["params"], st["decimals"]
    emode_lt = st["emode_lt"]
    assets = {a for r in rows for a in r["collateral"]}
    volatile = {a for a, n in nodes.items() if n.node_class == "volatile"}
    lst_nodes = {a for a, n in nodes.items() if n.lst_discount_applies}
    routing = det46_routing(b, rpc, reads, _cr)
    effective = all(r["check_pass"] for r in routing.values())
    supply_ruled = b.supply.supply_ruled

    # absorption: NODE volatile reserves only (R-B5.1 keeps tail out)
    sell = {}
    for a in nodes:
        row = cfg.sell_side.get(a)
        if row is None:
            continue
        try:
            sell[a] = int(Decimal(row["value"]) * 10 ** decimals.get(a, 18))
        except Exception:
            continue

    boxed = {}
    for v in venues:
        boxed[v.underlying] = boxed.get(v.underlying, 0) + v.balance
    gsm_term = sum(v.balance for v in venues if v.enters)
    mint_headroom = sum(int(Decimal(g.available_underlying_exposure)
                            * Decimal(v.exchange_rate) * 10 ** 12)
                        for g in b.gsms for v in venues if v.gsm == g.address)
    buckets = {f.address: f.bucket_level for f in b.facilitators}

    target = "0xdac17f958d2ee523a2206206994597c13d831ec7"          # P-6.07's fill
    exposed = {target} | {v.boxed_asset for v in venues if v.underlying == target}

    cells, notes = [], {}

    def m4(member, extra):
        return {k: extra.get(k, {"value": 0, "reason": NA.format(member=member)})
                for k in M4_KEYS}

    def buy_side(shocked_bonus_bps: int, _lp: Decimal) -> int:
        """DET-47: pool buy-side depth, bounded by the MINIMUM liquidation bonus
        across the cell's shocked reserves — a liquidator will pay impact up to
        the bonus and no further.

        NO LP-FLIGHT TERM, and that is the entry's own shape: DET-47 defines
        `gho_sourceable` without one, because LP flight is §6.1.4's modifier on
        the EXIT side — what a fleeing holder can sell into — not on what a
        liquidator can source. Applying the haircut here drove the pool
        degenerate at lp60 (a 60% single-sided withdrawal takes more paired
        asset than the pool holds) and produced an unbracketed buy side; the
        reading that removed it is the entry's, not a workaround.
        """
        s = Decimal(shocked_bonus_bps - 10000) / Decimal(10000)
        if s <= 0:
            return 0
        return depth_after_flight(states, numeraire, k90, Decimal(0), s, buy=True)

    # ---- Member 1 -----------------------------------------------------------
    base_bad = None
    for shock in SHOCKS:
        for lst in LSTS:
            f = factors(shock, lst, volatile, lst_nodes, assets, set(nodes))
            cap = 0
            for a, units in sell.items():
                pr = next((params[(i, x)].price for (i, x) in params if x == a), 0)
                cap += int(Decimal(units) * Decimal(pr) * f.get(a, Decimal(1))
                           / Decimal(10 ** decimals.get(a, 18)))
            res = crash_path(positions, params, decimals, f, emode_lt,
                             set(nodes), cap)
            if base_bad is None:
                f0 = {a: Decimal(1) for a in assets}
                base_bad = crash_path(positions, params, decimals, f0, emode_lt,
                                      set(nodes), cap)["bad_debt"]
            bonus = min((params[k].liquidation_bonus for k in params
                         if k[1] in volatile), default=10000)
            sellable = cap * BASE_TO_WEI
            for lp in LPS:
                depth = depth_after_flight(states, numeraire, k90, lp,
                                           Decimal("0.02")) + gsm_term
                sourceable = buy_side(bonus, lp) + mint_headroom
                binding = ("collateral_sellable" if sellable <= sourceable
                           else "gho_sourceable")
                cid = cell_id("M1", shock=shock, lst=lst, lp=lp)
                cells.append(Cell(
                    id=cid, member="M1", shock=shock, lst=lst, lp=lp, target=None,
                    m1=MetricOne(
                        pre=MetricReading(ratio=res["pre_ratio"],
                                          share_below_100=res["share_below_100"]),
                        post=MetricReading(ratio=res["post_ratio"],
                                           share_below_100=res["share_below_100"]),
                        gap=res["post_ratio"] - res["pre_ratio"]),
                    m2=MetricTwo(bad_debt=res["bad_debt"],
                                 pct_supply=_ratio(res["bad_debt"], supply_ruled)),
                    m3=MetricThree(
                        ratio=(None if depth == 0 and res["bad_debt"] > 0
                               else _ratio(res["bad_debt"], depth)),
                        forced_sell_volume=res["bad_debt"], exit_depth=depth),
                    m4=m4("M1", {
                        "gho_sourceable": sourceable,
                        "collateral_sellable": sellable,
                        "gsm_mint_headroom": mint_headroom,
                        "binding_side": binding,
                        "facilitator_bucket_levels": buckets,
                        "freezer_state": {a: r["routing"] for a, r in routing.items()},
                        "exit_depth_cell": depth, "lp_flight_share": str(lp),
                        "counterfactual_ref": []}),
                    lineage=["liquidation_model", "depth_model", "price_read",
                             "collateral_read", "debt_read"]))

    # ---- Member 2, compound, joint ------------------------------------------
    num, boxed_part, slice_part = member2_numerator(
        target, boxed, positions, params, decimals, exposed)
    notes["m2_numerator"] = {"total": num, "gsm_boxed": boxed_part,
                             "attributed_slice": slice_part}

    def m2_cell(cid, member, tgt, lp):
        # freezer_effective: the GSM freezes in a depeg, so its venue leaves
        # exit depth — the boxed supply stays in the numerator (memo §6.3 H2).
        depth = depth_after_flight(states, numeraire, k90, lp, Decimal("0.02"))
        if not effective:
            depth += gsm_term
        return Cell(
            id=cid, member=member, shock=None, lst=None, lp=lp, target=tgt,
            m1=MetricOne(pre=MetricReading(ratio=Decimal(0), share_below_100=Decimal(0)),
                         post=MetricReading(ratio=Decimal(0), share_below_100=Decimal(0)),
                         gap=Decimal(0)),
            m2=MetricTwo(bad_debt=0, pct_supply=Decimal(0)),
            m3=MetricThree(ratio=(None if depth == 0 else _ratio(num, depth)),
                           forced_sell_volume=num, exit_depth=depth),
            m4=m4(member, {"exit_depth_cell": depth, "lp_flight_share": str(lp),
                           "freezer_state": {a: r["routing"]
                                             for a, r in routing.items()},
                           "counterfactual_ref": ["H2_freezer"]}),
            counterfactual_lines=[CounterfactualLine(
                id="H2_freezer", metric_affected="m3",
                assumption_text=("routing per DET-46: freezer_effective, so the "
                                 "GSM venue leaves exit depth. Counterfactual: "
                                 "the freezer does not act and the venue stays."),
                value_primary=depth,
                value_counterfactual=depth + (0 if not effective else gsm_term))],
            lineage=["depth_model", "supply_attribution", "gsm_supply"])

    for tgt in TARGETS:
        for lp in LPS:
            cells.append(m2_cell(cell_id("M2", target=tgt, lp=lp), "M2", tgt, lp))
    cells.append(m2_cell("M2-compound", "M2_COMPOUND", Decimal("0.93"), Decimal(0)))

    # joint: −50% × 0.93
    f = factors(Decimal("-0.50"), Decimal(0), volatile, lst_nodes, assets, set(nodes))
    cap = sum(int(Decimal(u) * Decimal(next((params[(i, x)].price for (i, x)
                                             in params if x == a), 0))
                  * f.get(a, Decimal(1)) / Decimal(10 ** decimals.get(a, 18)))
              for a, u in sell.items())
    jres = crash_path(positions, params, decimals, f, emode_lt, set(nodes), cap)
    jdepth = depth_after_flight(states, numeraire, k90, Decimal(0), Decimal("0.02"))
    jnum = jres["bad_debt"] + num
    bonus = min((params[k].liquidation_bonus for k in params if k[1] in volatile),
                default=10000)
    cells.append(Cell(
        id="JOINT", member="JOINT", shock=Decimal("-0.50"), lst=Decimal(0),
        lp=Decimal(0), target=Decimal("0.93"),
        m1=MetricOne(pre=MetricReading(ratio=jres["pre_ratio"],
                                       share_below_100=jres["share_below_100"]),
                     post=MetricReading(ratio=jres["post_ratio"],
                                        share_below_100=jres["share_below_100"]),
                     gap=jres["post_ratio"] - jres["pre_ratio"]),
        m2=MetricTwo(bad_debt=jres["bad_debt"],
                     pct_supply=_ratio(jres["bad_debt"], supply_ruled)),
        m3=MetricThree(ratio=(None if jdepth == 0 else _ratio(jnum, jdepth)),
                       forced_sell_volume=jnum, exit_depth=jdepth),
        m4=m4("JOINT", {"gho_sourceable": buy_side(bonus, Decimal(0)) + mint_headroom,
                        "collateral_sellable": cap * BASE_TO_WEI,
                        "gsm_mint_headroom": mint_headroom,
                        "binding_side": ("collateral_sellable"
                                         if cap * BASE_TO_WEI
                                         <= buy_side(bonus, Decimal(0)) + mint_headroom
                                         else "gho_sourceable"),
                        "facilitator_bucket_levels": buckets,
                        "freezer_state": {a: r["routing"] for a, r in routing.items()},
                        "exit_depth_cell": jdepth, "lp_flight_share": "0",
                        "counterfactual_ref": ["H2_freezer"]}),
        counterfactual_lines=[CounterfactualLine(
            id="H2_freezer", metric_affected="m3",
            assumption_text="routing per DET-46 (freezer_effective).",
            value_primary=jdepth, value_counterfactual=jdepth + gsm_term)],
        lineage=["liquidation_model", "depth_model", "supply_attribution",
                 "gsm_supply", "price_read", "collateral_read", "debt_read"]))

    notes["routing"] = routing
    # B-7: the values behind DET-81's reads, so the spot-check sheet can state
    # an expected LTV / liquidation threshold / bonus for each of the 37 pairs.
    notes["reserve_params"] = {
        f"{inst}:{asset}": {"ltv": res.ltv,
                            "liquidation_threshold": res.liquidation_threshold,
                            "liquidation_bonus": res.liquidation_bonus,
                            "price": res.price,
                            "decimals": decimals.get(asset, 18)}
        for (inst, asset), res in sorted(params.items())}
    notes["emode_params"] = {f"{inst}:{cat}": lt
                             for (inst, cat), lt in sorted(emode_lt.items())}
    notes["base_bad_debt"] = base_bad
    notes["hf_below_1_base"] = sum(
        1 for p in positions
        if health(p, params, decimals, {a: Decimal(1) for a in assets},
                  emode_lt, set(nodes))[2] < 1)
    refs = [{"node": a, "symbol": n.symbol,
             "literal": "reference point unavailable"}
            for a, n in nodes.items() if n.node_class == "volatile"]
    return cells, refs, notes, {
        "tail_reserves": TAIL_LITERAL, "health_factor": HF_LITERAL,
        "oracle_assumption": ORACLE_LITERAL, "freezer": FREEZER_LITERAL,
        "lp_flight": ("LP capital assumed sticky; haircut grid 0% / 30% / 60% - "
                      "assumed scenario modifier, not data-derived; LP flight "
                      "modeled as single-sided withdrawal of the paired asset.")}
