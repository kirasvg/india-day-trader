---
name: india-trader-risk
description: Check an Indian cash-equity paper order against fresh quotes, session times and INR limits. Use before any paper fill or broker ticket.
---

# India Trader: Risk

Run the bundled standard-library Python 3.9+ engine with an explicit project workspace:

```bash
python3 "${CLAUDE_SKILL_DIR}/runner.py" --workspace /absolute/project/trader risk
```

In Codex, substitute this SKILL.md folder's absolute path for `${CLAUDE_SKILL_DIR}`; do not assume that Claude variable exists. For reproducible research only, place `--now 2026-10-19T09:35:00+05:30` before the command. Omit `--now` for the actual clock.

BLOCK ends the order workflow until the reason is resolved. Recheck changed orders and refresh quotes; broker commands independently re-run risk. Explain net reward/risk and estimated loss including configured costs. Daily risk reserves every paper entry for the day, even if later profitable. No exact daily loss or gap guarantee is implied. Unknown sessions and unverified instrument metadata block.

Use `runner.py --workspace PATH setup --interactive` for guided connected/demo setup, or `serve --demo` for the synthetic daily desk. `doctor`, `status` and `sync` expose health and refresh data. `init` remains a legacy import workflow. Read config.json, calendar.json, instruments.json and input provenance before interpreting a result. Never substitute demo data for missing market observations. Currency is INR and all sessions are IST. NSE and BSE symbols remain exchange-specific.

Use only long standard-lot cash equities. The implemented workflow uses no derivatives, short selling, leverage or live order submission. Unknown calendar dates fail closed; verify holidays, auctions, special sessions and broker cutoffs in official sources. Configured example limits and costs require user review for actual research. A plan stop cannot guarantee its fill price.

Read [data contracts](../../docs/schemas.md) when preparing inputs and [methodology](../../docs/methodology.md) when interpreting research results.


For the v0.2 daily workflow use `serve` (add `--collect` only for a connected workspace), `desk today`, `desk review`, `decision`, `replay`, `fees` and `filings`. Read [connection guide](../../docs/onboarding.md) and [release status](../../docs/release-status.md). Enter credentials only through the user's local hidden `auth` prompt or environment; never request them in chat. Do not claim an authenticated integration, reconciled charges, complete source coverage or 20-session validation from synthetic/offline checks.


For private release gates use `validate broker --broker groww|zerodha`, `reconcile --file REVIEWED.json --source-file ORIGINAL.pdf`, `context refresh`, `observe run --sessions 20`, and `validate readiness`. See [gate workflow](../../docs/finishing-the-gates.md). Synthetic notes/mocks are examples only. Do not change evidence origin, review flags or effective dates to force a pass. Actual observation commands reject clock overrides and need real elapsed sessions.
