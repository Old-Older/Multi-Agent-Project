import re, os, json
HERE = os.path.dirname(os.path.abspath(__file__))
h = open(os.path.join(HERE, "semiconductor_outlook_2026.html")).read()

# structural checks
print("slides:", h.count('<section class="slide'))
print("active:", h.count('class="slide title-slide active"'))
print("nav:", 'id="next"' in h, 'id="prev"' in h)
print("progress:", 'id="progress"' in h)
print("unclosed section:", h.count("<section") - h.count("</section>"))
print("unclosed div:", h.count("<div") - h.count("</div>"))
print("unclosed ul:", h.count("<ul") - h.count("</ul>"))
print("unclosed table:", h.count("<table") - h.count("</table>"))
print("unclosed li:", h.count("<li") - h.count("</li>"))
print("unclosed tr:", h.count("<tr") - h.count("</tr>"))
print("unclosed td:", h.count("<td") - h.count("</td>"))
print("unclosed th:", h.count("<th") - h.count("</th>"))
print("unclosed p:", h.count("<p>") - h.count("</p>"))
print("unclosed h4:", h.count("<h4>") - h.count("</h4>"))
print("unclosed span:", h.count("<span") - h.count("</span>"))

# check for unescaped braces / template leftovers
for bad in ["{e(", "None", "nan", "{{", "}}"]:
    if bad in h:
        print("WARNING leftover:", bad, h.count(bad))

# per-slide text length sanity (overflow risk)
S = json.load(open(os.path.join(HERE, "slides.json")))
for i, s in enumerate(S):
    n = len(json.dumps(s))
    flag = "  <-- LONG" if n > 2600 else ""
    print(f"{i+1:2d} {s['kind']:14s} {n:5d}{flag}  {s.get('title','')[:70]}")
