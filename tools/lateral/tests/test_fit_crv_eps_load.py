"""fit_crv_eps_load: recovers a known R6 scale and column load from a synthetic native drive (D-092)."""
import json

import numpy as np
import pytest

from openpilot.tools.lateral import fit_crv_eps_load as fit

TRUE_LOAD = np.array([-7.3, -0.143, -4.6, -298.0, -20.0, -3.6])
TRUE_R6 = -121.6
LAG = 0.015


def _drive(seed=0, minutes=6):
  rng = np.random.default_rng(seed)
  tv = np.arange(0.0, minutes * 60.0, 0.01)                       # 100 Hz vehicle / openpilot
  speed = 15.0 + 12.0 * np.sin(tv / 40.0)
  offset = np.full_like(tv, -0.69)
  true_angle = 25.0 * np.sin(tv / 3.1) + 6.0 * np.sin(tv / 0.9)
  rate = np.gradient(true_angle, tv)
  roll = 0.03 * np.sin(tv / 17.0)
  angle = true_angle + offset                                     # carState reads the raw angle
  te = np.arange(0.0, tv[-1] - 0.1, 0.02)                         # ~50 Hz EPS groups
  ta, sp, rl, rt = (np.interp(te, tv, x) for x in (true_angle, speed, roll, rate))
  x = np.column_stack((ta, ta * sp ** 2, rt, np.tanh(rt / 5.0), np.ones(len(te)), rl * sp ** 2))
  output = x @ TRUE_LOAD + rng.normal(0.0, 5.0, len(te))
  r6 = TRUE_R6 * np.interp(te - LAG, tv, rate)
  zeros_v, zeros_e = np.zeros_like(tv), np.zeros_like(te)
  return {
    "schema": "honda-crv-eps-autotune-v2", "route": "synthetic", "application_sha256": None,
    "eps": {"t": te.tolist(), "feedback_R6": r6.tolist(), "output": output.tolist(), "scale": (zeros_e + 256).tolist(),
            "pd_key": (zeros_e + 100).tolist()},
    # speed is m/s here, as the native extraction writes it (the compact drive's is mph)
    "vehicle": {"t": tv.tolist(), "v_ego": speed.tolist(), "steering_angle_deg": angle.tolist(),
                "steering_rate_deg": rate.tolist(), "steering_torque": zeros_v.tolist(),
                "steering_pressed": zeros_v.tolist()},
    "openpilot": {"t": tv.tolist(), "lat_active": (zeros_v + 1).tolist(), "live_roll_rad": roll.tolist(),
                  "live_angle_offset_deg": offset.tolist(), "personality": ["standard"] * len(tv)},
  }


def _parts(drive):
  return fit._arrays(drive, "eps"), fit._arrays(drive, "vehicle"), fit._arrays(drive, "openpilot")


def test_recovers_the_feedback_scale_and_its_lag():
  eps, veh, _ = _parts(_drive())
  r6, lag, r2, n = fit.fit_r6(eps, veh)
  assert r6 == pytest.approx(TRUE_R6, rel=0.01)
  assert lag == pytest.approx(LAG, abs=0.006)
  assert r2 > 0.99 and n > 1000


def test_recovers_the_load_in_controller_units():
  eps, veh, op = _parts(_drive())
  x, y, keep, _ = fit.load_design(eps, veh, op)
  coef = np.linalg.lstsq(x[keep], y[keep], rcond=None)[0]
  assert coef == pytest.approx(TRUE_LOAD, rel=0.03, abs=0.5)


def test_raw_angle_and_mph_would_have_biased_the_fit():
  # the two D-091 defects, reproduced: the angle offset leaks into the bias and mph shrinks k1 by 2.237^2
  eps, veh, op = _parts(_drive())
  x, y, keep, speed = fit.load_design(eps, veh, op)
  raw = x.copy()
  raw[:, 0] -= 0.69
  raw[:, 1] = raw[:, 0] * (speed * 2.23694) ** 2
  coef = np.linalg.lstsq(raw[keep], y[keep], rcond=None)[0]
  assert coef[1] == pytest.approx(TRUE_LOAD[1] / 2.23694 ** 2, rel=0.05)
  assert abs(coef[4] - TRUE_LOAD[4]) > 2.0


def test_rejects_the_compact_drive(tmp_path, monkeypatch, capsys):
  path = tmp_path / "compact.json"
  path.write_text(json.dumps({"route": "x", "speed": [1.0]}))
  monkeypatch.setattr("sys.argv", ["fit", str(path), "--drive-norm", "1450"])
  with pytest.raises(SystemExit):
    fit.main()
