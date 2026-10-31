# Data contracts

All files are UTF-8. Prices and money should be decimal strings to avoid binary float rounding. Explicit user input timestamps include an offset, preferably `+05:30`. All calculations and session matching use IST. A candle timestamp is its **opening** time. Only five-minute candles are supported by signal and replay logic.

## Workspace files

| File | Producer | Meaning |
| --- | --- | --- |
| `config.json` | `init`, then user review | INR budget, risk limits and estimated costs |
| `calendar.json` | `init`, then verified manual import | Explicit exchange/date sessions |
| `instruments.json` | Broker master importer or verified normalized import | Asset type, lot size, tick and provider identifier |
| `bars.csv` | Broker adapter or normalized CSV import | Multi-instrument historical/current candles |
| `quotes.json` | Broker quote calls or normalized import | Latest trade price/time keyed by exchange:symbol |
| `account.json` | `init`, paper fill/close | Local paper cash, positions and journal |
| `scan.json`, `entry.json` | Scanner/entry | Signal results |
| `plan.json` | Exit planner | One active research plan |
| `simulation.json` | Simulation | Replay probabilities and historical trades |
| `order.json`, `risk.json` | Budget/risk | One proposed paper entry and its current verdict |
| `groww-ticket.json`, `zerodha-ticket.json` | Ticket command | Unsubmitted manual entry payloads |
| `news.json`, `disclosures.json`, `earnings.json` | Research tools | Sourced event/arithmetic results |
| `alerts-seen.json`, `*-seen.json` | Alert/feed pollers | Bounded deduplication caches |

One workspace has one current plan/order. Use separate workspaces for independent simultaneous plans, or sequentially replace the current plan after completing its workflow. The account can hold multiple instrument positions. No result file is an instruction to execute a trade.

## Sessions

`calendar.json` has a `sessions` mapping keyed by `EXCHANGE:YYYY-MM-DD`. There is no inferred weekday or hardcoded holiday fallback. Omitted dates are unavailable for entries or historical replay. For a special Sunday session, add that Sunday explicitly. Exchanges remain independent.

Illustrative schema only; replace the source and timings with verified current notices and broker constraints:

```json
{
  "source": "Official exchange calendar/notices checked YYYY-MM-DD; broker cutoff checked separately",
  "sessions": {
    "NSE:2026-10-19": {
      "open": "09:15:00",
      "entry_after": "09:30:00",
      "entry_before": "14:45:00",
      "flat_by": "15:10:00",
      "close": "15:30:00"
    }
  }
}
```

The order is `open <= entry_after <= entry_before < flat_by <= close`. Session close is not a promise that every instrument can be continuously traded until then. Auctions, outages, eligibility and broker square-off constraints need earlier windows where applicable. Do not enter pre-open, auctions or special sessions as normal continuous candles without reviewing the strategy's applicability. The simulation pool now derives each complete grid from the applicable continuous-session policy; 72-, 75- and sourced special-session lengths are supported. See schema 2 below.

## Instruments

```json
{
  "NSE:INFY": {
    "asset": "EQUITY",
    "lot_size": 1,
    "tick_size": "0.05",
    "instrument_token": "408065"
  }
}
```

This is a schema illustration, not a current instrument-master assertion. Groww uses `groww_symbol` instead of Kite's `instrument_token`. Use broker master values, including current tick size; the engine assumes neither a universal ₹0.05 tick nor a universal symbol mapping. BSE symbols must match the chosen broker's trading symbol exactly. No index, derivative or lot greater than one is supported for paper entries. Keep provenance and refresh date when maintaining this file manually.

## Candles

```csv
exchange,symbol,timestamp,open,high,low,close,volume
NSE,INFY,2026-10-19T09:15:00+05:30,1000,1003,995,1001,100000
```

The numbers above are synthetic. Required fields are exactly the OHLCV identity and values shown. Prices must be finite and positive; volume must be finite and non-negative. OHLC ranges must contain open and close. Duplicate exchange/symbol/timestamp candles are rejected on import. Signal bars must align with the session's five-minute grid. Missing opening candles prevent a trigger; gaps before a breakout produce an unavailable result. No implicit interpolation is performed.

`data candles --append` intentionally updates overlapping observations from the fetched response. Keep separate raw files if auditability or provider comparisons matter. The engine does not normalize splits/dividends, adjust survivorship bias or infer missing volume.

## Quotes

```json
{
  "NSE:INFY": {
    "price": "1008",
    "timestamp": "2026-10-19T09:35:00+05:30",
    "source": "user export from broker; illustrative values"
  }
}
```

Timestamp means last trade time, not download time. Broker fetches also record `received_at`. A quote too old for `max_quote_age_seconds`, or dated after the current clock, blocks new entries and paper fills. The planner's entry time independently expires under `max_plan_age_seconds`.

## Costs and limits

See [the example configuration](../examples/config.json). All INR amounts and fractional limits use decimal strings; count/seconds fields use integers. Fractions are `0..1`, not percentages such as `25`.

Estimated trade loss = quantity × (conservative entry − stop + entry × slippage bps / 10,000) + estimated roundtrip charges. Charges = entry notional × roundtrip cost bps / 10,000 + fixed roundtrip charge. The conservative entry is the greater of the plan entry and current quote. Reward/risk subtracts roundtrip charges from gross target reward.

Include suitable estimates for brokerage, STT, exchange charges, GST, SEBI charges, stamp duty and slippage in reviewed settings. Defaults are illustrative aggregate estimates, not a calculator of statutory rates. Daily risk is the sum of reserved estimated loss for every paper entry that day, plus the proposed entry. It is intentionally conservative and does not release budget on wins. It is not actual realized daily P&L. Position/cash caps are measured against configured starting capital; they are not a mark-to-market portfolio optimizer.

## News and disclosures

Normalized `.json` input is an array:

```json
[
  {
    "title": "Company announcement title",
    "summary": "Short sourced metadata; not an instruction",
    "url": "https://example.com/replace-with-original-filing",
    "source": "Exchange or publisher name",
    "published_at": "2026-10-19T09:00:00+05:30"
  }
]
```

Saved RSS/Atom XML is accepted too. RFC-style RSS dates and timezone-aware ISO Atom dates are understood. Undated items are counted as skipped, not made current at download time. Future and out-of-window items are excluded. Unknown date formats may be skipped; normalize an official export rather than guessing a publication time. Empty/no matching feeds never constitute clearance to trade.

`watchlist_aliases` maps exchange:symbol to symbol/company-name phrases. Empty mapping scans all items. Matches use phrase boundaries and case-insensitive text; they are not a legal entity resolution service. Disclosures mode filters insider, ownership and pledge keywords. Read original filings for actual transaction details. `--new-only` persists a bounded cache of the last 10,000 delivered identities; old items may repeat after cache eviction.

## Earnings

An array of sourced **three-month quarters**, with the same instrument, basis and units:

```json
[
  {
    "instrument": "NSE:INFY",
    "period_end": "2026-09-30",
    "period_months": 3,
    "basis": "consolidated",
    "unit": "INR crore",
    "revenue": "1000",
    "net_profit": "100",
    "eps": "10",
    "published_at": "2026-10-18T18:00:00+05:30",
    "source_url": "https://example.com/replace-with-actual-results"
  }
]
```

Numbers above are synthetic. Revenue and profit use `unit`; EPS is INR per share. Supply standalone or consolidated quarters consistently. The CLI excludes statements not yet published at the research clock. QoQ looks for a period three months earlier and YoY twelve months earlier; missing comparisons return null. A non-positive prior base yields an absolute change and no growth percentage. Split-adjusted EPS and restated historical statements must be prepared consistently by the researcher. The tool does not infer revisions or extract financial statements from PDFs.

## State integrity

The CLI locks the workspace for each transaction with an exclusive `.lock` file and atomically replaces JSON state. Watch mode releases the lock between polls. Direct library calls leave concurrency/state management to the caller. A killed process can leave a lock file: verify no process is using the workspace before removing it. Do not manually edit account history to bypass risk gates. This is a local research ledger, not tamper-resistant financial infrastructure.


## v0.2 personal desk contracts

`calendar.json` schema 2 stores explicit `days`, dated security-class `policies` and broker/product `broker_cutoffs`, each with effective bounds and source/review evidence. `reviewed_on` and `review_interval_days` guard connected policy freshness. Session resolution yields continuous intervals, phase intervals, dynamic grid, entry/flat deadlines, policy ID and cutoff verification. BSE and unknown dates/classes never inherit NSE defaults.

`instruments.json` maps EXCHANGE:SYMBOL to `versions`. A version has `valid_from`, optional `valid_to`, `observed_on`, `source`, `asset`, whole-share `lot_size`, `tick_size`, `session_class`, provider identity and broker-specific reviewed eligibility. A newly fetched master starts today; it does not retroactively fill missing historical intervals. Partial masters cannot establish non-CAS membership by absence.

`settings.json` stores provider/mode/watchlist and credential-store selection, never secret values. `broker-snapshot.json` stores `status`, `broker`, `checked_at`, conservative `available_cash_inr`, exposed instruments, normalized positions and open-order count. Missing/failed components are not zero exposure. Risk requires the selected provider's complete snapshot within 120 seconds when configured.

`templates/fees.json` contains effective broker/exchange/product profiles, per-executed-order brokerage rate/cap/min, exchange/IPFT/SEBI/STT/stamp/GST rules, source and review date. Current profiles start on the actual review date and cannot be used for earlier sessions. Monetary values are decimal strings. Component-level paise estimates explicitly differ from reconciled contract-note aggregation/rounding. A paper position embeds the fee profile used at entry.

`desk.sqlite3` stores immutable plan JSON and family version, mutable lifecycle/context, idempotent journal events, authoritative paper account, source events, collector snapshots, research trials and observation scorecard. Account writes use a transaction and optimistic before-hash; tracking/closing changes plan state within that transaction. `account.json` is a compatibility mirror after the first DB account commit. Do not manually edit it to change the authoritative balance.

Source event JSON: an array of objects with `title`, `source`, original HTTPS `url`, offset-aware `published_at`, optional EXCHANGE:SYMBOL `instrument`, `summary`, `document_id`, `revision`, `content_sha256` and `scheduled_at`. A future scheduled event is allowed; future publication is not known evidence. Import adds receipt time and a stable revision ID, and labels source-supplied evidence as not independently verified. XBRL extraction accepts only supported three-month monetary and basic-EPS contexts with explicit units and field evidence; arbitrary PDFs and bank/NBFC templates are unsupported.


## v0.3 evidence and source contracts

`validate broker` stores actual read-only probe reports under private `evidence/` and journal keys, including capability status/latency and counts, with no tokens/customer identity/portfolio details. Client/clock injection sets `origin: TEST_DOUBLE` and does not persist live evidence. `validate readiness` shows independent per-provider probe and note states, context status and distinct observed dates; it never certifies production readiness.

Contract-note schema 1 is demonstrated in `examples/contract-notes/`. Complete reviewed NSE intraday scope and explicitly sourced seven-component charge totals are required. Each execution supplies instrument, product, side, quantity, price, offset-aware timestamp, order ID and distinct trade ID. Same-day per-instrument quantities must balance; partial fills group by order before brokerage calculation. Original local source bytes are hashed. Evidence counts only user-reviewed broker-note declarations with source hashes; this is not document-signature authentication. SYNTHETIC inputs and DEMO workspaces never count, even when model estimates match exactly. Reports retain mismatches and never overwrite paper balances.

Context snapshots separate source check time, original publication string, normalized publication time and receipt. `NSE_LOCAL_IST_NORMALIZATION` applies only to the observed offset-free NSE RSS format on explicitly allowed exchange archive hosts; other naive dates remain unverified. Source states include AVAILABLE, STALE, EMPTY_UNVERIFIED, PARTIAL_UNVERIFIED, UNVERIFIED and ERROR, with counts of undated/invalid/future items. ETF proxies have their own exchange trade clocks, previous-close/provider-percent evidence, age and kind `ETF_PROXY_NOT_INDEX`. Read-time aging prevents a once-fresh stored proxy from appearing current forever.

Observation records use `schema_version: 2`, fixed watchlist/policy/interval, per-session candle coverage, heartbeat gap, healthy/total market samples, capped incident history and processing/cycle samples. Legacy rows without health evidence do not qualify. The foreground observer has a distinct `.observer.lock`; each data cycle briefly owns the general `.lock`, allowing the UI to remain usable. Existing JSON/SQLite journal state is preserved.

## Separate data and execution providers

`config.json.broker` remains the execution broker for costs, eligibility and deadlines. Optional `data_provider: "upstox"`, `execution_mode: "MANUAL"`, and `account_source: "MANUAL_ATTESTATION"` select market-data-only collection. `settings.json.data_provider` selects credentials. Upstox master rows carry `upstox_key` (NSE_EQ plus ISIN) and rupee tick sizes converted from master paise; today's observation cannot backfill earlier dates. Unknown CAS flags stay UNVERIFIED.

Manual `broker-snapshot.json` records use status `MANUAL_ATTESTED`, source `USER_ATTESTATION`, the execution `broker`, actual-clock `checked_at`, `available_cash_inr` and `exposed_instruments`. They expire for entry checks after 120 seconds and are never refreshed by data sync. They do not qualify for authenticated release evidence. See [free-data workflow](upstox-free-data.md).

`setup --account-source broker` with an Upstox data provider sets `account_source: "BROKER"`: Upstox provides the master, quotes and candles; the execution broker supplies the authenticated account snapshot. Sync requires both requested roles to succeed and invalidates failed account snapshots instead of falling back to manual data. `validate broker` reports `data_provider` separately from `broker`; injected clients for either role remain test evidence. Observation records pin both provider and account-source roles; changing them invalidates qualification for that session.
