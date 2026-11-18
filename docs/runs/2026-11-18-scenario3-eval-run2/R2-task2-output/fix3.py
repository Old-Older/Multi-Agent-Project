import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
S = json.load(open(os.path.join(HERE, "slides.json")))

for s in S:
    if s["kind"] == "portfolio":
        s["subtitle"] = ("Illustrative weights for a dedicated semiconductor sleeve. The first draft put 60% in one factor — hyperscaler capex. "
                         "This version brings that to 47% against a 50% cap, and sizes the hedge to the 35% air-pocket probability.")
    if s["kind"] == "risks":
        # merge the duplicate crowding rows
        rows = [r for r in s["rows"] if r[0] != "Liquidity and crowding"]
        for i, r in enumerate(rows):
            if r[0] == "Valuation / crowding":
                rows[i] = ("Valuation, crowding and liquidity", "Medium", "Medium",
                    "The sector is priced for the supercycle continuing. A de-rating needs no fundamental deterioration — only a change in the second derivative. "
                    "The bottleneck names are widely held, so in a de-risking event correlation goes to one and the exit is narrower than the entry.")
        s["rows"] = rows

json.dump(S, open(os.path.join(HERE, "slides.json"), "w"), indent=1)
print("ok")
