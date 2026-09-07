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


def parse_first_run_reads(sheet_path: pathlib.Path) -> list[dict[str, str]]:
    """Read the registry table out of the stamped sheet's crvUSD section."""
    lines = sheet_path.read_text(encoding="utf-8").split("\n")
    rows = []
    for line in lines:
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


def count_first_run_tags(sheet_path: pathlib.Path) -> int:
    """DET-75's identity counts literal tags in the crvUSD section only."""
    lines = sheet_path.read_text(encoding="utf-8").split("\n")
    start = next(i for i, ln in enumerate(lines) if ln.startswith("## crvUSD"))
    end = next(i for i, ln in enumerate(lines) if i > start and ln.startswith("## "))
    return sum(ln.count("[FIRST-RUN READ:") for ln in lines[start:end])


def extract_cbbtc_disclosure(sheet_path: pathlib.Path) -> dict[str, str] | None:
    """D-8's cbBTC disclosure fields, mirrored from the node table row."""
    text = sheet_path.read_text(encoding="utf-8")
    for line in text.split("\n"):
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


def generate(sheet_path: pathlib.Path) -> str:
    """Render the mirror TOML from the stamped sheet."""
    h = sheet_hash(sheet_path)
    rows = parse_first_run_reads(sheet_path)
    disc = extract_cbbtc_disclosure(sheet_path)

    out = [
        "# DERIVED MIRROR - NOT AUTHORITATIVE (P-3.04 binding).",
        "# Source of truth: docs/context/intake-sheets-cdp.md, crvUSD section.",
        f"# Derived from sheet version sha256_first8 = {h} (signed 2026-09-04, P-3.12).",
        "# DET-77's sheet_hash check binds this mirror to that source; drift is caught",
        "# mechanically, never trusted away. Regenerated, never hand-patched.",
        "schema_version = 1",
        f'sheet_hash = "{h}"',
        "",
        "near_bound_threshold = 0.80",
        'counterparties = "n/a - archetype #1 holds no off-chain counterparties"',
        'attribution_method = "direct"',
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
    return "\n".join(out)
