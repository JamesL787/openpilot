import math
from types import SimpleNamespace as NS

import numpy as np
import pytest

from openpilot.selfdrive.locationd.lateral_timing import (BandLearner, AimLearner, Streams, TimingLearner, find_turns,
                                                           frame_aims, size_correction, slow_composite, ema_delay,
                                                           FREEZE_TURNS, MONITOR_TURNS, AIM_FREEZE_FRAMES, T_IDXS)
from openpilot.selfdrive.locationd.lateral_timingd import LateralTimingRunner, model_key

RAMP, CMD, TW, WY = 0.04, 0.12, 0.06, 0.05
V = 7.0
HOLD = 0.025
RATIO = 15.0 * 2.7 * 180 / math.pi   # deg of wheel per 1/m of curvature on the synthetic car


def conv(angle, v, roll):
  return np.asarray(angle, float) / RATIO


def curvature(t):
  """Smooth turns: a 4 s raised-cosine bump of 0.035 1/m every 12 s, alternating left and right."""
  k = np.zeros_like(t)
  for i, t0 in enumerate(np.arange(10.0, t[-1] - 10, 12.0)):
    m = (t >= t0) & (t < t0 + 4.0)
    k[m] = (-1) ** i * 0.035 * 0.5 * (1 - np.cos(2 * np.pi * (t[m] - t0) / 4.0))
  return k


def drive(duration=200.0, t_start=1000.0):
  """Message rows for a synthetic drive with known stage lags, as (which, t, msg) in time order."""
  rows = []
  tc = t_start + np.arange(0, duration, 0.01)
  tm = t_start + np.arange(0, duration, 0.05)
  k = lambda t: curvature(t - t_start)
  for t, a in zip(tm, k(tm)):
    row = [a * V] * 33
    rows.append(("modelV2", t, NS(timestampEof=int((t - 0.05) * 1e9), action=NS(desiredCurvature=float(a)),
                                  orientation=NS(z=[a * V * T for T in T_IDXS]), orientationRate=NS(z=row), velocity=NS(x=[V] * 33))))
  # the car side is continuous (controlsd ramps the action across each frame); the published action is held
  C = k(tc - RAMP)
  tgt = k(tc - RAMP - CMD) * RATIO
  ang = k(tc - RAMP - CMD - TW) * RATIO
  yaw = k(tc - RAMP - CMD - TW - WY) * V
  for i, t in enumerate(tc):
    rows.append(("carState", t, NS(vEgo=V, steeringAngleDeg=float(ang[i]), steeringPressed=False, yawRate=float(yaw[i]))))
    rows.append(("carControl", t, NS(latActive=True)))
    rows.append(("controlsState", t, NS(desiredCurvature=float(C[i]), lateralControlState=NS(
      which=lambda: "pidState", pidState=NS(steeringAngleDesiredDeg=float(tgt[i]))))))
    if i % 5 == 0:
      rows.append(("starpilotLateralState", t, NS(epsCalibration="test", epsModelDelay=0.19, epsCommandDelay=CMD)))
  rows.sort(key=lambda r: r[1])
  return rows


def run(rows, step_every=None, state=None, drive_id="d1"):
  logs = []
  r = LateralTimingRunner(conv, 0.1, {"car": "synthetic"}, state, log=lambda e, **kw: logs.append((e, kw)), drive=drive_id)
  last = None
  for which, t, msg in rows:
    r.handle(which, t, msg)
    if step_every is not None and which == "carState":
      r.step(t)
    last = t
  r.step(last + 10.0, force=True)   # flush: everything is final
  return r, logs


class TestTurnSearch:
  def test_stage_lags_recovered(self):
    r, _ = run(drive())
    assert len(r.turns) >= 10
    med = {k: np.median([t[k] for t in r.turns if t[k] is not None]) for k in ("ramp", "cmd", "tw", "wy", "ay")}
    # the held 20 Hz action leads the continuous car side by half a frame (25 ms); the yaw is read 2 ms early
    assert med["ramp"] == pytest.approx(RAMP - HOLD, abs=0.006)
    assert med["cmd"] == pytest.approx(CMD, abs=0.006)
    assert med["tw"] == pytest.approx(TW, abs=0.006)
    assert med["wy"] == pytest.approx(WY - 0.002, abs=0.006)
    assert med["ay"] == pytest.approx(RAMP - HOLD + CMD + TW + WY - 0.002, abs=0.008)
    assert all(t["cmd_applied"] == pytest.approx(CMD) and t["told"] == pytest.approx(0.19 + 0.075) for t in r.turns)

  def test_streaming_matches_one_batch(self):
    rows = drive()
    batch, _ = run(rows)
    stream, _ = run(rows, step_every=True)
    assert len(stream.turns) == len(batch.turns)
    for a, b in zip(batch.turns, stream.turns):
      assert b["t0"] == pytest.approx(a["t0"], abs=0.011)
      for k in ("ramp", "tw", "wy", "ay"):
        assert b[k] == pytest.approx(a[k], abs=0.002)

  def test_pressed_and_disengaged_windows_skipped(self):
    rows = drive()
    pressed = [(w, t, NS(**{**vars(m), "steeringPressed": True}) if w == "carState" else m) for w, t, m in rows]
    assert run(pressed)[0].turns == []
    off = [(w, t, NS(latActive=False)) if w == "carControl" else (w, t, m) for w, t, m in rows]
    assert run(off)[0].turns == []

  def test_out_of_speed_gate_skipped(self):
    rows = [(w, t, NS(**{**vars(m), "vEgo": 20.0}) if w == "carState" else m) for w, t, m in drive()]
    assert run(rows)[0].turns == []


class TestSlowComposite:
  def test_size_correction_sign(self):
    assert size_correction(30.0) == 0.0
    assert size_correction(30.0 * math.e) == pytest.approx(0.020)    # sharper turns read early, so they are moved later
    assert size_correction(30.0 / math.e) == pytest.approx(-0.020)

  def test_needs_all_three_stages(self):
    rec = dict(ramp=0.04, tw=0.06, wy=0.05, tgt_rate=30.0)
    assert slow_composite(rec) == pytest.approx(0.15)
    assert slow_composite({**rec, "tw": None}) is None

  def test_ema_delay(self):
    assert ema_delay(0.1) == pytest.approx(0.077, abs=0.001)
    assert ema_delay(0.0) == 0.0


class TestBandLearner:
  def test_freezes_only_with_enough_turns_and_drives(self):
    b = BandLearner()
    rng = np.random.default_rng(0)
    for i in range(FREEZE_TURNS + 20):
      assert b.add(0.15 + rng.normal(0, 0.03), f"d{i % 2}") is None   # two drives never freeze
    b = BandLearner()
    events = [b.add(0.15 + rng.normal(0, 0.03), f"d{i % 3}") for i in range(FREEZE_TURNS)]
    assert events[-1] == "frozen" and events.count("frozen") == 1
    assert b.frozen["value"] == pytest.approx(0.15, abs=0.015)

  def test_split_halves_must_agree(self):
    b = BandLearner()
    for i in range(FREEZE_TURNS + 10):   # alternate turns 40 ms apart: the halves disagree
      assert b.add(0.13 if i % 2 else 0.17, f"d{i % 3}") is None

  def test_frozen_value_does_not_move_and_drift_is_flagged(self):
    b = BandLearner()
    for i in range(FREEZE_TURNS):
      b.add(0.15, f"d{i % 3}")
    assert b.state == "frozen"
    for i in range(MONITOR_TURNS):
      assert b.add(0.165, "d4") is None      # 15 ms off: noise, kept
    assert b.frozen["value"] == pytest.approx(0.15)
    events = [b.add(0.20, "d5") for _ in range(MONITOR_TURNS)]
    assert events.count("stale") == 1 and b.state == "learning" and b.stale_count == 1
    assert len(b.turns) == MONITOR_TURNS - 1 - events.index("stale")   # learning starts over from the next turn


class TestTimingLearner:
  def test_car_change_resets_bands_but_keeps_model_aims(self):
    t = TimingLearner({"calibration": "a"})
    for i in range(FREEZE_TURNS):
      t.add_turn(dict(v=7.0, ramp=0.04, tw=0.06, wy=0.05, tgt_rate=30.0), f"d{i % 3}")
    t.add_aims("m1", [0.30] * AIM_FREEZE_FRAMES)
    d = t.to_dict()
    same = TimingLearner({"calibration": "a"}, d)
    assert same.bands["5-9"].state == "frozen" and same.reset_reason is None
    other = TimingLearner({"calibration": "b"}, d)
    assert other.bands["5-9"].state == "learning" and other.reset_reason == "changed: calibration"
    assert other.aims["m1"].frozen == pytest.approx(0.30)

  def test_estimate_sets_the_two_knobs(self):
    t = TimingLearner({})
    for i in range(FREEZE_TURNS):
      t.add_turn(dict(v=7.0, ramp=0.04, tw=0.06, wy=0.05, tgt_rate=30.0), f"d{i % 3}")
    t.add_aims("m1", [0.30] * AIM_FREEZE_FRAMES)
    e = t.estimate("m1", "actionHead", 0.033, 0.1, {"5-9": 0.265})
    band = e["bands"]["5-9"]
    delivery = 0.033 + ema_delay(0.1) + 0.15 + 0.002
    assert band["delivery"] == pytest.approx(delivery)
    assert band["plan_told"] == pytest.approx(delivery)
    assert band["head_cmd_delay"] == pytest.approx(0.30 + 0.55 * 0.265 - delivery)
    assert "delivery" not in e["bands"]["9-15"]


class TestAims:
  def test_frame_aim_finds_the_matching_horizon(self):
    # a plan whose curvature ramps up with horizon: the implied curvature 2 psi(T)/(vT) = 0.01 * T crosses 0.004 at T=0.4
    v, n = 7.0, 3
    yaws = np.array([[0.5 * 0.01 * v * T * T for T in T_IDXS]] * n)
    rates = np.zeros((n, 33))
    act = np.full(n, 0.004)
    aim = frame_aims(np.arange(n) * 0.05, act, yaws, rates, np.full((n, 33), v), np.full(n, v), np.ones(n, bool), 0.0)
    assert aim[1] == pytest.approx(0.4, abs=0.01)

  def test_aim_freezes(self):
    a = AimLearner()
    assert not a.add([0.3] * (AIM_FREEZE_FRAMES - 1))
    assert a.add([0.3])
    assert a.estimate()["offset"] == pytest.approx(0.3)


class TestRunner:
  def test_learns_across_drives_and_persists(self):
    state, saved = None, {}
    for d in range(3):
      r, logs = run(drive(duration=260.0, t_start=1000.0 + 1000 * d), state=state, drive_id=f"d{d}")
      state = r.learner.to_dict()
    assert r.learner.drives == 3
    assert any(e == "lateralTiming.turn" for e, _ in logs)
    est = r.estimate()["bands"]["5-9"]
    assert est["n"] > 0 and est["drives"] == 3
    size = np.median([size_correction(t["tgt_rate"]) for t in r.turns])
    assert est["running"] == pytest.approx(RAMP - HOLD + TW + size + WY - 0.002, abs=0.008)

  def test_model_key(self):
    raw = '{"msg":{"event":"modeld.loaded","modelId":"cinque","artifactSha256":"abcdef0123456789ff"}}'
    assert model_key(raw) == "cinque:abcdef012345"
    assert model_key('{"msg":{"event":"modeld.identity-unavailable"}}') is None
    assert model_key("not json") is None
    assert model_key('{"msg":"free text"}') is None


def test_rack_converter_matches_rack_map():
  pytest.importorskip("opendbc")
  from openpilot.selfdrive.controls.lib.honda_eps_rack_map import HondaEpsRackMap
  from openpilot.selfdrive.controls.lib.honda_eps_calibrations import CLARITY_TRW_A020
  from openpilot.selfdrive.locationd.lateral_timingd import rack_converter
  from opendbc.car.honda.steer_ratio import get_honda_vgr_inverse
  from opendbc.car.honda.values import HondaFlags
  inv = next(get_honda_vgr_inverse(f) for f in HondaFlags if get_honda_vgr_inverse(f) is not None)
  rack = HondaEpsRackMap(2.75, inv, CLARITY_TRW_A020.rack)
  conv = rack_converter(rack)
  ang = np.array([-500.0, -120.0, -3.0, 0.0, 2.0, 45.0, 300.0, 600.0])
  v = np.full(len(ang), 8.0)
  roll = np.full(len(ang), 0.03)
  assert conv(ang, v, roll) == pytest.approx([rack.curvature_from_angle(a, 8.0, 0.03) for a in ang], rel=1e-9, abs=1e-12)
