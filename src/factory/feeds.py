"""B-9: DET-54/55's per-feed update condition from the signed table (P-7.01 R21,
P-7.04), and A-19's observed NAV interval (P-7.05 S6).

A signed row is keyed by node address and names the feed; the adapter's
discovered `feed_or_source` must equal it, or the row describes a different
feed and the run stops. `deviation` and a `documented` heartbeat carry the
row's class-I `analyst_supplied {source, date}`; an `observed_max` heartbeat is
a pinned read of the feed's round history.
"""

from __future__ import annotations

import re

from factory.provenance import AnalystSupplied, ContractRead
from factory.rpc import Call
from factory.schema import Deviation, DeviationHeartbeat, HeartbeatS, NavSchedule

RD = ("uint80", "int256", "uint256", "uint256", "uint80")
# NAMED IMPLEMENTER DEFAULT (P-7.05 S6): the observation window for a NAV
# feed's `observed_max` heartbeat - 30 days back from the run block's timestamp,
# the gap reaching back past the window's start included.
NAV_WINDOW_S = 30 * 86_400
ROUND_BATCH = 45


class FeedStop(RuntimeError):
    """A signed feed row the chain contradicts."""


def nav_observed_max(rpc, adapter: str) -> tuple[HeartbeatS, list[str], int]:
    """The NAV adapter's source feed from its verified `source()` getter,
    asserted equal to the immutable in the adapter's runtime bytecode (the
    ScaledPriceAdapter's `_SOURCE`), then the largest interval between
    consecutive `updatedAt` values over the window."""
    rb = rpc.run_block
    code = rpc.code(adapter)
    src = rpc.read([Call(adapter, "source()", ("address",))])[0]
    immutables = {"0x" + x for x in re.findall(r"7f000000000000000000000000([0-9a-f]{40})",
                                               code[2:])}
    if not src.ok or src.one().lower() not in immutables:
        raise FeedStop(f"{adapter}: source() {src.one() if src.ok else 'reverted'} is not "
                       "the bytecode immutable")
    feed = src.one().lower()
    latest = rpc.read([Call(feed, "latestRoundData()", RD)])[0]
    if not latest.ok:
        raise FeedStop(f"{feed}: latestRoundData() reverted")
    rid, times, n = int(latest.value[0]), [int(latest.value[3])], 3
    floor = rpc.block_timestamp - NAV_WINDOW_S
    back = 1
    while times[-1] >= floor:
        batch = rpc.read([Call(feed, "getRoundData(uint80)", RD, (rid - back - k,))
                          for k in range(ROUND_BATCH)])
        n += len(batch)
        stop = False
        for r in batch:
            if not r.ok or int(r.value[3]) == 0:
                stop = True
                break
            times.append(int(r.value[3]))
            if times[-1] < floor:
                stop = True
                break
        back += ROUND_BATCH
        if stop:
            break
    if len(times) < 2:
        raise FeedStop(f"{feed}: fewer than two rounds - no observed interval")
    gaps = [times[k] - times[k + 1] for k in range(len(times) - 1)]
    first = rid - (len(times) - 1)
    hb = HeartbeatS(form="observed_max", value=max(gaps),
                    provenance=ContractRead(source_contract=feed, function="getRoundData(uint80)",
                                            args=[str(first), str(rid)], block=rb))
    flags = [f"A-19 observed_max over {len(gaps)} intervals of {feed} (source() of "
             f"{adapter}), window {NAV_WINDOW_S} s: max {max(gaps)} s"]
    return hb, flags, n


def condition_from_row(row: dict, discovered_feed: str, answer, updated, provenance: list,
                       observed: HeartbeatS | None = None):
    """The signed row's update condition for one oracle row."""
    if row["feed"] != discovered_feed:
        raise FeedStop(f"{row['symbol']}: signed feed {row['feed']} != discovered "
                       f"{discovered_feed}")
    signed = AnalystSupplied(source=row["source"], date=row["date"])
    if row["heartbeat_form"] == "observed_max":
        if observed is None:
            raise FeedStop(f"{row['symbol']}: observed_max heartbeat without a read")
        hb = observed
    else:
        hb = HeartbeatS(form="documented", value=row["heartbeat_s"], provenance=signed)
    if row["type"] == "nav_schedule":
        return NavSchedule(heartbeat_s=hb, answer=answer, updated_at=updated,
                           provenance=provenance)
    if row["type"] != "deviation_heartbeat" or row.get("deviation_bps") is None:
        raise FeedStop(f"{row['symbol']}: signed type {row['type']!r} without a deviation")
    return DeviationHeartbeat(heartbeat_s=hb,
                              deviation=Deviation(value_bps=row["deviation_bps"],
                                                  analyst_supplied=signed),
                              answer=answer, updated_at=updated, provenance=provenance)
