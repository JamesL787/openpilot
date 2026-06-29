#!/usr/bin/env python3
"""NRDR live longitudinal tune — /data JSON sidecar (no params_keys.h key, no recompile).

Transport layer for live-tuning hardcoded planner/MPC constants.
A JSON file at /data/nrdr_long_tune.json is polled on the existing live-param cadence (~1 Hz).
Missing or corrupt file == compiled defaults (provable no-op). Every field is hard-clamped in
code; non-finite values are rejected. Writers must use write_tune() (write-temp-then-rename) so
the 20 Hz planner can never read a half-written file.

Consumers:
  selfdrive/controls/lib/longcontrol.py  (stopping section: hold_accel, phase_switch_v, etc.)

stopping (Bundle D / L2 - longcontrol two-phase stopping shape):
  l2_enable          [0,1] default 1 - >=0.5 routes longcontrol's stopping state through the
                     two-phase shape; <0.5 reverts to the stock monotonic ramp to stop_accel.
  hold_accel         [-1.0, -0.3] default -0.6 - gentle Phase-A hold target while still rolling.
  phase_switch_v     [0.05, 0.5] default 0.15 - vEgo (m/s) below which true standstill declared.
  proximity_scale_m  [2.0, 20.0] default 8.0 - inert when no valid lead (dRel=inf, scale=1.0).
  pitch_margin       [0.0, 2.0] default 0.0 - grade compensation multiplier (0 = disabled here).
"""
import json
import math
import os

NRDR_LONG_TUNE_PATH = "/data/nrdr_long_tune.json"

# Bundle D / L2 stopping-shape knobs. Every entry is (default, lo, hi).
_STOPPING_CLAMPS = {
  "l2_enable": (1.0, 0.0, 1.0),
  "hold_accel": (-0.6, -1.0, -0.3),
  "phase_switch_v": (0.15, 0.05, 0.5),
  "proximity_scale_m": (8.0, 2.0, 20.0),
  "pitch_margin": (0.0, 0.0, 2.0),
}


def _clampf(value, lo, hi):
  v = float(value)
  if not math.isfinite(v):
    raise ValueError("non-finite value")
  return min(max(v, lo), hi)


class LongTune:
  """Polls the tune file and exposes clamped values; falls back to compiled defaults on any error."""

  REFRESH_INTERVAL = 20  # refresh() calls between stat() checks (~1 s at 20 Hz)

  def __init__(self, path=NRDR_LONG_TUNE_PATH, log_fn=None):
    self._path = path
    self._log_fn = log_fn
    self._frame = 0
    self._file_sig = ()
    self._last_log = None
    self._set_defaults()

  def _set_defaults(self):
    self.stopping = {k: d for k, (d, _, _) in _STOPPING_CLAMPS.items()}
    self.active = False

  def refresh(self):
    if self._frame % self.REFRESH_INTERVAL == 0:
      self._check_file()
    self._frame += 1

  def _check_file(self):
    try:
      st = os.stat(self._path)
      sig = (st.st_mtime_ns, st.st_size)
    except OSError:
      sig = None
    if sig == self._file_sig:
      return
    was_loaded = self._file_sig not in ((), None)
    self._file_sig = sig
    if sig is None:
      self._set_defaults()
      if was_loaded:
        self._warn("tune file removed; reverted to compiled defaults")
      return
    try:
      with open(self._path, encoding="utf-8") as f:
        data = json.load(f)
      if not isinstance(data, dict):
        raise ValueError("top level is not an object")
    except (OSError, ValueError) as e:
      self._set_defaults()
      self._warn(f"unreadable tune file ({e}); using compiled defaults")
      return
    self._apply(data)

  def _apply(self, data):
    self._set_defaults()
    bad = []
    if "stopping" in data:
      raw = data["stopping"]
      if isinstance(raw, dict):
        for k, (_, lo, hi) in _STOPPING_CLAMPS.items():
          if k in raw:
            try:
              self.stopping[k] = _clampf(raw[k], lo, hi)
            except (TypeError, ValueError):
              bad.append(f"stopping.{k}")
      else:
        bad.append("stopping")
    self.active = True
    if bad:
      self._warn(f"loaded with rejected fields: {', '.join(bad)}")

  def _warn(self, msg):
    if self._log_fn is not None and msg != self._last_log:
      self._last_log = msg
      self._log_fn(f"nrdr_long_tune: {msg}")


def write_tune(values, path=NRDR_LONG_TUNE_PATH):
  """Atomic write so the planner can never read a partial file."""
  tmp = path + ".tmp"
  with open(tmp, "w", encoding="utf-8") as f:
    json.dump(values, f, indent=2, sort_keys=True)
    f.write("\n")
    f.flush()
    os.fsync(f.fileno())
  os.replace(tmp, path)


if __name__ == "__main__":
  import argparse
  parser = argparse.ArgumentParser(description="NRDR long tune editor")
  parser.add_argument("--path", default=NRDR_LONG_TUNE_PATH)
  sub = parser.add_subparsers(dest="cmd", required=True)
  sub.add_parser("show")
  p_set = sub.add_parser("set")
  p_set.add_argument("assignments", nargs="+")
  sub.add_parser("reset")
  args = parser.parse_args()

  if args.cmd == "show":
    tune = LongTune(path=args.path, log_fn=print)
    tune.refresh()
    print(f"active={tune.active} stopping={tune.stopping}")
  elif args.cmd == "set":
    try:
      with open(args.path, encoding="utf-8") as f:
        data = json.load(f)
      if not isinstance(data, dict):
        data = {}
    except (OSError, ValueError):
      data = {}
    for assignment in args.assignments:
      key, _, raw = assignment.partition("=")
      keys = key.split(".")
      d = data
      for k in keys[:-1]:
        d = d.setdefault(k, {})
      try:
        d[keys[-1]] = json.loads(raw)
      except ValueError:
        d[keys[-1]] = raw
    write_tune(data, path=args.path)
    print(f"wrote {args.path}")
  elif args.cmd == "reset":
    try:
      os.remove(args.path)
      print(f"removed {args.path}")
    except FileNotFoundError:
      print("no tune file")
