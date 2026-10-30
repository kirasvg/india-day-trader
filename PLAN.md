# Implementation plan

Historical v0.1 build plan. The subsequent [Indian-market research](docs/research/2026-10-30-indian-market-research.md) found market-model and operational gaps beyond the initial offline tests. Future work is prioritized in [ROADMAP.md](ROADMAP.md); completion of the checklist below does not establish readiness for daily market use.

Build an original, MIT-licensed Indian cash-equity counterpart to the day-trader-skill concept, with eleven skills and a shared standard-library Python engine. Support Groww and Zerodha first.

## Stages

1. Market model: explicit IST sessions, exact exchange symbols, instrument tick sizes, whole-share quantities, INR accounts and conservative cash funding.
2. Data: official GET-only Groww and Kite adapters for quotes and five-minute candles, normalized CSV imports and instrument-master imports. No dependence on undocumented exchange JSON endpoints.
3. Signals: fifteen-minute opening-range breakout scanner, closed-bar entry checks, midpoint stops and configurable R targets.
4. Trade research: seeded time-of-day resampling, independent historical strategy replay, cost-aware position sizing and deterministic risk limits.
5. Operations: paper journal, manual broker tickets, stop/target/time alerts, RSS news monitoring, structured earnings comparisons and exchange disclosure monitoring.
6. Distribution: eleven discoverable skills, cross-platform installer, examples, schemas, sources, README, license and CI.
7. Verification: offline broker contract tests, financial invariants, no-look-ahead checks, state integrity and a complete synthetic demo. Package a clean archive.

## Scope and completion criteria

- Long cash equities on NSE/BSE. Derivatives, short selling, borrowing, leverage and live order submission are outside this release.
- Local paper fills are explicitly simulated; broker payloads are drafts for manual use. A plan stop does not become an exchange order.
- Calendar entries must be supplied explicitly per exchange and date. Unknown dates fail closed, including holidays and special sessions. No claim of an automatically current holiday calendar.
- Configured costs are estimates, not a statutory tax calculator. Broker cutoffs and auctions vary; use verified session overrides and a conservative flat-by time.
- A skill exists only when its CLI workflow works and its inputs/limitations are documented. News/disclosures use supplied official RSS feeds or normalized exports; earnings use sourced structured financial statements.
- Account-authenticated integration tests require user-managed broker credentials and are reported separately from offline tests.

## Progress

- [x] Official NSE, Groww and Kite interfaces reviewed (2026-10-30).
- [x] Initial core and data-adapter implementation.
- [x] CLI and all eleven workflows, including bounded foreground monitoring and multi-symbol candle merging.
- [x] Eleven skills, standalone installation, provider setup, data contracts, methodology and sources.
- [x] 60 offline regression tests on Python 3.9 and 3.12; eleven-workflow demo; installed-wheel 10,000-replay smoke test.
- [x] Source review, local Git initialization and release packaging. See docs/validation.md for exact validation scope.

Account-authenticated integration testing and GitHub publication remain external follow-up steps, explicitly outside the completed local build. No broker credentials were requested or used.
