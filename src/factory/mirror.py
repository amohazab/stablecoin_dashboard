"""B-5: the sheet-mirror generator.

P-3.15's rule: **the generator's output must reproduce the hand-derived
`config/crvusd_sheet.toml`; any diff is a finding** — chased to the
hand-derivation or the generator, never patched over.

The mirror is derived, never authoritative (P-3.04 binding). The stamped sheet
in `docs/context/` is the source of truth; DET-77's `sheet_hash` binds them.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re


def sheet_hash(sheet_path: pathlib.Path) -> str:
    """SHA-256 first-8 over LF-normalised bytes — the declared algorithm."""
    raw = sheet_path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(raw).hexdigest()[:8]


def _section(sheet_path: pathlib.Path, token: str) -> list[str]:
    """The lines of one token's section: `## <token>` up to the next `## `.

    P-4.05: this bound existed only in `count_first_run_tags`. The row parser
    scanned the whole file, which was correct only while crvUSD's was the
    sheet's only registry; the GHO registry made regeneration emit 80 rows
    into the crvUSD mirror. Both functions now take the token and share this.
    """
    lines = sheet_path.read_text(encoding="utf-8").split("\n")
    start = next(i for i, ln in enumerate(lines) if ln.startswith(f"## {token}"))
    end = next((i for i, ln in enumerate(lines) if i > start and ln.startswith("## ")),
               len(lines))
    return lines[start:end]


def parse_first_run_reads(sheet_path: pathlib.Path, token: str) -> list[dict[str, str]]:
    """Read the registry table out of the stamped sheet's `<token>` section."""
    rows = []
    for line in _section(sheet_path, token):
        if line.startswith("| FR-") and line.rstrip().endswith("| open |"):
            parts = [c.strip() for c in line.strip().strip("|").split(" | ")]
            if len(parts) != 5:
                raise ValueError(f"malformed registry row: {line[:60]}")
            rows.append({
                "tag_id": parts[0], "sheet_location": parts[1],
                "bundle_field_path": parts[2], "read_spec": parts[3],
                "status": parts[4],
            })
    return rows


def parse_sell_side(sheet_path: pathlib.Path, token: str) -> list[dict[str, str]]:
    """DET-52's per-volatile-node parameter rows out of the stamped sheet.

    Shape, one row per node in the token's section:

        | SS-<symbol> | <address> | <value> | <source> | <date> |

    A row whose value cell is empty is NOT emitted — P-4.15's rule that an
    analyst input without its source and date is left owed rather than minted,
    which is also what keeps DET-52 inert until every row is real. Returns []
    until the B-3b signed edit lands the table, so the mirror is byte-identical
    in the meantime.
    """
    rows = []
    for line in _section(sheet_path, token):
        if not line.startswith("| SS-"):
            continue
        parts = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if len(parts) != 5:
            raise ValueError(f"malformed sell-side row: {line[:60]}")
        _tag, address, value, source, date = parts
        if not (value and source and date):
            continue
        rows.append({"address": address.strip("`").lower(), "value": value,
                     "source": source, "date": date})
    return rows


BIAS_DIRECTIONS = frozenset({"overstates", "understates", "both"})     # DET-53, no `neutral`

# DET-53's four memo-derived rows, mandatory as literals: (mechanism, direction).
# The sheet marks them ★; the parse asserts the mark AND the direction, so a
# sheet edit that drops a ★ or flips one of these fails regeneration.
BIAS_MANDATORY = {
    "Collateral-sell-side bound": "overstates",
    "GSM cap headroom (H2.i)": "overstates",
    "Liquidator recycling (H5)": "understates",
    "Stability Pool refills (H3)": "understates",
}

# NAMED IMPLEMENTER DEFAULT (P-7.01 R8): DET-53 reads "`bias_table[]` (sheet
# field, analyst-keyed, dated)" and the sheet's table has no date column. The
# date is the P-6.07 signed edit's, which landed the table (sheet `ad7c35c2`,
# intake_trigger 2026-09-13). A later sheet edit that changes the table owes a
# new date here, by ruling.
BIAS_TABLE_DATE = "2026-09-13"

BIAS_HEADING = "stock-only capacity — direction of error per mechanism"


def parse_bias_table(sheet_path: pathlib.Path, token: str) -> list[dict]:
    """DET-53's rows out of the `<token>` section: the table under the bias
    heading, `| Mechanism | Token | Direction | Reason |`. A ★ at the end of the
    mechanism cell is `mandatory = true`; the ★ never enters `mechanism`."""
    lines = _section(sheet_path, token)
    start = next((i for i, ln in enumerate(lines) if BIAS_HEADING in ln), None)
    if start is None:
        raise ValueError(f"{token}: bias-table heading absent from the sheet section")
    rows = []
    for ln in lines[start + 1:]:
        if not ln.startswith("|"):
            if rows:
                break
            continue
        if re.fullmatch(r"\|[-| ]+\|", ln.strip()):          # the separator row
            continue
        parts = [c.strip() for c in ln.strip().strip("|").split(" | ")]
        if parts[0] == "Mechanism":                          # the header row
            continue
        if len(parts) != 4:
            raise ValueError(f"malformed bias row: {ln[:60]}")
        mech, tokens, direction, reason = parts
        mandatory = mech.endswith("★")
        mech = mech.removesuffix("★").strip()
        if direction not in BIAS_DIRECTIONS:
            raise ValueError(f"DET-53: {mech} direction {direction!r} outside the enum")
        rows.append({"mechanism": mech, "tokens": [t.strip() for t in tokens.split(",")],
                     "direction": direction, "reason": reason, "mandatory": mandatory})
    marked = {r["mechanism"]: r["direction"] for r in rows if r["mandatory"]}
    if marked != BIAS_MANDATORY:
        raise ValueError(f"DET-53: {token} mandatory rows {marked} != {BIAS_MANDATORY}")
    return rows


def parse_m4_fields(sheet_path: pathlib.Path, token: str) -> list[str]:
    """DET-38's per-token `m4` key set: the `<token> (N): k1, k2, ….` line under
    the "Metric-4 field set" passage; N is asserted against the list."""
    lines = _section(sheet_path, token)
    start = next((i for i, ln in enumerate(lines) if ln.startswith("**Metric-4 field set")),
                 None)
    if start is None:
        raise ValueError(f"{token}: Metric-4 field set passage absent from the sheet section")
    m = next((re.match(rf"^{re.escape(token)} \((\d+)\): (.+)\.$", ln.strip())
              for ln in lines[start + 1:] if ln.startswith(f"{token} (")), None)
    if m is None:
        raise ValueError(f"{token}: m4_fields line absent")
    keys = [k.strip() for k in m.group(2).split(",")]
    if len(keys) != int(m.group(1)) or len(set(keys)) != len(keys):
        raise ValueError(f"{token}: m4_fields count {m.group(1)} vs {len(keys)} keys")
    return keys


def count_first_run_tags(sheet_path: pathlib.Path, token: str) -> int:
    """DET-75's identity counts literal tags in the `<token>` section only."""
    return sum(ln.count("[FIRST-RUN READ:") for ln in _section(sheet_path, token))


def _q(v: str) -> str:
    """A TOML basic string. JSON's escapes are TOML's."""
    return json.dumps(v, ensure_ascii=False)


_TAG = re.compile(r"\s*\[(?:VERIFIED|ANALYST-SUPPLIED|FIRST-RUN READ)[^\]]*\]")


def parse_disclosures(sheet_path: pathlib.Path, token: str) -> list[dict[str, str]]:
    """DET-76(e)'s disclosure rows, generalised from C0's cbBTC-only extraction
    (P-7.02's deferral): every node-table row carrying `disclosure_cadence`.

    The row is keyed by its first two cells verbatim; `config.load` joins them
    to `[[node]]` ADDRESSES with uniqueness asserted, so the symbol text only
    locates the sheet row (named default, P-7.05)."""
    rows = []
    for line in _section(sheet_path, token):
        if not line.startswith("| ") or "`disclosure_cadence` = " not in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        cad = re.search(r"`disclosure_cadence` = ([^;]+);", line)
        last = re.search(r"`last_disclosure_date` = ([^\[]+?)\s*\[", line)
        src = re.search(r"\[ANALYST-SUPPLIED ([^\]]+)\]", line)
        if not (cad and last and src):
            raise ValueError(f"{token}: malformed disclosure row: {line[:60]}")
        rows.append({"row_key": cells[0], "memo_row": cells[1],
                     "disclosure_cadence": cad.group(1).strip(),
                     "last_disclosure_date": last.group(1).strip(),
                     "source": "ANALYST-SUPPLIED " + src.group(1).strip()})
    return rows


def parse_disclosure_inheritance(sheet_path: pathlib.Path, token: str) -> list[dict[str, str]]:
    """The sheet's pass-through sentence, "Disclosure: waEthUSDC inherits the
    USDC row's, waEthUSDT the USDT row's" (memo §4.3), as `{symbol, from}`."""
    out = []
    for line in _section(sheet_path, token):
        m = re.search(r"Disclosure: (.+?) \(memo §4\.3 pass-through\)", line)
        if not m:
            continue
        for part in m.group(1).split(", "):
            pm = re.fullmatch(r"(\S+) (?:inherits )?the (\S+) row's\.?", part.strip())
            if pm is None:
                raise ValueError(f"{token}: malformed inheritance clause {part!r}")
            out.append({"symbol": pm.group(1), "from": pm.group(2)})
    return out


def parse_counterparties(sheet_path: pathlib.Path, token: str) -> str:
    """DET-73's counterparty line, verbatim from the sheet (B-9; the mirror
    carried a hardcoded ASCII literal until then)."""
    head = "**Counterparty enumeration (memo §14):** "
    got = [ln[len(head):].strip() for ln in _section(sheet_path, token) if ln.startswith(head)]
    if len(got) != 1:
        raise ValueError(f"{token}: {len(got)} counterparty lines")
    return got[0]


def parse_audit_status(sheet_path: pathlib.Path, token: str) -> dict:
    """DET-73's structured block (P-7.04): `audits[]` as `{firm, date, scope}`,
    `bug_bounty {platform, max}`, `last_material_change_audited`,
    `staleness_date` - values as signed, marker tags stripped."""
    lines = _section(sheet_path, token)
    i = next((k for k, ln in enumerate(lines) if ln.startswith("**Audit status (memo §14)**")),
             None)
    if i is None:
        raise ValueError(f"{token}: audit status block absent")
    block = {}
    for ln in lines[i + 1:i + 5]:
        m = re.match(r"^- `([a-z_\[\]]+)`(.*)$", ln)
        if not m:
            raise ValueError(f"{token}: malformed audit line {ln[:60]}")
        block[m.group(1)] = _TAG.sub("", m.group(2)).strip()
    audits = []
    for item in block["audits[]"].lstrip(":").strip().split(" · "):
        am = re.match(r"^(.+?) (\d{4}-\d{2}(?:-\d{2})?), (.+)$", item.strip())
        if am is None:
            raise ValueError(f"{token}: malformed audit item {item[:60]}")
        audits.append({"firm": am.group(1), "date": am.group(2), "scope": am.group(3)})
    bm = re.match(r"^= \{platform: (.+), max: (.+)\}$", block["bug_bounty"])
    lm = re.match(r"^= (yes|no)\b", block["last_material_change_audited"])
    sm = re.match(r"^= (\d{4}-\d{2}-\d{2})\.", block["staleness_date"])
    if not (bm and lm and sm):
        raise ValueError(f"{token}: audit block fields unparsed {block}")
    return {"audits": audits,
            "bug_bounty": {"platform": bm.group(1), "max": bm.group(2)},
            "last_material_change_audited": lm.group(1),
            "staleness_date": sm.group(1)}


def parse_oracle_feeds(sheet_path: pathlib.Path, token: str) -> list[dict]:
    """DET-54/55's signed per-feed table (P-7.01 R21, P-7.04). Empty for a
    token whose section has none (crvUSD: EMA oracles, read per run)."""
    lines = _section(sheet_path, token)
    i = next((k for k, ln in enumerate(lines) if ln.startswith("**Oracle feed table")), None)
    if i is None:
        return []
    rows = []
    for ln in lines[i + 1:]:
        if rows and not ln.startswith("|"):
            break
        if not ln.startswith("| 0x"):
            continue
        c = [x.strip() for x in ln.strip().strip("|").split(" | ")]
        if len(c) != 9:
            raise ValueError(f"{token}: malformed feed row {ln[:60]}")
        node, symbol, feed, _cls, typ, dev, hb, source, date = c
        tm = re.match(r"^`([a-z_]+)`", typ)
        dm = re.match(r"^(\d+(?:\.\d+)?)%", dev)
        hm = re.match(r"^(\d+)", hb)
        row = {"node_address": node.lower(), "symbol": symbol, "feed": feed.lower(),
               "type": tm.group(1),
               "heartbeat_form": "observed_max" if "observed_max" in hb else "documented",
               "source": source, "date": date[:10]}
        if dm:
            row["deviation_bps"] = int(round(float(dm.group(1)) * 100))
        if hm:
            row["heartbeat_s"] = int(hm.group(1))
        rows.append(row)
    return rows


# DET-12 compares the bundle's `attribution_method` to the mirror's, so the
# mirror must carry the token's ruled method. NAMED IMPLEMENTER DEFAULT
# (P-4.06): crvUSD is `direct` as it has always been; GHO is `per_position`,
# which is P-4.04 R2's Route A, and the sheet's own "Primary: pro-rata per
# position". Nothing else in the header varies by token.
# LUSD is `direct` for a different reason than crvUSD's: not one method per
# market, but ONE COLLATERAL. Every trove's collateral is ETH, so the whole of
# backing attributes to the single §4.5 ETH node with nothing to apportion -
# the pro-rata denominator GHO needs (P-4.04 R2) does not exist here. Added at
# P-4.15 because `generate(sheet, "LUSD")` cannot render without it.
ATTRIBUTION_METHOD = {"crvUSD": "direct", "GHO": "per_position", "LUSD": "direct"}


def generate(sheet_path: pathlib.Path, token: str) -> str:
    """Render one token's mirror TOML from the stamped sheet."""
    h = sheet_hash(sheet_path)
    rows = parse_first_run_reads(sheet_path, token)
    disc = parse_disclosures(sheet_path, token)
    inherit = parse_disclosure_inheritance(sheet_path, token)
    audit = parse_audit_status(sheet_path, token)
    feeds = parse_oracle_feeds(sheet_path, token)
    m4 = parse_m4_fields(sheet_path, token)
    bias = parse_bias_table(sheet_path, token)

    out = [
        "# DERIVED MIRROR - NOT AUTHORITATIVE (P-3.04 binding).",
        f"# Source of truth: docs/context/intake-sheets-cdp.md, {token} section.",
        f"# Derived from sheet version sha256_first8 = {h}.",
        "# DET-77's sheet_hash check binds this mirror to that source; drift is caught",
        "# mechanically, never trusted away. Regenerated, never hand-patched.",
        "schema_version = 1",
        f'sheet_hash = "{h}"',
        "",
        "near_bound_threshold = 0.80",
        f"counterparties = {_q(parse_counterparties(sheet_path, token))}",
        f'attribution_method = "{ATTRIBUTION_METHOD[token]}"',
        # P-7.01 R8 retires the `member2_target = ""` line (R-B3.6): DET-50's
        # one owner is the set file, which `factory.stress` reads directly.
        "# member2_target - not mirrored: DET-50's owner is the set file (R-B3.6, P-7.01 R8).",
        "",
        f"# m4_fields[] - DET-38's exact per-cell m4 key set, {len(m4)} keys, "
        "mirrored from the stamped sheet.",
        "m4_fields = [" + ", ".join(f'"{k}"' for k in m4) + "]",
        "# bias_table[] date - the P-6.07 signed edit's; the sheet table has no date "
        "column (P-7.01 R8).",
        f"bias_table_date = {BIAS_TABLE_DATE}",
    ]
    out += [
        "",
        f"# disclosure[] - DET-76(e), {len(disc)} node-table rows; owner: the sheet (C-8).",
    ]
    for d in disc:
        out += ["", "[[disclosure]]", *[f"{k} = {_q(v)}" for k, v in d.items()]]
    for d in inherit:
        out += ["", "[[disclosure_inherit]]", f"symbol = {_q(d['symbol'])}",
                f"from = {_q(d['from'])}"]
    out += ["", f"# oracle_feed[] - DET-54/55, {len(feeds)} signed rows (P-7.01 R21)."]
    for f in feeds:
        out += ["", "[[oracle_feed]]"]
        out += [f"{k} = {v}" if isinstance(v, int) else f"{k} = {_q(v)}" for k, v in f.items()]
    out += [
        "",
        "# audit_status - DET-73's structured block, values as signed (P-7.04).",
        "[audit_status]",
        f"last_material_change_audited = {_q(audit['last_material_change_audited'])}",
        f"staleness_date = {_q(audit['staleness_date'])}",
        "bug_bounty = { platform = " + _q(audit["bug_bounty"]["platform"])
        + ", max = " + _q(audit["bug_bounty"]["max"]) + " }",
        "audits = [",
        *[f"  {{ firm = {_q(a['firm'])}, date = {_q(a['date'])}, scope = {_q(a['scope'])} }},"
          for a in audit["audits"]],
        "]",
    ]
    out += [
        "",
        f"# first_run_reads[] - {len(rows)} rows mirrored from the stamped sheet.",
        '# status stays "open" until a stamped sheet edit retires the prose tag (P-3.14).',
    ]
    for r in rows:
        out += [
            "", "[[first_run_read]]",
            f'tag_id = "{r["tag_id"]}"',
            f'sheet_location = "{r["sheet_location"]}"',
            f'bundle_field_path = "{r["bundle_field_path"]}"',
            f'read_spec = "{r["read_spec"]}"',
            f'status = "{r["status"]}"',
        ]
    out += [
        "",
        f"# bias_table[] - DET-53, {len(bias)} rows mirrored from the stamped sheet; "
        "the four mandatory rows are the memo-derived literals.",
        "",
    ]
    for r in bias:
        out += [
            "[[bias_table]]",
            f'mechanism = "{r["mechanism"]}"',
            "tokens = [" + ", ".join(f'"{t}"' for t in r["tokens"]) + "]",
            f'direction = "{r["direction"]}"',
            f'reason = "{r["reason"]}"',
            f"mandatory = {'true' if r['mandatory'] else 'false'}",
            "",
        ]
    out += [
        "# sell_side_capacity - DET-52, per volatile node, signed at P-6.07.",
        "",
    ]
    for r in parse_sell_side(sheet_path, token):
        out += [
            "[[sell_side_capacity]]",
            f'address = "{r["address"]}"',
            f'value = "{r["value"]}"',
            f'source = "{r["source"]}"',
            f'date = {r["date"]}',
            "",
        ]
    return "\n".join(out)
