"""Per segment: V-ASM params from initData, driver frame timestamps, radar adjacent leads, ego state."""
import json, sys, glob, os
from openpilot.tools.lib.logreader import LogReader
WANT = ("VASMAnnotationConfig", "VASMConfidenceThreshold", "VASMSmoothSeconds", "VASMEnabled", "VASMRadarAssist", "VASMConfHoldOff")
for d in sorted(glob.glob("/work/dm/*/*")):
  out = {"params": {}, "frames": [], "radar": [], "car": []}
  t0 = None
  for m in LogReader(os.path.join(d, "rlog.zst")):
    w = m.which()
    if t0 is None: t0 = m.logMonoTime
    t = (m.logMonoTime - t0) * 1e-9
    if w == "initData":
      for e in m.initData.params.entries:
        if e.key.startswith("VASM"):
          out["params"][e.key] = e.value.decode(errors="replace")[:4000]
    elif w == "driverEncodeIdx":
      e = m.driverEncodeIdx
      out["frames"].append([e.segmentId, t, e.frameId])
    elif w == "starpilotRadarState":
      r = m.starpilotRadarState
      row = [t]
      for l in (r.leadLeft, r.leadRight):
        row += [int(l.status), round(l.dRel, 2), round(l.yRel, 2), round(l.vRel, 2), int(l.radarTrackId)]
      out["radar"].append(row)
    elif w == "carState":
      c = m.carState
      out["car"].append([t, round(c.vEgo, 2), int(c.leftBlinker), int(c.rightBlinker), int(c.leftBlindspot), int(c.rightBlindspot)])
  out["t0_mono"] = t0
  name = d.replace("/work/dm/", "").replace("/", "_")
  json.dump(out, open(f"/work/dm/ex_{name}.json", "w"))
  print(name, {k: (v[:80] if isinstance(v, str) else v) for k, v in out["params"].items()}, len(out["frames"]), len(out["radar"]))
