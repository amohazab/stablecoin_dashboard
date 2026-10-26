"""Step 10, commit 5 (P-10.07): the archetype-#2 tree fold.

Memo #2 §4: tree weight comes from the six disclosure-category nodes alone, at their
disclosed `usdAmount` (D1); the buffer assets are label rows with zero weight, carried
with their staleness; the reserve fund is its own slice, never credited (§3); the
supply classes and the attested DET-55 rows ride along. Expected headline 0 / 0 / 100.
"""

from __future__ import annotations

import datetime as _dt
from decimal import ROUND_HALF_UP, Decimal

from factory.config import Config
from factory.schema import (
    Bundle,
    QualifierRow,
    StabilizerSlice,
    StalenessNode,
    StalenessWorst,
    TreeBar,
    TreeNode,
    TreeRoot,
    TreeShares,
    TreeStaleness,
    TruncatedNode,
    VerifiabilityTree,
)

VALUE_SCALE = 1                       # the route's usdAmount is whole USD (NAMED DEFAULT)
LABELS = ("terminal", "terminal_other_layer", "recurses", "recurses_truncated", "unlisted")
# memo #2 §13 (Q12): the qualifying set adds `set_parameters` where its scope reaches the
# custody perimeter (the custodian list or COLLATERAL_MANAGER_ROLE).
QUALIFYING = ("mint", "upgrade", "set_oracle", "seize", "set_parameters")


def _pct1(x: Decimal) -> str:
    return str((x * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _run_date(b: Bundle) -> _dt.date:
    return _dt.datetime.fromtimestamp(b.header.block_timestamp, _dt.UTC).date()


def _days(b: Bundle, date: str) -> int:
    return (_run_date(b) - _dt.date.fromisoformat(str(date))).days


def cadence_days(text: str) -> int | None:
    """A-28: the cadence a `recurses` node's date is measured against - for a two-source
    cadence (attestation + PoR) the source that dates the node, the attestation. NAMED
    DEFAULT: quarterly 92 d, monthly 30 d, weekly 7 d; any other wording is not assessed."""
    t = text.lower()
    for word, days in (("quarterly", 92), ("monthly", 30), ("weekly", 7)):
        if word in t:
            return days
    return None


def qualifier_synthetic(b: Bundle) -> tuple[list[QualifierRow], str]:
    """A-51 (DET-70, archetype #2): the qualifying set adds `set_parameters` (memo #2
    §13, Q12), and the banner ends with Q13's off-chain sentence, n = the route's
    distinct custodian locations this run (FR-U36)."""
    rows = [QualifierRow(power=a.power, holder_type=a.holder_type, signer_disclosure="n/a",
                         delay_bucket=a.delay_bucket, veto=a.veto_address)
            for a in b.admin_surface if a.power in QUALIFYING and a.holder_type != "none"]
    n = len(set(b.synthetic.reads["FR-U36"].value.get("locations", [])))
    head = ("Verifiability conditional on: " + "; ".join(
        f"{q.power} — {q.holder_type} + {q.delay_bucket}" for q in rows) + "."
            if rows else "No admin power can alter backing — immutable.")
    return rows, (f"{head} Backing held by {n} custodians under issuer discretion; "
                  "on-chain keys shown below.")


def fold_synthetic(b: Bundle, cfg: Config) -> VerifiabilityTree:
    r = b.synthetic.reads
    cats: dict[str, int] = r["FR-U20"].value
    unlisted = sorted(set(cats) - set(cfg.category_nodes))
    backing = sum(cats.values())
    if backing <= 0:
        raise ValueError("USDe: backing_value 0 - nothing to fold")
    label = {c: (cfg.category_nodes[c].label if c in cfg.category_nodes else "unlisted")
             for c in cats}
    by = dict.fromkeys(LABELS, 0)
    for c, v in cats.items():
        by[label[c]] += v
    shares = TreeShares(**{k: Decimal(v) / Decimal(backing) for k, v in by.items()})
    share = {c: Decimal(v) / Decimal(backing) for c, v in cats.items()}

    # staleness: the `recurses` category nodes (Liquid Stables' row derived, P-10.05)
    D = []
    for c in cats:
        if label[c] != "recurses":
            continue
        d = cfg.disclosures.get(c)
        last = str(d["last_disclosure_date"]) if d else None
        D.append(StalenessNode(category=c, symbol=c, share=share[c], last_disclosure_date=last,
                               staleness_days=_days(b, last) if last else None))
    trunc = shares.recurses_truncated
    companion = (f"{_pct1(trunc)}% of backing depth-truncated — staleness not assessed"
                 if trunc > 0 else None)
    if any(x.staleness_days is None for x in D):
        st = TreeStaleness(D=D, weighted_days=None, worst=None, companion=companion,
                           status="inputs_owed — DET-76(e)")
    else:
        tot = sum(x.share for x in D)
        w = max(D, key=lambda x: (x.staleness_days, x.share))
        st = TreeStaleness(D=D, weighted_days=sum(x.share * x.staleness_days for x in D) / tot,
                           worst=StalenessWorst(symbol=w.symbol, days=w.staleness_days,
                                                share=w.share),
                           companion=companion, status=None)

    qualifier, banner = qualifier_synthetic(b)

    label_rows = []
    for s, row in sorted(cfg.label_rows.items()):
        d = cfg.disclosures.get(s)
        last = str(d["last_disclosure_date"]) if d else None
        label_rows.append({"symbol": s, "address": row.address, "chain": row.chain,
                           "label": row.label, "recurses_into": row.recurses_into,
                           "roles": list(row.roles), "weight": "0",
                           "last_disclosure_date": last,
                           "staleness_days": _days(b, last) if last else None,
                           "inherited_from": d.get("inherited_from") if d else None})
    rf_onchain = r["FR-U19"].value
    st_v = r["FR-U21"].value
    total = b.supply.total_supply
    staked, cooling = r["FR-U06"].value, r["FR-U07"].value["balance"]
    escrow = r["FR-U08"].value["balance"]
    synthetic = {
        "label_rows": label_rows,
        "reserve_fund": {"slice": cfg.reserve_fund.get("slice"), "credited": False,
                         "disclosed_usd": st_v["reserve_fund_usd"],
                         "onchain": rf_onchain},
        "supply_classes": {"staked": staked, "cooling": cooling, "bridged_escrow": escrow,
                           "free_float": total - staked - cooling - escrow,
                           "supply_ruled": b.supply.supply_ruled},
        "attested_rows": {c: {k: v for k, v in row.items() if k != "key"}
                          for c, row in cfg.attested_rows.items()},
        "t29": [{"category": x.symbol, "last_disclosure_date": x.last_disclosure_date,
                 "age_days": x.staleness_days,
                 "cadence": cfg.disclosures[x.symbol]["disclosure_cadence"],
                 "cadence_days": cadence_days(cfg.disclosures[x.symbol]["disclosure_cadence"]),
                 "overdue": (x.staleness_days is not None
                             and cadence_days(cfg.disclosures[x.symbol]["disclosure_cadence"])
                             is not None
                             and x.staleness_days > 2 * cadence_days(
                                 cfg.disclosures[x.symbol]["disclosure_cadence"]))}
                for x in D],
        "status_backing_usd": st_v["backing_usd"],
        "unlisted_categories": unlisted,
    }

    return VerifiabilityTree(
        token=b.header.token, run_block=b.header.run_block,
        source_bundle_hash=b.header.bundle_hash,
        root=TreeRoot(backing_value=backing, value_scale=VALUE_SCALE,
                      backed_supply=b.supply.origination_sum, supply_ruled=b.supply.supply_ruled,
                      residual=b.supply.residual,
                      perimeter=("USDe is minted only through EthenaMinting V2 (by minter()); "
                                 "its backing is the six disclosure categories of the issuer's "
                                 "backing-assets route, attested monthly (memo #2 §2)"),
                      stabilizer_debt=0),
        shares=shares,
        bars=[TreeBar(name="terminal", share=shares.terminal),
              TreeBar(name="terminal_other_layer", share=shares.terminal_other_layer),
              TreeBar(name="disclosure_dependent",
                      share=shares.recurses + shares.recurses_truncated)],
        truncated_share=trunc,
        truncated_nodes=[TruncatedNode(category=c, symbol=c, share=share[c],
                                       reason=cfg.category_nodes[c].reason or
                                       f"depth truncated at {c}")
                         for c in cats if label[c] == "recurses_truncated"],
        unclassified_literal=(f"{_pct1(shares.unlisted)}% of backing unclassified — "
                              "pending intake" if shares.unlisted > 0 else None),
        staleness=st, qualifier=qualifier, banner=banner,
        denominators={"shares": "backing_value", "bars": "backing_value",
                      "truncated_share": "backing_value",
                      "truncated_nodes.share": "backing_value",
                      "staleness.D.share": "backing_value",
                      "root.backing_value": "amount", "root.backed_supply": "amount",
                      "root.supply_ruled": "amount", "root.residual": "amount",
                      "root.stabilizer_debt": "amount",
                      "stabilizer_slice.debt": "amount",
                      "stabilizer_slice.ceiling_aggregate": "amount",
                      "stabilizer_slice.ceiling_share_of_supply_ruled": "supply_ruled",
                      "synthetic.supply_classes": "amount"},
        paired_assets=[], concentration=None,
        nodes=sorted((TreeNode(category=c, symbol=c, label=label[c], share=share[c])
                      for c in cats), key=lambda x: (-x.share, x.symbol)),
        stabilizer_slice=StabilizerSlice(debt=0, ceiling_aggregate=0, operation_count=0,
                                         ceiling_share_of_supply_ruled=Decimal(0)),
        flags=[f"unlisted category {c} (memo #1 §8.2)" for c in unlisted],
        synthetic=synthetic)
