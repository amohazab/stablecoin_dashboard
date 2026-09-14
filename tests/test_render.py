"""B-11a′ tests: DET-89's `fmt` in both forms, the SVG writer (the tree diagram
included), the structural-zero branch, and the page's two layers."""

from __future__ import annotations

import pathlib
import re
import tomllib
from decimal import Decimal

import pytest

from factory.report import svg
from factory.report.render import Formatter, governance_sentence, m4_tables, structural_zero

REPO = pathlib.Path(__file__).resolve().parents[1]
MF = tomllib.loads((REPO / "templates/manifest.toml").read_text(encoding="utf-8"))
W = tomllib.loads((REPO / "templates/wording.toml").read_text(encoding="utf-8"))
E = 10 ** 18
BLOCKS = {"crvUSD": 25974925, "GHO": 25974932, "LUSD": 25974949}


def pages(token: str) -> pathlib.Path:
    """B-11b: pages that S3 blocked stay in rehearsal; the site directory holds none."""
    return REPO / f"out/rehearsal/{token}/{BLOCKS[token]}"


@pytest.fixture
def fmt():
    return Formatter(MF["display_rule"], MF["compact"], value_scale=10 ** 8)


def test_full_form_follows_the_display_rule(fmt):
    assert fmt(2_104_809_204_981_834_354_272_443_571, "base_units") == "2,104,809,204.98"
    assert fmt(5 * E // 10, "base_units") == "0.5000"             # < 1: four decimals
    assert fmt(12 * E, "base_units") == "12.00"
    assert fmt(2 ** 256 - 1, "base_units").endswith(".58")        # a 78-digit sentinel
    assert fmt(53_607_323_677_921_349, "value_scale_units") == "536,073,236.78"
    assert fmt(313_866_560, "usd_whole") == "313,866,560"
    assert fmt(None, "base_units") == "—"


def test_exact_zero_prints_zero_in_both_forms(fmt):
    # the fifth live run's ruling 2 (R-B11.6 refined): an amount's compact zero is "$0"
    for unit in ("base_units", "ratio", "bps", "usd_whole"):
        want = "$0" if unit in ("base_units", "usd_whole") else "0"
        assert fmt(0, unit) == "0" and fmt("0", unit, "supply_ruled", compact=True) == want


def test_compact_form(fmt):
    assert fmt(18_899_446_902_370_967_960_042_656, "base_units", compact=True) == "$18.9M"
    assert fmt(294_556_796_023_967_960_042_656, "base_units", compact=True) == "$294.6k"
    assert fmt(5_934_707_122_249_762_779, "base_units", compact=True) == "$6"
    assert fmt(2_104_809_204_981_834_354_272_443_571, "base_units", compact=True) == "$2.1B"
    assert fmt("0.003108", "ratio", "supply_ruled", compact=True) == "0.31%"
    assert fmt("0.0000000028", "ratio", "supply_ruled", compact=True) == "< 0.01%"


def test_ratios_percent_only_with_a_denominator(fmt):
    assert fmt("0.2869454398", "ratio", "backing_value") == "28.7%"
    assert fmt("0.00000031", "ratio", "exit_depth") == "< 0.1%"
    assert fmt("1.201792884", "ratio") == "1.2018"
    assert fmt(50, "bps") == "0.50%"
    assert fmt("19.583405", "days") == "19.6 days"
    assert fmt(1789323179, "unix_s") == "2026-09-13 18:12 UTC"
    assert fmt("0x2260fac5e5542a773aa44fbcfedf7c193bc2c599", "address") == "0x2260fa…c599"


def test_tree_diagram_band_legend_nodes_and_side_note():
    bars = [("Checkable on-chain", Decimal("0.287"), "28.7%"),
            ("Checkable one layer down", Decimal("0.394"), "39.4%"),
            ("Depends on disclosures", Decimal("0.319"), "31.9%")]
    cols = [[("WETH", "21.1%", None)], [("wstETH", "34.1%", None)],
            [(f"N{i}", "1.0%", "3 d old") for i in range(9)]]
    side = "minted for other chains — not traced here (21.5%)"
    a = svg.tree_diagram(["Supply $699.0M", "originated $699.0M · residual 0"], side, bars,
                         cols, "caption")
    assert a == svg.tree_diagram(["Supply $699.0M", "originated $699.0M · residual 0"], side,
                                 bars, cols, "caption")                    # deterministic
    vb = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', a)
    assert vb.group(1) == "1000" and 420 <= Decimal(vb.group(2)) <= 460 and 'width="100%"' in a
    assert side in a and "+3 more below" in a and "3 d old" in a and "WETH" in a
    band = [Decimal(m) for m in re.findall(r'<rect x="[\d.]+" y="[\d.]+" width="([\d.]+)" '
                                           r'height="36"', a)]
    assert len(band) == 3 and abs(sum(band) - 960) <= Decimal("0.3")     # one proportional band
    for fill in svg.CLASS_FILLS:                          # a colour per class, band + legend
        assert a.count(f'fill="{fill}"') >= 2
    assert "not traced" not in svg.tree_diagram(["Supply"], None, bars, cols, "c")


def test_charts_carry_dollar_axes():
    a = svg.line_chart([("−20%", Decimal(1), "$1"), ("−50%", Decimal(3), "$3")], "t", "x",
                       "bad debt ($)", [(Decimal(0), "0"), (Decimal(3), "$3")])
    assert a.count("<circle") == 2 and "bad debt ($)" in a and ">$3</text>" in a
    b = svg.stacked_columns([("2%", Decimal(10), Decimal(5), "$15")], "t", ("p", "g"), "x",
                            "exit liquidity ($)", [(Decimal(0), "0"), (Decimal(15), "$15")])
    assert "exit liquidity ($)" in b and 'viewBox="0 0 1000' in b


def test_coordinates_round_half_up_to_a_tenth():
    assert svg._r(Decimal("12.345")) == "12.3" and svg._r(10) == "10" and svg._r(0.05) == "0.1"


def test_structural_zero_branch_reads_its_named_rows():
    assert structural_zero({}) == (False, None)
    rows = {"stress.structural_zero.flag": {"value": True},
            "stress.structural_zero.reason": {"value": "no trove reaches MCR on the grid"}}
    assert structural_zero(rows) == (True, "no trove reaches MCR on the grid")


def test_governance_sentence_in_words():
    def row(power, holder, bucket):
        p = f"admin.{power}.0xabc"
        return {f"{p}.holder_type": {"value": holder}, f"{p}.delay_bucket": {"value": bucket},
                f"{p}.veto_address": {"value": None}, f"{p}.scope": {"value": []},
                f"{p}.upgradeability": {"value": None}}
    rows = {**row("mint", "dao_governance", "1–7d"), **row("set_oracle", "dao_governance", "1–7d")}
    assert governance_sentence(rows, W) == ("The DAO can change minting and oracle settings "
                                            "with a 1–7 day delay.")


@pytest.mark.parametrize("token", ["crvUSD", "GHO", "LUSD"])
def test_reader_layer_is_plain_and_the_page_escapes(token):
    page = (pages(token) / "index.html").read_text(encoding="utf-8")
    reader = page.split('class="specialists"')[0]
    text = re.sub(r"<[^>]+>", " ", re.sub(r"<svg.*?</svg>", "", reader, flags=re.S))
    assert not re.search(r"DET-\d|\bP-\d+\.\d+|\bA-\d+\b|\bT-\d\d\b", text)
    assert ("[slot: structural_summary — pending B-13]" in page         # B-13: or the filled slot
            or 'data-slot="structural_summary"' in page) and "<script" not in page
    assert "< 0." not in re.sub(r"<[^>]+>", "", page.replace("&lt;", "&lt;"))  # escaped
    assert "DET-19" not in page and "Rubric map" in (pages(token) / "appendix.html"
                                                     ).read_text(encoding="utf-8")


def test_m4_maps_render_as_tables_never_as_key_address_rows():
    nested = {"alpha": "0.5",
              "is_killed": {"0x338cb2d827112d989a861cde87cd9ffd913a1f9d": {
                  "allowed": 1, "balance": 2, "ceiling": 3, "debt": 0, "killed_provide": False}},
              "redemption_capacity": {"reason": "crash path excluded", "value": 0}}
    t = m4_tables(nested, lambda x: (str(x), ""), W)
    assert t["scalars"] == [("alpha", "0.5", "")]
    keepers = next(m for m in t["maps"] if m["title"] == "PegKeepers")
    assert keepers["key_label"] == "address"
    assert keepers["columns"] == ["allowed", "balance", "ceiling", "debt", "killed (provide)"]
    assert keepers["rows"][0][0] == "0x338cb2…1f9d" and len(keepers["rows"][0][2]) == 5
    assert next(m for m in t["maps"] if m["title"] == "Redemption capacity")["key_label"] == "field"


@pytest.mark.parametrize("token,flag", [("crvUSD", True), ("GHO", False), ("LUSD", True)])
def test_structural_zero_branch_on_each_page(token, flag):
    import json
    stress = json.loads((REPO / f"out/stress/{token}/{BLOCKS[token]}.json").read_text(
        encoding="utf-8"))
    assert stress["structural_zero"]["flag"] is flag
    page = (pages(token) / "index.html").read_text(encoding="utf-8")
    assert ("Bad debt is structurally zero on the whole grid" in page) is flag
    assert ('aria-label="bad debt as the collateral price falls"' in page.lower()) is (not flag)
    assert ("<h4>PegKeepers</h4>" in page) is (token == "crvUSD")
    assert not re.search(r"<td>[a-z_ ]+ · 0x[0-9a-f]{6}", page)          # no key · address rows


@pytest.mark.parametrize("token", ["crvUSD", "GHO", "LUSD"])
def test_tooltips_are_css_only_and_cover_the_reader_layer(token):
    page = (pages(token) / "index.html").read_text(encoding="utf-8")
    reader = page.split('class="specialists"')[0]
    tips = re.findall(r'<span class="tip" tabindex="0" role="button" aria-label="([^"]+)">\?'
                      r'<span class="tip-text" role="tooltip">([^<]+)</span></span>', reader)
    assert len(tips) == 9                           # 3 cards, 5 headings, the grid legend
    assert all(label == text and "block " in text for label, text in tips)
    assert any(t[1].startswith("Shortfall left after liquidations in the headline scenario")
               for t in tips)
    css = (pages(token).parent / "style.css").read_text(encoding="utf-8")
    assert ".tip:focus .tip-text" in css and "<script" not in page
    assert "Independent market reference prices are not available" in page
