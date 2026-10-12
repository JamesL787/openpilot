"""Run the real D-118 PassHold on rlog radar; compare with per-frame camera truth (conf>=0.8) on the same car side."""
import glob, json
import numpy as np
from openpilot.starpilot.common.vasm_assist import AdjacentLead, PassHold
IMG = {"left": 2, "right": 1}
tot = {"holds": 0, "hold_s": 0.0, "cam_during_or_after": 0, "gap_bridged": []}
for f in sorted(glob.glob("/work/dm/conf_*.npy")):
  name = f[len("/work/dm/conf_"):-4]; conf = np.load(f); ex = json.load(open(f"/work/dm/ex_{name}.json"))
  ft = np.array([r[1] for r in ex["frames"]])[: len(conf)]
  ph = PassHold(); on = {"left": None, "right": None}
  for row in ex["radar"]:
    t = row[0]
    for si, side in enumerate(("left", "right")):
      st, d, y, v, tid = row[1 + 5 * si: 6 + 5 * si]
      h = ph.update(side, AdjacentLead(bool(st), d, v, tid) if st else None, t)
      if h and on[side] is None: on[side] = t
      if not h and on[side] is not None:
        a, b = on[side], t; on[side] = None
        c = conf[:, IMG[side]]; sel = (ft >= a) & (ft <= b + 1.0)
        cam_t = ft[sel][c[sel] >= 0.8]
        first = cam_t[0] - a if len(cam_t) else None
        tot["holds"] += 1; tot["hold_s"] += b - a
        tot["cam_during_or_after"] += first is not None
        print(f"{name:26s} car{side:5s} hold {a:7.1f}..{b:7.1f} ({b-a:3.1f}s) camera>=.8 first at {'+%.1fs' % first if first is not None else 'NEVER'}"
              f"{'' if not len(cam_t) else ', last %.1fs before hold end' % (b - cam_t[-1])}")
print(tot["holds"], "holds", round(tot["hold_s"], 1), "s; confirmed by camera:", tot["cam_during_or_after"])
