# Free Upstox data, manual Groww execution

This mode uses Upstox's read-only Analytics Token for market quotes and completed five-minute candles. Your execution broker stays Groww (or Zerodha); fees, intraday permissions and exit deadlines use that broker's rules. No Groww token or paid Groww API subscription is needed for this mode. Upstox account/KYC and data entitlement are required. Free API access does not mean zero account, trading, AI or hosting costs.

The current adapter supports NSE normal, standard-lot cash equities. It uses REST polling, normally every 30 seconds, not WebSocket tick streaming. This is a closed-five-minute-bar research assistant, not a second-by-second scalper. It implements the existing long-only opening-range-breakout method; it does not predict profitable trades.

## 1. Create your Upstox account

Use https://upstox.com/ and complete signup/KYC yourself. Review account opening/maintenance charges shown during signup. Do not share a password, OTP, TOTP seed or token in a chat. Once active, open https://account.upstox.com/developer/apps and select **Analytics → Generate Token**. Choose the Analytics Token, not an order-capable OAuth token. Upstox documents free, one-year validity and market-data access without a static IP. Keep the token private; it is still a sensitive credential.

Sources checked 30 October 2026:

- [Analytics Token](https://upstox.com/developer/api-documentation/analytics-token/)
- [Full market quotes](https://upstox.com/developer/api-documentation/get-full-market-quote/)
- [Instrument master](https://upstox.com/developer/api-documentation/instruments/)
- [Historical V3 candles](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/)
- [Current-day V3 candles](https://upstox.com/developer/api-documentation/v3/get-intra-day-candle-data/)

## 2. Create a separate private workspace

From the repository root, choose your own paper capital and risk limits. These are examples, not recommended allocations:

```sh
python3 -m india_trader --workspace "$HOME/india-trader-upstox" setup \
  --broker groww --data-provider upstox \
  --watchlist NSE:INFY,NSE:RELIANCE \
  --capital 100000 --max-loss 500 --daily-risk 1500
```

`--broker` is where you intend to execute manually. `--data-provider` is the market-data connection. Existing initialized workspaces are never reset; create a new workspace to use this mode. The browser setup form also offers Upstox as the market-data provider.

On macOS, enter the token only in the hidden terminal prompt:

```sh
python3 -m india_trader --workspace "$HOME/india-trader-upstox" auth --broker upstox --flow token
python3 -m india_trader --workspace "$HOME/india-trader-upstox" sync
python3 -m india_trader --workspace "$HOME/india-trader-upstox" doctor --online
```

The token is stored in workspace-scoped macOS Keychain. Windows/Linux use `UPSTOX_ANALYTICS_TOKEN` in the process environment, populated privately by your shell/secret manager. Never pass a token as a CLI argument. Authentication can be revoked from the Upstox developer console. Run `auth --broker upstox --clear` to remove this workspace's Keychain entry; that does not revoke the upstream token or unset environment variables.

Sync downloads today's master, maps `NSE:SYMBOL` to the ISIN instrument key, fetches current quotes and backfills five-minute bars. Current metadata never establishes prior-day tick or eligibility coverage. A quote's timestamp is its last exchange trade, not when our request finished. Missing/old quotes, incomplete batches and open candles are not treated as current evidence.

## 3. Review health before relying on a plan

The feed does **not** connect your Groww account. The dashboard shows this explicitly. Review all Groww cash, holdings, positions and pending orders yourself. Settings has a manual confirmation form. The CLI equivalent is:

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

`SYNCED` in this mode means the requested market-data operations succeeded. It does not mean Groww is connected or safe to trade. Broker authentication, contract-note reconciliation and 20-session release gates remain separate. Manual account declarations do not qualify as authenticated exposure samples. Automated tests use synthetic fixtures; no actual account has been validated for this integration yet.

API consumption is restricted in code to fixed-origin, allowlisted market-data GET routes. The implementation does not use Upstox portfolio/profile endpoints, order APIs, static-IP account access or browser-cookie extraction. Raw tokens and broker responses are not printed in errors. Live data belongs in your private workspace; do not publish it with the open-source code. Provider terms and exchange data permissions still apply.
