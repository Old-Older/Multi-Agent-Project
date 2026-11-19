# Semiconductor Risk Memo — End-2026 Perspective

**To:** Fund PMs / Analysts · **From:** Risk Management · **Status:** Internal analysis — *not investment advice*

## 1. Top risks, ranked by expected impact × probability

| # | Risk | Prob. | Impact | Trigger indicator to monitor |
|---|------|-------|--------|------------------------------|
| 1 | **AI capex digestion** — hyperscaler growth decelerating from ~100% to ~12% by 2028 | High | High | Quarterly hyperscaler capex guidance revisions; 2027 capex landing below the ~$1.0T low end |
| 2 | **Memory price reversal** — $804B 2026 → $1.06T 2027 assumes pricing holds | Med-High | High | DRAM/NAND contract price MoM; memory inventory days; HBM contract renegotiations |
| 3 | **Concentration / valuation** — ~$13T of AI market value erased from 2026 highs; SOX −12.25% on 5 Nov 2026 | High | High | Top-10 index weight; forward P/E vs. 5-yr range; breadth (advancers/decliners) |
| 4 | **China / export-control shock** | Medium | High | New BIS entity-list or rule changes; China rare-material export licences; China domestic-capacity announcements |
| 5 | **HBM oversupply after 2027** — sold out through 2027, but capacity additions land 2028 | Medium | Medium | HBM capacity-add announcements; 2028 HBM pricing pre-agreements |
| 6 | **Cost inflation / margin squeeze** — TSMC 2nm ~$30k/wafer, +6–8% in Q1 2027 | Medium | Medium | Fabless gross-margin guidance; wafer-price pass-through commentary |
| 7 | **Semicap cyclicality** — $133B 2026 → $151B 2027 (+14%) is a late-cycle growth rate | Medium | Medium | Book-to-bill; memory-maker capex plans; China equipment share |
| 8 | **Liquidity / crowding** — single-day −12% moves show thin marginal bid | Low-Med | High | ETF flows; options skew; intraday gap risk |

## 2. Stress test — core-satellite sleeve (60% broad semi ETF / 25% memory-HBM / 15% semicap)

Illustrative drawdown estimates (judgement-based, not model output):

| Scenario | Sleeve impact | Notes |
|---|---|---|
| **A. AI capex digestion** (growth ~100% → ~12% by 2028) | **−30% to −40%** | Broad ETF −25/−30%; memory −45/−55% on multiple compression; semicap −30/−35% on order push-outs. Gradual, 2–4 quarters. |
| **B. Memory price reversal** | **−25% to −35%** | Memory sleeve −50/−60% (peak-to-trough memory cycles routinely halve); broad ETF −15/−20% via index weight; semicap −20% on memory capex cuts. |
| **C. China / export-control shock** | **−20% to −30%** | Semicap worst (−35/−45%, high China revenue exposure); memory −20/−25%; broad ETF −15/−20%. Fast, gap-driven. |

**Combined A+B** (the correlated case) is the real tail: **−45% to −55%** on the sleeve. The 25% memory weight is the dominant risk contributor in every scenario — it is the sleeve's beta amplifier, not a diversifier.

## 3. Concentration and valuation risk

- The Nov 2026 drawdown (−12.25% in one session, worst since Mar 2020) is a **de-rating signal, not a fundamental break**: WSTS still forecasts +90% (2026) and +27% (2027). Both can be true — the market is repricing the *durability* of 2027–28 growth.
- Index concentration means the "broad" ETF is not diversified: a handful of AI-linked names drive most of the variance, so 60% "core" behaves like 60% concentrated AI beta.
- Memory at $804B (2026) is ~53% of the $1.51T market — an unusually high single-segment share. Cyclical segments at peak revenue share are where valuation risk concentrates.
- **Implication:** the sleeve's effective factor exposure is one trade (AI capex), not three.

## 4. Risk-management recommendations

1. **Position sizing.** Cap the sleeve at a stated % of total portfolio (e.g. ≤15–20% for a growth mandate); cap memory/HBM at ≤25% *of the sleeve* and ≤5% of total portfolio. Treat semicap as cyclical, not defensive.
2. **Rebalancing.** Calendar (quarterly) plus band-based: rebalance when any sleeve component drifts >5pp from target. Take mechanical profits after >25% sleeve gains.
3. **Trim / stop-loss triggers.** Trim 25% of the sleeve on a −15% drawdown from peak, another 25% at −25%; hard review at −30%. Trim memory first — it carries the highest downside beta.
4. **Hedges.** Overlay 3–6 month put spreads on the broad ETF (strike ~10% OTM, funded by calls) ahead of capex-guidance quarters; consider a collar on concentrated memory exposure. Hedging is cheapest when implied vol is low — i.e. now, not after a shock.
5. **Diversifiers.** Pair the sleeve with non-AI-semiconductor exposure (power/utilities, industrial automation, software) and keep a cash/liquidity buffer sized to the −45% tail case.
6. **Monitoring pack (monthly).** Hyperscaler capex guidance; DRAM/NAND contract prices; HBM lead times; SOX breadth and top-10 weight; BIS rule changes; TSMC wafer pricing; book-to-bill.

**Bottom line:** the fundamental cycle is still expanding, but the sleeve is a concentrated, late-cycle, high-beta bet on one variable — hyperscaler capex. Size it as such, hedge before the guidance quarters, and let the trigger indicators, not the narrative, drive trims.

*This document is analysis for internal discussion only and is not investment advice or a recommendation to buy or sell any security.*
