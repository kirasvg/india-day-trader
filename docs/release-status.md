# v0.3 stage-by-stage delivery status

As of 30 October 2026. This is a locally usable research/paper desk, with operational gates still open. Feature completion alone is not evidence of dependable execution or strategy profitability.

| Stage | Delivered software | Remaining release evidence / work |
| --- | --- | --- |
| 1. Market correctness | Explicit NSE 2026 days, holidays/election addendum, dated CAS changes, dynamic bar grids, tick history, eligibility/cutoff gates, review-age checks | BSE and later years; special-session timing; independently maintained eligibility/surveillance service; current-master classification inference checked on actual accounts |
| 2. Guided setup | Browser/terminal wizard, Groww/Kite hidden local connection, optional Keychain, read-only account sync, master/quote/history sync, diagnostics, retry/backfill collector | Authenticate both providers privately; verify entitlement/error cases and provider response variation; measure quota usage; optional SDK streaming |
| 3. Costs and risk | Dated published NSE intraday fees, component breakdown, per-order cap/min, whole-share sizing, breakeven/reconciliation, existing exposure/cash checks, immutable versioned plans | Daily component/scope reconciliation importer is implemented; actual representative contract notes remain pending; actual multi-account exposure aggregation; BSE/special funding/rounding profiles |
| 4. Daily desk | Local Today, Review, Research, Settings/Health; chart/context; paper-track/save/skip/pause; graceful unavailable states | Repeated user workflow/accessibility checks; notifications outside the open browser; production packaging/updater |
| 5. Evidence and journal | SQLite decisions/events/account, atomic updates, causal next-bar-open research replay, chronological split, all trial IDs, before/after paper outcomes | Original-note hash and normalized execution import implemented; actual plan/fill matching remains pending; historical universe/corporate-action reconstruction; richer execution models |
| 6. Sourced context | RSS/Atom and source-preserving event imports, revision identities, publication/receipt timestamps, bounded supported Ind-AS XBRL quarterly extraction | Seven official corporate feeds and broker market/banking/IT ETF proxies implemented; full exchange/sector coverage and breadth remain open; broad earnings taxonomy/PDF support; no missing-news all-clear claims |
| 7. Daily-use validation | Resumable actual-clock campaign, independent context collection and quote/account health scorecard; strict synthetic exclusion; target 20 qualified sessions | **0/20 real sessions observed in this build.** Run privately with actual accounts; review failures, latency, fee and account reconciliation before release |

## Architecture decision

Keep the deterministic core on Python 3.9+ standard library. Decimal handles money. SQLite handles immutable plans, journal events and atomic paper-account state. A dependency-free browser app talks to a same-origin loopback service. REST adapters use fixed provider origins, explicit timeouts and bounded retries. This avoids introducing SDK/runtime dependencies before they have been validated on the target account; streaming remains a measured future change.

Installed skills remain independent bundled copies for portability; the roadmap's single shared installation migration is still open. Each skill uses the same engine source, never its own money/session arithmetic. Workspace/schema migrations must preserve user journals before changing the packaging model.

## Acceptance gates

- Offline tests and the eleven-workflow demo pass on supported runtimes; installed distribution includes the web assets and templates.
- Browser tests demonstrate paper-track, duplicate prevention, notes, replay, health and the guided setup flow using explicitly synthetic data.
- Authenticate privately, inspect actual broker responses and reconcile fee estimates with contract notes. None of this is replaced by a mock contract test.
- Observe at least 20 qualified connected market sessions, with session coverage, near-open-to-close span and heartbeat continuity. Record provider failures and machine sleep. The local scorecard is operational evidence, not a tamper-proof audit.
- Review sourced context coverage and real planned-versus-actual outcomes separately; do not call an empty feed complete or an ORB replay a proven edge.

The public research-preview source is maintained at [kirasvg/india-day-trader](https://github.com/kirasvg/india-day-trader). Repository publication does not close the broker, note, context-completeness or observed-session gates.

The [gate completion guide](finishing-the-gates.md) documents placeholder paths, the no-network synthetic tour, current public-source observations and exact commands to supply real evidence later. No assumed inputs are counted as authenticated or observed evidence.
