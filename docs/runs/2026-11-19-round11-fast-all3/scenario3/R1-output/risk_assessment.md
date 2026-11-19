# Risk Assessment — Simulated US Equity Portfolio
**Client:** 25-year-old Hong Kong resident · HKD 1,000,000 · objective: long-term capital growth · horizon: 10+ years · risk tolerance: high (accepts a 30–40% drawdown)
**Proposed shape:** ~70% US broad market (VOO/VTI) · ~15% growth/tech (QQQ) · ~10% diversifiers (international / small-cap value) · ~5% cash / T-bills
*Simulated illustration for discussion only — not real investment advice.*

## 1. Market / valuation risk
US equities are historically expensive on most measures (elevated trailing and forward P/E versus long-run averages), and a large share of index earnings growth is expected from a handful of AI-linked names. High starting valuations do not predict a crash, but they lower expected 10-year returns and raise the odds of sharp drawdowns. With ~85% of the portfolio in US equity, a broad de-rating would hit nearly the whole book at once. **Mitigant:** long horizon (10+ years) and staged entry (Rule 3) rather than a single lump sum.

## 2. Concentration risk
The S&P 500 is itself concentrated: the largest ~7 technology/AI names are roughly a third of the index, and QQQ is more concentrated still. Adding 15% QQQ on top of a 70% core means the portfolio's effective single-theme (mega-cap tech / AI capex) exposure is well above 40%. A sector-specific shock — AI capex disappointment, antitrust action, or a semiconductor cycle turn — would therefore be a portfolio-level event, not a diversifier. **Mitigant:** the 10% diversifier sleeve and rebalancing bands (Rule 1) cap drift.

## 3. Currency risk (HKD pegged to USD)
The HKD is pegged to the USD within a 7.75–7.85 band, so USD assets carry **little day-to-day FX risk for a Hong Kong investor** — this is a genuine advantage of a US-listed portfolio. Two caveats: (a) the peg removes FX diversification, so the client's total wealth is effectively USD-linked; (b) if the peg regime ever changed, or if the client later spends in HKD/CNY, unhedged USD exposure would matter. No FX hedge is recommended at this size — hedging costs would exceed the benefit.

## 4. US estate tax (non-resident alien) — the most under-appreciated risk
US-listed ETFs (VOO, VTI, QQQ, AVUV, etc.) are **US-situs assets**. For a non-resident alien, US estate tax applies at up to **40% on the value above a USD 60,000 exemption** — i.e. on roughly HKD 1,000,000 (~USD 128,000) of holdings, the exposure is on about USD 68,000, a potential tax of ~USD 27,000 (~HKD 210,000) if the client died holding them. This is a real, quantifiable cost that has nothing to do with market performance. **Mitigants to discuss:** (i) Ireland-domiciled UCITS equivalents (e.g. VUAA/CSPX for S&P 500, CNDX for Nasdaq-100) are generally not US-situs for estate-tax purposes and often have comparable expense ratios — the main trade-off is lower liquidity/spreads and no US-listed options; (ii) keep total US-situs holdings below USD 60,000 and hold the rest in UCITS; (iii) a US estate-tax treaty position does not currently help Hong Kong residents. **Recommendation: raise this with the client before implementation and consider a UCITS-based structure for the core.**

## 5. Liquidity risk
Low. VOO/VTI/QQQ trade tens of millions of shares daily with penny-wide spreads; T-bills/SGOV are effectively cash. The real liquidity risk is **behavioural, not structural**: selling during a panic crystallises losses, and in a severe stress episode ETF discounts to NAV can widen briefly. The 5% cash buffer (Rule 2) means the client never has to sell equities to meet an expense.

## 6. Behavioural risk in a 30–40% drawdown
The client has stated they can accept a 30–40% drawdown — in the abstract. In practice, a 35% fall on HKD 1,000,000 is a paper loss of ~HKD 350,000, and such drawdowns historically last 12–24 months. The realistic failure mode is capitulation near the bottom, which converts a temporary loss into a permanent one. **Mitigants:** pre-commit to the rules below in writing; review the portfolio at most quarterly; avoid daily price checking; remember the horizon is 10+ years and the client is 25 with decades of human capital ahead.

## 7. Three concrete risk-management rules
1. **Rebalancing bands (±5 percentage points absolute).** If any sleeve drifts more than 5pp from target (e.g. QQQ above 20% or core below 65%), rebalance back to target — quarterly check, act only when a band is breached. This mechanically trims winners and buys losers, and caps concentration creep.
2. **Cash buffer: 5% (HKD 50,000) in T-bills/SGOV, plus 6 months of living expenses outside this portfolio.** The buffer is the circuit-breaker that prevents forced selling in a drawdown; it is not part of the risk asset allocation and should be refilled from equity sales only after a recovery.
3. **Staged entry over 6–9 months (e.g. 4–6 equal tranches).** Deploy the HKD 1,000,000 in tranches rather than a single lump sum, which reduces the risk of buying at a local peak and, more importantly, gives the client time to experience volatility with smaller amounts before the full sum is at risk. Automate the tranches so the decision is not re-litigated each month.

## Summary
The main risks are **valuation/concentration** (market-driven, mitigated by horizon and rebalancing) and **US estate tax** (structural, mitigated by UCITS structuring — the one item that should be resolved before investing). Currency risk is low thanks to the peg; liquidity risk is low; behavioural risk is the highest-probability cause of a bad outcome and is best managed by the three written rules above.
