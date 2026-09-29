"""drive_plots: the analysis must recover properties planted in synthetic drives, score only engaged
samples, and the recorder must write, stop, auto-stop and recover sessions."""
import gzip
import json

import numpy as np
import pytest

from cereal import car, custom, log

import starpilot.system.the_galaxy.drive_plots as dp
import starpilot.system.the_galaxy.drive_plots_agents as agents

DT = 0.05


def _drive(n_s=120.0, lat_lag=0.0, lat_gain=1.0, lat_bias=0.0, wobble_hz=None, wobble_amp=0.0,
           long_lag=0.0, long_gain=1.0, lat_active=True, long_active=True, v=25.0):
  t = np.arange(0.0, n_s, DT)
  n = len(t)
  lat_des = 1.2 * np.sin(2 * np.pi * t / 15.0)            # slow curves, +-1.2 m/s^2
  lat_des[(t % 30) > 20] = 0.0                            # and some straights
  long_des = 0.8 * np.sin(2 * np.pi * t / 20.0)
  k_lat, k_long = int(round(lat_lag / DT)), int(round(long_lag / DT))
  lat_act = lat_gain * np.concatenate([np.full(k_lat, lat_des[0]), lat_des[:n - k_lat]]) + lat_bias
  if wobble_hz:
    lat_act = lat_act + wobble_amp * np.sin(2 * np.pi * wobble_hz * t)
  long_act = long_gain * np.concatenate([np.full(k_long, long_des[0]), long_des[:n - k_long]])
  rows = np.zeros((n, len(dp.COLUMNS)))
  c = dp.COL
  for name in dp.NAN_COLUMNS:   # like a recording made before these signals were logged
    rows[:, c[name]] = np.nan
  rows[:, c["t"]] = 1000.0 + t
  rows[:, c["v"]] = v
  rows[:, c["a_ego"]] = long_act
  rows[:, c["enabled"]] = 1
  rows[:, c["lat_active"]] = int(lat_active)
  rows[:, c["long_active"]] = int(long_active)
  rows[:, c["lat_des"]] = lat_des
  rows[:, c["lat_act"]] = lat_act
  rows[:, c["long_des"]] = long_des
  rows[:, c["long_act"]] = long_act
  rows[:, c["long_state"]] = dp.LONG_STATES["pid"]
  return rows


def test_perfect_tracking():
  a = dp.analyze(_drive())
  assert a["lateral"]["status"] == "ok" and a["longitudinal"]["status"] == "ok"
  assert a["lateral"]["rmse"] < 0.01 and a["longitudinal"]["rmse"] < 0.01
  assert abs(a["lateral"]["curve_gain"] - 1.0) < 0.01
  assert "closely" in a["lateral"]["summary"] and "closely" in a["longitudinal"]["summary"]


def test_lag_is_recovered_and_aligned_error_is_small():
  a = dp.analyze(_drive(lat_lag=0.3, long_lag=0.6))
  assert a["lateral"]["lag_s"] == pytest.approx(0.3, abs=0.051)
  assert a["longitudinal"]["lag_s"] == pytest.approx(0.6, abs=0.051)
  assert a["lateral"]["rmse"] < 0.02 < a["lateral"]["rmse_no_lag"]


def test_under_turning_is_reported():
  a = dp.analyze(_drive(lat_gain=0.7))
  assert a["lateral"]["curve_gain"] == pytest.approx(0.7, abs=0.03)
  assert any("less than asked" in n for n in a["lateral"]["notes"])


def test_drift_direction():
  a = dp.analyze(_drive(lat_bias=-0.1))
  assert a["lateral"]["straight_bias"] == pytest.approx(-0.1, abs=0.01)
  assert any("to the right" in n for n in a["lateral"]["notes"])


def test_oscillation_is_flagged_and_clean_drive_is_not():
  assert not any("ping-pong" in n for n in dp.analyze(_drive())["lateral"]["notes"])
  a = dp.analyze(_drive(wobble_hz=2.0, wobble_amp=0.3))
  assert a["lateral"]["wobble_ratio"] > dp.WOBBLE_RATIO_HIGH
  assert any("ping-pong" in n for n in a["lateral"]["notes"])


def test_braking_less_than_asked():
  a = dp.analyze(_drive(long_gain=0.6))
  assert a["longitudinal"]["brake_bias"] > dp.LONG_BIAS_NOTABLE
  assert any("slowed" in n and "less than planned" in n for n in a["longitudinal"]["notes"])
  assert "delivered less than asked" in a["longitudinal"]["summary"]


def test_disengaged_driving_is_not_scored():
  rows = _drive(lat_gain=0.2, long_gain=0.2, lat_active=False, long_active=False)
  a = dp.analyze(rows)
  assert a["lateral"]["status"] == "insufficient" and a["longitudinal"]["status"] == "insufficient"


def test_steering_touch_and_gas_press_are_excluded():
  rows = _drive()
  c = dp.COL
  bad = slice(0, len(rows) // 2)
  rows[bad, c["lat_act"]] += 3.0
  rows[bad, c["long_act"]] += 3.0
  rows[bad, c["steer_pressed"]] = 1
  rows[bad, c["gas_pressed"]] = 1
  a = dp.analyze(rows)
  assert a["lateral"]["rmse"] < 0.01 and a["longitudinal"]["rmse"] < 0.01
  assert a["lateral"]["steer_overrides"] == 0  # pressed from the first sample: no rising edge
  assert a["longitudinal"]["gas_overrides"] == 0


def test_lag_pairs_do_not_cross_a_gap():
  rows = _drive(n_s=60.0)
  rows[len(rows) // 2:, dp.COL["t"]] += 100.0
  assert len(set(dp._segments(rows[:, 0]))) == 2
  assert dp.analyze(rows)["lateral"]["status"] == "ok"


def test_overview_and_window_shapes():
  rows = _drive(n_s=300.0)
  o = dp.overview(rows, buckets=100)
  assert len(o["t"]) == 100 and len(o["lat_des"]) == 100
  w = dp.window(rows, 10.0, 20.0)
  assert w[0][0] == pytest.approx(10.0, abs=DT) and w[-1][0] == pytest.approx(20.0, abs=DT)


# ------------------------------- recorder -------------------------------

class _FakeSM:
  def __init__(self):
    self.frame = 0
    self.cs = log.ControlsState.new_message()
    self.cc = car.CarControl.new_message()
    self.car_state = car.CarState.new_message()
    self.plan = log.LongitudinalPlan.new_message()
    self.radar = log.RadarState.new_message()
    self.car_output = car.CarOutput.new_message()
    self.model = log.ModelDataV2.new_message()
    self.selfdrive = log.SelfdriveState.new_message()
    self.sp_plan = custom.StarPilotPlan.new_message()
    self.sp_lat = custom.StarPilotLateralState.new_message()
    self.live_params = log.LiveParametersData.new_message()
    self.live_delay = log.LiveDelayData.new_message()
    self.sp_car = custom.StarPilotCarState.new_message()
    self.sp_radar = custom.StarPilotRadarState.new_message()
    self.recv_frame = {s: 0 for s in dp.DrivePlots.SERVICES}
    self.updated = {s: False for s in dp.DrivePlots.SERVICES}
    self.logMonoTime = {s: 0 for s in dp.DrivePlots.SERVICES}

  def update(self, timeout=0):
    self.frame += 1
    for s in self.recv_frame:
      self.recv_frame[s] = self.frame
      self.updated[s] = True
      self.logMonoTime[s] = int((100.0 + self.frame * DT) * 1e9)

  def __getitem__(self, name):
    return {"controlsState": self.cs, "carControl": self.cc, "carState": self.car_state,
            "longitudinalPlan": self.plan, "radarState": self.radar, "carOutput": self.car_output, "modelV2": self.model,
            "selfdriveState": self.selfdrive, "starpilotPlan": self.sp_plan, "starpilotLateralState": self.sp_lat,
            "liveParameters": self.live_params, "liveDelay": self.live_delay, "starpilotCarState": self.sp_car,
            "starpilotRadarState": self.sp_radar}[name]


def _engaged_sm():
  sm = _FakeSM()
  sm.cc.enabled = sm.cc.latActive = sm.cc.longActive = True
  sm.car_state.vEgo = 20.0
  sm.car_state.aEgo = -0.5
  sm.plan.aTarget = -0.7
  sm.cs.desiredCurvature = 0.002
  sm.cs.curvature = 0.0019
  sm.cs.longControlState = "pid"
  return sm


def test_csv_values_round_trip_from_numpy_and_bool():
  assert [dp._fmt(x) for x in (np.float64(1.5), np.float32(0.25), True, np.int64(3), 2)] == ["1.5", "0.25", "1", "3", "2"]


def test_build_row_reads_the_right_fields():
  sm = _engaged_sm()
  sm.update()
  r = dict(zip(dp.COLUMNS, dp.build_row(sm)))
  assert r["lat_active"] == 1 and r["long_active"] == 1 and r["enabled"] == 1
  assert r["lat_des"] == pytest.approx(0.002 * 400) and r["lat_act"] == pytest.approx(0.0019 * 400)
  assert r["long_des"] == pytest.approx(-0.7) and r["long_act"] == pytest.approx(-0.5)
  assert r["long_state"] == dp.LONG_STATES["pid"]
  assert r["ang_ok"] == 0 and r["lead_src"] == 0


def test_build_row_reads_wheel_angle_and_car_ahead():
  sm = _engaged_sm()
  pid = sm.cs.lateralControlState.init("pidState")
  pid.steeringAngleDesiredDeg = 12.5
  sm.car_state.steeringAngleDeg = 11.0
  sm.radar.leadOne.status = True
  sm.radar.leadOne.dRel = 35.0
  sm.radar.leadOne.vLead = 18.0
  sm.radar.leadOne.radar = True
  sm.update()
  r = dict(zip(dp.COLUMNS, dp.build_row(sm)))
  assert r["ang_ok"] == 1 and r["ang_des"] == pytest.approx(12.5) and r["ang_act"] == pytest.approx(11.0)
  assert r["lead_d"] == pytest.approx(35.0) and r["lead_v"] == pytest.approx(18.0) and r["lead_src"] == 1
  sm.radar.leadOne.radar = False
  assert dict(zip(dp.COLUMNS, dp.build_row(sm)))["lead_src"] == 2
  sm.radar.leadOne.status = False
  assert dict(zip(dp.COLUMNS, dp.build_row(sm)))["lead_src"] == 0


def test_record_stop_analyze(tmp_path):
  plots = dp.DrivePlots(tmp_path, is_onroad=lambda: True, submaster_factory=lambda s: None)
  plots._ensure_thread_locked = lambda: None
  status = plots.start_recording({"car": "HONDA_TEST"})
  sm = _engaged_sm()
  for _ in range(40):
    plots.step(sm)
  assert plots.live()["recording"]["rows"] == 40
  plots.stop_recording(background=False)
  d = tmp_path / status["id"]
  meta = json.loads((d / "meta.json").read_text())
  assert meta["status"] == "done" and meta["car"] == "HONDA_TEST"
  assert meta["started_at"] <= meta["first_sample_at"] <= meta["stopped_at"]
  assert (d / "samples.csv.gz").exists() and not (d / "samples.csv").exists()
  assert len(gzip.open(d / "samples.csv.gz", "rt").read().strip().splitlines()) == 41
  assert plots.get_session(status["id"])["analysis"]["samples"] == 40
  assert [s["id"] for s in plots.list_sessions()] == [status["id"]]
  assert plots.delete_session(status["id"]) and not d.exists()


def test_autostop_when_drive_ends(tmp_path):
  now = [0.0]
  onroad = [True]
  plots = dp.DrivePlots(tmp_path, is_onroad=lambda: onroad[0], clock=lambda: now[0])
  plots._ensure_thread_locked = lambda: None
  status = plots.start_recording()
  sm = _engaged_sm()
  for _ in range(5):
    plots.step(sm)
  plots._check_autostop(now[0])
  onroad[0] = False
  now[0] = 1.0
  plots._check_autostop(now[0])
  assert plots.rec is not None
  now[0] = 1.0 + dp.OFFROAD_AUTOSTOP_S
  plots._check_autostop(now[0])
  assert plots.rec is None
  plots.thread = None
  import time
  for _ in range(50):
    if json.loads((tmp_path / status["id"] / "meta.json").read_text())["status"] != "analyzing":
      break
    time.sleep(0.05)
  meta = json.loads((tmp_path / status["id"] / "meta.json").read_text())
  assert meta["stop_reason"] == "drive ended" and meta["status"] == "done"


def test_start_while_offroad_does_not_autostop_before_the_drive(tmp_path):
  now = [0.0]
  plots = dp.DrivePlots(tmp_path, is_onroad=lambda: False, clock=lambda: now[0])
  plots._ensure_thread_locked = lambda: None
  plots.start_recording()
  now[0] = 10 * dp.OFFROAD_AUTOSTOP_S
  plots._check_autostop(now[0])
  assert plots.rec is not None
  plots.stop_recording(background=False)


def test_interrupted_session_is_recovered_from_a_torn_file(tmp_path):
  d = tmp_path / "20260926120000"
  d.mkdir()
  (d / "meta.json").write_text(json.dumps({"id": d.name, "status": "recording"}))
  lines = [",".join(dp.COLUMNS)] + [",".join(["1"] * len(dp.COLUMNS))] * 5 + ["1,2,3"]
  (d / "samples.csv").write_text("\n".join(lines))
  plots = dp.DrivePlots(tmp_path, is_onroad=lambda: False)
  plots.recover_interrupted()
  meta = json.loads((d / "meta.json").read_text())
  assert meta["status"] == "done" and "interrupted" in meta["stop_reason"]
  assert plots.get_session(d.name)["analysis"]["samples"] == 5


def test_session_id_cannot_escape_the_root(tmp_path):
  plots = dp.DrivePlots(tmp_path, is_onroad=lambda: False)
  with pytest.raises(ValueError):
    plots.get_session("../etc")


# ------------------------------- endpoints -------------------------------

def test_endpoints_round_trip(monkeypatch, tmp_path):
  from pathlib import Path
  import starpilot.system.the_galaxy.the_galaxy as server
  assert server._import_galaxy_web_symbols()
  module_dir = Path(server.__file__).resolve().parent

  class _Params:
    def get_bool(self, key):
      return key == "IsOnroad"

    def get(self, key, *a, **k):
      return {"GitCommit": b"abc123", "SteerKP": b"0.6"}.get(key)

  plots = dp.DrivePlots(tmp_path, is_onroad=lambda: True)
  plots._ensure_thread_locked = lambda: None
  monkeypatch.setattr(server, "params", _Params())
  monkeypatch.setattr(server, "_safe_params_get_live_raw", lambda key: None)
  monkeypatch.setattr(server, "_drive_plots", plots)
  app = server.Flask("drive_plots_test", template_folder=str(module_dir / "templates"),
                     static_folder=str(module_dir / "assets"))
  server.setup(app)
  client = app.test_client()

  started = client.post("/api/plots/recording/start").get_json()["recording"]
  sm = _engaged_sm()
  for _ in range(30):
    plots.step(sm)
  live = client.get("/api/plots/live?since=25").get_json()
  assert [r[0] for r in live["rows"]] == [26, 27, 28, 29, 30]
  assert live["recording"]["id"] == started["id"] and live["isOnroad"] is True
  assert live["columns"][1:] == dp.COLUMNS

  monkeypatch.setattr(plots, "stop_recording",
                      lambda reason="stopped", background=True, _orig=plots.stop_recording: _orig(reason, background=False))
  stopped = client.post("/api/plots/recording/stop").get_json()["stopped"]
  assert stopped["rows"] == 30

  session = client.get(f"/api/plots/sessions/{started['id']}").get_json()
  assert session["meta"]["status"] == "done"
  assert session["meta"]["git_commit"] == "abc123" and session["meta"]["tune"]["SteerKP"] == "0.6"
  assert "overview" in session["analysis"] and session["analysis"]["lateral"]["summary"]
  assert client.get("/api/plots/sessions").get_json()["sessions"][0]["id"] == started["id"]
  win = client.get(f"/api/plots/sessions/{started['id']}/window?start=0&end=0.5").get_json()
  assert len(win["rows"]) == 11
  dl = client.get(f"/api/plots/sessions/{started['id']}/download")
  assert dl.status_code == 200 and gzip.decompress(dl.data).startswith(b"t,v,")
  dl.close()
  assert client.get("/api/plots/sessions/..%2Fx").status_code in (400, 404)
  assert client.delete(f"/api/plots/sessions/{started['id']}").status_code == 200
  assert client.get(f"/api/plots/sessions/{started['id']}").status_code == 404


def test_speed_bands_report_gain_per_band():
  # Under-turning only above 50 mph (22.35 m/s): two bands, gains differ, and the note says so.
  rows = _drive(n_s=240.0, v=18.0)
  fast = np.zeros(len(rows), dtype=bool)
  fast[len(rows) // 2:] = True
  rows[fast, dp.COL["v"]] = 27.0
  rows[fast, dp.COL["lat_act"]] *= 0.75
  lat = dp.analyze(rows)["lateral"]
  bands = {b["name"]: b for b in lat["speed_bands"]}
  assert set(bands) == {"Standard", "Highway"}
  assert bands["Standard"]["lo_ms"] == pytest.approx(11.18) and bands["Highway"]["hi_ms"] is None
  assert bands["Standard"]["gain"] == pytest.approx(1.0, abs=0.03)
  assert bands["Highway"]["gain"] == pytest.approx(0.75, abs=0.03)
  assert any("By speed" in n and "Standard (25-50 mph) 100%" in n and "Highway (50+ mph) 75%" in n for n in lat["notes"])
  assert any("changes with speed" in x for x in dp.analyze(rows)["takeaways"])
  pid = [x for x in dp.analyze(rows, controller=dp.CONTROLLER_NRDR_PID)["takeaways"] if "changes with speed" in x]
  assert pid and "Low speed / Standard / Highway sliders" in pid[0]
  eps = [x for x in dp.analyze(rows, controller=dp.CONTROLLER_CLARITY_EPS)["takeaways"] if "changes with speed" in x]
  assert eps and "no per-speed sliders" in eps[0]
  assert dp.analyze(rows)["longitudinal"]["speed_bands"][0]["engaged_s"] > 100


def test_saturation_in_curves_is_reported():
  rows = _drive(n_s=120.0)
  curve = np.abs(rows[:, dp.COL["lat_des"]]) > dp.LAT_CURVE_DEMAND
  rows[curve, dp.COL["lat_sat"]] = 1
  lat = dp.analyze(rows)["lateral"]
  assert lat["saturated_curve_frac"] == pytest.approx(1.0, abs=0.02)
  assert any("at its limit" in n for n in lat["notes"])
  assert dp.analyze(_drive(n_s=120.0))["lateral"]["saturated_curve_frac"] == 0.0


def test_read_rows_by_header_tolerates_older_column_sets(tmp_path):
  new_cols = {"lat_sat", "ang_des", "ang_act", "ang_ok", "lead_d", "lead_v", "lead_src"}
  old = [c for c in dp.COLUMNS if c not in new_cols]
  rows = _drive(n_s=5.0)
  lines = [",".join(old)] + [",".join(dp._fmt(r[dp.COL[c]]) for c in old) for r in rows]
  (tmp_path / "samples.csv").write_text("\n".join(lines) + "\n")
  data = dp.read_rows(tmp_path)
  assert data.shape == (len(rows), len(dp.COLUMNS))
  assert np.all(data[:, dp.COL["lat_sat"]] == 0) and np.allclose(data[:, dp.COL["lat_des"]], rows[:, dp.COL["lat_des"]])
  assert np.all(data[:, dp.COL["ang_ok"]] == 0)


def test_a_zoom_reads_only_its_window_and_matches_the_whole_drive_read(tmp_path):
  # A zoom used to parse the whole drive per tap (~110 MB for 20 min); it now keeps only the window's rows.
  root, tmp_path = tmp_path, tmp_path / "20260928110259"
  tmp_path.mkdir()
  rows = _drive(n_s=120.0)
  lines = [",".join(dp.COLUMNS)] + [",".join(dp._fmt(x) for x in r) for r in rows]
  lines.insert(500, "1,2,3")                                   # a short line
  lines.insert(900, ",".join(["x"] * len(dp.COLUMNS)))         # an unparsable one
  with gzip.open(tmp_path / "samples.csv.gz", "wt") as f:
    f.write("\n".join(lines) + "\n" + ",".join(["1"] * 5))   # and a torn last line
  full = dp.read_rows(tmp_path)
  assert full.shape == rows.shape and np.allclose(full, rows, equal_nan=True)
  for start, end in ((0.0, 10.0), (40.0, 100.0), (110.0, 200.0), (500.0, 560.0)):
    part, t0 = dp.read_rows(tmp_path, start, end)
    assert t0 == full[0, 0] and len(part) < len(full)
    assert dp.window(part, start, end, t0=t0) == dp.window(full, start, end)
  plots = dp.DrivePlots(root, is_onroad=lambda: False)
  assert plots.get_window(tmp_path.name, 40.0, 100.0)["rows"] == dp.window(full, 40.0, 100.0)


def test_whole_drive_analysis_waits_until_the_car_is_parked(tmp_path):
  onroad = [True, True, True]
  plots = dp.DrivePlots(tmp_path, is_onroad=lambda: bool(onroad) and onroad.pop(0))
  slept, done = [], []
  plots._sleep = slept.append
  plots.finalize = done.append
  plots.prune_auto_sessions = lambda: None
  plots._finalize_and_prune(tmp_path / "x", wait_until_parked=True)
  assert len(slept) == 3 and done == [tmp_path / "x"]

def test_malloc_helpers_never_raise():
  dp.limit_malloc_arenas(2)
  dp.release_freed_memory()

def test_old_recording_without_angles_or_lead_still_analyzes():
  a = dp.analyze(_drive())
  assert "turns" not in a["lateral"] and a["lateral"]["curve_gain_source"] == "lateral acceleration"
  assert all(e["kind"] != "turn_overshoot" for e in a["events"])


def test_empty_recording_is_discarded(tmp_path):
  plots = dp.DrivePlots(tmp_path, is_onroad=lambda: False, submaster_factory=lambda s: None)
  plots._ensure_thread_locked = lambda: None
  status = plots.start_recording({"car": "HONDA_TEST"})
  stopped = plots.stop_recording(background=False)
  assert stopped["discarded"] is True and stopped["rows"] == 0
  assert not (tmp_path / status["id"]).exists() and plots.list_sessions() == []


# ------------------------------- wheel angle, tight turns, moments -------------------------------

def _with_angles(rows, gain=1.0, ratio=15.0):
  """Wheel angles consistent with the lateral accel columns: angle = ratio * wheelbase-ish * curvature."""
  c = dp.COL
  v = np.maximum(rows[:, c["v"]], 1.0)
  rows[:, c["ang_des"]] = rows[:, c["lat_des"]] / v ** 2 * 2.7 * ratio * 57.3
  rows[:, c["ang_act"]] = gain * rows[:, c["ang_des"]]
  rows[:, c["ang_ok"]] = 1
  return rows


def test_curve_response_uses_wheel_angle_when_recorded():
  # Lateral accel says 70% (a steer-ratio bias in "measured"), the wheel angle says 100%: angle wins.
  rows = _with_angles(_drive(lat_gain=0.7), gain=1.0)
  lat = dp.analyze(rows)["lateral"]
  assert lat["curve_gain_source"] == "wheel angle"
  assert lat["curve_gain"] == pytest.approx(1.0, abs=0.02)
  rows = _with_angles(_drive(), gain=0.8)
  lat = dp.analyze(rows)["lateral"]
  assert lat["curve_gain"] == pytest.approx(0.8, abs=0.02)
  assert all(b["gain"] == pytest.approx(0.8, abs=0.03) for b in lat["speed_bands"])


def _tight_turn_drive(overshoot_deg=0.0, v=4.5, n_turns=3):
  """Straight 20 mph cruising with n 90-degree turns at v; the wheel unwinds overshoot_deg late."""
  rows = _drive(n_s=120.0, v=9.0)
  c = dp.COL
  rows[:, c["lat_des"]] = 0.0
  rows[:, c["lat_act"]] = 0.0
  rows[:, c["ang_ok"]] = 1
  t = rows[:, c["t"]] - rows[0, c["t"]]
  des = np.zeros(len(t))
  for k in range(n_turns):
    t0 = 20.0 + 30.0 * k
    ph = (t - t0) / 6.0
    inside = (ph >= 0) & (ph <= 1)
    des[inside] = 90.0 * np.sin(np.pi * ph[inside])
    rows[inside, c["v"]] = v
  act = des.copy()
  if overshoot_deg:
    act += overshoot_deg * (des > 45.0)
  rows[:, c["ang_des"]] = des
  rows[:, c["ang_act"]] = act
  return rows


def test_tight_turns_are_scored_in_degrees():
  a = dp.analyze(_tight_turn_drive(overshoot_deg=0.0))
  turns = a["lateral"]["turns"]
  assert turns["count"] == 3 and [b["label"] for b in turns["bins"]] == ["under 12 mph"]
  assert turns["bins"][0]["err"] == pytest.approx(0.0, abs=0.01) and turns["overshoots"] == []
  assert not any("past the request" in x for x in a["takeaways"])
  a = dp.analyze(_tight_turn_drive(overshoot_deg=12.0), controller=dp.CONTROLLER_NRDR_PID)
  turns = a["lateral"]["turns"]
  assert turns["bins"][0]["past"] == pytest.approx(12.0, abs=0.1) and turns["bins"][0]["trail"] == 0.0
  assert len(turns["overshoots"]) == 3 and turns["overshoots"][0]["side"] == "left"
  assert any("past the request" in x for x in a["takeaways"])
  kinds = [e["kind"] for e in a["events"]]
  assert kinds.count("turn_overshoot") == 3
  assert any("Tight turns" in n for n in a["lateral"]["notes"])


def test_turns_at_higher_speed_land_in_the_second_bin():
  turns = dp.analyze(_tight_turn_drive(v=8.0))["lateral"]["turns"]
  assert [b["label"] for b in turns["bins"]] == ["12-25 mph"]


def test_wheel_wobble_is_measured_on_straights():
  rows = _tight_turn_drive(n_turns=0)
  clean = dp.analyze(rows)["lateral"]["turns"]["wobble"]
  t = rows[:, dp.COL["t"]]
  rows[:, dp.COL["ang_act"]] += 1.0 * np.sin(2 * np.pi * 1.5 * t)
  shaky = dp.analyze(rows)["lateral"]["turns"]["wobble"]
  assert [b["lo_ms"] for b in clean] == [8.0] and clean[0]["rms_deg"] < 0.05
  assert shaky[0]["rms_deg"] > 0.4


def test_hard_brake_and_overridden_braking_are_moments_with_the_car_ahead():
  rows = _drive(n_s=120.0)
  c = dp.COL
  t = rows[:, c["t"]] - rows[0, c["t"]]
  rows[:, c["lead_src"]] = 1
  rows[:, c["lead_d"]] = 30.0
  rows[:, c["lead_v"]] = 20.0
  brake = (t >= 40.0) & (t < 42.0)
  rows[brake, c["long_des"]] = -3.0
  rows[brake, c["long_act"]] = -3.0
  plan = (t >= 80.0) & (t < 82.0)
  rows[plan, c["long_des"]] = -1.5
  gas = (t >= 81.0) & (t < 81.5)
  rows[gas, c["gas_pressed"]] = 1
  rows[(t >= 60.0) & (t < 60.3), c["steer_pressed"]] = 1
  a = dp.analyze(rows)
  ev = {e["kind"]: e for e in a["events"]}
  assert ev["hard_brake"]["t"] == pytest.approx(40.0, abs=0.06) and ev["hard_brake"]["lead"]["src"] == "radar"
  assert ev["hard_brake"]["a_min"] == pytest.approx(-3.0) and ev["hard_brake"]["gas_after"] is False
  assert ev["gas_during_brake"]["t"] == pytest.approx(81.0, abs=0.06)
  lead = ev["gas_during_brake"]["lead"]
  assert {k: lead[k] for k in ("d", "v", "src")} == {"d": 30.0, "v": 20.0, "src": "radar"}
  assert all(lead.get(k) is None for k in ("track_id", "vrel", "a", "prob")), "not recorded is None, not 0"
  assert ev["steer_takeover"]["t"] == pytest.approx(60.0, abs=0.06)
  assert [e["t"] for e in a["events"]] == sorted(e["t"] for e in a["events"])
  assert a["longitudinal"]["gas_during_brake"] == 1
  assert a["takeaways"][0].startswith("You overrode openpilot's braking 1 time")


def test_event_starts_merge_close_crossings():
  m = np.zeros(200, dtype=bool)
  m[10:12] = m[20:22] = m[150:152] = True
  assert agents._starts(m, np.arange(200) * 0.05, 3.0) == [10, 150]


def test_advice_names_the_controller_that_drove():
  rows = _drive(wobble_hz=2.0, wobble_amp=0.3)
  pid = dp.analyze(rows, controller=dp.CONTROLLER_NRDR_PID)
  eps = dp.analyze(rows, controller=dp.CONTROLLER_CLARITY_EPS)
  assert pid["controller"] == dp.CONTROLLER_NRDR_PID
  assert any("LatP slider" in x for x in pid["takeaways"])
  assert any("James's controller" in x and "LatP" in x for x in eps["takeaways"])
  under = dp.analyze(_drive(lat_gain=0.7), controller=dp.CONTROLLER_NRDR_PID)
  assert any("LatF (feedforward) slider" in x for x in under["takeaways"])


def test_finalize_reads_the_controller_from_meta(tmp_path):
  plots = dp.DrivePlots(tmp_path, is_onroad=lambda: True, submaster_factory=lambda s: None)
  plots._ensure_thread_locked = lambda: None
  status = plots.start_recording({"car": "HONDA_CIVIC_BOSCH", "lateral_controller": dp.CONTROLLER_CLARITY_EPS})
  sm = _engaged_sm()
  for _ in range(10):
    plots.step(sm)
  plots.stop_recording(background=False)
  assert plots.get_session(status["id"])["analysis"]["controller"] == dp.CONTROLLER_CLARITY_EPS


def test_live_analysis_carries_the_controller(tmp_path):
  plots = dp.DrivePlots(tmp_path, is_onroad=lambda: True, submaster_factory=lambda s: None,
                        controller_fn=lambda: dp.CONTROLLER_NRDR_PID)
  plots._ensure_thread_locked = lambda: None
  sm = _engaged_sm()
  for _ in range(5):
    plots.step(sm)
  assert plots.live()["liveAnalysis"]["controller"] == dp.CONTROLLER_NRDR_PID


# ------------------------- signals the lat / long agents asked for -------------------------

def test_build_row_reads_agent_signals_and_nan_when_never_received():
  sm = _engaged_sm()
  sm.car_state.steeringTorque = -700.0
  sm.car_state.leftBlinker = True
  sm.cc.actuators.torque = 0.4
  sm.cc.actuators.accel = -1.2
  sm.car_output.actuatorsOutput.torque = 0.1
  pid = sm.cs.lateralControlState.init("pidState")
  pid.angleError, pid.output, pid.active = 1.5, 0.3, True
  sm.sp_lat.epsFfActive, sm.sp_lat.epsFfWeight, sm.sp_lat.epsFfFeedforward = True, 0.5, 0.2
  ll = sm.model.init("laneLines", 4)
  for line, y in zip(ll, (-5.4, -1.6, 2.0, 5.6), strict=True):
    line.y = [y]
  sm.model.laneLineProbs = [0.1, 0.9, 0.7, 0.1]
  sm.sp_plan.tFollow, sm.sp_plan.trackingLead = 1.45, True
  sm.selfdrive.experimentalMode = True
  sm.radar.leadOne.status = True
  sm.radar.leadOne.radarTrackId = 17
  sm.radar.leadOne.vRelRangeDerived = -0.8
  sm.radar.leadTwo.status = True
  sm.radar.leadTwo.dRel = 60.0
  sm.update()
  r = dict(zip(dp.COLUMNS, dp.build_row(sm), strict=True))
  assert r["steer_tq"] == -700.0 and r["blinker"] == 1
  assert r["tq_req"] == pytest.approx(0.4) and r["tq_out"] == pytest.approx(0.1) and r["a_cmd"] == pytest.approx(-1.2)
  assert r["ang_err"] == pytest.approx(1.5) and r["lat_out"] == pytest.approx(0.3) and r["pid_active"] == 1
  assert r["ff_active"] == 1 and r["ff_w"] == pytest.approx(0.5) and r["ff"] == pytest.approx(0.2)
  # model y is + = right: lines at -1.6 / +2.0 put the lane centre 0.2 m right, so the car is 0.2 m LEFT of it.
  assert r["lane_off"] == pytest.approx(0.2) and r["lane_w"] == pytest.approx(3.6) and r["lane_prob"] == pytest.approx(0.7)
  assert r["lane_prob_l"] == pytest.approx(0.9) and r["lane_prob_r"] == pytest.approx(0.7)
  assert r["t_follow"] == pytest.approx(1.45) and r["tracking_lead"] == 1 and r["exp_mode"] == 1
  assert r["lead_id"] == 17 and r["lead_vrr"] == pytest.approx(-0.8) and r["lead2_on"] == 1 and r["lead2_d"] == 60.0
  fresh = _engaged_sm()
  fresh.recv_frame = {s: 0 for s in fresh.recv_frame}
  fresh.recv_frame["longitudinalPlan"] = fresh.recv_frame["controlsState"] = 1
  row = dict(zip(dp.COLUMNS, dp.build_row(fresh), strict=True))
  for name in ("tq_out", "ff", "lane_off", "t_follow", "exp_mode", "lead_id", "mlead_p", "tq_req"):
    assert np.isnan(row[name]), name


def test_nan_is_null_in_live_and_window(tmp_path):
  plots = dp.DrivePlots(tmp_path, is_onroad=lambda: True, submaster_factory=lambda s: None)
  plots._ensure_thread_locked = lambda: None
  fresh = _engaged_sm()
  fresh.update()
  fresh.recv_frame = {s: (1 if s in ("longitudinalPlan", "controlsState", "carState") else 0) for s in fresh.recv_frame}
  plots.step(fresh)
  live = plots.live()
  json.dumps(live, allow_nan=False)
  assert live["rows"][-1][1 + dp.COL["lane_off"]] is None
  assert all(x is None for x in dp.window(_drive(n_s=5.0), 0, 5)[0][dp.COL["steer_tq"]:])


def _takeover_drive():
  rows = _drive(n_s=90.0)
  c = dp.COL
  t = rows[:, c["t"]] - rows[0, c["t"]]
  for name in ("steer_tq", "ang_err", "lane_off", "blinker", "lead_id"):
    rows[:, c[name]] = 0.0
  rows[:, c["ang_ok"]] = 1
  rows[:, c["lane_w"]] = 3.6
  rows[:, c["lane_prob"]] = 0.9
  hold = (t >= 30.0) & (t < 32.0)
  rows[hold, c["steer_pressed"]] = 1
  rows[hold, c["steer_tq"]] = 900.0     # + = left
  # The push carries the car left 0.8 m/s from 0.1 m for 3 s, across the lane line at 1.8 m (the model then reports
  # the new lane's centre, 3.6 m over).
  pos = 0.1 + 0.8 * np.clip(t - 30.0, 0.0, 3.0)
  rows[:, c["lane_off"]] = np.where(pos > 1.8, pos - 3.6, pos)
  rows[:, c["long_des"]] = 0.0
  rows[(t >= 50.0) & (t < 52.0), c["long_des"]] = -3.0
  rows[:, c["lead_src"]], rows[:, c["lead_d"]], rows[:, c["lead_v"]], rows[:, c["lead_id"]] = 1, 30.0, 20.0, 4
  return rows


def test_takeover_episode_is_measured():
  a = dp.analyze(_takeover_drive())
  eps = a["driver_takeovers"]["episodes"]
  assert len(eps) == 1
  e = eps[0]
  assert e["t"] == pytest.approx(30.0, abs=0.06) and e["hold_s"] == pytest.approx(2.0, abs=0.4)
  assert e["tag"] == "long hold" and e["push"] == "left" and e["lanes_ok"] is True
  summary = a["driver_takeovers"]["summary"]
  assert summary["count"] == 1 and summary["drift_3s_measurable"] == "1 / 1"
  assert any(ev["kind"] == "steer_takeover" for ev in a["events"])
  # Position from the press lane's centre, carried across the lane change (raw lane_off at 33 s reads -1.1).
  assert e["lane_press_m"] == pytest.approx(0.1, abs=0.05)
  assert e["lane_release_m"] == pytest.approx(0.1 + 0.8 * (e["release_t"] - 30.0), abs=0.1)
  assert e["lane_press_3s_m"] == pytest.approx(2.5, abs=0.05)
  assert e["lateral_controller"] is None and e["git_commit"] is None
  tagged = dp.analyze(_takeover_drive(), controller=dp.CONTROLLER_CLARITY_EPS, git_commit="abc123")
  e = tagged["driver_takeovers"]["episodes"][0]
  assert e["lateral_controller"] == dp.CONTROLLER_CLARITY_EPS and e["git_commit"] == "abc123"


# ------------------------------- recording every drive -------------------------------

class _FakePub:
  def __init__(self):
    self.sent = []

  def send(self, service, payload):
    assert service == dp.RLOG_SERVICE
    self.sent.append(json.loads(payload))


def _auto_plots(tmp_path, onroad, now, pub=None):
  plots = dp.DrivePlots(tmp_path, is_onroad=lambda: onroad[0], clock=lambda: now[0],
                        meta_fn=lambda: {"car": "HONDA_TEST", "tune": {"NrdrX": "1"}}, route_fn=lambda: "abc--0123456789",
                        publisher_factory=(lambda: pub) if pub is not None else None)
  plots._ensure_thread_locked = lambda: None
  return plots


def test_auto_record_starts_with_the_drive_and_respects_a_manual_stop(tmp_path):
  onroad, now = [False], [0.0]
  plots = _auto_plots(tmp_path, onroad, now, _FakePub())
  plots.auto_tick()
  assert plots.rec is None
  onroad[0] = True
  plots.auto_tick()
  assert plots.rec is not None
  meta = json.loads((plots.rec["dir"] / "meta.json").read_text())
  assert meta["auto"] is True and meta["route"] == "abc--0123456789" and meta["car"] == "HONDA_TEST"
  plots.stop_recording(reason="stopped by user", background=False)
  plots.auto_tick()
  assert plots.rec is None, "a driver's stop holds for the rest of this drive"
  onroad[0] = False
  plots.auto_tick()
  onroad[0] = True
  plots.auto_tick()
  assert plots.rec is not None, "and the next drive records again"
  plots.stop_recording(background=False)
  plots.set_settings({"auto_record": False, "bogus": 1})
  assert plots.settings() == {"auto_record": False, "publish_to_log": True}
  onroad[0] = False
  plots.auto_tick()
  onroad[0] = True
  plots.auto_tick()
  assert plots.rec is None


def test_rlog_copy_has_start_moments_takeovers_and_summary(tmp_path):
  onroad, now = [True], [0.0]
  pub = _FakePub()
  plots = _auto_plots(tmp_path, onroad, now, pub)
  plots.auto_tick()
  rows = _takeover_drive()
  rec = plots.rec
  plots.buffer = type(plots.buffer)(maxlen=len(rows))
  for i, row in enumerate(rows.tolist()):
    plots.buffer.append((i + 1, row))
  rec["first_t"], rec["last_t"], rec["rows"] = rows[0, 0], rows[-1, 0], len(rows)
  now[0] = dp.PUBLISH_SCAN_S
  plots.auto_tick()
  now[0] = 2 * dp.PUBLISH_SCAN_S
  plots.auto_tick()   # a second scan over the same window publishes nothing new
  now[0] = dp.SUMMARY_EVERY_S + 1
  plots.auto_tick()
  kinds = [m["type"] for m in pub.sent]
  assert kinds[0] == "start" and all(m["schema"] == dp.RLOG_SCHEMA and "mono_ns" in m for m in pub.sent)
  start = pub.sent[0]
  assert start["route"] == "abc--0123456789" and start["tune"] == {"NrdrX": "1"} and start["columns"] == dp.COLUMNS
  moments = [m for m in pub.sent if m["type"] == "moment"]
  takeovers = [m for m in pub.sent if m["type"] == "takeover"]
  assert [m["kind"] for m in moments] == ["hard_brake", "atarget_step"]   # the brake is a step in aTarget
  assert moments[0]["mono_s"] == pytest.approx(rows[0, 0] + 50.0, abs=0.06) and moments[0]["t"] == pytest.approx(50.0, abs=0.1)
  assert len(takeovers) == 1 and takeovers[0]["push"] == "left"
  assert {"lateral_controller", "git_commit", "lane_press_3s_m"} <= set(takeovers[0])
  summary = [m for m in pub.sent if m["type"] == "summary"][-1]
  assert summary["counts"] == {"hard_brake": 1, "atarget_step": 1, "takeover": 1} and "lateral" in summary
  plots.stop_recording(reason="drive ended", background=False)
  assert pub.sent[-1]["type"] == "end" and pub.sent[-1]["reason"] == "drive ended"


def test_prune_keeps_manual_sessions_and_the_newest_auto_ones(tmp_path, monkeypatch):
  monkeypatch.setattr(dp, "AUTO_KEEP_SESSIONS", 2)
  plots = dp.DrivePlots(tmp_path, is_onroad=lambda: False)
  for i in range(4):
    d = tmp_path / f"a{i}"
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({"id": d.name, "auto": True, "status": "done", "started_at": i}))
  (tmp_path / "manual").mkdir()
  (tmp_path / "manual" / "meta.json").write_text(json.dumps({"id": "manual", "status": "done", "started_at": -1}))
  assert sorted(plots.prune_auto_sessions()) == ["a0", "a1"]
  assert sorted(p.name for p in tmp_path.iterdir()) == ["a2", "a3", "manual"]


def test_lead_moments_are_gated_the_way_radar_work_asked():
  """Bob, route 28f: next-lane and far leads, sub-second flicker and radar<->camera handoffs were read as close
  appear / vanish and track swaps."""
  t = np.arange(0.0, 45.0, 0.05)
  n = len(t)
  z = np.zeros(n)
  c = {"t": t, "v": np.full(n, 20.0), "long_des": z.copy(), "long_act": z.copy(), "long_active": np.ones(n),
       "gas_pressed": z.copy(), "enabled": np.ones(n), "brake_pressed": z.copy(), "exp_mode": np.ones(n),
       "lead_src": z.copy(), "lead_d": z.copy(), "lead_v": np.full(n, 18.0), "lead_y": z.copy(),
       "lead_id": np.full(n, -1.0)}

  def lead(a, b, d, y=0.0, src=2, tid=-1.0):
    k = (t >= a) & (t < b)
    c["lead_src"][k], c["lead_d"][k], c["lead_y"][k], c["lead_id"][k] = src, d, y, tid

  lead(5.0, 10.0, 20.0, y=4.0)         # next lane: nothing
  lead(12.0, 20.0, 20.0)               # appears close, then vanishes close at 20 s
  lead(25.0, 25.3, 15.0)               # 0.3 s blink: one lead_flicker
  lead(30.0, 45.0, 60.0, src=1, tid=3)   # far radar lead: no appear
  lead(32.0, 45.0, 45.0, src=1, tid=3)   # 15 m drop while far: lead_jump
  lead(34.0, 45.0, 45.0, src=1, tid=7)   # radar to radar at the same distance: track_id_swap
  lead(36.0, 38.0, 45.0, src=2, tid=-1)  # to the camera: radar_lost; back to radar id 9 at 38 s: radar_acquired
  lead(38.0, 45.0, 45.0, src=1, tid=9)
  ms = agents.long_moments(c)
  got = [(m["kind"], m["t"]) for m in ms]
  assert got == [("lead_appeared_close", 12.0), ("lead_vanished_close", 20.0), ("lead_flicker", 25.0),
                 ("lead_jump", 32.0), ("track_id_swap", 34.0), ("radar_lost", 36.0), ("radar_acquired", 38.0)], got
  assert all(m["experimental_active"] is True and "experimental" not in m for m in ms)


def test_takeover_lane_numbers_need_both_lines_through_the_window():
  # James (route 293): a faint line during the hold jumped and read as 1 m of drift.
  rows = _takeover_drive()
  t = rows[:, dp.COL["t"]] - rows[0, dp.COL["t"]]
  rows[(t >= 30.4) & (t < 31.5), dp.COL["lane_prob"]] = 0.1
  e = dp.analyze(rows)["driver_takeovers"]["episodes"][0]
  assert e["lanes_ok"] is False and e["lane_prob_min"] == pytest.approx(0.1) and e["lane_ok_frac"] < 0.9
  rows[:, dp.COL["blinker"]] = 0
  summary = dp.analyze(rows)["driver_takeovers"]["summary"]
  assert summary["drift_3s_measurable"] == "0 / 1" and summary["median_drift_3s_m"] is None
  assert e["drift_1s_m"] is None and e["drift_3s_m"] is None and e["drift_6s_m"] is None
  assert e["lane_press_m"] is not None and e["lane_release_m"] is None and e["lane_press_3s_m"] is None
  # Faint only after release + 3 s: the 1 s and 3 s drift stand, the 6 s one does not.
  rows = _takeover_drive()
  rel = dp.analyze(rows)["driver_takeovers"]["episodes"][0]["release_t"]
  rows[(t >= rel + 4.0) & (t < rel + 4.8), dp.COL["lane_prob"]] = 0.1
  e = dp.analyze(rows)["driver_takeovers"]["episodes"][0]
  assert e["lanes_ok"] is True and e["drift_3s_m"] is not None and e["drift_6s_m"] is None
  # A one-frame dropout (a merge or a gore) no longer throws the window away.
  rows = _takeover_drive()
  rows[np.flatnonzero(t >= 31.0)[0], dp.COL["lane_prob"]] = 0.0
  e = dp.analyze(rows)["driver_takeovers"]["episodes"][0]
  assert e["lanes_ok"] is True and e["lane_prob_min"] == 0.0 and e["drift_6s_m"] is not None


def test_lane_curve_toward_inside_is_positive_left_of_centre_in_a_left_curve():
  # lat_des + = right (as openpilot's desiredCurvature), lane_off + = car left of centre.
  rows = _drive(v=20.0)
  c = dp.COL
  rows[:, c["lat_des"]] = -1.0                  # a steady left curve (ang_des > 0)
  rows[:, c["lat_act"]] = -1.0
  rows[:, c["lane_prob"]] = 0.9
  rows[:, c["lane_w"]] = 3.6
  rows[:, c["lane_off"]] = 0.2                  # car 20 cm left: toward the inside
  row = agents.lateral_detail(dp._as_arrays(rows))["bands"][0]
  assert row["lane_curve_toward_inside"]["median"] > 0.15
  rows[:, c["lat_des"]] = rows[:, c["lat_act"]] = 1.0   # the same offset in a right curve is toward the outside
  row = agents.lateral_detail(dp._as_arrays(rows))["bands"][0]
  assert row["lane_curve_toward_inside"]["median"] < -0.15

def test_a_light_hold_without_steering_pressed_is_not_the_controllers_turn():
  # James (route 293): steeringPressed flickers off in a light hold; the torque still shows the driver steering.
  rows = _tight_turn_drive(overshoot_deg=12.0)
  t = rows[:, dp.COL["t"]] - rows[0, dp.COL["t"]]
  rows[:, dp.COL["steer_tq"]] = 0.0
  rows[(t >= 19.0) & (t < 27.0), dp.COL["steer_tq"]] = 900.0
  a = dp.analyze(rows)
  overs = a["lateral"]["turns"]["overshoots"]
  assert len(overs) == 2 and all("mono_s" in x for x in overs)
  tight = a["lateral_detail"]["tight_turns"]
  assert tight["count"] == 2 and all(0.0 <= x["held_frac"] < 0.5 for x in tight["turns"])


def test_request_columns_read_the_right_fields():
  sm = _engaged_sm()
  r = dict(zip(dp.COLUMNS, dp.build_row(sm)))
  # Nothing received yet: every added column is NaN (not recorded), never 0.
  assert all(r[k] != r[k] for k in ("ang_off", "lat_delay", "gl_gf", "adj_l", "red_light", "ff_r5"))
  sm.car_state.steerFaultTemporary, sm.car_state.vCruise = True, 105.0
  sm.cc.orientationNED = [0.0, -0.03, 0.0]
  sm.sp_lat.epsFfR5, sm.sp_lat.epsFfLoad, sm.sp_lat.epsFfDesiredRate = 120.0, 80.0, 14.0
  sm.live_params.angleOffsetDeg, sm.live_params.roll = 0.4, 0.02
  sm.live_delay.lateralDelay = 0.21
  sm.plan.longitudinalPlanSource = "lead0"
  sm.plan.allowThrottle, sm.plan.closeLeadBrakeCap, sm.plan.leadGeometryRequiredAccel = True, -1.2, -0.8
  sm.radar.leadOne.status, sm.radar.leadOne.dPath, sm.radar.leadOne.aLeadTau = True, 0.3, 1.5
  sm.sp_plan.redLight, sm.sp_plan.roadCurvature, sm.sp_plan.approachStopLength = True, 0.004, 42.0
  sm.sp_car.gasLearnerAvailable, sm.sp_car.gasLearnerGasFactor, sm.sp_car.gasLearnerWindFactor = True, 1.1, 0.95
  sm.sp_car.gasLearnerError, sm.sp_car.gasLearnerLearning = 0.05, True
  sm.sp_radar.leadLeft.status, sm.sp_radar.adjacentStopped.status = True, True
  sm.update()
  r = dict(zip(dp.COLUMNS, dp.build_row(sm)))
  assert (r["fault_t"], r["fault_p"], r["v_cruise"], r["pitch"]) == (1, 0, 105.0, -0.03)
  assert (r["des_curv"], r["curv"]) == (2.0, 1.9)
  assert (r["ff_r5"], r["ff_load"], r["ff_rate"]) == (120.0, 80.0, 14.0)
  assert (r["ang_off"], r["roll"], r["lat_delay"]) == (0.4, 0.02, 0.21)
  assert (r["plan_src"], r["allow_thr"], r["allow_brk"], r["cl_cap"], r["geo_acc"]) == (1, 1, 0, -1.2, -0.8)
  assert (r["lead_dpath"], r["lead_tau"]) == (0.3, 1.5)
  assert (r["red_light"], r["forcing_stop"], r["road_curv"], r["stop_len"]) == (1, 0, 0.004, 42.0)
  sm.sp_car.gasLearnerGasFactorRaw = 1.6
  sm.update()
  r = dict(zip(dp.COLUMNS, dp.build_row(sm)))
  assert (r["gl_gf"], r["gl_wf"], r["gl_err"], r["gl_learn"], r["gl_gf_raw"]) == (1.1, 0.95, 0.05, 1, 1.6)
  assert (r["adj_l"], r["adj_r"], r["adj_stop"]) == (1, 0, 1)


def test_takeover_turn_fight_numbers():
  """Kevin's per-episode numbers on a slow-turn fight: a fault flicker and a target re-seed during the press, a
  wheel 25 deg short of the plan at release, a 0.6 /s takeback, and a second grab re-pressed 0.5 s after release."""
  rows = _takeover_drive()
  c = dp._as_arrays(rows)
  t = c["t"] - c["t"][0]
  c["lat_active"][:] = 1
  c["fault_t"] = np.where(((t >= 30.5) & (t < 30.7)) | ((t >= 31.2) & (t < 31.3)), 1.0, 0.0)
  c["ang_des"] = np.where(t < 31.0, 40.0, 140.0)
  c["ang_act"] = c["ang_des"] - 25.0
  near = (t >= 31.5) & (t < 32.0)
  c["steer_tq"][near], c["steer_pressed"][near] = 1600.0, 0.0
  c["lat_out"] = np.where(t < 32.0, 0.2, np.minimum(0.8, 0.2 + 0.6 * (t - 32.0)))
  c["lat_i"] = np.where((t >= 31.0) & (t < 31.05), -0.3, 0.1)
  for a, b in ((60.0, 61.0), (61.5, 61.7)):   # released at 61.0, re-pressed 0.5 s later
    m = (t >= a) & (t < b)
    c["steer_pressed"][m], c["steer_tq"][m] = 1.0, 900.0
  eps = agents.takeovers(c)["episodes"]
  assert [round(e["t"], 1) for e in eps] == [30.0, 60.0, 61.5]
  e = eps[0]
  assert e["turn"] is True and e["release_gap_deg"] == pytest.approx(25.0)
  assert e["lat_out_release"] == pytest.approx(0.2) and e["takeback_rate_peak"] == pytest.approx(0.6, abs=0.05)
  assert e["t90_s"] == pytest.approx(0.9, abs=0.06)
  assert e["fault_flicker_n"] == 2 and e["fault_flicker_ms"] == pytest.approx(300, abs=60)
  assert e["ang_des_step_max_dps"] == pytest.approx(2000, rel=0.1)
  assert e["i_press"] == pytest.approx(0.1) and e["i_press_min"] == pytest.approx(-0.3)
  assert e["near_cut_s"] == pytest.approx(0.5, abs=0.06) and e["override_cut_s"] == pytest.approx(1.5, abs=0.06)
  assert e["repress"] is False and e["repress_after_s"] is None
  assert eps[1]["repress"] is True and eps[1]["repress_after_s"] == pytest.approx(0.5, abs=0.06)
  assert eps[1]["t90_s"] is None   # pressed again before lat_out settled
  s = agents.takeovers(c)["summary"]
  assert (s["repress"], s["repress_late"], s["fault_flicker"], s["near_cut"]) == (1, 0, 1, 1)


def _blank(seconds=120.0, hz=20.0):
  t = np.arange(0.0, seconds, 1.0 / hz) + 1000.0
  c = {k: np.full(len(t), np.nan) for k in dp.COLUMNS}
  c["t"] = t
  return c, t - t[0]


def test_bob_moments():
  """Bob's 2026-09-29 moments, one of each on a synthetic 20 Hz drive, and none where the column is missing."""
  c, t = _blank()
  c["v"][:], c["long_active"][:], c["long_des"][:], c["lead_src"][:], c["lead_d"][:] = 25.0, 1, 0.0, 0, 0.0
  c["exp_mode"][:] = 0.0
  c["exp_mode"][(t >= 5.0) & (t < 5.5)] = 1.0          # on at 5.0, off 0.5 s later: a flip-flop at 5.0
  c["exp_mode"][[400, 402]] = 1.0                        # on/off every frame (0.05 s) from 20.0 ...
  c["exp_mode"][404:500] = 1.0                           # ... ending on at 20.2: 5 flips, then off at 25.0
  c["red_light"][:] = 0.0
  c["red_light"][(t >= 10.0) & (t < 12.0)] = 1.0        # the car stays at 25 m/s: false red light at 10
  c["road_curv"][:] = 0.002
  c["long_des"][(t >= 30.0) & (t < 31.0)] = 0.8         # +0.8 step at 30, -0.8 step at 31
  c["cl_cap"][:] = 0.0
  c["cl_cap"][(t >= 40.0) & (t < 42.0)] = -1.2
  radar = (t >= 50.0) & (t < 70.0)
  c["lead_src"][radar], c["lead_d"][radar], c["lead_meas"][radar] = 1, 30.0, 1.0
  c["lead_vrel"][radar], c["lead_vrr"][radar] = -1.0, -1.0
  c["lead_meas"][(t >= 52.0) & (t < 53.0)] = 0.0        # coasting 1 s at 30 m
  c["lead_meas"][(t >= 55.0) & (t < 55.3)] = 0.0        # 0.3 s: too short
  c["lead_vrr"][(t >= 58.0) & (t < 59.0)] = 1.0         # vRel off by 2 m/s for 1 s
  c["mlead_p"][radar], c["mlead_x"][radar] = 0.9, 30.0
  c["mlead_x"][(t >= 62.0) & (t < 64.0)] = 40.0         # model 10 m further for 2 s
  c["v_cruise"][:] = 90.0                               # km/h: 25 m/s set
  c["v"][(t >= 80.0) & (t < 85.0)] = 26.0               # 1 m/s over for 5 s with no lead
  c["pitch"][:], c["gl_gf"][:] = -0.03, 1.4
  c["gl_gf_raw"][:] = 1.2
  c["gl_gf_raw"][(t >= 90.0) & (t < 100.0)] = 1.6
  c["gl_gf_raw"][(t >= 95.0) & (t < 95.5)] = 1.58      # dips under for 0.5 s: still the same clip
  m = agents.long_moments(c)
  got = {}
  for e in m:
    got.setdefault(e["kind"], []).append(e)
  assert [e["t"] for e in got["exp_flipflop"]] == [5.0, 20.0]
  f = got["exp_flipflop"]
  assert f[0]["flips"] == 2 and f[0]["burst_s"] == pytest.approx(0.5) and f[0]["road_curv"] == 0.002
  assert f[1]["flips"] == 5 and f[1]["experimental_after"] is True   # one moment for a burst of quick flips
  assert [e["t"] for e in got["false_red_light"]] == [10.0] and got["false_red_light"][0]["v_min_10s"] == 25.0
  assert [e["t"] for e in got["atarget_step"]] == [30.0, 31.0] and got["atarget_step"][1]["a_after"] == 0.0
  assert [e["t"] for e in got["close_lead_cap"]] == [40.0] and got["close_lead_cap"][0]["cl_cap"] == -1.2
  assert [e["t"] for e in got["radar_coast_near"]] == [52.0]
  assert got["radar_coast_near"][0]["coast_s"] == pytest.approx(1.0)
  assert [e["t"] for e in got["vrel_disagree"]] == [58.0] and got["vrel_disagree"][0]["gap_max"] == 2.0
  assert [e["t"] for e in got["radar_vs_model"]] == [62.0] and got["radar_vs_model"][0]["d_gap_max"] == 10.0
  over = got["overspeed_no_lead"]
  assert [e["t"] for e in over] == [80.0] and over[0]["for_s"] == pytest.approx(5.0) and over[0]["pitch"] == -0.03
  assert [e["t"] for e in got["gf_clip"]] == [90.0]
  # A car that stopped for the light is not a false red light, and an unset set speed (255) never overspeeds.
  c["v"][(t >= 15.0) & (t < 16.0)] = 1.0
  c["v_cruise"][:] = 255.0
  kinds = [e["kind"] for e in agents.long_moments(c)]
  assert "false_red_light" not in kinds and "overspeed_no_lead" not in kinds
  # Older recordings without these columns give none of them.
  for k in ("exp_mode", "red_light", "cl_cap", "lead_meas", "lead_vrr", "mlead_x", "v_cruise", "gl_gf_raw"):
    c[k][:] = np.nan
  assert not {e["kind"] for e in agents.long_moments(c)} & {"exp_flipflop", "false_red_light", "close_lead_cap",
                                                            "radar_coast_near", "vrel_disagree", "radar_vs_model",
                                                            "overspeed_no_lead", "gf_clip"}


def test_james_lateral_moments():
  c, t = _blank()
  c["v"][:], c["lat_active"][:], c["steer_pressed"][:], c["steer_tq"][:] = 5.0, 1, 0, 0.0
  c["fault_t"][:], c["fault_p"][:] = 0.0, 0.0
  c["fault_t"][(t >= 5.0) & (t < 5.2)] = 1.0            # a 0.2 s flicker while steering
  c["tq_out"][:] = 0.0
  c["steer_pressed"][(t >= 10.0) & (t < 12.0)] = 1.0    # release at 12, tq_out ramps 2 /s, re-pressed at 13
  c["tq_out"][(t >= 12.0) & (t < 12.2)] = 2.0 * (t[(t >= 12.0) & (t < 12.2)] - 12.0)
  c["tq_out"][(t >= 12.2) & (t < 20.0)] = 0.4
  c["steer_pressed"][(t >= 13.0) & (t < 14.0)] = 1.0
  hwy = t >= 30.0
  c["v"][hwy], c["lat_des"][hwy], c["ang_act"][hwy], c["lane_off"][hwy], c["lane_prob"][hwy] = 30.0, -0.8, 12.0, 0.0, 0.9
  c["lane_off"][(t >= 40.0) & (t < 43.0)] = 0.35        # left curve (angle +), car left of centre: inside by 0.35 m
  c["lane_off"][(t >= 50.0) & (t < 51.0)] = 0.35        # only 1 s: not a cut
  c["lane_off"][(t >= 55.0) & (t < 58.0)] = -0.35       # outside: not a cut
  straight = t >= 70.0
  c["lat_des"][straight], c["ang_act"][straight] = 0.1, 0.5
  c["ff"][straight], c["lat_p"][straight] = 0.02, 0.03
  c["tq_out"][hwy] = 0.0
  w = (t >= 80.0) & (t < 82.5)
  c["tq_out"][w] = 0.1 * np.sign(np.sin(2 * np.pi * 1.0 * (t[w] - 80.0) + 0.1))   # 1 Hz square wave: 4 flips in 2.5 s
  small = (t >= 100.0) & (t < 105.0)
  c["tq_out"][small] = 0.02 * np.sign(np.sin(2 * np.pi * 2.0 * (t[small] - 100.0) + 0.1))  # under the floor
  got = {}
  for e in agents.lat_moments(c):
    got.setdefault(e["kind"], []).append(e)
  assert [e["t"] for e in got["fault_flicker"]] == [5.0] and got["fault_flicker"][0]["fault_s"] == pytest.approx(0.2)
  assert [e["t"] for e in got["release_snap"]] == [12.0, 14.0]
  s = got["release_snap"][0]
  assert s["tq_out_rate_peak"] == pytest.approx(2.0, abs=0.3) and s["repress"] is True
  assert s["repress_after_s"] == pytest.approx(1.0)
  assert got["release_snap"][1]["repress"] is False
  cut = got["hwy_inside_cut"]
  assert [e["t"] for e in cut] == [40.0] and cut[0]["turn"] == "left" and cut[0]["inside_max_m"] == 0.35
  wig = got["hwy_wiggle"]
  assert len(wig) == 1 and 80.0 <= wig[0]["t"] < 81.0 and wig[0]["ff"] == 0.02 and wig[0]["lat_p"] == 0.03
  # The events list and the column-free case.
  assert {"fault_flicker", "hwy_inside_cut"} <= {e["kind"] for e in dp._events(c, 0.05, {})}
  c2, _ = _blank(10.0)
  c2["v"][:] = 30.0
  assert agents.lat_moments(c2) == []
