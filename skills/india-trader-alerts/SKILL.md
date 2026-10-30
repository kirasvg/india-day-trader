---
name: india-trader-alerts
description: Check Indian equity paper plans for stop, target, stale data or flat-by conditions. Use for local price and time alerts.
---

# India Trader: Alerts

Run the bundled standard-library Python 3.9+ engine with an explicit project workspace:

```bash
python3 "${CLAUDE_SKILL_DIR}/runner.py" --workspace /absolute/project/trader alerts
```

In Codex, substitute this SKILL.md folder's absolute path for `${CLAUDE_SKILL_DIR}`; do not assume that Claude variable exists. For reproducible research only, place `--now 2026-10-19T09:35:00+05:30` before the command. Omit `--now` for the actual clock.

One invocation is one poll. Active conditions are always returned; new_events are deduplicated per plan. Time alerts can fire without fresh prices. DATA_STALE does not mean a safe position. Use `runner.py --workspace PATH watch alerts --broker groww --every 30 --polls 20` for bounded foreground polling with quote refresh. This does not close a position or install a background service. If recurring monitoring is requested, use the host scheduler with appropriate user authorization and report its latency.

Use `runner.py --workspace PATH setup --interactive` for guided connected/demo setup, or `serve --demo` for the synthetic daily desk. `doctor`, `status` and `sync` expose health and refresh data. `init` remains a legacy import workflow. Read config.json, calendar.json, instruments.json and input provenance before interpreting a result. Never substitute demo data for missing market observations. Currency is INR and all sessions are IST. NSE and BSE symbols remain exchange-specific.

Use only long standard-lot cash equities. The implemented workflow uses no derivatives, short selling, leverage or live order submission. Unknown calendar dates fail closed; verify holidays, auctions, special sessions and broker cutoffs in official sources. Configured example limits and costs require user review for actual research. A plan stop cannot guarantee its fill price.

Read [data contracts](../../docs/schemas.md) when preparing inputs and [methodology](../../docs/methodology.md) when interpreting research results.


For the v0.2 daily workflow use `serve` (add `--collect` only for a connected workspace), `desk today`, `desk review`, `decision`, `replay`, `fees` and `filings`. Read [connection guide](../../docs/onboarding.md) and [release status](../../docs/release-status.md). Enter credentials only through the user's local hidden `auth` prompt or environment; never request them in chat. Do not claim an authenticated integration, reconciled charges, complete source coverage or 20-session validation from synthetic/offline checks.


For private release gates use `validate broker --broker groww|zerodha`, `reconcile --file REVIEWED.json --source-file ORIGINAL.pdf`, `context refresh`, `observe run --sessions 20`, and `validate readiness`. See [gate workflow](../../docs/finishing-the-gates.md). Synthetic notes/mocks are examples only. Do not change evidence origin, review flags or effective dates to force a pass. Actual observation commands reject clock overrides and need real elapsed sessions.


For a free data connection with manual Groww execution, use `setup --broker groww --data-provider upstox` in a new private workspace, then hidden local `auth --broker upstox --flow token`, `sync` and `serve --collect`. Read [Upstox free-data setup](../../docs/upstox-free-data.md). `broker` remains the execution provider for fees/eligibility/cutoffs; `data_provider` supplies quotes/candles. Never call the Upstox account or order APIs in this mode. User-confirmed exposure is `MANUAL_ATTESTED`, expires after 120 seconds for entry checks, and is not authenticated evidence. Keep actual Groww fills separate from paper positions. Browser notifications require an open page, running collector and user-granted permission; they are not guaranteed real-time exits. Missing rules or stale data continue to block plans.
