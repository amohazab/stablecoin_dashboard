# Stablecoin Dashboard

An automated factory for structural risk reports on stablecoins. Adapters read each
token's backing on-chain at one pinned block, a look-through tree scores how verifiable
that backing is, and a mechanism-specific stress model runs against it. Every run is checked
against a documented set of validation gates before a report publishes; the rulings and gates are
the project, and the reports are samples of its output.

**Site:** https://amohazab.github.io/stablecoin_dashboard/

| token | run block | status |
|---|---|---|
| LUSD | 25974949 | published through the full loop, 96/96 checks |
| crvUSD | 25974925 | published by ruling P-7.11, open notices shown on the page |
| GHO | 25974932 | published by ruling P-7.11, open notices shown on the page |

## Reproduce a page

Python 3.12 with `uv`. `ETH_RPC_URL` (an archive node) and `ETHERSCAN_API_KEY` come from
the environment or from `.env` at the repo root (names in `.env.example`).

    uv run python -m factory.run <TOKEN>       # pinned reads, S0/S1 gates, the bundle
    uv run python -m factory.tree <TOKEN>      # the verifiability tree (no RPC)
    uv run python -m factory.stress <TOKEN>    # the stress cells (reads at the bundle's block)
    uv run python -m factory.report <TOKEN>    # table, pages, report-stage gates
    uv run python -m factory.site              # the selector and methodology pages

`<TOKEN>` is `crvUSD`, `GHO` or `LUSD`. The report stage calls the Anthropic API only with
`--llm` (needs `ANTHROPIC_API_KEY`); without it the run is a rehearsal and its pages stay
in `out/rehearsal/`. Tests: `uv run python -m pytest`; lint: `ruff check src tests`.

## Where the rulings live

- `docs/context/` - the brief, the CDP archetype memo, the intake sheets and the
  evaluator rubric (`rubic_v1.md`, filename as-is): closed design artifacts.
- `PROGRESS.md` - the implementation record, one confirmed entry per decision or step.

No license file is included.
