"""Step 2: V-ASM training/benchmark crops from driver-camera footage, with auto-proposed labels to review.

For every segment in /work/dm/<route>/<seg>/dcamera.hevc that has an ex_<route>_<seg>.json (tools/vasm_replay/rlog_extract.py),
sample both sides at --hz and save the model's exact input (the daemon's own _run_inference blob, 352x352 RGB) as a
PNG. PNG is lossless, so PNG/255 is bit-identical to the blob the shipped model saw (checked below on every crop).

manifest.csv, one row per crop:
  file, route, seg, t, frame, car_side, image_side   car_side is the driver's side (the driver camera is mirrored)
  p_nocar, p_car, p_distant                          shipped model output (softmax)
  radar_*                                            leadLeft/leadRight on that car side at t (dRel is ahead of the radar)
  pass_hold                                          the real D-118 PassHold would hold this side at t
  v_ego, blinker, mean_luma                          context; mean_luma < NIGHT_LUMA marks night/IR crops
  proposal, review                                   proposed class (0 nocar, 1 car, 2 distant) and why it needs a look
  split                                              "test" for --test-routes (held out by route), else "train"

Proposals are only a starting point for the labeler: a confident model (>= SURE) is proposed as-is; anything that is
uncertain, or where radar disagrees with the camera, is proposed and flagged for review.
"""

import argparse
import bisect
import csv
import glob
import json
import os

import av
import cv2
import numpy as np
from openpilot.starpilot.common.vasm_assist import AdjacentLead, PassHold
from openpilot.starpilot.system.adj_spot_monitor_vision_inference import V_ASM_UPSTREAM_MODEL_PATH, VASMInference

SURE = 0.98  # model probability taken as a proposal without review
RADAR_NEAR_M = 8.0  # radar car in the next lane this close ahead: its rear may already be in the crop
NIGHT_LUMA = 40.0  # mean crop luma (0-255, unmasked pixels) below this = night / IR
IMAGE_TO_CAR = {"left": "right", "right": "left"}  # mirrored driver camera, see vasm_assist.CAR_TO_IMAGE
FIELDS = [
  "file",
  "route",
  "seg",
  "t",
  "frame",
  "car_side",
  "image_side",
  "p_nocar",
  "p_car",
  "p_distant",
  "radar_status",
  "radar_drel",
  "radar_vrel",
  "radar_track",
  "pass_hold",
  "v_ego",
  "blinker",
  "mean_luma",
  "proposal",
  "review",
  "split",
]


class BlobTap:
  """Wraps the cv2.dnn net so the daemon's own preprocessing hands us its input blob and the full output."""

  def __init__(self, net):
    self.net, self.blob, self.out = net, None, None

  def setInput(self, blob):
    self.blob = blob.copy()
    self.net.setInput(blob)

  def forward(self):
    self.out = np.squeeze(self.net.forward()).copy()
    return self.out


def hold_intervals(radar):
  """[(start, end)] per car side where the real PassHold holds, from the rlog radar rows."""
  hold, on, out = PassHold(), {"left": None, "right": None}, {"left": [], "right": []}
  for row in radar:
    t = row[0]
    for i, side in enumerate(("left", "right")):
      st, d, _y, v, tid = row[1 + 5 * i : 6 + 5 * i]
      held = hold.update(side, AdjacentLead(True, d, v, int(tid)) if st else None, t)
      if held and on[side] is None:
        on[side] = t
      elif not held and on[side] is not None:
        out[side].append((on[side], t))
        on[side] = None
  for side, start in on.items():
    if start is not None:
      out[side].append((start, radar[-1][0]))
  return out


def propose(probs, radar_near, held):
  cls = int(np.argmax(probs))
  reasons = []
  if probs[cls] < SURE:
    reasons.append("uncertain")
  if held and cls != 1:
    reasons.append("pass_hold_but_camera_clear")
  if radar_near and cls == 0:
    reasons.append("radar_near_but_camera_clear")
  return cls, "+".join(reasons)


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--dm", default="/work/dm")
  ap.add_argument("--out", default="/work/crops")
  ap.add_argument("--hz", type=float, default=4.0)
  ap.add_argument("--test-routes", default="00000321--67540f4492,00000323--c20feb1f4b")
  args = ap.parse_args()
  test_routes = set(filter(None, args.test_routes.split(",")))
  os.makedirs(args.out, exist_ok=True)
  manifest = os.path.join(args.out, "manifest.csv")
  done = set()
  if os.path.exists(manifest):
    with open(manifest) as f:
      done = {(r["route"], r["seg"]) for r in csv.DictReader(f)}

  with open(manifest, "a", newline="") as mf:
    writer = csv.DictWriter(mf, fieldnames=FIELDS)
    if not done:
      writer.writeheader()
    for seg_dir in sorted(glob.glob(os.path.join(args.dm, "*", "*"))):
      route, seg = seg_dir.split(os.sep)[-2:]
      ex_path = os.path.join(args.dm, f"ex_{route}_{seg}.json")
      video = os.path.join(seg_dir, "dcamera.hevc")
      if (route, seg) in done or not (os.path.exists(ex_path) and os.path.exists(video)):
        continue
      with open(ex_path) as f:
        ex = json.load(f)
      inf = VASMInference(V_ASM_UPSTREAM_MODEL_PATH)
      assert inf.load(), inf.last_error
      inf.load_config(json.loads(ex["params"]["VASMAnnotationConfig"]))
      net, tap = inf.net, BlobTap(inf.net)
      inf.net = tap

      frame_t = [r[1] for r in ex["frames"]]
      radar = ex["radar"]
      radar_t = [r[0] for r in radar]
      car = ex["car"]
      car_t = [r[0] for r in car]
      holds = hold_intervals(radar) if radar else {"left": [], "right": []}
      split = "test" if route in test_routes else "train"
      crop_dir = os.path.join(args.out, route, seg)
      os.makedirs(crop_dir, exist_ok=True)

      next_t, n = None, 0
      container = av.open(video)
      for i, fr in enumerate(container.decode(video=0)):
        if i >= len(frame_t):
          break
        t = frame_t[i]
        if next_t is not None and t < next_t:
          continue
        next_t = t + 1.0 / args.hz
        nv = fr.to_ndarray(format="nv12")
        inf._prepare_geometry(fr.height, fr.width)
        ri = max(bisect.bisect_right(radar_t, t) - 1, 0)
        ci = max(bisect.bisect_right(car_t, t) - 1, 0)
        for image_side in ("left", "right"):
          if inf.bboxes[image_side] is None:
            continue
          inf._run_inference(nv, fr.height, image_side)
          rgb = (tap.blob[0].transpose(1, 2, 0) * 255.0).round().astype(np.uint8)
          probs = tap.out
          name = f"{i:04d}_{image_side}.png"
          path = os.path.join(crop_dir, name)
          cv2.imwrite(path, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
          back = cv2.cvtColor(cv2.imread(path), cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
          assert np.array_equal(back.transpose(2, 0, 1), tap.blob[0]), f"PNG round trip changed {path}"

          car_side = IMAGE_TO_CAR[image_side]
          k = 0 if car_side == "left" else 1
          st, d, _y, v, tid = radar[ri][1 + 5 * k : 6 + 5 * k] if radar else (0, 0.0, 0.0, 0.0, -1)
          held = any(a <= t <= b for a, b in holds[car_side])
          lit = rgb[rgb.max(axis=2) > 0]
          luma = float(lit.mean()) if lit.size else 0.0
          cls, review = propose(probs, bool(st) and 0.0 <= d <= RADAR_NEAR_M, held)
          writer.writerow(
            {
              "file": f"{route}/{seg}/{name}",
              "route": route,
              "seg": seg,
              "t": f"{t:.3f}",
              "frame": i,
              "car_side": car_side,
              "image_side": image_side,
              "p_nocar": f"{probs[0]:.4f}",
              "p_car": f"{probs[1]:.4f}",
              "p_distant": f"{probs[2]:.4f}",
              "radar_status": int(bool(st)),
              "radar_drel": f"{d:.1f}",
              "radar_vrel": f"{v:.1f}",
              "radar_track": int(tid),
              "pass_hold": int(held),
              "v_ego": f"{car[ci][1]:.1f}" if car else "",
              "blinker": int(bool(car[ci][2 + k])) if car else 0,
              "mean_luma": f"{luma:.1f}",
              "proposal": cls,
              "review": review,
              "split": split,
            }
          )
          n += 1
      inf.net = net
      mf.flush()
      print(f"{route} {seg}: {n} crops ({split})", flush=True)


if __name__ == "__main__":
  main()
