# Research methodology

## Signal and exits

The opening range comprises the first three closed five-minute candles after the explicitly configured session open. A long signal occurs on the first subsequent candle whose close exceeds the opening-range high. Its entry time is that candle's close, never its opening timestamp. Missing bars invalidate coverage. Breakouts outside the configured entry window expire; an earlier ineligible first breakout is not replaced by a later one.

The midpoint of the opening range is rounded down to the instrument tick and used as the stop. The target is `entry + target_R × (entry − stop)`, rounded down to tick. This is a research rule, not a claim that midpoint stops or ORB trades are profitable. Planning uses the signal close as an intended entry; actual fills can differ.

## Bootstrap replays

1. Keep up to the last 60 complete verified sessions **strictly before** the plan date. At least 20 slot-aligned observations are required. Derive each grid from its dated continuous-session policy and instrument metadata; supported CAS/non-CAS and sourced special sessions can have different lengths. Missing/duplicate/misaligned candles and unavailable historical metadata are excluded.
2. Represent each candle's OHLC relative to its preceding close. The first candle uses its own open as the denominator. Ratios preserve an individual candle's internal OHLC structure.
3. From the plan entry through flat-by, sample a candle independently from that exact time-of-day slot across prior sessions. Scale the OHLC ratios to the simulated prior close. Seeded randomness makes runs reproducible for the same inputs and Python random algorithm.
4. Gap below the stop exits at the simulated open. Gap above the target exits at the target conservatively. Otherwise a candle touching both exits at the stop. This avoids assuming a favorable intrabar ordering when OHLC cannot determine it.
5. Count target/stop/neither. Mark any remaining position at the last simulated close before flat-by. Report mean R after configured proportional charges and slippage; fixed per-order charges are excluded because the replay happens before position sizing.

These probabilities are **conditional frequencies under the resampling model**, not probabilities validated against future outcomes. Independent candles destroy serial dependence, volatility clustering and coherent session-level news effects. Circuit locks, queueing, market depth, partial fills, delayed exits and out-of-distribution events are not modeled. Corporate-action adjustments and survivorship bias are the researcher's responsibility. More replays reduce sampling noise under this model; they do not remove model error.

## Historical strategy replay

The historical replay is separate from the bootstrap. For each complete prior session, recompute the ORB signal, midpoint stop and R target using only that session's bars and configured session windows. Replay subsequent candles to that session's flat-by. The historical table reports each trade's gross R; inspect it separately from simulation R after variable costs. Small samples, universe selection and parameter tuning can create misleading apparent edges. This release deliberately avoids categorical claims such as “strong buy” or “guaranteed edge.”

## Position sizing and risk

Sizing chooses the largest whole-share quantity satisfying per-trade estimated risk, starting-capital position cap, and cash buffer including estimated roundtrip charges. Risk independently recomputes these constraints using a fresh quote, verifies the plan age/session/tick, and checks duplicate symbols and daily reserved risk. Tickets and paper fills run risk again rather than trusting a saved PASS file.

Each paper fill records its exact order hash. The engine permits one entry per instrument per day, including after a close. No pyramiding or same-day re-entry is implemented. A paper close requires a fresh quote but is independent of entry-window and daily-entry limits.

The local journal fully funds buys even though broker tickets use MIS. It does not borrow from broker margin. Estimated charges are reserved in full at entry and deducted once. Slippage affects risk estimates and replay R; local paper fills record the chosen limit and paper exits record the supplied quote, so journal P&L is an illustrative accounting result, not an execution-quality backtest.


## v0.2 chronological desk replay

`replay` and the Research view use `causal-orb-v2`, separate from the seeded candle-resampling experiment above. The frozen long ORB baseline uses only completed sessions strictly before the research clock. It selects the first executable observation after signal close: next-bar open must be above the stop and at/below the planned buy limit. It conservatively charges the limit entry and refuses later-touch/queue assumptions. Stop gaps and ambiguous bars retain conservative stop-first treatment; non-target exits include configured slippage. No fee profile or dated metadata means exclusion, never a current-rate historical substitution.

Session dates are split chronologically (default 70% training / 30% held-out) before outcomes are summarized. No parameter search is performed. Every distinct recorded run ID is retained, including losses and inconclusive results. Net/gross results, fees, drawdown and missed fills are descriptive. Maximum excursion includes the exit bar's OHLC, whose exact within-bar sequence is unknown. Corporate-action adjustment and historical universe reconstruction remain separate requirements.
