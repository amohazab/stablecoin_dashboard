"""P-10.09: DET-66's archetype-#2 clause (A-39) - one module_on_chain path, R2
whitelisted, R6 {capacity_limited, pausable}, R7 FR-U09 and FR-U35, R9 disclaimed."""

from types import SimpleNamespace as NS

import pytest

from factory.schema import ContractRead, RedemptionPath
from factory.validate.harness import Level3, det_66

V2 = "0x" + "2" * 40


def path(**kw):
    base = dict(r1_path="module_on_chain", r2_who="whitelisted", r3_received=["0x" + "a" * 40],
                r4_rate="face_value", r5_minimum="none",
                r6_gates=[{"kind": "capacity_limited", "param": "global_max_redeem_per_block"},
                          {"kind": "pausable", "param": None}],
                r7_capacity="min(synthetic.reads.FR-U09, synthetic.reads.FR-U35)",
                r8="enforceable_unless_paused (see R7)", r9_legal_claim="disclaimed",
                r10_provenance=ContractRead(source_contract=V2, function="redeem()",
                                            args=[], block=1, read_at="2026-10-25T00:00:00Z"))
    return RedemptionPath(**{**base, **kw})


def bundle(*paths):
    return NS(redemption_paths=list(paths), header=NS(token="USDe"),
              synthetic=NS(reads={"FR-U09": 1, "FR-U35": 2}))


def test_usde_path_passes():
    assert det_66(bundle(path()), None) is None


@pytest.mark.parametrize("bad", [dict(r2_who="anyone"), dict(r9_legal_claim="yes"),
                                 dict(r6_gates=[{"kind": "pausable", "param": None}]),
                                 dict(r7_capacity="synthetic.reads.FR-U09")])
def test_usde_path_limbs_fail(bad):
    with pytest.raises(Level3):
        det_66(bundle(path(**bad)), None)
    with pytest.raises(Level3, match="exactly one"):
        det_66(bundle(path(), path()), None)


@pytest.mark.parametrize("backing,rf,fires", [("1000", "10", True), ("1020", "10", False),
                                              ("1020", "4", True)])
def test_det61_a37_backing_ratio_and_reserve_fund(backing, rf, fires):
    from factory.validate.harness import det_61
    b = NS(synthetic=NS(reads={"FR-U21": NS(value={"backing_usd": backing,
                                                    "reserve_fund_usd": rf})}),
           supply=NS(supply_ruled=1000 * 10 ** 18))
    assert det_61(b, {"sheet": {}}) == (("T-07", 1) if fires else None)
