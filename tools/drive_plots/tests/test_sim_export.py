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
