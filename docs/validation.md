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
- GitHub Actions is configured for Linux Python 3.9–3.14 plus Python 3.12 on macOS and Windows. Local execution above is distinct from hosted CI; see the [actual GitHub Actions runs](https://github.com/kirasvg/india-day-trader/actions). The public source is published as a research preview.


Session qualification now requires known candle coverage, full session span, continuous heartbeat, ≥99% healthy market samples, fresh quotes and complete account snapshots, and unchanged watchlist/policy/interval. Tests cover both rejection cases and a complete simulated healthy session passing through the recorder. Such unit-test sessions exist only in disposable test directories and are never installed as actual observations. Cycle and processing p95 latency use nearest-rank summaries.

## Upstox data-only integration

Executed locally on 30 October 2026 for this change:

- Python 3.9.6: **187 tests passed**, including both explicitly enabled loopback HTTP tests.
- All eleven synthetic CLI workflows passed; no real orders or account connections were used.
- All eleven portable skill bundles installed into a temporary destination; the broker runner configured Upstox mode outside the source checkout. Updated broker/alerts skill validators passed.
- Ruff lint/format, engine type checking, JavaScript syntax, notification behavior, workflow lint and offline workflow-security checks passed.
- The real public Upstox NSE instrument master downloaded and parsed: 2,714 supported normal cash equities; INFY mapped to `NSE_EQ|INE009A01021`, tick ₹0.05; RELIANCE to `NSE_EQ|INE002A01018`, tick ₹0.10. Both supplied an explicit CAS flag. This public-file check required no credentials and is not authenticated quote/history validation.


Synthetic adapter and workflow tests cover quote identity/timestamps/depth, paise tick conversion, missing CAS classification, historical/current-day splitting, closed-bar filtering, redacted auth errors, endpoint restrictions, manual exposure preservation and stale/overlap/cash risk checks. They do not prove real-token access, latency, reconnect reliability or Groww account exposure. Live REST polling and optional browser notifications require an awake local machine. Authenticated Upstox validation and 20 actual sessions remain pending. See [connection guide](upstox-free-data.md).

## Combined Upstox feed and Groww account (31 October 2026)

The configured combined mode is covered by synthetic tests for role-separated GET calls, complete/partial account reads, expired and missing account tokens, ISIN exposure matching, independent Keychain clearing, dual-role validation provenance and observation-role changes. Account access under Groww’s advertised ₹0 trial has not been authenticated here; eligibility, duration and renewal terms remain unverified. No real orders are implemented and actual observed sessions remain 0/20. Final software check results are recorded in the pull request.

Local checks for the combined-provider change: **200 tests passed** on Python 3.9.6, including all three enabled loopback HTTP tests. All eleven synthetic workflows and the synthetic evidence tour passed. All eleven portable skills installed; the broker runner configured combined mode outside the checkout, and the two updated skill validators passed. Ruff, engine type checks, JavaScript syntax/notification behavior, actionlint and offline zizmor passed. These results are software checks, not authenticated Groww trial or Upstox account validation.
