#!/usr/bin/env python3
"""Score closed_loop.py pickles (replay only). score.py OUT.pkl CAND [--ref reference/expected.json KEY]
Per event: command min, biggest 0.5 s command drop, closest gap (m), min TTC (s), achieved-decel min and biggest 0.5 s drop."""
import json, pickle, sys
import numpy as np


def metrics(rows, c):
  r = [x for x in rows if x["out"].get(c) and x["out"][c][6] is not None]
  if not r:
    return None
  t = np.array([x["t"] for x in r]); u = np.array([x["out"][c][0] for x in r]); a = np.array([x["out"][c][6][1] for x in r])
  drop = lambda y: float(max(y[i] - y[i:np.searchsorted(t, t[i] + 0.5) + 1].min() for i in range(len(t))))
  g, ttc = [], []
  for x in r:
    s, _, d, _, vl, _ = x["L"]
    if not s:
      continue
    v, _, _, sh = x["out"][c][6]; g.append(d + sh)
    if v - vl > 0.1:
      ttc.append((d + sh) / (v - vl))
  return dict(cmd_min=float(u.min()), cmd_drop=drop(u), gap_min=min(g) if g else None, ttc_min=min(ttc) if ttc else None,
              ach_min=float(a.min()), ach_drop=drop(a))


def score(pkl, cand):
  res = pickle.load(open(pkl, "rb"))
  return {k: metrics(v["rows"], cand) for k, v in res.items() if v.get("rows")}


if __name__ == "__main__":
  out = score(sys.argv[1], sys.argv[2])
  ref = json.load(open(sys.argv[sys.argv.index("--ref") + 1]))[sys.argv[sys.argv.index("--ref") + 2]] if "--ref" in sys.argv else {}
  worst = 0.0
  for k, m in out.items():
    if m is None:
      print(f"{k:28} no rows"); continue
    line = f"{k:28} " + " ".join(f"{n}={'-' if m[n] is None else round(m[n], 2)}" for n in m)
    if k in ref and ref[k]:
      d = max(abs(m[n] - ref[k][n]) for n in m if m[n] is not None and ref[k].get(n) is not None)
      worst = max(worst, d); line += f"   max|diff vs ref|={d:.3f}"
    print(line)
  if ref:
    print(f"WORST diff vs reference: {worst:.3f}  (expect < 0.05 on the same planner/params/plant; route-data or build mismatch otherwise)")
