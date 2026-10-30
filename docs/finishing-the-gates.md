# Finish the private validation gates

The current release is v0.3. The example paths below are placeholders for later configuration. No API keys, private contract notes or actual observations are assumed to exist. The included examples are invented and never close real evidence gates.

## Try the complete workflow now

From the repository:

```bash
python3 scripts/evidence_demo.py
# Optional detailed report:
python3 scripts/evidence_demo.py --json
python3 -m india_trader --workspace trader-demo serve --demo
```

The offline tour tests broker-probe behavior using a test double, reconciles two synthetic daily notes including partial-fill grouping, collects synthetic context, and verifies that real broker/fee/session gates remain open. It needs no network, credentials or account. Model-generated example charges matching the same model validate plumbing only; they are not evidence that actual charges agree.

The daily desk shows market/sector context in Today and a per-provider evidence panel in Settings & health. Synthetic data stays labelled. Empty and stale feeds, failed probes and missing note evidence are visible.

## 1. Authenticated broker validation — fill in later

Choose separate private workspaces for each provider. Setup asks for your own capital/risk values; the example does not set them on your behalf.

```bash
python3 -m india_trader --workspace /YOUR/PRIVATE/groww setup --interactive
python3 -m india_trader --workspace /YOUR/PRIVATE/groww auth --broker groww --flow token
python3 -m india_trader --workspace /YOUR/PRIVATE/groww validate broker --broker groww

python3 -m india_trader --workspace /YOUR/PRIVATE/zerodha setup --interactive
python3 -m india_trader --workspace /YOUR/PRIVATE/zerodha auth --broker zerodha --flow login
python3 -m india_trader --workspace /YOUR/PRIVATE/zerodha validate broker --broker zerodha
```

Credentials enter hidden local prompts/Keychain or process environment. Do not enter placeholder strings as credentials; do not paste credentials into chat. Daily session expiry and subscriptions remain provider controlled.

Each actual probe checks authenticated profile, full instrument master, watchlist quotes and trade timestamps, complete account snapshot and a bounded historical request. It records capability status/latency and aggregate counts without customer identity, tokens or portfolio values. Missing authentication, entitlement, stale quotes, incomplete history/account responses and errors prevent a pass. No trade is required or placed.

Reports are stored privately under `evidence/` and the journal. Injected clients/research clocks are explicitly test doubles and never count as actual integration evidence. A passing probe is dated integration evidence, not continuous reliability or perpetual authentication.

For consolidated evidence about both providers, you may explicitly connect and validate both in one chosen primary workspace. The second connection does not change the primary provider or merge portfolios. Separate workspaces otherwise keep separate evidence stores; the app does not silently combine them.

## 2. Contract-note reconciliation — fill in later

Download existing notes privately:

- Groww: Profile → Reports → Transactions → Contract Note. [Official instructions](https://groww.in/help/my-account/ma-others/where-can-i-get-the-contract-note).
- Zerodha: download through Console. [Contract-note scope](https://support.zerodha.com/category/console/reports/contract-note/articles/what-is-a-contract-note-and-how-to-interpret-it).

Work locally with the original document. Never send a PAN, document password or unredacted account identifiers through chat. Automatic PDF decryption/OCR/broker-specific layout parsing is not implemented; normalize from the note and review against it. This deliberately avoids silently inventing missing order IDs, tax allocations or scope.

Use `examples/contract-notes/synthetic-groww.json` or `synthetic-zerodha.json` to understand the schema, then create a separate reviewed file from the actual note. Required data:

- `schema_version: 1`, broker, trade date, `exchange: "NSE"` and complete supported note scope.
- `scope: "COMPLETE_NSE_INTRADAY_ONLY"` and `scope_reviewed: true` only after verifying the whole note contains that scope. Mixed delivery/F&O/MTF/BSE notes require another reviewed model and are rejected.
- Executions with real order ID, distinct trade ID, instrument, BUY/SELL, INTRADAY, whole-share quantity, price and offset-aware execution time.
- All seven actual charge components: brokerage, exchange, IPFT, SEBI, STT, stamp and GST, plus the actual total. Missing/combined lines need a documented reviewed allocation; never guess an absent line is zero. GST may be aggregated from actual CGST/SGST/IGST lines.
- `origin: "BROKER_CONTRACT_NOTE"` and `source_reviewed: true` only for a genuine original document you reviewed. Keep the example origin SYNTHETIC on fixtures.

```bash
python3 -m india_trader --workspace /YOUR/PRIVATE/groww reconcile \
  --file /YOUR/PRIVATE/reviewed-note.json \
  --source-file /YOUR/PRIVATE/original-contract-note.pdf
```

The importer hashes the source locally; it does not upload or decrypt it. It groups partial fills by order before applying brokerage caps/minimums, checks whole-day scope and per-instrument balances, estimates the dated schedule, and compares every component and the total. Opposite component errors cannot cancel into a false pass. Unknown historical fee dates are rejected; do not backdate current profiles. Differences remain visible and never rewrite a fee schedule or paper balance.

The working evidence target is at least three distinct matched dates per provider, with unresolved mismatches reviewed. Use existing notes rather than creating trades for validation. One matched note does not certify all sizes, executions or plans. File hashes and user review are provenance declarations, not broker digital-signature authentication. Actual fill/plan matching and broad PDF templates remain further work.

## 3. Broader context

```bash
# Public sources only; no broker credentials needed:
python3 -m india_trader --workspace context-research context refresh --public-only

# Corporate feeds plus provider ETF observations:
python3 -m india_trader --workspace /YOUR/PRIVATE/groww context refresh
python3 -m india_trader --workspace /YOUR/PRIVATE/groww context show
```

Seven endpoints from the [official NSE RSS directory](https://www.nseindia.com/static/rss-feed) cover announcements, financial results, integrated financials, corporate actions, board meetings, insider trading and pledges. Each source has its own last check, publication time, counts, errors and coverage state. Source results are cached for five minutes. Receipt is not publication; NSE's offset-free `DD-Mon-YYYY HH:MM:SS` format is explicitly normalized to IST with raw text/basis retained, and other unknown date formats stay unverified.

NIFTYBEES, BANKBEES and ITBEES provide timestamped broad-market, banking and IT **ETF proxies**, fetched through the authorized provider. They are not actual index levels or whole-market breadth. Current quote age is recomputed when viewed. These proxies never join the trade watchlist automatically. Further sectors and company-sector mappings remain future coverage.

The actual public-feed smoke report is in `docs/research/public-context-smoke-2026-10-30.json`. At the recorded check, some sources were fresh, the legacy financial-results feed was stale, and pledge dates were unverified. These are observed gaps, not empty successful all-clears. A fallback integrated-financials source does not make all filings complete.

## 4. Twenty observed sessions — start later with real credentials

```bash
python3 -m india_trader --workspace /YOUR/PRIVATE/groww sync
python3 -m india_trader --workspace /YOUR/PRIVATE/groww status
python3 -m india_trader --workspace /YOUR/PRIVATE/groww observe run --sessions 20 --interval 30
# Or use the same campaign with the desk:
python3 -m india_trader --workspace /YOUR/PRIVATE/groww serve --collect --interval 30
```

Both commands share a single-workspace observer lock. Start before the first session opens. The foreground campaign waits outside verified exchange windows, skips explicit holidays, refuses guessed special-session times, bootstraps today's metadata, and resumes from persisted distinct dates after a restart. No OS service, wake schedule or Codex automation is installed by these commands. The machine must stay awake and connected; refresh daily credentials privately as required.

Market polling and slower context collection run separately, with shared in-process provider pacing. Context feed delays do not block the market loop. Each failed market poll is retained. A qualifying day needs known ≥99% candle coverage, near-open-to-close span, heartbeat continuity, ≥99% healthy market polls with fresh quotes/account snapshots, and unchanged watchlist/policy/interval. Starting halfway through a session does not reconstruct observation coverage from downloaded history. Legacy measurements without health samples do not qualify. The date must actually pass; historical bars, tests and synthetic clocks do not count.

```bash
python3 -m india_trader --workspace /YOUR/PRIVATE/groww observe report --sessions 20
python3 -m india_trader --workspace /YOUR/PRIVATE/groww validate readiness
```

Currently there are **0/20 real observations** and no authenticated/actual-note evidence. The campaign is ready to run after real inputs are supplied. It stops at the requested target and retains the scorecard for review; this is operational evidence, not strategy profitability or production certification.
