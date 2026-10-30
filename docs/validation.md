# v0.3 validation report

Executed **30 October 2026**. This report separates demonstrated software behavior from actual broker-account access and market-session evidence. The [delivery matrix](release-status.md) lists remaining work across all seven stages.

| Executed check | Result |
| --- | --- |
| Offline unit/integration suite, Python 3.9.6 | 169 tests passed; isolated socket test skipped in the default suite |
| Same suite, Python 3.12.14 | 169 tests passed; isolated socket test skipped in the default suite |
| Eleven-workflow synthetic CLI demo | Passed, both manual tickets and paper roundtrip |
| Eleven SKILL.md validators | All passed |
| Temporary independent skill installation | All eleven installed; portable desk runner/web assets present; overwrite refused |
| Offline synthetic evidence tour | Both provider note examples match their invented charges; fake probes/context pass; all actual gates remain open, 0/20 sessions |
| Public NSE feed check | Seven sources checked; dated current announcements/integrated financials/actions/board/insider observations, stale legacy financial results and unverified pledge dates retained in the [actual report](research/public-context-smoke-2026-10-30.json) |
| JavaScript syntax | `node --check` passed |
| Local browser | Paper-track, tracked state/duplicate block, journal note persistence, chronological replay with held-out results, fresh Groww setup form, actionable missing-data health, labelled ETF context and per-provider release evidence verified |
| Isolated local HTTP integration (opt-in test passed separately) | Host/Origin/fetch guards, CSRF token, duplicate fill refusal, atomic close/journal, synthetic validation exclusion, static assets, path whitelist, new context/evidence routes and demo network guards passed |
| Wheel | v0.3 built without runtime dependencies; installed outside checkout; web/templates/setup/doctor/desk/paper roundtrip/replay/fees and new context/evidence/reconciliation/observer modules passed |

## What the checks establish

Tests cover closed-bar timing, missing candles, dynamic 72/75-bar and special-session grids, current/future CAS policy activation, holiday/election addendum, unknown BSE/year/Muhurat rules, dated tick versions, no backdated master observations, reviewed broker eligibility, quote freshness, circuit/depth guards, position/risk/cash limits, daily reserved risk, edited-order rechecks, duplicate paper actions, concurrent account writes, SQLite-authoritative recovery and atomic paper lifecycle changes.

Fee checks cover per-order caps/minimums, different buy/sell tax bases, duplicate partial-fill IDs, whole-share quantities, unavailable historical/BSE schedules, smallest profitable breakeven tick and reconciliation mismatches. New daily note checks cover multiple fills per order, per-instrument balance, scope/completeness, totals, component errors that offset, source hashes, immutable paper balances and synthetic evidence exclusion. Contract-note daily rounding is explicitly not certified.

Research/source checks cover causal next-bar-open entry, chronological split, exclusion of current/future sessions and missing fee history, reproducible identities, source revisions, future publication, unsupported units/periods, XBRL external-entity rejection and conflicting quarterly facts. OHLC replay cannot establish actual fills or a trading edge.

Account adapter contract checks cover complete account components, conservative cash, cross-exchange overlap, unknown open-order statuses, pagination refusal and batched quote completeness. Credentials/login tests use fake values and mocks; no actual Keychain or private broker session was accessed.

Browser testing uses local synthetic state and illustrative wizard values. The synthetic replay displays losses rather than selected winning outcomes. Its results are not market evidence. The browser console had no errors/warnings in the verified fresh setup flow.

## Open gates

- **0/20 actual connected market sessions observed.** Scorecard tests use synthetic unit-test inputs; those inputs are not shipped as actual observations. Demo sessions are explicitly excluded.
- No authenticated Groww/Kite requests, paid subscriptions, actual portfolio reconciliation or contract-note validation. Real provider response variation, rate quotas and entitlements require a private account session.
- No actual orders, modifications, cancellations or real fills. Order mutation endpoints are not implemented.
- No official complete historical calendar/security eligibility service, automated surveillance ingestion, corporate-action/universe reconstruction, complete filing coverage or broad earnings/PDF extraction. Broker ETF proxies are implemented and offline-tested; authenticated proxy responses and whole-market breadth remain unvalidated.
- The resumable foreground observation campaign is implemented, including dated windows, one-workspace locking, separate context collection, backoff and health measurement. No OS service/Codex automation is installed, and no campaign with actual credentials has started. The machine must remain awake and connected. Streaming remains unimplemented.
- No profitability or calibrated probability claim. Chronological holdout is descriptive; research assumptions and repeated trials require review.
- GitHub Actions is configured for Python 3.9/3.11/3.13. Local execution above is distinct from a GitHub CI run. No repository has been published remotely.


Session qualification now requires known candle coverage, full session span, continuous heartbeat, ≥99% healthy market samples, fresh quotes and complete account snapshots, and unchanged watchlist/policy/interval. Tests cover both rejection cases and a complete simulated healthy session passing through the recorder. Such unit-test sessions exist only in disposable test directories and are never installed as actual observations. Cycle and processing p95 latency use nearest-rank summaries.
