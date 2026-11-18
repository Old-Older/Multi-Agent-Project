import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
S = json.load(open(os.path.join(HERE, "slides.json")))

for s in S:
    if s["kind"] == "portfolio":
        # Fix the capex-beta label: 47% including foundry, 37% excluding.
        for i, (t, d) in enumerate(s["riskbox"]):
            if t == "Factor limit":
                s["riskbox"][i] = ("Factor limit",
                    "Hyperscaler-capex beta is 47% of the sleeve including foundry (37% excluding it), against a 50% cap — "
                    "only 3pp of headroom, not 10pp. Single name ≤8%; memory ≤15%; single country ex-US ≤35%.")
            if t == "Hedge, costed":
                s["riskbox"][i] = ("Hedge, costed — and its limit",
                    "5% rolling put spread (long 90% / short 70% strike, 40% notional) plus 7% cash. Carry 0.75–1.25% a year. "
                    "This covers the expected air-pocket loss but not a −40% basket: at that level the sleeve loses ~19% and the hedge covers ~12%.")
            if t == "Why the change":
                s["riskbox"][i] = ("Why the change",
                    "At 35% probability the air pocket costs 6–9% of the sleeve in expectation. A 5% cash buffer offsets only 5pp — "
                    "it was insurance theatre, not insurance. The 7% cash is dry powder, not a hedge; only the put spread is.")
        s["bars"][7] = ("Cash + put-spread hedge", 12, "7% cash (dry powder) + 5% put spread at 40% notional")

    if s["kind"] == "judgments":
        for i, it in enumerate(s["items"]):
            if it[0] == "6":
                s["items"][i] = ("6", "The risk budget, not the stock selection, is the binding constraint.",
                    "47% of the proposed sleeve is one factor — hyperscaler capex. Modelled sleeve volatility is ~28% in a normal regime but ~38% in a capex scare, "
                    "which breaches a 30–35% budget. The sizing on slide 14 is set to the stressed number, not the calm one.")

    if s["kind"] == "risks":
        # Add the missing risks the risk manager flagged
        have = {r[0] for r in s["rows"]}
        if "Memory price collapse" not in have:
            s["rows"].insert(2, ("Memory price collapse", "Medium", "High",
                "Distinct from capex digestion: a spot-led collapse in conventional DRAM would hit the 12% memory sleeve before HBM LTAs reprice. "
                "HBM3E spot at ~$2,100 versus $300–400 LTA shows how violent the dislocation can be in both directions."))
        if "Liquidity and crowding" not in have:
            s["rows"].append(("Liquidity and crowding", "Medium", "Medium",
                "The bottleneck names are widely held. In a de-risking event, correlation goes to one and the exit is narrower than the entry."))

json.dump(S, open(os.path.join(HERE, "slides.json"), "w"), indent=1)
print("ok")
