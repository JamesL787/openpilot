import json

from cereal import log

import openpilot.tools.drive_plots.rlog_report as rr


def _write_segment(path, t0_ns, n, with_init=True, marker=None, brake=True):
  events = []
  if with_init:
    ev = log.Event.new_message(logMonoTime=1_000_000_000)   # repeated in every segment with the route's first time
    ev.init("initData")
    ev.initData.gitCommit = "0" * 40
    ev.initData.gitBranch = "test"
    entries = ev.initData.params.init("entries", 2)
    entries[0].key, entries[0].value = "NrdrLatEpsFirmwareFF", b"1"
    entries[1].key, entries[1].value = "LaneCenterOffset", b"0.1"
    events.append(ev)
  for i in range(n):
    t = t0_ns + i * 50_000_000
    cs = log.Event.new_message(logMonoTime=t)
    cs.init("carState")
    cs.carState.vEgo = 20.0
    cs.carState.aEgo = -3.0 if brake and 100 <= i < 140 else 0.0
    ctl = log.Event.new_message(logMonoTime=t + 1_000_000)
    ctl.init("controlsState")
    cc = log.Event.new_message(logMonoTime=t + 1_000_000)
    cc.init("carControl")
    cc.carControl.enabled = cc.carControl.latActive = cc.carControl.longActive = True
    plan = log.Event.new_message(logMonoTime=t + 2_000_000)
    plan.init("longitudinalPlan")
    plan.longitudinalPlan.aTarget = -3.0 if brake and 100 <= i < 140 else 0.0
    events += [cs, ctl, cc, plan]
  if marker is not None:
    m = log.Event.new_message(logMonoTime=t0_ns + 5_000_000_000)
    m.customReservedRawData0 = json.dumps(marker).encode()
    events.append(m)
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_bytes(b"".join(e.to_bytes() for e in events))


def test_report_times_are_route_relative_and_car_messages_are_read(tmp_path):
  route = tmp_path / "route"
  _write_segment(route / "0" / "rlog", 2_000_000_000, 1200,
                 marker={"schema": rr.dp.RLOG_SCHEMA, "type": "moment", "kind": "hard_brake", "mono_s": 7.0})
  _write_segment(route / "1" / "rlog", 62_000_000_000, 400, brake=False)
  segs = rr.segments(str(route))
  rep, r = rr.report(segs, detect=False)
  assert len(r["rows"]) == 1600
  assert rep["tune"]["NrdrLatEpsFirmwareFF"] == "1" and rep["tune"]["LaneCenterOffset"] == "0.1"
  missing = [k for k in rr.agent_param_keys() if k != "NrdrLatEpsFirmwareFF"]
  assert missing and all(rep["tune"][k] == "missing" for k in missing)
  hard = [e for e in rep["analysis"]["events"] if e["kind"] == "hard_brake"]
  assert len(hard) == 1
  # The route starts at the initData time (1.0 s); the brake is at 2.0 + 100 * 0.05 = 7.0 s monotonic.
  assert hard[0]["route_s"] == 6.0 and hard[0]["seg"] == 0 and hard[0]["seg_mmss"] == "00:06.0"
  assert "t" not in hard[0]
  (msg,) = rep["car_messages"]
  assert msg["kind"] == "hard_brake" and msg["route_s"] == 6.0 and msg["logged_route_s"] == 6.0
  assert r["seg_starts"][1] == 62_000_000_000, "a segment starts at its first carState, not the repeated initData"
  rr.write(str(tmp_path / "out"), rep, r)
  assert json.loads((tmp_path / "out" / "report.json").read_text())["schema"] == "drivePlotsReport/1"
  assert (tmp_path / "out" / "samples.csv").read_text().splitlines()[0].startswith("seg,route_s,t,")
  win = (tmp_path / "out" / "moment_windows.csv").read_text().splitlines()
  assert win[0].startswith("moment,kind,rel_s,route_s,t,")
  brake = [x.split(",") for x in win[1:] if x.split(",")[1] == "hard_brake"]
  assert 80 <= len(brake) <= 81 and -2.0 <= float(brake[0][2]) < -1.9 and 1.9 < float(brake[-1][2]) <= 2.0   # +-2 s, 20 Hz
