import json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))
S = json.load(open(os.path.join(HERE, "slides.json")))

def find(kind):
    for s in S:
        if s["kind"] == kind:
            return s
    raise KeyError(kind)

# ---- Slide 2: add the missing 6th judgment + retitle ----
j = find("judgments")
j["title"] = "Six judgments — and the one number that decides the outcome"
j["items"].append(("6",
    "The risk budget, not the stock selection, is the binding constraint.",
    "60% of the proposed sleeve is one factor — hyperscaler capex. Modelled sleeve volatility is ~34% in a normal regime but ~46% in a capex scare, which breaches a 30–35% budget. The sizing on slide 14 is set to the stressed number, not the calm one."))

# ---- Slide 3: retitle as assertion ----
find("scoreboard")["title"] = "Every segment is at a record — which is the problem, not the reassurance"

# ---- Slide 4: retitle ----
find("chart")["title"] = "Capex is still rising, but the second derivative has already turned"

# ---- Slide 6: memory retitle ----
for s in S:
    if s["kind"] == "chart" and s.get("chart_id") == "memory":
        s["title"] = "Memory is the tightest market in the industry — and the most dangerous to own late"

# ---- Slide 8: semicap retitle ----
for s in S:
    if s["kind"] == "chart" and s.get("chart_id") == "wfe":
        s["title"] = "Semicap gets its best year in 2027 — and its earnings peak before the orders do"

# ---- Slide 11: profit pool retitle ----
find("profitpool")["title"] = "The profit pool has moved to whoever owns the bottleneck"

# ---- Slide 12: scenarios retitle ----
find("scenarios")["title"] = "Three scenarios for 2028 — and the air pocket is not a tail risk"

# ---- Slide 13: implications retitle ----
find("implications")["title"] = "Six things we would actually do about it"

# ---- Slide 15: fix the contradiction with slide 12 ----
r = find("risks")
r["title"] = "What would prove us wrong — and how we would know"
for i, row in enumerate(r["rows"]):
    if row[0] == "AI capex digestion in 2028":
        r["rows"][i] = ("AI capex digestion in 2028", "High", "High",
            "Capex growth decelerates to +12% in 2028 [E] just as new memory and foundry capacity lands. We assign this a 35% probability — the second most likely outcome, not the base case.")
    if row[0] == "Valuation / crowding":
        r["rows"][i] = ("Valuation / crowding", "Medium", "Medium",
            "The sector is priced for the supercycle continuing. A de-rating needs no fundamental deterioration — only a change in the second derivative. This is the risk that arrives first.")

# ---- Slide 14: rebuild portfolio to the risk-reviewed sizing ----
p = find("portfolio")
p["title"] = "Sizing the barbell to the stressed scenario, not the calm one"
p["subtitle"] = ("Illustrative weights for a dedicated semiconductor sleeve. The first draft put 60% in one factor — hyperscaler capex. "
                 "This version caps that exposure at 50% and sizes the hedge to the 35% air-pocket probability.")
p["bars"] = [
    ("Leading-edge foundry", 22, "Core — paid per wafer regardless of which accelerator wins"),
    ("Memory / HBM", 12, "Trimmed from 20% — highest 2027 earnings, highest 2028 risk"),
    ("Analog / auto / industrial", 26, "Raised from 12% — the ballast, and the cheapest part of the sector"),
    ("Semicap", 10, "Trimmed from 18% — earnings peak before WFE does"),
    ("AI accelerators (GPU/ASIC)", 10, "Trimmed from 14% — growth, not margin"),
    ("Advanced packaging / OSAT", 5, "Bottleneck, but few pure-play vehicles"),
    ("Mature-node / commodity", 3, "Structural underweight"),
    ("Cash + put-spread hedge", 12, "7% cash + 5% rolling put spread, sized to the air pocket"),
]
p["riskbox"] = [
    ("Risk budget — restated", "Normal-regime vol ~28%; stressed (capex scare) ~38%. Max drawdown tolerance 55%, with a hard de-risking trigger at −35%."),
    ("Factor limit", "Hyperscaler-capex beta capped at 50% of the sleeve (was 60%). Single name ≤8%; memory ≤15%; single country ex-US ≤35%."),
    ("Hedge, costed", "5% rolling put spread (long 90% / short 70% strike, 25% notional) plus 7% cash. Carry 0.75–1.25% a year. Escalate if air-pocket probability rises above 45%."),
    ("Why the change", "At 35% probability the air pocket costs 9–12% of the sleeve. A 5% cash buffer offsets only 5pp — it was insurance theatre, not insurance."),
]
p["footnote"] = ("Weights are illustrative and sum to 100. Volatility figures are modelled from assumed sub-sector vols and correlations (ρ≈0.85); "
                 "they must be replaced with realised vols from the fund's risk system before the IC meeting.")

# ---- Slide 16: dashboard retitle ----
find("dashboard")["title"] = "Ten indicators, each with a threshold that forces a review"

# ---- Slide 17: conclusion retitle ----
find("conclusion")["title"] = "The industry has never been in better shape — which is exactly why we size for 2028"

# ---- Slide 18: appendix retitle ----
find("appendix")["title"] = "Sources, data conventions and what we do not know"

json.dump(S, open(os.path.join(HERE, "slides.json"), "w"), indent=1)
print("updated", len(S), "slides")
