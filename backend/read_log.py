import sys
with open("populate.log", "r", encoding="utf-8", errors="replace") as f:
    text = f.read()

with open("out.txt", "w", encoding="utf-8") as f:
    f.write(text)
print("Done")
