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


@dataclass(frozen=True)
class Config:
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

    def root(self, root_id: str) -> Root:
        if root_id not in self.roots:
            raise KeyError(f"discovery root '{root_id}' absent from config")
        return self.roots[root_id]


def _date(v) -> _dt.date:
    return v if isinstance(v, _dt.date) else _dt.date.fromisoformat(str(v))


def load(config_dir: Path) -> Config:
    roots_raw = tomllib.loads((config_dir / "discovery_roots.toml").read_text(encoding="utf-8"))
    labels_raw = tomllib.loads((config_dir / "labels.toml").read_text(encoding="utf-8"))
    sheet_raw = tomllib.loads((config_dir / "crvusd_sheet.toml").read_text(encoding="utf-8"))

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

    bridges = [{"address": b["address"].lower(), "bridge_type": b["bridge_type"],
                "source": b["source"], "date": _date(b["date"])}
               for b in roots_raw.get("bridge", [])]
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
    return Config(roots=roots, labels=labels, paired=paired, lend=lend, sheet=sheet_raw,
                  bridges=bridges, reference_feeds=refs, por_feeds=pors,
                  oracle_constituents=ocs, wallet_registries=wrs,
                  frozen_pool_index=frozen_pool_index)
