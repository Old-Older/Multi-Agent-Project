# Semiconductor Industry Outlook — End-2026 Perspective
## Speaker notes / read-me for the fund team

**Deliverable:** `semis_outlook_2026/semiconductor_outlook_2026.html` — 18 slides, open in any browser.
Navigate with ← → (or Space / PageUp / PageDown), `F` for fullscreen, `Home`/`End` to jump. Prints to PDF via the browser's print dialog (each slide is a page).

### The argument in one paragraph
The semiconductor industry enters 2027 in the best shape it has ever been in — memory contracted out to 2029, TSMC at a 66% gross margin, WFE at a record. But every one of those facts is a statement about *scarcity*, and scarcity is precisely what capital expenditure is designed to destroy. Roughly $146bn of memory capex and up to $105bn of TSMC capex are already committed, and they arrive in 2028 — the same year hyperscaler capex growth decelerates to about +12%. So we own the bottlenecks (HBM, advanced packaging, leading-edge foundry, semicap) through 2027, underweight the commoditised middle, and size the sleeve to the stressed scenario rather than the calm one.

### Slide map
| # | Slide | Message |
|---|---|---|
| 1 | Title | — |
| 2 | Six judgments | The whole thesis, including the risk-budget point |
| 3 | Scoreboard | Every segment at a record — that is the problem |
| 4 | Hyperscaler capex | Second derivative has turned |
| 5 | AI compute | NVIDIA owns the market, not the margin |
| 6 | Memory | Tightest market, most dangerous to own late |
| 7 | Foundry & packaging | TSMC's toll booth; packaging is the moat |
| 8 | Semicap | Best year in 2027, earnings peak before orders |
| 9 | Analog/auto/industrial | Bottoming, weak recovery, ballast |
| 10 | China | Shrinking revenue pool, rising competitor |
| 11 | Profit pool | Value has moved to the bottleneck owners |
| 12 | Scenarios | 45% soft landing / 35% air pocket / 20% break |
| 13 | Implications | Six actions |
| 14 | Portfolio | Sizing to the stressed scenario |
| 15 | Risks | What would prove us wrong |
| 16 | Dashboard | Ten indicators with review triggers |
| 17 | Conclusion | — |
| 18 | Appendix | Sources, conventions, caveats |

### What changed after review
- **Risk review** found the original sizing put 60% of the sleeve in one factor (hyperscaler capex) and stated a 30–35% volatility budget that the sleeve breached at ~46% in a capex scare. Reweighted to foundry 22 / analog 26 / memory 12 / semicap 10 / accelerators 10 / packaging 5 / mature 3 / cash+hedge 12. Capex beta now 47% against a 50% cap. Risk budget restated to ~28% normal / ~38% stressed, 55% drawdown tolerance, −35% de-risking trigger.
- **Hedge** was 5% cash, which the risk review correctly called "insurance theatre". Now 7% cash (dry powder) + 5% put spread at 40% notional, with its coverage limit stated honestly on the slide.
- **Marketing review** found five slide titles were labels rather than assertions, and slide 2 did not preview the scenarios or the sizing. All titles rewritten as assertions; slide 2 extended to six judgments.
- **Arithmetic check** caught two errors I had introduced: the capex growth path (my chart anchors implied +79/+78/+8% against a sourced +77/+54/+12%) and the TSMC share basis. Both corrected and the discrepancy is now disclosed on the slide rather than hidden.

### Honest caveats (also on slide 18)
- 2027 hyperscaler capex is **sell-side estimate, not company guidance**. The level is uncertain; the direction of deceleration is the load-bearing claim.
- HBM market share is single-sourced (Counterpoint); levels differ across TrendForce and Omdia.
- The ~$146bn 2027 memory capex figure is a press compilation without primary-source verification; the 3.4x multiple is our calculation.
- SiC pricing, EV unit growth and mature-node utilisation are directional judgments, not fully sourced.
- **Volatility figures are modelled from assumed sub-sector vols and correlations (ρ≈0.85), not realised vols from the fund's risk system.** Replace before the IC meeting.
- Scenario probabilities are subjective and stated so they can be argued with.
- NVIDIA's reported leadership transition (interim CEO) was flagged by research but **not independently verified** — check before presenting.
- Taiwan look-through of the 22% foundry + 5% packaging sleeves against the 35% single-country cap has not been computed.

### Files
- `semiconductor_outlook_2026.html` — the deck (deliverable)
- `slides.json` — slide content, editable
- `build_deck.py` — content source
- `render_deck.py` — HTML renderer
- `deck_notes.md` — working notes
- `verify.py`, `check.py`, `dump.py` — QA scripts
