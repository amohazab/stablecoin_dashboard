# Unattended runs on the laptop (Step 8 phase B)

The pipeline runs by itself through Windows Task Scheduler and the local Ollama model
(P-8.04). Four tasks are needed: one weekly, and three monthly tasks (one token per night).

## What runs

| task | when | what it does |
|---|---|---|
| stablecoin weekly | Sundays 03:00 | Webacy fetch → site build → commit → push |
| stablecoin monthly crvUSD | day 1, 01:00 | crvUSD: run → tree → stress → report, then the weekly steps |
| stablecoin monthly GHO | day 2, 01:00 | the same for GHO |
| stablecoin monthly LUSD | day 3, 01:00 | the same for LUSD |

Each monthly task ends with the site build, commit and push, so the site updates as each token
lands. A push that changes `out/site/` deploys the site to GitHub Pages; other pushes deploy
nothing. A token whose report is not published keeps its last published page; the attempt is
in the log. Each run writes `out\logs\scheduler\<time>-<mode>.log`, and a run that fails exits
with an error code, which Task Scheduler shows as "Last Run Result" other than 0x0.

Before the first run, check the chain without running anything (no model, no push):

    cd D:\projects\stable_dashboard
    uv run python -m factory.chain --monthly --token LUSD --dry-run

## Once: the two Ollama settings

1. Press Start, type **environment**, open **Edit environment variables for your account**.
2. Under **User variables**, click **New…**: name `OLLAMA_FLASH_ATTENTION`, value `1`, OK.
3. Click **New…** again: name `OLLAMA_KV_CACHE_TYPE`, value `q8_0`, OK. Then OK to close.
4. Right-click the Ollama icon by the clock → **Quit Ollama**, then start Ollama from Start.
5. Ollama must be running when a task starts: leave "start at login" on (Ollama's default).

## Once per task: create it

1. Press Start, type **Task Scheduler**, open it.
2. In the right pane click **Create Task…** (not "Create Basic Task").
3. **General** tab: Name, for example `stablecoin weekly`. Choose **Run only when user is
   logged on**, and tick **Hidden** at the bottom, so no console window is left open to
   close by mistake. Leave "Run with highest privileges" unticked.
4. **Triggers** tab → **New…**:
   - weekly: **Weekly**, start today at **03:00:00**, recur every 1 week, tick **Sunday**;
   - monthly: **Monthly**, start at **01:00:00**, Months: **Select all months**, Days: **1**
     (crvUSD), **2** (GHO) or **3** (LUSD). OK.
5. **Actions** tab → **New…** → Action **Start a program**:
   - Program/script: `D:\projects\stable_dashboard\tools\scheduler\run_weekly.cmd`
     (monthly: `...\run_monthly.cmd`)
   - Add arguments: nothing for weekly; `crvUSD`, `GHO` or `LUSD` for the monthly tasks
   - Start in: `D:\projects\stable_dashboard`. OK.
6. **Conditions** tab: untick **Wake the computer to run this task**. "Start the task only if
   the computer is on AC power" is ticked by default: keep it and leave the laptop plugged in
   on run nights, or untick it to allow runs on battery.
7. **Settings** tab: tick **Run task as soon as possible after a scheduled start is missed**;
   tick **Stop the task if it runs longer than** and choose **12 hours**; at the bottom, "If
   the task is already running": **Do not start a new instance**. OK.

## Check a task

- Right-click the task → **Run**: it starts now. Its window stays hidden; wait for "Last Run
  Result" to show 0x0 (success) or another code (failure), then read the newest file in
  `out\logs\scheduler\`.
- A missed start (the laptop was asleep or off) runs at the next wake-up.
- The push uses the same Git login as your own pushes (Git Credential Manager); the task runs
  as you, so it finds it.
- A second chain that starts while one is running stops at once with "busy" in its log.
