import re

text = open("channels_ai_on_campus.md", encoding="utf-8").read()

post = text.split("## Channel 1")[1].split("## Channel 2")[0]
body = "Since Fall 2023-24" + post.split("Since Fall 2023-24", 1)[1].split("**What to do:**")[0]
body = re.sub(r"\*\*Key points\*\*", "", body)
print("POST body words:", len(body.split()))

script = text.split("## Channel 2")[1].split("**[Opening hook", 1)[1].split("*(Spoken word count")[0]
script = re.sub(r"\*\*\[[^\]]*\]\*\*", "", script)
script = re.sub(r"\*\(.*?\)\*", "", script, flags=re.S)
print("SCRIPT spoken words:", len(script.split()))
