"""Step 9: the public site's two root pages (P-9.01).

`uv run python -m factory.site` - no RPC, no API, no arguments. Reads each token's
published page set under `out/site/<T>/`, the committed gate records
(`out/evaluation/<T>/<run_block>.json`, D12), the three event logs, the rubric's
printed trigger table, and `templates/{wording,manifest}.toml`. Writes
`out/site/index.html` (the selector), `out/site/methodology.html`,
`out/site/site.css` and `out/site/site.json`, and applies D4's two recorded rewrites
to each token's `index.html`. Deterministic: no wall clock, no HEAD - building twice
leaves `out/site/` byte-identical.

Fail-closed (each stops the build with its numbers, before anything is written):
- a token directory missing any of index / appendix / verify / data (§3.4);
- D2: the three gate records disagree on `unregistered`;
- D5: the page's `structural_summary` text differs from the record's highest-pass
  text, or a stat-card figure formatted here differs from the page's card;
- D1: the methodology page's rendered log rows ≠ Σ quarantine lines (DET-60's
  row-count clause - this module is its evaluator);
- D9: a DET-79 `literals` entry appears on either new page;
- D4: a rewrite form is neither present once in its old form nor once in its new form;
- A-20 (P-8.01): a token page carrying both the DET-59 pending literal and the behavioral
  block, or neither; a snapshot whose consumed paths do not validate.

Step 8 phase A (P-8.01): with a snapshot under `out/behavioral/<T>/`, two more recorded
rewrites per token page - (i) the DET-59 meta literal -> the behavioral block, rebuilt
from the latest snapshot between `<!-- behavioral:begin/end -->` markers; (ii) the reader
sentence -> wording `[behavioral] reader`. Both are inverted before every build, so
"before" stays the report as rendered. No snapshot: neither applies and the pending text
stays. The as-of date for the 14-day suffix is the build's UTC date (P3), recorded in
site.json: two builds on the same day are byte-identical.

NAMED DEFAULTS:
- `TOKEN_ORDER` is the ruled card order (§3.2); the token directories under
  `out/site/` must be exactly that set.
- The first sentence is the first paragraph up to its first ". " (P-9.01 D5).
- D8: a rewrite's "before" is reconstructed by inverse substitution of the current
  page, so a second build records the same before/after hashes.
- A stat-card figure is also compared with the page's own card text (D5's addition
  formats the same rows; a disagreement means the page and the table have drifted).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html as _html
import json
import pathlib
import re
import sys
import tomllib

from markupsafe import Markup

from factory import behavioral, eventlog
from factory.report.render import Formatter, environment, structural_zero
from factory.rubric import read_trigger_table

TOKEN_ORDER = ("crvUSD", "GHO", "LUSD")
PAGE_SET = ("index.html", "appendix.html", "verify.html", "data")
CARD_ROWS = (("supply_card", "supply.supply_ruled"), ("bad_debt_card", "headline.m2.bad_debt"),
             ("exit_card", "headline.m3.exit_depth"))
SLOT = re.compile(r'<div class="prose-slot" data-slot="structural_summary">(.*?)</div>', re.S)
PILLS = re.compile(r'<div class="pills">\n?(.*?)\n?</div>', re.S)
PILL = re.compile(r'<span class="pill [a-z]+">[^<]*</span>')
MARKED = re.compile(re.escape(behavioral.MARK_BEGIN) + r".*?" + re.escape(behavioral.MARK_END),
                    re.S)
HEADER_NAV = ('<a href="index.html">report</a><a href="appendix.html">appendix</a>'
              '<a href="verify.html">verify</a>')


class SiteStop(Exception):
    """A fail-closed condition: nothing is written."""


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _json(obj) -> str:
    return json.dumps(obj, sort_keys=True, indent=1, ensure_ascii=False) + "\n"


def _load(p: pathlib.Path):
    return json.loads(p.read_text(encoding="utf-8"))


def first_sentence(text: str) -> str:
    para = text.strip().split("\n\n")[0].strip()
    head, sep, _ = para.partition(". ")
    return head + "." if sep else para


def rewrites(w: dict) -> list[tuple[str, str]]:
    """D4: (old, new) pairs - the memo/sheet hrefs to the repository on its branch, and
    the header nav gaining the selector link, both exactly as the fixed templates render."""
    blob = f'{w["repo"]["url"]}/blob/{w["repo"]["branch"]}'
    pairs = [(f'href="../../../{w["memo"][k]}"', f'href="{blob}/{w["memo"][k]}"')
             for k in ("section", "sheet")]
    pairs.append((HEADER_NAV, f'<a href="../index.html">{w["nav"]["all_tokens"]}</a>' + HEADER_NAV))
    return pairs


def apply_rewrites(page: str, pairs: list[tuple[str, str]], token: str,
                   beh: tuple[str, tuple[str, str], str | None] | None = None) -> tuple[str, str]:
    """(original, rewritten). A form present in its new shape is inverted first (D8);
    the original must then hold each old form exactly once and no new form.
    `beh` = {pending, spec, check, readers, reader, block} (P-8.01; R4 at the P-8.02
    review): a marked block is removed and the literal restored after the specialists h2;
    every reader variant is inverted. Forward, with a block: the literal's line goes, the
    block is inserted before the "How to check this" section, the reader pair applies."""
    original = page
    extra: list[tuple[str, str]] = []
    if beh is not None:
        marked = MARKED.findall(original)
        if len(marked) > 1:
            raise SiteStop(f"{token}: behavioral block x{len(marked)}")
        if marked:
            region = marked[0] + "\n"
            if original.count(region) != 1 or original.count(beh["spec"]) != 1:
                raise SiteStop(f"{token}: behavioral block or specialists heading not once")
            original = original.replace(region, "").replace(
                beh["spec"], beh["spec"] + beh["pending"])
        for new in beh["readers"]:
            if new in original:
                original = original.replace(new, beh["reader"][0])
        if beh["block"] is not None:
            extra = [beh["reader"]]
    for old, new in [*pairs, *extra]:
        n_new = original.count(new)
        if n_new > 1:
            raise SiteStop(f"{token}: rewritten form {new[:60]!r} x{n_new}")
        if n_new == 1:
            original = original.replace(new, old)
    after = original
    block = beh["block"] if beh is not None else None
    for old, new in [*pairs, *extra]:
        n_old, n_new = original.count(old), original.count(new)
        if (n_old, n_new) != (1, 0):
            raise SiteStop(f"{token}: rewrite form {old[:60]!r} old x{n_old}, new x{n_new}")
        after = after.replace(old, new)
    if block is not None:
        lit, anchor = beh["spec"] + beh["pending"], beh["check"]
        if after.count(lit) != 1 or after.count(anchor) != 1:
            raise SiteStop(f"{token}: literal line x{after.count(lit)}, check section "
                           f"x{after.count(anchor)} before the block")
        after = after.replace(lit, beh["spec"]).replace(anchor, block + "\n" + anchor)
    return original, after


def notice_of(repo: pathlib.Path, w: dict) -> str | None:
    """Ruling 1: the not-refreshed sentence when status.json says the last fetch failed."""
    st = behavioral.read_status(repo)
    if not st or st.get("ok"):
        return None
    snap = st.get("snapshot_stamp")
    shown = f"{snap[:4]}-{snap[4:6]}-{snap[6:8]}" if snap else "never"
    return w["behavioral"]["not_refreshed"].format(date=st["fetched_at"][:10],
                                                   reason=st.get("reason"), snapshot=shown)


def either_or(page: str, w: dict, landed: bool, token: str, notice: str | None = None) -> None:
    """A-20: the pending literal or the block with its attribution line - never both,
    never neither; which one follows whether the tier has landed. Ruling 1: when the last
    refresh failed, the block carries the not-refreshed notice exactly once, else never."""
    blocks_ = MARKED.findall(page)
    if blocks_:
        want = 1 if notice else 0
        got = blocks_[0].count(_html_escape(notice)) if notice else blocks_[0].count(
            w["behavioral"]["not_refreshed"].split("{")[0])
        if got != want:
            raise SiteStop(f"{token}: not-refreshed notice x{got}, expected x{want}")
    lit = page.count(w["behavioral_pending"])
    blocks = MARKED.findall(page)
    attr = w["behavioral"]["attribution"].split("{")[0]
    has_block = len(blocks) == 1 and attr in blocks[0]
    if landed and (lit, len(blocks)) == (0, 1) and has_block:
        return
    if not landed and (lit, len(blocks)) == (1, 0):
        return
    raise SiteStop(f"{token}: A-20 either/or - literal x{lit}, block x{len(blocks)}"
                   f"{'' if not blocks or has_block else ' without its attribution line'}, "
                   f"snapshot {'present' if landed else 'absent'}")


def _html_escape(s: str) -> str:
    return str(Markup.escape(s))


def token_card(repo: pathlib.Path, token: str, w: dict, mf: dict, pairs, as_of: dt.date,
               notice: str | None = None) -> dict:
    site = repo / "out/site" / token
    missing = [n for n in PAGE_SET if not (site / n).exists()]
    if missing:
        raise SiteStop(f"{token}: page set incomplete under {site}: {missing}")
    man = _load(site / "data/manifest.json")
    blk = man["run_block"]
    table = _load(site / "data/table.json")
    rec = _load(repo / "out/evaluation" / token / f"{blk}.json")          # D12
    rows = {r["field_id"]: r for r in table["rows"]}
    fmt = Formatter(mf["display_rule"], mf["compact"], int(rows["tree.root.value_scale"]["value"]))
    page = (site / "index.html").read_text(encoding="utf-8")

    # D5: the rendered structural_summary equals the record's highest-pass text
    m = SLOT.search(page)
    gens = [g for g in rec["generation"] if g.get("slot") == "structural_summary" and g.get("text")]
    if "structural_summary" in (rec.get("slots_missing") or []):        # A-25: the notice
        if m is not None or 'class="slot-missing" data-slot="structural_summary"' not in page:
            raise SiteStop(f"{token}: structural_summary missing in the record but not shown "
                           "as the A-25 notice")
        top = {"text": w["site"]["no_summary"]}
        finding = w["site"]["no_summary"]
    else:
        if m is None:
            raise SiteStop(f"{token}: no structural_summary slot on index.html")
        shown = "\n\n".join(_html.unescape(p)
                            for p in re.findall(r"<p>(.*?)</p>", m.group(1), re.S))
        if not gens:
            raise SiteStop(f"{token}: the record carries no structural_summary text")
        top = max(gens, key=lambda g: g["pass"])
        if shown != top["text"].strip():
            raise SiteStop(f"{token}: structural_summary on the page differs from pass "
                           f"{top['pass']}'s text")
        finding = first_sentence(top["text"])

    # D5's addition: the three stat-card figures, compact, from the cards' own rows
    sz_flag, _ = structural_zero(rows)
    figures = []
    for key, fid in CARD_ROWS:
        r = rows[fid]
        text = fmt(r["value"], r["unit"], r["denominator"], compact=True)
        card = re.search(rf'<div class="card-value" title="{re.escape(fid)}">([^<]*)</div>', page)
        if card is None or _html.unescape(card.group(1)) != text:
            raise SiteStop(f"{token}: card {fid} reads {card and card.group(1)!r}, "
                           f"table gives {text!r}")
        label = w["labels"][key]
        figures.append(f"{label} {text}, structurally zero"
                       if fid == "headline.m2.bad_debt" and sz_flag else f"{label} {text}")

    pills = PILLS.search(page)
    spans = PILL.findall(pills.group(1)) if pills else []
    if not spans:
        raise SiteStop(f"{token}: no notices pill on index.html")
    ts = rows["header.block_timestamp"]
    pending = f'<p class="meta">{w["behavioral_pending"]}</p>\n'
    spec = f'<h2 class="specialists">{w["specialists"]}</h2>\n'
    wb = w["behavioral"]
    usd = Formatter(mf["display_rule"], mf["compact"])
    snap_path = behavioral.latest(repo, token)
    block, beh_rec, subs = None, {"state": "pending", "snapshot": None}, list(pairs)
    if snap_path is not None:
        try:
            snap = behavioral.load(snap_path)
            block, st = behavioral.block(snap, as_of, wb,
                                         lambda x: usd(x, "usd_whole", compact=True))
        except Exception as exc:                                        # P6: shape mismatch
            raise SiteStop(f"{token}: snapshot {snap_path.name} does not validate: "
                           f"{type(exc).__name__}: {exc}"[:400]) from exc
        if notice:                                                      # Ruling 1
            head = block.index(">", block.index("<section")) + 1
            block = (block[:head] + f'\n<p class="meta notice">{_html_escape(notice)}</p>'
                     + block[head:])
        beh_rec = {"state": "rendered", "snapshot": snap_path.relative_to(repo).as_posix(),
                   "snapshot_sha256": _sha(snap_path.read_bytes()),
                   "block_sha256": _sha(block.encode("utf-8")), **st}
    full = block is not None and st["liquidity_shown"] and st["supply_shown"]      # R4
    reader = (w["behavioral_tier"], wb["reader_full"] if full else wb["reader"])
    if block is not None:
        subs += [reader, (spec + pending, spec),
                 ('<section id="check">',
                  f"<behavioral block, sha256 {beh_rec['block_sha256']}>" + '<section id="check">')]
    original, after = apply_rewrites(page, pairs, token, {
        "pending": pending, "spec": spec, "check": '<section id="check">',
        "readers": (wb["reader"], wb["reader_full"]), "reader": reader, "block": block})
    either_or(after, w, block is not None, token, notice)                     # A-20
    # P-8.11: the card's "Last successful run", the log's last `published` line
    last = eventlog.last_published(
        eventlog.read(repo / "out/logs" / f"events_{token.lower()}.jsonl"), token)
    last_ok = w["banner"]["last"].format(date=last.date if last else w["banner"]["none"])
    return {
        "last_ok": last_ok,
        "token": token, "run_block": blk, "report_hash": man["report_hash"],
        "read": fmt(ts["value"], ts["unit"], ts["denominator"]),
        "finding": finding, "figures": " · ".join(figures),
        "pill": Markup(spans[-1]), "outcome": rec["outcome"],
        "ruling": (rec.get("publication") or {}).get("ruling"),
        "passed": sum(1 for x in rec["results"] if x["result"] == "pass"),
        "total": len(rec["results"]), "unregistered": rec["unregistered"],
        "checks": checks_line(rec["results"]),
        "index_after": after, "block": block, "behavioral": beh_rec,
        "rewrite": {"before": _sha(original.encode("utf-8")), "after": _sha(after.encode("utf-8")),
                    "substitutions": [{"old": o, "new": n} for o, n in subs]},
    }


def log_rows(repo: pathlib.Path, tt: dict) -> tuple[list[dict], dict[str, list[dict]], int]:
    """D10: one row per quarantine line, status from `open_entries`."""
    out, opened, total = [], {}, 0
    for token in TOKEN_ORDER:
        entries = eventlog.read(repo / "out/logs" / f"events_{token.lower()}.jsonl")
        lines = eventlog.quarantine_lines(entries, token)
        total += len(lines)
        open_ids = {eid for eid, _ in eventlog.open_entries(entries, token)}
        opened[token] = [{"id": eid, "trigger": e.trigger}
                         for eid, e in eventlog.open_entries(entries, token)]
        key = lambda e: (e.date, e.token, e.trigger, e.level)  # noqa: E731 - eventlog's tuple
        fire = {key(e): i for i, e in lines if e.resolution_date is None}
        res = {key(e): i for i, e in lines if e.resolution_date is not None}
        for i, e in lines:
            eid = eventlog.entry_id(token, i)
            if e.resolution_date is not None:
                status = f"resolution of {eventlog.entry_id(token, fire[key(e)])}" \
                    if key(e) in fire else "resolution"
            elif eid in open_ids:
                status = "open"
            else:
                status = f"resolved by {eventlog.entry_id(token, res[key(e)])}"
            out.append({"id": eid, "date": e.date, "token": token,
                        "category": tt[e.trigger]["name"], "trigger": e.trigger, "level": e.level,
                        "resolution_type": (e.resolution_type or "—").replace("_", " "),
                        "resolution_date": e.resolution_date or "—", "status": status})
    return out, opened, total


def _possessive(names: list[str]) -> str:
    s = [f"{n}'s" for n in names]
    return s[0] if len(s) == 1 else ", ".join(s[:-1]) + " and " + s[-1]


def checks_line(results: list[dict]) -> str:
    """A-24 (P-8.05): the count is over the evaluated rows, and the not-evaluated rows are
    named - "90 of 90 evaluated, 6 not evaluated (judge withdrawn)", never "90 of 96"."""
    done = [x for x in results if x["result"] != "not_evaluated"]
    passed = sum(1 for x in done if x["result"] == "pass")
    skipped = len(results) - len(done)
    return (f"{passed} of {len(done)} evaluated"
            + (f", {skipped} not evaluated (judge withdrawn)" if skipped else ""))


def notices_sentence(cards: list[dict]) -> str:
    """The open-notices sentence from the records' outcomes (§3.3), never a token list;
    the ruling id is the committed record's `publication.ruling`."""
    ruled = [c for c in cards if c["outcome"] == "published_without_banner_by_ruling"]
    clean = [c["token"] for c in cards if c["outcome"] == "published"]
    parts = []
    if ruled:
        many = len(ruled) > 1
        ids = ", ".join(dict.fromkeys(c["ruling"] for c in ruled))
        names = _possessive([c["token"] for c in ruled])
        parts.append(f"{names} page{'s were' if many else ' was'}"
                     f" published by a recorded ruling ({ids}) from {'their' if many else 'its'}"
                     " last evaluation run, with the quarantine banner removed and the open "
                     f"notices kept in {'each' if many else 'the'} page's notices pill")
    if clean:
        many = len(clean) > 1
        parts.append(f"{_possessive(clean)} page{'s' if many else ''} passed every check")
    return "; ".join(parts) + "."


def leaks(texts: dict[str, str], literals: list[str]) -> list[str]:
    """D9: DET-79's literals over the page text (tags stripped, entities decoded); a
    literal starting "<" reads the HTML itself, as det_79 does."""
    hits = []
    for name, page in texts.items():
        txt = _html.unescape(re.sub(r"<[^>]+>", " ", page))
        for lit in literals:
            n = (page if lit.startswith("<") else txt).count(lit)
            if n:
                hits.append(f"{name} {lit!r} x{n}")
    return hits


def plan(repo: pathlib.Path, as_of: dt.date | None = None) -> dict[str, bytes]:
    """Every output as bytes, every fail-closed condition checked; nothing written.
    `as_of` defaults to today's UTC date (P-8.01 P3)."""
    as_of = as_of or dt.datetime.now(dt.UTC).date()
    tpl = repo / "templates"
    w = tomllib.loads((tpl / "wording.toml").read_text(encoding="utf-8"))
    mf = tomllib.loads((tpl / "manifest.toml").read_text(encoding="utf-8"))
    site = repo / "out/site"
    dirs = sorted(p.name for p in site.iterdir() if p.is_dir())
    if dirs != sorted(TOKEN_ORDER):
        raise SiteStop(f"token directories {dirs} != {sorted(TOKEN_ORDER)}")
    pairs = rewrites(w)
    notice = notice_of(repo, w)                                               # Ruling 1
    cards = [token_card(repo, t, w, mf, pairs, as_of, notice) for t in TOKEN_ORDER]

    unreg = [c["unregistered"] for c in cards]                                 # D2
    if any(u != unreg[0] for u in unreg):
        raise SiteStop("gate records disagree on unregistered: "
                       + "; ".join(f"{c['token']} {[x['entry_id'] for x in c['unregistered']]}"
                                   for c in cards))
    tt = read_trigger_table(repo)
    rows, opened, n_lines = log_rows(repo, tt)
    repo_url = w["repo"]["url"]
    blob = f"{repo_url}/blob/{w['repo']['branch']}"
    outcomes = [{**{k: c[k] for k in ("token", "run_block", "report_hash", "outcome",
                                      "passed", "total", "checks")},
                 "open": opened[c["token"]],
                 "record_url": f"{blob}/out/evaluation/{c['token']}/{c['run_block']}.json"}
                for c in cards]
    env = environment(tpl)
    snaps = [{"token": c["token"], "path": c["behavioral"]["snapshot"]} for c in cards
             if c["behavioral"]["snapshot"]]
    beh = {"landed": len(snaps) == len(cards), "snapshots": snaps}                # P4
    ctx = dict(s=w["site"], w=w, repo_url=repo_url, blob=blob, beh=beh, beh_notice=notice)
    index = env.get_template("site/index.html.j2").render(**ctx, cards=cards)
    method = env.get_template("site/methodology.html.j2").render(
        **ctx, log_rows=rows, n_log=len(rows), outcomes=outcomes,
        a16={"count": len(unreg[0]), "ids": unreg[0]}, notices_sentence=notices_sentence(cards))

    rendered = method.count('<tr class="log-row">')                            # D1
    if rendered != n_lines:
        raise SiteStop(f"methodology log rows {rendered} != quarantine lines {n_lines}")
    texts = {"index.html": index, "methodology.html": method,
             **{f"{c['token']} behavioral block": c["block"] for c in cards if c["block"]}}
    hits = leaks(texts, mf["substitution_list"]["literals"])                     # D9
    if hits:
        raise SiteStop(f"literal leak on the new pages: {'; '.join(hits)}")

    record = {
        "repo_url": repo_url, "branch": w["repo"]["branch"], "log_rows": len(rows),
        "behavioral_as_of": as_of.isoformat(),
        "behavioral_status": behavioral.read_status(repo),
        "a16": {"count": len(unreg[0]), "ids": [x["entry_id"] for x in unreg[0]]},
        "tokens": {c["token"]: {"run_block": c["run_block"], "report_hash": c["report_hash"],
                                "outcome": c["outcome"], "pill": str(c["pill"]),
                                "finding": c["finding"], "figures": c["figures"],
                                "behavioral": c["behavioral"],
                                "rewrites": {"index.html": c["rewrite"]}} for c in cards},
    }
    out = {"index.html": index.encode("utf-8"), "methodology.html": method.encode("utf-8"),
           "site.css": (tpl / "site/site.css").read_bytes().replace(b"\r\n", b"\n"),
           "site.json": _json(record).encode("utf-8")}
    for c in cards:
        out[f"{c['token']}/index.html"] = c["index_after"].encode("utf-8")
    return out


def build(repo: pathlib.Path, as_of: dt.date | None = None) -> dict[str, bytes]:
    out = plan(repo, as_of)
    site = repo / "out/site"
    for rel, data in out.items():
        p = site / rel
        if not p.exists() or p.read_bytes() != data:
            p.write_bytes(data)
    return out


if __name__ == "__main__":
    _repo = pathlib.Path(__file__).resolve().parents[2]
    try:
        _out = build(_repo)
    except SiteStop as exc:
        print(f"SITE STOPPED: {exc}")
        sys.exit(1)
    _rec = json.loads(_out["site.json"])
    print(f"site built | log rows {_rec['log_rows']} | A-16 {_rec['a16']['count']} | "
          + " · ".join(f"{t} {v['report_hash'][:8]} {v['rewrites']['index.html']['before'][:8]}"
                       f"->{v['rewrites']['index.html']['after'][:8]}"
                       for t, v in _rec["tokens"].items()))
    for _t, _v in _rec["tokens"].items():
        _b = _v["behavioral"]
        print(f"{_t} behavioral {_b['state']}" + ("" if _b["state"] == "pending" else
              f" | {_b['snapshot']} {_b['snapshot_sha256'][:8]} | fetched_at {_b['fetched_at']} | "
              f"age {_b['age_days']} d | stale depeg {_b['depeg_stale']} hci {_b['hci_stale']} | "
              f"HCI {'page ' + str(_b['hci_page']) if _b['hci_found'] else 'not covered'}"))
