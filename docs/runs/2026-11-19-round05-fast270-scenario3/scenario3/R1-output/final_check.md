# Final consistency check — proposal_draft.md vs client_intro.md vs us_market_hkd_brief.md

Files checked: `proposal_draft.md` (with new §3 Market context and §4.4 costs/taxes), `client_intro.md`, `us_market_hkd_brief.md` (incl. "Gap fill"). Date of check: 18 Nov 2026.

## Verdict: PASS (with 2 wording notes, no figure conflicts)

## (a) Weights and HKD/USD amounts — PASS
| Item | proposal_draft.md | client_intro.md | Match |
|---|---|---|---|
| VOO | 45% / HKD 450,000 / USD 57,350 | 45% / HKD 450,000 | Yes |
| QQQ | 15% / HKD 150,000 / USD 19,120 | 15% / HKD 150,000 | Yes |
| VXF | 10% / HKD 100,000 / USD 12,745 | 10% / HKD 100,000 | Yes |
| VXUS | 20% / HKD 200,000 / USD 25,490 | 20% / HKD 200,000 | Yes |
| Cash | 10% / HKD 100,000 / USD 12,745 | 10% / HKD 100,000 | Yes |
| Total | USD 127,450 ≈ HKD 1,000,000 at 7.8461 | USD 127,450 at 7.8461 | Yes |

USD sleeve amounts sum to 127,450 (57,350+19,120+12,745+25,490+12,745). The intro omits per-sleeve USD amounts but states the matching total — omission only, not a conflict.

## (b) New §3 figures vs us_market_hkd_brief.md — PASS (all identical)
| Figure | proposal §3 | brief | Match |
|---|---|---|---|
| S&P 500 close 17 Nov 2026 | 7,340.53 | 7,340.53 | Yes |
| Below record | 6.12% below 7,818.93 (6 Oct 2026) | 6.12% below 7,818.93 (6 Oct 2026) | Yes |
| VOO 1-yr total return | +11.26% | +11.26% | Yes |
| QQQ 1-yr total return | +9.34% | +9.34% | Yes |
| VXUS 1-yr total return | +11.06% | +11.06% | Yes |
| Current drawdown QQQ | −13.52% | −13.52% | Yes |
| Current drawdown VXUS | −9.22% | −9.22% | Yes |
| Current drawdown VOO | −6.01% | −6.01% | Yes |
| Worst drawdown QQQ | −35.12% (2022) | −35.12% (2022) | Yes |
| Worst drawdown VOO | −33.99% (Mar 2020) | −33.99% (Mar 2020) | Yes |
| Worst drawdown VXUS | −35.97% (Mar 2020) | −35.97% (Mar 2020) | Yes |

Caveat carried correctly: proposal §3 labels the S&P 500 level "snippet-verified only", matching the brief's note that the pages returned 403/429. §6 Data caveats still lists the unverified items (S&P 500 YTD, NDX/RUT levels, forward P/E, VXF 1-yr, tariffs) — consistent with the brief's status table.

## (c) Intro vs proposal — no conflict
- Drawdown: intro "about 40% … paper loss of about HKD 400,000 … roughly HKD 600,000" = proposal §4.1 "40% market fall ≈ HKD 400,000 paper loss (portfolio ≈ HKD 600,000)". Match.
- Rates: intro 10-yr 5.10%, T-bills 4.33% = proposal §3/§4.2. Match.
- FX: intro 7.8461, band 7.75–7.85, ~0.05% room, ~1.2% to 7.75 = proposal §4.3. Match.
- Tranches 40/30/30 over ~3 months; bands ±5pp (45/15/20) and ±3pp (10% sleeves); cash-first rebalancing; no leverage/single stocks/daily trading = proposal §5. Match.
- AI concentration rationale (65% US large-cap double-up) = proposal §2. Match.

## Notes (no action required for consistency)
1. Intro says the cash buffer pays "~4% a year"; proposal/brief say 4.33% (3-month T-bill). Rounded, not contradictory.
2. Intro's closing note says "past 1-year fund returns … not available and is not quoted here" — true of the intro, but the proposal §3 now quotes them (verified). No conflict; the intro simply does not use them.
3. Proposal §4.4 costs/taxes (30% withholding ≈ 0.4%/yr drag; UCITS option) is not in the intro. Omission only; the underlying 30%/15% rates and ~1.3% yield remain [UNCERTAIN] in risk_review.md and should be confirmed with a tax adviser before external use.
