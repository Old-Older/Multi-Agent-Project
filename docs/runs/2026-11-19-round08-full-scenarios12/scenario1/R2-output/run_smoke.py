import subprocess
r = subprocess.run(["node", "smoke.js"], capture_output=True, text=True)
print(r.returncode)
print(r.stdout)
print(r.stderr[-3000:])
