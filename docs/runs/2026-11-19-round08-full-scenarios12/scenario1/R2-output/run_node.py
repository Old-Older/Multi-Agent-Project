import subprocess, sys
r = subprocess.run(["node"] + sys.argv[1:], capture_output=True, text=True)
print("rc", r.returncode)
print(r.stdout[-4000:])
print(r.stderr[-4000:])
