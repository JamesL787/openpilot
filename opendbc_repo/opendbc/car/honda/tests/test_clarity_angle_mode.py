"""Clarity angle mode (clarity_angle_mode.py, eps_cal_status.py angle checks), with 0x6A4 layout-v3 frames the emulated
angle-mode EPS firmware transmitted (clarity_angle_mode_emulator_frames.json: rwd-xray CLARITY_ANGLE_MODE_20261117,
build 0x04 in sh2a_emu, closed loop with openpilot's angle frames)."""
import json
import os
import struct

import numpy as np
import pytest

from opendbc.can import CANParser
from opendbc.car import structs
from opendbc.car.honda import clarity_angle_mode as cam
from opendbc.car.honda.eps_cal_status import ANGLE_BUILDS, KNOWN_BUILDS
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.tests.test_clarity_mode_switch import honda_checksum_ok
from opendbc.car.honda.tests.test_eps_cal_status import Feed, honda_checksum
from opendbc.car.honda.tests.test_modified_eps import eps, params
from opendbc.car.honda.values import CAR, HondaFlags

ADDR = 0x6A4
FRAMES = json.load(open(os.path.join(os.path.dirname(__file__), "clarity_angle_mode_emulator_frames.json")))
MODIFIED = b'39990-TRW,A020\x00\x00'


def datas(name):
  return [bytes.fromhex(h) for _, h, _ in FRAMES[name]["frames"]]


def v3(active=3, requested=3, build=0x04, flags=0x18, ref=0, out=0, counter=0, running=True):
  b = bytearray([(requested << 4) | active | (8 if running else 0), build, flags]) + struct.pack(">hh", ref, out) + bytes([counter << 4])
  b[7] |= honda_checksum(bytes(b))
  return bytes(b)


ANGLE = [False]   # the HondaClarityAngleMode setting as card's startup hook would read it


@pytest.fixture
def angle_file():
  """Angle Mode setting on (name kept from the file era)."""
  ANGLE[0] = True
  yield
  ANGLE[0] = False


def clarity(fw=MODIFIED, candidate=CAR.HONDA_CLARITY):
  # card: CarParams from the interface, then the pre-create hook applies the setting, then the interface is built
  return CarInterface(cam.apply_angle_mode(params(candidate, [eps(fw)]), ANGLE[0]))


def ready(ci, n=8):
  """Feed mode-3 status frames until the interlock reports angle_ready."""
  f = Feed(ci)
  f.run([v3(counter=k % 4) for k in range(n)])
  assert ci.CS.eps_cal_status.angle_ready, ci.CS.eps_cal_status.fault
  return f


def e4(ci, lat, angle_des, measured, v=10.0, pressed=False, t=[2_000_000_000]):
  ci.CS.out = structs.CarState(vEgo=float(v), steeringAngleDeg=float(measured), steeringPressed=bool(pressed)).as_reader()
  cc = structs.CarControl(latActive=lat)
  cc.actuators.steeringAngleDeg = float(angle_des)
  t[0] += 10_000_000
  act, frames = ci.apply(cc.as_reader(), t[0])
  f = [bytes(x[1]) for x in frames if x[0] == 0xE4]
  assert len(f) == 1 and honda_checksum_ok(f[0])
  return act, f[0]


# --- 0x6A4 layout v3 decode, on the emulator's frames ---

def test_dbc_decodes_every_v3_emulator_frame():
  for name in FRAMES:
    cp = CANParser("honda_clarity_hybrid_2018_can_generated", [("EPS_CAL_STATUS", float("nan"))], 0)
    t = 1_000_000_000
    for d in datas(name):
      t += 20_000_000
      assert ADDR in cp.update([(t, [(ADDR, d, 0)])]), (name, d.hex())
      vl = cp.vl["EPS_CAL_STATUS"]
      assert vl["ACTIVE_MODE"] == d[0] & 7 and vl["ANGLE_LOOP_RUNNING"] == (d[0] >> 3) & 1 and vl["REQUESTED_MODE"] == d[0] >> 4
      assert vl["BUILD_ID"] == 0x04
      assert (vl["ANGLE_FAULT"], vl["ANGLE_FAULT_WHY"], vl["ANGLE_TARGET_HELD"], vl["ANGLE_LOOP_ACTIVE"]) == \
             (d[2] & 1, (d[2] >> 1) & 3, (d[2] >> 3) & 1, (d[2] >> 4) & 1)
      assert vl["ANGLE_REF"] == pytest.approx(-0.1 * struct.unpack(">h", d[3:5])[0])
      assert vl["ANGLE_OUT"] == struct.unpack(">h", d[5:7])[0]
  assert KNOWN_BUILDS[0x04] == 0b1111 and 0x04 in ANGLE_BUILDS and 0x02 not in ANGLE_BUILDS


def test_angle_ref_has_the_steer_angle_scale_and_sign():
  # while the loop runs, its reference follows the EPS's own published angle (0x14A raw) with the same sign
  ref, ang = [], []
  for _, h, a14a in FRAMES["pc_39_11"]["frames"]:
    d = bytes.fromhex(h)
    if d[2] & 0x10 and a14a is not None:
      ref.append(struct.unpack(">h", d[3:5])[0]); ang.append(a14a)
  assert len(ref) > 100 and np.ptp(ang) > 300                         # > 30 deg of travel in the window
  assert np.corrcoef(ref, ang)[0, 1] > 0.98
  assert abs(np.polyfit(ang, ref, 1)[0] - 1.0) < 0.1


def test_emulator_runs_show_the_expected_loop_states():
  why = lambda n: {(d[2] & 1, (d[2] >> 1) & 3) for d in datas(n)}
  assert (1, 1) in why("g_step_39") and (1, 2) in why("g_stale_45")
  assert (1, 3) in why("g_invalid_45")
  assert all(d[2] & 1 == 0 for d in datas("pc_39_11")) and any(d[0] & 8 for d in datas("pc_39_11"))
  assert not any(d[0] & 8 for d in datas("g_bit5off_16"))              # bit 5 off: mode 3 active, loop never runs
  assert {d[0] & 7 for d in datas("g_mode1ang_16")} == {0, 1}           # mode 1 requested: never mode 3


# --- startup selection ---

def test_angle_setting_selects_angle_mode_on_modified_clarity_only(angle_file):
  ci = clarity()
  assert ci.CP.flags & HondaFlags.CLARITY_ANGLE_MODE and ci.CP.steerControlType == structs.CarParams.SteerControlType.angle
  assert ci.CC.eps_mode == 0x07 and ci.CS.eps_cal_status.angle and ci.CS.eps_cal_status.requested == 3
  stock = clarity(b'39990-TRW-A020\x00\x00')
  assert not stock.CP.flags & HondaFlags.CLARITY_ANGLE_MODE and stock.CP.steerControlType == structs.CarParams.SteerControlType.torque
  assert stock.CC.angle_sender is None and stock.CC.eps_mode == 0


def test_angle_setting_off_keeps_torque_mode():
  ci = clarity()
  assert not ci.CP.flags & HondaFlags.CLARITY_ANGLE_MODE and ci.CP.steerControlType == structs.CarParams.SteerControlType.torque
  assert ci.CC.angle_sender is None and ci.CC.eps_mode == 0x02 and not ci.CS.eps_cal_status.angle


# --- interlock in angle mode ---

def test_no_status_frame_faults_in_angle_mode(angle_file):
  ci = clarity(); f = Feed(ci)
  assert all(s.steerFaultTemporary for s in f.run([None] * 20))
  assert ci.CS.eps_cal_status.fault == "no_status" and not ci.CS.eps_cal_status.angle_ready


def test_emulator_run_ready_only_once_the_eps_runs_mode_3(angle_file):
  ci = clarity(); f = Feed(ci)
  ds = datas("pc_39_11")
  running = []
  for i, d in enumerate(ds):
    s = f.step(d); f.step()
    assert s.steerFaultTemporary == ((d[0] & 7) != 3), (i, d.hex())
    running.append(ci.CS.eps_cal_status.loop_running)
  assert ci.CS.eps_cal_status.angle_ready and running == [bool(d[0] & 8) for d in ds]


@pytest.mark.parametrize("name,why", [("g_step_39", 1), ("g_stale_45", 2), ("g_invalid_45", 3)])
def test_eps_angle_fault_faults_openpilot(angle_file, name, why):
  ci = clarity(); f = Feed(ci)
  ds = datas(name)
  states = f.run(ds)
  for i, d in enumerate(ds):
    assert states[2 * i].steerFaultTemporary == ((d[0] & 7) != 3 or bool(d[2] & 1)), (i, d.hex())
  assert any(d[2] & 1 for d in ds) and ci.CS.eps_cal_status.angle_fault_why == why


def test_build_without_angle_loop_faults(angle_file):
  ci = clarity(); f = Feed(ci)
  f.run([v3(build=0x02, active=0, requested=0, running=False, flags=0, counter=k % 4) for k in range(6)])
  assert ci.CS.eps_cal_status.fault == "mode_not_built" and not ci.CS.eps_cal_status.angle_ready
  KNOWN_BUILDS[0x7D] = 0b1111                                           # mode 3 listed, but not an angle build
  try:
    ci = clarity(); f = Feed(ci)
    f.run([v3(build=0x7D, counter=k % 4) for k in range(6)])
    assert ci.CS.eps_cal_status.fault == "no_angle_loop"
  finally:
    del KNOWN_BUILDS[0x7D]


def test_torque_mode_interlock_accepts_build_04_in_mode_1():
  ci = clarity(); f = Feed(ci)                                          # no angle file: CleanPTM request
  states = f.run([v3(active=1, requested=1, running=False, flags=0, counter=k % 4) for k in range(6)])
  assert not states[-1].steerFaultTemporary and not ci.CS.eps_cal_status.angle_ready


# --- 0xE4 angle payload ---

def test_no_payload_until_the_eps_is_ready(angle_file):
  ci = clarity()
  Feed(ci).run([v3(active=0, running=False, flags=0, counter=k % 4) for k in range(6)])   # EPS still in mode 0
  for _ in range(20):
    _, f = e4(ci, True, 30.0, 5.0)
    assert f[0:3] == bytes(3) and f[3] == 0x07                          # nothing an EPS could read as torque


def test_idle_frames_carry_only_the_mode_request(angle_file):
  ci = clarity(); ready(ci)
  for _ in range(10):
    _, f = e4(ci, False, 30.0, 5.0)
    assert f[0:3] == bytes(3) and f[3] == 0x07


def test_engage_starts_at_the_measured_angle_and_fades_in(angle_file):
  ci = clarity(); ready(ci)
  e4(ci, False, 0.0, 12.3)
  raws = []
  for _ in range(300):
    _, f = e4(ci, True, 20.0, 12.3, v=10.0)
    assert f[2] == 0xA0 and f[3] == 0x07                                 # request + angle payload, mode 3 + angle
    raws.append(struct.unpack(">h", f[0:2])[0])
  ang = [r / cam.RAW_PER_DEG for r in raws]
  assert ang[0] == pytest.approx(12.3, abs=0.051)                        # first target = the measured angle
  assert max(np.diff(ang[:10])) <= 0.11                                  # no jump: starts at rest, accelerates (0.1 deg raw)
  assert ang[-1] == pytest.approx(20.0, abs=0.051)


def trajectory(v, des, n, meas=0.0, rate0=0.0):
  s = cam.AngleModeSender(); s.update(False, 0.0, meas, v, True, rate0)
  return np.array([s.update(True, des(k), meas, v, True)[0] / cam.RAW_PER_DEG for k in range(n)]), s


@pytest.mark.parametrize("v", [2.0, 8.0, 15.0, 30.0])
def test_target_rate_and_acceleration_limits(v):
  a, s = trajectory(v, lambda k: 60.0 * np.sign(np.sin(k / 40.0)), 600)   # repeated big reversals (a twitchy model)
  w = []; acc = []
  ex = cam.AngleModeSender(); ex.update(False, 0.0, 0.0, v, True)
  prev_a = prev_w = 0.0
  for k in range(600):                                                   # exact (unrounded) trajectory
    ex.update(True, 60.0 * np.sign(np.sin(k / 40.0)), 0.0, v, True)
    w.append((ex.apply_angle - prev_a) / 0.01); acc.append((w[-1] - prev_w) / 0.01); prev_a, prev_w = ex.apply_angle, w[-1]
  assert max(map(abs, w)) <= float(np.interp(v, cam._VT, cam.TARGET_RATE_DEG_S)) + 1e-6
  assert max(map(abs, acc)) <= float(np.interp(v, cam._VT, cam.TARGET_ACCEL_DEG_S2)) + 1e-6


def test_engage_fade_limits_rate_and_acceleration_at_first():
  ex = cam.AngleModeSender(); ex.update(False, 0.0, 0.0, 5.0, True)
  w = []; prev = 0.0
  for k in range(int(cam.ENGAGE_S / 0.01)):
    ex.update(True, 100.0, 0.0, 5.0, True); w.append((ex.apply_angle - prev) / 0.01); prev = ex.apply_angle
  fade = lambda k: cam.ENGAGE_FLOOR + (1 - cam.ENGAGE_FLOOR) * k * 0.01 / cam.ENGAGE_S
  for k, x in enumerate(w):
    assert abs(x) <= fade(k) * float(np.interp(5.0, cam._VT, cam.TARGET_RATE_DEG_S)) + 1e-6
  assert w[0] <= cam.ENGAGE_FLOOR * float(np.interp(5.0, cam._VT, cam.TARGET_ACCEL_DEG_S2)) * 0.01 + 1e-6


def test_engage_carries_the_wheel_rate():
  for w0 in (15.0, 80.0):                                                # driver lets go with the wheel moving
    ex = cam.AngleModeSender(); ex.update(False, 0.0, 10.0, 8.0, True, w0)
    ex.update(True, 100.0, 10.0, 8.0, True)
    a_floor = cam.ENGAGE_FLOOR * float(np.interp(8.0, cam._VT, cam.TARGET_ACCEL_DEG_S2))
    assert abs(ex.apply_rate - w0) <= a_floor * 0.01 + 1e-6               # continues from the wheel's rate, no jolt


def test_no_overshoot_on_a_step():
  a, _ = trajectory(10.0, lambda k: 30.0, 600)
  assert a.max() <= 30.0 + 0.051 and a[-1] == pytest.approx(30.0, abs=0.051)


@pytest.mark.parametrize("v", [2.0, 5.0, 10.0, 15.0, 25.0, 35.0])
def test_steps_stay_inside_the_eps_jump_threshold(angle_file, v):
  ci = clarity(); ready(ci)
  e4(ci, False, 0.0, 0.0, v=v)
  prev = 0.0; worst = 0.0
  for k in range(300):
    des = 15.0 * np.sign(np.sin(k / 25.0))                               # repeated large steps
    act, f = e4(ci, True, des, 0.0, v=v)
    a = struct.unpack(">h", f[0:2])[0] / cam.RAW_PER_DEG
    worst = max(worst, abs(a - prev)); prev = a
    assert act.steeringAngleDeg == pytest.approx(a, abs=0.051)
  jt = float(np.interp(v, cam._V, cam.EPS_JUMP_DEG))
  assert worst <= 0.6 * jt + 0.1                                         # the EPS allows >= 0.8 x JT per frame


@pytest.mark.parametrize("v", [5.0, 12.0, 20.0, 30.0])
def test_target_is_clamped_inside_the_eps_lateral_accel_clamp(angle_file, v):
  ci = clarity(); ready(ci)
  e4(ci, False, 0.0, 0.0, v=v)
  for _ in range(3000):
    _, f = e4(ci, True, 600.0, 0.0, v=v)
  a = struct.unpack(">h", f[0:2])[0] / cam.RAW_PER_DEG
  assert a == pytest.approx(cam.angle_limit(v), abs=0.06) and a < float(np.interp(v, cam.AMAX_V, cam.EPS_AMAX_DEG))


def test_measured_angle_above_the_clamp_walks_down(angle_file):
  ci = clarity(); ready(ci)
  e4(ci, False, 0.0, 40.0, v=30.0)                                      # engage at 30 m/s with the wheel at 40 deg
  prev = 40.0
  for _ in range(400):
    _, f = e4(ci, True, 40.0, 40.0, v=30.0)
    a = struct.unpack(">h", f[0:2])[0] / cam.RAW_PER_DEG
    assert abs(a - prev) <= float(np.interp(30.0, cam._VT, cam.TARGET_RATE_DEG_S)) * 0.01 + 0.06
    prev = a
  assert prev == pytest.approx(cam.angle_limit(30.0), abs=0.06)


def test_driver_press_drops_the_request_and_reengage_starts_at_the_wheel(angle_file):
  # same yield as torque mode (ModifiedEpsSteering lkas_active): no request while the driver overrides
  ci = clarity(); ready(ci)
  e4(ci, False, 0.0, 0.0)
  for _ in range(100):
    _, f = e4(ci, True, 10.0, 0.0)
  assert f[2] == 0xA0
  for _ in range(50):
    _, f = e4(ci, True, 10.0, -5.0, pressed=True)
    assert f[0:3] == bytes(3) and f[3] == 0x07
  outs = [e4(ci, True, 10.0, -5.0)[1] for _ in range(300)]               # released: re-engage from the wheel, faded in
  a = [struct.unpack(">h", f[0:2])[0] / cam.RAW_PER_DEG for f in outs]
  assert outs[0][2] == 0xA0 and a[0] == pytest.approx(-5.0, abs=0.051)
  steps = np.abs(np.diff(a))
  assert steps[:10].max() <= 0.11                                        # no snap: the target starts at rest (0.1 deg raw)
  assert steps.max() <= float(np.interp(10.0, cam._VT, cam.TARGET_RATE_DEG_S)) * 0.01 + 0.051
  assert a[-1] == pytest.approx(10.0, abs=0.051)


def test_fault_mid_drive_stops_the_payload_at_once(angle_file):
  ci = clarity(); f6 = ready(ci)
  e4(ci, False, 0.0, 0.0)
  for _ in range(60):
    _, f = e4(ci, True, 5.0, 0.0)
  assert f[2] == 0xA0
  f6.run([v3(flags=0x1B, counter=k % 4) for k in range(8, 10)])        # EPS reports FAULT (why 1)
  assert ci.CS.eps_cal_status.fault == "angle_fault"
  _, f = e4(ci, True, 5.0, 0.0)
  assert f[0:3] == bytes(3) and f[3] == 0x07


def test_torque_mode_frames_unchanged():
  ci = clarity()
  ci.update([])
  ci.CS.out = structs.CarState(vEgo=15.0).as_reader()
  cc = structs.CarControl(latActive=True)
  cc.actuators.torque = 0.3
  _, frames = ci.apply(cc.as_reader(), 1_000_000_000)
  f = next(bytes(x[1]) for x in frames if x[0] == 0xE4)
  assert f[3] == 0x02 and f[2] & 0x20 == 0


def test_angle_setting_leaves_other_hondas_alone():
  cp = params(CAR.HONDA_CIVIC_BOSCH, [])
  flags, sct = cp.flags, cp.steerControlType
  cam.apply_angle_mode(cp, True)
  assert cp.flags == flags and cp.steerControlType == sct


# Owner rule 11-18: no angle request ever leaves openpilot unless the EPS build itself reports angle support and runs it.
NOT_ANGLE_CAPABLE = {
  "no 0x6A4 (stock, CleanPTM, P1)": [None] * 20,
  "MM 0x02 in torque mode": [v3(build=0x02, active=1, requested=1, running=False, flags=0, counter=k % 4) for k in range(10)],
  "MM 0x02 stock mode": [v3(build=0x02, active=0, requested=0, running=False, flags=0, counter=k % 4) for k in range(10)],
  "unknown build claiming mode 3": [v3(build=0x7E, counter=k % 4) for k in range(10)],
  "0x04 still in mode 1 (switch pending)": [v3(active=1, running=False, flags=0, counter=k % 4) for k in range(10)],
  "0x04 in mode 3 with the EPS fault bit": [v3(flags=0x19, counter=k % 4) for k in range(10)],
}


@pytest.mark.parametrize("state", NOT_ANGLE_CAPABLE)
def test_no_angle_request_unless_the_build_reports_angle_support(angle_file, state):
  ci = clarity(); f = Feed(ci)
  f.run(NOT_ANGLE_CAPABLE[state])
  assert not ci.CS.eps_cal_status.angle_ready and ci.CS.eps_cal_status.fault, state
  for k in range(30):                                  # lateral active, a real target, the wheel elsewhere
    _, d = e4(ci, True, 20.0 + k, 0.0)
    assert d[0:2] == b"\0\0" and not d[2] & 0x80 and not d[2] & 0x20, (state, d.hex())   # no angle, no request, no bit 5
    assert d[3] == 0x07                                # only the mode request, which a non-angle build ignores or maps


@pytest.mark.parametrize("setting", [dict(fade_down_s=1.0), dict(assist_during_override=True)])
def test_press_drops_the_angle_request_whatever_the_override_settings(angle_file, setting):
  # Override Fade Down / Assist During Override keep the request up through a press in torque mode; never in angle mode
  import dataclasses
  from opendbc.car.honda.modified_eps import DEFAULT_SETTINGS
  ci = clarity(); ready(ci)
  ci.CC.modified_eps_settings = type("S", (), {"current": lambda self: dataclasses.replace(DEFAULT_SETTINGS, **setting)})()
  e4(ci, False, 0.0, 0.0)
  for _ in range(100):
    _, f = e4(ci, True, 10.0, 0.0)
  assert f[2] == 0xA0
  for _ in range(50):
    _, f = e4(ci, True, 10.0, -5.0, pressed=True)
    assert f[0:3] == bytes(3) and f[3] == 0x07                           # no angle, no request while pressed


@pytest.mark.parametrize("fade_up", [0.0, 0.5, 3.0])
def test_engage_fade_follows_override_fade_up(angle_file, fade_up):
  import dataclasses
  from opendbc.car.honda.modified_eps import DEFAULT_SETTINGS
  ci = clarity(); ready(ci)
  ci.CC.modified_eps_settings = type("S", (), {"current": lambda self: dataclasses.replace(DEFAULT_SETTINGS, fade_up_s=fade_up)})()
  e4(ci, False, 0.0, 0.0, v=5.0)
  ex = ci.CC.angle_sender; w = []; prev = 0.0
  for _ in range(600):
    e4(ci, True, 350.0, 0.0, v=5.0); w.append(abs(ex.apply_angle - prev) / 0.01); prev = ex.apply_angle
  full = min(float(np.interp(5.0, cam._VT, cam.TARGET_RATE_DEG_S)), float(np.interp(5.0, cam._V, cam.ANGLE_STEP_DEG)) / 0.01)
  t_full = next(k for k, x in enumerate(w) if x >= 0.99 * full) * 0.01      # first time the full rate is reached
  if fade_up == 0.0:
    assert t_full < 0.5                                                  # only the acceleration limit
  else:
    assert t_full >= 0.6 * fade_up                                       # the limits fade over the setting


# --- build 0x05: angle profile 2 (mode 4, 3.0 m/s^2 clamp), chosen by HondaClarityAngleCap3 ---

def cap3(ci, on):
  import dataclasses
  from opendbc.car.honda.modified_eps import DEFAULT_SETTINGS
  ci.CC.modified_eps_settings = type("S", (), {"current": lambda self: dataclasses.replace(DEFAULT_SETTINGS, angle_cap3=on)})()


def test_cap3_on_build_04_keeps_mode_3(angle_file):
  ci = clarity(); cap3(ci, True); f = Feed(ci)
  f.run([v3(counter=k % 4) for k in range(8)])                          # build 0x04, mode 3
  _, d = e4(ci, False, 0.0, 0.0)
  assert d[3] == 0x07 and ci.CS.eps_cal_status.requested == 3 and ci.CS.eps_cal_status.angle_ready


@pytest.mark.parametrize("build", [0x05, 0x06, 0x08, 0x09])
def test_cap3_on_build_05_requests_mode_4_and_uses_the_3g_clamp(angle_file, build):
  ci = clarity(); cap3(ci, True); f = Feed(ci)
  f.run([v3(build=build, active=3, requested=3, counter=k % 4) for k in range(4)])
  _, d = e4(ci, False, 0.0, 0.0)                                         # lateral off: the profile switch is allowed
  assert d[3] == 0x09 and ci.CS.eps_cal_status.requested == 4
  f.run([v3(build=build, active=3, requested=4, counter=k % 4) for k in range(4)])
  assert ci.CS.eps_cal_status.fault == "inactive_mode" and not ci.CS.eps_cal_status.angle_ready   # until the EPS switches
  f.run([v3(build=build, active=4, requested=4, counter=k % 4) for k in range(4)])
  assert ci.CS.eps_cal_status.angle_ready and ci.CS.eps_cal_status.cap3_active
  for _ in range(3000):
    _, d = e4(ci, True, 600.0, 0.0, v=12.0)
  a = struct.unpack(">h", d[0:2])[0] / cam.RAW_PER_DEG
  assert d[3] == 0x09 and a == pytest.approx(cam.angle_limit(12.0, cam.AMAX_CAP3_SCALE), abs=0.06)
  assert a < 0.75 * float(np.interp(12.0, cam.AMAX_V, cam.EPS_AMAX_DEG))    # inside the EPS's 3.0 clamp


def test_cap3_off_on_build_05_stays_mode_3(angle_file):
  ci = clarity(); cap3(ci, False); f = Feed(ci)
  f.run([v3(build=0x05, counter=k % 4) for k in range(8)])
  _, d = e4(ci, False, 0.0, 0.0)
  assert d[3] == 0x07 and ci.CS.eps_cal_status.angle_ready and not ci.CS.eps_cal_status.cap3_active


def test_cap3_toggle_while_engaged_waits_for_disengage(angle_file):
  ci = clarity(); cap3(ci, False); f = Feed(ci)
  f.run([v3(build=0x05, counter=k % 4) for k in range(8)])
  e4(ci, False, 0.0, 0.0)
  for _ in range(20):
    _, d = e4(ci, True, 5.0, 0.0)
  cap3(ci, True)
  for _ in range(20):
    _, d = e4(ci, True, 5.0, 0.0)
    assert d[3] == 0x07 and d[2] == 0xA0                                 # still mode 3, still steering
  _, d = e4(ci, False, 0.0, 0.0)
  assert d[3] == 0x09                                                    # switches once lateral is off


@pytest.mark.parametrize("limit", [0.0, 40.0])
def test_steering_angle_rate_limit_caps_the_target_in_carcontroller(angle_file, limit):
  # Night Star "Steering Angle Rate Limit" (HondaEpsAngleRateLimit): applied to the angle target in CarController
  import dataclasses
  from opendbc.car.honda.modified_eps import DEFAULT_SETTINGS
  ci = clarity(); ready(ci)
  ci.CC.modified_eps_settings = type("S", (), {"current": lambda self: dataclasses.replace(DEFAULT_SETTINGS, angle_rate_limit_deg_s=limit,
                                                                                          fade_up_s=0.0)})()
  e4(ci, False, 0.0, 0.0, v=5.0)
  ex = ci.CC.angle_sender; w = []; prev = 0.0
  for _ in range(400):
    e4(ci, True, 300.0, 0.0, v=5.0); w.append(abs(ex.apply_angle - prev) / 0.01); prev = ex.apply_angle
  cap = min(float(np.interp(5.0, cam._VT, cam.TARGET_RATE_DEG_S)), float(np.interp(5.0, cam._V, cam.ANGLE_STEP_DEG)) / 0.01)
  if limit:
    assert max(w) <= limit + 1e-6 and max(w) > 0.99 * limit
  else:
    assert max(w) > 0.99 * cap                                           # 0 = off: only the sender's own cap


# --- '+' software ID (39990+TRW+A020, PTM 2.0 / angle PTM marker, EPS build 0x05 on): same application as ',' ---
PTM2 = b'39990+TRW+A020\x00\x00'


def test_ptm2_id_is_the_same_modified_clarity():
  from opendbc.car.honda.steer_ratio import get_honda_vgr_profile, normalize_honda_eps_fw
  from opendbc.car.honda.fingerprints import FW_VERSIONS
  from opendbc.car.structs import CarParams
  assert normalize_honda_eps_fw(PTM2) == normalize_honda_eps_fw(MODIFIED) == "39990-TRW-A020"
  assert PTM2 in FW_VERSIONS[CAR.HONDA_CLARITY][(CarParams.Ecu.eps, 0x18da30f1, None)]
  a, b = params(CAR.HONDA_CLARITY, [eps(PTM2)]), params(CAR.HONDA_CLARITY, [eps(MODIFIED)])
  assert a.flags & HondaFlags.EPS_MODIFIED and a.flags == b.flags                       # modified, same VGR flags
  assert get_honda_vgr_profile([eps(PTM2)]) == get_honda_vgr_profile([eps(MODIFIED)]) is not None


def test_ptm2_id_gets_angle_mode(angle_file):
  ci = clarity(PTM2)
  assert ci.CP.flags & HondaFlags.CLARITY_ANGLE_MODE and ci.CC.eps_mode == 0x07


# --- effort fade: sent = wheel + w * (trajectory - wheel), w smoothstep 0 -> 1 over engage_s ---

def _release(engage_s, effort_fade=True, frames=120, v=8.0):
  s = cam.AngleModeSender()
  wheel, rate = -37.0, 100.0                       # car e8/e9: released 35-60 deg from the target, wheel still moving
  s.update(False, 2.0, wheel, v, True, measured_rate_deg_s=rate)
  log = []
  for _ in range(frames):
    wheel += rate * cam.DT_CTRL
    rate *= 0.97
    s.update(True, 2.0, wheel, v, True, measured_rate_deg_s=rate, engage_s=engage_s, effort_fade=effort_fade)
    log.append((wheel, s.apply_angle, s.out_angle))
  return np.array(log)


def test_effort_fade_starts_at_the_wheel_and_hands_over_to_the_trajectory():
  L = _release(0.5)
  gap = np.abs(L[:, 2] - L[:, 0])                  # what the EPS loop sees as its error
  traj_gap = np.abs(L[:, 1] - L[:, 0])
  assert gap[0] < 0.05 * max(traj_gap[0], 0.1) + 0.01
  assert np.all(gap[:49] <= traj_gap[:49] + 1e-9)
  assert L[49, 2] == pytest.approx(L[49, 1], abs=1e-9)        # w = 1 at engage_s (50 frames)
  assert np.allclose(L[50:, 2], L[50:, 1], atol=1e-9)


def test_effort_fade_off_or_zero_time_sends_the_trajectory():
  for L in (_release(0.5, effort_fade=False), _release(0.0)):
    assert np.allclose(L[:, 2], L[:, 1], atol=1e-9)


@pytest.mark.parametrize("v", [2.0, 10.0, 20.0])
def test_effort_fade_respects_the_eps_step_limit(v):
  L = _release(1.0, v=v, frames=200)
  step = float(np.interp(v, cam._V, cam.ANGLE_STEP_DEG))
  assert np.abs(np.diff(L[:, 2])).max() <= step + 1e-9


# --- build 0x06: authority ramp (HKG style), byte 3 bits 7:4 = CUT; 0x08 = 0x06 + 100 ms stale window ---

def fade_up(ci, s):
  import dataclasses
  from opendbc.car.honda.modified_eps import DEFAULT_SETTINGS
  ci.CC.modified_eps_settings = type("S", (), {"current": lambda self: dataclasses.replace(DEFAULT_SETTINGS, fade_up_s=s)})()


def test_authority_ramp_follows_hkg():
  r = cam.AuthorityRamp()
  assert r.update(False, False, 1.0) == 15
  cuts = [r.update(True, False, 1.0) for _ in range(120)]
  assert cuts[0] == 15 and cuts[-1] == 0 and all(b <= a for a, b in zip(cuts, cuts[1:]))
  assert next(i for i, c in enumerate(cuts) if c == 0) == pytest.approx(97, abs=2)       # Override Fade Up 1.0 s
  down = [r.update(True, True, 1.0) for _ in range(60)]
  assert r.g < 1 / 30 and down[-1] == 15                                                 # floor 0: CUT 15 (stock lockout)
  assert next(i for i, c in enumerate(down) if c >= 13) < 45                             # (g - min)/17 per frame: tau 17 frames
  g0 = r.g
  up = [r.update(True, False, 0.0) for _ in range(160)]                                  # Fade Up 0: HKG's 0.008/frame
  assert next(i for i, c in enumerate(up) if c == 0) == pytest.approx((1 - 0.5 / 15 - g0) / 0.008, abs=2)   # CUT 0 from g > 29/30
  assert r.update(False, True, 1.0) == 15 and r.g == 0.0                                 # lateral off: zero authority


def hold(ci, on):
  import dataclasses
  from opendbc.car.honda.modified_eps import DEFAULT_SETTINGS
  ci.CC.modified_eps_settings = type("S", (), {"current": lambda self: dataclasses.replace(DEFAULT_SETTINGS, angle_hold_override=on)})()


def test_hold_through_override_is_on_by_default():
  from opendbc.car.honda.modified_eps import DEFAULT_SETTINGS
  assert DEFAULT_SETTINGS.angle_hold_override and cam.AUTH_MIN == 0.0


@pytest.mark.parametrize("build", [0x06, 0x08, 0x09])
def test_build_06_hold_off_drops_the_request_on_press_and_sends_no_cut(angle_file, build):
  ci = clarity(); hold(ci, False); f = Feed(ci)
  f.run([v3(build=build, counter=k % 4) for k in range(8)])
  assert ci.CS.eps_cal_status.authority_ready
  e4(ci, False, 0.0, 0.0)
  assert all(e4(ci, True, 10.0, 0.0)[1][3] == 0x07 for _ in range(50))   # the firmware ramps in by itself (CUT 0)
  _, d = e4(ci, True, 10.0, -5.0, pressed=True)
  assert d[0:3] == bytes(3) and d[3] == 0x07


@pytest.mark.parametrize("build", [0x06, 0x08, 0x09])
def test_build_06_hold_holds_the_request_through_a_press_and_ramps_authority(angle_file, build):
  ci = clarity(); fade_up(ci, 1.0); f = Feed(ci)                         # default settings: hold on
  f.run([v3(build=build, counter=k % 4) for k in range(8)])
  assert ci.CS.eps_cal_status.authority_ready
  assert e4(ci, False, 0.0, 0.0)[1][3] == 0x07                                         # lateral off: byte 3 as on 0x05
  eng = [e4(ci, True, 10.0, 0.0)[1] for _ in range(150)]
  assert eng[0][3] == 0xF7 and eng[-1][3] == 0x07 and all(d[3] & 0x0F == 0x07 for d in eng)
  press = [e4(ci, True, 10.0, -5.0, pressed=True)[1] for _ in range(60)]
  assert all(d[2] == 0xA0 for d in press)                                              # request held
  a = [struct.unpack(">h", d[0:2])[0] / cam.RAW_PER_DEG for d in press]
  assert a[-1] == pytest.approx(-5.0, abs=0.051)                                       # target follows the wheel (route ed)
  cuts = [d[3] >> 4 for d in press]
  assert cuts[-1] == 15 and all(b >= a for a, b in zip(cuts, cuts[1:]))              # zero authority: under the lockout
  relf = [e4(ci, True, 10.0, -5.0)[1] for _ in range(150)]
  rel = [d[3] >> 4 for d in relf]
  assert rel[-1] == 0 and all(b <= a for a, b in zip(rel, rel[1:]))
  ra = [struct.unpack(">h", d[0:2])[0] / cam.RAW_PER_DEG for d in relf]
  assert abs(ra[0] - -5.0) < 0.2 and all(b >= a - 1e-9 for a, b in zip(ra, ra[1:]))     # release: from the wheel toward the plan
  e4(ci, False, 0.0, 0.0)
  assert e4(ci, True, 10.0, 0.0)[1][3] == 0xF7                                         # every engage starts at zero authority


def test_build_06_hold_below_min_steer_speed_drops_the_request(angle_file):
  import dataclasses
  from opendbc.car.honda.modified_eps import DEFAULT_SETTINGS
  ci = clarity(); f = Feed(ci)
  ci.CC.modified_eps_settings = type("S", (), {"current": lambda self: dataclasses.replace(DEFAULT_SETTINGS, min_steer_speed_mph=10.0)})()
  f.run([v3(build=0x06, counter=k % 4) for k in range(8)])
  _, d = e4(ci, True, 10.0, 0.0, v=2.0)
  assert d[0:3] == bytes(3) and d[3] == 0x07                                          # no request: no CUT


@pytest.mark.parametrize("build", [0x04, 0x05])
def test_older_builds_send_no_cut_and_drop_the_request_on_press(angle_file, build):
  # default settings (hold on): no CUT, request dropped on 0x04/0x05
  ci = clarity(); f = Feed(ci)
  f.run([v3(build=build, counter=k % 4) for k in range(8)])
  assert not ci.CS.eps_cal_status.authority_ready
  e4(ci, False, 0.0, 0.0)
  assert all(e4(ci, True, 10.0, 0.0)[1][3] == 0x07 for _ in range(50))
  _, d = e4(ci, True, 10.0, -5.0, pressed=True)
  assert d[0:3] == bytes(3) and d[3] == 0x07


# --- angle mode: the press threshold follows the wheel angle (lower toward center, the full setting from 45 deg) ---

def test_angle_mode_threshold_curve():
  from opendbc.car.honda.modified_eps import angle_mode_threshold
  assert [round(angle_mode_threshold(1660, a)) for a in (0, 5, -15, 30, 45, 200)] == [1295, 1295, 1394, 1527, 1660, 1660]


def _press_at(ci, angle, torque, n=6):
  from opendbc.can import CANPacker
  pk = CANPacker("honda_clarity_hybrid_2018_can_generated")
  cs = None
  for _ in range(n):
    _press_at.t += 10_000_000
    msgs = [pk.make_can_msg("STEERING_SENSORS", 0, {"STEER_ANGLE": angle, "COUNTER": _press_at.c}),
            pk.make_can_msg("STEER_STATUS", 0, {"STEER_TORQUE_SENSOR": torque, "COUNTER": _press_at.c})]
    _press_at.c = (_press_at.c + 1) % 4
    cs = ci.update([(_press_at.t, [(a, d, b) for a, d, b in msgs])])
  return cs.steeringPressed
_press_at.t, _press_at.c = 3_000_000_000, 0


def test_angle_mode_press_threshold_follows_the_angle(angle_file):
  import dataclasses
  from opendbc.car.honda.modified_eps import DEFAULT_SETTINGS
  ci = clarity()
  ci.CS.modified_eps_settings = type("S", (), {"current": lambda self: dataclasses.replace(DEFAULT_SETTINGS, override_threshold=1660)})()
  assert _press_at(ci, 2.0, 1400)              # near center 1400 > 1295: a press
  assert not _press_at(ci, 60.0, 0, n=150)     # release (hold time), then a large angle
  assert not _press_at(ci, 60.0, 1400)         # 60 deg: 1400 < 1660, not a press
  assert _press_at(ci, 60.0, 1700)


def test_torque_mode_press_threshold_ignores_the_angle():
  import dataclasses
  from opendbc.car.honda.modified_eps import DEFAULT_SETTINGS
  ci = clarity()                                # Angle Mode off: torque mode
  ci.CS.modified_eps_settings = type("S", (), {"current": lambda self: dataclasses.replace(DEFAULT_SETTINGS, override_threshold=1660)})()
  assert not _press_at(ci, 2.0, 1400)
