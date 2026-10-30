# Groww and Zerodha setup

Both providers support research data and **manual draft tickets** in this release. No broker account changes or order submissions are made. Local paper trading does not use a broker sandbox.

## Credentials

Use the broker's official authentication flow. The program reads these variables from its process environment:

| Provider | Variables | Headers |
| --- | --- | --- |
| Zerodha | `KITE_API_KEY`, `KITE_ACCESS_TOKEN` | Kite version 3 and token authorization |
| Groww | `GROWW_ACCESS_TOKEN` | API version 1.0 and Bearer authorization |

Do not paste secrets in chat, fixtures, config.json or version control. `.env.example` lists names only; dotenv loading is deliberately not automatic. A session token can authorize more than reads at the broker even though this project uses only GET endpoints. Renew tokens through the provider's current documented flow; no token-refresh or login automation is included.

Use [Kite authentication](https://kite.trade/docs/connect/v3/user/) and [Groww's documentation](https://groww.in/trade-api/docs) for account-specific access, terms and current subscription requirements. This repository makes no promise that broker data is free or accessible without a qualifying account.

## Instrument masters

Download the CSV to a local file using the provider's documented process:

- Kite: [market quotes/instruments](https://kite.trade/docs/connect/v3/market-quotes/), instrument master endpoint `https://api.kite.trade/instruments`.
- Groww: [instrument documentation](https://groww.in/trade-api/docs/curl/instruments), public CSV `https://growwapi-assets.groww.in/instruments/instrument.csv`.

```bash
python3 -m india_trader --workspace trader-real data master --broker zerodha --file /absolute/path/kite.csv
# Or:
python3 -m india_trader --workspace trader-real data master --broker groww --file /absolute/path/groww.csv
```

Import accepts supported NSE/BSE cash equities with lot size one. Kite selection uses EQ plus the exchange cash segment. Groww selection additionally checks ISIN and conservative equity series. This is not a complete exchange eligibility filter: manually review ASM/GSM, trade-to-trade, SME, suspension and broker intraday restrictions. The engine does not automatically monitor these lists. Refresh the master for each research session and preserve the file's source/date separately.

Kite history uses `instrument_token`; Groww history uses `groww_symbol`. These are loaded from the imported master. Never substitute a symbol guessed from another exchange. Importing a master replaces the current normalized master; use the same provider for that workspace's history calls or maintain a deliberately merged normalized master.

## Candles and quotes

```bash
python3 -m india_trader --workspace trader-real data candles --broker groww --instrument NSE:INFY \
  --start 2026-09-01T09:15:00+05:30 --end 2026-10-30T10:00:00+05:30 --append
python3 -m india_trader --workspace trader-real data quote --broker groww --instrument NSE:INFY
```

Five-minute history is fetched in 29-calendar-day chunks and deduplicated at chunk boundaries. Candle times are normalized to IST. Naive times in broker responses are interpreted as IST, consistent with their examples; user-supplied timestamps must have an offset. `--end` is exclusive. Only fully closed bars are used for entry logic.

Without `--append`, the destination CSV is replaced. With it, incoming candles replace rows with the same exchange, symbol and timestamp; other rows are retained. This also permits assembling a multi-symbol watchlist sequentially. No automatic thousands-of-symbol fan-out is included; respect data permissions and rate limits.

Quotes retain the broker's **last trade timestamp**, separately from local receipt time. Fetching a stale quote does not make it fresh. If trade time is missing, the quote call fails. The risk gate blocks stale, missing and future-dated quotes. GET calls retry transient 429/502/503/504 errors twice with bounded delay; authentication errors do not retry. History is not automatically adjusted for corporate actions.

## Manual ticket mapping

| Meaning | Zerodha draft | Groww draft |
| --- | --- | --- |
| Security | `tradingsymbol`, `exchange` | `trading_symbol`, `exchange`, `segment=CASH` |
| Product | `MIS` | `MIS` |
| Entry | `BUY`, `LIMIT`, whole-share quantity, `DAY` | Same |
| Reference | `tag` | `order_reference_id` |

The generated JSON includes the plan's stop, target and flat-by separately. It is **not** a bracket, OCO, protective stop or order guarantee. Review the stock's intraday eligibility and all exit controls directly in the broker app. An accepted broker order would not itself establish a fill; this project never reaches that stage.

## v0.2 guided connection and account facts

Prefer [guided setup](onboarding.md) over the legacy manual-import examples above. `auth` accepts hidden local input and can store workspace-scoped macOS Keychain values; environment credentials take priority. Market/account fetches remain GET-only. Explicit Kite login alone exchanges a request token at the fixed session endpoint through POST; no API secret is stored.

`sync` retrieves a full current instrument master, normalized cash/holdings/positions/open-order snapshot, quotes and incremental five-minute history. A failed account component leaves exposure unverified. Holdings/open orders overlap by symbol across exchanges conservatively; providers and paper balances are not merged. The cash view excludes margin leverage and may underestimate usable cash.

`serve --collect` uses rate-limited REST polling. Kite quotes are batched, Groww quotes are individually paced. The documented request chunk is not a claim about historical retention or entitlement. Actual authenticated behavior and quota consumption remain untested. Official SDK streaming has not been implemented.
