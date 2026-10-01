import json

import numpy as np

import openpilot.tools.drive_plots.sim_export as se
from openpilot.tools.drive_plots.rlog_report import segments
from openpilot.tools.drive_plots.tests.test_mirror_check import _write_route


def test_sim_export_writes_john_keys_per_segment(tmp_path):
  _write_route(tmp_path / "r" / "0" / "rlog", n=600)
  _write_route(tmp_path / "r" / "1" / "rlog", n=300)
  info = se.export(segments(str(tmp_path / "r")), str(tmp_path / "out"), route="r")
  assert [s["seg"] for s in info["segments"]] == ["0", "1"] and all("file" in s for s in info["segments"])
  z = np.load(tmp_path / "out" / "1" / "lat_pid_sim.npz")
  assert set(z.files) == set(se.KEYS)
  t = z["t"]
  assert len(t) == 300 and np.all(np.diff(t) > 0)
  assert t[0] < 0.01, "t is seconds from the segment's first carState, not the route's or the repeated initData's"
  assert np.all(z["active"] == 1) and np.allclose(z["cc_torque"], 0.2) and np.allclose(z["sr"], 15.3)
  assert np.all(z["v"] == 10.0) and np.all(np.isnan(z["co_torque"])) and np.all(np.isnan(z["yaw_curv"]))
  assert np.allclose(z["des_curv"], 0.001) and np.allclose(z["out"], 0.3)
  assert info["segments"][1]["rate_hz"] > 90
  assert json.loads((tmp_path / "out" / "export.json").read_text())["keys"] == list(se.KEYS)


def test_find_windows_labels_band_shape_and_presses():
  """John's P' labels: engaged no-press runs split by speed band and straight / curve, totals, and press runs."""
  t = np.arange(0.0, 20.0, 0.01)
  n = len(t)
  d = {k: np.zeros(n) for k in se.KEYS}
  d["t"], d["active"] = t, np.ones(n)
  d["v"] = np.where(t < 10.0, 27.0, 6.0)                   # 25+ then 5-8
  d["des_angle"] = np.where(t < 10.0, 2.0, 20.0)           # straight, then a curve
  d["des_angle"][(t >= 14.0) & (t < 15.0)] = 40.0          # past the curve band: other
  d["pressed"][(t >= 17.0) & (t < 18.0)] = 1.0             # a press: not engaged-no-press
  w, tot, pr = se.find_windows(d, "3")
  assert [(x["band"], x["shape"]) for x in w] == [("25+", "straight"), ("5-8", "curve"), ("5-8", "curve")]
  assert w[0]["s"] == 10.0 and w[0]["seg"] == "3" and w[1]["s"] == 4.0
  assert tot["25+"]["straight"] == 10.0 and round(tot["5-8"]["other"], 2) == 1.0
  assert abs(tot["5-8"]["curve"] - 8.0) < 0.02         # 10-14, 15-17 and 18-20 (the last frame has no dt)
  assert len(pr) == 1 and pr[0]["t_press"] == 17.0 and pr[0]["band"] == "5-8" and pr[0]["active_before"] is True
  assert abs(pr[0]["held_s"] - 1.0) < 0.02 and pr[0]["blinker"] is False
  d["lblink"][(t >= 14.5) & (t < 15.5)] = 1.0              # signalled 1.5 s before the press
  assert se.find_windows(d, "3")[2][0]["blinker"] is True
  d["lblink"][:] = 0.0
  d["lblink"][(t >= 14.0) & (t < 14.9)] = 1.0              # off 2.1 s before: not this press
  assert se.find_windows(d, "3")[2][0]["blinker"] is False
  assert se.band_of(4.9) is None and se.band_of(25.0) == "25+" and se.shape_of(-7.0) == "other"


def test_press_summary_counts_episodes_and_long_presses():
  """Kevin's rule: presses within 2 s of the last release are one episode; long presses are >= 0.3 s."""
  def p(seg, t0, held, band="16-25", active=True, blinker=False):
    return {"seg": seg, "t_press": t0, "t_release": t0 + held, "held_s": held, "band": band, "active_before": active,
            "blinker": blinker}
  presses = [p("1", 10.0, 0.05), p("1", 11.0, 0.5, blinker=True), p("1", 12.4, 0.1, blinker=True),  # one episode
             p("1", 20.0, 0.05),                                            # gap 7.6 s: a second episode
             p("2", 0.5, 0.4, band="25+"),                                  # new segment: new episode
             p("2", 30.0, 1.0, active=False)]                               # openpilot not steering: not counted
  s = se.press_summary(presses)
  assert [x["episode"] for x in presses] == [0, 0, 0, 1, 2, 3]
  assert s == {"16-25": {"presses": 4, "presses_long": 1, "episodes": 2, "episodes_blinker": 1},
               "25+": {"presses": 1, "presses_long": 1, "episodes": 1, "episodes_blinker": 0}}
