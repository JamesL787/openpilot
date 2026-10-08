#!/usr/bin/env python3
"""Build Jetlink's camera warp pickles for this fork's tinygrad. Run ON A COMMA: the pickle is a TinyJit captured against
the device's GPU (QCOM); a host build (CPU/Metal) produces a pickle that cannot run on the car.

    cd /data/openpilot && source ./launch_env.sh
    python3 starpilot/jetlink_adapter/build_warp.py                  # this device's camera
    python3 starpilot/jetlink_adapter/build_warp.py --all-cameras    # both geometries, for a prebuilt release

Each geometry is its own process (tinygrad fixes its device at first use) and goes through Jetlink's own capture
(``python -m jetlink.openpilot.warp``), which calls the adapter's ``make_warp`` for this fork's warp graph and writes
``starpilot/jetlink_adapter/models/warp_<cam>_<model>_tinygrad.pkl`` through a temporary, so a killed build leaves nothing
under the name modeld opens. Afterwards each pickle is loaded back the way modeld loads it (``Warps.load``), which checks
that it captured and that its call convention is the one every frame uses.

A tinygrad bump invalidates every pickle: rebuild them with it. They are committed with the other prebuilt artifacts; a
device without one for its camera simply runs the small model, and the offroad alert says why.

QCOM kernels are GPU-specific. Build each geometry on the device model that will run it (1928x1208 on tici/tizi,
1344x760 on mici) unless you have confirmed a pickle from the other device runs: ``--all-cameras`` builds both on *this*
device and says so.
"""
import argparse
import json
import os
import subprocess
import sys

CAMERAS = ((1928, 1208), (1344, 760))


def main(argv=None) -> int:
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument("--all-cameras", action="store_true", help="build every camera geometry, not only this device's")
  parser.add_argument("--camera", metavar="WxH", help="build one explicit camera geometry")
  parser.add_argument("--check-only", action="store_true", help="load the existing pickles the way modeld does; build nothing")
  args = parser.parse_args(argv)

  from openpilot.starpilot import jetlink_adapter as ja
  ja.vendor_on_path()
  from openpilot.common.basedir import BASEDIR

  op = ja.adapter()
  device_cam_w, device_cam_h, model_w, model_h = op.camera()
  if args.camera:
    w, _, h = args.camera.lower().partition("x")
    cameras = [(int(w), int(h))]
  elif args.all_cameras:
    cameras = list(CAMERAS)
    print("note: QCOM kernels are GPU-specific; confirm a pickle built here runs on the other device model before shipping it")
  else:
    cameras = [(device_cam_w, device_cam_h)]

  env = {**os.environ, "PYTHONPATH": ja.pythonpath(BASEDIR)}
  failed = []
  for cam_w, cam_h in cameras:
    target = ja.warp_path(cam_w, cam_h, model_w, model_h)
    if not args.check_only:
      print(f"== {cam_w}x{cam_h} -> {model_w}x{model_h}: {target}", flush=True)
      cmd = [sys.executable, "-m", "jetlink.openpilot.warp", "--adapter", ja.ADAPTER_MODULE,
             "--camera", f"{cam_w}x{cam_h}", "--model", f"{model_w}x{model_h}", "--output", str(target)]
      if subprocess.run(cmd, cwd=BASEDIR, env=env).returncode != 0:
        failed.append((cam_w, cam_h, "build failed"))
        continue
      # what it was built against, beside it: modeld refuses a pickle whose record does not match the running tinygrad
      ja.warp_meta_path(target).write_text(json.dumps(ja.warp_meta(cam_w, cam_h, model_w, model_h), indent=1) + "\n")
    try:
      # a fresh process again: the capture process has the device open, and modeld loads in a clean one
      check = "; ".join(["from openpilot.starpilot import jetlink_adapter as ja", "ja.vendor_on_path()",
                         "from jetlink.openpilot.warp import Warps",
                         f"Warps(ja.adapter()).load({cam_w}, {cam_h}, {model_w}, {model_h})", "print('load ok')"])
      subprocess.run([sys.executable, "-c", check], cwd=BASEDIR, env=env, check=True)
    except subprocess.CalledProcessError:
      failed.append((cam_w, cam_h, "pickle does not load"))

  for cam_w, cam_h, why in failed:
    print(f"FAILED {cam_w}x{cam_h}: {why}", file=sys.stderr)
  return 1 if failed else 0


if __name__ == "__main__":
  sys.exit(main())
