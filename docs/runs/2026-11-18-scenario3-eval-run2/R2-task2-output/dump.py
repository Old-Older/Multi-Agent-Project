import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
S = json.load(open(os.path.join(HERE, "slides.json")))

print("=== SLIDE 14 (portfolio) ===")
p = [s for s in S if s["kind"] == "portfolio"][0]
print("TITLE:", p["title"])
print("SUB:", p["subtitle"])
for b in p["bars"]:
    print(f"  {b[0]:32s} {b[1]:3d}%  {b[2]}")
print("  sum:", sum(b[1] for b in p["bars"]))
for t, d in p["riskbox"]:
    print(f"  [{t}] {d}")

print("\n=== SLIDE 15 (risks) ===")
r = [s for s in S if s["kind"] == "risks"][0]
for row in r["rows"]:
    print(f"  {row[0]:42s} L={row[1]:6s} I={row[2]:6s}")

print("\n=== SLIDE 2 judgment 6 ===")
j = [s for s in S if s["kind"] == "judgments"][0]
print(j["items"][5][1], "|", j["items"][5][2])

print("\n=== SLIDE 4 capex ===")
c = [s for s in S if s["kind"] == "chart" and s.get("chart_id") == "capex"][0]
print("SUB:", c["subtitle"])
print("B3:", c["bullets"][2])

print("\n=== SLIDE 7 TSMC ===")
t = [s for s in S if s["kind"] == "twocol" and "TSMC" in s.get("title", "")][0]
print("L1:", t["left"][0])

print("\n=== SLIDE 8 WFE ===")
w = [s for s in S if s["kind"] == "chart" and s.get("chart_id") == "wfe"][0]
print("SUB:", w["subtitle"])

print("\n=== SLIDE 12 scenarios ===")
sc = [s for s in S if s["kind"] == "scenarios"][0]
print("SUB:", sc["subtitle"])
print("probs:", [x[1] for x in sc["cols"]])
