# Free Upstox data, manual Groww execution

This mode uses Upstox's read-only Analytics Token for market quotes and completed five-minute candles. Your execution broker stays Groww (or Zerodha); fees, intraday permissions and exit deadlines use that broker's rules. Combined account mode requires a separate Groww token and eligible account-API access; manual-account mode does not. Neither mode requests Groww live-data APIs. An eligible Upstox Analytics Token and data entitlement are required; signup-only account eligibility has not been confirmed. Free API access does not mean zero account, trading, AI or hosting costs.

The current adapter supports NSE normal, standard-lot cash equities. It uses REST polling, normally every 30 seconds, not WebSocket tick streaming. This is a closed-five-minute-bar research assistant, not a second-by-second scalper. It implements the existing long-only opening-range-breakout method; it does not predict profitable trades.

## Choose the account connection

- **Recommended combined mode:** `--account-source broker` reads Groww holdings, cash-equity positions, pending cash orders and available cash with a separate Groww token. Upstox supplies the market data. Check your actual Groww plan before relying on it: Groww's [official guide](https://groww.in/blog/api-trading-on-groww) describes a ₹0 **Free Trial** covering account/order APIs while excluding live-data and backtesting APIs. Trial eligibility, duration and renewal terms remain account-specific and unverified here. This app never activates a subscription or places an order.
- **Manual mode:** omit `--account-source` for Upstox setup, or select `--account-source manual`. You explicitly confirm exposure, and that declaration never becomes broker-verified evidence. No automatic fallback between these modes occurs.

## 1. Get an eligible Upstox Analytics Token

Try signing in to https://account.upstox.com/developer/apps first and check whether Analytics Token generation is available. The Analytics Token docs do not explicitly establish whether signup-only users qualify without trading/demat activation. If activation is required, review account opening/maintenance charges before completing signup/KYC yourself. Do not share a password, OTP, TOTP seed or token in a chat. Once active, open https://account.upstox.com/developer/apps and select **Analytics → Generate Token**. Choose the Analytics Token, not an order-capable OAuth token. Upstox documents free, one-year validity and market-data access without a static IP. Keep the token private; it is still a sensitive credential.

Sources reviewed for this workflow on 31 October 2026:

- [Analytics Token](https://upstox.com/developer/api-documentation/analytics-token/)
- [Full market quotes](https://upstox.com/developer/api-documentation/get-full-market-quote/)
- [Instrument master](https://upstox.com/developer/api-documentation/instruments/)
- [Historical V3 candles](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/)
- [Current-day V3 candles](https://upstox.com/developer/api-documentation/v3/get-intra-day-candle-data/)

## 2. Create a separate private workspace

From the repository root, choose your own paper capital and risk limits. These are examples, not recommended allocations:

```sh
python3 -m india_trader --workspace "$HOME/india-trader-upstox" setup \
  --broker groww --data-provider upstox --account-source broker \
  --watchlist NSE:INFY,NSE:RELIANCE \
  --capital 100000 --max-loss 500 --daily-risk 1500
```

`--broker` is where you intend to execute manually. `--data-provider` is the market-data connection. `--account-source broker` selects authenticated execution-account reads; `manual` selects explicit user declarations. Existing initialized workspaces are never reset; create a new workspace to use this mode. The browser setup form also offers Upstox as the market-data provider.

On macOS, enter the token only in the hidden terminal prompt:

```sh
python3 -m india_trader --workspace "$HOME/india-trader-upstox" auth --broker upstox --flow token
python3 -m india_trader --workspace "$HOME/india-trader-upstox" auth --broker groww --flow token
python3 -m india_trader --workspace "$HOME/india-trader-upstox" sync
python3 -m india_trader --workspace "$HOME/india-trader-upstox" doctor --online
```

Tokens are stored separately by provider in workspace-scoped macOS Keychain. Generate the Groww daily access token in its Trading APIs page after confirming your account-API entitlement. Groww controls expiry; expired credentials require a fresh local auth step. Clearing one provider does not disable the other provider’s Keychain lookup. Windows/Linux use `UPSTOX_ANALYTICS_TOKEN` and, for combined mode, `GROWW_ACCESS_TOKEN` in the process environment, populated privately by your shell/secret manager. Never pass a token as a CLI argument. Authentication can be revoked from the Upstox developer console. Run `auth --broker upstox --clear` to remove this workspace's Keychain entry; that does not revoke the upstream token or unset environment variables.

Sync downloads today's master, maps `NSE:SYMBOL` to the ISIN instrument key, fetches current quotes and backfills five-minute bars. Current metadata never establishes prior-day tick or eligibility coverage. A quote's timestamp is its last exchange trade, not when our request finished. Missing/old quotes, incomplete batches and open candles are not treated as current evidence.

## 3. Review health before relying on a plan

### Combined broker-account mode

In `--account-source broker` mode, sync constructs an independent Groww adapter and fetches all supported cash-account components. It does not call Groww quotes/history or Upstox portfolio/profile APIs. Fees, instrument eligibility and deadlines still use Groww. Auth failures, incomplete responses or wrong-provider snapshots invalidate the old account snapshot; the result stays PARTIAL and entry checks block. Sync never replaces an account error with manual declarations or an empty portfolio. Account holdings/positions are matched by symbol and ISIN, conservatively across exchanges. Paper cash stays separate from real broker funds.

Settings shows both providers and their separate auth commands. Run `doctor --online` for market-data and account-profile diagnostics. A successful profile alone does not prove a complete account snapshot; sync must succeed. Then use `validate broker --broker groww` to probe the configured Upstox feed and Groww account roles together. Synthetic/injected clients remain TEST_DOUBLE and cannot satisfy live evidence gates. No real authenticated validation has been performed in this session.

### Manual account mode

Only in `--account-source manual` mode: the feed does **not** connect your Groww account. The dashboard shows this explicitly. Review all Groww cash, holdings, positions and pending orders yourself. Settings has a manual confirmation form. The CLI equivalent is:

```sh
python3 -m india_trader --workspace "$HOME/india-trader-upstox" confirm-account \
  --cash 50000 --exposed NSE:INFY,BSE:RELIANCE --reviewed
```

Only use an empty `--exposed` list after checking that you have no holdings, positions or pending orders. Include exposure outside the watchlist too. Matching symbols are conservatively blocked across exchanges. Confirmation expires after 120 seconds for entry risk checks; repeat immediately before tracking an entry and after an account change. It never refreshes itself during sync and never counts as authenticated broker evidence. Cash here is available unleveraged broker cash; paper balances and daily limits remain separate. Actual trading activity outside the paper ledger is not automatically captured: pause ideas and reconcile your journal and remaining risk before continuing.

The existing market-policy, fee, eligibility, freshness and cash/risk gates remain active. In particular, an unverified Groww CAS exit cutoff or instrument permission blocks an entry. Follow `market verify-instrument --help` and `market set-cutoff --help` only after checking a dated official Groww source. Do not guess a cutoff or change review dates to force a pass. No signal is guaranteed simply because the feed is connected.

## 4. Run the desk

```sh
python3 -m india_trader --workspace "$HOME/india-trader-upstox" serve --collect
```

Open http://127.0.0.1:8765. Keep the computer awake, browser open and collector running during market hours. Today displays entry candidates, risk reasons and stop/target/time exit conditions for **tracked paper positions**. **Enable alerts** requests optional browser notifications for new conditions while the page is running. Browser permissions, tab throttling, network and sleep can delay or prevent notifications; use the broker's own protective orders for actual positions. Existing conditions are visible on Today; enabling notifications does not replay the backlog.

You review the plan and place any real trade yourself in Groww. Paper tracking and paper closing do not place or close real orders, and simulated fills are not your actual Groww fill prices. Record real fills separately in your notes/journal and manage real stops/targets in Groww. The assistant cannot see an actual position merely because you placed it there. This chat is not the background alert service.

## Health and release evidence

- `DATA_ONLY`: quote connection rather than a broker-profile/account login.
- `MANUAL_REQUIRED`: execution-account exposure must be confirmed by the user.
- `MANUAL_ATTESTED`: explicit recent user declaration; not broker verification.
- `AUTH_REQUIRED`: expired/revoked/invalid token; regenerate privately.
- `NOT_ENTITLED`, `RATE_LIMITED`, `STALE`, `PARTIAL`: inspect diagnostics; do not treat missing data as zero exposure or a current quote.

`SYNCED` in manual mode means the requested market-data operations succeeded. In broker-account mode it additionally requires the execution-account snapshot to succeed. It never establishes overall readiness to trade. Only a fresh authenticated snapshot establishes the configured read-only account connection; manual mode does not connect Groww. Broker authentication, contract-note reconciliation and 20-session release gates remain separate. Manual account declarations do not qualify as authenticated exposure samples. Automated tests use synthetic fixtures; no actual account has been validated for this integration yet.

API consumption is restricted in code to fixed-origin, allowlisted market-data GET routes. The implementation does not use Upstox portfolio/profile endpoints, order mutation APIs, static-IP account access or browser-cookie extraction. Combined mode uses the execution broker’s documented account/profile GET endpoints only. Raw tokens and broker responses are not printed in errors. Live data belongs in your private workspace; do not publish it with the open-source code. Provider terms and exchange data permissions still apply.
