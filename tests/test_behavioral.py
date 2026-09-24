"""Step 8 phase A (P-8.01): the behavioral tier - trimming, the fetch, the site block and
A-20's either/or. Fixtures are the committed trimmed probe files (P5); nothing here
touches the network."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys

import pytest

from factory import behavioral, site

REPO = pathlib.Path(__file__).resolve().parents[1]
FIX = REPO / "tests/fixtures/webacy"
RAW = REPO / "tests/fixtures/webacy-raw"
TOKENS = ("crvUSD", "GHO", "LUSD")
SOURCE = {"crvUSD_depeg.json": "503c5df3", "GHO_depeg.json": "4592b784",
          "LUSD_depeg.json": "80850175", "hci.json": "07d81d8a"}
FETCHED = dt.date(2026, 9, 15)
P902_BEFORE = {"crvUSD": "996a25d1", "GHO": "f0e396e3", "LUSD": "75a2882f"}   # P-9.02

# ---- the trimmed schema (P5): nothing outside it is ever committed ------------------------
REQ = {"fetched_at": None, "url": None, "status": None, "seconds": None, "body_sha256": None,
       "rate_headers": {k: None for k in behavioral.RATE}}
COHORT = {"index": None, "topSharePct": None, "riskBand": None, "note": None}
ENTRY = {"chain": None, "address": None, "symbol": None, "name": None,
         "holderConcentration": {"top10": COHORT, "top30": COHORT, "holderCount": None}}
DEPEG_BODY = {"snapshot": {k: None for k in ("ts", "price", "peg_value", "dev_clean", "score",
                                             "tier", "total_dex_liquidity_usd",
                                             "cost_to_move_up_usd", "cost_to_move_down_usd",
                                             "liquidity_depth_tier")},
              "history": {"series": [{"ts": None, "price": None, "peg_value": None}]},
              "stale": None,
              "token": {"total_supply_on_chain": None,
                        "markets": [{k: None for k in behavioral.MARKET_KEYS}]}}
META = {"generatedAt": None, "stale": None, "page": None}
SNAPSHOT = {"token": None, "address": None, "depeg": {"request": REQ, "body": DEPEG_BODY},
            "supply": {"request": REQ, "body": {"stale": None, "token": {
                "symbol": None, "addresses": {"eth": None}, "supply": None, "net_7d": None,
                "net_7d_pct": None, "net_30d": None, "net_90d": None}}},
            "hci": {"requests": [REQ], "meta": META, "entry": ENTRY}}
FIXTURE_DEPEG = {"source_sha256": None, "request": REQ, "body": DEPEG_BODY}
FIXTURE_HCI = {"source_sha256": None, "request": REQ, "body": {"meta": META, "data": [ENTRY]}}


def outside(obj, schema, path="$") -> list[str]:
    """Every key in `obj` that `schema` does not allow (None = a leaf)."""
    if schema is None or obj is None:
        return []
    if isinstance(schema, list):
        return [x for i, o in enumerate(obj) for x in outside(o, schema[0], f"{path}[{i}]")]
    out = [f"{path}.{k}" for k in obj if k not in schema]
    return out + [x for k in obj if k in schema for x in outside(obj[k], schema[k], f"{path}.{k}")]


def fixture(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def unit(d: dict) -> dict:
    return {k: d[k] for k in ("request", "body")}


def addresses() -> dict[str, str]:
    return behavioral.addresses(REPO)


def entry_for(address: str) -> dict:
    return {"chain": "eth", "address": address.lower(), "symbol": "x", "name": "x",
            "holderConcentration": {"top10": {"index": 0.1234, "topSharePct": 61.25,
                                              "riskBand": "low"},
                                    "top30": {"index": 0.13, "topSharePct": 80.0,
                                              "riskBand": "low"},
                                    "holderCount": 12345}}


def usd(x) -> str:
    import tomllib

    from factory.report.render import Formatter
    mf = tomllib.loads((REPO / "templates/manifest.toml").read_text(encoding="utf-8"))
    return Formatter(mf["display_rule"], mf["compact"])(x, "usd_whole", compact=True)


def blk(snap: dict, as_of: dt.date = FETCHED):
    return behavioral.block(snap, as_of, wording(), usd)


def supply_unit(address: str, net=23817262.58, pct=0.1039, supply=252963999.56) -> dict:
    return {"request": dict(REQ, fetched_at="2026-09-15T18:16:50+00:00", url="u", status=200,
                            seconds=0.5, body_sha256="0" * 64,
                            rate_headers={k: "1" for k in behavioral.RATE}),
            "body": {"stale": False, "token": {"symbol": "x", "addresses": {"eth": address},
                                               "supply": supply, "net_7d": net,
                                               "net_7d_pct": pct}}}


def fixture_snapshot(token: str, *, stale=False, hci_stale=False, covered=False,
                     supply=None, note=None) -> dict:
    a = addresses()[token]
    depeg = unit(fixture(f"{token}_depeg.json"))
    depeg["body"]["stale"] = stale
    hci = unit(fixture("hci.json"))
    hci["body"]["meta"]["stale"] = hci_stale
    if covered:
        hci["body"]["data"] = [entry_for(a)]
        if note:
            hci["body"]["data"][0]["holderConcentration"]["top10"]["note"] = note
    return behavioral.assemble(token, a, depeg, supply, [hci])


def tmp_repo(tmp_path: pathlib.Path, snapshots: dict[str, dict] | None = None) -> pathlib.Path:
    for sub in ("out/site", "out/evaluation", "out/logs", "docs/context", "templates", "config"):
        shutil.copytree(REPO / sub, tmp_path / sub)
    for t, snap in (snapshots or {}).items():
        p = tmp_path / "out/behavioral" / t / "20260915T181626Z.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(snap, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return tmp_path


def files(root: pathlib.Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted((root / "out/site").rglob("*")) if p.is_file()}


def page(out: dict, token: str) -> str:
    return out[f"{token}/index.html"].decode("utf-8")


# ---- trimming ---------------------------------------------------------------------------

def test_committed_fixtures_and_snapshots_carry_no_key_outside_the_trimmed_schema():
    for name in SOURCE:
        f = fixture(name)
        assert outside(f, FIXTURE_HCI if name == "hci.json" else FIXTURE_DEPEG) == [], name
        assert f["source_sha256"][:8] == SOURCE[name]
    assert fixture("hci.json")["body"]["data"] == []            # no other token's entry
    snaps = sorted((REPO / "out/behavioral").glob("*/*.json"))
    for p in snaps:
        assert outside(json.loads(p.read_text(encoding="utf-8")), SNAPSHOT) == [], p
    for t in TOKENS:
        assert outside(fixture_snapshot(t, covered=True), SNAPSHOT) == []


@pytest.mark.skipif(not RAW.exists(), reason="full probe files are gitignored (P5)")
def test_the_trimmed_fixtures_reproduce_from_the_full_files():
    for name, short in SOURCE.items():
        raw = (RAW / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest()[:8] == short
        kind = "hci" if name == "hci.json" else "depeg"
        assert behavioral.trim_fixture(kind, raw, addresses().values()) == fixture(name)


def test_naive_timestamps_parse_as_utc_and_the_series_runs_oldest_to_newest():
    series = fixture("crvUSD_depeg.json")["body"]["history"]["series"]
    naive = [p["ts"] for p in series if not re.search(r"(Z|[+-]\d\d:\d\d)$", p["ts"])]
    assert len(naive) == 23
    assert behavioral.parse_ts(naive[0]).utcoffset() == dt.timedelta(0)
    pts = behavioral.series_bp(fixture_snapshot("crvUSD"))
    assert [t for t, _ in pts] == sorted(t for t, _ in pts) and len(pts) == 390
    assert pts[0][0] < pts[-1][0]
    assert behavioral.parse_ts(series[0]["ts"]) == pts[-1][0]      # the API is newest-first


def test_lusd_week_max_deviation_is_193_7_bp():
    _, st = blk(fixture_snapshot("LUSD"))
    assert st["max_abs_bp"] == "193.7"


# ---- the block and its suffixes -----------------------------------------------------------

def wording() -> dict:
    import tomllib
    text = (REPO / "templates/wording.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)["behavioral"]


def cards_of(html: str) -> dict[str, tuple[str, str | None]]:
    """label -> (value, note) for every stat card in a block."""
    import html as _h
    out = {}
    for label, value, note in re.findall(
            r'<div class="card"><div class="card-label">(.*?) <span class="tip".*?</span></span>'
            r'</div><div class="card-value">(.*?)</div>(?:<div class="card-note">(.*?)</div>)?'
            r"</div>", html):
        out[_h.unescape(label)] = (_h.unescape(value), _h.unescape(note) if note else None)
    return out


def test_block_contents_and_the_not_covered_card():
    html, st = blk(fixture_snapshot("GHO"))
    assert html.startswith(behavioral.MARK_BEGIN) and html.endswith(behavioral.MARK_END)
    assert '<h2>How it trades <span class="tip"' in html
    c = cards_of(html)
    assert list(c) == ["Peg price", "Deviation from peg", "Webacy depeg score", "DEX liquidity",
                       "Supply change, 7 days", "Top-10 holder share"]         # R11's order
    assert c["Peg price"] == ("0.9986", None) and c["Deviation from peg"] == ("−13.8 bp", None)
    assert c["Webacy depeg score"] == ("2 of 100", "tier ok")
    assert c["Top-10 holder share"] == ("not covered by Webacy", None) and not st["hci_found"]
    assert "7-day max |deviation|: 18.5 bp" in html
    assert "Behavioral data: Webacy, fetched 2026-09-15 18:16 UTC. Fetched, not computed or " \
           "verified by this pipeline.</p>" in html
    covered, st2 = blk(fixture_snapshot("GHO", covered=True))
    assert cards_of(covered)["Top-10 holder share"] == ("61.3%", "risk band low")
    order = [covered.index(x) for x in ('<div class="cards">', "7-day max |deviation|",
                                        "Share of supply held, ", "DEX pools, top 10",
                                        'class="meta attribution"')]
    assert order == sorted(order)                                              # R15


def test_a_snapshot_older_than_14_days_gets_the_staleness_suffix():
    old = " — snapshot is older than 14 days"
    html14, _ = blk(fixture_snapshot("crvUSD"), FETCHED + dt.timedelta(days=14))
    html15, st = blk(fixture_snapshot("crvUSD"), FETCHED + dt.timedelta(days=15))
    assert old not in html14 and st["age_days"] == 15
    assert f"by this pipeline.{old}</p>" in html15


def test_webacy_stale_flags_get_the_webacy_suffix():
    suffix = " — Webacy marks this data stale"
    fresh, _ = blk(fixture_snapshot("LUSD"))
    assert suffix not in fresh
    for kw in ({"stale": True}, {"hci_stale": True}):
        html, st = blk(fixture_snapshot("LUSD", **kw))
        assert f"by this pipeline.{suffix}</p>" in html
        assert st["depeg_stale"] or st["hci_stale"]


# ---- the site build -----------------------------------------------------------------------

def test_the_block_lands_and_a_second_build_is_byte_identical(tmp_path):
    root = tmp_repo(tmp_path, {t: fixture_snapshot(t) for t in TOKENS})
    out = site.build(root, FETCHED)
    first = files(root)
    site.build(root, FETCHED)
    assert files(root) == first
    rec = json.loads(out["site.json"])
    w = wording()
    for t in TOKENS:
        p = page(out, t)
        assert "behavioral tier: pending" not in p and p.count(behavioral.MARK_BEGIN) == 1
        assert w["reader"] in p
        b = rec["tokens"][t]["behavioral"]
        assert b["state"] == "rendered" and b["snapshot"] == \
            f"out/behavioral/{t}/20260915T181626Z.json"
        rw = rec["tokens"][t]["rewrites"]["index.html"]
        assert rw["before"][:8] == P902_BEFORE[t] and len(rw["substitutions"]) == 6
        spec = '<h2 class="specialists">Detail for specialists</h2>\n'
        assert p.index(behavioral.MARK_END) < p.index('<section id="check">') < p.index(spec)
        assert spec + "\n<details" in p                           # R4: the literal's line gone
        for n in ("appendix.html", "verify.html", "data/table.json"):
            assert first[f"out/site/{t}/{n}"] == (REPO / f"out/site/{t}/{n}").read_bytes()
    assert rec["behavioral_as_of"] == "2026-09-15"
    method = out["methodology.html"].decode()
    from markupsafe import escape
    assert "<h2>The behavioral tier</h2>" in method
    assert str(escape(w["methodology_reader"])) in method
    assert "out/behavioral/LUSD/20260915T181626Z.json" in method


def test_no_snapshot_keeps_the_pending_text_and_records_it(tmp_path):
    root = tmp_repo(tmp_path, {t: fixture_snapshot(t) for t in TOKENS})
    site.build(root, FETCHED)
    shutil.rmtree(root / "out/behavioral")
    out = site.build(root, FETCHED)
    rec = json.loads(out["site.json"])
    for t in TOKENS:
        p = page(out, t)
        assert p.count('<p class="meta">behavioral tier: pending</p>') == 1
        assert behavioral.MARK_BEGIN not in p and wording()["reader"] not in p
        assert rec["tokens"][t]["behavioral"] == {"state": "pending", "snapshot": None}
        assert rec["tokens"][t]["rewrites"]["index.html"]["before"][:8] == P902_BEFORE[t]
    assert "What is not covered yet" in out["methodology.html"].decode()


def test_a20_either_or_in_both_directions():
    import tomllib
    w = tomllib.loads((REPO / "templates/wording.toml").read_text(encoding="utf-8"))
    html, _ = blk(fixture_snapshot("GHO"))
    lit = '<p class="meta">behavioral tier: pending</p>'
    site.either_or(f"x {lit} y", w, False, "GHO")
    site.either_or(f"x {html} y", w, True, "GHO")
    for text, landed in ((f"{lit}{html}", True), (f"{lit}{html}", False),     # both
                         ("x y", True), ("x y", False),                         # neither
                         (f"x {lit} y", True), (f"x {html} y", False)):         # wrong one
        with pytest.raises(site.SiteStop, match="A-20 either/or"):
            site.either_or(text, w, landed, "GHO")
    bare = html.replace("Behavioral data: Webacy", "Data")
    with pytest.raises(site.SiteStop, match="without its attribution line"):
        site.either_or(f"x {bare} y", w, True, "GHO")


def test_a_snapshot_that_does_not_validate_stops_the_site_build(tmp_path):
    bad = fixture_snapshot("LUSD")
    del bad["depeg"]["body"]["snapshot"]["price"]
    root = tmp_repo(tmp_path, {t: fixture_snapshot(t) for t in ("crvUSD", "GHO")} | {"LUSD": bad})
    before = files(root)
    with pytest.raises(site.SiteStop, match="LUSD: snapshot .* does not validate"):
        site.build(root, FETCHED)
    assert files(root) == before


def test_factory_site_makes_no_network_call(tmp_path, monkeypatch):
    root = tmp_repo(tmp_path, {t: fixture_snapshot(t) for t in TOKENS})

    def refuse(*a, **k):
        raise AssertionError("network call from factory.site")
    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    site.build(root, FETCHED)


# ---- the fetch (fake transport) -----------------------------------------------------------

def fake_get(bodies: dict[str, dict], seen: list):
    def get(url, key):
        seen.append((url, key))
        body = next(v for k, v in bodies.items() if k in url)
        return {"fetched_at": "2026-09-24T12:00:00+00:00", "url": url, "status": 200,
                "seconds": 0.5, "rate_headers": {"X-RateLimit-Limit": "6000",
                                                 "X-RateLimit-Remaining": "5990",
                                                 "X-RateLimit-Reset": "60", "Set-Cookie": "s"},
                "body": json.loads(json.dumps(body))}
    return get


def fetch_bodies(covered: str | None = None) -> dict[str, dict]:
    a = addresses()
    bodies = {f"/rwa/{a[t]}?": fixture(f"{t}_depeg.json")["body"] for t in TOKENS}
    bodies |= {f"/rwa/supply/{t}": {"token": {"symbol": t, "addresses": {"eth": a[t].lower()},
                                              "net_7d": -52067.85, "net_7d_pct": -0.002,
                                              "minted_7d": 0, "chains": {"eth": 1.0}},
                                    "stale": False} for t in TOKENS}
    data = [entry_for(a[covered])] if covered else []
    bodies["/rwa/hci"] = {"data": data, "meta": {"generatedAt": "2026-09-24T03:00:00Z",
                                                 "stale": False, "page": 1, "totalPages": 1}}
    return bodies


def test_fetch_makes_seven_requests_and_never_writes_the_key(tmp_path):
    root = tmp_repo(tmp_path)
    key = "wk_live_" + "9" * 24
    seen, gaps = [], []
    r = behavioral.fetch(root, key, get=fake_get(fetch_bodies("GHO"), seen), sleep=gaps.append,
                         now=dt.datetime(2026, 9, 24, 12, tzinfo=dt.UTC))
    assert len(seen) == 7 and gaps == [behavioral.GAP_S] * 6
    assert "pageSize=500" in seen[-1][0] and not any("/v3/" in u for u, _ in seen)
    assert r["written"]["GHO"]["hci_found"] and not r["written"]["LUSD"]["hci_found"]
    written = list((root / "out").rglob("20260924T120000Z.json"))
    assert len(written) == 6
    for p in written:
        assert key not in p.read_text(encoding="utf-8")
        assert "x-api-key" not in p.read_text(encoding="utf-8").lower()
    for t in TOKENS:
        snap = json.loads((root / f"out/behavioral/{t}/20260924T120000Z.json").read_text("utf-8"))
        assert outside(snap, SNAPSHOT) == []
        assert "Set-Cookie" not in snap["depeg"]["request"]["rate_headers"]


def test_a_shape_mismatch_or_a_non_200_writes_nothing(tmp_path):
    root = tmp_repo(tmp_path)
    bodies = fetch_bodies()
    del bodies[f"/rwa/{addresses()['GHO']}?"]["snapshot"]["price"]
    with pytest.raises(behavioral.BehavioralStop, match="response shape"):
        behavioral.fetch(root, "k", get=fake_get(bodies, []), sleep=lambda s: None)
    assert not (root / "out/behavioral").exists() and not (root / "out/behavioral-raw").exists()

    def refused(url, key):
        raise behavioral.BehavioralStop(f"{url} -> HTTP 401")
    with pytest.raises(behavioral.BehavioralStop, match="HTTP 401"):
        behavioral.fetch(root, "k", get=refused, sleep=lambda s: None)
    assert not (root / "out/behavioral").exists()


# ---- the Step 8 rule: no Anthropic ----------------------------------------------------------

def test_behavioral_and_site_neither_import_anthropic_nor_read_its_key(tmp_path):
    for mod in ("behavioral.py", "site.py"):
        assert "anthropic" not in (REPO / "src/factory" / mod).read_text(encoding="utf-8").lower()
    root = tmp_repo(tmp_path, {t: fixture_snapshot(t) for t in TOKENS})
    code = (
        "import os, sys, datetime, pathlib\n"
        "class Env(dict):\n"
        "    reads = []\n"
        "    def get(self, k, d=None):\n"
        "        Env.reads.append(k); return super().get(k, d)\n"
        "    def __getitem__(self, k):\n"
        "        Env.reads.append(k); return super().__getitem__(k)\n"
        "os.environ = Env(os.environ)\n"
        "from factory import behavioral, site\n"
        f"site.build(pathlib.Path(r'{root}'), datetime.date(2026, 9, 15))\n"
        "assert 'anthropic' not in sys.modules, 'anthropic imported'\n"
        "assert not [k for k in Env.reads if 'ANTHROPIC' in k], Env.reads\n"
        "print('ok')\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith("ANTHROPIC")}
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr


@pytest.mark.skipif(not (REPO / "out/behavioral-raw").exists(),
                    reason="full envelopes are gitignored (P5)")
def test_each_committed_snapshot_re_derives_from_its_raw_file():
    for raw in sorted((REPO / "out/behavioral-raw").glob("*/*.json")):
        token = raw.parent.name
        committed = REPO / "out/behavioral" / token / raw.name
        assert json.loads(committed.read_text(encoding="utf-8")) == \
            behavioral.retrim(REPO, raw, token)


# ---- R1-R3 and R11 ------------------------------------------------------------------------

def test_liquidity_card_shows_total_and_depth_or_not_reported():
    snap = fixture_snapshot("crvUSD")
    s = snap["depeg"]["body"]["snapshot"]
    s.update(total_dex_liquidity_usd=336968902.44, liquidity_depth_tier="deep",
             cost_to_move_up_usd=1.0e9, cost_to_move_down_usd=2.0e47)
    html, st = blk(snap)
    assert cards_of(html)["DEX liquidity"] == ("$337.0M", "depth deep") and st["liquidity_shown"]
    assert "cost to move" not in html.lower()                    # undocumented: stored only
    s.update(total_dex_liquidity_usd=None, liquidity_depth_tier=None)
    html, st = blk(snap)
    assert cards_of(html)["DEX liquidity"] == ("not reported by Webacy", None)   # card stays
    assert not st["liquidity_shown"]


def test_supply_card_is_signed_its_tip_names_the_base_and_a_mismatch_shows_nothing():
    a = addresses()["crvUSD"]
    html, st = blk(fixture_snapshot("crvUSD", supply=supply_unit(a.upper().replace("0X", "0x"))))
    assert cards_of(html)["Supply change, 7 days"] == ("+$23.8M", "+10.4%")
    assert "the % is of Webacy&#x27;s circulating supply 7 days earlier ($229.1M)." in html
    assert st["supply_shown"] and st["supply_base"] == "$229.1M"                # R8, R16
    html, _ = blk(fixture_snapshot("crvUSD", supply=supply_unit(a, -52067.85, -0.002,
                                                                  26289846.26)))
    assert cards_of(html)["Supply change, 7 days"] == ("−$52.1k", "−0.2%")
    html, _ = blk(fixture_snapshot("crvUSD", supply=supply_unit(a, supply=None)))
    assert cards_of(html)["Supply change, 7 days"] == ("+$23.8M", None)       # no base: no %
    other = "0x" + "1" * 40
    html, st = blk(fixture_snapshot("crvUSD", supply=supply_unit(other)))
    assert cards_of(html)["Supply change, 7 days"] == ("not reported by Webacy", None)
    assert not st["supply_shown"] and st["supply_not_shown"].startswith("address mismatch: ")
    assert "Net supply change" not in html                          # no bars either


def test_a_known_note_joins_the_note_line_and_an_unknown_one_is_recorded_only():
    note = "all_top_n_are_protocol_contracts_organic_low"
    html, st = blk(fixture_snapshot("GHO", covered=True, note=note))
    sentence = "Webacy counts the largest holders as protocol contracts, so it rates " \
               "concentration as low."
    exceeds = ("Webacy&#x27;s figure exceeds the token&#x27;s total supply ($699.0M); "
               "shown as given.")
    assert f'</div>\n<p class="meta">{exceeds} {sentence}</p>' in html        # one line, R11
    assert st["notes"] == [note] and st["unknown_notes"] == []
    html, st = blk(fixture_snapshot("GHO", covered=True, note="brand_new_note"))
    assert sentence not in html and "brand_new_note" not in html
    assert st["unknown_notes"] == ["brand_new_note"] and st["notes"] == []


def test_the_reader_sentence_names_four_things_only_when_liquidity_and_supply_render(tmp_path):
    w = wording()
    snaps = {}
    for t in TOKENS:
        s = fixture_snapshot(t, supply=supply_unit(addresses()[t]))
        s["depeg"]["body"]["snapshot"].update(total_dex_liquidity_usd=1e6,
                                             liquidity_depth_tier="deep")
        snaps[t] = s
    snaps["LUSD"]["depeg"]["body"]["snapshot"]["total_dex_liquidity_usd"] = None
    out = site.build(tmp_repo(tmp_path, snaps), FETCHED)
    assert w["reader_full"] in page(out, "crvUSD")                  # pair (ii): raw text
    assert w["reader"] in page(out, "LUSD") and w["reader_full"] not in page(out, "LUSD")


# ---- R6-R7 --------------------------------------------------------------------------------

def test_markets_table_top_10_by_liquidity_or_not_reported():
    html, st = blk(fixture_snapshot("crvUSD"))
    assert "<summary>DEX pools, top 10 by liquidity</summary>" in html and st["markets"] == 10
    rows = re.findall(r"<tr><td class=\"num\">(\d+)</td>", html)
    assert rows == [str(i) for i in range(1, 11)]
    assert html.count("<code title=\"0x") == 10
    assert "†" not in html and st["daggers"] == 0
    html, st = blk(fixture_snapshot("LUSD"))                     # the probe's list is empty
    assert "DEX pools: not reported by Webacy" in html and st["markets"] == 0
    snap = fixture_snapshot("LUSD")
    snap["depeg"]["body"]["token"]["markets"] = None
    assert "DEX pools: not reported by Webacy" in blk(snap)[0]


def test_liquidity_above_webacys_supply_is_noted_and_the_pool_daggered_on_gho():
    note = "Webacy&#x27;s figure exceeds the token&#x27;s total supply ($699.0M); shown as given"
    html, st = blk(fixture_snapshot("GHO"))
    assert f'<p class="meta">{note}.</p>' in html
    assert st["liquidity_exceeds_supply"] and st["daggers"] == 1
    assert "$4.0B †</td>" in html and f'<p class="meta">† {note}</p>' in html
    assert "<code title=\"0xdde30ed2ddd2b6a6faca9b81e6a1571eb9c375b6b0521c4ecc6be627cf87a5a6\">" \
           "0xdde3…a5a6</code>" in html                          # a v4 id: shortened, no link
    for t in ("crvUSD", "LUSD"):
        h, s = blk(fixture_snapshot(t))
        assert not s["liquidity_exceeds_supply"] and "exceeds the token" not in h


# ---- R12-R16 (third review) ---------------------------------------------------------------

def pools(n: int, big: int | None = None) -> list[dict]:
    out = [{"dex": "curve", "pair": f"X/P{i}", "pool_address": "0x" + f"{i:040x}",
            "liquidity_usd": 1000.0 * (n - i), "volume_24h_usd": 1.0} for i in range(n)]
    if big is not None:
        out[big]["liquidity_usd"] = 5e12
    return out


def test_donut_excludes_daggered_pools_and_caps_at_six_slices():
    snap = fixture_snapshot("GHO")
    snap["depeg"]["body"]["token"]["markets"] = pools(9, big=0)
    html, st = blk(snap)
    assert st["donut_slices"] == 6 and st["donut_excluded"] == 1
    assert "other listed pools" in html and "X/P0" not in re.sub(r"<table.*</table>", "", html,
                                                                 flags=re.S)
    assert "Share of liquidity among the 8 Ethereum pools Webacy lists, $36.0k — excludes 1 " \
           "pool whose reported liquidity exceeds the token&#x27;s supply" in html
    snap["depeg"]["body"]["token"]["markets"] = pools(4)
    html, st = blk(snap)
    assert st["donut_slices"] == 4 and "other listed pools" not in html
    dup = pools(3)
    dup[2]["pair"] = dup[0]["pair"]
    snap["depeg"]["body"]["token"]["markets"] = dup
    html, _ = blk(snap)
    assert "X/P0 0x0000…0000" in html and "X/P0 0x0000…0002" in html        # repeated pair


def test_lusd_has_no_donut_and_keeps_its_six_cards():
    html, st = blk(fixture_snapshot("LUSD"))
    assert st["donut_slices"] == 0 and "Share of liquidity among" not in html
    assert len(cards_of(html)) == 6


def test_supply_bars_omit_a_null_window_and_name_it():
    a = addresses()["crvUSD"]
    unit = supply_unit(a)
    unit["body"]["token"].update(net_30d=-67400920.62, net_90d=63991346.87)
    html, st = blk(fixture_snapshot("crvUSD", supply=unit))
    assert st["supply_bars"] == 3 and "Net supply change, per Webacy</figcaption>" in html
    assert "−$67.4M" in html and "+$64.0M" in html
    unit["body"]["token"]["net_30d"] = None
    html, st = blk(fixture_snapshot("crvUSD", supply=unit))
    assert st["supply_bars"] == 2
    assert "Net supply change, per Webacy — no figure for 30 days</figcaption>" in html


def test_holder_bar_three_segments_or_skipped_without_top30():
    html, st = blk(fixture_snapshot("GHO", covered=True))
    assert st["holder_bar"] and st["holder_segments"] == ["61.3%", "18.8%", "20.0%"]
    assert "Share of supply held, 12,345 holders</figcaption>" in html
    snap = fixture_snapshot("GHO", covered=True)
    snap["hci"]["entry"]["holderConcentration"]["top30"] = None
    html, st = blk(snap)
    assert not st["holder_bar"] and "Share of supply held, " not in html
    assert not blk(fixture_snapshot("GHO"))[1]["holder_bar"]            # no HCI entry


def test_dex_names_map_to_display_names_and_an_unmapped_one_prints_as_given():
    snap = fixture_snapshot("GHO")
    ms = snap["depeg"]["body"]["token"]["markets"]
    ms[1]["dex"] = "some_new_dex"
    html, _ = blk(snap)
    assert "<td>Uniswap v4</td>" in html and "<td>some_new_dex</td>" in html
    assert "uniswap-v4-ethereum" not in html


def test_every_chart_carries_the_aria_label_and_title_pattern():
    a = addresses()["GHO"]
    html, st = blk(fixture_snapshot("GHO", covered=True, supply=supply_unit(a)))
    svgs = re.findall(r"<svg [^>]*>", html)
    assert len(svgs) == 4 and len(st["captions"]) == 4
    for s in svgs:
        assert 'role="img" aria-label="' in s
    assert html.count("<title>") == 4


def test_methodology_records_that_hci_history_is_not_offered(tmp_path):
    from markupsafe import escape
    out = site.build(tmp_repo(tmp_path, {t: fixture_snapshot(t) for t in TOKENS}), FETCHED)
    assert str(escape(wording()["hci_history"])) in out["methodology.html"].decode()
