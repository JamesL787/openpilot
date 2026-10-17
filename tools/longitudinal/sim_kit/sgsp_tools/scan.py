import sys, json
from openpilot.tools.lib.logreader import LogReader
p, out = sys.argv[1], sys.argv[2]
rows, st, meta = [], {}, {}
for m in LogReader(p, sort_by_time=True):
  w = m.which()
  if w == "initData":
    meta["commit"] = m.initData.gitCommit; meta["branch"] = m.initData.gitBranch; meta["t_init"] = m.logMonoTime / 1e9
  elif w in ("carState", "carControl", "radarState", "selfdriveState"):
    st[w] = getattr(m, w)
  elif w == "modelV2" and len(st) == 4:
    L = st["radarState"].leadOne; cs = st["carState"]
    rows.append((m.logMonoTime / 1e9, cs.vEgo, cs.aEgo, st["carControl"].longActive, L.status, L.dRel, L.vLead, cs.gasPressed or cs.brakePressed, st["selfdriveState"].experimentalMode, st["selfdriveState"].personality.raw))
json.dump(dict(meta=meta, rows=rows), open(out, "w"))
