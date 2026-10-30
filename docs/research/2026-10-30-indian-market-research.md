# Indian market research and product assessment

**Historical assessment:** code findings below describe v0.1 before implementation. See [v0.2 release status](../release-status.md) for delivered changes and remaining gates.

Research date: **30 October 2026, IST**. Intended user: **one individual using a personal trading assistant**, with Groww and Zerodha support. This is product and engineering research. It does not establish that any proposed setup has a trading edge.

## Recommendation

Build a local daily trading desk around four recurring jobs: prepare, monitor, decide, and review. Preserve the eleven skills as entrypoints into one shared application. The next release should make it possible to connect an account, prepare a watchlist and follow a complete session without editing JSON or repeatedly running commands.

The existing repository is a tested prototype. Its offline tests establish useful software invariants, but its synthetic demonstration and undocumented live-account behavior do not establish readiness for daily market use. The highest priorities are Indian market correctness, onboarding, verified data, persistent operation and realistic accounting. Additional strategies follow those foundations.

## Research method and limits

Reviewed regulator/exchange circulars, exchange product descriptions, official index methodology, broker pricing, API specifications, broker support pages and primary statistical research. Inspected the current engine, CLI, installer and validation report. Sources are linked beside the findings below. No broker credentials, real orders, paid subscriptions or user-account records were accessed. This turn changes documentation only.

Distinguish four evidence classes: **verified published fact**, **local code finding**, **product recommendation**, and **unresolved operational detail**. Current rules and announced future rules are separate. General website summaries do not override more specific dated circulars. Provider marketing is not proof of a particular account's entitlements.

## 1. Session structure must be instrument-specific and dated

**Verified:** NSE's current CAS documentation distinguishes eligible derivative-underlying cash stocks from non-CAS stocks. The former enter a 15:15–15:35 closing auction; the latter retain continuous trading until 15:30. CAS excludes stop-loss orders. These cash shares remain relevant even when the assistant does not support trading derivatives. [NSE CAS specification](https://www.nseindia.com/static/products-services/closing-auction-session).

**Announced, future effective:** SEBI's 15 October circular schedules revised CAS timings from **7 December 2026**, with a separate **8 February 2027** effective date for paragraph 4.8 order-transition changes. The December auction is 15:30–15:40. Store both effective dates; do not activate announced rules early. [SEBI circular, including implementation timeline](https://www.sebi.gov.in/sebi_data/attachdocs/oct-2026/1792079571420.pdf), [broker implementation summary](https://zerodha.com/marketintel/bulletin/461085/changes-to-closing-auction-session-cas-from-december-7-2026).

**Code finding:** `india_trader/core.py:329` accepts historical sessions only when they contain exactly 75 five-minute bars. A 09:15–15:15 continuous session has 72 such intervals. Changing only a calendar close will therefore still exclude it. The current calendar is keyed by exchange/date and cannot distinguish two stocks with different session classes on that date.

**Decision:** Introduce session phases, eligibility classes, effective intervals and broker-specific exit deadlines. Expected bar grids must be derived from the instrument's applicable continuous session. Historical tests must use the rule in force on the historical date. Test holidays, special sessions, outages and transitions between rule versions. BSE rules must be verified independently rather than inferred from an NSE identifier.

## 2. A broker cutoff is distinct from the exchange close

**Verified:** Zerodha documents different current auto-square-off times for CAS cash stocks and other cash stocks: 15:12 and 15:25 respectively. Its GTT/alert timing also depends on instrument class. [Zerodha CAS support](https://support.zerodha.com/category/trading-and-markets/trading-faqs/general/articles/closing-auction-session).

Groww's general help describes automatic intraday square-off from 15:20, while its CAS explanation describes the earlier end of continuous trading for eligible shares. A generic help-page cutoff is insufficient evidence for every stock/session. [Groww square-off help](https://groww.in/help/stocks%2C-f%26o%2C-ipo-%26-mtf/sx-margin/what-are-intraday-square-off-charges-1), [Groww CAS explanation](https://groww.in/blog/closing-auction-session).

**Decision:** Resolve an effective exit deadline from the instrument's trading phase, provider's verified product rules and a configurable safety buffer. Show the source and review date. Unknown broker exceptions remain unverified. The present 15:10 example is a synthetic/conservative setting, not a verified universal deadline. The assistant must warn about an approaching cutoff even if quote data has failed.

## 3. Tradability is more than a stock symbol

**Verified:** NSE's tick-size schedule varies by price band and is reviewed monthly; the applicable security file is authoritative. A historical instrument also needs its historical tick regime. [NSE tick-size circular](https://nsearchives.nseindia.com/content/circulars/CMTR67133.pdf).

GSM stages can impose full margins, trade-for-trade treatment, additional deposits or limited trading days. ASM has its own stage-dependent consequences. Do not equate every surveillance flag with the same prohibition. [NSE GSM](https://www.nseindia.com/static/regulations/graded-surveillance-measure), [NSE surveillance overview](https://www.nseindia.com/static/regulations/exchange-market-surveillance-actions).

Stock price bands and dynamic operating ranges differ. A dynamic band is not a guarantee of liquidity or a permanently fixed limit. Market-wide index circuit breakers are another mechanism. [NSE price bands](https://www.nseindia.com/static/products-services/equity-market-price-bands), [operating-range FAQ](https://www.nseindia.com/static/trade/price-band-operating-range-flex-faqs), [market-wide breakers](https://www.nseindia.com/products-services/equity-market-circuit-breakers).

**Decision:** Join exchange, ISIN, series, provider token, tick/lot, session class, corporate actions, surveillance status and broker product eligibility. Preserve dates/provenance. Block unsupported trade-to-trade/SME/illiquid instruments from the initial intraday workflow; review ASM by actual restrictions. Keep circuit distance, spread and available depth on the decision card. An unknown eligibility record must be visible.

## 4. Settlement and holdings require separate account models

**Verified:** NSE Clearing describes T+1 equity settlement. Short delivery can lead to buying-in auctions and close-out procedures. Those mechanics are a reason to distinguish intraday intent, deliverable holdings and unsettled quantities. [NSE Clearing equities](https://www.nseclearing.in/equities), [NSE shortages handling](https://www.nseindia.com/static/products-services/equity-market-shortages-handling).

**Decision:** Initial scope remains fully cash-funded long intraday equities. Read actual broker positions, holdings, open orders and available funds; identify their product and settlement status rather than treating every quantity as immediately interchangeable. T+0 and short selling need separate explicit models before support. Do not infer modern settlement rules from legacy labels inside an API example.

Both brokers expose account portfolio data, which makes read-only reconciliation feasible. [Kite portfolio API](https://kite.trade/docs/connect/v3/portfolio/), [Groww portfolio API](https://groww.in/trade-api/docs/curl/portfolio).

## 5. Personal onboarding should reflect real subscriptions and token lifetimes

| Capability | Zerodha | Groww | Product consequence |
| --- | --- | --- | --- |
| Published data subscription | Connect lists ₹500/month for streaming and historical candles; free Personal tier has different capabilities | API page lists ₹499/month plus taxes | Show an entitlement check and current provider link before recommending a purchase |
| Session setup | User login, request-token exchange, trading-day session | Daily access token expiry; alternative credential flow includes daily approval requirements | Guided connection and an explicit reconnect state |
| Streaming | Official Kite WebSocket/SDK support | Official GrowwFeed/SDK support | Use provider adapters behind one normalized stream |
| Read-only account context | Holdings, orders, positions and funds | Holdings, positions, orders and margin | Local journal can be compared with broker facts |

Sources: [Zerodha API pricing](https://zerodha.com/products/api/), [Kite login](https://kite.trade/docs/connect/v3/user/), [Groww pricing](https://groww.in/trade-api), [Groww authentication and limits](https://groww.in/trade-api/docs/curl), [Kite streaming](https://kite.trade/docs/connect/v3/websocket/), [Groww feed](https://groww.in/trade-api/docs/python-sdk/feed).

**Decision:** Support both providers, with one selected primary market-data provider. Do not require two paid feeds to begin. Offer demo, replay/import and connected modes. Store credentials through the operating system's secret store where available; never in research exports. A `doctor` view should show login, subscription, source freshness and missing capabilities separately.

## 6. Scanning should use batching and streaming, with explicit coverage

**Verified:** Kite documents distinct quote/history quotas; Groww groups request quotas across endpoint types. Streaming capacity is much larger than a small personal watchlist. [Kite rate limits](https://kite.trade/docs/connect/v3/exceptions/), [Groww shared quotas](https://groww.in/trade-api/docs/curl).

**Code finding:** Current watch mode refreshes one instrument, repeatedly downloads session history and exits on a trigger/error. It is useful for a CLI check, but it is not a persistent multi-symbol session service. Quote timestamps represent last trade; a separate feed heartbeat is needed to distinguish an illiquid stock from a broken connection.

**Decision:** Start with 20–50 actively monitored eligible stocks and index/sector context. Seed discovery from a defined liquid universe, then rank by turnover, spread, depth and relative volume. Nifty 500 membership offers a documented starting universe, not proof of intraday liquidity for every member. [Nifty 500 definition](https://www.niftyindices.com/indices/equity/broad-based-indices/nifty-500).

Persist data, incrementally backfill gaps, subscribe to live updates and finalize bars using exchange time. Track expected/observed coverage, reconnects and feed age. Use a process-level request budget per provider. Missing coverage must not become a negative trading signal.

## 7. Historical availability must be probed, not inferred from marketing

Groww's API page describes a limited historical offering, while its dedicated backtesting documentation describes a broader archive and per-request duration limits. A 30-day request limit for five-minute data is not itself a 30-day retention limit. These documents do not prove a given account can retrieve every stock/date. [Groww product description](https://groww.in/trade-api), [Groww backtesting specification](https://groww.in/trade-api/docs/curl/backtesting).

**Decision:** During setup, test a small recent request and one older requested window, record earliest confirmed availability and cache permitted data locally. Keep missing, zero-volume, incomplete and not-entitled states distinct. For stronger research, evaluate a licensed historical provider or NSE's historical products only after an actual coverage/cost comparison. [NSE historical data products](https://www.nseindia.com/static/market-data/eod-historical-data-subscription).

## 8. Costs can determine whether a setup is usable

**Verified:** The two brokers' published equity brokerage schedules differ, including caps and minimums. Statutory charges have buy/sell-side differences and GST treatment. Their pages also represent NSE transaction/IPFT charges differently, so copying one headline percentage into a universal calculator would be poor engineering. [Zerodha charges](https://zerodha.com/charges/), [Groww charges](https://groww.in/pricing).

**Illustration, brokerage only:** For a ₹10,000 entry sold for ₹10,020, gross profit is ₹20. Applying the currently displayed percentage schedules below their caps gives approximately ₹6 brokerage on Zerodha versus ₹20 on Groww, before statutory levies. This is arithmetic illustrating cost sensitivity, not a reconciled contract-note estimate.

**Code finding:** Current `costs()` applies one aggregate bps value plus one fixed roundtrip fee. It uses entry notional and does not model actual exit notional, per-executed-order rounding, partial fills or product-specific charges.

**Decision:** Add effective-dated broker/exchange/product fee schedules with a transparent breakdown and reconciled examples. Show net target reward, estimated stop loss, breakeven movement and stressed slippage. Separate statutory fees, brokerage and execution assumptions. Flag rate-source conflicts for verification against official circulars and contract notes.

## 9. News quality depends on identity, timestamps and availability

NSE offers public corporate filing pages/RSS and commercial corporate-data products. An accessible RSS channel is not a completeness or delivery-latency guarantee. The existing smoke check returned an empty channel; it did not establish that there were no announcements. [NSE RSS directory](https://www.nseindia.com/static/rss-feed), [corporate filings](https://www.nseindia.com/companies-listing/corporate-filings-announcements), [corporate-data products](https://www.nseindia.com/static/market-data/corporate-data-subscription).

**Decision:** Preserve filing identity, company/ISIN, publication/dissemination/receipt times, original attachment and revisions. Deduplicate across exchanges. An LLM may summarize a sourced filing, but a symbol match or keyword must not establish its contents. Separate confirmed facts, extracted numbers, interpretations and unanswered questions. News ingestion must not execute instructions embedded in filings.

RSS is an inexpensive discovery input. If coverage cannot be established, display “filing coverage unverified” and link the original exchange page. Paid feeds are an optional upgrade after a personal budget review; do not build an expensive commercial feed into the basic experience.

## 10. Indian earnings need fiscal periods and structured filings

NSE directs results for March 2025 onward to Integrated Filing–Financials and publishes XBRL information/utilities. An earnings tool should follow those structures rather than assuming every filing is an independent quarterly revenue/profit table. [NSE financial results notice](https://www.nseindia.com/companies-listing/corporate-filings-financial-results), [XBRL information](https://www.nseindia.in/static/companies-listing/xbrl-information), [NSE integrated-filing circular](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NSE_Circular_02042025_0.pdf).

**Decision:** Prefer structured XBRL/official tables; use PDF extraction with field-level source references and confidence checks as fallback. Model Indian fiscal years, quarter versus cumulative periods, standalone/consolidated basis, restatements, exceptional items and ₹/lakh/crore units. A derived Q4 from annual minus nine-month results must be marked derived and reconciled. Bank/NBFC statements need sector-specific metrics. Keep the current arithmetic-only analyst clearly labeled until extraction is validated.

## 11. Market context should help interpret a setup

**Recommendation:** A morning brief should show index/sector performance, breadth over the covered universe, previous-day levels, overnight gaps, current liquidity and known company/macro events. Scheduled items need official-source dates; the assistant should not invent a live economic calendar or a directional consequence.

NSE labels institutional trading activity as provisional and subject to revision. Such daily information should be presented with its actual period and availability time, rather than described as live institutional buying. [NSE FII/DII reports](https://www.nseindia.com/reports/fii-dii).

Relative strength, relative volume and VWAP context are candidate research features. Their incremental predictive value is unproven here. Compare each feature against a simple baseline before using it to rank trades.

## 12. Strategy research needs a stronger evidence standard

**Verified research:** Backtest selection itself creates overfitting risk. Repeatedly trying variants and reporting the best result can materially misrepresent future performance. [Bailey et al., The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).

**Code finding:** Current simulation independently samples candles by time slot, loses serial dependence, uses current plan tick settings in historical replay and exposes model frequencies without calibration against future sessions. Its mean-R calculation omits fixed order fees and its historical table uses gross R. Those limitations are disclosed but still constrain decisions.

**Decision:** Establish timestamp-correct event replay, one consistent fee/execution model, frozen strategy definitions and chronological out-of-sample evaluation. Preserve raw and adjusted data separately; account for corporate actions and historical universe membership. Model spread, partial fills, gap-through-stop events and non-fills at circuit locks. Keep bootstrap results in a research view, clearly separate from observed outcomes and any validated probability estimates. Do not optimize to a target win rate.

## 13. Discipline and review are core product features

SEBI's cash intraday study reported that seven out of ten individual intraday traders lost money in the studied population; this is a historical study, not an estimate of this user's odds. Its product implication is to prioritize costs, abstention and review over increasing trade frequency. [SEBI cash-intraday study release, July 2024](https://www.sebi.gov.in/media-and-notifications/press-releases/jul-2024/sebi-study-finds-that-7-out-of-10-individual-intraday-traders-in-equity-cash-segment-make-losses_84948.html).

The August 2026 SEBI derivatives profitability report records 87.7% net loss-makers in FY26. This is a different product/population and must not be applied to cash-equity performance. [SEBI FY25–FY26 derivatives study](https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1787233506209.pdf).

**Decision:** Include pre-trade intent, accepted/skipped candidates, rule overrides, actual fills, screenshots/notes, fees and post-trade review. Track planned versus actual risk, slippage, adverse/favorable excursion and behavior such as chasing or repeated entries. A local “pause new ideas” control pauses the assistant; it is not a broker kill switch or position closure.

## 14. The assistant should complement existing broker tools

Groww already offers technical discovery and a trading terminal; Zerodha Console already provides reporting and trade tagging. Merely recreating indicators and a P&L table would provide limited differentiation. [Groww intraday screener](https://groww.in/updates/intraday-screener-on-groww), [Groww Terminal](https://groww.in/charts), [Zerodha Console](https://zerodha.com/products/console).

**Recommended differentiator:** A persistent decision record linking the original evidence, market context, setup definition, fee calculation, risk result, user's decision and eventual outcome. The useful question is “Why is this on my screen, and what changed since I last looked?” rather than an unexplained score or a promise of an AI edge. Usability and usefulness still require direct testing with the user; this research is not a user interview study.

## 15. Personal tools, public products and execution have different obligations

Kite explicitly distinguishes static-IP requirements for API order placement from read-only/streaming access. Read-only onboarding should not demand an execution deployment. NSE's retail-algo FAQ also states that API orders receive algo treatment/tagging even within the OPS threshold; “below ten orders per second” is not a blanket exemption. [Kite static-IP policy](https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/static-ip), [NSE retail-algo FAQ](https://nsearchives.nseindia.com/web/sites/default/files/inline-files/FAQ_Retail_Algo_03112025_NSE.pdf), [SEBI framework](https://www.sebi.gov.in/sebi_data/attachdocs/feb-2025/1738665456458.pdf).

NSE data redistribution depends on agreed rights. SEBI's May 2026 education-data circular, effective July 2026, changes the relevant educational-data lag to 30 days. That is not a rule that every private research tool must delay its own authorized broker feed. It does mean a public “educational” simulator is not automatically licensed merely because it uses paper trades. [NSE data policy](https://www.nseindia.com/static/market-data/nse-data-policy), [SEBI education-data circular](https://www.sebi.gov.in/sebi_data/attachdocs/may-2026/1778242522289.pdf).

**Decision:** Keep the first product local, personal, read-only and paper/manual. Open-source code does not grant exchange-data redistribution rights. Cloud aggregation, subscriptions, public signal distribution and any order-writing feature require their own current broker/data/regulatory review. A disclaimer is not a substitute for that review.

## Current-project gap assessment

| Priority | Observed gap | User consequence | Next action |
| --- | --- | --- | --- |
| P0 | Exactly 75 historical bars; exchange/date-only calendar | Legitimate sessions rejected; historical rules conflated | Instrument/session policy engine |
| P0 | Manual calendar and instrument-master preparation | Setup requires market-data engineering | Guided sync with provenance and validation |
| P0 | No authenticated broker integration evidence | Documented contracts may differ from actual access | Private read-only provider test matrix |
| P0 | Illustrative aggregate fees | Net reward and risk can be misleading | Reconciled provider-specific cost engine |
| P0 | Local paper account detached from broker facts | Existing exposure can be overlooked | Read-only positions/orders/funds reconciliation |
| P1 | Foreground single-instrument watch | Monitoring stops on sleep, process exit or errors | Persistent session service and health view |
| P1 | One current plan/order; no plan lifecycle | Stale or overlapping ideas become hard to manage | Stable candidate/plan IDs and state transitions |
| P1 | CLI/JSON-first interaction | High daily operating effort | One setup flow and a local dashboard |
| P1 | Synthetic-only end-to-end proof | No evidence about real feed behavior or fill quality | Timestamped replay and live shadow sessions |
| P1 | Keyword news and hand-entered earnings | Material events can be missed/misinterpreted | Sourced event ingestion and structured extraction |
| P2 | Eleven installed copies of the engine | Updates can drift between skills | Thin skill wrappers against one versioned engine |

## Unresolved items to verify during implementation

1. Actual account entitlements, older-history depth, adjusted/unadjusted behavior and payload edge cases for each provider.
2. Groww's exact current CAS-stock intraday deadlines and implementation of announced future session changes.
3. Primary BSE security/session metadata, product restrictions and source update behavior.
4. Source-of-truth charge decomposition and rounding against dated contract notes; reconcile headline fee differences.
5. Practical filing-feed completeness and latency at a personal-use budget.
6. Lawful retention/use terms for each selected historical/news provider and for any future sharing feature.
7. The user's actual trading hours, capital/risk preferences and whether a machine is available for full-session monitoring. Capture these in setup, not as invented defaults.

The proposed implementation sequence and measurable release gates are in [ROADMAP.md](../../ROADMAP.md). No claim of strategy profitability or market-ready operation follows from this research alone.
