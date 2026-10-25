"""P-10.03 (Q27, Q42): the fourth provenance shape, `DisclosureSnapshot`.

Stored bundles carry only the three older shapes, so adding a union member must
not move a byte of any committed bundle; the type checks that assumed three
shapes now name the fourth instead of crashing on it."""

import datetime as dt
import pathlib
from types import SimpleNamespace

import pytest
from pydantic import TypeAdapter

from factory.provenance import ContractRead, DisclosureSnapshot, Provenance
from factory.run import write_raw
from factory.schema import Bundle, serialise_for_disk
from factory.validate.harness import Level3, _token_address, det_72, det_76e

REPO = pathlib.Path(__file__).resolve().parents[1]
P812_OPTIONAL = ("controller_admin_fees", "residual_unexplained_abs")
SNAP = dict(kind="disclosure_snapshot", source_url="https://app.ethena.fi/api/collateralization/status",
            as_of_date="2026-09-27", published_date="2026-10-10", sha256="ab" * 32,
            fetched_at="2026-10-25T11:06:04Z")


def test_union_round_trip():
    ta = TypeAdapter(Provenance)
    p = ta.validate_python(SNAP)
    assert isinstance(p, DisclosureSnapshot) and p.as_of_date == dt.date(2026, 9, 27)
    assert ta.validate_python(p.model_dump()) == p


def test_latest_committed_bundles_reserialise_byte_for_byte():
    """The latest promoted bundle per token - what `load_prior` and the stress
    loader read. Older bundles predate later schema fields and are not loaded."""
    files = [sorted(d.glob("*.json"))[-1] for d in sorted((REPO / "out/bundles").iterdir())
             if d.is_dir()]
    assert len(files) == 3
    for f in files:
        raw = f.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
        out = serialise_for_disk(Bundle.model_validate_json(raw))
        # GHO's and LUSD's latest bundles predate P-8.12's two optional fields,
        # which re-serialise as null (true at e73c078 too); nothing else moves.
        for key in P812_OPTIONAL:
            if f'"{key}":' not in raw:
                out = out.replace(f'"{key}":null,', "")
        assert out == raw, f


def _node(prov, date="2026-09-27"):
    return SimpleNamespace(label="recurses", symbol="Crypto Basis", disclosure_cadence="monthly",
                           last_disclosure_date=date, reads={"last_disclosure_date": prov})


def test_det_76e_accepts_a_snapshot_dated_as_the_node():
    snap = DisclosureSnapshot(**SNAP)
    b = SimpleNamespace(nodes=[_node(snap)], header=SimpleNamespace(run_block=1))
    assert det_76e(b, {}) is None
    b.nodes = [_node(snap, date="2026-09-26")]
    with pytest.raises(Level3, match="snapshot as_of_date"):
        det_76e(b, {})


def test_token_address_and_det_72_name_the_shape_instead_of_crashing():
    snap = DisclosureSnapshot(**SNAP)
    with pytest.raises(Level3, match="disclosure_snapshot"):
        _token_address(SimpleNamespace(supply=SimpleNamespace(reads={"total_supply": snap})))
    path = SimpleNamespace(r1_path="module_on_chain", r10_provenance=snap, r6_gates=[])
    b = SimpleNamespace(gsms=[], admin_surface=[], redemption_paths=[path])
    with pytest.raises(Level3, match="DET-72: path 0"):
        det_72(b, None)
    read = ContractRead(source_contract="0x" + "1" * 40, function="totalSupply()", block=1)
    assert _token_address(SimpleNamespace(supply=SimpleNamespace(reads={"total_supply": read}))) \
        == "0x" + "1" * 40


def test_write_raw_tracked_copy_only_for_a_disclosure_token(tmp_path):
    write_raw(tmp_path, "USDe", 7, '{"a":1}', disclosures=True)
    assert (tmp_path / "out/raw/7.json").read_bytes() \
        == (tmp_path / "out/disclosures/USDe/7.json").read_bytes() == b'{"a":1}'
    write_raw(tmp_path, "LUSD", 8, '{"b":2}')
    assert (tmp_path / "out/raw/8.json").exists()
    assert not (tmp_path / "out/disclosures/LUSD").exists()
