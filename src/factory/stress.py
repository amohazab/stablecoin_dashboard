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
from factory.depth import A_PRECISION, BISECT_TOL, PoolState, pool_depth
from factory.provenance import ContractRead
from factory.rpc import Call
from factory.schema import (
    DepthConcentration,
    DepthPoint,
    ExitDepth,
    GroundTruth,
    GsmVenue,
    Mechanism,
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
                     base_comp: dict) -> dict[str, PoolState]:
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
                for m in range(8):
                    bc = rpc.read([Call(base, "coins(uint256)", ("address",), (m,))])[0]
                    if not bc.ok:
                        break
                    ca = bc.one().lower()
                    comp[ca] = int(rpc.read([Call(base, "balances(uint256)",
                                                  ("uint256",), (m,))])[0].one())
                    reads[f"{base}.coins({m})"] = _cr(base, "coins(uint256)", rb, (m,))
                    reads[f"{base}.balances({m})"] = _cr(base, "balances(uint256)",
                                                         rb, (m,))
                base_comp[base] = comp
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
    test is STRICT: the venue enters a curve point iff `fee_exit < s`."""
    rb = rpc.run_block
    out: list[GsmVenue] = []
    for g in bundle.gsms:
        dec = int(rpc.read([Call(g.underlying_asset, "decimals()", ("uint8",))])[0].one())
        probe = 10 ** 24
        raw = rpc.read([Call(g.fee_strategy, "getBuyFee(uint256)", ("uint256",),
                             (probe,))])[0]
        fee_exit = Decimal(int(raw.one())) / Decimal(probe) if raw.ok else Decimal(1)
        reads[f"{g.address}.getBuyFee"] = _cr(g.fee_strategy, "getBuyFee(uint256)",
                                              rb, (probe,))
        reads[f"{g.underlying_asset}.decimals()"] = _cr(g.underlying_asset,
                                                        "decimals()", rb)
        closed = g.is_frozen or g.is_seized
        out.append(GsmVenue(
            gsm=g.address, boxed_asset=g.underlying_asset, fee_exit=fee_exit,
            # The boxed asset counts at 1.00 per unit, the same par convention
            # §6.1.3 applies to paired assets, and it is a stata wrapper rather
            # than the bare stable (F14) — the identity is C2's.
            balance=g.available_liquidity * 10 ** (18 - dec),
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


def build_exit_depth(bundle, states: dict[str, PoolState], numeraire: str,
                     venues: list[GsmVenue], cfg, reads: dict, base_vps: dict,
                     base_comp: dict, flags: list, rpc=None) -> ExitDepth:
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
        label = row.label if row else "unlabeled"
        if label == "composite_passthrough":
            # R-B2.7: P-5.01 R4's mapping applies here exactly as in the tree —
            # the rubric's literal wins, and the mapping is flagged, not silent.
            label = "composite"
            flags.append("config literal composite_passthrough read as DET-11 "
                         "composite (R4, P-5.01; R-B2.7)")
        conc = DepthConcentration(
            largest_paired_asset=top,
            share_of_exit_depth=Decimal(by_asset[top]) / Decimal(total_d),
            label=label,
            disclosure_source=row.label_source if row else None)
    truth = (record_ground_truth(rpc, states, per_pool_2, numeraire, reads)
             if rpc is not None else [])
    return ExitDepth(ground_truth=truth, base_virtual_price=base_vps,
                     base_pool_composition=base_comp, depth_curve=curve,
                     k_subsets=ks, sensitivity_rows=rows, gsm_venues=venues,
                     concentration=conc, lp_flight_literal=LP_FLIGHT_LITERAL,
                     reads=reads)


def fold(inputs: dict, rpc=None) -> StressReport:
    """B-2: the header, and the exit-depth block. The mechanism block and the
    cells still land at B-4/5/6; `member2_target` is B-3's."""
    from factory.run import PIPELINE_VERSION, _token_address
    b, t, cfg = inputs["bundle"], inputs["tree"], inputs["cfg"]
    exit_depth = ExitDepth(lp_flight_literal=LP_FLIGHT_LITERAL)
    flags: list[str] = []
    if rpc is not None:
        reads: dict = {}
        base_vps: dict = {}
        base_comp: dict = {}
        numeraire = _token_address(cfg, b.header.token)
        frozen = sorted(r.address for r in b.pools if r.in_frozen_set)
        states = read_pool_states(rpc, cfg, frozen, numeraire, reads, base_vps,
                                  base_comp)
        venues = gsm_venues(b, rpc, reads)
        exit_depth = build_exit_depth(b, states, numeraire, venues, cfg, reads,
                                      base_vps, base_comp, flags, rpc)
        flags += [f"T-21 GSM {v.gsm} {v.reason} — venue closed in every cell"
                  for v in venues if not v.enters]
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
        mechanism=Mechanism(),
        flags=flags)


# ------------------------------------------------------------------ I/O -----


def emit(repo: pathlib.Path, bundle, tree,
         report: StressReport) -> tuple[pathlib.Path, bool]:
    """Run the stress checks, stamp, and route. The routing is the only write.

    Promotion needs THREE things: every check passing, a non-empty cell set,
    and a coherent sheet pairing. The cell clause is a named implementer
    default (P-6.01 R2): a report with no cells has computed nothing, and an
    empty artifact in `out/stress/` would read as a completed run.
    """
    from factory.validate.harness import run_stress_checks
    report = report.model_copy(update={
        "checks": run_stress_checks(bundle, tree, report)})
    ok = (all(r.result == "pass" for r in report.checks)
          and bool(report.cells)
          and not report.header.stale_sheet)
    report = finalise_stress(report)
    token, blk = report.header.token, report.header.run_block
    path = (repo / "out/stress" / token / f"{blk}.json" if ok
            else repo / "out/rehearsal" / token / f"stress-{blk}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialise_stress(report), encoding="utf-8", newline="")
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
    path, ok = emit(repo, inputs["bundle"], inputs["tree"], report)
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
