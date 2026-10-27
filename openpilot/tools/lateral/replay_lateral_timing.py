#!/usr/bin/env python3
"""Replay rlogs through lateral_timingd's estimator exactly as it runs on the car (streaming, the same runner), drive by
drive, and print every turn it measures and what it would set.

  replay_lateral_timing.py ROUTE_GLOB [ROUTE_GLOB ...] [--state state.json] [--compare turns.jsonl --label LABEL]

Each ROUTE_GLOB is one drive (its segments' rlogs). --state carries the learned state from drive to drive as the
device's STATE_PATH does. --compare matches each turn to an offline turn record (t, ay, ramp_lag, cmd_lag, tw_lag,
wy_lag; the timing standard's turns.jsonl) and reports how far apart the two are per stage.
"""
import argparse
import glob
import json
import os
import re
import sys

import numpy as np
import zstandard as zstd

from opendbc.car.structs import car
from openpilot.cereal import log
from opendbc.car.honda.steer_ratio import get_honda_vgr_inverse, normalize_honda_eps_fw
from openpilot.selfdrive.controls.lib.honda_eps_calibrations import select_eps_firmware_calibration
from openpilot.selfdrive.controls.lib.honda_eps_rack_map import HondaEpsRackMap
from openpilot.selfdrive.locationd.lateral_timing import load_state, save_state
from openpilot.selfdrive.locationd.lateral_timingd import LateralTimingRunner, rack_converter, model_key

LAT_SMOOTH_SECONDS = 0.1   # latcontrol_honda_eps.LAT_SMOOTH_SECONDS (that module needs the device's native params)
SERVICES = ("carState", "carControl", "controlsState", "modelV2", "starpilotLateralState", "vehicleParameters")


def seg_num(path: str) -> int:
  m = re.findall(r"--(\d+)(?:/|$)", path)
  return int(m[-1]) if m else 0


def events(paths):
  for p in sorted(paths, key=seg_num):
    try:
      data = zstd.ZstdDecompressor().stream_reader(open(p, "rb")).read() if p.endswith(".zst") else open(p, "rb").read()
      yield from log.Event.read_multiple_bytes(data)
    except Exception as e:
      print(f"  partial {p}: {e}", file=sys.stderr)


def logmessage_source(raw: str) -> str | None:
  try:
    msg = json.loads(raw).get("msg", {})
  except (ValueError, AttributeError):
    return None
  return msg.get("source") if isinstance(msg, dict) and msg.get("event") == "modelLateralSource" else None


def replay(paths, state, label):
  CP = None
  for e in events(paths):
    if e.which() == "carParams":
      CP = e.carParams
      break
  if CP is None:
    print(f"{label}: no carParams")
    return None, state
  eps_fw = next((normalize_honda_eps_fw(fw.fwVersion) for fw in CP.carFw if str(fw.ecu) == "eps"), None)
  calibration = select_eps_firmware_calibration(str(CP.carFingerprint), eps_fw) if eps_fw else None
  inv = get_honda_vgr_inverse(CP.flags)
  rack = HondaEpsRackMap(CP.wheelbase, inv, calibration.rack) if calibration is not None and calibration.rack and inv else None
  if calibration is None or rack is None:
    print(f"{label}: not a Honda EPS controller car ({CP.carFingerprint})")
    return None, state
  keys = dict(fingerprint=str(CP.carFingerprint), calibration=calibration.name)   # replay: the car only
  runner = LateralTimingRunner(rack_converter(rack), LAT_SMOOTH_SECONDS, keys, state,
                               log=lambda name, **kw: None, drive=label)
  now = None
  for e in events(paths):
    w = e.which()
    t = e.logMonoTime * 1e-9
    if w == "can":
      runner.handle("can", t, None)   # only its receipt time is used
    elif w in SERVICES:
      runner.handle(w, t, getattr(e, w))
      if w == "carState":
        now = t
        runner.step(now)
    elif w == "logMessage":
      if model_key(e.logMessage) is not None:
        runner.handle("modelIdentity", t, e.logMessage)
      elif (src := logmessage_source(e.logMessage)) is not None:
        runner.set_source(src)
  if now is not None:
    runner.step(now + 10.0, force=True)
  return runner, runner.learner.to_dict()


def fmt(x, scale=1000.0):
  return "   -" if x is None or not np.isfinite(x) else f"{x * scale:4.0f}"


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("drives", nargs="+")
  ap.add_argument("--state")
  ap.add_argument("--compare")
  ap.add_argument("--label", action="append", default=[])
  args = ap.parse_args()
  state = load_state(args.state) if args.state else None
  offline = [json.loads(line) for line in open(args.compare)] if args.compare else []
  diffs = {k: [] for k in ("ramp", "cmd", "tw", "wy", "ay")}
  for i, pattern in enumerate(args.drives):
    label = args.label[i] if i < len(args.label) else os.path.basename(pattern.rstrip("/*"))
    paths = sorted(glob.glob(pattern, recursive=True))
    runner, state = replay(paths, state, label)
    if runner is None:
      continue
    print(f"\n=== {label}: {len(runner.turns)} turns, model {runner.model}, source {runner.source}")
    print("   t0      v   band  ramp  cmd   tw   wy   ay | size    S  | told  aim  event")
    ref = [o for o in offline if o.get("label") == label]
    for r in runner.turns:
      print(f"  {r['t0'] % 10000:7.1f} {r['v']:4.1f} {str(r['band']):5s} {fmt(r['ramp'])} {fmt(r['cmd'])} {fmt(r['tw'])} {fmt(r['wy'])} "
            f"{fmt(r['ay'])} | {fmt(r['size_corr'])} {fmt(r['S'])} | {fmt(r['told'])} {fmt(r['aim'])}  {r['event'] or ''}")
      match = [o for o in ref if abs(o["t"] - r["t0"]) < 0.3]
      if match:
        o = match[0]
        for k, ok in (("ramp", "ramp_lag"), ("cmd", "cmd_lag"), ("tw", "tw_lag"), ("wy", "wy_lag"), ("ay", "ay")):
          if r[k] is not None and o.get(ok) is not None:
            diffs[k].append(r[k] - o[ok])
    est = runner.estimate()
    for name, b in est["bands"].items():
      print(f"  {name} m/s: {b['state']}, {b['n']} turns over {b['drives']} drives, S running {fmt(b['running'])} ±{fmt(b['running_se'])} ms"
            + (f", frozen {fmt(b['value'])}" if b.get("value") is not None else "")
            + (f" -> delivery {fmt(b.get('delivery_running'))} ms, plan told {fmt(b.get('plan_told_running'))}, "
               f"head command delay {fmt(b.get('head_cmd_delay_running'))}" if b.get("delivery_running") is not None else ""))
    print(f"  aim: {est['aim']}")
  if args.state and state is not None:
    save_state(args.state, state)
  if offline:
    print("\nreplay - offline, per matched turn (ms): median / 90th percentile of |diff| / share within 5 ms")
    for k, d in diffs.items():
      if d:
        a = np.abs(d)
        print(f"  {k:5s} n {len(d):3d}  median {np.median(d) * 1000:+5.1f}  p90 |d| {np.percentile(a, 90) * 1000:5.1f}  within 5 ms {np.mean(a <= 0.005) * 100:3.0f}%")


if __name__ == "__main__":
  main()
