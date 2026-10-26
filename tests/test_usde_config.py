"""P-10.05: the USDe config (E6/E7) and config.load's archetype-#2 tables."""

import pathlib

import pytest

from factory.config import TOKEN_FILES, _label_rows, load
from factory.tree import analyzed_set

REPO = pathlib.Path(__file__).resolve().parents[1]
CFG = REPO / "config"


def test_usde_loads_with_six_nodes_nine_label_rows_four_classes():
    c = load(CFG, "USDe")
    assert sorted(c.category_nodes) == ["Crypto Basis", "DeFi Lending", "Equity and RWA Basis",
                                        "Institutional Lending", "Liquid Stables", "RWA"]
    assert len(c.label_rows) == 9 and len(c.supply_classes) == 4
    assert c.labels == {} and c.lend.state.value == "explicit_empty"
    assert {p.symbol for p in c.paired.values()} == {"USDT", "FRAX"}       # P-10.09 pool pairs
    assert c.label_rows["USDT0"].address == "none" and c.label_rows["USDT0"].as_ == "USDT"
    assert set(c.label_rows["USDT"].roles) == {"buffer", "pool_pair"}
    assert c.pool_set["member2_target"] == "none" and c.pool_set["floor_usd"] == 500000
    assert c.reserve_fund["credited"] is False and c.frozen_set_path.exists()  # P-10.09
    assert len(c.attested_rows) == 6 and all(
        r["assumption_applied"] == "attested_value" for r in c.attested_rows.values())


def test_liquid_stables_cadence_is_derived_from_the_oldest_buffer_row():
    d = load(CFG, "USDe").disclosures
    assert d["Liquid Stables"]["inherited_from"] == "USDT"
    assert d["Liquid Stables"]["last_disclosure_date"] == d["USDT"]["last_disclosure_date"]
    assert d["USDT0"]["inherited_from"] == "USDT"


def test_node_needs_exactly_one_of_address_and_category(tmp_path):
    for f in ("usde_roots.toml", "usde_sheet.toml"):
        (tmp_path / f).write_bytes((CFG / f).read_bytes())
    both = (CFG / "usde_labels.toml").read_text(encoding="utf-8").replace(
        'category = "RWA"\n', 'category = "RWA"\naddress = "0x' + "1" * 40 + '"\n')
    (tmp_path / "usde_labels.toml").write_text(both, encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one"):
        load(tmp_path, "USDe")


def test_label_row_none_address_iff_other_chain():
    row = dict(symbol="X", address="none", chain="ethereum", label="recurses",
               recurses_into="y", roles=["buffer"], label_source="s", date="2026-10-25")
    with pytest.raises(ValueError, match="iff chain"):
        _label_rows({"label_row": [row]})


def test_usde_joins_the_analyzed_set_and_cdp_configs_are_unchanged():
    assert "USDe" in TOKEN_FILES
    assert analyzed_set(REPO)["0x4c9edd5852cd905f086c759e8383e09bff1e68b3"] == "USDe"
    for t in ("crvUSD", "GHO", "LUSD"):
        c = load(CFG, t)
        assert c.category_nodes == {} and c.label_rows == {} and c.attested_rows == {}
