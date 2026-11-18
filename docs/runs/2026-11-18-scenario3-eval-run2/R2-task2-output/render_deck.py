import json, os, html

HERE = os.path.dirname(os.path.abspath(__file__))
SLIDES = json.load(open(os.path.join(HERE, "slides.json")))

def e(s):
    return html.escape(str(s))

CSS = """
:root{
  --bg:#0b0f16; --panel:#131a26; --panel2:#1a2333; --line:#26313f;
  --ink:#e8edf5; --dim:#93a1b5; --accent:#4da3ff; --accent2:#7c5cff;
  --up:#2ecc8f; --down:#ff5c72; --flat:#f0b429;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{
  background:var(--bg); color:var(--ink);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Helvetica Neue",Arial,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
  overflow:hidden;
}
#stage{position:fixed;inset:0;display:flex;align-items:center;justify-content:center}
.slide{
  display:none; width:1280px; height:720px; padding:44px 56px 40px;
  background:linear-gradient(160deg,#0e141d 0%,#0b0f16 60%,#0d1219 100%);
  position:relative; flex-direction:column;
}
.slide.active{display:flex}
.slide::after{
  content:""; position:absolute; left:0; top:0; width:100%; height:3px;
  background:linear-gradient(90deg,var(--accent),var(--accent2) 55%,transparent);
}
.kicker{
  font-size:11.5px; letter-spacing:.16em; text-transform:uppercase;
  color:var(--accent); font-weight:700; margin-bottom:10px;
}
h1{font-size:34px; line-height:1.18; font-weight:700; letter-spacing:-.01em; margin-bottom:8px}
h2{font-size:27px; line-height:1.22; font-weight:700; letter-spacing:-.01em; margin-bottom:10px}
.sub{font-size:14.5px; color:var(--dim); line-height:1.5; margin-bottom:18px; max-width:1080px}
.foot{
  position:absolute; left:56px; right:56px; bottom:16px;
  font-size:10.5px; color:#5f6d80; line-height:1.4; border-top:1px solid var(--line); padding-top:8px;
}
.pagenum{position:absolute; right:56px; bottom:16px; font-size:11px; color:#4a5666; font-variant-numeric:tabular-nums}
.body{flex:1; min-height:0; display:flex; flex-direction:column; gap:14px}

/* title slide */
.title-slide{justify-content:center}
.title-slide h1{font-size:52px; line-height:1.1; margin-bottom:18px; max-width:1000px}
.title-slide .sub{font-size:19px; max-width:900px; margin-bottom:34px}
.title-meta{display:flex; flex-direction:column; gap:7px; font-size:13px; color:var(--dim)}
.title-meta span::before{content:"— "; color:var(--accent)}

/* judgments */
.jgrid{display:flex; flex-direction:column; gap:11px}
.jrow{display:flex; gap:16px; background:var(--panel); border:1px solid var(--line);
  border-left:3px solid var(--accent); border-radius:6px; padding:13px 18px}
.jnum{font-size:22px; font-weight:800; color:var(--accent); min-width:26px; line-height:1.1; opacity:.85}
.jtitle{font-size:15.5px; font-weight:700; margin-bottom:4px}
.jtext{font-size:12.8px; color:var(--dim); line-height:1.5}

/* scoreboard / generic table */
table{width:100%; border-collapse:collapse; font-size:13px}
th{text-align:left; font-size:10.5px; letter-spacing:.1em; text-transform:uppercase;
  color:#6d7c90; font-weight:700; padding:0 12px 8px; border-bottom:1px solid var(--line)}
td{padding:11px 12px; border-bottom:1px solid #1c2532; vertical-align:top; line-height:1.45}
tr:last-child td{border-bottom:none}
td.seg{font-weight:700; font-size:13.5px; width:190px}
td.stat{width:120px}
.pill{display:inline-block; font-size:10.5px; font-weight:700; padding:3px 9px; border-radius:20px; letter-spacing:.03em}
.pill.up{background:rgba(46,204,143,.14); color:var(--up)}
.pill.down{background:rgba(255,92,114,.14); color:var(--down)}
.pill.flat{background:rgba(240,180,41,.14); color:var(--flat)}

/* two column */
.cols{display:grid; grid-template-columns:1fr 1fr; gap:22px; flex:1; min-height:0}
.col{background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:18px 20px; display:flex; flex-direction:column}
.col h3{font-size:12px; letter-spacing:.12em; text-transform:uppercase; color:var(--accent); margin-bottom:12px; font-weight:700}
.col ul{list-style:none; display:flex; flex-direction:column; gap:10px}
.col li{font-size:12.9px; line-height:1.5; color:#c3cddb; padding-left:14px; position:relative}
.col li::before{content:""; position:absolute; left:0; top:7px; width:5px; height:5px; border-radius:50%; background:var(--accent); opacity:.7}
.verdict{margin-top:14px; background:linear-gradient(90deg,rgba(77,163,255,.12),rgba(124,92,255,.06));
  border:1px solid rgba(77,163,255,.3); border-radius:6px; padding:12px 16px; font-size:13px; line-height:1.5; color:#dbe6f5}

/* chart slide */
.chartwrap{background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px 20px 10px; flex:1; min-height:0; display:flex; flex-direction:column}
.chart-title{font-size:11px; letter-spacing:.1em; text-transform:uppercase; color:#6d7c90; font-weight:700; margin-bottom:10px}
.bullets{display:flex; flex-direction:column; gap:8px}
.bullets li{font-size:12.6px; line-height:1.5; color:#c3cddb; padding-left:15px; position:relative; list-style:none}
.bullets li::before{content:""; position:absolute; left:0; top:7px; width:5px; height:5px; border-radius:50%; background:var(--accent2); opacity:.8}

/* bar chart */
.bars{display:flex; align-items:flex-end; gap:26px; height:100%; padding:8px 10px 0}
.barcol{flex:1; display:flex; flex-direction:column; align-items:center; justify-content:flex-end; height:100%}
.barval{font-size:13px; font-weight:700; margin-bottom:6px; font-variant-numeric:tabular-nums}
.bar{width:100%; max-width:110px; border-radius:4px 4px 0 0; background:linear-gradient(180deg,var(--accent),#2b6fb8); min-height:4px}
.bar.est{background:linear-gradient(180deg,#7c5cff,#4a35a8)}
.barlbl{font-size:11.5px; color:var(--dim); margin-top:8px; text-align:center; line-height:1.3}
.barnote{font-size:10px; color:#5f6d80; margin-top:2px}

/* profit pool */
td.pos{width:150px}
td.pos .pill{font-size:10px}

/* scenarios */
.scen{display:grid; grid-template-columns:1fr 1fr 1fr; gap:16px; flex:1; min-height:0}
.scard{background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px 18px; display:flex; flex-direction:column}
.scard .sname{font-size:16px; font-weight:700; margin-bottom:2px}
.scard .sprob{font-size:30px; font-weight:800; letter-spacing:-.02em; margin-bottom:12px}
.scard.up .sprob{color:var(--up)} .scard.flat .sprob{color:var(--flat)} .scard.down .sprob{color:var(--down)}
.scard ul{list-style:none; display:flex; flex-direction:column; gap:9px}
.scard li{font-size:12.2px; line-height:1.48; color:#c3cddb; padding-left:13px; position:relative}
.scard li::before{content:""; position:absolute; left:0; top:6px; width:4px; height:4px; border-radius:50%; background:currentColor; opacity:.5}
.scard li:last-child{color:#8fa0b6; font-style:italic}

/* implications */
.imp{display:grid; grid-template-columns:1fr 1fr; gap:12px; flex:1; min-height:0}
.impcard{background:var(--panel); border:1px solid var(--line); border-radius:7px; padding:13px 16px}
.impcard h4{font-size:13.5px; font-weight:700; margin-bottom:6px; color:#dbe6f5}
.impcard p{font-size:12.2px; line-height:1.48; color:var(--dim)}

/* portfolio */
.pf{display:grid; grid-template-columns:1.35fr 1fr; gap:20px; flex:1; min-height:0}
.pfbars{display:flex; flex-direction:column; gap:9px; justify-content:center}
.pfrow{display:grid; grid-template-columns:150px 1fr 44px; gap:10px; align-items:center}
.pfname{font-size:12.3px; font-weight:600; text-align:right; color:#c3cddb}
.pftrack{background:#1a2333; border-radius:3px; height:20px; overflow:hidden}
.pffill{height:100%; border-radius:3px; background:linear-gradient(90deg,#2b6fb8,var(--accent))}
.pfpct{font-size:12.5px; font-weight:700; font-variant-numeric:tabular-nums; color:var(--accent)}
.pfnote{font-size:10.5px; color:#5f6d80; margin-top:2px; grid-column:2/4}
.riskbox{background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px 18px; display:flex; flex-direction:column; gap:12px; justify-content:center}
.rb h4{font-size:10.5px; letter-spacing:.1em; text-transform:uppercase; color:var(--accent); margin-bottom:4px; font-weight:700}
.rb p{font-size:12.2px; line-height:1.45; color:#c3cddb}

/* conclusion */
.concl{display:flex; flex-direction:column; gap:13px; flex:1; justify-content:center}
.concl li{list-style:none; font-size:14.5px; line-height:1.55; color:#c9d4e2; padding-left:22px; position:relative}
.concl li::before{content:"›"; position:absolute; left:0; color:var(--accent); font-weight:800; font-size:18px; top:-2px}
.closing{margin-top:16px; padding:16px 20px; border-left:3px solid var(--accent2);
  background:linear-gradient(90deg,rgba(124,92,255,.1),transparent); font-size:15px; line-height:1.55; color:#e8edf5; font-weight:600}

/* appendix */
.apx{display:grid; grid-template-columns:1fr 1fr 1fr; gap:16px; flex:1; min-height:0}
.apxcol{background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:15px 17px}
.apxcol h4{font-size:11px; letter-spacing:.1em; text-transform:uppercase; color:var(--accent); margin-bottom:10px; font-weight:700}
.apxcol li{list-style:none; font-size:11.4px; line-height:1.5; color:var(--dim); margin-bottom:9px; padding-left:11px; position:relative}
.apxcol li::before{content:""; position:absolute; left:0; top:6px; width:4px; height:4px; border-radius:50%; background:#3d4b5e}

/* nav */
#nav{position:fixed; bottom:14px; left:50%; transform:translateX(-50%); display:flex; gap:8px;
  align-items:center; background:rgba(19,26,38,.92); border:1px solid var(--line); border-radius:24px;
  padding:7px 14px; font-size:12px; color:var(--dim); z-index:50; backdrop-filter:blur(8px)}
#nav button{background:none; border:none; color:var(--ink); cursor:pointer; font-size:15px; padding:2px 8px; border-radius:4px}
#nav button:hover{background:var(--panel2)}
#nav .cnt{font-variant-numeric:tabular-nums; min-width:52px; text-align:center}
#progress{position:fixed; top:0; left:0; height:2px; background:var(--accent); z-index:60; transition:width .2s}
#hint{position:fixed; top:14px; right:18px; font-size:11px; color:#4a5666; z-index:50}
@media print{
  body{overflow:visible; background:#fff}
  #stage{position:static; display:block}
  .slide{display:flex !important; page-break-after:always; margin:0 auto}
  #nav,#progress,#hint{display:none}
}
"""

def render_chart(cid):
    if cid == "capex":
        data = [("2024", "~$230bn", 230, False), ("2025", "~$410bn", 410, False),
                ("2026", "$720–745bn", 732, False), ("2027E", "$1.2–1.4tn", 1300, True),
                ("2028E", "$1.4tn", 1400, True)]
        title = "Big-4 hyperscaler capex, USD bn — reported vs estimated"
        mx = 1400
    elif cid == "memory":
        data = [("2024", "~$165bn", 165, False), ("2025", "~$420bn", 420, False),
                ("2026", "$889bn", 889, False), ("2027E", ">$1.28tn", 1280, True)]
        title = "Total memory market, USD bn — the steepest upcycle on record"
        mx = 1280
    else:
        data = [("2024", "~$110bn", 110, False), ("2025", "$116.9bn", 117, False),
                ("2026E", "$143.9bn", 144, True), ("2027E", "~$175bn", 175, True),
                ("2028E", "~$200bn", 200, True)]
        title = "Wafer fab equipment spending, USD bn (SEMI base case)"
        mx = 200
    out = [f'<div class="chart-title">{e(title)}</div><div class="bars">']
    for lbl, val, num, est in data:
        h = max(4, int(num / mx * 100))
        cls = "bar est" if est else "bar"
        out.append(f'<div class="barcol"><div class="barval">{e(val)}</div>'
                   f'<div class="{cls}" style="height:{h}%"></div>'
                   f'<div class="barlbl">{e(lbl)}</div>'
                   f'<div class="barnote">{"estimate" if est else "reported"}</div></div>')
    out.append("</div>")
    return "".join(out)

def render(s, idx, total):
    k = s["kind"]
    pn = f'<div class="pagenum">{idx+1} / {total}</div>'
    foot = f'<div class="foot">{e(s["footnote"])}</div>' if s.get("footnote") else ""

    if k == "title":
        meta = "".join(f"<span>{e(m)}</span>" for m in s["meta"])
        return (f'<section class="slide title-slide active"><div class="kicker">{e(s["kicker"])}</div>'
                f'<h1>{e(s["title"])}</h1><div class="sub">{e(s["subtitle"])}</div>'
                f'<div class="title-meta">{meta}</div>{pn}</section>')

    head = f'<div class="kicker">{e(s["kicker"])}</div><h2>{e(s["title"])}</h2>'
    sub = f'<div class="sub">{e(s["subtitle"])}</div>' if s.get("subtitle") else ""

    if k == "judgments":
        rows = "".join(f'<div class="jrow"><div class="jnum">{e(n)}</div><div>'
                       f'<div class="jtitle">{e(t)}</div><div class="jtext">{e(d)}</div></div></div>'
                       for n, t, d in s["items"])
        body = f'<div class="body"><div class="jgrid">{rows}</div></div>'
    elif k == "scoreboard":
        rows = "".join(f'<tr><td class="seg">{e(a)}</td><td>{e(b)}</td>'
                       f'<td class="stat"><span class="pill {c}">{e(d)}</span></td></tr>'
                       for a, b, d, c in s["rows"])
        body = (f'<div class="body"><table><thead><tr><th>Segment</th><th>Latest reported data point</th>'
                f'<th>Cycle position</th></tr></thead><tbody>{rows}</tbody></table></div>')
    elif k == "chart":
        bl = "".join(f"<li>{e(b)}</li>" for b in s["bullets"])
        body = (f'<div class="body"><div class="chartwrap">{render_chart(s["chart_id"])}</div>'
                f'<ul class="bullets">{bl}</ul></div>')
    elif k == "twocol":
        L = "".join(f"<li>{e(x)}</li>" for x in s["left"])
        R = "".join(f"<li>{e(x)}</li>" for x in s["right"])
        v = f'<div class="verdict">{e(s["verdict"])}</div>' if s.get("verdict") else ""
        body = (f'<div class="body"><div class="cols">'
                f'<div class="col"><h3>{e(s["left_title"])}</h3><ul>{L}</ul></div>'
                f'<div class="col"><h3>{e(s["right_title"])}</h3><ul>{R}</ul></div></div>{v}</div>')
    elif k == "profitpool":
        rows = "".join(f'<tr><td class="seg">{e(a)}</td><td>{e(b)}</td><td>{e(c)}</td>'
                       f'<td class="pos"><span class="pill {d2}">{e(d)}</span></td></tr>'
                       for a, b, c, d, d2 in s["rows"])
        body = (f'<div class="body"><table><thead><tr><th>Layer</th><th>Profit capture</th>'
                f'<th>Evidence</th><th>Positioning</th></tr></thead><tbody>{rows}</tbody></table></div>')
    elif k == "scenarios":
        cards = ""
        for name, prob, cls, pts in s["cols"]:
            li = "".join(f"<li>{e(p)}</li>" for p in pts)
            cards += (f'<div class="scard {cls}"><div class="sname">{e(name)}</div>'
                      f'<div class="sprob">{e(prob)}</div><ul>{li}</ul></div>')
        body = f'<div class="body"><div class="scen">{cards}</div></div>'
    elif k == "implications":
        cards = "".join(f'<div class="impcard"><h4>{e(t)}</h4><p>{e(d)}</p></div>'
                        for t, d in s["items"])
        body = f'<div class="body"><div class="imp">{cards}</div></div>'
    elif k == "portfolio":
        bars = ""
        for name, pct, note in s["bars"]:
            bars += (f'<div class="pfrow"><div class="pfname">{e(name)}</div>'
                     f'<div class="pftrack"><div class="pffill" style="width:{pct*4.2}%"></div></div>'
                     f'<div class="pfpct">{pct}%</div>'
                     f'<div class="pfnote">{e(note)}</div></div>')
        rb = "".join(f'<div class="rb"><h4>{e(t)}</h4><p>{e(d)}</p></div>' for t, d in s["riskbox"])
        body = (f'<div class="body"><div class="pf"><div class="pfbars">{bars}</div>'
                f'<div class="riskbox">{rb}</div></div></div>')
    elif k == "risks":
        rows = "".join(f'<tr><td class="seg">{e(a)}</td><td class="stat">{e(b)}</td>'
                       f'<td class="stat">{e(c)}</td><td>{e(d)}</td></tr>'
                       for a, b, c, d in s["rows"])
        body = (f'<div class="body"><table><thead><tr><th>Risk</th><th>Likelihood</th>'
                f'<th>Impact</th><th>Why it matters</th></tr></thead><tbody>{rows}</tbody></table></div>')
    elif k == "dashboard":
        rows = "".join(f'<tr><td class="stat" style="width:34px;color:#6d7c90">{e(a)}</td>'
                       f'<td class="seg" style="width:300px">{e(b)}</td><td>{e(c)}</td>'
                       f'<td class="stat" style="width:150px;color:#8fa0b6">{e(d)}</td></tr>'
                       for a, b, c, d in s["rows"])
        body = (f'<div class="body"><table><thead><tr><th>#</th><th>Indicator</th>'
                f'<th>Review trigger</th><th>Frequency</th></tr></thead><tbody>{rows}</tbody></table></div>')
    elif k == "conclusion":
        li = "".join(f"<li>{e(p)}</li>" for p in s["points"])
        body = (f'<div class="body"><ul class="concl">{li}</ul>'
                f'<div class="closing">{e(s["closing"])}</div></div>')
    elif k == "appendix":
        cols = ""
        for title, items in s["groups"]:
            li = "".join(f"<li>{e(i)}</li>" for i in items)
            cols += f'<div class="apxcol"><h4>{e(title)}</h4><ul>{li}</ul></div>'
        body = f'<div class="body"><div class="apx">{cols}</div></div>'
    else:
        body = ""

    return f'<section class="slide">{head}{sub}{body}{foot}{pn}</section>'

total = len(SLIDES)
slides_html = "".join(render(s, i, total) for i, s in enumerate(SLIDES))

JS = """
let cur=0; const S=[...document.querySelectorAll('.slide')];
function show(i){cur=Math.max(0,Math.min(S.length-1,i));
  S.forEach((s,j)=>s.classList.toggle('active',j===cur));
  document.getElementById('cnt').textContent=(cur+1)+' / '+S.length;
  document.getElementById('progress').style.width=((cur+1)/S.length*100)+'%';}
document.addEventListener('keydown',ev=>{
  if(['ArrowRight','ArrowDown','PageDown',' '].includes(ev.key)){ev.preventDefault();show(cur+1);}
  if(['ArrowLeft','ArrowUp','PageUp'].includes(ev.key)){ev.preventDefault();show(cur-1);}
  if(ev.key==='Home')show(0); if(ev.key==='End')show(S.length-1);
  if(ev.key==='f'){document.fullscreenElement?document.exitFullscreen():document.documentElement.requestFullscreen();}
});
document.getElementById('prev').onclick=()=>show(cur-1);
document.getElementById('next').onclick=()=>show(cur+1);
function fit(){const s=Math.min(window.innerWidth/1280,window.innerHeight/720);
  document.getElementById('stage').style.transform='scale('+s+')';}
window.addEventListener('resize',fit); fit(); show(0);
"""

doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Semiconductor Industry Outlook — End-2026 Perspective</title>
<style>{CSS}</style></head>
<body>
<div id="progress"></div>
<div id="hint">← → to navigate · F for fullscreen</div>
<div id="stage">{slides_html}</div>
<div id="nav"><button id="prev">‹</button><span class="cnt" id="cnt">1 / {total}</span><button id="next">›</button></div>
<script>{JS}</script>
</body></html>"""

out = os.path.join(HERE, "semiconductor_outlook_2026.html")
open(out, "w").write(doc)
print("wrote", out, len(doc), "chars,", total, "slides")
