"""B-5: the sheet-mirror generator.

P-3.15's rule: **the generator's output must reproduce the hand-derived
`config/crvusd_sheet.toml`; any diff is a finding** — chased to the
hand-derivation or the generator, never patched over.

The mirror is derived, never authoritative (P-3.04 binding). The stamped sheet
in `docs/context/` is the source of truth; DET-77's `sheet_hash` binds them.
"""

from __future__ import annotations

import hashlib
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


def count_first_run_tags(sheet_path: pathlib.Path, token: str) -> int:
    """DET-75's identity counts literal tags in the `<token>` section only."""
    return sum(ln.count("[FIRST-RUN READ:") for ln in _section(sheet_path, token))


def extract_cbbtc_disclosure(sheet_path: pathlib.Path, token: str) -> dict[str, str] | None:
    """D-8's cbBTC disclosure fields, mirrored from the node table row.

    Scoped to the token's section like everything else here: cbBTC is a crvUSD
    node, so this returns None for GHO and the block is ABSENT from GHO's
    mirror rather than faked (P-4.06).
    """
    for line in _section(sheet_path, token):
        if line.startswith("| cbBTC ") and "disclosure_cadence" in line:
            cad = re.search(r"`disclosure_cadence` = ([^;]+);", line)
            last = re.search(r"`last_disclosure_date` = ([^\[]+)\[", line)
            src = re.search(r"\[ANALYST-SUPPLIED ([^\]]+)\]", line)
            return {
                "disclosure_cadence": cad.group(1).strip() if cad else "",
                "last_disclosure_date": last.group(1).strip() if last else "",
                "source": ("ANALYST-SUPPLIED " + src.group(1).strip()) if src else "",
            }
    return None


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
    disc = extract_cbbtc_disclosure(sheet_path, token)

    out = [
        "# DERIVED MIRROR - NOT AUTHORITATIVE (P-3.04 binding).",
        f"# Source of truth: docs/context/intake-sheets-cdp.md, {token} section.",
        f"# Derived from sheet version sha256_first8 = {h} (signed 2026-09-04, P-3.12).",
        "# DET-77's sheet_hash check binds this mirror to that source; drift is caught",
        "# mechanically, never trusted away. Regenerated, never hand-patched.",
        "schema_version = 1",
        f'sheet_hash = "{h}"',
        "",
        "near_bound_threshold = 0.80",
        'counterparties = "n/a - archetype #1 holds no off-chain counterparties"',
        f'attribution_method = "{ATTRIBUTION_METHOD[token]}"',
        # R-B3.6 retires this line in favour of a pointer at the set file, which
        # DET-50 makes the one owner ("recorded in the set file at freeze") and
        # which `factory.stress` already reads directly. The REPLACEMENT lands
        # at B-3b, not here: changing it now would move all three mirror files,
        # and B-3a writes no mirror. Kept verbatim so the generator still
        # reproduces the committed mirrors byte-for-byte (P-3.15).
        'member2_target = ""   # null until the R-a1 refresh (Step 6/7); '
        "nothing consumes it in Step 3",
    ]
    if disc:
        out += [
            "",
            "# cbBTC disclosure fields - mirrored from the stamped sheet "
            "(D-8; owner: sheet, not labels.toml per C-8)",
            "[disclosure.cbBTC]",
            f'disclosure_cadence = "{disc["disclosure_cadence"]}"',
            f'last_disclosure_date = "{disc["last_disclosure_date"]}"',
            f'source = "{disc["source"]}"',
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
        "# ---- Deferred by ruling, present-and-empty -------------------------------",
        "# sell_side_capacity - per volatile node; lands at the R-a1 refresh (R-a4).",
        "# m4_fields[]        - Step 6.",
        "# bias_table[]       - Step 6 (Appendix C seed).",
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
