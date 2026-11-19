# Simulated US Equity Investment Proposal — HKD 1,000,000 (age 25)

Client profile (confirmed): 10+ year horizon, capital growth objective, high risk tolerance (accepts 30–40% temporary drawdown), long-only, no leverage, no need to hold HKD cash.
Market data as of 17–18 Nov 2026 (see us_market_hkd_brief.md).

## 1. Allocation (USD 127,450 ≈ HKD 1,000,000 at USD/HKD 7.8461)
| Sleeve | ETF | Weight | HKD | USD |
|---|---|---|---|---|
| US large-cap core | VOO (S&P 500) | 45% | 450,000 | 57,350 |
| US growth / tech tilt | QQQ (Nasdaq-100) | 15% | 150,000 | 19,120 |
| US small/mid-cap | VXF (US extended market) | 10% | 100,000 | 12,745 |
| Non-US developed + EM | VXUS | 20% | 200,000 | 25,490 |
| Cash buffer (USD T-bills / money market) | — | 10% | 100,000 | 12,745 |

## 2. Why this split
- **VOO 45% — the base.** Broadest, lowest-cost (0.03%) way to own US earnings; most of the long-run growth comes from here.
- **QQQ 15% — growth tilt, deliberately trimmed.** A 25-year-old with a 10+ year horizon can take growth risk, but 65% in US large-cap (VOO+QQQ) would double up on the same mega-cap AI names. 15% keeps the tilt without making it the portfolio's main bet.
- **VXF 10% — different engine.** US small/mid-caps behave differently from mega-caps and are less exposed to the AI-theme concentration.
- **VXUS 20% — the main diversifier.** Non-US markets are a much smaller share of the global index than of US market cap; 20% reduces single-country and single-theme risk.
- **Cash 10% — dry powder.** 3-month T-bills yield 4.33%, so the buffer earns a real return while funding the tranches and rebalancing without forced sales.

## 3. Market context (verified 17 Nov 2026)
- S&P 500 closed **7,340.53**, −1.03% on the day, **6.12% below its 7,818.93 record of 6 Oct 2026** (CNBC / portfolio-terminal; snippet-verified only).
- 1-year total returns to 17 Nov 2026: **VOO +11.26%, QQQ +9.34%, VXUS +11.06%** (totalrealreturns.com, dividends reinvested). Current drawdowns: QQQ −13.52%, VXUS −9.22%, VOO −6.01%.
- Historical worst drawdowns for these funds: QQQ −35.12% (2022), VOO −33.99% (Mar 2020), VXUS −35.97% (Mar 2020) — this is the basis for the 30–40% drawdown assumption below.
- US 10-yr Treasury **5.10%** (+91 bp YTD); Fed funds target 3.75–4.00%; 3-month T-bill 4.33%.
- USD/HKD **7.8461**, peg band 7.75–7.85.

## 4. Risks (quantified)
1. **Drawdown / concentration.** 90% equity: a 40% market fall ≈ HKD 400,000 paper loss (portfolio ≈ HKD 600,000). This is at the top of the client's stated tolerance — no headroom. VOO+QQQ still share mega-cap AI exposure and can fall together.
2. **Rates / valuation.** 10-yr at 5.10%, above the Fed range — elevated term premium. A further 50–100 bp rise in the long end would compress multiples, hitting the growth tilt hardest.
3. **FX (HKD/USD peg).** USD/HKD 7.8461, ~0.05% from the 7.85 weak side: further USD upside is capped at ~0.05%, while a move to 7.75 costs ~1.2% in HKD terms. Small and bounded, but one-directional — the portfolio is ~100% USD assets, unhedged.
4. **Costs and taxes.** 30% US dividend withholding for HK residents ≈ 0.4% a year of drag (see risk_review.md §5); Irish-domiciled UCITS alternatives could roughly halve it — an option to consider, not a recommendation.
5. **Behavioural.** The largest real risk is selling during a drawdown.

## 5. Execution and rules
- **Entry:** 3 tranches over ~3 months — 40% / 30% / 30% at ~monthly intervals, executed on schedule regardless of market direction (no market timing). Undeployed cash sits in T-bills.
- **Rebalancing:** annual review, plus a hard trigger at ±5pp drift for the 45%/15%/20% sleeves and ±3pp for the 10% sleeves. Rebalance from cash first.
- **Constraints:** no leverage, no individual stocks, no daily trading.
- **Monitoring triggers:** AI-capex/NVDA earnings, 10-yr yield moves >50 bp, USD/HKD approaching 7.85.

## 6. Data caveats
Still unverified and therefore not used: S&P 500 YTD return, Nasdaq-100 and Russell 2000 levels/YTD, S&P 500 forward P/E and its 10-year average, VXF 1-year return, current tariff headlines. The S&P 500 level is snippet-verified only. Expense ratios (VOO 0.03%, QQQ 0.20%, VXUS 0.05–0.07%) are issuer-published. This is a simulated proposal, not a guarantee.
