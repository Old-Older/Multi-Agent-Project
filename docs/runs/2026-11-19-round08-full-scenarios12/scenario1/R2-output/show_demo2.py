import re
src = open("inbox/roombook.html", encoding="utf-8").read()
i = src.find("var past=[")
j = src.find("return {rooms:", i)
print(src[j-1800:j+900])
