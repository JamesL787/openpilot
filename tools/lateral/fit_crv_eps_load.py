#!/usr/bin/env python3
"""Fit LatControlHondaEps' CR-V feedback scale (R6) and column-load model from a native-rate EPS telemetry drive.

The input is the native extraction (schema `honda-crv-eps-autotune-v2`, e.g. `drive-82bb552a2c-native-v5.json`):
~49 Hz V5 EPS groups plus 100 Hz vehicle and openpilot samples. The path is explicit: route data and extracted
drives are not repository dependencies.

Why native, not the 10 Hz compact drive: the compact `speed` field is mph (`extract_drives.py` writes
`vEgo * 2.23694`), the compact angle is the raw steering angle (the controller evaluates the load on the
offset-corrected desired angle), and the compact drive carries no roll. Fitting that file put the speed term in
mph^2 (5.0x too weak in the controller's m/s), folded the steering-angle offset into the bias, and left roll at zero.
"""
import argparse
import json
from pathlib import Path

import numpy as np

LOAD_NAMES = ("k0", "k1", "c", "friction", "bias", "kroll")
R6_LAGS = np.arange(-0.10, 0.1001, 0.005)  # s


def _arrays(drive: dict, block: str) -> dict[str, np.ndarray]:
  return {k: np.asarray(v, dtype=float) for k, v in drive[block].items()
          if isinstance(v, list) and v and not isinstance(v[0], str)}


def _at(t_src: np.ndarray, x: np.ndarray, t: np.ndarray) -> np.ndarray:
  ok = np.isfinite(x)
  return np.interp(t, t_src[ok], x[ok])


def fit_r6(eps: dict, veh: dict, lags=R6_LAGS) -> tuple[float, float, float, int]:
  """Least squares of the EPS's own feedback_R6 on steering_rate_deg, hands off, over a lag scan.

  The lag absorbs tracker-1 and CAN timing; a median of R6/rate is biased low by that lag and must not be used.
  Returns (counts per deg/s, lag s, R^2, samples)."""
  te, r6 = eps["t"], eps["feedback_R6"]
  best = None
  for lag in lags:
    rate = np.interp(te - lag, veh["t"], veh["steering_rate_deg"])
    keep = ((np.abs(rate) > 2.0) & (np.abs(rate) < 200.0) & (np.abs(r6) < 32000)
            & (np.interp(te, veh["t"], np.abs(veh["steering_torque"])) < 400.0)
            & (np.interp(te, veh["t"], veh["steering_pressed"]) < 0.5) & (np.interp(te, veh["t"], veh["v_ego"]) > 2.0))
    x = np.column_stack((rate[keep], np.ones(int(keep.sum()))))
    coef = np.linalg.lstsq(x, r6[keep], rcond=None)[0]
    resid = r6[keep] - x @ coef
    r2 = 1.0 - float(resid @ resid) / float(((r6[keep] - r6[keep].mean()) ** 2).sum())
    if best is None or r2 > best[2]:
      best = (float(coef[0]), float(lag), r2, int(keep.sum()))
  return best


def load_design(eps: dict, veh: dict, op: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
  """The controller's load form, in its own units: m/s, offset-corrected angle (deg), rate (deg/s), roll (rad)."""
  te = eps["t"]
  angle = np.interp(te, veh["t"], veh["steering_angle_deg"]) - _at(op["t"], op["live_angle_offset_deg"], te)
  rate = np.interp(te, veh["t"], veh["steering_rate_deg"])
  speed = np.interp(te, veh["t"], veh["v_ego"])
  roll = _at(op["t"], op["live_roll_rad"], te)
  roll_ok = np.interp(te, op["t"], np.isfinite(op["live_roll_rad"]).astype(float)) > 0.99
  x = np.column_stack((angle, angle * speed ** 2, rate, np.tanh(rate / 5.0), np.ones(len(te)), roll * speed ** 2))
  keep = ((speed > 2.0) & (np.interp(te, veh["t"], veh["steering_pressed"]) < 0.5)
          & (np.interp(te, veh["t"], np.abs(veh["steering_torque"])) < 400.0) & (np.abs(eps["pd_key"]) > 5.0)
          & (eps["scale"] == 256.0) & (np.interp(te, op["t"], op["lat_active"]) > 0.5) & roll_ok
          & np.isfinite(x).all(axis=1))
  return x, eps["output"], keep, speed


def score(x: np.ndarray, y: np.ndarray, coefficients: np.ndarray) -> tuple[float, float]:
  residual = y - x @ coefficients
  r2 = 1.0 - float(residual @ residual) / float((y - y.mean()) @ (y - y.mean()))
  return r2, float(np.sqrt(np.mean(residual ** 2)))


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("drive", type=Path, help="native drive JSON (schema honda-crv-eps-autotune-v2)")
  parser.add_argument("--drive-norm", type=float, required=True, help="feedback normalization of the image the drive ran")
  parser.add_argument("--target-norm", type=float, default=1650.0, help="feedback normalization of the image to calibrate")
  args = parser.parse_args()
  drive = json.loads(args.drive.read_text())
  if drive.get("schema") != "honda-crv-eps-autotune-v2":
    raise SystemExit("expected a native honda-crv-eps-autotune-v2 drive, not the 10 Hz compact one")
  eps, veh, op = _arrays(drive, "eps"), _arrays(drive, "vehicle"), _arrays(drive, "openpilot")
  print(f"route={drive.get('route')} application_sha256={drive.get('application_sha256')}")

  r6, lag, r2, n = fit_r6(eps, veh)
  scaled = r6 * args.target_norm / args.drive_norm
  print(f"r6: {r6:.4f} counts/(deg/s) at norm {args.drive_norm:g}, lag {lag * 1000:+.0f} ms, R2 {r2:.4f}, n {n}")
  print(f"r6 at norm {args.target_norm:g}: {scaled:.4f}")

  x, y, keep, speed = load_design(eps, veh, op)
  coefficients = np.linalg.lstsq(x[keep], y[keep], rcond=None)[0]
  r2, rms = score(x[keep], y[keep], coefficients)
  print(f"load samples={int(keep.sum())} share above 20 m/s={float((speed[keep] > 20.0).mean()):.3f}")
  print("load=(" + ", ".join(f"{value:.6g}" for value in coefficients) + ")  # " + ", ".join(LOAD_NAMES))
  print(f"fit r2={r2:.6f} rms={rms:.3f}")
  blocks = (eps["t"] // 60.0).astype(int)
  for parity in (0, 1):
    train = keep & (blocks % 2 != parity)
    test = keep & (blocks % 2 == parity)
    held = np.linalg.lstsq(x[train], y[train], rcond=None)[0]
    held_r2, held_rms = score(x[test], y[test], held)
    print(f"held_blocks={parity} train={int(train.sum())} test={int(test.sum())} r2={held_r2:.6f} rms={held_rms:.3f}")


if __name__ == "__main__":
  main()
