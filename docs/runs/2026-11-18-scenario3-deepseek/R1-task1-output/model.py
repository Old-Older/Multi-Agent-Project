import json

HKD = 1_000_000
USDHKD = 7.80
USD = HKD / USDHKD

# Core-satellite allocation (weights of total portfolio)
alloc = [
    # name, ticker, weight, role, exp_return, vol
    ("US total market core", "VTI", 0.30, "Core", 0.075, 0.165),
    ("S&P 500 core", "VOO", 0.15, "Core", 0.075, 0.160),
    ("US growth / tech tilt", "QQQM", 0.10, "Core-satellite", 0.090, 0.215),
    ("International ex-US", "VXUS", 0.15, "Diversifier", 0.070, 0.170),
    ("US quality dividend", "SCHD", 0.08, "Defensive ballast", 0.070, 0.140),
    ("US small/mid cap value", "AVUV", 0.05, "Diversifier", 0.085, 0.210),
    ("Cash / T-bills (dry powder)", "SGOV", 0.07, "Liquidity", 0.038, 0.005),
    ("Individual stocks (satellite)", "8 names", 0.10, "Satellite", 0.095, 0.280),
]

total_w = sum(a[2] for a in alloc)
print("weights sum:", total_w)

# Portfolio expected return & vol (simple, ignoring correlations -> conservative vol estimate)
er = sum(a[2]*a[4] for a in alloc)
# assume average pairwise correlation 0.75 for equities
import itertools
var = 0.0
for i, a in enumerate(alloc):
    for j, b in enumerate(alloc):
        rho = 1.0 if i == j else (0.10 if (a[1] in ("SGOV",) or b[1] in ("SGOV",)) else 0.75)
        var += a[2]*b[2]*a[5]*b[5]*rho
vol = var ** 0.5
print(f"Expected return (nominal USD): {er:.2%}")
print(f"Expected volatility: {vol:.2%}")

# HKD amounts
print("\n--- HKD allocation ---")
for a in alloc:
    print(f"{a[0]:32s} {a[1]:8s} {a[2]:6.1%}  HKD {a[2]*HKD:>10,.0f}  USD {a[2]*USD:>10,.0f}")

# Satellite detail
sat = [
    ("NVIDIA", "NVDA", 0.020, "AI compute leader; de-rated on peak-capex fears"),
    ("Microsoft", "MSFT", 0.015, "Azure + Copilot; recurring revenue"),
    ("Alphabet", "GOOGL", 0.015, "Search + Cloud + Gemini; cheapest mega-cap"),
    ("Amazon", "AMZN", 0.012, "AWS re-acceleration + retail margin"),
    ("Broadcom", "AVGO", 0.010, "Custom AI silicon + software cash flow"),
    ("JPMorgan", "JPM", 0.010, "Rate-cycle beneficiary, quality financials"),
    ("UnitedHealth", "UNH", 0.009, "Healthcare diversifier, depressed valuation"),
    ("Costco", "COST", 0.009, "Defensive compounder, pricing power"),
]
print("\n--- Satellite (10% of portfolio) ---")
s = 0
for n, t, w, th in sat:
    s += w
    print(f"{n:12s} {t:6s} {w:6.2%}  HKD {w*HKD:>9,.0f}  USD {w*USD:>9,.0f}  {th}")
print("satellite sum:", f"{s:.2%}")

# Drawdown stress tests
print("\n--- Stress tests (HKD) ---")
scen = [
    ("2008 GFC style", -0.51),
    ("2022 rate-shock style", -0.25),
    ("2020 COVID crash (Feb-Mar)", -0.34),
    ("AI-capex bust (tech-led)", -0.30),
    ("Mild correction", -0.10),
]
for name, dd in scen:
    print(f"{name:28s} {dd:6.0%}  -> HKD {HKD*(1+dd):>12,.0f}  (loss HKD {HKD*dd:>12,.0f})")

# Long-run compounding
print("\n--- 10y / 20y compounding at expected return ---")
for yrs in (10, 20):
    for r in (0.05, 0.075, 0.09):
        print(f"{yrs}y @ {r:.1%}: HKD {HKD*(1+r)**yrs:,.0f}")

# Tax drag illustration
print("\n--- Dividend withholding drag ---")
yield_us = 0.013
print(f"US-listed ETF blended yield ~{yield_us:.1%}; 30% WHT -> drag {yield_us*0.30:.2%}/yr")
print(f"Irish-domiciled UCITS (15% treaty) -> drag {yield_us*0.15:.2%}/yr")
print(f"Annual saving on HKD 1m: HKD {HKD*yield_us*0.15:,.0f}")

# Estate tax exposure
print("\n--- US estate tax exposure ---")
us_situs = HKD * 0.93 / USDHKD
print(f"US-situs assets ~USD {us_situs:,.0f}; exemption USD 60,000")
print(f"Exposed above exemption: USD {max(0, us_situs-60000):,.0f}")
print(f"Max 40% tax: USD {max(0, us_situs-60000)*0.40:,.0f} (HKD {max(0, us_situs-60000)*0.40*USDHKD:,.0f})")

# Rebalancing bands
print("\n--- Rebalance bands ---")
for a in alloc:
    print(f"{a[1]:8s} target {a[2]:6.1%}  band {max(0,a[2]-0.03):.1%}-{a[2]+0.03:.1%}")
