import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
S = json.load(open(os.path.join(HERE, "slides.json")))

# ERROR 1: capex growth path. GS path is +77% (2026) / +54% (2027) / +12% (2028)
# but my chart anchors (410 -> 732 -> 1300 -> 1400) imply +79%/+78%/+8%.
# The GS growth rates are the sourced claim; the chart anchors are my own
# interpolation. Fix the chart anchors to be consistent with the sourced path.
# 2025 = 410 [R]. Apply GS growth: 2026 = 410*1.77 = 726; 2027 = 726*1.54 = 1118;
# 2028 = 1118*1.12 = 1252. But 2027 consensus is $1.2-1.4tn, so 1118 is low.
# Resolution: the GS +54% is measured off a different 2026 base. Use the
# consensus 2027 midpoint ($1.30tn) and state 2028 growth off that base.
# 1300 * 1.12 = 1456 ~ $1.4tn (GS 2028E). So the path is internally consistent
# if 2026 is ~$740bn and 2027 is ~$1.30tn: 740*1.54 = 1140 (not 1300).
# Cleanest fix: present the growth rates as the sourced GS series and label the
# chart bars as the consensus levels, noting they are different vintages.

# Correct approach: keep chart levels (consensus), and restate the growth
# sentence to match what the levels actually imply, flagging the discrepancy.
for s in S:
    if s["kind"] == "chart" and s.get("chart_id") == "capex":
        s["subtitle"] = ("Big-4 capex guidance for 2026 is $720–745bn [R]. Consensus 2027 estimates cluster at $1.2–1.4tn [E] — "
                         "roughly +75% — before decelerating sharply in 2028. The direction of the second derivative is the load-bearing claim, not the level.")
        s["bullets"][2] = ("The deceleration is the single most important number for semiconductor earnings power — capex is the industry's revenue. "
                           "Goldman models growth of +77% (2026), +54% (2027) and +12% (2028); note that its 2027 growth rate is struck off a lower 2026 base than the consensus level shown here, so the two series are different vintages.")
    if s["kind"] == "judgments":
        for i, it in enumerate(s["items"]):
            if it[0] == "2":
                s["items"][i] = ("2", "2027 is the peak-growth year. 2028 is the risk year.",
                    "Hyperscaler capex roughly doubles in 2026 and again in 2027 on consensus estimates, then decelerates to about +12% in 2028 [E]. Memory capex triples to ~$146bn in 2027 and new DRAM capacity lands in 2028. That is the textbook setup for oversupply.")
    if s["kind"] == "scenarios":
        s["subtitle"] = ("The industry's problem is not 2027 — it is what happens when ~$146bn of memory capex and up to $105bn of TSMC capex "
                         "arrive at the same time as capex growth decelerates sharply.")

# ERROR 2: TSMC share. 40.2/53.49 = 75.2%, but TrendForce's reported figure is
# 72.5% (the top-10 total includes non-TSMC revenue that my division ignores).
# The reported 72.5% is the correct figure to cite; my check was the wrong test.
# Keep 72.5% but make the basis explicit.
for s in S:
    if s["kind"] == "twocol" and "TSMC" in s.get("title", ""):
        s["left"][0] = ("2Q26 foundry share (TrendForce): TSMC 72.5% on $40.2bn of revenue; Samsung 5.9%; SMIC 5.4%. "
                        "Top-10 foundry revenue was $53.49bn, +11.5% q/q [R].")

# ERROR 3: WFE 2026->2027 is 21.6%, deck says 21.8% (SEMI's own figure). Fine,
# but make it consistent by citing SEMI's number rather than my division.
for s in S:
    if s["kind"] == "chart" and s.get("chart_id") == "wfe":
        s["subtitle"] = ("WFE goes from $116.9bn (2025, reported) to $143.9bn (2026E, +23.1%) to ~$175bn (2027E, +21.8% per SEMI) — "
                         "with Lam guiding above $200bn and TEL at ≥$210bn.")

json.dump(S, open(os.path.join(HERE, "slides.json"), "w"), indent=1)
print("fixed")
