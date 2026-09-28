# Stablecoin Dashboard

An automated factory for structural risk reports on stablecoins: it reads each token's backing
on-chain at one pinned block, scores how far that backing can be verified, and stress-tests it
with a model of the token's own liquidation mechanism. The thesis is that judgment belongs at
design time: an analyst rules once per archetype and once per token, and code enforces those
rulings on every run. Numbers never originate from a model: every figure comes from the data
table, through one formatter. The rulings, the gates and the record of decisions are the
artifact; the reports are samples of what it produces.

**Site:** https://amohazab.github.io/stablecoin_dashboard/

| token | last published block | prose written by | open notices on the page |
|---|---|---|---|
| LUSD | 26060799 | the local model, under the figure guard | none |
| crvUSD | 25974925 | API models, September evaluation runs | 3 kinds: gate failure, harness error, judge instability |
| GHO | 25974932 | API models, September evaluation runs | 4 kinds: freeze coverage below target, off-venue share 92.4%, gate failure, harness error |

## How it runs

Windows Task Scheduler on the author's laptop runs everything unattended. Weekly, it
refreshes the behavioral tier (peg, liquidity and holder data fetched from Webacy) and
rebuilds the site. Monthly, it runs the full chain for one token per night: on-chain reads,
the verifiability tree, the stress model, the report. Each run commits its record and pushes,
and a push that changes the site deploys it to GitHub Pages. A run that fails still commits
its evidence. The click-through is in [`docs/scheduler.md`](docs/scheduler.md).

## What is checked

96 registered rubric checks run in four stages: S0 config integrity (3), S1 adapter output
before analysis (23), S2 verifiability and stress output (41), and S3 the rendered report (29).
Every trigger declares a severity:
- Level 1 publishes with a visible notice;
- Level 2 withholds the token's report;
- Level 3 halts the pipeline for that token.

Every firing goes into a public log. Some things the checks and the loop actually caught:
- crvUSD's page printed "$6 of bad debt" beside "structurally zero" (two template sentences). No
  prose revision could reach it, so the fix went to the template. crvUSD's page still shows it
  until a crvUSD run publishes.
- The generation guard rejects any figure the data table does not print: for example "$260" and
  "0.00%" in GHO drafts, and "7 days" in a crvUSD draft, each refused before it reached a page.
- A blocked run keeps the last good page. crvUSD and GHO were blocked in each attempt from
  25 to 26 September; their pages did not change, and each attempt is in the log.

## Known limitations

- The LLM judge is withdrawn in the local configuration. A 9B local model failed a control run
  (it missed a planted wrong figure and flagged correct ones), so its six prose criteria are
  recorded as not evaluated. The deterministic checks still run on every page.
- LUSD's summaries are written by the local 9B model under the guard, with no second reviewer.
- crvUSD's and GHO's summaries come from the September API-model runs: the local model's drafts
  for those two tokens do not pass the guard.
- One archetype so far: collateralised debt positions (CDP).

## Reproduce a page

Python 3.12 with `uv`. Keys come from the environment or from `.env` at the repo root, by name:
`ETH_RPC_URL` (an archive node), `ETHERSCAN_API_KEY`, and `WEBACY_API_KEY` (behavioral tier).

    uv run python -m factory.run <TOKEN>       # pinned reads, S0/S1 gates, the bundle
    uv run python -m factory.tree <TOKEN>      # the verifiability tree (no RPC)
    uv run python -m factory.stress <TOKEN>    # the stress cells (reads at the bundle's block)
    uv run python -m factory.report <TOKEN>    # table, pages, report-stage gates
    uv run python -m factory.site              # the selector and methodology pages

`<TOKEN>` is `crvUSD`, `GHO` or `LUSD`. `factory.report <TOKEN> --llm` writes the prose with a
local [Ollama](https://ollama.com) server running `qwen3.5:9b`. Without `--llm` the run is a
rehearsal, and its pages stay in `out/rehearsal/`. Tests: `uv run python -m pytest`; lint:
`ruff check src tests`.

## Where the rulings live

- `docs/context/`: the design record, read in order. The brief sets the project; the CDP
  archetype memo makes the class-level rulings; the intake sheets instantiate them per token;
  the evaluator rubric (`rubic_v1.md`, filename as-is) owns every check and trigger.
- `PROGRESS.md`: one entry per confirmed decision, in order. Start at the Step 7 and Step 8
  status lines near the top. The AS-COUNTED lines record errors on both sides, the builder's
  and the design layer's.

## What is next

USDe, as the second archetype (a synthetic, delta-hedged dollar), with its report reconciled
against a manual benchmark. Then more tokens, chosen by archetype coverage.

## License

MIT; see [LICENSE](LICENSE).
