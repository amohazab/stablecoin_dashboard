"""P-10.04 (A-33, A-48, E4): the §1 `[archetypes: …]` markers, the registry's sets,
the runner's filter and the record's `not_applicable[]`."""

import copy
import pathlib

import pytest

from factory.report.record import GateRecord
from factory.rubric import (
    ARCHETYPES,
    archetype_markers,
    base_id,
    read_archetype_markers,
    read_trigger_table,
)
from factory.validate.harness import CDP_ONLY, CHECKS, Level3, applies, det_12

REPO = pathlib.Path(__file__).resolve().parents[1]


def test_markers_name_29_cdp_rows_and_det_90():
    m = read_archetype_markers(REPO)
    cdp = sorted(k for k, v in m.items() if v == {"cdp"})
    assert cdp == sorted(CDP_ONLY) and len(cdp) == 29
    assert m["DET-90"] == {"synthetic"}
    assert all(v == ARCHETYPES for k, v in m.items() if k not in CDP_ONLY | {"DET-90"})


def test_registry_sets_equal_the_markers_and_det_12_holds_them():
    m = read_archetype_markers(REPO)
    assert all(m.get(base_id(c.entry_id), ARCHETYPES) == c.archetypes for c in CHECKS)
    assert len(CHECKS) == 97 and sum(1 for c in CHECKS if c.archetypes == {"cdp"}) == 29
    assert [c.entry_id for c in CHECKS if c.archetypes == {"synthetic"}] == ["DET-90"]
    ctx = {"printed_trigger_table": read_trigger_table(REPO), "archetype_markers": m}
    det_12(None, ctx)
    off = copy.deepcopy(ctx)
    off["archetype_markers"]["DET-03"] = ARCHETYPES
    with pytest.raises(Level3, match="archetype markers"):
        det_12(None, off)


def test_marker_parser_defaults_and_rejects():
    text = "**DET-01 — a**\n**DET-03 — b** [archetypes: cdp]\n"
    assert archetype_markers(text) == {"DET-01": ARCHETYPES, "DET-03": frozenset({"cdp"})}
    with pytest.raises(ValueError, match="outside"):
        archetype_markers("**DET-03 — b** [archetypes: fiat]\n")
    with pytest.raises(ValueError, match="different markers"):
        archetype_markers("**DET-29(a) — x** [archetypes: cdp]\n**DET-29(b)(c) — y**\n")


def test_runner_filter_by_token_archetype():
    det03 = next(c for c in CHECKS if c.entry_id == "DET-03")
    det12 = next(c for c in CHECKS if c.entry_id == "DET-12")
    assert all(applies(c, t) for c in CHECKS for t in ("crvUSD", "GHO", "LUSD")
               if c.entry_id != "DET-90")
    assert not applies(det03, "USDe") and applies(det12, "USDe")
    assert sum(applies(c, "USDe") for c in CHECKS) == 68           # E1 floor 67 + DET-90


def test_record_omits_an_empty_not_applicable():
    base = dict(token="LUSD", run_block=1, report_hash="r", bundle_hash="b", tree_hash="t",
                stress_hash="s", table_hash="x", template_hash="m", pipeline_version="p",
                sheet_hash="h", results=[], triggers=[], unregistered=[])
    assert "not_applicable" not in GateRecord(**base).model_dump(mode="json")
    na = [{"entry_id": "DET-03", "reason": "archetype #2"}]
    got = GateRecord(**{**base, "token": "USDe", "not_applicable": na}).model_dump(mode="json")
    assert got["not_applicable"] == na
