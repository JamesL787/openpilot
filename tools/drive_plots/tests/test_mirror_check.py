import json

import numpy as np
from cereal import log

import openpilot.tools.drive_plots.mirror_check as mc
from openpilot.tools.drive_plots.rlog_report import segments


def _write_route(path, n=1600, marker=None):
  """A synthetic drive at 100 Hz (plan at 20 Hz): straight, a lane change, then a long tight turn at 7 m/s with
  a grab in it and a lead ahead. controlsState is stamped 1 ms after the plan it precedes in the file, as rlogs do."""
  ev = []

  def add(t, which):
    e = log.Event.new_message(logMonoTime=int(t))
    e.init(which)
    ev.append(e)
    return getattr(e, which)

  add(1_000_000_000, "initData").gitCommit = "0" * 40
  cp = add(1_000_000_000, "carParams")
  cp.carFingerprint = "HONDA_CLARITY"
  for i in range(n):
    t = 2_000_000_000 + i * 10_000_000
    turn = i >= 700
    des = 90.0 * min(1.0, (i - 700) / 100) if turn else 2.0 * np.sin(i / 7)
    ang = des - (8.0 if turn else 0.3 * np.sin(i / 3))
    pressed = 1000 <= i < 1030
    lp = add(t, "liveParameters")
    lp.steerRatio, lp.stiffnessFactor = 15.3, 1.0
    cs = add(t + 1, "carState")
    cs.vEgo = 7.0 if turn else 10.0
    cs.steeringAngleDeg, cs.steeringRateDeg, cs.steeringPressed = float(ang), 5.0, pressed
    cc = add(t + 2, "carControl")
    cc.enabled = cc.latActive = cc.longActive = True
    cc.actuators.torque, cc.actuators.accel = 0.2, -0.1
    md = add(t + 3, "modelV2")
    md.meta.laneChangeState = "laneChangeStarting" if 300 <= i < 500 else "off"
    ll = md.init("laneLines", 4)
    for k, y in enumerate((-5.4, -1.9, 1.7, 5.2)):
      ll[k].y = [y, y]
    md.laneLineProbs = [0.5, 0.9, 0.8, 0.5]
    rs = add(t + 4, "radarState")
    rs.leadOne.status, rs.leadOne.radar, rs.leadOne.dRel, rs.leadOne.vLead = True, True, 25.0, 9.0
    rs.leadOne.radarTrackId = 7
    if i % 5 == 0:
      add(t + 5, "longitudinalPlan").aTarget = -0.1
    ctl = add(t + 6_000_000 if i % 5 == 0 else t + 5, "controlsState")
    ctl.desiredCurvature, ctl.curvature = 0.001, 0.0009
    ps = ctl.lateralControlState.init("pidState")
    ps.active, ps.steeringAngleDesiredDeg, ps.output = True, float(des), 0.3
  if marker is not None:
    m = log.Event.new_message(logMonoTime=int(2e9 + 15e9))
    m.customReservedRawData0 = json.dumps(marker).encode()
    ev.append(m)
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_bytes(b"".join(e.to_bytes() for e in ev))


def test_mirror_check_matches_rlog_fields_and_lat_score(tmp_path):
  _write_route(tmp_path / "r" / "0" / "rlog", marker={"schema": mc.dp.RLOG_SCHEMA, "type": "takeover", "mono_s": 12.0})
  res = mc.run(segments(str(tmp_path / "r")))
  assert res["rows"] > 300
  assert not {k: v for k, v in res["columns"].items() if v["mismatches"]}
  fr = res["frames"]
  # Lined up by message order, not logMonoTime (the controlsState here is stamped after the plan it follows).
  assert fr["ang_des"]["agree_frac"] == 1.0 and fr["pid_active"]["agree_frac"] == 1.0
  # A row holds the newest modelV2, lat_pid_sim the one before its controlsState: only the two edges differ.
  assert fr["lane_change"]["agree_frac"] > 0.99
  turn = {x["metric"]: x for x in res["lat_score"] if x["metric"].startswith("turn_err 12-25mph")}
  assert turn["turn_err 12-25mph"]["match"], turn
  assert res["car"]["car_messages"] == 1 and res["car"]["kinds"]["takeover"]["car"] == 1


def test_mirror_check_catches_a_column_reading_the_wrong_field(tmp_path, monkeypatch):
  _write_route(tmp_path / "r" / "0" / "rlog", n=400)
  real = mc.dp.build_row

  def wrong(sm):
    row = real(sm)
    row[mc.dp.COL["lead_d"]] = row[mc.dp.COL["lead_v"]]
    return row

  monkeypatch.setattr(mc.dp, "build_row", wrong)
  res = mc.run(segments(str(tmp_path / "r")))
  assert res["columns"]["lead_d"]["mismatches"] == res["rows"]
  assert sum(v["mismatches"] for v in res["columns"].values()) == res["rows"]
