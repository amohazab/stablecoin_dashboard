"""B-11a′: the page renderer (P-7.01 R5, R6, R11, R17; R-B11.1–R-B11.7).

Two layers on one page (R-B11.1): the reader layer in plain English, then
"Detail for specialists" with every table inside `<details>`. Rubric IDs and
denominator mappings render on `appendix.html` only.

Jinja2 with `StrictUndefined` and autoescape; templates, stylesheet, reader
wording and the manifest live under `templates/` and all enter `template_hash`.
Every figure is a flat-table or grid value passed through `fmt` - the single
owner of DET-89's display rule, full form for tables and compact form for stat
cards and reader sentences (R-B11.6), both defined in `templates/manifest.toml`.
No JavaScript.

Pages are written to a staging directory and published by the report stage
only when every S3 row passes (B-11b).

Verify page (R11): the stress spot-check sheet's text from the same generator,
verbatim - its i/j and raw base-unit figures are the reproduction recipe, so
`fmt` does not touch them (named default, stated on the page).
"""

from __future__ import annotations

import datetime as _dt
import json
import pathlib
import re
import shutil
import tomllib
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from markupsafe import Markup, escape

from factory.report import svg

E18 = Decimal(10) ** 18
NUMERIC = {"base_units", "value_scale_units", "token_units", "usd_whole", "ratio", "bps",
           "seconds", "days", "count"}
AMOUNTS = {"base_units", "value_scale_units", "token_units", "usd_whole"}
QUALIFYING = ("mint", "upgrade", "set_oracle", "seize")          # DET-70 (tree.QUALIFYING)


class Formatter:
    """DET-89: `format(value, unit, decimals)` - the page's only number formatter,
    in two forms (R-B11.6)."""

    def __init__(self, rule: dict, compact: dict, value_scale: int = 1):
        self.rule, self.c, self.value_scale = rule, compact, value_scale

    @staticmethod
    def _q(v: Decimal, dp: int) -> Decimal:
        return v.quantize(Decimal(1).scaleb(-dp), rounding=ROUND_HALF_UP)

    def __call__(self, value: Any, unit: str, denominator: str | None = None,
                 compact: bool = False) -> str:
        with localcontext() as ctx:          # exact division for 78-digit sentinels
            ctx.prec = 120
            return self._format(value, unit, denominator, compact)

    def _amount_of(self, value: Any, unit: str) -> Decimal:
        if unit == "base_units":
            return Decimal(value) / E18
        if unit == "value_scale_units":
            return Decimal(value) / Decimal(self.value_scale)
        return Decimal(str(value))

    def _full_amount(self, amt: Decimal) -> str:
        a = abs(amt)
        if a >= 1000:
            return f"{self._q(amt, self.rule['usd_ge_1k_decimals']):,}"
        if a < 1:
            return f"{self._q(amt, self.rule['token_amount_lt_1_decimals'])}"
        return f"{self._q(amt, 2)}"

    def _compact_amount(self, amt: Decimal) -> str:
        sign = "-" if amt < 0 else ""
        a = abs(amt)
        pre = self.c["currency_prefix"]
        for base, suf in self.c["suffixes"]:
            if a >= base:
                return f"{sign}{pre}{self._q(a / Decimal(base), self.c['suffixed_decimals'])}{suf}"
        dp = self.c["below_1k_decimals"] if a >= 1 else self.c["below_1_decimals"]
        return f"{sign}{pre}{self._q(a, dp)}"

    def _format(self, value: Any, unit: str, denominator: str | None, compact: bool) -> str:
        if value is None or unit == "null":
            return "—"
        if unit in NUMERIC:
            try:
                if Decimal(str(value)) == 0:
                    return self.rule["zero"]
            except ArithmeticError:
                return str(value)
        if unit in AMOUNTS:
            if unit == "usd_whole" and not compact:
                return f"{int(value):,}"
            try:
                amt = self._amount_of(value, unit)
            except ArithmeticError:
                return str(value)
            return self._compact_amount(amt) if compact else self._full_amount(amt)
        if unit == "ratio":
            v = Decimal(str(value))
            if denominator:
                dp = (self.c["percent_decimals"] if compact
                      else self.rule["ratio_as_percent_decimals"])
                floor = Decimal(1).scaleb(-dp)
                if abs(v * 100) < floor / 2:
                    return f"< {floor}%"
                return f"{self._q(v * 100, dp)}%"
            return f"{self._q(v, 2 if compact else 4)}"
        if unit == "bps":
            return f"{self._q(Decimal(value) / 100, 2)}%"
        if unit == "seconds":
            return f"{int(value):,} s"
        if unit == "days":
            return f"{self._q(Decimal(str(value)), 1)} d"
        if unit == "count":
            return f"{int(value):,}"
        if unit == "unix_s":
            return _dt.datetime.fromtimestamp(int(value), _dt.UTC).strftime("%Y-%m-%d %H:%M UTC")
        if unit == "block":
            return str(int(value))
        if unit == "hash":
            return str(value)[:8]
        if unit == "address":
            s = str(value)
            return f"{s[:8]}…{s[-4:]}" if re.fullmatch(r"0x[0-9a-f]{40}", s) else s
        if unit == "list":
            return ", ".join(str(x) for x in value) if isinstance(value, list) else str(value)
        if unit == "boolean":
            return "yes" if value else "no"
        return str(value)


def infer_unit(v: Any) -> str:
    from factory.report.table import _unit_of
    return _unit_of(v)


def trigger_names(rubric_text: str) -> dict[str, tuple[str, str]]:
    out = {}
    for m in re.finditer(r"^\| (T-\d\d) \| ([^|]+) \| [^|]+ \| ([^|]+) \|", rubric_text, re.M):
        out[m.group(1)] = (m.group(2).strip(), m.group(3).strip())
    return out


def structural_zero(rows: dict) -> tuple[bool, str | None]:
    """R-B11.1(c) / R-B11.4's branch. It keys on a `stress.structural_zero`
    flag and reason row; no artifact carries a Member-1 structural-zero flag
    today (the only structural flag is DET-43's Member-2 insulation), so the flag
    reads unset until a ruling names its source."""
    flag = rows.get("stress.structural_zero.flag")
    reason = rows.get("stress.structural_zero.reason")
    return (bool(flag and flag["value"]), reason["value"] if reason else None)


def join_words(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def admin_rows(rows: dict) -> list[dict]:
    out = []
    for fid, r in rows.items():
        if fid.startswith("admin.") and fid.endswith(".holder_type"):
            p = fid[:-len(".holder_type")]
            out.append({"power": fid.split(".")[1], "prefix": p, "holder_type": r["value"],
                        "bucket": rows[p + ".delay_bucket"]["value"],
                        "veto": rows[p + ".veto_address"]["value"],
                        "scope": rows[p + ".scope"]["value"],
                        "upgradeability": rows[p + ".upgradeability"]["value"]})
    return out


def governance_sentence(rows: dict, w: dict) -> str:
    """DET-70's banner in words (R-B11.6): the qualifying held powers grouped by
    (holder, delay)."""
    held = [a for a in admin_rows(rows) if a["power"] in QUALIFYING and a["holder_type"] != "none"]
    if not held:
        return w["governance"]["immutable"]
    groups: dict[tuple, list[str]] = {}
    for a in held:
        groups.setdefault((a["holder_type"], a["bucket"]), []).append(w["powers"][a["power"]])
    parts = [f"{w['holders'][h]} can change {join_words(p)} {w['delays'][b or 'none']}"
             for (h, b), p in groups.items()]
    s = "; ".join(parts) + "."
    return s[0].upper() + s[1:]


def power_sentences(rows: dict, w: dict) -> list[str]:
    rs = admin_rows(rows)
    if all(a["holder_type"] == "none" for a in rs):
        return [w["governance"]["all_none"]]
    out = []
    for a in rs:
        gsm = any(k.startswith(a["prefix"] + ".reads.SWAP_FREEZER_ROLE") for k in rows)
        name = w["powers"]["gsm_freeze"] if gsm else w["powers"][a["power"]]
        if a["holder_type"] == "none":
            out.append(f"{name[0].upper()}{name[1:]}: {w['holders']['none']}.")
            continue
        veto = f"; {w['governance']['veto']}" if a["veto"] else ""
        out.append(f"{name[0].upper()}{name[1:]}: {w['holders'][a['holder_type']]}, "
                   f"{w['delays'][a['bucket'] or 'none']}{veto}.")
    return out


def _days(v: Any) -> str:
    return str(Decimal(str(v)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _days_words(v: Any) -> str:
    d = _days(v)
    return f"{d} day" if d == "1" else f"{d} days"


def pills(rows: dict, rec: dict, tnames: dict, w: dict) -> list[tuple[str, str]]:
    """(colour, text) for freshness, governance delay and flags (R-B11.1(b)).
    NAMED DEFAULT: freshness green to 30 days, amber to 92 (DET-74's class-I
    staleness limit), red beyond; governance red at under a day, amber otherwise,
    green when immutable; flags amber at Level 1, red at Level 2 or 3."""
    p = w["pills"]
    worst = rows.get("verif.staleness.worst.days")
    avg = rows.get("verif.staleness.weighted_days")
    if avg and avg["value"] is not None and worst:
        d = Decimal(str(worst["value"]))
        colour = "green" if d <= p["fresh_days"] else "amber" if d <= p["stale_days"] else "red"
        fresh = (colour, p["freshness"].format(
            avg=_days_words(avg["value"]), worst=rows["verif.staleness.worst.symbol"]["value"],
            days=_days_words(worst["value"])))
    else:
        fresh = ("green", p["freshness_none"])
    held = [a for a in admin_rows(rows) if a["power"] in QUALIFYING and a["holder_type"] != "none"]
    if not held:
        gov = ("green", p["governance_immutable"])
    else:
        buckets = {a["bucket"] or "none" for a in held}
        shortest = next(b for b in ("none", "<24h", "1–7d", ">7d") if b in buckets)
        gov = ("red" if shortest in ("none", "<24h") else "amber",
               p["governance"].format(delay=w["delay_short"][shortest]))
    trig = rec.get("triggers", [])
    if not trig:
        flag = ("green", p["flags_none"])
    else:
        lvl = max(t["level"] for t in trig)
        names = join_words([tnames.get(t["trigger"], (t["trigger"], ""))[0] for t in trig])
        flag = ("red" if lvl >= 2 else "amber", p["flags"].format(n=len(trig), names=names))
    return [fresh, gov, flag]


ADDR_KEY = re.compile(r"^0x[0-9a-f]{40}$")


def m4_tables(nested: dict, leaf, w: dict) -> dict:
    """R-B11.12: an m4 map renders as a table - one row per map key (a keeper,
    a GSM, a facilitator, a pool), one column per sub-key - never as
    "key · address · subkey" rows. `leaf(x)` formats a leaf and returns
    `(text, title)`. Scalars form their own two-column table."""
    labels = w["labels"]
    maps_w = w.get("m4_maps", {})
    cols_w = w.get("m4_columns", {})
    scalars, maps = [], []
    for k in sorted(nested):
        val = nested[k]
        if not isinstance(val, dict):
            text, title = leaf(val)
            scalars.append((labels.get(k, k.replace("_", " ")), text, title))
            continue
        keys = sorted(val)
        sub = sorted({s for kk in keys if isinstance(val[kk], dict) for s in val[kk]})
        columns = [cols_w.get(c, c.replace("_", " ")) for c in sub] if sub else \
            [labels.get(k, k.replace("_", " "))]
        rows = []
        for kk in keys:
            name = (f"{kk[:8]}…{kk[-4:]}" if ADDR_KEY.match(kk) else kk.replace("_", " "))
            if sub:
                cells = [leaf(val[kk][c]) if c in val[kk] else ("—", "") for c in sub]
            else:
                cells = [leaf(val[kk])]
            rows.append((name, kk, cells))
        maps.append({"title": maps_w.get(k, labels.get(k, k.replace("_", " "))),
                     "key_label": ("address" if all(ADDR_KEY.match(kk) for kk in keys)
                                   else "field"), "columns": columns,
                     "rows": rows})
    return {"scalars": scalars, "maps": maps}


def rows_nested(rows: dict, prefix: str) -> dict:
    """The `headline.m4.*` rows back into their map shape, leaves = field ids."""
    out: dict = {}
    for fid in rows:
        if not fid.startswith(prefix):
            continue
        parts = fid[len(prefix):].split(".")
        cur = out
        for part in parts[:-1]:
            cur = cur.setdefault(part, {})
        cur[parts[-1]] = fid
    return out


def render_token(repo: pathlib.Path, token: str, doc: dict, grid: dict, man: dict, rec: dict,
                 bundle, stress, out: pathlib.Path) -> dict:
    """Render the three pages into `out` (B-11b: a staging directory under
    `out/rehearsal/`; the report stage copies it to `out/site/<token>/` only on a
    green S3). The stylesheet goes beside `out`, where `../style.css` finds it."""
    tpl = repo / "templates"
    mf = tomllib.loads((tpl / "manifest.toml").read_text(encoding="utf-8"))
    w = tomllib.loads((tpl / "wording.toml").read_text(encoding="utf-8"))
    rows = {r["field_id"]: r for r in doc["rows"]}
    fmt = Formatter(mf["display_rule"], mf["compact"], int(rows["tree.root.value_scale"]["value"]))

    def v(fid: str) -> str:
        r = rows[fid]
        return fmt(r["value"], r["unit"], r["denominator"])

    def c(fid: str) -> str:
        r = rows[fid]
        return fmt(r["value"], r["unit"], r["denominator"], compact=True)

    def raw(fid: str) -> Any:
        return rows[fid]["value"] if fid in rows else None

    def ids(prefix: str) -> list[str]:
        return [f for f in rows if f.startswith(prefix)]

    def label(key: str) -> str:
        return w["labels"].get(key, key.replace("_", " "))

    cells = {x["id"]: x for x in grid["cells"]}
    rubric = (repo / "docs/context/rubic_v1.md").read_bytes().replace(b"\r\n", b"\n").decode()
    tnames = trigger_names(rubric)
    sz_flag, sz_reason = structural_zero(rows)

    # ---- the tree diagram (R-B11.3) --------------------------------------------------
    n_fam = len([f for f in ids("supply.family.") if f.endswith(".family")])
    root_lines = [f"{label('supply')} {c('supply.supply_ruled')}",
                  f"{label('originated')} {c('supply.origination_sum')} · "
                  f"{label('residual')} {c('supply.residual')}"
                  + (f" — {n_fam} {label('named_causes')}" if n_fam else "")]
    side = None
    if "supply.off_mainnet.share" in rows:
        side = w["tree"]["off_mainnet"].format(share=v("supply.off_mainnet.share"))
    bar_ids = [("terminal", ("terminal",)), ("terminal_other_layer", ("terminal_other_layer",)),
               ("disclosure_dependent", ("recurses", "recurses_truncated"))]
    bars, columns = [], []
    for name, labels in bar_ids:
        bars.append((w["tree"]["bars"][name], Decimal(str(raw(f"verif.bar.{name}"))),
                     v(f"verif.bar.{name}")))
        col = []
        for f in ids("tree.node."):
            if not f.endswith(".label") or raw(f) not in labels:
                continue
            a = f.split(".")[2]
            pill = None
            if raw(f) == "recurses_truncated":
                pill = w["tree"]["truncated_pill"]
            elif f"verif.staleness.{a}.staleness_days" in rows:
                pill = w["tree"]["days_pill"].format(
                    days=_days(raw(f"verif.staleness.{a}.staleness_days")))
            col.append((raw(f"tree.node.{a}.symbol"), v(f"tree.node.{a}.share"), pill))
        columns.append(col)
    tree_svg = svg.tree_diagram(root_lines, side, bars, columns, w["tree"]["caption"])
    scope = w["scope"].get(token, w["scope"]["default"])

    def tip(key: str) -> Markup:
        """R-B11.10: a keyboard-focusable "?" with a CSS tooltip; text from wording."""
        text = w["tips"][key].format(token=token, block=v("header.run_block"), scope=scope)
        return Markup('<span class="tip" tabindex="0" role="button" aria-label="{}">?'
                      '<span class="tip-text" role="tooltip">{}</span></span>').format(
                          escape(text), escape(text))

    # ---- charts and the exit grid (R-B11.4) --------------------------------------------
    shocks = ["20", "35", "50", "70"]
    chart_a = None
    if not sz_flag:
        top_a = max(shocks, key=lambda s: Decimal(raw(f"panel.M1-s{s}-d0-lp0.m2.bad_debt")))
        chart_a = svg.line_chart(
            [(f"−{s}%", Decimal(raw(f"panel.M1-s{s}-d0-lp0.m2.bad_debt")),
              c(f"panel.M1-s{s}-d0-lp0.m2.bad_debt")) for s in shocks],
            w["charts"]["a_title"], w["charts"]["a_axis"], w["charts"]["a_y"],
            [(Decimal(0), fmt(0, "base_units", compact=True)),
             (Decimal(raw(f"panel.M1-s{top_a}-d0-lp0.m2.bad_debt")),
              c(f"panel.M1-s{top_a}-d0-lp0.m2.bad_debt"))])
    curve = [(f"{Decimal(p) * 100}%", Decimal(raw(f"exit.curve.s{p}.pool_depth")),
              Decimal(raw(f"exit.curve.s{p}.gsm_contribution")), c(f"exit.curve.s{p}.total"))
             for p in ("0.005", "0.01", "0.02", "0.05")]
    chart_b = svg.stacked_columns(curve, w["charts"]["b_title"],
                                  (w["charts"]["b_pool"], w["charts"]["b_gsm"]),
                                  w["charts"]["b_x"], w["charts"]["b_y"],
                                  [(Decimal(0), fmt(0, "base_units", compact=True)),
                                   (Decimal(raw("exit.curve.s0.05.total")),
                                    c("exit.curve.s0.05.total"))])
    collapse = None
    if token == "GHO" and "M2-t0.93-lp0" in cells:
        m2 = cells["M2-t0.93-lp0"]["m3"]["exit_depth"]
        collapse = svg.two_bars(
            (w["charts"]["collapse_a"], Decimal(raw("headline.m3.exit_depth")),
             c("headline.m3.exit_depth")),
            (w["charts"]["collapse_b"], Decimal(m2), fmt(m2, "base_units", compact=True)),
            w["charts"]["collapse_title"])
    grid_rows = []
    for s in shocks:
        line = []
        for lp in ("0", "30", "60"):
            fid = f"panel.M1-s{s}-d0-lp{lp}.m3.ratio"
            val = raw(fid)
            if val is None:
                line.append(("exhausted", w["grid"]["exhausted"], fid))
            else:
                d = Decimal(str(val))
                shade = ("s0" if d == 0 else "s1" if d < Decimal("0.001") else "s2"
                         if d < Decimal("0.1") else "s3" if d < 1 else "s4")
                line.append((shade, v(fid), fid))
        grid_rows.append((f"−{s}%", line))

    def reading(shock: str, lp: str) -> str:
        fid = f"panel.M1-s{shock}-d0-lp{lp}.m3.ratio"
        val = raw(fid)
        if val is None:
            return w["grid"]["reading_exhausted"]
        key = "reading_over" if Decimal(str(val)) >= 1 else "reading_within"
        return w["grid"][key].format(ratio=c(fid))

    grid_reading = w["grid"]["reading"].format(r50=reading("50", "0"), r70=reading("70", "0"),
                                               r70lp60=reading("70", "60"))

    # autoescape keyed on the real extensions: the templates end `.j2`, and B-11a's
    # `select_autoescape(["html"])` left escaping OFF (as-counted, B-11a′).
    headline_m4 = m4_tables(rows_nested(rows, "headline.m4."),
                            lambda fid: (v(fid), fid), w)

    def cell_m4(cell: dict) -> dict:
        return m4_tables(cell["m4"], lambda x: (fmt(x, infer_unit(x)), ""), w)

    n_refs = len([f for f in ids("refpoint.") if f.endswith(".literal")])
    env = Environment(loader=FileSystemLoader(str(tpl)),
                      autoescape=select_autoescape(["html", "j2"], default_for_string=True),
                      undefined=StrictUndefined, keep_trailing_newline=True)
    env.filters["fmt"] = fmt
    ctx = dict(token=token, rows=rows, v=v, c=c, raw=raw, ids=ids, label=label, cells=cells,
               grid=grid, doc=doc, man=man, rec=rec, w=w, tnames=tnames,
               tree_svg=tree_svg, chart_a=chart_a, chart_b=chart_b, collapse=collapse,
               grid_rows=grid_rows, grid_reading=grid_reading, infer_unit=infer_unit, fmt=fmt,
               sz_flag=sz_flag, sz_reason=sz_reason,
               pills=pills(rows, rec, tnames, w), governance=governance_sentence(rows, w),
               power_sentences=power_sentences(rows, w), tip=tip,
               headline_m4=headline_m4, cell_m4=cell_m4, n_refs=n_refs,
               slot=lambda name: f"[slot: {name} — pending B-13]")
    (out / "data").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(tpl / "style.css", out.parent / "style.css")
    files = {}
    for name in ("index", "appendix"):
        html = env.get_template(f"{name}.html.j2").render(**ctx)
        (out / f"{name}.html").write_text(html, encoding="utf-8", newline="")
        files[name] = out / f"{name}.html"
    from factory.spotcheck import stress_sheet_text
    ver = tomllib.loads((repo / "config/verifications.toml").read_text(encoding="utf-8"))
    vrow = next((x for x in ver.get("verification", [])
                 if x["artifact_hash"] == stress.header.stress_hash), None)
    html = env.get_template("verify.html.j2").render(
        **ctx, sheet=stress_sheet_text(bundle, stress, repo), vrow=vrow)
    (out / "verify.html").write_text(html, encoding="utf-8", newline="")
    files["verify"] = out / "verify.html"
    blk = doc["run_block"]
    for nm, obj in (("table.json", doc), ("grid.json", grid), ("manifest.json", man),
                    (f"evaluation-{blk}.json", rec)):
        (out / "data" / nm).write_text(json.dumps(obj, sort_keys=True, indent=1,
                                                  ensure_ascii=False) + "\n",
                                       encoding="utf-8", newline="")
    return files
