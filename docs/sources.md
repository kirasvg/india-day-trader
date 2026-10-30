# Sources and verification scope

Documentation reviewed on **2026-10-30**. Recheck current provider/exchange documentation before using current market data. This project intentionally contains no hardcoded PDT, US tax, SEC or US congressional-disclosure rules.

| Source | Used for |
| --- | --- |
| [Original day-trader-skill repository](https://github.com/Jakeschincariol/day-trader-skill) | Workflow inspiration and eleven-role structure |
| [NSE market timings and holidays](https://www.nseindia.com/resources/exchange-communication-holidays?apiversion=v2) | Indian exchange-session context; verify instrument-specific auction applicability |
| [NSE pre-open explanation](https://www.nseindia.com/static/products-services/equity-market-pre-open) | Distinguish pre-open from continuous trading and special reopening conditions |
| [NSE RSS directory](https://www.nseindia.com/static/rss-feed) | Official discovery of announcement, results, corporate-action and disclosure feeds |
| [NSE corporate announcements](https://www.nseindia.com/companies-listing/corporate-filings-announcements) | Original corporate filing verification |
| [NSE insider disclosures](https://www.nseindia.com/companies-listing/corporate-filings-insider-trading) | Public insider disclosure context |
| [SEBI corporate-filings directory](https://www.sebi.gov.in/curation/corporate_filings.html) | Links to NSE/BSE disclosure sources |
| [Kite instruments and market quotes](https://kite.trade/docs/connect/v3/market-quotes/) | Exchange:symbol keys, instrument tokens and full quote calls |
| [Kite historical candles](https://kite.trade/docs/connect/v3/historical/) | Five-minute historical endpoint and candle response |
| [Kite authentication](https://kite.trade/docs/connect/v3/user/) | Session authorization header and user-managed login |
| [Kite order specification](https://kite.trade/docs/connect/v3/orders/) | Manual ticket fields; order acceptance versus execution distinction |
| [Groww instruments](https://groww.in/trade-api/docs/curl/instruments) | Current CSV schema and provider symbols |
| [Groww live data](https://groww.in/trade-api/docs/curl/live-data) | Quote endpoint, last-trade timestamp and price fields |
| [Groww backtesting candles](https://groww.in/trade-api/docs/curl/backtesting) | Historical endpoint, five-minute interval and request-window limits |
| [Groww orders](https://groww.in/trade-api/docs/curl/orders) | Manual entry ticket format and reference fields |
| [Groww annexures](https://groww.in/trade-api/docs/curl/annexures) | CASH, MIS, LIMIT, DAY and EQ enumerations |

Only the public NSE announcements feed received a network smoke check. It returned an RSS channel with zero items at the time checked. No authenticated Groww/Kite calls were made. Format-contract tests use fixtures modeled on the providers' public documented response formats. Tests do not prove subscription access, current entitlements, real fills, exchange completeness or broker intraday eligibility.


## v0.3 evidence/source additions (reviewed 2026-10-30)

- [NSE official RSS directory](https://www.nseindia.com/static/rss-feed): exact endpoint links for the seven corporate feeds, inspected in the public page. Actual network coverage states are retained in `docs/research/public-context-smoke-2026-10-30.json`; no complete-feed guarantee is inferred.
- [NSE ETF market page](https://www.nseindia.com/market-data/exchange-traded-funds-etf): NIFTYBEES/BANKBEES/ITBEES as market/banking/IT context proxies, not actual index levels or recommendations.
- [Groww quote documentation](https://groww.in/trade-api/docs/curl/live-data): exchange trade timestamp in milliseconds, provider day change and quote/depth fields.
- [Kite market-data documentation](https://kite.trade/docs/connect/v3/market-data-and-instruments/): batch quote semantics, timestamps and previous close.
- [Groww contract-note retrieval](https://groww.in/help/my-account/ma-others/where-can-i-get-the-contract-note): private reports download path.
- [Zerodha contract-note interpretation](https://support.zerodha.com/category/console/reports/contract-note/articles/what-is-a-contract-note-and-how-to-interpret-it): daily aggregation, unavailable scrip-wise charges and charges outside the note's scope.
