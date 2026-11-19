import re
src = open("inbox/roombook.html", encoding="utf-8").read()
i = src.find("function demo()")
print(src[i-200:i+2600])
