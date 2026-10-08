#!/usr/bin/env python3
"""Run this fork's comma side against a REAL Jetlink server over TCP, with no comma and no car.

    ./dev python -m openpilot.starpilot.jetlink_adapter.host_bench --host 127.0.0.1 [--n 400] [--rate 20]

On a Mac this talks to Jetlink.app's TCP bench listener (Settings → transport "TCP (bench client)"; Jetlink 0.8.x also takes
`-developerTransport tcp -tcpPort 5599`). It uses the vendored client, asks the server for the pinned model by identity, and
then does what modeld does with every reply: refuses a model profiles.py has not validated (`require_profile` on the spec the
SERVER reports, the first time that check meets a real server), parses the reply with this fork's Parser, takes the action the
v16 way, and publishes it through `fill_model_msg`. It reports round-trip latency, held frames, and anything non-finite.

The frames are noise (no camera), so the outputs say nothing about driving; the point is protocol compatibility, the model
gate, the output path and the host's latency tail. Use `--frames-from` an .npy of shape (N, 2, 6, 128, 256) uint8 for real ones."""
from __future__ import annotations

import argparse
import logging
import sys
import time

import numpy as np

from openpilot.starpilot import jetlink_adapter as ja
from openpilot.starpilot.jetlink_adapter import profiles

ja.vendor_on_path()
FRAME_BUDGET_MS = 50.0


def main(argv=None) -> int:
  p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  p.add_argument("--host", default="127.0.0.1")
  p.add_argument("--port", type=int, default=5599)
  p.add_argument("--n", type=int, default=400)
  p.add_argument("--rate", type=float, default=20.0)
  p.add_argument("--frames-from", help="npy of uint8 warped frames, shape (N, 2, 6, 128, 256)")
  p.add_argument("--timeout", type=float, default=10.0, help="seconds to wait for the connection")
  args = p.parse_args(argv)

  from jetlink.client import JetlinkClient
  from openpilot.selfdrive.modeld.constants import ModelConstants
  from openpilot.selfdrive.modeld.fill_model_msg import PublishState, fill_model_msg
  from openpilot.selfdrive.modeld.modeld import get_action_from_model
  from openpilot.selfdrive.modeld.parse_model_outputs import Parser
  from cereal import log, messaging

  profile = profiles.CINQUE_TERRE_V3
  try:
    client = JetlinkClient.open_tcp(args.host, args.port)
  except OSError as e:
    print(f"cannot reach a Jetlink server at {args.host}:{args.port}: {e}", file=sys.stderr)
    print("Set Jetlink.app to the TCP bench transport (or start jetlink-server without --usb) and retry.", file=sys.stderr)
    return 2
  try:
    hello = client.hello()
    print(f"server: {hello.get('backend')} {hello.get('runtime_version', hello.get('trt_version'))} on {hello.get('device')}")
    print(f"engine {hello.get('engine_state')}")
    spec = client.ensure_engine(profile.sha256, profile.nbytes, progress=lambda s, f, m: print(f"  {s:<7} {f*100:5.1f}%  {m}"))
    got = profiles.require_profile(spec)           # the gate modeld's join applies, on the server's own spec
    print(f"server spec accepted as {got.name} ({got.generation})")

    frames = np.load(args.frames_from) if args.frames_from else None
    rng = np.random.default_rng(0)
    warped = rng.integers(0, 256, spec.warped_shape, dtype=np.uint8)
    packed = np.zeros(spec.packed_nelem, np.float32)
    packed[spec.packed_layout["action_t"][0]] = [0.3, 0.6]
    parser, state, prev = Parser(), PublishState(), log.ModelDataV2.Action()
    lat, srv, held, bad = [], [], 0, 0
    period = 1.0 / args.rate if args.rate > 0 else 0.0
    next_t = time.perf_counter()
    for i in range(args.n):
      if period:
        time.sleep(max(0.0, next_t - time.perf_counter()))
        next_t += period
      if frames is not None:
        warped = frames[i % len(frames)]
      t = time.perf_counter()
      seq = client.infer_begin(warped, packed, frame_id=i, reset=(i == 0))
      out = client.infer_end(seq, hold=None)
      lat.append((time.perf_counter() - t) * 1e3)
      srv.append(client.last_timings[2] / 1e3)
      sliced = {k: out[np.newaxis, s] for k, s in spec.output_slices.items() if k in profile.output_slices}
      parsed = parser.parse_outputs(sliced)
      action = get_action_from_model(parsed, prev, 0.3, 0.6, 15.0, profile.mlsim, False, False, False, ja_toggles(), 0.1, 0.3,
                                     is_v16=profile.is_v16)
      driving, model = messaging.new_message("drivingModelData"), messaging.new_message("modelV2")
      fill_model_msg(driving, model, parsed, action, state, i, i, i, 0.0, 0, lat[-1] / 1e3, True)
      prev = action
      if not all(np.isfinite(v).all() for v in parsed.values() if isinstance(v, np.ndarray)):
        bad += 1
    a = np.array(lat[10:] or lat)
    print(f"{len(lat)} frames, {bad} with non-finite output, {held} held")
    print(f"round trip ms: p50 {np.percentile(a, 50):.1f}  p95 {np.percentile(a, 95):.1f}  p99 {np.percentile(a, 99):.1f}  max {a.max():.1f}")
    print(f"server total ms: mean {np.mean(srv[10:] or srv):.1f}")
    print(f"over the {FRAME_BUDGET_MS:.0f} ms budget: {int((a > FRAME_BUDGET_MS).sum())}/{len(a)}")
    print(f"last action: curvature {prev.desiredCurvature:.5f} accel {prev.desiredAcceleration:.3f}  (ModelConstants.MODEL_FREQ={ModelConstants.MODEL_FREQ})")
    return 1 if bad else 0
  finally:
    client.close()


def ja_toggles():
  from types import SimpleNamespace
  return SimpleNamespace()


if __name__ == "__main__":
  logging.basicConfig(level=logging.WARNING)
  sys.exit(main())
