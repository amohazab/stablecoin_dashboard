"""Step 9 (P-9.01): the selector and methodology pages, their fail-closed stops, the
recorded rewrites and the Pages workflow."""

from __future__ import annotations

import json
import pathlib
import shutil

import pytest

from factory import eventlog, site

REPO = pathlib.Path(__file__).resolve().parents[1]


def tmp_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    for sub in ("out/site", "out/evaluation", "out/logs", "docs/context", "templates"):
        shutil.copytree(REPO / sub, tmp_path / sub)
    return tmp_path


def snapshot(root: pathlib.Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted((root / "out/site").rglob("*")) if p.is_file()}


def test_build_on_the_committed_state(tmp_path):
    root = tmp_repo(tmp_path)
    out = site.build(root)
    index = out["index.html"].decode()
    method = out["methodology.html"].decode()
    rec = json.loads(out["site.json"])
    for t in site.TOKEN_ORDER:
        man = json.loads((root / f"out/site/{t}/data/manifest.json").read_text(encoding="utf-8"))
        assert f"block {man['run_block']}" in index and f">{man['report_hash'][:8]}</code>" in index
        assert rec["tokens"][t]["run_block"] == man["run_block"]
    assert index.index("crvUSD/index.html") < index.index("GHO/index.html") \
        < index.index("LUSD/index.html")
    assert "<script" not in index + method
    ids = ["DET-09", "DET-75", "DET-76abcd", "DET-81", "DET-23abd", "DET-64"]
    assert "6 rubric entries are not yet registered in the harness" in method
    assert all(f"<code>{i}</code>" in method for i in ids) and rec["a16"]["ids"] == ids
    lines = sum(len(eventlog.quarantine_lines(
        eventlog.read(root / f"out/logs/events_{t.lower()}.jsonl"), t)) for t in site.TOKEN_ORDER)
    assert method.count('<tr class="log-row">') == lines == rec["log_rows"] == 11


def test_rewrites_are_applied_once_and_a_second_build_is_byte_identical(tmp_path):
    root = tmp_repo(tmp_path)
    site.build(root)
    first = snapshot(root)
    site.build(root)
    assert snapshot(root) == first
    rec = json.loads(first["out/site/site.json"])
    for t in site.TOKEN_ORDER:
        page = first[f"out/site/{t}/index.html"].decode()
        assert page.count("/blob/master/docs/context/archetype-memo-1-cdp.md") == 1
        assert page.count('<a href="../index.html">all tokens</a>') == 1
        assert "../../../docs/context" not in page
        rw = rec["tokens"][t]["rewrites"]["index.html"]
        assert rw["before"] != rw["after"] and len(rw["substitutions"]) == 3
        for n in ("appendix.html", "verify.html", "data/table.json"):   # never touched
            assert first[f"out/site/{t}/{n}"] == (REPO / f"out/site/{t}/{n}").read_bytes()


def test_a_leak_list_literal_stops_the_build(tmp_path):
    root = tmp_repo(tmp_path)
    p = root / "out/site/LUSD/index.html"
    p.write_text(p.read_text(encoding="utf-8").replace("No warnings this run", "TBD"),
                 encoding="utf-8", newline="")
    before = snapshot(root)
    with pytest.raises(site.SiteStop, match="literal leak.*'TBD'"):
        site.build(root)
    assert snapshot(root) == before                                     # nothing written


def test_a_row_count_mismatch_stops_the_build(tmp_path):
    root = tmp_repo(tmp_path)
    t = root / "templates/site/methodology.html.j2"
    t.write_text(t.read_text(encoding="utf-8").replace("{% for r in log_rows %}",
                                                       "{% for r in log_rows[1:] %}"),
                 encoding="utf-8", newline="")
    before = snapshot(root)
    with pytest.raises(site.SiteStop, match="log rows 10 != quarantine lines 11"):
        site.build(root)
    assert snapshot(root) == before                                     # nothing written


def test_the_pages_workflow_publishes_out_site():
    text = (REPO / ".github/workflows/pages.yml").read_text(encoding="utf-8")
    lines = [x.rstrip() for x in text.splitlines()]
    for want in ("on: { workflow_dispatch: {} }",
                 "permissions: { contents: read, pages: write, id-token: write }",
                 "    environment:", "      name: github-pages",
                 "      url: ${{ steps.deployment.outputs.page_url }}",
                 "      - uses: actions/checkout@v4", "      - uses: actions/configure-pages@v5",
                 "      - uses: actions/upload-pages-artifact@v3",
                 "        with: { path: out/site }",
                 "        uses: actions/deploy-pages@v4"):
        assert want in lines, want
    assert "secrets." not in text and "run:" not in text
