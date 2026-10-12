"""Raw V-ASM model confidence for BOTH image sides on every dcamera frame (the daemon only samples one side ~1 Hz)."""

import glob
import json
import os
import av
import numpy as np
from openpilot.starpilot.system.adj_spot_monitor_vision_inference import VASMInference, V_ASM_MODEL_PATH

for d in sorted(glob.glob("/work/dm/*/*")):
  name = d.replace("/work/dm/", "").replace("/", "_")
  outp = f"/work/dm/conf_{name}.npy"
  if os.path.exists(outp):
    continue
  ex = json.load(open(f"/work/dm/ex_{name}.json"))
  inf = VASMInference(V_ASM_MODEL_PATH)
  assert inf.load(), inf.last_error
  inf.load_config(json.loads(ex["params"]["VASMAnnotationConfig"]))
  rows = []
  c = av.open(os.path.join(d, "dcamera.hevc"))
  for i, fr in enumerate(c.decode(video=0)):
    nv = fr.to_ndarray(format="nv12")  # (h*3/2, w)
    h, w = fr.height, fr.width
    inf._prepare_geometry(h, w)
    rows.append([i, inf._run_inference(nv, h, "left"), inf._run_inference(nv, h, "right")])
    if i == 0:
      print(name, w, h, inf.bboxes["left"], inf.bboxes["right"], flush=True)
  np.save(outp, np.array(rows, dtype=np.float32))
  print(name, len(rows), flush=True)
