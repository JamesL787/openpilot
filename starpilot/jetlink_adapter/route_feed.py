#!/usr/bin/env python3
"""Feed a recorded drive's camera frames to a real Jetlink server and compare the large model's answer with what the car logged.

    ./dev python -m openpilot.starpilot.jetlink_adapter.route_feed ROUTE SEG --rlogs DIR --video DIR \
        --framesrc ~/nrdr/cinque-head-rl [--seconds 20] [--host 127.0.0.1]

For each camera frame (road + wide, from the segment's fcamera/ecamera.hevc, warped to (2, 6, 128, 256) with the calibration
from the same drive's rlog) the model's reply goes through this fork's own output path: spec gate (profiles.require_profile),
Parser, the v16 `get_action_from_model`, and `fill_model_msg`. Then it is compared with the modelV2 the car published for the
same frame: action curvature, plan speed and orientation rate. This is open loop: the server's recurrent state follows the
recorded frames, not its own plan.

`--framesrc` is a directory holding framesrc.py (the camera warp and log reader the cinque-head-rl project verified against the
car, corr 0.997 plan / 0.999 action on route 380). The warp here is that numpy one, not the fork's tinygrad warp; the fork's
warp graph is checked separately (tests/test_tinygrad.py)."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from openpilot.starpilot import jetlink_adapter as ja
from openpilot.starpilot.jetlink_adapter import profiles

ja.vendor_on_path()


def corr(a, b):
  a, b = np.asarray(a, float), np.asarray(b, float)
  m = np.isfinite(a) & np.isfinite(b)
  return float(np.corrcoef(a[m], b[m])[0, 1]) if m.sum() > 2 and a[m].std() > 0 and b[m].std() > 0 else float("nan")


def main(argv=None) -> int:
  p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  p.add_argument("route")
  p.add_argument("seg", type=int)
  p.add_argument("--rlogs", required=True, help="directory holding <route>--<seg>/rlog.zst")
  p.add_argument("--video", required=True, help="directory holding fcamera.hevc and ecamera.hevc of the segment")
  p.add_argument("--framesrc", required=True)
  p.add_argument("--host", default="127.0.0.1")
  p.add_argument("--port", type=int, default=5599)
  p.add_argument("--seconds", type=float, default=20.0)
  p.add_argument("--start", type=float, default=0.0, help="seconds into the segment")
  p.add_argument("--paced", action="store_true", help="send at 20 Hz instead of as fast as the server answers")
  args = p.parse_args(argv)

  sys.path.insert(0, str(Path(args.framesrc).expanduser()))
  from framesrc import LONG_ACTION_T, frames, lat_action_t
  from jetlink.client import JetlinkClient
  from cereal import log, messaging
  from openpilot.selfdrive.modeld.constants import Plan
  from openpilot.selfdrive.modeld.fill_model_msg import PublishState, fill_model_msg
  from openpilot.selfdrive.modeld.modeld import get_action_from_model
  from openpilot.selfdrive.modeld.parse_model_outputs import Parser

  profile = profiles.CINQUE_TERRE_V3
  client = JetlinkClient.open_tcp(args.host, args.port)
  try:
    hello = client.hello()
    print(f"server: {hello.get('backend')} {hello.get('runtime_version')} on {hello.get('device')}")
    spec = client.ensure_engine(profile.sha256, profile.nbytes)
    profiles.require_profile(spec)
    layout = spec.packed_layout
    parser, state, prev = Parser(), PublishState(), log.ModelDataV2.Action()
    toggles = SimpleNamespace()
    rec = {k: [] for k in ("fid", "v", "lat_t", "raw", "mine", "logged", "plan_v", "log_v", "rate_z", "log_rate", "ms", "bad")}
    last = None
    t_loop = time.perf_counter()
    t_from = args.seg * 60.0 + args.start       # frames() times are from the start of the route
    for fid, _t, v, img, logged in frames(args.rlogs, args.route, args.seg, args.video, t_from, t_from + args.seconds):
      packed = np.zeros(spec.packed_nelem, np.float32)
      packed[layout["traffic_convention"][0]] = [1, 0]
      lat_t = lat_action_t(v)
      packed[layout["action_t"][0]] = [lat_t, LONG_ACTION_T]
      t0 = time.perf_counter()
      out = client.infer(np.ascontiguousarray(img), packed, frame_id=len(rec["fid"]), reset=last is None or fid != last + 1)
      ms = (time.perf_counter() - t0) * 1e3
      last = fid
      parsed = parser.parse_outputs({k: out[np.newaxis, s] for k, s in spec.output_slices.items()})
      action = get_action_from_model(parsed, prev, lat_t, LONG_ACTION_T, v, profile.mlsim, False, False, False, toggles, 0.1, 0.3,
                                     is_v16=profile.is_v16)
      driving, model = messaging.new_message("drivingModelData"), messaging.new_message("modelV2")
      fill_model_msg(driving, model, parsed, action, state, fid, fid, fid, 0.0, 0, ms / 1e3, True)
      prev = action
      raw = float(parsed["action"][0][0]) / max(1.0, v) ** 2
      row = {"fid": fid, "v": v, "lat_t": lat_t, "raw": raw, "mine": action.desiredCurvature, "ms": ms,
             "logged": logged[0] if logged else np.nan, "plan_v": float(parsed["plan"][0][0, Plan.VELOCITY][0]),
             "log_v": float(logged[2][0]) if logged else np.nan, "rate_z": float(parsed["plan"][0][5, Plan.ORIENTATION_RATE][2]),
             "log_rate": float(logged[1][5]) if logged else np.nan}
      for key, value in row.items():
        rec[key].append(value)
      rec["bad"].append(not all(np.isfinite(x).all() for x in parsed.values() if isinstance(x, np.ndarray)))
      if args.paced:
        time.sleep(max(0.0, 0.05 - (time.perf_counter() - t0)))
    n = len(rec["fid"])
    wall = time.perf_counter() - t_loop
    ms = np.array(rec["ms"][5:])
    print(f"{n} frames of {args.route} seg {args.seg} ({wall:.1f} s wall), {sum(rec['bad'])} with non-finite output")
    print(f"speed {np.min(rec['v']):.1f}..{np.max(rec['v']):.1f} m/s (a car below 0.3 m/s holds its last curvature)")
    p50, p95, p99 = (np.percentile(ms, q) for q in (50, 95, 99))
    print(f"round trip ms: p50 {p50:.1f}  p95 {p95:.1f}  p99 {p99:.1f}  max {ms.max():.1f}")
    print(f"vs the car's logged modelV2 on the same frames (n={int(np.isfinite(rec['logged']).sum())}):")
    print(f"  action curvature, raw head / v^2     corr {corr(rec['raw'], rec['logged']):.4f}")
    print(f"  action curvature, this fork's v16 path corr {corr(rec['mine'], rec['logged']):.4f}")
    print(f"  plan speed at t=0                      corr {corr(rec['plan_v'], rec['log_v']):.4f}")
    print(f"  orientation rate z at index 5          corr {corr(rec['rate_z'], rec['log_rate']):.4f}")
    d = np.array(rec["mine"]) - np.array(rec["logged"])
    d = d[np.isfinite(d)]
    print(f"  curvature difference: mean {d.mean():+.5f}  rms {np.sqrt((d ** 2).mean()):.5f}  (logged rms {np.sqrt(np.nanmean(np.square(rec['logged']))):.5f})")
    return 1 if any(rec["bad"]) else 0
  finally:
    client.close()


if __name__ == "__main__":
  sys.exit(main())
