"""B-9: DET-76(e)'s disclosure fields for `recurses` nodes (P-7.01 R7, P-7.04).

Three read forms, chosen by the signed sheet row (`cfg.disclosures`, joined to
the node's address in `config.load`), never by symbol:

* an ISO date in the row -> the analyst-supplied date, class I, dated by the
  row's own `[ANALYST-SUPPLIED <date>: ...]` tag;
* a `[[por_feed]]` row for the node -> the PoR feed's `latestRoundData()` at
  `run_block`; the date is the UTC date of `updatedAt`. `description()` must
  equal the signed row's (a mismatch contradicts a signed value: stop);
* cbETH's "last update of the exchange-rate oracle" -> the last
  `ExchangeRateUpdated(address,uint256)` log at or before `run_block`, found by
  the logs POINTER (P-4.04 R3) and decided by the chain: `exchangeRate()` at
  `run_block` must equal the log's value. Provenance is that `ContractRead`, the
  log's block goes in `last_disclosure_block` (P-7.05 S4, option (b)).

A PoR older than its heartbeat has no owning trigger: recorded in the node's
`flags`, no level (P-7.05 S10).
"""

from __future__ import annotations

import datetime as _dt
import re

from eth_utils import keccak

from factory.logs_pointer import get_logs
from factory.provenance import AnalystSupplied, ContractRead
from factory.rpc import Call

RD = ("uint80", "int256", "uint256", "uint256", "uint80")
EXCHANGE_RATE_UPDATED = "0x" + keccak(text="ExchangeRateUpdated(address,uint256)").hex()
# NAMED IMPLEMENTER DEFAULT (B-9): the pointer's lookback for cbETH's last rate
# update - 30 days of blocks at 12 s. The oracle updated daily through 2026-09.
EVENT_LOOKBACK_BLOCKS = 216_000


class DisclosureStop(RuntimeError):
    """A signed disclosure input the chain contradicts."""


def _utc_date(ts: int) -> str:
    return _dt.datetime.fromtimestamp(ts, _dt.UTC).date().isoformat()


def _tag_date(source: str) -> str:
    m = re.match(r"ANALYST-SUPPLIED (\d{4}-\d{2}-\d{2})", source)
    if m is None:
        raise DisclosureStop(f"disclosure source carries no dated tag: {source[:60]}")
    return m.group(1)


def disclosure_fields(cfg, rpc, address: str, http_get=None, key: str = "") -> tuple[dict, int]:
    """`{disclosure_cadence, last_disclosure_date, last_disclosure_block,
    reads, flags}` for one `recurses` node, and the RPC read count."""
    row = cfg.disclosures.get(address)
    if row is None:
        return {}, 0
    out = {"disclosure_cadence": row["disclosure_cadence"], "last_disclosure_date": None,
           "last_disclosure_block": None, "reads": {}, "flags": []}
    rb = rpc.run_block
    text = row["last_disclosure_date"]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        out["last_disclosure_date"] = text
        out["reads"]["last_disclosure_date"] = AnalystSupplied(
            source=row["source"], date=_tag_date(row["source"]))
        if row.get("inherited_from"):
            out["flags"].append(f"DET-76(e): disclosure inherited from the "
                                f"{row['inherited_from']} row (memo §4.3 pass-through)")
        return out, 0
    por = next((p for p in cfg.por_feeds if p["node_address"] == address), None)
    if por is not None:
        f = por["feed_address"]
        q = rpc.read([Call(f, "description()", ("string",)), Call(f, "latestRoundData()", RD)])
        if not q[0].ok or q[0].one() != por["description"]:
            raise DisclosureStop(f"PoR {f}: description() "
                                 f"{q[0].one() if q[0].ok else 'reverted'!r} != signed "
                                 f"{por['description']!r}")
        if not q[1].ok:
            out["flags"].append(f"DET-76(e): PoR {f} latestRoundData() reverted")
            return out, 2
        updated = int(q[1].value[3])
        age = rpc.block_timestamp - updated
        out["last_disclosure_date"] = _utc_date(updated)
        out["reads"]["last_disclosure_date"] = ContractRead(
            source_contract=f, function="latestRoundData()", args=[], block=rb)
        out["flags"].append(
            f"DET-76(e): PoR {f} updatedAt {updated}, age {age} s vs heartbeat "
            f"{por['heartbeat']} s" + (" - older than heartbeat, record-only (S10)"
                                       if age > por["heartbeat"] else ""))
        return out, 2
    if "exchange-rate oracle" in text:
        if http_get is None:
            out["flags"].append("DET-76(e): no logs pointer injected; event read not made")
            return out, 0
        ptr = get_logs(address, [EXCHANGE_RATE_UPDATED],
                       max(rb - EVENT_LOOKBACK_BLOCKS, 0), rb, http_get, key)
        if not ptr.rows:
            out["flags"].append(f"DET-76(e): no ExchangeRateUpdated in the "
                                f"{EVENT_LOOKBACK_BLOCKS}-block lookback")
            return out, 0
        last = max(ptr.rows, key=lambda r: r.block)
        logged = int(last.data, 16)
        r = rpc.read([Call(address, "exchangeRate()", ("uint256",))])[0]
        if not r.ok or int(r.one()) != logged:
            raise DisclosureStop(f"{address}: exchangeRate() at {rb} "
                                 f"{r.one() if r.ok else 'reverted'} != last "
                                 f"ExchangeRateUpdated value {logged} (block {last.block})")
        ts = int(rpc._w3.eth.get_block(last.block)["timestamp"])
        out["last_disclosure_date"] = _utc_date(ts)
        out["last_disclosure_block"] = last.block
        out["reads"]["last_disclosure_date"] = ContractRead(
            source_contract=address, function="exchangeRate()", args=[], block=rb)
        out["flags"].append(f"DET-76(e): last ExchangeRateUpdated at block {last.block} "
                            f"(ts {ts}), rate {logged} equals exchangeRate() at run_block")
        return out, 2
    raise DisclosureStop(f"{address}: disclosure row names no read form this module "
                         f"implements: {text[:60]}")
