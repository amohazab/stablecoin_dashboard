"""Config loading: discovery roots, label config, sheet mirror.

Config is read-only. Nothing in the pipeline writes it back; corrections are
logged analyst events (P-3.15).
"""

from __future__ import annotations

import datetime as _dt
import tomllib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


@dataclass(frozen=True)
class Root:
    """A discovery root — analyst-supplied, staleness-tracked (DET-04, R-1)."""

    id: str
    address: str
    role: str
    source: str
    date: _dt.date

    def stale_days(self, today: _dt.date) -> int:
        return (today - self.date).days


@dataclass(frozen=True)
class LabelRow:
    """A §4 label config row (DET-02). `label` is None where the label is only
    knowable at run time — tBTC, resolved by FR-36's WalletRegistry read (A5)."""

    address: str
    symbol: str
    node_class: str
    lst_discount_applies: bool
    label_source: str
    date: _dt.date
    label: str | None = None
    # P-4.08: an `unlabeled` row is a config state, not a tree state - it says
    # a ruling is OWED. `reason` and `share` travel with it into the node's
    # flags so the disclosure names which wedge of the tree is unruled.
    reason: str | None = None
    share: str | None = None


class LendState(Enum):
    """Three states, never two (P-3.17).

    An absent or empty lend list must never render as "no lend markets exist";
    that would silently assert the Morpho double-count is impossible.
    """

    NOT_CONFIGURED = "not_configured"
    EXPLICIT_EMPTY = "explicit_empty"
    POPULATED = "populated"


@dataclass(frozen=True)
class LendFactories:
    state: LendState
    addresses: tuple[str, ...] = ()
    # Full signed rows, in file order. `rows` carries the per-factory
    # enumeration surface (3.1b): the two factories differ - OneWayLending
    # exposes `vaults(i)`, the V2 factory exposes `markets(i)` - so the getter
    # signature is config data, established by probe, never a constant in code.
    rows: tuple[dict, ...] = ()

    @property
    def market_count_field(self) -> str | int:
        """What `counts.lend_market_count` renders as, per state."""
        if self.state is LendState.NOT_CONFIGURED:
            return "unknown - no lend exclusion data configured"
        if self.state is LendState.EXPLICIT_EMPTY:
            return "n/a - no lend factories exist"
        return len(self.addresses)

    @property
    def det07_exercisable(self) -> bool:
        """DET-07's mint/lend exclusion can only be exercised with real data."""
        return self.state is LendState.POPULATED


@dataclass(frozen=True)
class PairedAsset:
    """A DET-11 paired-asset label row. Deliberately NOT a LabelRow: paired
    stables are not crvUSD tree nodes and owe no sell-side parameter (DET-52)
    or disclosure cadence (DET-76(e)). Keeping the classes distinct is what
    stops the tree-node checks sweeping them in (P-3.24 binding)."""

    address: str
    symbol: str
    label: str
    label_source: str
    date: _dt.date
    note: str | None = None


# P-4.06: one file set per token, separate files rather than one keyed file.
# crvUSD's names are untouched, so its four hashes do not move on this change.
# The GHO frozen set is ABSENT until its freeze; absence is the first-run state,
# not an error, so the loader never reads it — `frozen_set_path` is resolved and
# the caller checks existence.
TOKEN_FILES: dict[str, dict[str, str]] = {
    "crvUSD": {"roots": "discovery_roots.toml", "labels": "labels.toml",
               "sheet": "crvusd_sheet.toml", "frozen_set": "frozen_set_crvusd.json"},
    "GHO": {"roots": "gho_roots.toml", "labels": "gho_labels.toml",
            "sheet": "gho_sheet.toml", "frozen_set": "frozen_set_gho.json"},
    # P-4.15: declared with the sheet edit so `lusd_sheet.toml` is loadable and
    # the mirror's reproduce test can cover three tokens. `lusd_roots.toml` and
    # `lusd_labels.toml` are the BUILD session's and do not exist yet, so
    # `load(config_dir, "LUSD")` raises FileNotFoundError today. That is the
    # honest state: the declaration says which files LUSD will read, not that
    # they are there.
    "LUSD": {"roots": "lusd_roots.toml", "labels": "lusd_labels.toml",
             "sheet": "lusd_sheet.toml", "frozen_set": "frozen_set_lusd.json"},
}


@dataclass(frozen=True)
class Config:
    token: str
    frozen_set_path: Path
    roots: dict[str, Root]
    labels: dict[str, LabelRow]
    paired: dict[str, PairedAsset]
    lend: LendFactories
    sheet: dict
    bridges: list[dict] = field(default_factory=list)
    reference_feeds: list[dict] = field(default_factory=list)
    por_feeds: list[dict] = field(default_factory=list)
    oracle_constituents: dict[str, list[str]] = field(default_factory=dict)
    wallet_registries: list[dict] = field(default_factory=list)
    # DET-10(d)-ii's factory-side pin, signed 2026-09-07: one row per
    # frozen pool, `{pool, factory_root, index, found_at_block, date}`.
    frozen_pool_index: list[dict] = field(default_factory=list)
    # DET-28's dated fallback (P-4.08 ruling 1). Consulted ONLY for a
    # facilitator the selector probe returns `unresolved`; absence keeps it.
    facilitator_classes: dict[str, dict] = field(default_factory=dict)
    unlabeled_by_threshold: dict | None = None
    # DET-68 A4 for off-chain-governed holders (P-5.01 R13): dated analyst rows
    # keyed by lower-cased HOLDER ADDRESS, never by holder type - two crvUSD
    # holders share `dao_governance` with different delays. Absent is not an
    # error here; the adapter stops on a holder that needs a row and has none.
    admin_delays: dict[str, dict] = field(default_factory=dict)

    def root(self, root_id: str) -> Root:
        if root_id not in self.roots:
            raise KeyError(f"discovery root '{root_id}' absent from config")
        return self.roots[root_id]


def _date(v) -> _dt.date:
    return v if isinstance(v, _dt.date) else _dt.date.fromisoformat(str(v))


def load(config_dir: Path, token: str) -> Config:
    if token not in TOKEN_FILES:
        raise KeyError(f"no config file set declared for token '{token}'")
    files = TOKEN_FILES[token]
    roots_raw = tomllib.loads((config_dir / files["roots"]).read_text(encoding="utf-8"))
    labels_raw = tomllib.loads((config_dir / files["labels"]).read_text(encoding="utf-8"))
    sheet_raw = tomllib.loads((config_dir / files["sheet"]).read_text(encoding="utf-8"))

    roots: dict[str, Root] = {}
    for r in roots_raw.get("root", []):
        root = Root(r["id"], r["address"].lower(), r["role"], r["source"], _date(r["date"]))
        if root.id in roots:
            raise ValueError(f"duplicate discovery root id: {root.id}")
        roots[root.id] = root

    labels: dict[str, LabelRow] = {}
    for n in labels_raw.get("node", []):
        row = LabelRow(
            address=n["address"].lower(),
            symbol=n["symbol"],
            node_class=n["node_class"],
            lst_discount_applies=bool(n["lst_discount_applies"]),
            label_source=n["label_source"],
            date=_date(n["date"]),
            label=n.get("label"),
            reason=n.get("reason"),
            share=n.get("share"),
        )
        if row.address in labels:  # DET-02: unique address per row
            raise ValueError(f"duplicate label config address: {row.address}")
        if row.lst_discount_applies and row.node_class != "volatile":
            # DET-02 clause (i)
            raise ValueError(f"{row.symbol}: lst_discount_applies requires node_class=volatile")
        labels[row.address] = row

    if "lend_factory" not in roots_raw:
        lend = LendFactories(LendState.NOT_CONFIGURED)
    else:
        rows = tuple(roots_raw["lend_factory"])
        addrs = tuple(f["address"].lower() for f in rows)
        lend = LendFactories(
            LendState.EXPLICIT_EMPTY if not addrs else LendState.POPULATED, addrs,
            rows
        )

    paired: dict[str, PairedAsset] = {}
    for a in labels_raw.get("paired_asset", []):
        row = PairedAsset(
            address=a["address"].lower(), symbol=a["symbol"], label=a["label"],
            label_source=a["label_source"], date=_date(a["date"]), note=a.get("note"),
        )
        if row.address in paired:
            raise ValueError(f"duplicate paired-asset address: {row.address}")
        if row.address in labels:
            raise ValueError(f"{row.symbol}: address is both a node and a paired asset")
        paired[row.address] = row

    # P-4.07: a `[[bridge]]` row is read from EITHER file. crvUSD's three sit
    # in `discovery_roots.toml` where P-3.35 signed them and do not move; GHO's
    # CCIP row sits in `gho_labels.toml`. One reader, two homes, no duplication.
    bridges = [{"address": b["address"].lower(), "bridge_type": b["bridge_type"],
                "source": b["source"], "date": _date(b["date"])}
               for b in list(roots_raw.get("bridge", [])) + list(labels_raw.get("bridge", []))]
    refs = [{"node_address": r["node_address"].lower(), "kind": r["kind"],
             "feed_address": r.get("feed_address"), "source": r["source"],
             "date": _date(r["date"])} for r in labels_raw.get("reference_feed", [])]
    pors = [{"node_address": r["node_address"].lower(),
             "feed_address": r["feed_address"], "source": r["source"],
             "date": _date(r["date"])} for r in labels_raw.get("por_feed", [])]

    ocs = {r["oracle_address"].lower(): [p.lower() for p in r["pools"]]
           for r in labels_raw.get("oracle_constituents", [])}
    wrs = [{"node_address": r["node_address"].lower(),
            "bridge_address": r["bridge_address"].lower(),
            "registry_address": r["registry_address"].lower(),
            "locator_read": r["locator_read"], "source": r["source"],
            "date": _date(r["date"])}
           for r in labels_raw.get("wallet_registry", [])]

    frozen_pool_index = list(roots_raw.get("frozen_pool_index", []))
    fac_cls = {}
    for f in labels_raw.get("facilitator_class", []):
        a = f["address"].lower()
        if a in fac_cls:
            raise ValueError(f"duplicate facilitator_class address: {a}")
        fac_cls[a] = {"facilitator_class": f["facilitator_class"],
                      "classified_on": _date(f["classified_on"]), "source": f["source"]}
    admin_delays = {}
    for d in list(roots_raw.get("admin_delay", [])) + list(labels_raw.get("admin_delay", [])):
        a = d["holder_address"].lower()
        if a in admin_delays:
            raise ValueError(f"duplicate admin_delay holder_address: {a}")
        admin_delays[a] = {"holder_name": d["holder_name"],
                           "delay_seconds": int(d["delay_seconds"]),
                           "delay_bucket": d["delay_bucket"],
                           "source": d["source"], "date": _date(d["date"])}
    return Config(token=token, frozen_set_path=config_dir / files["frozen_set"],
                  facilitator_classes=fac_cls, admin_delays=admin_delays,
                  unlabeled_by_threshold=labels_raw.get("unlabeled_by_threshold"),
                  roots=roots, labels=labels, paired=paired, lend=lend, sheet=sheet_raw,
                  bridges=bridges, reference_feeds=refs, por_feeds=pors,
                  oracle_constituents=ocs, wallet_registries=wrs,
                  frozen_pool_index=frozen_pool_index)
