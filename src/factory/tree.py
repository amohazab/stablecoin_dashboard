"""Step 5: the verifiability tree (memo §4, brief §8.5) — a FOLD over a promoted
bundle. No RPC call, no read: every number here is already in the bundle, and a
field the bundle does not carry is a flag, never a build (P-5.01).

`uv run python -m factory.tree <TOKEN>` folds the LATEST promoted bundle in
`out/bundles/<TOKEN>/`, runs the four S2 checks (DET-14, DET-19, DET-70,
DET-11), and writes `out/trees/<TOKEN>/<run_block>.json` when all pass, or
`out/rehearsal/<TOKEN>/tree-<run_block>.json` when any does not (R2). One
required positional token, `sys.argv[1]` - the P-4.02 shape.

The tree changes no `Bundle` shape and moves no `bundle_hash` (R2). DET-84
folds `tree_hash` into `bundle_hash` at Step 7 under P-3.08's phased
definition - not here.
"""

from __future__ import annotations

import datetime as _dt
import json
import pathlib
import sys
from decimal import ROUND_HALF_UP, Decimal

from factory.config import Config, load
from factory.schema import (
    Bundle,
    ConcentrationLine,
    OffMainnetLine,
    PairedAssetRow,
    QualifierRow,
    StalenessNode,
    StalenessWorst,
    TreeBar,
    TreeRoot,
    TreeShares,
    TreeStaleness,
    TruncatedNode,
    VerifiabilityTree,
    finalise_tree,
    serialise_tree,
)

LABELS = ("terminal", "terminal_other_layer", "recurses", "recurses_truncated", "unlisted")
QUALIFYING = ("mint", "upgrade", "set_oracle", "seize")          # memo §13, DET-70
IMMUTABLE_BANNER = "No admin power can alter backing — immutable."

# Named implementer default (R3), citing each adapter's own entry: the unit
# `nodes[].value` is emitted in. A token absent here stops - no guessed scale.
VALUE_SCALE = {"crvUSD": 1, "GHO": 10**8, "LUSD": 10**18}

# R5: before Step 9, "last published tree" = the latest artifact in
# `out/trees/<token>/`. Ruled first for crvUSD's rows, widened to GHO at
# P-5.04 once GHO's tree existed: each tree links the other by `token@block`,
# never by hash, so the pair converges in one re-fold. LUSD is in no frozen
# pool's paired assets, so it has nothing to link.
LINKABLE = ("crvUSD", "GHO")


def _perimeter(b: Bundle) -> str:
    """R1's perimeter line. crvUSD's counts come from the bundle rather than a
    typed number, so the literal stays true if a market is added (named
    default); today it renders the ruled text exactly (P-5.02)."""
    if b.header.token == "crvUSD":
        n_ctrl = len(b.markets)
        n_coll = len({m.collateral_address for m in b.markets})
        return (f"mint-market origination — {n_ctrl} controllers, {n_coll} "
                "collaterals (P-3.20); crvUSD originated by the third minting "
                "class, the leveraged-market factory `0x370a449f…` (P-3.39), is "
                "outside this tree — P-4.01 #1")
    if b.header.token == "GHO":
        # Amin's wording (P-7.05), fitted to the bundle's own counts: Pool
        # instances = direct minters, GSMs = live GSM rows, the cross-chain
        # bridge = the off-mainnet facilitators. The flash minter (level 0 by
        # construction) mints nothing that persists and is not named.
        by = {c: sum(1 for f in b.facilitators if f.facilitator_class == c)
              for c in ("direct_minter", "off_mainnet")}
        return (f"GHO is minted only through Aave facilitators ({by['direct_minter']} Pool "
                f"instances, {len(b.gsms)} GSMs, the cross-chain bridge — "
                f"{by['off_mainnet']} off-mainnet facilitators); its backing branches are "
                "the Aave collateral attributed per §11.1 and the GSM boxed assets (C2)")
    if b.header.token == "LUSD":
        return "all troves; identity exact"
    raise KeyError(f"no perimeter ruled for token {b.header.token!r}")


OFF_MAINNET_LITERAL = ("minted against off-mainnet facilitators; backing on "
                       "Arbitrum/Monad/Plasma, not traced by this tree")
# The ruled literal names three chains; a facilitator whose label names none of
# them would make it false, so the fold refuses rather than prints it.
OFF_MAINNET_CHAINS = ("Arbitrum", "Monad", "Plasma")


def off_mainnet_line(b: Bundle) -> OffMainnetLine | None:
    """P-7.05's ruling on S1: the off-mainnet facilitator levels as a named line
    over `supply_ruled`, outside every bar (bars are over `backing_value`)."""
    rows = [f for f in b.facilitators if f.facilitator_class == "off_mainnet"]
    if not rows:
        return None
    stray = [f.label for f in rows if not any(c in f.label for c in OFF_MAINNET_CHAINS)]
    if stray:
        raise ValueError(f"off-mainnet facilitator(s) {stray} name no chain in the ruled "
                         "literal; the literal needs re-ruling")
    amount = sum(f.bucket_level for f in rows)
    return OffMainnetLine(
        amount=amount, share_of_supply_ruled=Decimal(amount) / Decimal(b.supply.supply_ruled),
        literal=OFF_MAINNET_LITERAL,
        facilitators=[{"address": f.address, "label": f.label, "bucket_level": f.bucket_level}
                      for f in rows])


def _pct1(share: Decimal) -> str:
    """R-7: p = 1, half-up."""
    return str((share * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def fold_shares(b: Bundle) -> tuple[int, TreeShares]:
    """DET-14(a)(b): shares by label over `backing_value` = sum of node values."""
    backing = sum(n.value for n in b.nodes)
    if backing <= 0:
        raise ValueError(f"{b.header.token}: backing_value {backing} - nothing to fold")
    by = dict.fromkeys(LABELS, 0)
    for n in b.nodes:
        by[n.label] += n.value
    return backing, TreeShares(**{k: Decimal(v) / Decimal(backing) for k, v in by.items()})


def qualifier_of(b: Bundle) -> tuple[list[QualifierRow], str]:
    """DET-70: one row per qualifying (power, holder) with a holder, copied
    verbatim, in table order; the banner replays from those rows."""
    rows = [QualifierRow(power=r.power, holder_type=r.holder_type, signer_disclosure="n/a",
                         delay_bucket=r.delay_bucket, veto=r.veto_address)
            for r in b.admin_surface
            if r.power in QUALIFYING and r.holder_type != "none"]
    if not rows:
        return rows, IMMUTABLE_BANNER
    return rows, "Verifiability conditional on: " + "; ".join(
        f"{q.power} — {q.holder_type} + {q.delay_bucket}" for q in rows)


def _staleness(b: Bundle, shares: dict[str, Decimal], truncated: Decimal) -> TreeStaleness:
    run_date = b.header.run_date
    d = []
    for n in b.nodes:
        if n.label != "recurses":
            continue
        days = None
        if n.last_disclosure_date is not None:
            days = (run_date - _dt.date.fromisoformat(n.last_disclosure_date)).days
        d.append(StalenessNode(address=n.address, symbol=n.symbol, share=shares[n.address],
                               last_disclosure_date=n.last_disclosure_date,
                               staleness_days=days))
    companion = (f"{_pct1(truncated)}% of backing depth-truncated — staleness not assessed"
                 if truncated > 0 else None)
    if not d:
        return TreeStaleness(D=[], weighted_days=None, worst=None, companion=companion,
                             status="no disclosure-dependent nodes")
    if any(x.staleness_days is None for x in d):
        return TreeStaleness(D=d, weighted_days=None, worst=None, companion=companion,
                             status="inputs_owed — DET-76(e); see P-5.01")
    total = sum(x.share for x in d)
    weighted = sum(x.share * x.staleness_days for x in d) / total
    w = max(d, key=lambda x: (x.staleness_days, x.share))
    return TreeStaleness(D=d, weighted_days=weighted,
                         worst=StalenessWorst(symbol=w.symbol, days=w.staleness_days,
                                              share=w.share),
                         companion=companion, status=None)


def _paired(b: Bundle, cfg: Config, linked: dict,
            analyzed: dict) -> tuple[list, ConcentrationLine | None, list]:
    """DET-11 rows per frozen pool, joined to `[[paired_asset]]` by address."""
    flags: list[str] = []
    rows: list[PairedAssetRow] = []
    weight: dict[str, Decimal] = {}
    frozen = [p for p in b.pools if p.in_frozen_set]
    total_tvl = sum((p.freeze_tvl or 0) for p in frozen)
    for p in frozen:
        for a in p.paired_assets:
            if total_tvl and p.paired_assets:
                # a multi-paired pool partitions its depth (P-3.26 finding 3)
                weight[a] = weight.get(a, Decimal(0)) + \
                    Decimal(p.freeze_tvl or 0) / Decimal(total_tvl) / len(p.paired_assets)
            cfg_row = cfg.paired.get(a)
            if cfg_row is None:
                rows.append(PairedAssetRow(pool=p.address, address=a, symbol=None,
                                           label="unlabeled", source=None))
                continue
            row = PairedAssetRow(pool=p.address, address=a, symbol=cfg_row.symbol,
                                 label=cfg_row.label, source=cfg_row.label_source)
            if cfg_row.label == "composite_passthrough":
                row.label = "composite"                  # R4: the rubric's literal wins
                row.note = "composition read owed (F4, C4)"
                flags.append("config literal composite_passthrough read as DET-11 "
                             "composite (R4, P-5.01)")
            if a in linked:
                row.label = "linked"
                row.source_tree, row.linked_shares = linked[a]
            elif a in analyzed:
                flags.append(f"analyzed token, tree pending: {analyzed[a]} "
                             "(memo §4.1, Level 1)")
            rows.append(row)
    concentration = None
    if weight:
        top = sorted(weight.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]  # PQ-3 tie-break
        top_row = next(r for r in rows if r.address == top)
        concentration = ConcentrationLine(largest_paired_asset=top, share_of_exit_depth=weight[top],
                                          label=top_row.label, disclosure_source=top_row.source)
    return rows, concentration, sorted(set(flags), key=flags.index)


def fold(bundle: Bundle, cfg: Config, linked: dict | None = None,
         analyzed: dict | None = None) -> VerifiabilityTree:
    """The tree, from one bundle. `linked` maps an analyzed token's ADDRESS to
    `(source_tree, TreeShares)`; `analyzed` maps every analyzed-set token's
    address to its name. Both resolved by `main`, so the fold stays pure."""
    b = bundle
    token = b.header.token
    if token not in VALUE_SCALE:
        raise KeyError(f"no value_scale named for token {token!r}")
    backing, shares = fold_shares(b)
    per_node = {n.address: Decimal(n.value) / Decimal(backing) for n in b.nodes}
    trunc = shares.recurses_truncated
    qualifier, banner = qualifier_of(b)
    paired, concentration, pflags = _paired(b, cfg, linked or {}, analyzed or {})
    offm = off_mainnet_line(b)

    flags = [f"{n.symbol}: {f}" for n in b.nodes for f in n.flags] + pflags
    boxed = {g.underlying_asset for g in b.gsms}
    if b.gsms and not boxed & {n.address for n in b.nodes}:
        flags.append("DET-28 boxed-asset nodes absent: "
                     + ", ".join(f"gsms[{i}]" for i in range(len(b.gsms)))
                     + " — identity and value owed (F2, C2)")

    return VerifiabilityTree(
        token=token, run_block=b.header.run_block,
        source_bundle_hash=b.header.bundle_hash,
        root=TreeRoot(backing_value=backing, value_scale=VALUE_SCALE[token],
                      backed_supply=b.supply.origination_sum,
                      supply_ruled=b.supply.supply_ruled, residual=b.supply.residual,
                      perimeter=_perimeter(b),
                      stabilizer_debt=sum(o.current_debt for o in b.stabilizer.operations)),
        shares=shares,
        bars=[TreeBar(name="terminal", share=shares.terminal),
              TreeBar(name="terminal_other_layer", share=shares.terminal_other_layer),
              TreeBar(name="disclosure_dependent",
                      share=shares.recurses + shares.recurses_truncated)],
        truncated_share=trunc,
        truncated_nodes=[TruncatedNode(address=n.address, symbol=n.symbol,
                                       share=per_node[n.address],
                                       reason=f"depth truncated at {n.symbol}; node's own "
                                              "backing not analyzed by this pipeline")
                         for n in b.nodes if n.label == "recurses_truncated"],
        unclassified_literal=(f"{_pct1(shares.unlisted)}% of backing unclassified — "
                              "pending intake" if shares.unlisted > 0 else None),
        staleness=_staleness(b, per_node, trunc),
        qualifier=qualifier, banner=banner,
        denominators={"shares": "backing_value", "bars": "backing_value",
                      "truncated_share": "backing_value",
                      "truncated_nodes.share": "backing_value",
                      "staleness.D.share": "backing_value",
                      "concentration.share_of_exit_depth": "frozen_set_freeze_tvl",
                      "root.backing_value": "amount", "root.backed_supply": "amount",
                      "root.supply_ruled": "amount", "root.residual": "amount",
                      "root.stabilizer_debt": "amount",
                      **({"off_mainnet_line.share_of_supply_ruled": "supply_ruled"}
                         if offm else {})},
        paired_assets=paired, concentration=concentration, off_mainnet_line=offm,
        flags=flags)


# ------------------------------------------------------------------ I/O -----


def latest_bundle(repo: pathlib.Path, token: str) -> Bundle:
    d = repo / "out/bundles" / token
    files = sorted((p for p in d.glob("*.json") if p.stem.isdigit()), key=lambda p: int(p.stem))
    if not files:
        raise FileNotFoundError(f"no promoted bundle in {d}")
    return Bundle.model_validate_json(files[-1].read_text(encoding="utf-8"))


def latest_tree(repo: pathlib.Path, token: str) -> VerifiabilityTree | None:
    d = repo / "out/trees" / token
    files = sorted((p for p in d.glob("*.json") if p.stem.isdigit()), key=lambda p: int(p.stem))
    if not files:
        return None
    return VerifiabilityTree.model_validate_json(files[-1].read_text(encoding="utf-8"))


def analyzed_set(repo: pathlib.Path) -> dict:
    """Memo §4.1's analyzed set, by address: every token with a declared config
    file set, its address from its own root (never a symbol match)."""
    from factory.config import TOKEN_FILES
    from factory.run import _token_address
    return {_token_address(load(repo / "config", t), t): t for t in TOKEN_FILES}


def resolve_links(repo: pathlib.Path, token: str) -> dict:
    """R5: `{analyzed token address: (source_tree, shares)}` for LINKABLE tokens
    other than this one that have a tree in `out/trees/`."""
    from factory.run import _token_address  # the token's own root
    out = {}
    for t in LINKABLE:
        if t == token:
            continue
        tree = latest_tree(repo, t)
        if tree is not None:
            addr = _token_address(load(repo / "config", t), t)
            out[addr] = (f"{t}@{tree.run_block}", tree.shares)
    return out


def emit(repo: pathlib.Path, bundle: Bundle, tree: VerifiabilityTree) -> tuple[pathlib.Path, bool]:
    """Run the four S2 checks, stamp, and route: all pass -> `out/trees/`,
    anything else -> `out/rehearsal/` (R2). The routing is the only write."""
    from factory.validate.harness import run_tree_checks
    tree = tree.model_copy(update={"checks": run_tree_checks(bundle, tree)})
    ok = all(r.result == "pass" for r in tree.checks)
    tree = finalise_tree(tree)
    token, blk = tree.token, tree.run_block
    path = (repo / "out/trees" / token / f"{blk}.json" if ok
            else repo / "out/rehearsal" / token / f"tree-{blk}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialise_tree(tree), encoding="utf-8", newline="")
    return path, ok


def main(repo: pathlib.Path, token: str) -> tuple[pathlib.Path, bool, VerifiabilityTree]:
    bundle = latest_bundle(repo, token)
    cfg = load(repo / "config", token)
    tree = fold(bundle, cfg, resolve_links(repo, token), analyzed_set(repo))
    path, ok = emit(repo, bundle, tree)
    written = VerifiabilityTree.model_validate_json(path.read_text(encoding="utf-8"))
    from factory.config import TOKEN_FILES
    from factory.spotcheck import write_tree
    write_tree(bundle, written, cfg, TOKEN_FILES[token]["labels"],
               repo / "out/spotcheck" / token)             # gitignored (P-3.13)
    return path, ok, written


if __name__ == "__main__":
    _repo = pathlib.Path(__file__).resolve().parents[2]
    if len(sys.argv) < 2:
        print("usage: python -m factory.tree <TOKEN>  (crvUSD | GHO | LUSD)")
        sys.exit(2)
    _path, _ok, _t = main(_repo, sys.argv[1])
    print(f"token {_t.token} | run_block {_t.run_block} | tree {_t.tree_hash[:8]} | "
          f"checks {sum(r.result == 'pass' for r in _t.checks)}/{len(_t.checks)} | "
          f"{'promoted' if _ok else 'REHEARSAL'} | {_path}")
    print(json.dumps({"bars": [(x.name, str(x.share)) for x in _t.bars],
                      "banner": _t.banner}, ensure_ascii=False))
    sys.exit(0 if _ok else 1)
