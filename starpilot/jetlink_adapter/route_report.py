#!/usr/bin/env python3
"""Qualification report for a drive or replay that includes Jetlink handovers.

    python3 -m openpilot.starpilot.jetlink_adapter.route_report <route | segment | rlog path> [--json]

What a mocked test cannot show, from the logs of a real run: how long the whole modeld frame took on each backend (warp +
transport + parse + publish, as modeld measures it: ``modelV2.modelExecutionTime``), how stale a held output was, how many
camera frames were dropped, and what the consumers of modelV2 did around each backend switch: the Bosch radar's lead
(`radarState.leadOne`: range, relative speed, model probability, status flips), the model-based ego velocity, the
longitudinal target and the commanded accel. Each handover window is compared with the same step statistic over the quiet
rest of the drive, so a step is judged against what this car does anyway.

The analysis is a pure function of the messages (`analyze`), so it is tested on synthetic logs; running it on a real route is
the qualification this repository cannot do without a comma and a host."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict

import numpy as np

# the window around a handover that is compared with the rest of the drive, seconds
BEFORE, AFTER = 1.0, 2.0
# lead range steps larger than this between consecutive radarState frames are a jump, not tracking (m)
LEAD_JUMP_M = 2.0


def _pct(values, q):
  return float(np.percentile(values, q)) if len(values) else None


def _summary(values):
  v = np.asarray(values, dtype=float)
  if not len(v):
    return {"n": 0}
  return {"n": int(len(v)), "p50": _pct(v, 50), "p95": _pct(v, 95), "p99": _pct(v, 99), "max": float(v.max())}


def _steps(series):
  """|difference| between consecutive samples of [(t, value)], as [(t, step)]."""
  return [(t1, abs(v1 - v0)) for (t0, v0), (t1, v1) in zip(series, series[1:], strict=False)]


def analyze(msgs) -> dict:
  state_t, state = [], []           # starpilotModelV2 (t, backend, accelerator, held, age_ms, handovers)
  model = []                        # (t, exec_ms, drop_perc, frame_id, ego_v, lead0_prob)
  radar = []                        # (t, md_lag_ms, d_rel, v_rel, model_prob, status)
  plan_a, accel_cmd, events = [], [], []
  for m in msgs:
    t = m.logMonoTime / 1e9
    which = m.which()
    if which == "starpilotModelV2":
      s = m.starpilotModelV2
      state_t.append(t)
      state.append((str(s.backend), str(s.accelerator), int(s.heldFrames), float(s.outputAgeMs), int(s.handovers)))
    elif which == "modelV2":
      v = m.modelV2
      model.append((t, v.modelExecutionTime * 1e3, v.frameDropPerc, int(v.frameId), v.velocity.x[0] if len(v.velocity.x) else np.nan,
                    v.leadsV3[0].prob if len(v.leadsV3) else np.nan))
    elif which == "radarState":
      r = m.radarState
      lead = r.leadOne
      radar.append((t, (m.logMonoTime - r.mdMonoTime) / 1e6, lead.dRel, lead.vRel, lead.modelProb, bool(lead.status)))
    elif which == "longitudinalPlan":
      plan_a.append((t, float(m.longitudinalPlan.aTarget)))
    elif which == "carControl":
      accel_cmd.append((t, float(m.carControl.actuators.accel)))
    elif which == "onroadEvents":
      for e in m.onroadEvents:
        if e.softDisable or e.immediateDisable or e.userDisable:
          events.append((t, str(e.name)))

  def backend_at(t):
    i = int(np.searchsorted(state_t, t, side="right")) - 1
    return state[i] if i >= 0 else ("local", "none", 0, 0.0, 0)

  by_backend = defaultdict(lambda: {"exec_ms": [], "drop_perc": [], "held": 0, "frames": 0, "age_ms": []})
  last_frame = None
  for t, exec_ms, drop, frame_id, _, _ in model:
    backend, _, held, age, _ = backend_at(t)
    b = by_backend[backend]
    b["frames"] += 1
    b["exec_ms"].append(exec_ms)
    b["drop_perc"].append(drop)
    b["held"] += 1 if held else 0
    if age:
      b["age_ms"].append(age)
    if last_frame is not None and frame_id - last_frame > 1:
      b.setdefault("dropped_camera_frames", 0)
      b["dropped_camera_frames"] += frame_id - last_frame - 1
    last_frame = frame_id

  handovers, prev = [], None
  for t, s in zip(state_t, state, strict=False):
    if prev is not None and s[0] != prev[0]:
      handovers.append({"t": t, "from": prev[0], "to": s[0], "accelerator": s[1]})
    prev = s

  series = {
    "lead_range_m": [(t, d) for t, _, d, _, _, st in radar if st],
    "lead_rel_speed": [(t, v) for t, _, _, v, _, st in radar if st],
    "lead_model_prob": [(t, p) for t, _, _, _, p, _ in radar],
    "model_ego_velocity": [(t, v) for t, _, _, _, v, _ in model if np.isfinite(v)],
    "model_lead_prob": [(t, p) for t, _, _, _, _, p in model if np.isfinite(p)],
    "plan_a_target": plan_a,
    "accel_command": accel_cmd,
  }
  all_steps = {k: _steps(v) for k, v in series.items()}
  windows = [(h["t"] - BEFORE, h["t"] + AFTER) for h in handovers]

  def in_window(t):
    return any(a <= t <= b for a, b in windows)

  baseline = {k: _summary([s for t, s in v if not in_window(t)]) for k, v in all_steps.items()}
  for h in handovers:
    a, b = h["t"] - BEFORE, h["t"] + AFTER
    around = {}
    for k, v in all_steps.items():
      inside = [s for t, s in v if a <= t <= b]
      base_p99 = baseline[k].get("p99")
      worst = max(inside) if inside else None
      around[k] = {"max_step": worst, "baseline_p99": base_p99,
                   "exceeds_baseline": bool(worst is not None and base_p99 is not None and worst > base_p99)}
    lead_flips = sum(1 for r0, r1 in zip(radar, radar[1:], strict=False) if a <= r1[0] <= b and r0[5] != r1[5])
    jumps = sum(1 for t, s in all_steps["lead_range_m"] if a <= t <= b and s > LEAD_JUMP_M)
    h["around"] = around
    h["lead_status_flips"] = lead_flips
    h["lead_range_jumps"] = jumps
    h["soft_disables"] = [e for t, e in events if a <= t <= b]

  return {
    "frames": len(model),
    "handovers": handovers,
    "by_backend": {k: {"frames": v["frames"], "held_frames": v["held"], "exec_ms": _summary(v["exec_ms"]),
                       "frame_drop_perc": _summary(v["drop_perc"]), "output_age_ms": _summary(v["age_ms"]),
                       "dropped_camera_frames": v.get("dropped_camera_frames", 0)} for k, v in by_backend.items()},
    "radar": {"md_lag_ms": _summary([lag for _, lag, *_ in radar])},
    "baseline_step_statistics": baseline,
    "disengagements": [{"t": t, "event": e} for t, e in events],
  }


def render(report: dict) -> str:
  lines = [f"{report['frames']} modelV2 frames, {len(report['handovers'])} backend handovers"]
  for backend, b in report["by_backend"].items():
    e = b["exec_ms"]
    loop = f"loop ms p50 {e['p50']:.1f} p95 {e['p95']:.1f} p99 {e['p99']:.1f} max {e['max']:.1f}" if e.get("n") else ""
    lines.append(f"  {backend:8s} frames {b['frames']:6d}  held {b['held_frames']:4d}  dropped camera frames {b['dropped_camera_frames']:4d}  {loop}")
    if b["output_age_ms"].get("n"):
      lines.append(f"           held output age ms p99 {b['output_age_ms']['p99']:.0f} max {b['output_age_ms']['max']:.0f}")
  if report["radar"]["md_lag_ms"].get("n"):
    m = report["radar"]["md_lag_ms"]
    lines.append(f"  radarState lags its modelV2 (mdMonoTime) by ms: p50 {m['p50']:.1f} p99 {m['p99']:.1f} max {m['max']:.1f}")
  for h in report["handovers"]:
    lines.append(f"handover t={h['t']:.2f}s {h['from']} -> {h['to']}  lead flips {h['lead_status_flips']}")
    lines[-1] += f"  lead range jumps {h['lead_range_jumps']}  disables {h['soft_disables'] or 'none'}"
    for k, v in h["around"].items():
      if v["max_step"] is not None:
        mark = "  ABOVE BASELINE" if v["exceeds_baseline"] else ""
        base = f"{v['baseline_p99']:.3f}" if v["baseline_p99"] is not None else "n/a"
        lines.append(f"    {k:20s} max step {v['max_step']:.3f}  (drive p99 {base}){mark}")
  return "\n".join(lines)


def main(argv=None) -> int:
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument("route", help="a route, segment or rlog path (anything LogReader takes)")
  parser.add_argument("--json", action="store_true")
  args = parser.parse_args(argv)
  from openpilot.tools.lib.logreader import LogReader
  report = analyze(LogReader(args.route))
  print(json.dumps(report, indent=1, default=str) if args.json else render(report))
  return 0


if __name__ == "__main__":
  sys.exit(main())
