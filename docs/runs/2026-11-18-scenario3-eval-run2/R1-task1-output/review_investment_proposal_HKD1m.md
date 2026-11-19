# Review — investment_proposal_us_equity_HKD1m.md (numbers & compliance check)

**Reviewer:** Risk manager · **Status:** review only — the proposal file was **not** rewritten.
**Important caveat:** `investment_proposal_us_equity_HKD1m.md` is **not present in my workspace** (I only have `risk_assessment_us_equity_portfolio.md`, `review_client_introduction.md` and `inbox/client_introduction_plain_language.md`). The human confirmed they do not hold it either. This review is therefore built from (a) the figures quoted in the review brief, (b) the two documents in the shared workspace that the proposal is derived from, and (c) independent arithmetic and a fresh tax/FX fact-check. **Every correction below must be re-checked against the actual proposal text before delivery.** Items marked ⚠ are unverified because the source text was unavailable.

---

## 1. Allocation table — internally consistent, but the FX rate is used inconsistently

Checked at **USD/HKD 7.846** (confirmed as the 17 Nov 2026 mid-market rate: 7.8461) on HKD 1,000,000:

| Sleeve | Weight | HKD | USD @ 7.846 |
|---|---|---|---|
| VOO | 40.0% | 400,000 | 50,981 |
| VTI | 20.0% | 200,000 | 25,491 |
| VEA | 15.0% | 150,000 | 19,118 |
| QQQ | 10.0% | 100,000 | 12,745 |
| BND | 7.5% | 75,000 | 9,559 |
| SGOV | 7.5% | 75,000 | 9,559 |
| **Total** | **100.0%** | **1,000,000** | **127,453** |

- Weights sum to exactly 100%; HKD column sums to exactly 1,000,000; USD column sums to **127,453** (not 128,000).
- **Correction 1.1 — FX inconsistency.** The risk assessment and the client introduction both convert at **7.80** (≈USD 128,000 / 128,200). At 7.846 the same portfolio is **USD 127,453** — a difference of ~USD 750. Pick **one** rate (7.846, stated "as of 17 Nov 2026") and use it in the allocation table, the drawdown USD column, the estate-tax paragraph and the data caveats. Do not mix 7.80 and 7.846 in one document.
- **Correction 1.2 — rounding.** If the table shows USD figures, show them to the nearest USD 100 with "≈" — the exact figures above are not round numbers and a client will try to add them up.
- ⚠ **Correction 1.3 — allocation mismatch.** The client introduction uses **VOO 40 / VTI 20 / VEA 15 / QQQ 10 / BND 7.5 / SGOV 7.5** (6 funds, 70% US). The risk assessment reviews **VOO 45 / VTI 10 / QQQ 15 / VEA 15 / VB 5 / BND 5 / SGOV 5** (7 funds, 75% US) and recommends moving to the 6-fund version. If the proposal still shows the 7-fund 45/10/15/15/5/5/5 table, it contradicts the client-facing document. **The proposal must carry the final, single allocation** — and if it is the 7-fund version, the client introduction's "70% US / 15% non-US / 15% ballast" and "six low-cost funds" are wrong.

## 2. Compounding table (section 5) — ⚠ cannot be verified; here are the correct numbers

Lump sum **HKD 1,000,000**, annual compounding:

| Return | 10 years | 20 years |
|---|---|---|
| 3% | **1,343,916** | **1,806,111** |
| 6% | **1,790,848** | **3,207,135** |
| 8% | **2,158,925** | **4,660,957** |
| 10% | **2,593,742** | **6,727,500** |

Common errors to look for: simple interest (10% × 10 yrs = 2,000,000 instead of 2,593,742), or compounding 8% for 20 years as 2,600,000 (that is 10% for 10 years). **Correction 2.1:** replace any figure in the table that differs from the bold numbers above.

**HKD 5,000/month** (end-of-month contributions, monthly compounding at r/12):

| Return | 10 years | 20 years |
|---|---|---|
| 3% | 698,707 | 1,641,510 |
| 6% | 819,397 | 2,310,204 |
| **8%** | **914,730** | **2,945,102** |
| 10% | 1,024,225 | 3,796,844 |

- **Correction 2.2 — the brief's figures are wrong.** "~HKD 3.1m at 10 years" and "~HKD 7.6m at 20 years at 8%" are **not** achievable by HKD 5,000/month. At 8% the correct answers are **≈HKD 0.91m after 10 years** and **≈HKD 2.95m after 20 years**. HKD 3.1m at 10 years would require ~HKD 17,000/month; HKD 7.6m at 20 years would require ~HKD 12,900/month at 8%. If the proposal contains 3.1m / 7.6m, it **overstates the outcome by roughly 2.5×** and must be corrected before the client sees it.
- **Correction 2.3 — label the basis.** State explicitly "contributions at the end of each month, returns compounded monthly, no fees, no tax, no inflation". A 20-year 8% projection that ignores the ~0.05% fund fee, ~0.4% withholding drag and ~0.1–0.5% FX conversion cost overstates the result by roughly 10–15%.
- **Correction 2.4 — add a real-return line.** At 3% inflation, 8% nominal ≈ 4.85% real: HKD 1,000,000 → **≈HKD 1.60m in today's money after 10 years** and **≈HKD 2.58m after 20 years**. Without this, a 20-year HKD 4.66m figure reads as wealth when it is roughly HKD 2.6m of purchasing power.

## 3. Drawdown and recovery — arithmetic correct, one historical mislabel

| Scenario | Value | Loss | Recovery needed | Years at 7% p.a. |
|---|---|---|---|---|
| −30% | 700,000 | −300,000 | **+42.9%** | 5.3 |
| −45% | 550,000 | −450,000 | **+81.8%** | 8.8 |
| −55% | 450,000 | −550,000 | **+122.2%** | 11.8 |

- **+43% / +82% / +122% are correct** (42.9 / 81.8 / 122.2). HKD figures are correct.
- **Correction 3.1 — the 2007–09 figure is mislabelled.** The client introduction says the US market fell "about 49% peak-to-trough in 2007–09". The 2007–09 fall was **−56.8%**; **−49.1%** was **2000–02**. Fix to: "about 57% in 2007–09 and about 49% in 2000–02". Check the proposal for the same error.
- **Correction 3.2 — recovery time is presented as a forecast.** "Expect 5–7 years to recover" is the *worst-case* range (2000–02 = 7.2 yrs, 2007–09 = 5.5 yrs); the median post-1945 bear recovered in ~2 years. Reword to "in the two worst modern crashes it took about 5.5 and 7 years; the median was about 2 years, but plan for the bad case."
- **Correction 3.3 — "history says markets have always come back"** is a survivorship statement. Add "in the US, so far" and note Japan 1989 / Nasdaq 2000 took 15–25 years.
- **Correction 3.4 — USD loss column.** If the drawdown table shows USD losses, recompute at the single chosen FX rate (at 7.846: −38,200 / −57,300 / −70,100, not −38,500 / −57,700 / −70,500 which are 7.80 figures).

## 4. Risk disclosures — mostly adequate; three statements are misleading as written

**Estate tax.** The substance is right and independently confirmed: USD 60,000 NRA exemption, **explicitly not indexed** (IRS, updated 28 Jun 2026); top marginal rate **40%** (IRC §2001(c)); **Form 706-NA** required (IRS, updated 10 Nov 2026); HK has no US estate-tax treaty; Irish UCITS (CSPX/VUAA/VWRA) are non-US-situs. At 7.846: portfolio **USD 127,453**, exposed above the threshold **USD 67,453**, potential tax at 40% **≈USD 26,981 ≈ HKD 211,700**.
- **Correction 4.1 — conflated exposure and tax.** The client introduction says "the amount exposed above that threshold is roughly USD 27,000, or about HKD 210,000, which could mean a tax bill of up to about HKD 84,000". That is wrong twice: **USD 67,453 is exposed**, and the potential tax is **≈USD 27,000 ≈ HKD 212,000** — not HKD 84,000. (HKD 84,000 looks like USD 27,000 × 3.1, or a 40% rate applied to the wrong base.) Fix to: "about USD 67,000 of your holdings would sit above the threshold, which could mean a tax bill of up to about USD 27,000 (≈HKD 212,000)."
- **Correction 4.2 — scope.** Say the USD 60,000 threshold applies to **all** US-situs assets the client owns (US stocks, US-listed ETFs, US property), not just this portfolio, and that the estate must file Form 706-NA within 9 months while the broker may freeze the account.
- **Correction 4.3 — the Irish route is not free.** Add that UCITS alternatives carry slightly higher fees and, for some lines, wider spreads, and that the 15% is withholding *at fund level* (not a rate the client claims).

**Withholding tax.** 30% statutory rate for HK residents, W-8BEN does not reduce it, Irish funds pay 15% at fund level under the US–Ireland treaty — all independently confirmed (TradeSmart 13 Mar 2026; TIN Compliance 26 Oct 2026; Vested Nov 2026; Sonic Wallet 2 Nov 2026).
- **Correction 4.4 — the drag is understated.** On a 1.2–1.5% blended yield, 30% withholding is **0.36–0.45% p.a. (HKD 3,600–4,500/yr)**. The "~HKD 60,000+ over 15 years compounded" figure should be labelled as *undiscounted cumulative* (15 × 4,000 = 60,000); compounded at 8% the opportunity cost is closer to HKD 110,000. Either state the basis or drop the number.
- **Correction 4.5 — missing disclosure.** Add that US capital gains are generally not taxed for NRAs but **US estate tax can apply on death**, and that HK does not tax capital gains or dividends — so the client does not assume "no US tax".

**Other disclosure gaps (add, do not rewrite):**
- **Correction 4.6** — state the **SRI / risk rating (5 of 7, high)** and that the portfolio is ~75% single-country equity, ~85% single currency, with ~85% overlap between VOO and VTI.
- **Correction 4.7** — state that the **0.05% cost figure is the fund expense ratio only**; broker commission, HKD→USD conversion (~0.1–0.5% per conversion), bid-ask spread and withholding are extra.
- **Correction 4.8** — date-stamp the market data ("as of November 2026") for forward P/E 17.7× and CAPE 37–39×, and note the method (daily vs consensus forward P/E differ: 17.6× vs 20.1×).
- **Correction 4.9** — add "ETF prices can fall as well as rise; you may get back less than you invest" and "this document is not issued by an SFC-licensed corporation and is not a solicitation".

## 5. Promise-of-returns / personalised-advice language — needs tightening

The disclaimer is present and broadly adequate (simulation, not advice, not an offer, no returns promised, can lose money, tax to be confirmed). But several sentences read as forecast or advice:
- **Correction 5.1** — "Expect 5–7 years to recover" → "in the worst modern crashes it took 5.5–7 years; the median was ~2 years". ("Expect" is a forecast.)
- **Correction 5.2** — "history says markets have always come back" → "in the US, so far, markets have always recovered — but not every market has (Japan 1989, Nasdaq 2000)".
- **Correction 5.3** — "many people choose the Irish versions for exactly this reason" → "many investors choose…; this is a decision for you and your tax adviser". As written it is a soft recommendation.
- **Correction 5.4** — any sentence of the form "you should / we would put your money in…" should be "in this simulation we would…". The proposal must not read as an instruction to transact.
- **Correction 5.5** — the compounding table must carry a header such as "**Illustration only — not a projection or promise of returns. Actual results will differ and may be negative.**" A 20-year 10% column (HKD 6.73m) with no such header is the single most likely source of a mis-selling complaint.
- **Correction 5.6** — add "past performance is not a reliable indicator of future results" next to the historical return figures, not only in the footer.

---

## Verdict

**Not fit to hand to the client in its current state.** The drawdown arithmetic is sound and the tax framework is broadly right, but there are **three blocking errors**:

1. **The HKD 5,000/month figures (3.1m at 10 yrs / 7.6m at 20 yrs at 8%) are wrong by roughly 2.5×** — correct values are **≈HKD 0.91m** and **≈HKD 2.95m**. This is a material overstatement of outcomes.
2. **The estate-tax paragraph states HKD 84,000 of potential tax** — the correct figure is **≈HKD 212,000** (USD 67,453 exposed × 40%), and it conflates exposure with tax.
3. **The allocation is inconsistent across documents** (6-fund 40/20/15/10/7.5/7.5 vs 7-fund 45/10/15/15/5/5/5) and the FX rate is mixed (7.80 vs 7.846).

Fix 1–3, apply corrections 3.1, 4.1, 5.1–5.5, and the document becomes suitable as an **educational simulation** for a 25-year-old HK first-time investor. It should still carry the SFC/licensed-status line and a "confirm tax with an adviser" note.

**Unfinished:** the proposal file itself was never readable, so section 5's table and the exact wording of the tax and disclaimer sections could not be checked line by line. Re-run this review against the actual file before delivery.
