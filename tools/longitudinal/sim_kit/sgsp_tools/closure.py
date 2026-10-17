"""closure.py OUT_DIR: extract the SGSP longitudinal planner + long_mpc import closure (git show) into OUT_DIR (sim_kit/sgsp)."""
import ast, subprocess, sys, os
R = "starpilot/SecretGoodStarPilot"; OUT = sys.argv[1]
files = set(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sgsp", "sgsp_files.txt")).read().split())
def mod2path(m):
  p = m.replace(".", "/")
  for c in (p + ".py", p + "/__init__.py"):
    if c in files: return c
  return None
seen, todo, missing = set(), ["openpilot.selfdrive.controls.lib.longitudinal_planner", "openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc"], set()
SKIP = ("openpilot.cereal", "openpilot.common.swaglog", "openpilot.common.params", "openpilot.common.realtime", "openpilot.system")
while todo:
  m = todo.pop()
  if m in seen: continue
  seen.add(m)
  if m.startswith(SKIP): continue
  p = mod2path(m)
  if p is None:
    # maybe attribute import (from pkg import name)
    missing.add(m); continue
  src = subprocess.run(["git", "show", f"{R}:{p}"], capture_output=True, text=True, timeout=60).stdout
  dst = os.path.join(OUT, p); os.makedirs(os.path.dirname(dst), exist_ok=True); open(dst, "w").write(src)
  # parents' __init__
  parts = m.split(".")
  for i in range(1, len(parts)):
    todo.append(".".join(parts[:i]))
  for n in ast.walk(ast.parse(src)):
    if isinstance(n, ast.Import):
      todo += [a.name for a in n.names if a.name.startswith("openpilot.")]
    elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0 and n.module.startswith("openpilot."):
      todo.append(n.module); todo += [n.module + "." + a.name for a in n.names]
    elif isinstance(n, ast.ImportFrom) and n.level > 0:
      base = ".".join(m.split(".")[:len(m.split("."))-n.level + (1 if p.endswith("__init__.py") else 0)])
      mm = base + ("." + n.module if n.module else "")
      todo.append(mm); todo += [mm + "." + a.name for a in n.names]
print(len(seen), "seen")
real = sorted(m for m in missing if mod2path(m.rsplit(".",1)[0]) is None and not m.startswith(SKIP))
print("unresolved:", [m for m in real][:50])
