import re
src = open("inbox/roombook.html", encoding="utf-8").read()
i = src.find("function renderDash")
j = src.find("function renderRooms", i)
print(src[i+3000:j])
