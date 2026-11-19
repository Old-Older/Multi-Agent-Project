import re
src = open("inbox/roombook.html", encoding="utf-8").read()
i = src.find("function dashData")
j = src.find("function renderDash", i)
print(src[i:j])
