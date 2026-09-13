"""Step 6 B-1: the stress report's container, its two stops, and its routing.

`uv run python -m factory.stress <TOKEN> [--allow-stale-sheet]` folds the
LATEST promoted bundle in `out/bundles/<TOKEN>/`, its tree and its raw dump
into a `StressReport` at `out/stress/<TOKEN>/<run_block>.json` (P-6.01 R2).
One required positional token, `sys.argv[1]` - the P-4.02 shape, no argparse.

B-1 BUILDS THE CONTAINER AND THE ROUTING ONLY. `fold` is a stub returning the
present-and-empty report: no pool is read, no cell is computed, `len(CHECKS)`
does not move. From B-2 on this module DOES make pinned reads - unlike
`factory.tree`, which is a pure fold - at the bundle's own `run_block`, and
R-13 holds precisely because the block is the bundle's, not a fresh one.

TWO STOPS, both before anything is folded, both pure functions so they are
testable without a fixture repository:

  * `assert_raw_hash` - the raw dump's bytes must hash to the bundle's
    `raw_positions_hash`. This is P-3.05's integrity link finally exercised:
    the link was recorded so "a regenerated dump is verifiable byte-identical
    to what the run consumed", and until now nothing checked it. The preimage
    is the FILE BYTES AS WRITTEN, never a re-serialisation - each adapter
    hashes the exact string it then writes, so re-encoding here would test our
    own encoder rather than the link.
  * `assert_sheet_coherent` - the bundle's `sheet_hash` must equal the config
    mirror's (P-6.01 R3). `--allow-stale-sheet` is a DEV flag and nothing
    else: it stamps `stale_sheet` into the artifact and forces rehearsal
    routing regardless of checks, and Step 8's cron never passes it.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
from decimal import Decimal

from factory.config import load
from factory.depth import (
    A_PRECISION,
    BISECT_TOL,
    PoolState,
    pool_depth,
    withdraw_one_coin,
)
from factory.liquidation import (
    BAND_LINEAR_LITERAL,
    CAPACITY_LITERAL,
    UNDEFINED_RATIO_LITERAL,
    BandPrices,
    Position,
    ratio,
    run_cell,
    share_below_100,
)
from factory.liquidation import ONE as ONE_E18
from factory.llamma import (
    AMM_READS,
    BAND_READS,
    CONTROLLER_READS,
    Keeper,
    LlammaError,
    band_union,
    headroom,
    read_ticks,
    scale_alpha_beta,
)
from factory.provenance import ContractRead
from factory.rpc import Call
from factory.schema import (
    Band,
    Cell,
    CounterfactualLine,
    DepthConcentration,
    DepthPoint,
    ExitDepth,
    GroundTruth,
    GsmVenue,
    LlammaState,
    MarketState,
    Mechanism,
    Member2Candidate,
    MetricOne,
    MetricReading,
    MetricThree,
    MetricTwo,
    SensitivityRow,
    StressHeader,
    StressReport,
    finalise_stress,
    serialise_stress,
)

# Memo section 6.1.4's content, carried as a constant because it is text, not a
# computed figure. The RENDERED wording is DET-36's at Step 7 and may be
# re-ruled there; this is the field it renders from.
LP_FLIGHT_LITERAL = (
    "LP capital assumed sticky; haircut grid 0% / 30% / 60% - assumed scenario "
    "modifier, not data-derived; LP flight modeled as single-sided withdrawal "
    "of the paired asset."
)


# ------------------------------------------------------------- the stops ----


def assert_raw_hash(expected: str, raw_bytes: bytes) -> None:
    """P-3.05's integrity link. A mismatch means the dump on disk is not the
    one the run consumed, so nothing folded from it can be trusted."""
    got = hashlib.sha256(raw_bytes).hexdigest()
    if got != expected:
        from factory.run import AssemblyStop  # lazy: `run` pulls the adapters
        raise AssemblyStop(
            f"raw dump does not match the bundle's raw_positions_hash: "
            f"bundle {expected}, file {got}. The dump on disk is not the one "
            "this bundle was assembled from (P-3.05).")


def assert_sheet_coherent(bundle_sheet_hash: str, mirror_sheet_hash: str,
                          allow_stale: bool) -> bool:
    """R3. Returns True when the pairing is stale AND the dev flag permits it;
    False when the two agree. Raises otherwise."""
    if bundle_sheet_hash == mirror_sheet_hash:
        return False
    if not allow_stale:
        from factory.run import AssemblyStop
        raise AssemblyStop(
            f"sheet stamps disagree: bundle {bundle_sheet_hash}, mirror "
            f"{mirror_sheet_hash}. The promoted bundle predates the current "
            "sheet; re-run the adapter, or pass --allow-stale-sheet to fold a "
            "rehearsal artifact (P-6.01 R3).")
    return True


# ------------------------------------------------------------- the inputs ---


def load_inputs(repo: pathlib.Path, token: str,
                allow_stale_sheet: bool = False) -> dict:
    """The promoted bundle, ITS tree, its raw dump and its config, with both
    stops applied before anything is folded."""
    from factory.run import AssemblyStop
    from factory.tree import latest_bundle, latest_tree

    bundle = latest_bundle(repo, token)
    tree = latest_tree(repo, token)
    if tree is None:
        raise AssemblyStop(
            f"no tree in out/trees/{token}/ - run `factory.tree {token}` first; "
            "the stress module folds a bundle AND its tree.")
    # "its tree", asserted rather than assumed: the latest tree must be the one
    # folded from the latest bundle, or a promotion without a re-fold would
    # silently pair a new bundle with an old tree.
    if tree.source_bundle_hash != bundle.header.bundle_hash:
        raise AssemblyStop(
            f"the latest tree was folded from a different bundle: tree "
            f"{tree.source_bundle_hash[:8]}, bundle "
            f"{bundle.header.bundle_hash[:8]}. Re-fold before stressing.")

    cfg = load(repo / "config", token)
    raw_path = repo / "out/raw" / f"{bundle.header.run_block}.json"
    if not raw_path.exists():
        raise AssemblyStop(
            f"raw dump absent at {raw_path} - it is gitignored and regenerable "
            "from any archive node at run_block (P-3.05), but it is not "
            "optional: the stress module folds per-position rows.")
    raw_bytes = raw_path.read_bytes()
    assert_raw_hash(bundle.header.raw_positions_hash, raw_bytes)
    stale = assert_sheet_coherent(bundle.header.sheet_hash,
                                  cfg.sheet["sheet_hash"], allow_stale_sheet)
    fs = json.loads(cfg.frozen_set_path.read_text(encoding="utf-8"))
    return {"bundle": bundle, "tree": tree, "cfg": cfg, "raw": raw_bytes,
            "stale_sheet": stale, "member2_target": fs.get("member2_target")}


# --------------------------------------------------------------- the fold ---


# --------------------------------------------------------- exit depth ------
# B-2. Memo §6.1.1's four points verbatim: "the depth curve at s ∈ {0.5%, 1%,
# 2%, 5%}. The s = 2% value is the headline and the input to the stress model."
S_POINTS = (Decimal("0.005"), Decimal("0.01"), Decimal("0.02"), Decimal("0.05"))
S_DEN = 10 ** 6
K_KEYS = ("80", "90", "95")


def _cr(contract: str, fn: str, block: int, args=()) -> ContractRead:
    return ContractRead(source_contract=contract.lower(), function=fn,
                        args=[str(a) for a in args], block=block)


def read_pool_states(rpc, cfg, pools: list[str], numeraire: str,
                     reads: dict, base_vps: dict,
                     base_comp: dict, base_dec: dict) -> dict[str, PoolState]:
    """Every pool's math inputs at the bundle's own `run_block` (R-13). Shape
    is DISCOVERED, never configured: a pool answering `offpeg_fee_multiplier()`
    is NG; otherwise its signed factory root's `is_meta()` decides metapool vs
    plain, and a metapool's base pool comes from the same root's
    `get_base_pool()` — P-6.01-A1's route, since `LP.minter()` reverts."""
    from factory.run import AssemblyStop
    rb = rpc.run_block
    pins = {q["pool"].lower(): q for q in cfg.frozen_pool_index}
    out: dict[str, PoolState] = {}
    for addr in pools:
        coins, decs, bals = [], [], []
        for k in range(8):
            c = rpc.read([Call(addr, "coins(uint256)", ("address",), (k,))])[0]
            if not c.ok:
                break
            a = c.one().lower()
            coins.append(a)
            decs.append(int(rpc.read([Call(a, "decimals()", ("uint8",))])[0].one()))
            bals.append(int(rpc.read([Call(addr, "balances(uint256)", ("uint256",),
                                           (k,))])[0].one()))
            reads[f"{addr}.balances({k})"] = _cr(addr, "balances(uint256)", rb, (k,))
        if len(coins) != 2:
            raise AssemblyStop(
                f"{addr}: {len(coins)} coins — the depth solver models two-coin "
                "stableswap pools only (memo §5.1); a wider pool needs a ruling.")
        a_human, fee, admin_fee, vprice, tsupply = (
            int(rpc.read([Call(addr, s, ("uint256",))])[0].one())
            for s in ("A()", "fee()", "admin_fee()", "get_virtual_price()",
                      "totalSupply()"))
        for s in ("A()", "fee()", "admin_fee()", "get_virtual_price()", "totalSupply()"):
            reads[f"{addr}.{s}"] = _cr(addr, s, rb)
        offpeg_r = rpc.read([Call(addr, "offpeg_fee_multiplier()", ("uint256",))])[0]
        offpeg = int(offpeg_r.one()) if offpeg_r.ok else None
        if offpeg is not None:
            kind, rates = "ng", [int(x) for x in rpc.read(
                [Call(addr, "stored_rates()", ("uint256[]",))])[0].one()]
            reads[f"{addr}.stored_rates()"] = _cr(addr, "stored_rates()", rb)
            reads[f"{addr}.offpeg_fee_multiplier()"] = _cr(
                addr, "offpeg_fee_multiplier()", rb)
        else:
            pin = pins.get(addr)
            if pin is None:
                raise AssemblyStop(
                    f"{addr}: no [[frozen_pool_index]] row, so its factory root is "
                    "unknown and its shape cannot be discovered. Present config or "
                    "no run.")
            fac = cfg.root(pin["factory_root"]).address
            is_meta = rpc.read([Call(fac, "is_meta(address)", ("bool",), (addr,))])[0]
            reads[f"{addr}.is_meta"] = _cr(fac, "is_meta(address)", rb, (addr,))
            if is_meta.ok and is_meta.one():
                kind = "metapool"
                base = rpc.read([Call(fac, "get_base_pool(address)", ("address",),
                                      (addr,))])[0].one().lower()
                base_vp = int(rpc.read(
                    [Call(base, "get_virtual_price()", ("uint256",))])[0].one())
                reads[f"{addr}.get_base_pool"] = _cr(fac, "get_base_pool(address)",
                                                     rb, (addr,))
                reads[f"{base}.get_virtual_price()"] = _cr(
                    base, "get_virtual_price()", rb)
                base_vps[addr] = base_vp          # R-B2.6: recorded, not implicit
                rates = [10 ** (36 - decs[0]), base_vp]
                # C4 (R-B2.8): the base pool's composition at `run_block`, raw.
                # Only `get_virtual_price()` enters the depth math; these rows
                # exist so B-3 can pick LUSD's Member-2 target by constituent
                # share without a second discovery pass.
                comp: dict[str, int] = {}
                cdec: dict[str, int] = {}
                for m in range(8):
                    bc = rpc.read([Call(base, "coins(uint256)", ("address",), (m,))])[0]
                    if not bc.ok:
                        break
                    ca = bc.one().lower()
                    comp[ca] = int(rpc.read([Call(base, "balances(uint256)",
                                                  ("uint256",), (m,))])[0].one())
                    # B-3a: the constituents' scales are READ, never tabled. A
                    # 6-dp and an 18-dp balance cannot be compared for §4.3's
                    # pro-rata weights otherwise, and a decimals table keyed by
                    # address is the hardcoded-list shape the gates forbid.
                    cdec[ca] = int(rpc.read([Call(ca, "decimals()", ("uint8",))])[0].one())
                    reads[f"{base}.coins({m})"] = _cr(base, "coins(uint256)", rb, (m,))
                    reads[f"{base}.balances({m})"] = _cr(base, "balances(uint256)",
                                                         rb, (m,))
                    reads[f"{ca}.decimals()"] = _cr(ca, "decimals()", rb)
                base_comp[base] = comp
                base_dec[base] = cdec
                for s in ("A()", "fee()"):
                    rpc.read([Call(base, s, ("uint256",))])
                    reads[f"{base}.{s}"] = _cr(base, s, rb)
            else:
                kind, rates = "plain_v6", [10 ** (36 - d) for d in decs]
        if numeraire not in coins:
            raise AssemblyStop(f"{addr}: the analyzed token is not a coin of a "
                               "frozen pool — the frozen set is incoherent.")
        out[addr] = PoolState(address=addr, kind=kind, coins=tuple(coins),
                              decimals=tuple(decs), balances=tuple(bals),
                              amp=a_human * A_PRECISION, fee=fee, rates=tuple(rates),
                              offpeg_fee_multiplier=offpeg, virtual_price=vprice,
                              total_supply=tsupply)
    return out


def k_subsets(frozen: list) -> dict[str, list[str]]:
    """R5 (ruled 2026-09-12): `"95"` is F BY CONSTRUCTION — memo §5.5's intent,
    "K = 95% is always the full frozen set". `"80"` and `"90"` are DET-29(b)'s
    shortest prefix by `tvl_at_par` at `run_block` descending, ascending-address
    tie-break (PQ-3)."""
    ranked = sorted(frozen, key=lambda r: (-r.tvl_at_par, r.address))
    total = sum(r.tvl_at_par for r in ranked)
    out: dict[str, list[str]] = {"95": sorted(r.address for r in ranked)}
    for k in ("80", "90"):
        target = Decimal(total) * Decimal(k) / 100
        run, chosen = 0, []
        for r in ranked:
            chosen.append(r.address)
            run += r.tvl_at_par
            if Decimal(run) >= target:
                break
        out[k] = chosen
    return out


def gsm_venues(bundle, rpc, reads: dict) -> list[GsmVenue]:
    """DET-35 / §5.10. `fee_exit` is the BUY fee — the fee a GHO holder pays to
    leave into the boxed asset (F12); FR-G14's `getSellFee` is the MINT
    direction, and correcting the sheet's own text is B-3's signed edit. R-19's
    test is STRICT: the venue enters a curve point iff `fee_exit < s`.

    C2 (R-C2.3): the boxed asset is a stata wrapper, so the balance is put
    through `convertToAssets` and the par unit is the UNDERLYING's. The walk is
    re-read here rather than taken from the bundle's nodes: this fold runs
    against bundles written before C2, and a venue must not depend on whether
    the adapter has been re-run.
    """
    rb = rpc.run_block
    out: list[GsmVenue] = []
    for g in bundle.gsms:
        under = rpc.read([Call(g.underlying_asset, "asset()", ("address",))])[0].one().lower()
        conv = rpc.read([Call(g.underlying_asset, "convertToAssets(uint256)", ("uint256",),
                              (g.available_liquidity,))])[0]
        converted = int(conv.one())
        rate = (Decimal(converted) / Decimal(g.available_liquidity)
                if g.available_liquidity else Decimal(0))
        dec = int(rpc.read([Call(under, "decimals()", ("uint8",))])[0].one())
        reads[f"{g.address}.asset()"] = _cr(g.underlying_asset, "asset()", rb)
        reads[f"{g.address}.convertToAssets"] = _cr(
            g.underlying_asset, "convertToAssets(uint256)", rb, (g.available_liquidity,))
        probe = 10 ** 24
        raw = rpc.read([Call(g.fee_strategy, "getBuyFee(uint256)", ("uint256",),
                             (probe,))])[0]
        fee_exit = Decimal(int(raw.one())) / Decimal(probe) if raw.ok else Decimal(1)
        reads[f"{g.address}.getBuyFee"] = _cr(g.fee_strategy, "getBuyFee(uint256)",
                                              rb, (probe,))
        reads[f"{under}.decimals()"] = _cr(under, "decimals()", rb)
        closed = g.is_frozen or g.is_seized
        out.append(GsmVenue(
            gsm=g.address, boxed_asset=g.underlying_asset, underlying=under,
            fee_exit=fee_exit, exchange_rate=rate,
            # Par is the UNDERLYING's 1.00, not the wrapper's: the wrapper is a
            # §4.3 pass-through and its unit is worth `exchange_rate` of them.
            balance=converted * 10 ** (18 - dec),
            enters=not closed,
            reason=("frozen at base" if g.is_frozen else
                    "seized at base" if g.is_seized else
                    f"fee_exit {fee_exit} — enters each point s > fee_exit (R-19)")))
    return sorted(out, key=lambda v: v.gsm)


def record_ground_truth(rpc, states: dict[str, PoolState], depths: dict[str, int],
                        numeraire: str, reads: dict) -> list[GroundTruth]:
    """DET-31 / R-17's ground truth, RECORDED here because the harness is pure.
    At the pipeline's own depth we ask the CONTRACT for `get_dy` twice and take
    the finite difference; the implied marginal price must sit in
    `1 - s ± ε` with s = 2%, ε = 0.05%. A revert is Level 3 by the entry, so it
    stops the run rather than routing."""
    from factory.run import AssemblyStop
    rb = rpc.run_block
    out = []
    for addr, dx in sorted(depths.items()):
        p = states[addr]
        i = p.coins.index(numeraire)
        j = 1 - i
        ddx = max(BISECT_TOL, dx // 10 ** 6)
        got = rpc.read([Call(addr, "get_dy(int128,int128,uint256)", ("uint256",),
                             (i, j, dx)),
                        Call(addr, "get_dy(int128,int128,uint256)", ("uint256",),
                             (i, j, dx + ddx))])
        if not all(x.ok for x in got):
            raise AssemblyStop(
                f"DET-31: `get_dy` reverted or is unsupported on {addr} at block "
                f"{rb} — Level 3 by the entry, so nothing downstream computes.")
        dy0, dy1 = int(got[0].one()), int(got[1].one())
        # R-B2.6: the same rate-scaled conversion the bound uses, so the ground
        # truth and the solver are measured in one space. For the metapool this
        # multiplies the received side by `base_virtual_price / PRECISION`.
        implied = (Decimal(dy1 - dy0) * Decimal(p.rates[j])
                   / (Decimal(ddx) * Decimal(p.rates[i])))
        reads[f"{addr}.get_dy"] = _cr(addr, "get_dy(int128,int128,uint256)", rb,
                                      (i, j, dx))
        out.append(GroundTruth(pool=addr, dx=dx, ddx=ddx, onchain_dy_at_dx=dy0,
                               onchain_dy_at_dx_plus=dy1, implied_price=implied,
                               within_epsilon=abs(implied - Decimal("0.98"))
                               <= Decimal("0.0005")))
    return out


def gsm_enters(v: GsmVenue, s: Decimal) -> bool:
    """R-19, STRICT: a deterministic venue enters a curve point iff its exit
    fee is BELOW that point's slippage bound. Equality does not enter."""
    return v.enters and v.fee_exit < s


def _label_of(cfg, asset: str, flags: list, tree_labels: dict | None = None) -> str:
    """The asset's DET-11/§4 label, with R-B2.7's mapping applied once.

    R18 (P-7.01, applied at B-9): DET-11 owns a paired asset's label, and the
    tree is where it is RESOLVED - `linked` needs a last published tree - so a
    row the tree carries wins over the config row. Assets the tree does not
    carry (composite constituents, GSM underlyings) keep the config label."""
    row = cfg.paired.get(asset) or cfg.labels.get(asset)
    label = getattr(row, "label", None) or "unlabeled"
    if label == "composite_passthrough":
        label = "composite"
        msg = ("config literal composite_passthrough read as DET-11 composite "
               "(R4, P-5.01; R-B2.7)")
        if msg not in flags:
            flags.append(msg)
    if tree_labels and asset in tree_labels:
        label = tree_labels[asset]
    return label


def member2_candidates(bundle, frozen, per_pool_2: dict, venues: list,
                       cfg, base_comp: dict, base_dec: dict,
                       flags: list, tree_labels: dict | None = None) -> list[Member2Candidate]:
    """DET-50's candidate table at s = 2% (R-B3.1).

    Three bases, each keeping the asset's OWN label: a pool's paired asset
    directly; a `composite` paired asset expanded pro-rata to its constituents
    by `base_pool_composition`, normalised to 18 dp so a 6-dp and an 18-dp
    constituent compare (memo §4.3); and every ENTERING §5.10 GSM venue, at its
    UNDERLYING rather than the wrapper (R7 + §4.3, C2's walk).

    Selection is `select_member2`; this function only measures. The split keeps
    the artifact honest about `linked` assets, which are recorded here and
    excluded there.
    """
    out: dict[tuple[str, str], int] = {}
    for r in frozen:
        d = per_pool_2.get(r.address, 0)
        if not r.paired_assets or d == 0:
            continue
        each = d // len(r.paired_assets)
        for a in r.paired_assets:
            # A composite paired asset is the LP token; the composition is keyed
            # by the BASE POOL it wraps, so the expansion is keyed off the label
            # and there is exactly one base pool per metapool in F.
            base = (next(iter(base_comp), None)
                    if _is_composite(cfg, a, flags, tree_labels) else None)
            if base is None:
                out[(a, "paired_direct")] = out.get((a, "paired_direct"), 0) + each
                continue
            cons, dec = base_comp[base], base_dec.get(base, {})
            norm = {c: v * 10 ** (18 - dec[c]) for c, v in cons.items()}
            tot = sum(norm.values()) or 1
            for c, v in norm.items():
                k = (c, "composite_constituent")
                out[k] = out.get(k, 0) + each * v // tot
    for v in venues:
        if v.enters:
            k = (v.underlying, "gsm_venue")
            out[k] = out.get(k, 0) + v.balance
    total = sum(out.values()) or 1
    return sorted(
        (Member2Candidate(asset=a, depth_at_2pct=d, share=Decimal(d) / Decimal(total),
                          label=_label_of(cfg, a, flags, tree_labels), basis=b)
         for (a, b), d in out.items()),
        key=lambda c: (-c.depth_at_2pct, c.asset))


def _is_composite(cfg, asset: str, flags: list, tree_labels: dict | None = None) -> bool:
    return _label_of(cfg, asset, flags, tree_labels) == "composite"


def select_member2(cands: list[Member2Candidate]) -> str | None:
    """DET-50: the `recurses` candidate with the largest share; ties break on
    ascending address (named default, DET-29(b)'s precedent). `linked` and
    `recurses_truncated` are not eligible — §6.2.5 does not shock an analyzed
    CDP token, and a truncated label is not the `recurses` the entry names."""
    elig = [c for c in cands if c.label == "recurses"]
    if not elig:
        return None
    return sorted(elig, key=lambda c: (-c.depth_at_2pct, c.asset))[0].asset


def build_exit_depth(bundle, states: dict[str, PoolState], numeraire: str,
                     venues: list[GsmVenue], cfg, reads: dict, base_vps: dict,
                     base_comp: dict, base_dec: dict, flags: list,
                     rpc=None, tree_labels: dict | None = None) -> ExitDepth:
    """The curve on K-subset(0.90) (DET-31), the three sensitivity rows
    (DET-30), and the concentration line on the depth basis (F18)."""
    frozen = [r for r in bundle.pools if r.in_frozen_set]
    ks = k_subsets(frozen)
    total_f = sum(r.tvl_at_par for r in frozen)
    curve: list[DepthPoint] = []
    depth_at = {}
    for s in S_POINTS:
        s_num = int((Decimal(1) - s) * S_DEN)
        per_pool, gsm = {}, 0
        for addr in ks["90"]:
            p = states[addr]
            i = p.coins.index(numeraire)
            per_pool[addr] = pool_depth(p, i, 1 - i, s_num, S_DEN)
        for v in venues:
            if gsm_enters(v, s):
                gsm += v.balance
        pd = sum(per_pool.values())
        curve.append(DepthPoint(s=s, pool_depth=pd, per_pool=per_pool,
                                gsm_contribution=gsm, total=pd + gsm))
        depth_at[s] = (per_pool, pd, gsm)
    rows = []
    for k in K_KEYS:
        s2 = Decimal("0.02")
        s_num = int((Decimal(1) - s2) * S_DEN)
        d = sum(pool_depth(states[a], states[a].coins.index(numeraire),
                           1 - states[a].coins.index(numeraire), s_num, S_DEN)
                for a in ks[k])
        share = (Decimal(sum(r.tvl_at_par for r in frozen if r.address in ks[k]))
                 / Decimal(total_f)) if total_f else Decimal(0)
        rows.append(SensitivityRow(k=k, pools=sorted(ks[k]), depth_at_2pct=d,
                                   share_of_F=share))
    per_pool_2 = depth_at[Decimal("0.02")][0]
    cands = member2_candidates(bundle, frozen, per_pool_2, venues, cfg,
                               base_comp, base_dec, flags, tree_labels)
    by_asset: dict[str, int] = {}
    for r in frozen:
        d = per_pool_2.get(r.address, 0)
        if not r.paired_assets or d == 0:
            continue
        for a in r.paired_assets:                     # partitioned (P-3.26 F3)
            by_asset[a] = by_asset.get(a, 0) + d // len(r.paired_assets)
    conc = None
    if by_asset:
        total_d = sum(by_asset.values())
        top = sorted(by_asset.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        row = cfg.paired.get(top)
        # R-B2.7's mapping has ONE owner, `_label_of` — it is flagged there and
        # the flag is added once. B-3a found the duplicate the hard way: this
        # block carried its own copy of the mapping, so LUSD's artifact grew a
        # second identical `flags` entry the moment the candidate table started
        # resolving labels too.
        label = _label_of(cfg, top, flags, tree_labels)
        conc = DepthConcentration(
            largest_paired_asset=top,
            share_of_exit_depth=Decimal(by_asset[top]) / Decimal(total_d),
            label=label,
            disclosure_source=row.label_source if row else None)
    truth = (record_ground_truth(rpc, states, per_pool_2, numeraire, reads)
             if rpc is not None else [])
    return ExitDepth(ground_truth=truth, base_virtual_price=base_vps,
                     base_pool_composition=base_comp,
                     member2_candidates=cands, depth_curve=curve,
                     k_subsets=ks, sensitivity_rows=rows, gsm_venues=venues,
                     concentration=conc, lp_flight_literal=LP_FLIGHT_LITERAL,
                     reads=reads)


def build_mechanism(b, cfg, rpc, raw_bytes: bytes) -> Mechanism:
    """B-4a: crvUSD's H1 block. Present-and-empty for a token with no AMM.

    Every keeper value is REUSED FROM THE BUNDLE (R-B4.5) — debt, balance,
    ceiling, the decoded kill flags, α and β — so R-13 holds on the bundle's
    own block without re-reading a single one. What IS read here: the gate
    views (R10), the per-market state, the per-position ticks, the band UNION,
    and the five LP balances DET-27's printed quantities need.
    """
    rb = rpc.run_block
    reads: dict = {}
    if not b.stabilizer.operations:
        return Mechanism()

    ops = b.stabilizer.operations
    keepers = [Keeper(address=o.operation_address, debt=o.current_debt,
                      balance=o.balance, ceiling=o.debt_ceiling,
                      killed_provide=o.is_killed_provide,
                      killed_withdraw=o.is_killed_withdraw) for o in ops]
    reg = cfg.root("pegkeeper_regulator").address
    # R-B4.5: α and β are the BUNDLE's reads, reused. They are stored in human
    # units (0.5 / 0.25) and the port needs 1e18 fixed point, so the scaling
    # happens here and nowhere else.
    alpha, beta = scale_alpha_beta(b.stabilizer.alpha, b.stabilizer.beta)
    eff, naive, per = headroom(keepers, alpha, beta)
    if eff > naive:
        from factory.run import AssemblyStop
        raise AssemblyStop(f"DET-45: effective {eff} > naive {naive}")

    # R10: the gated views, read but never modeled, with the reason they read
    # as they do. The aggregator's own price is the second guard in
    # `provide_allowed`; at this block it is what shuts the view, not the flag.
    pa = rpc.read([Call(reg, "provide_allowed(address)", ("uint256",), (k.address,))
                   for k in keepers])
    wa = rpc.read([Call(reg, "withdraw_allowed(address)", ("uint256",), (k.address,))
                   for k in keepers])
    agg = rpc.read([Call(reg, "aggregator()", ("address",))])[0].one().lower()
    price = int(rpc.read([Call(agg, "price()", ("uint256",))])[0].one())
    for k in keepers:
        reads[f"{k.address}.provide_allowed"] = _cr(reg, "provide_allowed(address)",
                                                    rb, (k.address,))
        reads[f"{k.address}.withdraw_allowed"] = _cr(reg, "withdraw_allowed(address)",
                                                     rb, (k.address,))
    reads[f"{agg}.price()"] = _cr(agg, "price()", rb)
    reason = ("aggregator.price() < ONE" if price < 10 ** 18 else
              f"aggregator.price() = {price} >= ONE; the view's later guards decide")

    # DET-27's printed quantities, base state: each keeper's LP position in its
    # own pool, and the paired units that LP share represents.
    lp_share: dict[str, Decimal] = {}
    units: dict[str, int] = {}
    for o in ops:
        pool = o.paired_pool_address
        bal, sup = rpc.read([Call(pool, "balanceOf(address)", ("uint256",),
                                  (o.operation_address,)),
                             Call(pool, "totalSupply()", ("uint256",))])
        reads[f"{pool}.balanceOf({o.operation_address[:10]})"] = _cr(
            pool, "balanceOf(address)", rb, (o.operation_address,))
        b_, s_ = int(bal.one()), int(sup.one())
        lp_share[o.operation_address] = (Decimal(b_) / Decimal(s_) if s_ else Decimal(0))
        units[o.operation_address] = b_

    # --- the band state ------------------------------------------------------
    rows = json.loads(raw_bytes.decode("utf-8"))
    by_market: dict[str, list[str]] = {}
    for r in rows:
        by_market.setdefault(r["controller"].lower(), []).append(r["user"].lower())
    amm_of = {m.address: m.amm_address for m in b.markets}
    markets: dict[str, MarketState] = {}
    bands: dict[str, list[Band]] = {}
    ticks: dict[str, dict[str, tuple[int, int]]] = {}
    for ctrl, users in sorted(by_market.items()):
        amm = amm_of[ctrl]
        res = rpc.read([Call(amm, sig, (out,)) for sig, out in AMM_READS]
                       + [Call(ctrl, sig, (out,)) for sig, out in CONTROLLER_READS])
        for (sig, _), r in zip(AMM_READS + CONTROLLER_READS, res, strict=True):
            if not r.ok:
                raise LlammaError(f"{amm}/{ctrl}: {sig} reverted")
        v = [int(r.one()) for r in res]
        markets[amm] = MarketState(
            active_band=v[0], spot=v[1], oracle=v[2], base_price=v[3],
            a_coefficient=v[4], fee=v[5], admin_fee=v[6],
            loan_discount=v[7], liquidation_discount=v[8])
        for sig, _ in AMM_READS:
            reads[f"{amm}.{sig}"] = _cr(amm, sig, rb)
        for sig, _ in CONTROLLER_READS:
            reads[f"{ctrl}.{sig}"] = _cr(ctrl, sig, rb)
        ticks[amm] = read_ticks(rpc, amm, users, reads)
        # R-B4.10: `p_oracle_down(n)` IS `p_oracle_up(n + 1)` (the source's own
        # identity), so the union is extended by one band at the top of every
        # contiguous run — 40 bands across the nine markets. Reading the
        # boundary is what lets the model avoid porting LLAMMA's exp.
        core = band_union(ticks[amm])
        union = sorted(set(core) | {n + 1 for n in core})
        got = rpc.read([Call(amm, sig, (out,), (n,))
                        for n in union for sig, out in BAND_READS])
        if not all(r.ok for r in got):
            raise LlammaError(f"{amm}: a band read reverted over {len(union)} bands")
        bands[amm] = [Band(n=n, x=int(got[i * 3].one()), y=int(got[i * 3 + 1].one()),
                           p_oracle_up=int(got[i * 3 + 2].one()))
                      for i, n in enumerate(union)]
        for sig, _ in BAND_READS:
            reads[f"{amm}.{sig}"] = _cr(amm, sig, rb)

    return Mechanism(
        effective_headroom=eff, naive_headroom=naive,
        provide_allowed={k.address: int(r.one()) for k, r in zip(keepers, pa, strict=True)},
        withdraw_allowed={k.address: int(r.one()) for k, r in zip(keepers, wa, strict=True)},
        gate_reason=reason,
        burn_capacity=sum(o.current_debt for o in ops),
        ceiling_aggregate=b.stabilizer.ceiling_aggregate,
        pegkeeper_lp_share=lp_share, paired_units_held=units,
        llamma=LlammaState(markets=markets, bands=bands, ticks=ticks,
                           keeper_state=per),
        reads=reads)



# ------------------------------------------------------------- B-4b cells ---
SHOCKS = (Decimal("-0.20"), Decimal("-0.35"), Decimal("-0.50"), Decimal("-0.70"))
LSTS = (Decimal("0"), Decimal("0.05"), Decimal("0.10"))
LPS = (Decimal("0"), Decimal("0.30"), Decimal("0.60"))
TARGETS = (Decimal("0.97"), Decimal("0.93"), Decimal("0.88"))
HEADLINE = "M1-s50-d0-lp0"
M4_KEYS = ("effective", "naive", "is_killed", "alpha", "beta", "provide_allowed",
           "withdraw_allowed", "burn_capacity", "stabilizer_debt_post_cell",
           "ceiling_aggregate", "utilization_post_cell", "pegkeeper_lp_share",
           "paired_units_held", "pool_tilt_post_cell", "exit_depth_cell",
           "lp_flight_share", "oracle_spot_gap", "counterfactual_ref")
NA = "not applicable — {member}"


def m3_ratio(numerator: int, depth: int) -> Decimal | None:
    """R-B4.14. Undefined when the exit is exhausted and flow remains."""
    if depth == 0:
        return Decimal(0) if numerator == 0 else None
    return ratio(numerator, depth)


def _cell_id(member: str, **kw) -> str:
    if member == "M1":
        s = int(abs(kw["shock"]) * 100)
        return f"M1-s{s}-d{int(kw['lst'] * 100)}-lp{int(kw['lp'] * 100)}"
    if member == "M2":
        return f"M2-t{kw['target']}-lp{int(kw['lp'] * 100)}"
    return "M2-compound" if member == "M2_COMPOUND" else "JOINT"


def depth_after_flight(states: dict, numeraire: str, k90: list[str],
                       lp: Decimal, s: Decimal = Decimal("0.02"),
                       buy: bool = False) -> int:
    """B-5's caller: the same withdrawal, at an arbitrary bound and direction.

    `buy=True` swaps the indices — selling the PAIRED asset into the numeraire
    — which is DET-47's `pool_buy_side_depth`, the side a liquidator sources
    GHO from. The bound there is the minimum liquidation bonus, not 2%.
    """
    s_num = int((Decimal(1) - s) * S_DEN)
    total = 0
    for addr in k90:
        p = states[addr]
        i = p.coins.index(numeraire)
        j = 1 - i
        if lp > 0:
            amount = int(Decimal(p.total_supply) * lp)
            _dy, p = withdraw_one_coin(p, amount, j)
        total += (pool_depth(p, j, i, s_num, S_DEN) if buy
                  else pool_depth(p, i, j, s_num, S_DEN))
    return total


def _depth_after_flight(states: dict, numeraire: str, k90: list[str],
                        lp: Decimal) -> tuple[int, dict]:
    """DET-41's `exit_depth_cell`: depth(2%) on K-subset(0.90) after the cell's
    LP-flight haircut is withdrawn single-sided in the PAIRED asset (§6.1.4).

    At lp = 0 no withdrawal happens and the figure is DET-31's `depth(0.02)`
    byte-for-byte — the identity the wiring check asserts first.
    """
    s_num = int((Decimal(1) - Decimal("0.02")) * S_DEN)
    total, per = 0, {}
    for addr in k90:
        p = states[addr]
        i = p.coins.index(numeraire)
        j = 1 - i
        if lp > 0:
            amount = int(Decimal(p.total_supply) * lp)
            _dy, p = withdraw_one_coin(p, amount, j)       # the paired side
        d = pool_depth(p, i, j, s_num, S_DEN)
        per[addr] = d
        total += d
    return total, per


def _shocked_depth(states: dict, numeraire: str, k90: list[str],
                   target: Decimal, s: Decimal = Decimal("0.02")) -> int:
    """DET-43's Member-2 curve: depth at `s` recomputed in par terms against
    the SHOCKED paired asset. R-B2.6 evaluates the bound in rate-scaled space,
    so a paired asset worth `target` is its rate scaled by `target` — one
    change, in the one place par enters.

    B-7: `s` defaults to 2% because that is the point the cells consume, but
    the entry wants the whole four-point curve per target, so the bound is a
    parameter rather than a constant.
    """
    return _shocked_depth_after_flight(states, numeraire, k90, target,
                                       Decimal(0), s)


def _shocked_depth_after_flight(states: dict, numeraire: str, k90: list[str],
                                target: Decimal, lp: Decimal,
                                s: Decimal = Decimal("0.02")) -> int:
    """R-B7.1: a Member-2 cell's exit depth — the paired stable AT ITS TARGET,
    with the cell's LP-flight haircut applied on top (DET-41).

    ORDER, and why. The withdrawal happens first at the pool's true rates: LP
    flight is a physical removal of the paired asset, not a repricing, and a
    depositor leaving does not leave at the depegged rate. The scenario's price
    then applies to what remains. Reversing the two would haircut a pool that
    had already been marked down and understate both.

    At `lp = 0` this IS DET-43's recomputed curve, which is why the entry's
    replay is against the LP-0 cells.
    """
    s_num = int((Decimal(1) - s) * S_DEN)
    total = 0
    for addr in k90:
        p = states[addr]
        i = p.coins.index(numeraire)
        j = 1 - i
        if lp > 0:
            amount = int(Decimal(p.total_supply) * lp)
            _dy, p = withdraw_one_coin(p, amount, j)
        rates = list(p.rates)
        rates[j] = int(Decimal(rates[j]) * target)
        total += pool_depth(p.__class__(**{**p.__dict__, "rates": tuple(rates)}),
                            i, j, s_num, S_DEN)
    return total


def build_cells(b, report_bits: dict) -> tuple[list, list, dict]:
    """crvUSD's 47 cells (R-B4.9..R-B4.13). `(cells, reference_points, notes)`.

    The grid is memo §6.2.6's, the factors DET-39's, the absorption
    R-B4.11's — `effective` is NOT in it, `band depth` is NOT in it. Every
    per-cell aggregate lands here; no per-position row reaches the artifact.
    """
    states = report_bits["states"]
    numeraire = report_bits["numeraire"]
    k90 = report_bits["k90"]
    positions = report_bits["positions"]
    oracle = report_bits["oracle"]              # market -> price_oracle()
    spot = report_bits["spot"]                  # market -> get_p()
    discount = report_bits["liquidation_discount"]
    sell_side = report_bits["sell_side"]        # market -> units of the node
    lst_nodes = report_bits["lst_nodes"]        # markets whose node takes `d`
    mech = report_bits["mechanism"]
    ema = report_bits["ema_window_s"]
    supply_ruled = b.supply.supply_ruled
    prices = report_bits["band_prices"]
    bandxy = report_bits["band_xy"]

    base_value = sum(p.collateral * oracle[p.market] // ONE_E18 for p in positions)
    base_debt = sum(p.debt for p in positions)
    cells, notes = [], {}

    def m4_for(member: str, lp: Decimal, extra: dict) -> dict:
        """R-B3.10: every cell carries every key; a key not applicable to the
        cell's member carries 0 and a `reason` naming the member."""
        out = {}
        for key in M4_KEYS:
            if key in extra:
                out[key] = extra[key]
            else:
                out[key] = {"value": 0, "reason": NA.format(member=member)}
        return out

    def counterfactuals(member: str, cell_id: str, m2_primary: int,
                        erosion: int = 0) -> list:
        lines = []
        if member in ("M1", "JOINT"):
            lines.append(CounterfactualLine(
                id="H1_kill", metric_affected="m2",
                assumption_text=("all PegKeepers killed: zero contribution. The "
                                 "primary already excludes `effective` from "
                                 "absorption (P-6.08 R-B4.11), so the two agree "
                                 "— the crash path does not depend on the "
                                 "keepers, which is the finding, not a defect."),
                value_primary=m2_primary, value_counterfactual=m2_primary))
            # R-B4.18: the line carries NUMBERS. Primary is 0 — under §7.2's
            # instant observation the oracle never lags, so nothing erodes.
            # The counterfactual is the UPPER BOUND: every unit of collateral
            # that crossed a band, valued at that band's price, eroded by the
            # full shock, as if the oracle had stood still for the whole move.
            lines.append(CounterfactualLine(
                id="EMA_lag", metric_affected="m1.post",
                assumption_text=("bounded approximation — not full EMA "
                                 f"band-crossing dynamics; window {ema} s "
                                 "(the bundle's transitive max, P-3.31: no "
                                 "MA_EXP_TIME getter exists)"),
                value_primary=0, value_counterfactual=erosion,
                approximation_flag=True))
        if member in ("M2", "M2_COMPOUND", "JOINT"):
            lines.append(CounterfactualLine(
                id="H1_v1_contagion", metric_affected="m2",
                assumption_text=("primary: V2 gating effective, no new mint, LP "
                                 "share stuck in the depegging asset. "
                                 "Counterfactual: V1 contagion mint sized by "
                                 "headroom (memo §6.3 H1 depeg path).")))
        return lines

    # --- Member 1: 4 x 3 x 3 --------------------------------------------------
    for shock in SHOCKS:
        for lst in LSTS:
            f = {m: (Decimal(1) + shock) * (Decimal(1) - (lst if m in lst_nodes
                                                          else Decimal(0)))
                 for m in oracle}
            shocked = {m: int(Decimal(oracle[m]) * f[m]) for m in oracle}
            cap = {m: int(Decimal(sell_side.get(m, 0)) * Decimal(shocked[m])
                          / Decimal(ONE_E18)) for m in oracle}
            res = run_cell(positions, prices, shocked, discount, cap, bandxy)
            pre_v = sum(p.collateral * shocked[p.market] // ONE_E18
                        for p in positions)
            for lp in LPS:
                depth, _per = _depth_after_flight(states, numeraire, k90, lp)
                bad = res["bad_debt"]
                cid = _cell_id("M1", shock=shock, lst=lst, lp=lp)
                m4 = m4_for("M1", lp, {
                    "effective": mech.effective_headroom,
                    "naive": mech.naive_headroom,
                    "is_killed": mech.llamma.keeper_state if mech.llamma else {},
                    "alpha": str(b.stabilizer.alpha), "beta": str(b.stabilizer.beta),
                    "provide_allowed": mech.provide_allowed,
                    "withdraw_allowed": mech.withdraw_allowed,
                    "burn_capacity": mech.burn_capacity,
                    "ceiling_aggregate": mech.ceiling_aggregate,
                    "stabilizer_debt_post_cell": mech.burn_capacity,
                    "utilization_post_cell": str(ratio(mech.burn_capacity,
                                                       mech.ceiling_aggregate)),
                    "pegkeeper_lp_share": {a: str(v) for a, v
                                           in mech.pegkeeper_lp_share.items()},
                    "paired_units_held": mech.paired_units_held,
                    "exit_depth_cell": depth,
                    "lp_flight_share": str(lp),
                    "oracle_spot_gap": {m: str(ratio(spot[m] - oracle[m], oracle[m]))
                                        for m in oracle},
                    "counterfactual_ref": ["H1_kill", "EMA_lag"]})
                erosion = res["converted"] * int(abs(shock) * 10 ** 6) // 10 ** 6
                if cid in (HEADLINE, "M1-s70-d0-lp0"):
                    notes.setdefault("ema_pairs", {})[cid] = {
                        "m1_post_primary": str(ratio(res["post_value"],
                                                     res["post_debt"])),
                        "m1_post_counterfactual": str(
                            ratio(max(res["post_value"] - erosion, 0),
                                  res["post_debt"])),
                        "erosion": erosion}
                cells.append(Cell(
                    id=cid, member="M1", shock=shock, lst=lst, lp=lp, target=None,
                    m1=MetricOne(
                        pre=MetricReading(ratio=ratio(pre_v, base_debt),
                                          share_below_100=share_below_100(res["rows"])),
                        post=MetricReading(ratio=ratio(res["post_value"],
                                                       res["post_debt"]),
                                           share_below_100=share_below_100(
                                               [r for r in res["rows"]])),
                        gap=ratio(res["post_value"], res["post_debt"])
                        - ratio(pre_v, base_debt)),
                    m2=MetricTwo(bad_debt=bad, pct_supply=ratio(bad, supply_ruled)),
                    m3=MetricThree(ratio=m3_ratio(bad, depth),
                                   forced_sell_volume=bad, exit_depth=depth),
                    m4=m4,
                    counterfactual_lines=counterfactuals("M1", cid, bad,
                                                         erosion),
                    lineage=["liquidation_model", "depth_model", "price_read",
                             "collateral_read", "debt_read"]))
                notes.setdefault("eligible", {})[cid] = (res["eligible"],
                                                         res["eligible_debt"])

    # --- Member 2 + compound + joint: DET-43, crvUSD is structurally insulated -
    # DET-43 wants three FOUR-point curves — twelve values — not three scalars.
    # The s grid is DET-31's own `S_POINTS`, so the two curves are comparable
    # point for point; the cells still consume the s = 2% entry.
    curves: dict[str, dict[str, int]] = {
        str(target): {str(s): _shocked_depth(states, numeraire, k90, target, s)
                      for s in S_POINTS}
        for target in TARGETS}
    # R-B7.1: a Member-2 cell's venue set is priced with the paired stable AT
    # ITS TARGET - the cell's own scenario - not at par. Until B-7 these cells
    # carried the UNSHOCKED depth, identical across all three targets, while
    # the JOINT cell used the recomputed curve for the same target: a defect
    # against DET-43's letter, carried from B-4b and caught by the widened
    # replay. `m3.ratio` stays exactly 0 either way - the numerator is 0 by
    # construction (DET-43) - so only the depth each cell reports moves.
    for target in TARGETS:
        for lp in LPS:
            depth = _shocked_depth_after_flight(states, numeraire, k90, target, lp)
            cid = _cell_id("M2", target=target, lp=lp)
            cells.append(_insulated_cell(cid, "M2", target, lp, depth, base_value,
                                         base_debt, supply_ruled, m4_for, ema,
                                         counterfactuals))
    cells.append(_insulated_cell("M2-compound", "M2_COMPOUND", Decimal("0.93"),
                                 Decimal(0),
                                 _shocked_depth_after_flight(
                                     states, numeraire, k90, Decimal("0.93"),
                                     Decimal(0)),
                                 base_value, base_debt, supply_ruled, m4_for, ema,
                                 counterfactuals))
    # --- the joint cell: -50% x 0.93, LST 0, LP 0 (memo §6.2.6) --------------
    # DET-42: `forced_sell = bad_debt_joint + m2_slice_joint`. crvUSD's M2
    # slice is zero by construction (DET-43), so the joint numerator IS the
    # crash-path bad debt — and its exit depth is the SHOCKED one, because the
    # paired asset is depegged in this cell too.
    shock, target = Decimal("-0.50"), Decimal("0.93")
    f = {m: Decimal(1) + shock for m in oracle}
    shocked = {m: int(Decimal(oracle[m]) * f[m]) for m in oracle}
    cap = {m: int(Decimal(sell_side.get(m, 0)) * Decimal(shocked[m])
                  / Decimal(ONE_E18)) for m in oracle}
    res = run_cell(positions, prices, shocked, discount, cap, bandxy)
    pre_v = sum(p.collateral * shocked[p.market] // ONE_E18 for p in positions)
    depth = curves[str(target)]["0.02"]
    bad = res["bad_debt"]
    m4 = m4_for("JOINT", Decimal(0), {
        "effective": mech.effective_headroom, "naive": mech.naive_headroom,
        "burn_capacity": mech.burn_capacity,
        "ceiling_aggregate": mech.ceiling_aggregate,
        "stabilizer_debt_post_cell": mech.burn_capacity,
        "utilization_post_cell": str(ratio(mech.burn_capacity,
                                           mech.ceiling_aggregate)),
        "exit_depth_cell": depth, "lp_flight_share": "0",
        "counterfactual_ref": ["H1_kill", "EMA_lag", "H1_v1_contagion"]})
    cells.append(Cell(
        id="JOINT", member="JOINT", shock=shock, lst=Decimal(0), lp=Decimal(0),
        target=target,
        m1=MetricOne(
            pre=MetricReading(ratio=ratio(pre_v, base_debt),
                              share_below_100=share_below_100(res["rows"])),
            post=MetricReading(ratio=ratio(res["post_value"], res["post_debt"]),
                               share_below_100=share_below_100(res["rows"])),
            gap=ratio(res["post_value"], res["post_debt"]) - ratio(pre_v, base_debt)),
        m2=MetricTwo(bad_debt=bad, pct_supply=ratio(bad, supply_ruled)),
        m3=MetricThree(ratio=m3_ratio(bad, depth), forced_sell_volume=bad,
                       exit_depth=depth),
        m4=m4, counterfactual_lines=counterfactuals(
            "JOINT", "JOINT", bad,
            res["converted"] * int(abs(shock) * 10 ** 6) // 10 ** 6),
        lineage=["liquidation_model", "depth_model", "price_read",
                 "collateral_read", "debt_read"]))
    notes.setdefault("eligible", {})["JOINT"] = (res["eligible"],
                                                 res["eligible_debt"])
    notes["curves"] = curves
    if any(c.m3.ratio is None for c in cells):
        notes["undefined_ratio"] = UNDEFINED_RATIO_LITERAL
    return cells, [], notes


def _insulated_cell(cid, member, target, lp, depth, base_value, base_debt,
                    supply_ruled, m4_for, ema, counterfactuals):
    """DET-43: `m3.ratio = 0` EXACTLY, with DET-42's `structurally_insulated`.

    crvUSD holds no `node_class = stable` node and no GSM, so no supply's
    backing IS the shocked stable — the Member-2 numerator is zero by
    construction, not by rounding.
    """
    return Cell(
        id=cid, member=member, shock=None, lst=None, lp=lp, target=target,
        m1=MetricOne(pre=MetricReading(ratio=ratio(base_value, base_debt),
                                       share_below_100=Decimal(0)),
                     post=MetricReading(ratio=ratio(base_value, base_debt),
                                        share_below_100=Decimal(0)),
                     gap=Decimal(0)),
        m2=MetricTwo(bad_debt=0, pct_supply=Decimal(0)),
        m3=MetricThree(ratio=Decimal(0), forced_sell_volume=0, exit_depth=depth),
        m4=m4_for(member, lp, {"exit_depth_cell": depth,
                               "lp_flight_share": str(lp),
                               "counterfactual_ref": ["H1_v1_contagion"]}),
        counterfactual_lines=counterfactuals(member, cid, 0),
        lineage=["depth_model"])


def build_crvusd_cells(b, cfg, rpc, raw_bytes, mech, states, numeraire, frozen,
                       reads) -> tuple[list, list, dict, dict]:
    """Assemble B-4b's inputs from what B-4a already read, then build the 47.

    NOTHING here re-reads the chain except `calc_withdraw_one_coin`, which is
    R-B2.4's deferred ground truth arriving with `withdraw_one_coin`'s first
    consumption — one read per K90 pool at each of the three haircuts.
    """
    rows = json.loads(raw_bytes.decode("utf-8"))
    amm_of = {m.address: m.amm_address for m in b.markets}
    node_of = {m.address: m.collateral_address for m in b.markets}
    # COLLATERAL DECIMALS. The raw dump carries each position's collateral in
    # the ASSET's own base units - 8 for the four BTC markets, 18 for the rest -
    # while every price here is 1e18-scaled. Scaling to 18 dp is what makes the
    # two comparable; the bundle already read `decimals` per market, so this
    # costs nothing. Omitting it read every WBTC/cbBTC/LBTC/tBTC position as
    # zero-collateral, which is how B-4b's first fold produced 29.8M of
    # shock-invariant "bad debt" out of four markets that have none.
    scale = {m.address: 10 ** (18 - m.decimals) for m in b.markets}
    ll = mech.llamma
    positions = []
    for r in rows:
        ctrl = r["controller"].lower()
        amm = amm_of[ctrl]
        n1, n2 = ll.ticks[amm][r["user"].lower()]
        net = max(r["gross_debt"] - r["stablecoin_in_position"], 0)   # DET-06
        positions.append(Position(user=r["user"].lower(), market=ctrl, amm=amm,
                                  collateral=r["collateral"] * scale[ctrl],
                                  debt=net, n1=n1, n2=n2,
                                  x_pos=r["stablecoin_in_position"]))
    prices = {amm: BandPrices(up={bd.n: bd.p_oracle_up for bd in bands})
              for amm, bands in ll.bands.items()}
    # R-B4.15's weights: each band's recorded (x, y), the allocation basis.
    bandxy = {amm: {bd.n: (bd.x, bd.y) for bd in bands}
              for amm, bands in ll.bands.items()}
    oracle = {c: ll.markets[amm_of[c]].oracle for c in amm_of}
    spot = {c: ll.markets[amm_of[c]].spot for c in amm_of}
    disc = {c: ll.markets[amm_of[c]].liquidation_discount for c in amm_of}
    sell = {c: _sell_side_units(cfg, node_of[c]) for c in amm_of}
    lst = {c for c in amm_of if _is_lst(cfg, node_of[c])}
    ema = max((m.ema_window_s for m in b.oracle_rows
               if getattr(m.update_condition, "ema_window_s", None)), default=0) \
        if False else _ema_window(b)
    ks = k_subsets([r for r in b.pools if r.in_frozen_set])
    bits = {"states": states, "numeraire": numeraire, "k90": ks["90"],
            "positions": positions, "oracle": oracle, "spot": spot,
            "liquidation_discount": disc, "sell_side": sell, "lst_nodes": lst,
            "mechanism": mech, "ema_window_s": ema, "band_prices": prices,
            "band_xy": bandxy}
    cells, refs, notes = build_cells(b, bits)
    # DET-48 / R14: the literal, per volatile node, with no block and no flag.
    refs = [{"node": m.collateral_address, "symbol": m.symbol,
             "literal": "reference point unavailable"} for m in b.markets]
    notes["ground_truth"] = _withdraw_ground_truth(rpc, states, numeraire,
                                                   ks["90"], reads)
    assumptions = {"band_linear": BAND_LINEAR_LITERAL,
                   "capacity": CAPACITY_LITERAL,
                   "lp_flight": LP_FLIGHT_LITERAL,
                   # DET-43 / R-22: the literal and the three recomputed curves,
                   # which the check replays against each cell's exit depth.
                   "structural_insulation":
                       "structurally insulated; exposed through exit venues only",
                   "m2_curves": notes["curves"]}
    if "undefined_ratio" in notes:
        assumptions["undefined_ratio"] = notes["undefined_ratio"]
    if "ema_pairs" in notes:
        # R-B4.18: the optimistic and pessimistic m1.post side by side, so a
        # reader sees both readings of the same cell without recomputing.
        assumptions["ema_lag_readings"] = "; ".join(
            f"{k}: m1.post {v['m1_post_primary'][:8]} primary vs "
            f"{v['m1_post_counterfactual'][:8]} under EMA_lag"
            for k, v in sorted(notes["ema_pairs"].items()))
    return cells, refs, notes, assumptions


def _sell_side_units(cfg, node: str) -> int:
    """The node's sheet-signed bound in ITS OWN units, scaled to 1e18. The
    value is prose on the sheet (`"13750.0000"`), so it is parsed once here."""
    row = cfg.sell_side.get(node)
    if row is None:
        return 0
    try:
        return int(Decimal(row["value"]) * 10 ** 18)
    except Exception:                       # the LUSD exempt literal, not a number
        return 0


def _is_lst(cfg, node: str) -> bool:
    row = cfg.labels.get(node)
    return bool(row and row.lst_discount_applies)


def _ema_window(b) -> int:
    """R13 / §0(c): the bundle's per-market transitive max, NOT DET-44's
    `MA_EXP_TIME` — P-3.31 proved no such getter exists (A-14 queued)."""
    out = 0
    for row in b.oracle_rows:
        w = getattr(row.update_condition, "ema_window_s", None)
        if w:
            out = max(out, int(w))
    return out


def _withdraw_ground_truth(rpc, states, numeraire, k90, reads) -> list[dict]:
    """R-B2.4, arriving with the first consumption: the port's
    `withdraw_one_coin` against the pool's own `calc_withdraw_one_coin`, one
    read per K90 pool at each haircut."""
    out = []
    for addr in k90:
        p = states[addr]
        j = 1 - p.coins.index(numeraire)
        for lp in LPS:
            if lp == 0:
                continue
            amount = int(Decimal(p.total_supply) * lp)
            ported, _ = withdraw_one_coin(p, amount, j)
            r = rpc.read([Call(addr, "calc_withdraw_one_coin(uint256,int128)",
                               ("uint256",), (amount, j))])[0]
            onchain = int(r.one()) if r.ok else None
            reads[f"{addr}.calc_withdraw_one_coin({lp})"] = _cr(
                addr, "calc_withdraw_one_coin(uint256,int128)", rpc.run_block,
                (amount, j))
            out.append({"pool": addr, "lp": str(lp), "ported": ported,
                        "onchain": onchain,
                        "delta": None if onchain is None else ported - onchain})
    return out


def fold(inputs: dict, rpc=None) -> StressReport:
    """B-2: the header, and the exit-depth block. The mechanism block and the
    cells still land at B-4/5/6; `member2_target` is B-3's."""
    from factory.run import PIPELINE_VERSION, _token_address
    b, t, cfg = inputs["bundle"], inputs["tree"], inputs["cfg"]
    exit_depth = ExitDepth(lp_flight_literal=LP_FLIGHT_LITERAL)
    flags: list[str] = []
    cells: list = []
    refs: list = []
    assumptions: dict = {}
    mech = Mechanism()
    if rpc is not None:
        reads: dict = {}
        base_vps: dict = {}
        base_comp: dict = {}
        base_dec: dict = {}
        numeraire = _token_address(cfg, b.header.token)
        frozen = sorted(r.address for r in b.pools if r.in_frozen_set)
        states = read_pool_states(rpc, cfg, frozen, numeraire, reads, base_vps,
                                  base_comp, base_dec)
        venues = gsm_venues(b, rpc, reads)
        exit_depth = build_exit_depth(b, states, numeraire, venues, cfg, reads,
                                      base_vps, base_comp, base_dec, flags, rpc,
                                      {p.address: p.label for p in t.paired_assets})
        flags += [f"T-21 GSM {v.gsm} {v.reason} — venue closed in every cell"
                  for v in venues if not v.enters]
        mech = build_mechanism(b, cfg, rpc, inputs["raw"])
        if mech.llamma is not None:
            cells, refs, notes, assumptions = build_crvusd_cells(
                b, cfg, rpc, inputs["raw"], mech, states, numeraire, frozen, reads)
        elif b.gsms:                       # GHO: no AMM, an Aave book (B-5)
            from factory.gho_cells import build as build_gho
            ks = k_subsets([r for r in b.pools if r.in_frozen_set])
            # The cell builder's reads are the MECHANISM's, exactly as crvUSD's
            # are: `build_mechanism` keeps a dict of its own, and `exit_depth`
            # has already snapshotted the pool/GSM dict above. A shared dict
            # would be written after that snapshot and land nowhere.
            mech_reads: dict = {}
            cells, refs, notes, assumptions = build_gho(
                b, cfg, rpc, inputs["raw"], mech, states, numeraire, venues,
                mech_reads, _cr, depth_after_flight, ks["90"])
            mech = mech.model_copy(update={"h2_routing": {
                a: r["routing"] for a, r in notes["routing"].items()},
                "reads": mech_reads,
                "reserve_params": notes["reserve_params"],
                "emode_params": notes["emode_params"]})
        else:                              # LUSD: a trove book and a pool (B-6)
            from factory.lusd_cells import build as build_lusd
            ks = k_subsets([r for r in b.pools if r.in_frozen_set])
            mech_reads = {}
            cells, refs, notes, assumptions = build_lusd(
                b, cfg, rpc, inputs["raw"], mech, states, numeraire, venues,
                mech_reads, _cr, depth_after_flight,
                _shocked_depth_after_flight, ks["90"])
            mech = mech.model_copy(update={"reads": mech_reads})
    return StressReport(
        header=StressHeader(
            token=b.header.token, run_block=b.header.run_block,
            source_bundle_hash=b.header.bundle_hash,
            source_tree_hash=t.tree_hash,
            bundle_sheet_hash=b.header.sheet_hash,
            mirror_sheet_hash=cfg.sheet["sheet_hash"],
            stale_sheet=inputs["stale_sheet"],
            pipeline_version=PIPELINE_VERSION),
        value_scale=t.root.value_scale,
        member2_target=inputs["member2_target"] or None,
        exit_depth=exit_depth,
        mechanism=mech,
        cells=cells,
        reference_points=refs,
        assumptions=assumptions,
        flags=flags)


# ------------------------------------------------------------------ I/O -----


def emit(repo: pathlib.Path, bundle, tree, report: StressReport,
         m4_fields: tuple[str, ...] | None = None) -> tuple[pathlib.Path, bool]:
    """Run the stress checks, stamp, and route. The routing is the only write.

    Promotion needs THREE things: every check passing, a non-empty cell set,
    and a coherent sheet pairing. The cell clause is a named implementer
    default (P-6.01 R2): a report with no cells has computed nothing, and an
    empty artifact in `out/stress/` would read as a completed run.
    """
    from factory.validate.harness import run_stress_checks
    report = report.model_copy(update={
        "checks": run_stress_checks(bundle, tree, report, m4_fields)})
    ok = (all(r.result == "pass" for r in report.checks)
          and bool(report.cells)
          and not report.header.stale_sheet)
    report = finalise_stress(report)
    token, blk = report.header.token, report.header.run_block
    path = (repo / "out/stress" / token / f"{blk}.json" if ok
            else repo / "out/rehearsal" / token / f"stress-{blk}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialise_stress(report), encoding="utf-8", newline="")
    if ok:
        # R17's hand-verification sheet rides the PROMOTION, not the fold: a
        # rehearsal artifact has nothing to verify by hand. Gitignored with the
        # rest of `out/spotcheck/`.
        from factory.spotcheck import write_stress
        write_stress(bundle, report, repo)
    return path, ok


def main(repo: pathlib.Path, token: str, allow_stale_sheet: bool = False,
         rpc=None) -> tuple[pathlib.Path, bool, StressReport]:
    """`rpc` is injected in tests; in production it is built here and PINNED to
    the bundle's own `run_block`, never to a fresh head — which is why R-13
    holds for a module that reads (P-6.01 R2)."""
    from factory.logs_pointer import env
    from factory.rpc import RpcClient
    from factory.run import AssemblyStop
    inputs = load_inputs(repo, token, allow_stale_sheet)
    if rpc is None:
        url = env(repo, "ETH_RPC_URL")
        if not url:
            raise AssemblyStop("ETH_RPC_URL not set in the environment or .env")
        rpc = RpcClient(url, run_block=inputs["bundle"].header.run_block)
    if rpc.run_block != inputs["bundle"].header.run_block:
        raise AssemblyStop(
            f"rpc pinned to {rpc.run_block}, bundle is {inputs['bundle'].header.run_block}"
            " — R-13 requires one block per run and it is the bundle's.")
    report = fold(inputs, rpc)
    path, ok = emit(repo, inputs["bundle"], inputs["tree"], report,
                    inputs["cfg"].m4_fields)
    written = StressReport.model_validate_json(path.read_text(encoding="utf-8"))
    return path, ok, written


if __name__ == "__main__":
    _repo = pathlib.Path(__file__).resolve().parents[2]
    if len(sys.argv) < 2:
        print("usage: python -m factory.stress <TOKEN> [--allow-stale-sheet]"
              "  (crvUSD | GHO | LUSD)")
        sys.exit(2)
    _allow = "--allow-stale-sheet" in sys.argv[2:]
    try:
        _path, _ok, _r = main(_repo, sys.argv[1], _allow)
    except Exception as exc:                                  # a raised stop
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    print(f"token {_r.header.token} | run_block {_r.header.run_block} | "
          f"stress {_r.header.stress_hash[:8]} | cells {len(_r.cells)} | "
          f"checks {sum(x.result == 'pass' for x in _r.checks)}/{len(_r.checks)} | "
          f"stale_sheet {str(_r.header.stale_sheet).lower()} | "
          f"{'promoted' if _ok else 'REHEARSAL'} | {_path}")
    sys.exit(0 if _ok else 1)
