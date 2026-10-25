"""P-10.06: the USDe adapter's offline pieces - disclosure shape gates, the snapshot
set, the selector scan, the holder classifier, and the schema's `synthetic` key."""

import json
import pathlib

import pytest

from factory.adapters import usde as U
from factory.schema import Bundle, serialise_for_disk

REPO = pathlib.Path(__file__).resolve().parents[1]

GOOD = {
    "/api/positions/current/backing-assets": {"strategies": [], "timestamp": 1792933308},
    "/api/collateral-breakdown": {"breakdown": []},
    "/api/collateralization/status": {"timestamp": "2026-10-25T19:00:16Z",
                                      "totalBackingAssetsInUsd": 1,
                                      "totalReserveFundInUsd": 1, "totalTokenSupplyInUsd": 1},
    "/api/por": {"lastUpdatedAt": "2026-10-23T00:03:49Z", "reports": []},
    "/api/institutional-lending": {"asOf": "2026-10-25T04:00:36Z", "totals": {},
                                   "counterparties": []},
    "/api/stablecoin-collateral": {"USDC": {"usd_amount": 1, "timestamp": 1792922294}},
    "/api/funding/quarterly": [{"name": "2022-Q3", "value": 0.1}],
}


def _get(bodies):
    return lambda url: (200, json.dumps(bodies[url.removeprefix(U.APP)]).encode())


def test_disclosures_pin_each_route_and_the_set_is_deterministic():
    d = U.fetch_disclosures(_get(GOOD))
    assert set(d) == set(U.ROUTES)
    assert d["status"]["prov"].as_of_date.isoformat() == "2026-10-25"
    assert d["por"]["prov"].as_of_date.isoformat() == "2026-10-23"
    a = U.snapshot_set(d)
    assert a == U.snapshot_set(d) and json.loads(a)["por"]["sha256"] == d["por"]["prov"].sha256


def test_a_missing_key_is_a_shape_change():
    bad = dict(GOOD, **{"/api/por": {"reports": []}})
    with pytest.raises(U.UsdeAdapterStop, match="SHAPE CHANGE"):
        U.fetch_disclosures(_get(bad))


def test_selector_scan_reads_the_dispatcher_push4():
    from eth_utils import function_signature_to_4byte_selector as sel
    code = "0x6080" + "63" + sel(U.SEIZE_SUSDE).hex() + "14"
    assert U._has_selector(code, U.SEIZE_SUSDE)
    assert not U._has_selector(code, "setOracle(address)")


def test_holder_kind_by_code_safe_and_timelock():
    class R:
        def __init__(self, ok, v=None):
            self.ok, self.value = ok, (v,)

        def one(self):
            return self.value[0]

    class Rpc:
        def __init__(self, code, thr, delay):
            self._c, self._r = code, [R(thr), R(delay is not None, delay)]

        def code(self, a):
            return self._c

        def read(self, calls):
            return self._r

    assert U.holder_kind(Rpc("0x", False, None), "0x1")[0] == "eoa"
    assert U.holder_kind(Rpc("0x60", True, None), "0x1")[0] == "multisig"
    assert U.holder_kind(Rpc("0x60", False, 86400), "0x1") == ("timelock", 86400)
    assert U.holder_kind(Rpc("0x60", False, None), "0x1")[0] == "contract_automated"


def test_cdp_bundles_carry_no_synthetic_key():
    f = sorted((REPO / "out/bundles/crvUSD").glob("*.json"))[-1]
    raw = f.read_bytes().replace(b"\r\n", b"\n").decode()
    assert '"synthetic"' not in serialise_for_disk(Bundle.model_validate_json(raw))
