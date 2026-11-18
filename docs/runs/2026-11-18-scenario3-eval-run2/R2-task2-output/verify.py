import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
S = json.load(open(os.path.join(HERE, "slides.json")))

print("=== ARITHMETIC CHECKS ===")
# 1. portfolio weights sum
p = [s for s in S if s["kind"] == "portfolio"][0]
tot = sum(b[1] for b in p["bars"])
print("portfolio weights sum:", tot, "OK" if tot == 100 else "*** ERROR ***")

# 2. capex-beta share
capex_beta = sum(b[1] for b in p["bars"] if b[0] in
    ("Memory / HBM", "Semicap", "AI accelerators (GPU/ASIC)", "Advanced packaging / OSAT"))
print("capex-beta share:", capex_beta, "% (claim: capped at 50%)",
      "OK" if capex_beta <= 50 else "*** ERROR ***")

# 3. hedge components
cash = [b[1] for b in p["bars"] if "Cash" in b[0]][0]
print("cash+hedge line:", cash, "= 7% cash + 5% put spread ->", 7 + 5 == cash)

# 4. memory capex multiple
print("memory capex 146/43 =", round(146/43, 2), "(claim 3.4x)")

# 5. capex growth path
c = [410, 732, 1300, 1400]
print("capex growth:", [f"{(c[i+1]/c[i]-1)*100:.0f}%" for i in range(3)],
      "(claim +77%/+54%/+12%)")

# 6. memory market growth
print("memory 2026->2027 growth:", f"{(1280/889-1)*100:.0f}%", "(claim +44%)")

# 7. TSMC share check
print("TSMC 40.2 / 53.49 =", f"{40.2/53.49*100:.1f}%", "(claim 72.5%)")

# 8. NVIDIA DC annualised
print("NVIDIA DC annualised:", 107.6*4, "bn (claim ~$430bn)")

# 9. scenario probabilities
sc = [s for s in S if s["kind"] == "scenarios"][0]
probs = [int(c[1].strip("%")) for c in sc["cols"]]
print("scenario probs:", probs, "sum:", sum(probs), "OK" if sum(probs) == 100 else "*** ERROR ***")

# 10. WFE growth
print("WFE 2025->2026:", f"{(143.9/116.9-1)*100:.1f}%", "(claim +23.1%)")
print("WFE 2026->2027:", f"{(175/143.9-1)*100:.1f}%", "(claim +21.8%)")
print("WFE 2027->2028:", f"{(200/175-1)*100:.1f}%", "(claim +14%)")

# 11. air pocket cost vs hedge
print("air pocket cost 9-12% of sleeve; 5% cash offsets 5pp -> residual 4-7pp")
print("12% cash+hedge vs 9-12% loss -> coverage", f"{12/10.5:.1f}x", "of midpoint")

print("\n=== CONSISTENCY: slide 15 vs slide 12 ===")
r = [s for s in S if s["kind"] == "risks"][0]
for row in r["rows"]:
    if "capex digestion" in row[0]:
        print("slide15 says:", row[3][:120])
print("slide12 air pocket prob: 35% -> consistent" if "35%" in str(r["rows"]) else "check")

print("\n=== TITLE CHECK: assertions not labels ===")
for i, s in enumerate(S):
    t = s.get("title", "")
    label = len(t.split()) <= 4 and not any(c in t for c in "—:,")
    print(f"{i+1:2d} {'LABEL?' if label else 'ok':7s} {t[:80]}")
