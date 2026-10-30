---
name: india-trader-analyst
description: Compare sourced Indian quarterly revenues, profits and EPS with consistent units and reporting basis. Use for earnings arithmetic.
---

# India Trader: Analyst

Run the bundled standard-library Python 3.9+ engine with an explicit project workspace:

```bash
python3 "${CLAUDE_SKILL_DIR}/runner.py" --workspace /absolute/project/trader analyst --file /absolute/path/to/financials.json
```

In Codex, substitute this SKILL.md folder's absolute path for `${CLAUDE_SKILL_DIR}`; do not assume that Claude variable exists. For reproducible research only, place `--now 2026-10-19T09:35:00+05:30` before the command. Omit `--now` for the actual clock.

Input must contain sourced three-month quarters with period_end, published_at, revenue, net_profit, eps, unit and standalone/consolidated basis. Only data published by --now are considered. Never mix basis or units. Zero/negative prior values have undefined percentage growth; explain absolute changes. The tool does not extract PDFs, retrieve all company filings or make forecasts. Read the schema in the repository docs before constructing financial inputs.

Use `runner.py --workspace PATH setup --interactive` for guided connected/demo setup, or `serve --demo` for the synthetic daily desk. `doctor`, `status` and `sync` expose health and refresh data. `init` remains a legacy import workflow. Read config.json, calendar.json, instruments.json and input provenance before interpreting a result. Never substitute demo data for missing market observations. Currency is INR and all sessions are IST. NSE and BSE symbols remain exchange-specific.

Use only long standard-lot cash equities. The implemented workflow uses no derivatives, short selling, leverage or live order submission. Unknown calendar dates fail closed; verify holidays, auctions, special sessions and broker cutoffs in official sources. Configured example limits and costs require user review for actual research. A plan stop cannot guarantee its fill price.

Read [data contracts](../../docs/schemas.md) when preparing inputs and [methodology](../../docs/methodology.md) when interpreting research results.


For the v0.2 daily workflow use `serve` (add `--collect` only for a connected workspace), `desk today`, `desk review`, `decision`, `replay`, `fees` and `filings`. Read [connection guide](../../docs/onboarding.md) and [release status](../../docs/release-status.md). Enter credentials only through the user's local hidden `auth` prompt or environment; never request them in chat. Do not claim an authenticated integration, reconciled charges, complete source coverage or 20-session validation from synthetic/offline checks.


For private release gates use `validate broker --broker groww|zerodha`, `reconcile --file REVIEWED.json --source-file ORIGINAL.pdf`, `context refresh`, `observe run --sessions 20`, and `validate readiness`. See [gate workflow](../../docs/finishing-the-gates.md). Synthetic notes/mocks are examples only. Do not change evidence origin, review flags or effective dates to force a pass. Actual observation commands reject clock overrides and need real elapsed sessions.
