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
- D4: a rewrite form is neither present once in its old form nor once in its new form.

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

import hashlib
import html as _html
import json
import pathlib
import re
import sys
import tomllib

from markupsafe import Markup

from factory import eventlog
from factory.report.render import Formatter, environment, structural_zero
from factory.rubric import read_trigger_table

TOKEN_ORDER = ("crvUSD", "GHO", "LUSD")
PAGE_SET = ("index.html", "appendix.html", "verify.html", "data")
CARD_ROWS = (("supply_card", "supply.supply_ruled"), ("bad_debt_card", "headline.m2.bad_debt"),
             ("exit_card", "headline.m3.exit_depth"))
SLOT = re.compile(r'<div class="prose-slot" data-slot="structural_summary">(.*?)</div>', re.S)
PILLS = re.compile(r'<div class="pills">\n?(.*?)\n?</div>', re.S)
PILL = re.compile(r'<span class="pill [a-z]+">[^<]*</span>')
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


def apply_rewrites(page: str, pairs: list[tuple[str, str]], token: str) -> tuple[str, str]:
    """(original, rewritten). A form present in its new shape is inverted first (D8);
    the original must then hold each old form exactly once and no new form."""
    original = page
    for old, new in pairs:
        n_new = original.count(new)
        if n_new > 1:
            raise SiteStop(f"{token}: rewritten form {new[:60]!r} x{n_new}")
        if n_new == 1:
            original = original.replace(new, old)
    after = original
    for old, new in pairs:
        n_old, n_new = original.count(old), original.count(new)
        if (n_old, n_new) != (1, 0):
            raise SiteStop(f"{token}: rewrite form {old[:60]!r} old x{n_old}, new x{n_new}")
        after = after.replace(old, new)
    return original, after


def token_card(repo: pathlib.Path, token: str, w: dict, mf: dict, pairs) -> dict:
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
    if m is None:
        raise SiteStop(f"{token}: no structural_summary slot on index.html")
    shown = "\n\n".join(_html.unescape(p) for p in re.findall(r"<p>(.*?)</p>", m.group(1), re.S))
    gens = [g for g in rec["generation"] if g.get("slot") == "structural_summary" and g.get("text")]
    if not gens:
        raise SiteStop(f"{token}: the record carries no structural_summary text")
    top = max(gens, key=lambda g: g["pass"])
    if shown != top["text"].strip():
        raise SiteStop(f"{token}: structural_summary on the page differs from pass "
                       f"{top['pass']}'s text")

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
    original, after = apply_rewrites(page, pairs, token)
    return {
        "token": token, "run_block": blk, "report_hash": man["report_hash"],
        "read": fmt(ts["value"], ts["unit"], ts["denominator"]),
        "finding": first_sentence(top["text"]), "figures": " · ".join(figures),
        "pill": Markup(spans[-1]), "outcome": rec["outcome"],
        "ruling": (rec.get("publication") or {}).get("ruling"),
        "passed": sum(1 for x in rec["results"] if x["result"] == "pass"),
        "total": len(rec["results"]), "unregistered": rec["unregistered"],
        "index_after": after,
        "rewrite": {"before": _sha(original.encode("utf-8")), "after": _sha(after.encode("utf-8")),
                    "substitutions": [{"old": o, "new": n} for o, n in pairs]},
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


def plan(repo: pathlib.Path) -> dict[str, bytes]:
    """Every output as bytes, every fail-closed condition checked; nothing written."""
    tpl = repo / "templates"
    w = tomllib.loads((tpl / "wording.toml").read_text(encoding="utf-8"))
    mf = tomllib.loads((tpl / "manifest.toml").read_text(encoding="utf-8"))
    site = repo / "out/site"
    dirs = sorted(p.name for p in site.iterdir() if p.is_dir())
    if dirs != sorted(TOKEN_ORDER):
        raise SiteStop(f"token directories {dirs} != {sorted(TOKEN_ORDER)}")
    pairs = rewrites(w)
    cards = [token_card(repo, t, w, mf, pairs) for t in TOKEN_ORDER]

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
                                      "passed", "total")},
                 "open": opened[c["token"]],
                 "record_url": f"{blob}/out/evaluation/{c['token']}/{c['run_block']}.json"}
                for c in cards]
    env = environment(tpl)
    ctx = dict(s=w["site"], w=w, repo_url=repo_url, blob=blob)
    index = env.get_template("site/index.html.j2").render(**ctx, cards=cards)
    method = env.get_template("site/methodology.html.j2").render(
        **ctx, log_rows=rows, n_log=len(rows), outcomes=outcomes,
        a16={"count": len(unreg[0]), "ids": unreg[0]}, notices_sentence=notices_sentence(cards))

    rendered = method.count('<tr class="log-row">')                            # D1
    if rendered != n_lines:
        raise SiteStop(f"methodology log rows {rendered} != quarantine lines {n_lines}")
    hits = leaks({"index.html": index, "methodology.html": method},
                 mf["substitution_list"]["literals"])                          # D9
    if hits:
        raise SiteStop(f"literal leak on the new pages: {'; '.join(hits)}")

    record = {
        "repo_url": repo_url, "branch": w["repo"]["branch"], "log_rows": len(rows),
        "a16": {"count": len(unreg[0]), "ids": [x["entry_id"] for x in unreg[0]]},
        "tokens": {c["token"]: {"run_block": c["run_block"], "report_hash": c["report_hash"],
                                "outcome": c["outcome"], "pill": str(c["pill"]),
                                "finding": c["finding"], "figures": c["figures"],
                                "rewrites": {"index.html": c["rewrite"]}} for c in cards},
    }
    out = {"index.html": index.encode("utf-8"), "methodology.html": method.encode("utf-8"),
           "site.css": (tpl / "site/site.css").read_bytes().replace(b"\r\n", b"\n"),
           "site.json": _json(record).encode("utf-8")}
    for c in cards:
        out[f"{c['token']}/index.html"] = c["index_after"].encode("utf-8")
    return out


def build(repo: pathlib.Path) -> dict[str, bytes]:
    out = plan(repo)
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
