"""Step 8 phase B (P-8.04 Q9, Q10, Q14): the unattended chain with fake stages, git and model
server - nothing runs, nothing calls a model, nothing pushes."""

from __future__ import annotations

import datetime as dt
import os
import pathlib
import time

from factory import chain

REPO = pathlib.Path(__file__).resolve().parents[1]
NOW = dt.datetime(2026, 10, 1, 1, 0, tzinfo=dt.UTC)


class Git:
    def __init__(self, status: str = "", staged: str = "out/site/index.html\n"):
        self.status, self.staged, self.calls = status, staged, []

    def __call__(self, repo, *args):
        self.calls.append(args)
        if args[0] == "status":
            return 0, self.status
        if args[:2] == ("diff", "--cached"):
            return 0, self.staged
        return 0, "ok"


def runner_with(fail: str | None = None, outcome: str = "published"):
    ran = []

    def run(repo, argv):
        ran.append(argv[0])
        if fail and argv[0] == fail:
            return 1, "Traceback: boom"
        return 0, f"outcome {outcome} | revision_count 0" if argv[0] == "factory.report" else "ok"
    return run, ran


def test_the_plan_orders_the_token_stages_before_the_shared_tail():
    assert [n for n, _ in chain.plan("monthly", "GHO")] == [
        "run GHO", "tree GHO", "stress GHO", "report GHO", "behavioral", "site"]
    assert dict(chain.plan("monthly", "GHO"))["report GHO"] == ["factory.report", "GHO", "--llm"]
    assert [n for n, _ in chain.plan("weekly", None)] == ["behavioral", "site"]


def test_a_monthly_run_commits_its_outcome_and_pushes_last(tmp_path):
    git, (run, ran) = Git(), runner_with()
    code, log = chain.chain(tmp_path, "monthly", "LUSD", runner=run, git=git,
                            server=lambda: "0.34.4", now=NOW)
    assert code == 0 and ran == ["factory.run", "factory.tree", "factory.stress",
                                 "factory.report", "factory.behavioral", "factory.site"]
    commit = next(c for c in git.calls if c[0] == "commit")
    assert commit[-1] == "chain monthly 20261001T010000Z: LUSD published"
    assert git.calls[-1] == ("push", "origin", "master")
    assert (tmp_path / "out/logs/scheduler/20261001T010000Z-monthly.log").exists()
    assert not (tmp_path / "out/logs/scheduler/chain.lock").exists()           # released


def test_a_failed_stage_stops_the_token_stages_but_the_evidence_is_pushed(tmp_path):
    git, (run, ran) = Git(), runner_with(fail="factory.tree")
    code, log = chain.chain(tmp_path, "monthly", "crvUSD", runner=run, git=git,
                            server=lambda: "0.34.4", now=NOW)
    assert code == 1 and ran == ["factory.run", "factory.tree", "factory.behavioral",
                                 "factory.site"]
    assert any("skip stress crvUSD" in x for x in log)
    commit = next(c for c in git.calls if c[0] == "commit")
    assert commit[-1].endswith("site refresh; failed: tree crvUSD")
    assert git.calls[-1] == ("push", "origin", "master")


def test_a_blocked_report_is_an_outcome_not_a_failure(tmp_path):
    git, (run, _ran) = Git(), runner_with(outcome="blocked_S3")
    code, _log = chain.chain(tmp_path, "monthly", "GHO", runner=run, git=git,
                             server=lambda: "0.34.4", now=NOW)
    assert code == 0
    assert next(c for c in git.calls if c[0] == "commit")[-1].endswith("GHO blocked_S3")


def test_an_unreachable_server_skips_the_token_but_refreshes_the_site(tmp_path):
    def down():
        raise ConnectionError("refused")
    git, (run, ran) = Git(), runner_with()
    code, log = chain.chain(tmp_path, "monthly", "LUSD", runner=run, git=git, server=down,
                            now=NOW)
    assert code == 1 and ran == ["factory.behavioral", "factory.site"]
    assert any("model server unreachable" in x for x in log)


def test_a_dirty_tree_is_refused_before_anything_runs(tmp_path):
    git, (run, ran) = Git(status=" M src/x.py\n"), runner_with()
    code, log = chain.chain(tmp_path, "weekly", None, runner=run, git=git, now=NOW)
    assert code == 1 and ran == [] and "not clean" in log[-1]


def test_a_second_chain_is_busy_and_a_stale_lock_is_taken(tmp_path):
    lock = tmp_path / "out/logs/scheduler/chain.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("{}")
    os.utime(lock, (NOW.timestamp() - 60, NOW.timestamp() - 60))
    git, (run, ran) = Git(), runner_with()
    code, log = chain.chain(tmp_path, "weekly", None, runner=run, git=git, now=NOW)
    assert code == 1 and ran == [] and log[-1].startswith("FAIL: busy")
    stale = NOW.timestamp() - chain.STALE_LOCK_S - 1
    os.utime(lock, (stale, stale))
    code, _log = chain.chain(tmp_path, "weekly", None, runner=run, git=git, now=NOW)
    assert code == 0 and ran == ["factory.behavioral", "factory.site"]


def test_a_lock_whose_holder_is_dead_is_stale_at_once(tmp_path, monkeypatch):
    # Amin, 4 Oct: a run killed mid-way (0xC000013A) left a lock; its pid is gone
    lock = tmp_path / "out/logs/scheduler/chain.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text('{"pid": 1400, "since": 0}')
    os.utime(lock, (NOW.timestamp() - 60, NOW.timestamp() - 60))
    monkeypatch.setattr(chain, "_pid_alive", lambda pid: False)
    git, (run, ran) = Git(), runner_with()
    code, _log = chain.chain(tmp_path, "weekly", None, runner=run, git=git, now=NOW)
    assert code == 0 and ran == ["factory.behavioral", "factory.site"]
    monkeypatch.setattr(chain, "_pid_alive", lambda pid: True)
    lock.write_text('{"pid": 1400, "since": 0}')
    os.utime(lock, (NOW.timestamp() - 60, NOW.timestamp() - 60))
    code, log = chain.chain(tmp_path, "weekly", None, runner=run, git=git, now=NOW)
    assert code == 1 and log[-1].startswith("FAIL: busy")
    assert chain._pid_alive(os.getpid()) is True


def test_a_key_in_a_staged_file_blocks_the_commit(tmp_path):
    leak = tmp_path / "out/site/leak.html"
    leak.parent.mkdir(parents=True)
    leak.write_text("ETH_RPC_URL=https://node.example/abcdefghijklmnop", encoding="utf-8")
    git, (run, _ran) = Git(staged="out/site/leak.html\n"), runner_with()
    code, log = chain.chain(tmp_path, "weekly", None, runner=run, git=git, now=NOW)
    assert code == 1 and any("key found" in x for x in log)
    assert not [c for c in git.calls if c[0] in ("commit", "push")]
    assert ("reset", "-q") in git.calls


def test_the_dry_run_runs_no_stage_and_pushes_nothing(tmp_path):
    git, (run, ran) = Git(), runner_with()
    seen = []
    code, log = chain.chain(tmp_path, "monthly", "LUSD", dry_run=True, runner=run, git=git,
                            server=lambda: seen.append(1) or "0.34.4", now=NOW)
    assert code == 0 and ran == [] and seen == [1]
    assert [c[0] for c in git.calls] == ["status"]
    assert sum(x.startswith("plan ") for x in log) == 6 and any("not run" in x for x in log)


def test_the_wrappers_and_the_workflow():
    for name, arg in (("run_monthly.cmd", "--monthly --token %1"), ("run_weekly.cmd", "--weekly")):
        text = (REPO / "tools/scheduler" / name).read_bytes().decode("ascii")
        assert "cd /d D:\\projects\\stable_dashboard" in text and "\r\n" in text
        assert f"-m factory.chain {arg} < nul >> out\\logs\\scheduler\\wrapper.log 2>&1" in text
        assert "chcp 65001 >nul" in text and "set PYTHONUTF8=1" in text
        assert text.rstrip().endswith("exit %RC%") and "exit /b" not in text
    wf = (REPO / ".github/workflows/pages.yml").read_text(encoding="utf-8")
    assert 'push: { branches: [master], paths: ["out/site/**"] }' in wf
    assert "continue-on-error: true" in wf and "run: sleep 60" in wf
    assert wf.count("uses: actions/deploy-pages@v4") == 2
    assert "if: steps.deployment.outcome == 'failure'" in wf
    assert "out/logs/scheduler/" in (REPO / ".gitignore").read_text(encoding="utf-8")
    assert len((REPO / "docs/scheduler.md").read_text(encoding="utf-8").splitlines()) <= 80
    assert time.time() > 0


def test_stages_write_utf8_and_the_final_print_cannot_fail(tmp_path, monkeypatch):
    # P-8.09: run 1 pushed, then crashed printing a U+FFFD to a cp1252 console (exit 1)
    import subprocess
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(cmd, 0, "site built \u00b7 ok", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    rc, out = chain._run(tmp_path, ["factory.site"])
    assert rc == 0 and "\u00b7" in out
    assert seen["env"]["PYTHONUTF8"] == "1" and seen["env"]["PYTHONIOENCODING"] == "utf-8"
    src = (REPO / "src/factory/chain.py").read_text(encoding="utf-8")
    assert 'sys.stdout.reconfigure(encoding="utf-8", errors="replace")' in src


def test_a_failed_behavioral_stage_alone_is_a_partial_run(tmp_path):
    # Amin, 4 Oct: exit 2 (0x2) when only the behavioral stage failed; its reason is logged
    st = tmp_path / "out/behavioral/status.json"
    st.parent.mkdir(parents=True)
    st.write_text('{"ok": false, "reason": "the request returned HTTP 503"}')
    git, (run, _ran) = Git(), runner_with(fail="factory.behavioral")
    code, log = chain.chain(tmp_path, "monthly", "LUSD", runner=run, git=git,
                            server=lambda: "0.34.4", now=NOW)
    assert code == 2 and log[-1] == "exit 2: partial, failed behavioral"
    assert "behavioral not refreshed: the request returned HTTP 503" in log
    git2, (run2, _r) = Git(), runner_with(fail="factory.tree")
    code2, _l = chain.chain(tmp_path, "monthly", "LUSD", runner=run2, git=git2,
                            server=lambda: "0.34.4", now=NOW)
    assert code2 == 1
