"""Simulate the daemon's sampling (1 s alternation, 0.3 s follow-up, optional D-118 focus) on per-frame conf.
Report, per car side, how late the published flag turns on vs the camera's own per-frame onset, and how
many camera-seen intervals it misses entirely."""
import glob, json, sys
import numpy as np
TH, OFF = 0.8, 0.65
IMG_COL = {"left": 1, "right": 2}   # image side -> conf column
CAR = {"right": "left", "left": "right"}  # image side -> car side
def sim(ft, conf, radar, focus):
  rt = np.array([r[0] for r in radar]); act = {"left": False, "right": False}; out = []
  side, last_side = "left", {"left": -9, "right": -9}; last = -9; follow = -9; t = ft[0]
  i = 0
  while i < len(ft):
    t = ft[i]
    focus_img = set()
    if focus:
      r = radar[min(np.searchsorted(rt, t), len(radar) - 1)]
      for k, carside in ((1, "left"), (6, "right")):
        if r[k] and r[k + 1] <= 15: focus_img.add({"left": "right", "right": "left"}[carside])
    interval = 0.3 if (t < follow or focus_img) else 1.0
    if t - last >= interval - 0.015:
      if len(focus_img) == 1:
        f = next(iter(focus_img)); other = "right" if f == "left" else "left"
        side = other if t - last_side[other] >= 1.0 else f
      c = conf[i, IMG_COL[side]]
      a = act[side]
      act[side] = c >= TH if not a else c >= OFF
      last = t; last_side[side] = t
      if act["left"] or act["right"]: follow = t + 1.0
      side = "right" if side == "left" else "left"
    out.append((t, act["right"], act["left"]))  # car-left = image-right
    i += 1
  return np.array(out, dtype=float)
def intervals(t, m):
  res = []; on = None
  for ti, x in zip(t, m):
    if x and on is None: on = ti
    if not x and on is not None: res.append((on, ti)); on = None
  if on is not None: res.append((on, t[-1]))
  return res
for focus in (False, True):
  lat = []; missed = 0; total = 0
  for f in sorted(glob.glob("/work/dm/conf_*.npy")):
    name = f[len("/work/dm/conf_"):-4]; conf = np.load(f); ex = json.load(open(f"/work/dm/ex_{name}.json"))
    ft = np.array([r[1] for r in ex["frames"]])[: len(conf)]
    s = sim(ft, conf, ex["radar"], focus)
    for col, carside in ((1, "left"), (2, "right")):
      truth = intervals(ft, conf[:, IMG_COL[CAR[carside]]] >= TH)
      truth = [iv for iv in truth if iv[1] - iv[0] >= 0.5]   # ignore sub-0.5 s blips
      pub = s[:, col].astype(bool)
      for a, b in truth:
        total += 1
        on = ft[(ft >= a) & (ft <= b + 1.0) & pub]
        if len(on): lat.append(on[0] - a)
        else: missed += 1
  lat = np.array(lat)
  print(f"focus={focus}: camera intervals>=0.5s {total}, missed {missed}, onset latency median {np.median(lat):.2f}s p90 {np.percentile(lat,90):.2f}s max {lat.max():.2f}s")
