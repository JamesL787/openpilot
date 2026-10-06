#!/usr/bin/env python3
"""Fit LatControlHondaEps' CR-V column-load model from a compact EPS telemetry drive.

The input path is explicit: route data and extracted drives are not repository dependencies.
"""
import argparse
import json
from pathlib import Path

import numpy as np


def design_matrix(drive: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
  angle = np.asarray(drive["angle"], dtype=float)
  rate = np.asarray(drive["rate"], dtype=float)
  speed = np.asarray(drive["speed"], dtype=float)
  driver = np.asarray(drive["driver"], dtype=float)
  pressed = np.asarray(drive["pressed"], dtype=bool)
  command = np.asarray(drive["key"], dtype=float)
  scale = np.asarray(drive["telemetry"]["scale"], dtype=float)
  output = np.asarray(drive["telemetry"]["output"], dtype=float)
  x = np.column_stack((angle, angle * speed ** 2, rate, np.tanh(rate / 5.0), np.ones(len(angle))))
  keep = ((speed > 2.0) & ~pressed & (np.abs(driver) < 400.0) & (np.abs(command) > 5.0) &
          (scale == 256.0) & np.isfinite(x).all(axis=1) & np.isfinite(output))
  return x, output, keep


def score(x: np.ndarray, y: np.ndarray, coefficients: np.ndarray) -> tuple[float, float]:
  residual = y - x @ coefficients
  r2 = 1.0 - float(residual @ residual) / float((y - y.mean()) @ (y - y.mean()))
  return r2, float(np.sqrt(np.mean(residual ** 2)))


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("drive", type=Path, help="compact drive JSON from extract_drives.py")
  args = parser.parse_args()
  drive = json.loads(args.drive.read_text())
  x, y, keep = design_matrix(drive)
  coefficients = np.linalg.lstsq(x[keep], y[keep], rcond=None)[0]
  print(f"route={drive.get('route', 'unknown')} samples={int(keep.sum())}")
  print("load=(" + ", ".join(f"{value:.8g}" for value in coefficients) + ", 0.0)")
  r2, rms = score(x[keep], y[keep], coefficients)
  print(f"fit r2={r2:.6f} rms={rms:.3f}")
  time_s = np.asarray(drive["t"], dtype=float)
  blocks = (time_s // 60.0).astype(int)
  for parity in (0, 1):
    train = keep & (blocks % 2 != parity)
    test = keep & (blocks % 2 == parity)
    held_coefficients = np.linalg.lstsq(x[train], y[train], rcond=None)[0]
    held_r2, held_rms = score(x[test], y[test], held_coefficients)
    print(f"held_blocks={parity} train={int(train.sum())} test={int(test.sum())} r2={held_r2:.6f} rms={held_rms:.3f}")


if __name__ == "__main__":
  main()
