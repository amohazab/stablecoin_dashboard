"""Step 8 phase A (P-8.01): the behavioral tier, fetched from Webacy.

`uv run python -m factory.behavioral` - no RPC, no arguments. Reads `WEBACY_API_KEY`
(environment, then `.env`) and each token's contract address from its roots config, makes
3 x `/rwa/{address}?chain=eth&hours=168`, 3 x `/rwa/supply/{symbol}` and
`/rwa/hci?chain=eth&pageSize=500` (further pages only while a token is unfound and pages
remain, cap 6), 1.1 s apart, and writes per token:
- `out/behavioral/<T>/<stamp>.json` (committed): the trimmed snapshot (P5) - only the
  rendered inputs, each request's {fetched_at, url, status, seconds, X-RateLimit-*} and
  the sha256 of each full response body;
- `out/behavioral-raw/<T>/<stamp>.json` (gitignored): the full envelopes.
The key is sent as the `x-api-key` header and never written. A non-200 status or a
response whose consumed paths do not validate stops the run before anything is written.
`factory.site` renders the block from the latest committed snapshot and never fetches.

NAMED DEFAULTS (P-8.01 P6 and this module):
- `<stamp>` is ISO-8601 basic UTC, `YYYYMMDDTHHMMSSZ` (no colons: Windows paths).
- `body_sha256` is the sha256 of the body as canonical JSON (sorted keys, no spaces), so
  it reproduces from the raw file; fixtures also carry `source_sha256`, the probe file's.
- HCI entries are matched by lowercase contract address, never by symbol.
- A timestamp without a zone suffix is UTC.
- Figures are formatted here (4 d.p. price, signed 1 d.p. bp with U+2212, integer score);
  `render.Formatter` owns table figures, and A-20 exempts this block from DET-84/DET-89.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import re
import sys
import time
import tomllib
from decimal import ROUND_HALF_UP, Decimal
from html import escape

from pydantic import BaseModel, ConfigDict

BASE = "https://api.webacy.com"
# token -> (roots config file, root id) : the address is read, never restated here
ROOTS = {"crvUSD": ("discovery_roots.toml", "crvusd_token"),
         "GHO": ("gho_roots.toml", "gho_token"),
         "LUSD": ("lusd_roots.toml", "lusd_token")}
RATE = ("X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset")
GAP_S = 1.1
HCI_PAGE_SIZE = 500
HCI_PAGE_CAP = 6
MARK_BEGIN = "<!-- behavioral:begin -->"
MARK_END = "<!-- behavioral:end -->"


class BehavioralStop(Exception):
    """A fetch that cannot be recorded: nothing is written."""


# ---- the consumed shape (a mismatch stops the fetch and the site build) ----------------

class _M(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Snap(_M):
    ts: str
    price: float
    peg_value: float
    dev_clean: float
    score: float | None
    tier: str | None
    total_dex_liquidity_usd: float | None = None
    cost_to_move_up_usd: float | None = None
    cost_to_move_down_usd: float | None = None
    liquidity_depth_tier: str | None = None


class Point(_M):
    ts: str
    price: float
    peg_value: float


class History(_M):
    series: list[Point]


class Market(_M):
    dex: str | None = None
    pair: str | None = None
    pool_address: str | None = None
    liquidity_usd: float | None = None
    volume_24h_usd: float | None = None


class DepegToken(_M):
    total_supply_on_chain: float | None = None
    markets: list[Market] | None = None


class DepegBody(_M):
    snapshot: Snap
    history: History
    stale: bool
    token: DepegToken | None = None


class Cohort(_M):
    index: float
    topSharePct: float
    riskBand: str
    note: str | None = None


class HolderConc(_M):
    top10: Cohort
    top30: Cohort
    holderCount: int


class HciEntry(_M):
    chain: str
    address: str
    symbol: str
    name: str
    holderConcentration: HolderConc


class SupplyAddresses(_M):
    eth: str | None = None


class SupplyToken(_M):
    symbol: str
    addresses: SupplyAddresses
    supply: float | None = None
    net_7d: float | None = None
    net_7d_pct: float | None = None
    net_30d: float | None = None
    net_90d: float | None = None


class SupplyBody(_M):
    token: SupplyToken | None
    stale: bool = False


class HciMeta(_M):
    generatedAt: str
    stale: bool
    page: int
    totalPages: int = 1


class HciBody(_M):
    data: list[HciEntry]
    meta: HciMeta


def validate_hci(body: dict, addresses) -> list[HciEntry]:
    """Amin, 4 Oct (B): the HCI page's meta and the entries of OUR three addresses are
    validated strictly; the other tokens' entries only need an address. Webacy began
    returning `top30: null` for some other tokens (1-3 Oct), which failed the whole page."""
    HciMeta.model_validate(body["meta"])
    want = {a.lower() for a in addresses}
    if not isinstance(body.get("data"), list):
        raise ValueError("HCI data is not a list")
    out = []
    for e in body["data"]:
        if not isinstance(e, dict) or not isinstance(e.get("address"), str):
            raise ValueError("HCI entry without an address")
        if e["address"].lower() in want:
            out.append(HciEntry.model_validate(e))
    return out


# ---- trimming (P5): the one function for live fetches and fixtures ---------------------

def body_sha256(body) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


MARKET_KEYS = ("dex", "pair", "pool_address", "liquidity_usd", "volume_24h_usd")


def trim_request(env: dict) -> dict:
    return {"fetched_at": env["fetched_at"], "url": env["url"], "status": env["status"],
            "seconds": env["seconds"],
            "rate_headers": {k: env["rate_headers"][k] for k in RATE if k in env["rate_headers"]},
            "body_sha256": body_sha256(env["body"])}


def trim_depeg(env: dict) -> dict:
    b = DepegBody.model_validate(env["body"])
    s = env["body"]["snapshot"]
    return {"request": trim_request(env), "body": {
        "snapshot": {k: s.get(k) for k in ("ts", "price", "peg_value", "dev_clean", "score", "tier",
                                             "total_dex_liquidity_usd", "cost_to_move_up_usd",
                                             "cost_to_move_down_usd", "liquidity_depth_tier")},
        "history": {"series": [{k: p[k] for k in ("ts", "price", "peg_value")}
                               for p in env["body"]["history"]["series"]]},
        "stale": b.stale,
        "token": {"total_supply_on_chain": None if b.token is None
                  else b.token.total_supply_on_chain,
                  "markets": None if b.token is None or b.token.markets is None else [
                      m.model_dump(include=set(MARKET_KEYS)) for m in b.token.markets]}}}


def trim_entry(e: dict) -> dict:
    """An HCI entry's consumed keys only (P5), each cohort's `note` kept when present (R3)."""
    h = e["holderConcentration"]
    cohort = lambda c: {k: c[k] for k in ("index", "topSharePct", "riskBand", "note")  # noqa: E731
                        if k in c}
    return {**{k: e[k] for k in ("chain", "address", "symbol", "name")},
            "holderConcentration": {"top10": cohort(h["top10"]), "top30": cohort(h["top30"]),
                                    "holderCount": h["holderCount"]}}


def trim_hci(env: dict, addresses) -> dict:
    """One HCI page: meta {generatedAt, stale, page} and only the entries of
    `addresses` (lowercase) - the other tokens' entries are not carried."""
    validate_hci(env["body"], addresses)                       # Amin, 4 Oct (B)
    m = env["body"]["meta"]
    want = {a.lower() for a in addresses}
    return {"request": trim_request(env), "body": {
        "meta": {k: m[k] for k in ("generatedAt", "stale", "page")},
        "data": [trim_entry(e) for e in env["body"]["data"] if e["address"].lower() in want]}}


def trim_supply(env: dict) -> dict:
    """R2/R13: the returned row's symbol and Ethereum address (the collision check), its
    supply and the 7/30/90-day net changes; net_24h and the rest stay in the raw file."""
    b = SupplyBody.model_validate(env["body"])
    tok = None if b.token is None else {
        "symbol": b.token.symbol, "addresses": {"eth": b.token.addresses.eth},
        "supply": b.token.supply, "net_7d": b.token.net_7d, "net_7d_pct": b.token.net_7d_pct,
        "net_30d": b.token.net_30d, "net_90d": b.token.net_90d}
    return {"request": trim_request(env), "body": {"token": tok, "stale": b.stale}}


def trim_fixture(kind: str, raw: bytes, addresses=()) -> dict:
    env = json.loads(raw)
    t = trim_depeg(env) if kind == "depeg" else trim_hci(env, addresses)
    return {"source_sha256": hashlib.sha256(raw).hexdigest(), **t}


def retrim(repo: pathlib.Path, raw_path: pathlib.Path, token: str) -> dict:
    """The committed snapshot re-derived from its gitignored raw file (same functions)."""
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    a = addresses(repo)[token]
    return assemble(token, a, trim_depeg(raw["depeg"]), trim_supply(raw["supply"]),
                    [trim_hci(e, [a]) for e in raw["hci"]])


def assemble(token: str, address: str, depeg: dict, supply: dict | None,
             hci_pages: list[dict]) -> dict:
    """The committed per-token snapshot from trimmed units."""
    entry, meta = None, hci_pages[-1]["body"]["meta"]
    for pg in hci_pages:
        hit = [e for e in pg["body"]["data"] if e["address"].lower() == address.lower()]
        if hit:
            entry, meta = hit[0], pg["body"]["meta"]
            break
    return {"token": token, "address": address, "depeg": depeg, "supply": supply,
            "hci": {"requests": [pg["request"] for pg in hci_pages],
                    "meta": {k: meta[k] for k in ("generatedAt", "stale", "page")},
                    "entry": entry}}


# ---- reading -----------------------------------------------------------------------------

def parse_ts(s: str) -> dt.datetime:
    d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=dt.UTC)


def latest(repo: pathlib.Path, token: str) -> pathlib.Path | None:
    files = sorted((repo / "out/behavioral" / token).glob("*.json"))
    return files[-1] if files else None


def load(path: pathlib.Path) -> dict:
    snap = json.loads(path.read_text(encoding="utf-8"))
    DepegBody.model_validate(snap["depeg"]["body"])
    if snap["hci"]["entry"] is not None:
        HciEntry.model_validate(snap["hci"]["entry"])
    return snap


def series_bp(snap: dict) -> list[tuple[dt.datetime, Decimal]]:
    """Signed deviation (price - peg_value) x 10^4, oldest -> newest."""
    pts = [(parse_ts(p["ts"]), (Decimal(str(p["price"])) - Decimal(str(p["peg_value"]))) * 10000)
           for p in snap["depeg"]["body"]["history"]["series"]]
    return sorted(pts, key=lambda x: x[0])


# ---- the block ---------------------------------------------------------------------------

def _q(x, places: str) -> Decimal:
    """Half-up, as svg.py rounds."""
    return Decimal(str(x)).quantize(Decimal(places), ROUND_HALF_UP)


def _bp(x: Decimal) -> str:
    v = _q(x, "0.1")
    return ("−" if v < 0 else "+" if v > 0 else "") + f"{abs(v):.1f}"


def state(snap: dict, as_of: dt.date, w: dict) -> dict:
    fetched = parse_ts(snap["depeg"]["request"]["fetched_at"]).astimezone(dt.UTC)
    age = (as_of - fetched.date()).days
    depeg_stale = bool(snap["depeg"]["body"]["stale"])
    hci_stale = bool(snap["hci"]["meta"]["stale"])
    suffixes = []
    if age > w["stale_days"]:
        suffixes.append(w["suffix_old"].format(days=w["stale_days"]))
    if depeg_stale or hci_stale:
        suffixes.append(w["suffix_webacy"])
    return {"fetched_at": snap["depeg"]["request"]["fetched_at"],
            "fetched": fetched.strftime("%Y-%m-%d %H:%M"), "as_of": as_of.isoformat(),
            "age_days": age, "depeg_stale": depeg_stale, "hci_stale": hci_stale,
            "suffixes": suffixes}


def _signed(x: Decimal, text: str) -> str:
    return ("−" if x < 0 else "+" if x > 0 else "") + text


def _pct(x: Decimal) -> str:
    return f"{_q(x, '0.1'):.1f}%"


def _supply_cap(snap: dict) -> float | None:
    return ((snap["depeg"]["body"].get("token") or {}).get("total_supply_on_chain"))


def _short(pool: str) -> str:
    return f"{pool[:6]}…{pool[-4:]}" if len(pool) > 12 else pool or "—"


def _tip(text: str) -> str:
    t = escape(text)
    return (f'<span class="tip" tabindex="0" role="button" aria-label="{t}">?'
            f'<span class="tip-text" role="tooltip">{t}</span></span>')


def _card(label: str, tip: str, value: str, note: str | None) -> str:
    """The reader layer's stat card (index.html.j2's `.card`), with its "?" tooltip."""
    return (f'  <div class="card"><div class="card-label">{escape(label)} {_tip(tip)}</div>'
            f'<div class="card-value">{escape(value)}</div>'
            + (f'<div class="card-note">{escape(note)}</div>' if note else "") + "</div>")


def _supply_token(snap: dict) -> tuple[dict | None, str | None]:
    """R2: the /rwa/supply row, only when its Ethereum address is the token's."""
    tok = (((snap.get("supply") or {}).get("body") or {}).get("token"))
    if not tok:
        return None, "no supply row"
    if (tok["addresses"].get("eth") or "").lower() != snap["address"].lower():
        return None, f"address mismatch: {tok['addresses'].get('eth')} ({tok['symbol']})"
    return tok, None


def _markets(snap: dict) -> list[dict]:
    ms = (snap["depeg"]["body"].get("token") or {}).get("markets") or []
    return sorted(ms, key=lambda m: -(m.get("liquidity_usd") or 0))


def _over(m: dict, cap: float | None) -> bool:
    return cap is not None and m.get("liquidity_usd") is not None and m["liquidity_usd"] > cap


def cards(snap: dict, w: dict, usd) -> tuple[str, list[str], dict]:
    """R11: six cards - peg price, deviation, score, DEX liquidity, supply change 7d,
    top-10 holder share; a null field's card reads "not reported by Webacy"."""
    s = snap["depeg"]["body"]["snapshot"]
    c, nr = w["cards"], w["not_reported"]
    dev = Decimal(str(s["dev_clean"])) * 10000
    score = "—" if s["score"] is None else str(int(round(s["score"])))
    out = [_card(c["price"], c["price_tip"], f'{_q(s["price"], "0.0001")}', None),
           _card(c["deviation"], c["deviation_tip"], f"{_bp(dev)} bp", None),
           _card(c["score"], c["score_tip"], f"{score} of 100", f'tier {s["tier"] or "—"}')]
    rec: dict = {}
    notes: list[str] = []
    liq, tier = s.get("total_dex_liquidity_usd"), s.get("liquidity_depth_tier")
    rec["liquidity_shown"] = liq is not None and tier is not None
    cap = _supply_cap(snap)
    rec["liquidity_exceeds_supply"] = rec["liquidity_shown"] and cap is not None and liq > cap
    out.append(_card(c["liquidity"], c["liquidity_tip"], usd(liq) if rec["liquidity_shown"] else nr,
                     f'depth {tier.replace("_", " ")}' if rec["liquidity_shown"] else None))
    if rec["liquidity_exceeds_supply"]:
        notes.append(w["exceeds_supply"].format(supply=usd(cap)) + ".")        # R7
    tok, why = _supply_token(snap)
    net = None if tok is None or tok.get("net_7d") is None else Decimal(str(tok["net_7d"]))
    rec["supply_shown"], rec["supply_not_shown"] = net is not None, why
    sub, tip = None, c["supply_tip"]
    if net is not None and tok.get("net_7d_pct") is not None and tok.get("supply") is not None:
        pct = _q(Decimal(str(tok["net_7d_pct"])) * 100, "0.1")                 # R8, R16
        base = Decimal(str(tok["supply"])) - net
        sub = _signed(pct, f"{abs(pct):.1f}%")
        tip = c["supply_tip_base"].format(base=usd(base))
        rec["supply_base"] = usd(base)
    out.append(_card(c["supply"], tip, _signed(net, usd(abs(net))) if net is not None else nr, sub))
    e = snap["hci"]["entry"]
    rec["hci_found"] = e is not None
    rec["notes"], rec["unknown_notes"] = [], []
    if e is None:
        out.append(_card(c["holders"], c["holders_tip"], w["not_covered_value"], None))
    else:
        h = e["holderConcentration"]
        share = _pct(Decimal(str(h["top10"]["topSharePct"])))
        band = f'risk band {h["top10"]["riskBand"]}'
        out.append(_card(c["holders"], c["holders_tip"], share, band))
        for n in dict.fromkeys(x.get("note") for x in (h["top10"], h["top30"])
                               if x and x.get("note")):
            (rec["notes"] if n in w["notes"] else rec["unknown_notes"]).append(n)
        notes += [w["notes"][n] for n in rec["notes"]]                         # R3
    return '<div class="cards">\n' + "\n".join(out) + "\n</div>", notes, rec


def donut_figure(snap: dict, w: dict, usd) -> tuple[str | None, dict]:
    """R12: the listed pools less any above Webacy's supply; top 5 plus one "other listed
    pools" slice; a pair listed twice carries its short pool id."""
    from factory.report.svg import donut
    cap = _supply_cap(snap)
    ms = _markets(snap)
    kept = [m for m in ms if not _over(m, cap) and (m.get("liquidity_usd") or 0) > 0]
    excluded = len(ms) - len([m for m in ms if not _over(m, cap)])
    if not kept:
        return None, {"donut_slices": 0, "donut_excluded": excluded}
    pairs = [m.get("pair") or "—" for m in ms]
    total = sum(Decimal(str(m["liquidity_usd"])) for m in kept)

    def label(m):
        p = m.get("pair") or "—"
        return f"{p} {_short(m.get('pool_address') or '')}" if pairs.count(p) > 1 else p
    head = kept[:5] if len(kept) > 6 else kept
    slices = [(label(m), Decimal(str(m["liquidity_usd"]))) for m in head]
    if len(kept) > 6:
        slices.append((w["donut_other"], sum(Decimal(str(m["liquidity_usd"])) for m in kept[5:])))
    rows = [(lab, v / total, f"{usd(v)} · {_pct(v / total * 100)}") for lab, v in slices]
    cap_text = w["donut_caption"].format(n=len(kept), sum=usd(total))
    if excluded:
        cap_text += w["donut_excluded"].format(k=excluded, s="" if excluded == 1 else "s")
    svg = donut(rows, w["donut_title"])
    return (f'<figure class="half">{svg}<figcaption>{escape(cap_text)}</figcaption></figure>',
            {"donut_slices": len(rows), "donut_excluded": excluded, "donut_caption": cap_text})


def supply_figure(snap: dict, w: dict, usd) -> tuple[str | None, dict]:
    """R13: net 7d / 30d / 90d as signed bars; a null window is omitted and named."""
    from factory.report.svg import signed_bars
    tok, _ = _supply_token(snap)
    if tok is None:
        return None, {"supply_bars": 0}
    bars, missing = [], []
    for key, lab in w["supply_windows"]:
        v = tok.get(key)
        if v is None:
            missing.append(lab)
        else:
            d = Decimal(str(v))
            bars.append((lab, d, _signed(d, usd(abs(d)))))
    if not bars:
        return None, {"supply_bars": 0}
    cap_text = w["supply_caption"] + (w["supply_missing"].format(windows=", ".join(missing))
                                      if missing else "")
    svg = signed_bars(bars, w["supply_title"])
    return (f'<figure class="half">{svg}<figcaption>{escape(cap_text)}</figcaption></figure>',
            {"supply_bars": len(bars), "supply_caption": cap_text})


def holder_figure(snap: dict, w: dict) -> tuple[str | None, dict]:
    """R14: top 10 · holders 11-30 · all others, one stacked bar; skipped without top30."""
    from factory.report.svg import stacked_bar
    e = snap["hci"]["entry"]
    if e is None or e["holderConcentration"].get("top30") is None:
        return None, {"holder_bar": False}
    h = e["holderConcentration"]
    t10 = Decimal(str(h["top10"]["topSharePct"]))
    t30 = Decimal(str(h["top30"]["topSharePct"]))
    segs = [(w["holder_segments"][0], t10), (w["holder_segments"][1], t30 - t10),
            (w["holder_segments"][2], Decimal(100) - t30)]
    rows = [(lab, v / 100, f"{lab}: {_pct(v)}") for lab, v in segs]
    cap_text = w["holder_caption"].format(n=f'{h["holderCount"]:,}')
    svg = stacked_bar(rows, w["holder_title"])
    return (f'<figure class="wide">{svg}<figcaption>{escape(cap_text)}</figcaption></figure>',
            {"holder_bar": True, "holder_caption": cap_text,
             "holder_segments": [_pct(v) for _, v in segs]})


NUM, NUM_COLS = ' class="num"', (0, 3, 4)      # the markets table's numeric columns


def markets_html(snap: dict, w: dict, usd) -> tuple[str, dict]:
    """R6: the Ethereum `markets` list, top 10 by liquidity, collapsed; R7's dagger on a
    pool above Webacy's total supply; R16's DEX display names. Pool ids are shortened,
    never linked (v4 ids are not addresses)."""
    ms = _markets(snap)
    if not ms:
        return f'<p class="meta">{escape(w["markets_none"])}</p>', {"markets": 0, "daggers": 0}
    cap = _supply_cap(snap)
    rows, daggers = [], 0
    for i, m in enumerate(ms[:10], 1):
        liq, dag = m.get("liquidity_usd"), _over(m, cap)
        daggers += dag
        pool = m.get("pool_address") or ""
        dex = m.get("dex") or "—"
        cells = [str(i), w["dex"].get(dex, dex), m.get("pair") or "—",
                 ("—" if liq is None else usd(liq)) + (" †" if dag else ""),
                 "—" if m.get("volume_24h_usd") is None else usd(m["volume_24h_usd"])]
        rows.append("<tr>" + "".join(f"<td{NUM if j in NUM_COLS else ''}>{escape(c)}</td>"
                                     for j, c in enumerate(cells))
                    + f'<td><code title="{escape(pool)}">{escape(_short(pool))}</code></td></tr>')
    head = "".join(f"<th{NUM if j in NUM_COLS else ''}>{escape(h)}</th>"
                   for j, h in enumerate(w["markets_columns"]))
    foot = (f'<p class="meta">† {escape(w["exceeds_supply"].format(supply=usd(cap)))}</p>'
            if daggers else "")
    return (f'<details class="markets"><summary>{escape(w["markets_summary"])}</summary>\n'
            f'<table class="striped"><tr>{head}</tr>\n' + "\n".join(rows) + "\n</table>"
            f"{foot}</details>", {"markets": min(len(ms), 10), "daggers": daggers})


# R15: the two half-width figures sit side by side and stack below ~860px; inline because
# style.css is byte-frozen (P-9.01 D7).
PAIR_OPEN = '<div style="display:flex;flex-wrap:wrap;gap:16px;align-items:flex-start">'
HALF = 'style="flex:1 1 420px;min-width:0;margin:0"'


def block(snap: dict, as_of: dt.date, w: dict, usd) -> tuple[str, dict]:
    """(the marked HTML block, its recorded state). `w` = wording.toml [behavioral];
    `usd` formats a USD amount in the report's compact display rule. R15's order:
    cards, note line, deviation chart, donut + supply bars, holder bar, pools, attribution."""
    from factory.report.svg import deviation_chart
    st = state(snap, as_of, w)
    card_html, notes, rec = cards(snap, w, usd)
    pts = series_bp(snap)
    mx = max(abs(v) for _, v in pts)
    caption = w["chart_caption"].format(n=f"{_q(mx, '0.1'):.1f}")
    lo, hi = min(min(v for _, v in pts), Decimal(0)), max(max(v for _, v in pts), Decimal(0))
    svg = deviation_chart([(t.timestamp(), v) for t, v in pts],
                          y_labels={hi: f"{_bp(hi)} bp", Decimal(0): "0", lo: f"{_bp(lo)} bp"},
                          x_labels=(pts[0][0].strftime("%m-%d %H:%M"),
                                    pts[-1][0].strftime("%m-%d %H:%M")),
                          title=w["chart_title"])
    donut_html, dk = donut_figure(snap, w, usd)
    bars_html, bk = supply_figure(snap, w, usd)
    holder_html, hk = holder_figure(snap, w)
    markets, mk = markets_html(snap, w, usd)
    halves = [x.replace('<figure class="half">', f"<figure {HALF}>")
              for x in (donut_html, bars_html) if x]
    attribution = w["attribution"].format(date=st["fetched"]) + "".join(st["suffixes"])
    parts = [f'{MARK_BEGIN}\n<section class="behavioral" id="behavioral">',
             f'<h2>{escape(w["heading"])} {_tip(w["tip"])}</h2>', card_html]
    if notes:
        parts.append(f'<p class="meta">{escape(" ".join(notes))}</p>')
    parts.append(f'<figure class="wide">{svg}<figcaption>{escape(caption)}</figcaption></figure>')
    if halves:
        parts.append(PAIR_OPEN + "\n" + "\n".join(halves) + "\n</div>")
    if holder_html:
        parts.append(holder_html)
    parts += [markets, f'<p class="meta attribution">{escape(attribution)}</p>',
              f"</section>\n{MARK_END}"]
    captions = [caption] + [x[k] for x, k in ((dk, "donut_caption"), (bk, "supply_caption"),
                                              (hk, "holder_caption")) if k in x]
    return "\n".join(parts), {**st, **rec, **dk, **bk, **hk, **mk,
                              "max_abs_bp": f"{_q(mx, '0.1'):.1f}",
                              "hci_page": snap["hci"]["meta"]["page"], "notes_line": notes,
                              "captions": captions}


# ---- the fetch ---------------------------------------------------------------------------

def addresses(repo: pathlib.Path) -> dict[str, str]:
    out = {}
    for token, (fname, rid) in ROOTS.items():
        cfg = tomllib.loads((repo / "config" / fname).read_text(encoding="utf-8"))
        hit = [r["address"] for r in cfg.get("root", []) if r.get("id") == rid]
        if len(hit) != 1:
            raise BehavioralStop(f"{token}: root {rid!r} x{len(hit)} in config/{fname}")
        out[token] = hit[0]
    return out


def _get(url: str, key: str) -> dict:
    import requests
    t0 = time.monotonic()
    r = requests.get(url, headers={"x-api-key": key, "accept": "application/json"}, timeout=60)
    secs = round(time.monotonic() - t0, 2)
    env = {"fetched_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "url": url,
           "status": r.status_code, "seconds": secs,
           "rate_headers": {k: r.headers[k] for k in RATE if k in r.headers}}
    if r.status_code != 200:
        raise BehavioralStop(f"{url} -> HTTP {r.status_code}: {r.text[:200]}")
    env["body"] = r.json()
    return env


def fetch(repo: pathlib.Path, key: str, get=_get, sleep=time.sleep, now=None) -> dict:
    """All requests first, every shape validated, then every file written."""
    now = now or dt.datetime.now(dt.UTC)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    addr = addresses(repo)
    calls = []

    def call(url):
        if calls:
            sleep(GAP_S)
        env = get(url, key)
        calls.append(url)
        return env

    depeg = {t: call(f"{BASE}/rwa/{a}?chain=eth&hours=168") for t, a in addr.items()}
    supply = {t: call(f"{BASE}/rwa/supply/{t}") for t in addr}
    hci_envs, found, page = [], set(), 1
    while True:
        env = call(f"{BASE}/rwa/hci?chain=eth&pageSize={HCI_PAGE_SIZE}&page={page}")
        hci_envs.append(env)
        try:
            ours = validate_hci(env["body"], addr.values())        # Amin, 4 Oct (B)
        except Exception as exc:
            raise BehavioralStop(f"HCI page {page}: {type(exc).__name__}: {exc}"[:400]) from exc
        found |= {e.address.lower() for e in ours}
        meta = HciMeta.model_validate(env["body"]["meta"])
        if len(found) == len(addr) or page >= meta.totalPages or page >= HCI_PAGE_CAP:
            break
        page += 1
    try:
        trimmed = {t: assemble(t, a, trim_depeg(depeg[t]), trim_supply(supply[t]),
                               [trim_hci(e, [a]) for e in hci_envs]) for t, a in addr.items()}
    except Exception as exc:                                   # shape mismatch: write nothing
        raise BehavioralStop(f"response shape: {type(exc).__name__}: {exc}"[:400]) from exc
    written = {}
    for t in addr:
        p = repo / "out/behavioral" / t / f"{stamp}.json"
        raw = repo / "out/behavioral-raw" / t / f"{stamp}.json"
        for path, obj in ((p, trimmed[t]),
                          (raw, {"depeg": depeg[t], "supply": supply[t], "hci": hci_envs})):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
                            encoding="utf-8", newline="")
        written[t] = {"path": p, "raw": raw, "hci_found": trimmed[t]["hci"]["entry"] is not None,
                      "hci_page": trimmed[t]["hci"]["meta"]["page"]}
    return {"requests": calls, "stamp": stamp, "written": written,
            "statuses": [e["status"] for e in [*depeg.values(), *supply.values(), *hci_envs]]}


STATUS = "out/behavioral/status.json"


def plain_reason(msg: str) -> str:
    """Amin, 4 Oct (Ruling 1): the failure in one plain sentence - an HTTP status or the
    first failing field and its message; never a key, never a raw payload."""
    m = re.search(r"HTTP (\d{3})", msg)
    if m:
        return f"the request returned HTTP {m[1]}"
    lines = [x.strip() for x in msg.splitlines() if x.strip()]
    field = next((x for x in lines if re.fullmatch(r"[\w.\[\]]+", x)), None)
    what = next((x.split(" [type=")[0] for x in lines if x.startswith("Input ")
                 or x.startswith("Field ")), None)
    if field and what:
        return f"{field}: {what}"[:200]
    return (lines[0] if lines else "unknown error").split(" [type=")[0][:200]


def latest_stamp(repo: pathlib.Path) -> str | None:
    """The snapshot stamp in use: the newest stamp every token has a snapshot for."""
    stamps = [{p.stem for p in (repo / "out/behavioral" / t).glob("*.json")} for t in ROOTS]
    common = set.intersection(*stamps) if stamps and all(stamps) else set()
    return max(common) if common else None


def write_status(repo: pathlib.Path, ok: bool, reason: str | None, now=None) -> dict:
    """Ruling 1: out/behavioral/status.json (committed) on every run."""
    now = now or dt.datetime.now(dt.UTC)
    st = {"fetched_at": now.isoformat(timespec="seconds"), "ok": ok, "reason": reason,
          "snapshot_stamp": latest_stamp(repo)}
    p = repo / STATUS
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="")
    return st


def read_status(repo: pathlib.Path) -> dict | None:
    p = repo / STATUS
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


if __name__ == "__main__":
    from factory.logs_pointer import env as _env
    _repo = pathlib.Path(__file__).resolve().parents[2]
    _key = _env(_repo, "WEBACY_API_KEY")
    if not _key:
        write_status(_repo, False, "the WEBACY_API_KEY setting is missing")
        print("WEBACY_API_KEY is not set (environment or .env)")
        sys.exit(2)
    try:
        _r = fetch(_repo, _key)
    except BehavioralStop as exc:
        _st = write_status(_repo, False, plain_reason(str(exc)))
        print(f"BEHAVIORAL STOPPED: {exc}")
        print(f"behavioral not refreshed: {_st['reason']}")
        sys.exit(1)
    write_status(_repo, True, None)
    print(f"fetched {len(_r['requests'])} requests | statuses {_r['statuses']} | "
          f"stamp {_r['stamp']}")
    for _t, _w in _r["written"].items():
        _rel = _w["path"].relative_to(_repo).as_posix()
        print(f"{_t}: {_rel} ({_w['path'].stat().st_size:,} B) | "
              f"raw {_w['raw'].stat().st_size:,} B | HCI "
              + (f"found on page {_w['hci_page']}" if _w["hci_found"] else
                 f"not found (pages read to {_w['hci_page']})"))
