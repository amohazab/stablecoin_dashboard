"""
Export a flat context folder for a design-chat step: copies of the governing documents,
code, templates, site pages, records and reports under fixed export names.

Run from the repo root:
    python tools/export_context.py --step 9

Writes out/context-step<N>/ (a delete-later folder, never committed). Missing optional
sources are listed, not fatal. Prints each export with its size and scans every exported
file for a key assignment with a value (ANTHROPIC_API_KEY=..., ETH_RPC_URL=...).
Stdlib only.
"""

import pathlib
import re
import shutil
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
BLOCKS = {"crvUSD": 25974925, "GHO": 25974932, "LUSD": 25974949}
R = "src/factory/report"
T = "templates"

PROFILES = {
    "9": [
        # governing
        ("CLAUDE.md", "CLAUDE.md"), ("PROGRESS.md", "PROGRESS.md"),
        ("brief.md", "docs/context/stablecoin-risk-factory-brief.md"),
        ("rubic_v1.md", "docs/context/rubic_v1.md"),
        ("archetype-memo-1-cdp.md", "docs/context/archetype-memo-1-cdp.md"),
        ("intake-sheets-cdp.md", "docs/context/intake-sheets-cdp.md"),
        ("phase-b-checklist.md", "docs/context/phase-b-checklist.md"),
        ("README.md", "README.md?"), ("pyproject.toml", "pyproject.toml"),
        (".gitignore", ".gitignore"), (".gitattributes", ".gitattributes"),
        # code
        ("schema.py", "src/factory/schema.py"), ("harness.py", "src/factory/validate/harness.py"),
        ("rubric.py", "src/factory/rubric.py"),
        *((f"report-{n}.py", f"{R}/{n}.py") for n in (
            "__main__", "render", "svg", "table", "record", "manifest", "llm", "paths",
            "assumptions")),
        # templates
        *((n, f"{T}/{n}") for n in ("base.html.j2", "index.html.j2", "appendix.html.j2",
                                     "verify.html.j2", "style.css", "wording.toml",
                                     "manifest.toml")),
        *((f"prompts-{n}", f"{T}/prompts/{n}") for n in ("generate.md", "judge.md", "revise.md",
                                                          "remediate.md", "slots.toml")),
        # site (index pages only)
        *((f"site-{t}-index.html", f"out/site/{t}/index.html") for t in BLOCKS),
        ("site-verify-LUSD.html", "out/site/LUSD/verify.html"),
        # records
        *((f"evaluation-{t}-{b}.json", f"out/evaluation/{t}/{b}.json") for t, b in BLOCKS.items()),
        ("evaluation-LUSD-resolutions.jsonl", "out/evaluation/LUSD/resolutions.jsonl"),
        *((f"manifest-{t}.json", f"out/report/{t}/{b}/manifest.json") for t, b in BLOCKS.items()),
        *((f"events-{t}.jsonl", f"out/logs/events_{t.lower()}.jsonl") for t in BLOCKS),
        ("verifications.toml", "config/verifications.toml"),
        # reports
        ("step7-inventory-c.md", "out/reports/step7-inventory-c.md"),
        ("step7-b13-plan.md", "out/reports/step7-b13-plan.md"),
    ],
}

KEY_VALUE = re.compile(r"\b(ANTHROPIC_API_KEY|ETH_RPC_URL)=[^\s\"'`]+")


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "--step" or sys.argv[2] not in PROFILES:
        print(f"usage: python tools/export_context.py --step {{{','.join(PROFILES)}}}")
        return 2
    out = REPO / "out" / f"context-step{sys.argv[2]}"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    missing = []
    for name, src in PROFILES[sys.argv[2]]:
        optional = src.endswith("?")
        path = REPO / src.rstrip("?")
        if not path.exists():
            missing.append(f"{name} <- {src.rstrip('?')}{' (optional)' if optional else ''}")
            continue
        shutil.copyfile(path, out / name)
    files = sorted(out.iterdir(), key=lambda p: p.name.lower())
    total = 0
    for p in files:
        size = p.stat().st_size
        total += size
        print(f"{size:>10,}  {p.name}")
    print(f"{total:>10,}  total, {len(files)} files -> {out.relative_to(REPO).as_posix()}")
    for m in missing:
        print(f"missing: {m}")
    hits = [f"{p.name}: {m.group(1)}=…" for p in files
            for m in KEY_VALUE.finditer(p.read_text(encoding="utf-8", errors="replace"))]
    print("key scan (ANTHROPIC_API_KEY= / ETH_RPC_URL= with a value):",
          "none" if not hits else hits)
    return 1 if hits or any("optional" not in m for m in missing) else 0


if __name__ == "__main__":
    sys.exit(main())
