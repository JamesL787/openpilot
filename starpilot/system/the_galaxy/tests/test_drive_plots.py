"""drive_plots: the analysis must recover properties planted in synthetic drives, score only engaged
samples, and the recorder must write, stop, auto-stop and recover sessions."""
import gzip
import json

import numpy as np
import pytest

from cereal import car, log

import starpilot.system.the_galaxy.drive_plots as dp

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
            "longitudinalPlan": self.plan, "radarState": self.radar}[name]


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
  assert ev["gas_during_brake"]["lead"] == {"d": 30.0, "v": 20.0, "src": "radar"}
  assert ev["steer_takeover"]["t"] == pytest.approx(60.0, abs=0.06)
  assert [e["t"] for e in a["events"]] == sorted(e["t"] for e in a["events"])
  assert a["longitudinal"]["gas_during_brake"] == 1
  assert a["takeaways"][0].startswith("You overrode openpilot's braking 1 time")


def test_event_starts_merge_close_crossings():
  m = np.zeros(200, dtype=bool)
  m[10:12] = m[20:22] = m[150:152] = True
  assert dp._event_starts(m, 0.05) == [10, 150]


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
