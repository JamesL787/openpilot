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


def test_engage_starts_at_the_measured_angle_and_ramps(angle_file):
  ci = clarity(); ready(ci)
  e4(ci, False, 0.0, 12.3)
  raws = []
  for _ in range(80):
    _, f = e4(ci, True, 20.0, 12.3, v=10.0)
    assert f[2] == 0xA0 and f[3] == 0x07                                 # request + angle payload, mode 3 + angle
    raws.append(struct.unpack(">h", f[0:2])[0])
  ang = [r / cam.RAW_PER_DEG for r in raws]
  assert ang[0] == pytest.approx(12.3 + cam.ENGAGE_RATE * 0.01, abs=0.051)   # first target = measured + one engage step
  steps = np.diff(ang)
  assert steps[:45].max() <= cam.ENGAGE_RATE * 0.01 + 0.051             # engage ramp (0.5 s)
  assert ang[-1] == pytest.approx(20.0, abs=0.051)


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
    assert abs(a - prev) <= cam.ENGAGE_RATE * 0.01 + 0.06 or abs(a - prev) <= 0.6 + 0.06
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
  outs = [e4(ci, True, 10.0, -5.0)[1] for _ in range(60)]                # released: re-engage from the wheel, ramped
  a = [struct.unpack(">h", f[0:2])[0] / cam.RAW_PER_DEG for f in outs]
  assert outs[0][2] == 0xA0 and a[0] == pytest.approx(-5.0 + cam.ENGAGE_RATE * 0.01, abs=0.051)
  assert max(abs(y - x) for x, y in zip(a[:50], a[1:50])) <= cam.ENGAGE_RATE * 0.01 + 0.051   # 0.5 s engage ramp


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
