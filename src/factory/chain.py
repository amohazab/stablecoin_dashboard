"""`uv run python -m factory.chain --monthly --token <T> | --weekly [--dry-run]` - Step 8
phase B's unattended chain (P-8.04 Q9), run by Windows Task Scheduler through
`tools/scheduler/run_{monthly,weekly}.cmd` (docs/scheduler.md).

Monthly, one token per night (days 1/2/3):
  factory.run T -> factory.tree T -> factory.stress T -> factory.report T --llm
then, as for the weekly run:
  factory.behavioral -> factory.site -> key scan -> git add -A out/ -> commit -> push
so the site updates as each token lands (Amin, P-8.04 Q9). A stage that exits non-zero stops
the later token stages and is logged; the behavioral/site/commit/push tail still runs, so the
evidence of a failed loop is committed and the site keeps its last published pages (Q7).
A report outcome other than `published` is not a stage failure - the record and the log
line are the evidence. The push always comes last.

Fail-closed, each logged: a dirty working tree (refused before anything runs); another chain
holding the lock (exits "busy"); the model server unreachable (`GET /api/version`, monthly
only - no auto-start); a key value or key assignment in any staged file (no commit, no push).
One log per run at `out/logs/scheduler/<UTC stamp>-<mode>.log` (gitignored); any failure
exits non-zero.

`--dry-run` runs no stage, calls no model and pushes nothing: it checks the tree, takes and
releases the lock, reads the server version, and logs the plan it would run.

NAMED DEFAULTS: the lock is `out/logs/scheduler/chain.lock`, treated as stale after 12 hours
(Task Scheduler stops a run at 12 h); the commit message is "chain <mode> <UTC stamp>:
<outcomes>".
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import re
import subprocess
import sys
from collections.abc import Callable

TOKENS = ("crvUSD", "GHO", "LUSD")
STALE_LOCK_S = 12 * 3600
# any `NAME_KEY=value` or `NAME_URL=value` assignment with a value (the export scan's rule,
# widened); the values themselves are compared for the three keys the pipeline reads
KEY_ASSIGNMENT = re.compile(r"\b[A-Z][A-Z0-9_]*_(?:KEY|URL)=[^\s\"'`]+")
KEY_NAMES = ("ETH_RPC_URL", "WEBACY_API_KEY", "ETHERSCAN_API_KEY")


def plan(mode: str, token: str | None) -> list[tuple[str, list[str]]]:
    """The stages, in order: (name, argv after `python -m`)."""
    steps = []
    if mode == "monthly":
        steps += [(f"run {token}", ["factory.run", token]),
                  (f"tree {token}", ["factory.tree", token]),
                  (f"stress {token}", ["factory.stress", token]),
                  (f"report {token}", ["factory.report", token, "--llm"])]
    return steps + [("behavioral", ["factory.behavioral"]), ("site", ["factory.site"])]


def _run(repo: pathlib.Path, argv: list[str]) -> tuple[int, str]:
    # P-8.09: the stages write UTF-8 into the pipe, whatever the console's code page
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    p = subprocess.run([sys.executable, "-m", *argv], cwd=repo, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _git(repo: pathlib.Path, *args: str) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _server(url: str = "http://localhost:11434") -> str:
    import requests
    return requests.get(f"{url}/api/version", timeout=10).json()["version"]


def _status(repo: pathlib.Path) -> dict | None:
    p = repo / "out/behavioral/status.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def key_hits(repo: pathlib.Path, names: list[str]) -> list[str]:
    """The staged files carrying a key assignment or a key value (the export scan's rule)."""
    from factory.logs_pointer import env
    values = [v for v in (env(repo, k) for k in KEY_NAMES) if v and len(v) > 8]
    values += [v.rstrip("/").split("/")[-1] for v in values if "/" in v]
    values = [v for v in values if len(v) > 12]
    hits = []
    for n in names:
        p = repo / n
        if not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        if KEY_ASSIGNMENT.search(text) or any(v in text for v in values):
            hits.append(n)
    return hits


def _pid_alive(pid: int) -> bool:
    """Whether a process with this id exists (Windows: OpenProcess and its exit code)."""
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)                 # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259                  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class Lock:
    def __init__(self, path: pathlib.Path, now: float):
        self.path, self.now, self.held = path, now, False

    def acquire(self) -> str | None:
        """None when taken; else the reason it is busy."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            age = self.now - self.path.stat().st_mtime
            try:
                pid = json.loads(self.path.read_text())["pid"]
            except Exception:
                pid = None
            if pid is not None and not _pid_alive(pid):       # Amin, 4 Oct: a dead holder
                self.path.unlink()
                age = STALE_LOCK_S
            if age < STALE_LOCK_S and self.path.exists():
                return f"busy: {self.path.name} held for {age:.0f} s ({self.path.read_text()})"
            self.path.unlink(missing_ok=True)                   # stale: a killed run
        self.path.write_text(json.dumps({"pid": os.getpid(), "since": self.now}))
        self.held = True
        return None

    def release(self) -> None:
        if self.held and self.path.exists():
            self.path.unlink()


def outcome_of(output: str) -> str | None:
    m = re.search(r"^outcome (\S+)", output, re.M)
    return m[1] if m else None


def chain(repo: pathlib.Path, mode: str, token: str | None, dry_run: bool = False,
          runner: Callable = _run, git: Callable = _git, server: Callable = _server,
          now: _dt.datetime | None = None) -> tuple[int, list[str]]:
    """Run the chain; returns (exit code, log lines). The log is also written to disk."""
    now = now or _dt.datetime.now(_dt.UTC)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    log: list[str] = [f"chain {mode}{' ' + token if token else ''} {stamp}"
                      f"{' (dry run)' if dry_run else ''}"]
    logdir = repo / "out/logs/scheduler"
    code, failed, outcomes = 0, [], []

    def done() -> tuple[int, list[str]]:
        logdir.mkdir(parents=True, exist_ok=True)
        (logdir / f"{stamp}-{mode}.log").write_text("\n".join(log) + "\n", encoding="utf-8")
        return code, log

    if mode == "monthly" and token not in TOKENS:
        log.append(f"FAIL: --monthly needs --token one of {TOKENS}")
        code = 2
        return done()
    rc, status = git(repo, "status", "--porcelain")
    if rc != 0 or status.strip():
        log.append(f"FAIL: working tree not clean:\n{status.strip()}")
        code = 1
        return done()
    lock = Lock(logdir / "chain.lock", now.timestamp())
    busy = lock.acquire()
    if busy:
        log.append(f"FAIL: {busy}")
        code = 1
        return done()
    try:
        if mode == "monthly":
            try:
                log.append(f"ollama {server()}")
            except Exception as exc:
                log.append(f"FAIL: model server unreachable: {type(exc).__name__}: {exc}"[:300])
                failed.append("ollama")
        stop_token = bool(failed)
        for name, argv in plan(mode, token):
            is_token_stage = name.split()[0] in ("run", "tree", "stress", "report")
            if is_token_stage and stop_token:
                log.append(f"skip {name}: an earlier stage failed")
                continue
            if dry_run:
                log.append(f"plan {name}: python -m {' '.join(argv)}")
                continue
            rc, out = runner(repo, argv)
            tail = "\n".join(out.strip().splitlines()[-6:])
            log.append(f"{'ok' if rc == 0 else 'FAIL'} {name} (exit {rc})\n{tail}")
            if name.startswith("report"):
                outcomes.append(f"{token} {outcome_of(out) or 'no outcome'}")
            if name == "behavioral":                            # Ruling 1: the disclosed reason
                st = _status(repo)
                if st and not st.get("ok"):
                    log.append(f"behavioral not refreshed: {st.get('reason')}")
            if rc != 0:
                failed.append(name)
                stop_token = stop_token or is_token_stage
        if dry_run:
            log.append("plan: key scan -> git add -A out/ -> commit -> push (not run)")
        else:
            git(repo, "add", "-A", "out/")
            _rc, staged = git(repo, "diff", "--cached", "--name-only")
            names = [x for x in staged.split() if x]
            hits = key_hits(repo, names)
            if hits:
                log.append(f"FAIL: key found in staged files {hits}; nothing committed")
                git(repo, "reset", "-q")
                failed.append("key scan")
            elif not names:
                log.append("nothing to commit")
            else:
                summary = "; ".join(outcomes) or "site refresh"
                if failed:
                    summary += f"; failed: {', '.join(failed)}"
                rc, out = git(repo, "commit", "-q", "-m", f"chain {mode} {stamp}: {summary}")
                log.append(f"{'ok' if rc == 0 else 'FAIL'} commit ({len(names)} files): {summary}")
                if rc != 0:
                    failed.append("commit")
                else:
                    rc, out = git(repo, "push", "origin", "master")
                    log.append(f"{'ok' if rc == 0 else 'FAIL'} push\n{out.strip()[-300:]}")
                    if rc != 0:
                        failed.append("push")
    finally:
        lock.release()
    # Amin, 4 Oct: a failed behavioral stage alone is a partial run, exit 2 (0x2); any other
    # failure is exit 1
    code = 0 if not failed else 2 if failed == ["behavioral"] else 1
    label = {0: "", 1: ": failed ", 2: ": partial, failed "}[code]
    log.append(f"exit {code}{label + ', '.join(failed) if failed else ''}")
    return done()


if __name__ == "__main__":
    # P-8.09: printing the log can never fail the run after its push (a cp1252 console
    # raised UnicodeEncodeError and turned a pushed run into exit 1)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = sys.argv[1:]
    mode = "monthly" if "--monthly" in args else "weekly" if "--weekly" in args else None
    tok = args[args.index("--token") + 1] if "--token" in args else None
    if mode is None:
        print("usage: python -m factory.chain --monthly --token <T> | --weekly [--dry-run]")
        sys.exit(2)
    _code, _log = chain(pathlib.Path(__file__).resolve().parents[2], mode, tok,
                        dry_run="--dry-run" in args)
    print("\n".join(_log))
    sys.exit(_code)
