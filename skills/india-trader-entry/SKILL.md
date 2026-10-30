---
name: india-trader-entry
description: Check the first closed five-minute breakout above an Indian equity opening range. Use for entry-timing research.
---

# India Trader: Entry

Run the bundled standard-library Python 3.9+ engine with an explicit project workspace:

```bash
python3 "${CLAUDE_SKILL_DIR}/runner.py" --workspace /absolute/project/trader entry NSE:RELIANCE
```

In Codex, substitute this SKILL.md folder's absolute path for `${CLAUDE_SKILL_DIR}`; do not assume that Claude variable exists. For reproducible research only, place `--now 2026-10-19T09:35:00+05:30` before the command. Omit `--now` for the actual clock.

A bar timestamp marks its open. A signal is known only five minutes later. The first fifteen minutes require all three bars. Missing intermediate candles make the signal unavailable. A previous trigger is not a current recommendation; inspect entry_time and run risk with fresh quotes.

Use `runner.py --workspace PATH setup --interactive` for guided connected/demo setup, or `serve --demo` for the synthetic daily desk. `doctor`, `status` and `sync` expose health and refresh data. `init` remains a legacy import workflow. Read config.json, calendar.json, instruments.json and input provenance before interpreting a result. Never substitute demo data for missing market observations. Currency is INR and all sessions are IST. NSE and BSE symbols remain exchange-specific.

Use only long standard-lot cash equities. The implemented workflow uses no derivatives, short selling, leverage or live order submission. Unknown calendar dates fail closed; verify holidays, auctions, special sessions and broker cutoffs in official sources. Configured example limits and costs require user review for actual research. A plan stop cannot guarantee its fill price.

Read [data contracts](../../docs/schemas.md) when preparing inputs and [methodology](../../docs/methodology.md) when interpreting research results.

For foreground monitoring with broker refresh: `runner.py --workspace PATH watch entry --broker zerodha --instrument NSE:RELIANCE --every 30 --polls 20`. Watch uses the actual clock and stops when triggered or expired.


For the v0.2 daily workflow use `serve` (add `--collect` only for a connected workspace), `desk today`, `desk review`, `decision`, `replay`, `fees` and `filings`. Read [connection guide](../../docs/onboarding.md) and [release status](../../docs/release-status.md). Enter credentials only through the user's local hidden `auth` prompt or environment; never request them in chat. Do not claim an authenticated integration, reconciled charges, complete source coverage or 20-session validation from synthetic/offline checks.
