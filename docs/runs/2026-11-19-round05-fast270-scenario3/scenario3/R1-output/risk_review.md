# Risk Review — Draft US Equity Proposal (HKD 1,000,000, age 25)

Sources: `proposal_draft.md` and `us_market_hkd_brief.md` (data as of 17–18 Nov 2026). All figures below are taken from those two files; items the brief marks [NOT VERIFIED] are flagged and must not be used in client materials.

## 1. Suitability verdict — PASS, with conditions
- Horizon 10+ yrs, growth objective, long-only, no leverage: the 90% equity / 10% cash structure is consistent with the client's stated tolerance for a 30–40% temporary drawdown.
- The proposal's own drawdown figure (40% = HKD 400,000 paper loss) sits at the top of the client's accepted range — acceptable, but no headroom. Conditions: (a) tranche entry, (b) a written rebalancing rule, (c) the client must be told the 10% cash sleeve is a drag in rising markets.
- No leverage, no individual stocks: compliant. Note the draft's "VXF or IWM" is an unresolved choice — pick one before execution (VXF = US extended market, IWM = Russell 2000; different exposures).

## 2. Three biggest risks (quantified)
1. **Equity drawdown / concentration.** 90% equity → a 40% market fall ≈ HKD 400,000 loss (draft §3). Concentration is the amplifier: VOO 45% + QQQ 20% = 65% in US large-cap, and QQQ is heavily mega-cap AI (NVDA −2.6% on 18 Nov 2026 ahead of earnings). A tech-led drawdown would hit both sleeves together; the 15% VXUS and 10% cash are the only offsets. *Index-level P/E and YTD data are [NOT VERIFIED] in the brief, so no valuation-based drawdown estimate can be made.*
2. **FX (HKD/USD peg).** USD/HKD 7.8461 (17 Nov 2026), ~0.05% from the 7.85 weak-side CU. Upside from further USD strength is capped at ~0.05%; a move to 7.75 costs ~1.2% on the HKD value of USD assets. So FX is a small, bounded drag, not a major risk — but it is one-directional: the portfolio is ~100% USD assets with no HKD hedge, and HKMA intervention risk exists at the weak side.
3. **Rate sensitivity / valuation.** US 10-yr at 5.10% (+91 bp YTD), above the top of the Fed range (3.75–4.00%) — elevated term premium. High-multiple growth (QQQ 20%) is the most rate-sensitive sleeve; a further 50–100 bp rise in the long end would compress multiples, with the impact concentrated in the growth tilt. The 10% T-bill sleeve (~4.33% 3-mth) partially cushions this and earns a real yield.

## 3. Risk-management recommendations
- **Tranche schedule:** 3 tranches over ~3 months (draft §4) — keep it, but specify: 40% / 30% / 30% at ~monthly intervals, and state that tranche 2 and 3 are executed on schedule regardless of market direction (no market timing). Cash not yet deployed stays in T-bills.
- **Rebalancing bands:** annual review plus a hard trigger at ±5pp drift per sleeve (draft §4) — tighten the trigger to ±5pp for the 45%/20% sleeves and ±3pp for the 10% sleeves (VXF/IWM, cash), since small sleeves drift proportionally faster. Rebalance from cash first, then across sleeves.
- **Cash sleeve:** 10% (HKD 100,000) is appropriate for a 10+ yr growth client — it funds tranches and rebalancing without forced sales. Do not raise it above 10% (opportunity cost for a 25-year-old); do not cut it below 5% while tranches are still being deployed.
- **Monitoring:** review on NVDA/AI-capex earnings, 10-yr yield moves >50 bp, and any USD/HKD approach to 7.85.

## 4. Allocation changes I would make
1. **Resolve VXF vs IWM** (10%) — prefer VXF for broader US small/mid exposure; IWM is Russell 2000 only. Unresolved choice is an execution risk.
2. **Consider trimming QQQ 20% → 15% and lifting VXUS 15% → 20%.** Rationale: 65% US large-cap + a mega-cap AI tilt is the single largest concentration; the brief flags AI concentration and a 5.10% 10-yr yield as the two live headwinds, both of which hit QQQ hardest. This keeps the growth objective but reduces single-theme risk. (Optional — the current split is still within the client's tolerance.)
3. **Keep 10% cash** as proposed; no change.
4. **No change** to VOO 45% core.

## 5. Costs and taxes the proposal omits (added)
The draft's expense ratios cover fund fees only. Three further costs are real and currently unstated:
- **US dividend withholding tax — 30%.** The US has no tax treaty with Hong Kong, so dividends paid by US-listed ETFs (VOO, QQQ, VXF, VXUS) are withheld at the statutory 30% non-resident rate. At a portfolio dividend yield of ~1.3%, that is ~0.39% a year of lost return (1.3% × 30% ≈ 0.4%), i.e. roughly HKD 3,900 a year on HKD 1,000,000 — comparable to the fund fees themselves. *The ~1.3% yield is an assumption, not a verified figure for these ETFs; the 30% rate is the statutory default and applies unless a lower treaty rate exists.*
- **No US capital gains tax for non-resident aliens.** A Hong Kong resident is not taxed by the US on gains from selling US-listed securities, and Hong Kong does not tax capital gains. So the tax drag is on dividends only — relevant because this is a growth portfolio, where most of the return is expected to be price appreciation.
- **Trading costs and spreads.** ETF commissions at HK brokers are typically a few USD per trade (often zero-commission with a small platform fee); the bigger cost is the bid-ask spread, typically ~0.01–0.03% for VOO/VXUS-class funds and wider for less liquid ETFs. With 3 tranches and annual rebalancing, total trading cost is small (well under 0.1% of the portfolio per year) — but it argues against frequent trading, consistent with the draft's "no daily trading" rule.
- **Option to consider (not a recommendation):** Irish-domiciled UCITS ETFs (e.g. CSPX for S&P 500, VUAA accumulating) benefit from the US–Ireland treaty, which reduces US dividend withholding to 15% instead of 30% — roughly halving the ~0.4% drag to ~0.2% a year. Trade-offs to weigh before any switch: different listing/currency (LSE, USD or GBP lines), higher expense ratios than VOO, possible HK broker access and stamp-duty/spread differences, and the fact that accumulating share classes change the tax/cash-flow profile. *[UNCERTAIN] The exact saving depends on each fund's underlying dividend yield and on the 15% treaty rate being applied in practice; the ~0.2% figure is an estimate.*

## Flags / unverified
- [NOT VERIFIED] in the brief: S&P 500 / Nasdaq-100 / Russell 2000 levels, YTD returns, forward P/E and 10-yr average P/E; 1-yr total returns for VOO, VTI, QQQ, VXUS; current tariff/trade-policy headlines. None of these are used above; they must be pulled before any client-facing valuation claim.
- The draft's "~4%" cash yield is consistent with the brief's 3-mth T-bill 4.33%, but the exact money-market fund yield is not in either file.
- [UNCERTAIN] §5: the ~1.3% portfolio dividend yield is an assumption; the 30% / 15% withholding rates are statutory/treaty rates stated from general knowledge, not from a document in this session; the ~0.2% saving from Irish-domiciled ETFs is an estimate. Confirm with a tax adviser before acting.
