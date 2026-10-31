# Personal connection guide

The assistant keeps broker facts and paper decisions separate. Use one execution broker per workspace. The optional [Upstox data mode](upstox-free-data.md) supplies market data separately, with either authenticated execution-account reads (`--account-source broker`) or explicit manual declarations. It fetches account/data through GET endpoints; the explicit Kite login flow alone POSTs to the fixed session-token endpoint. It cannot place, modify or cancel orders.

## First session

1. Run `python3 -m india_trader --workspace trader-real setup --interactive`, or `serve` and use the local setup form. Review capital and maximum planned losses. Full cash funding is assumed even when a manual ticket says MIS.
2. Confirm that your broker API plan includes the desired quotes/history. A successful profile login alone does not establish data entitlement.
3. Authenticate privately through `auth --broker zerodha --flow login`, `auth --broker zerodha --flow token`, or `auth --broker groww --flow token`. macOS prompts use hidden input and workspace-scoped Keychain storage. The Groww token is generated in its Trading APIs page. Session expiry remains provider controlled; this release does not bypass interactive login/2FA or silently refresh expired sessions.
4. Run `doctor --online`, then `sync`. Diagnose AUTH_REQUIRED, NOT_ENTITLED, RATE_LIMITED and network errors separately. Credential presence alone is never reported as an authenticated session.
5. Read `status`. Resolve instrument eligibility, dated session coverage and cutoff issues. Full current instrument masters can infer NSE CAS classification from derivative-underlying membership; partial imports stay UNVERIFIED. That inference is not a broker intraday-permission check.
6. Review each broker's permitted instrument/product and surveillance status before using `market verify-instrument --help`. Permissions are broker specific. Today's master only establishes today's observation and cannot validate earlier sessions.
7. Run `serve --collect`. Keep the machine awake and connected during observations. Check last trade, complete candles and network heartbeat separately.

On Windows/Linux use process environment credentials instead of Keychain. Environment values take priority when both exist. `auth --clear --broker BROKER` removes only this workspace's stored entries; it does not revoke a broker session or unset environment values. No plaintext credential file is created.

## Market-policy maintenance

Built-in calendar snapshot reviewed 30 October 2026: NSE only, explicit 2026 day records, CAS policy from 3 August and announced 7 December change. Unknown Muhurat timings are unverified. Current Zerodha CAS and non-CAS cutoffs are sourced; Groww CAS remains unverified until a suitable source is reviewed. All of these are dated snapshots, not a live rules service.

Use `market load-calendar`, `market load-instruments` and `market set-cutoff` for reviewed sourced updates. Imports retain backups. Do not extend an effective date or refresh a review timestamp without actually checking the original exchange/broker source. The risk guard blocks old connected policies after the review interval.

## Health and recovery

`doctor` checks local data; `doctor --online` also checks the selected provider's profile and a quote. Sync reports account, master, quote and history capabilities separately. A failed account component invalidates the account snapshot rather than substituting an empty portfolio. Open/unknown-status orders and holdings block overlapping instruments conservatively across exchanges.

The collector retries with bounded backoff and increments history from the latest cached candle. Missing bars remain visible and block a complete signal. A successful network response with an old exchange trade timestamp remains stale. No broker stop/target is attached to a paper plan.

The local app binds only 127.0.0.1, validates Host/Origin/fetch metadata, requires a random token for JSON mutations and blocks external scripts. This is a single-user local boundary, not authentication against other trusted programs on the same machine. Do not expose the port publicly or through a tunnel.

## Private data

The workspace contains balances, positions, notes and SQLite records. It is ignored by Git. Keep it outside the source checkout when practical, protect it with normal OS permissions, and back it up privately. The engine and skill installer do not copy user workspaces. Sharing source code is different from sharing private account evidence.


## Finish validation after connecting

Use the [private validation workflow](finishing-the-gates.md) for `validate broker`, daily `reconcile`, automatic `context`, and the resumable `observe run --sessions 20` campaign. `serve --collect` now runs this same campaign with a separate context worker. Both share the observer lock and stop at the target. No assumed account, synthetic note or downloaded historical bar is counted as an actual observed session.
