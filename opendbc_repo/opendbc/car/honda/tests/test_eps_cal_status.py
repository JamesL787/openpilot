"""0x6A4 EPS_CAL_STATUS interlock (eps_cal_status.py), fed with frames the emulated MM EPS firmware transmitted
(eps_cal_status_emulator_frames.json, rwd-xray lab/clarity/sh2a_emu, image img_mm.bin = MM build 0x02, 0x6A4 layout v2)."""
import json
import os

from opendbc.can import CANParser
from opendbc.car.honda.eps_cal_status import KNOWN_BUILDS, STATUS_TIMEOUT_FRAMES
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.tests.test_modified_eps import eps, params
from opendbc.car.honda.values import CAR

ADDR = 0x6A4
FRAMES = json.load(open(os.path.join(os.path.dirname(__file__), "eps_cal_status_emulator_frames.json")))


def honda_checksum(b, addr=ADDR):
  s = sum((x >> 4) + (x & 0xF) for x in b[:-1]) + (b[-1] >> 4) + sum((addr >> (4 * k)) & 0xF for k in range(3))
  return (8 - s) & 0xF


def frame(active=1, requested=1, build=0x02, counter=0):
  b = bytearray([(requested << 4) | active, build, 0, 0, 0, 0, 0, counter << 4])
  b[7] |= honda_checksum(bytes(b))
  return bytes(b)


def clarity(fw=b'39990-TRW,A020\x00\x00'):
  ci = CarInterface(params(CAR.HONDA_CLARITY, [eps(fw)]))
  return ci


class Feed:
  """carState at 100 Hz; 0x6A4 at 50 Hz (every other update), like the car."""
  def __init__(self, ci):
    self.ci, self.t = ci, 1_000_000_000

  def step(self, data=None):
    self.t += 10_000_000
    cs = self.ci.update([(self.t, [(ADDR, data, 0)] if data is not None else [])])
    return cs

  def run(self, datas):
    out = []
    for d in datas:
      out.append(self.step(d))
      out.append(self.step())
    return out


def test_dbc_decodes_every_emulator_frame():
  for name, rec in FRAMES.items():
    cp = CANParser("honda_clarity_hybrid_2018_can_generated", [("EPS_CAL_STATUS", float("nan"))], 0)
    t = 1_000_000_000
    for _, hexdat in rec["frames"]:
      t += 20_000_000
      dat = bytes.fromhex(hexdat)
      assert ADDR in cp.update([(t, [(ADDR, dat, 0)])]), (name, hexdat)   # checksum and counter valid
      vl = cp.vl["EPS_CAL_STATUS"]
      assert vl["ACTIVE_MODE"] == dat[0] & 0xF and vl["REQUESTED_MODE"] == dat[0] >> 4
      assert vl["BUILD_ID"] == 0x02 and dat[2:7] == bytes(5)          # reserved bytes are 0
  assert KNOWN_BUILDS[0x02] == 0b111


def test_mode1_real_timing_run_faults_only_until_the_eps_runs_cleanptm():
  ci = clarity(); f = Feed(ci)
  datas = [bytes.fromhex(h) for _, h in FRAMES["mode1_realtiming"]["frames"]]
  states = f.run(datas)
  first_active = next(i for i, d in enumerate(datas) if d[0] & 0xF == 1)
  assert first_active > 0                                     # the EPS boots in stock and switches at the first idle frame
  faults = [s.steerFaultTemporary for s in states]
  assert all(faults[:2 * first_active])                       # stock active while openpilot asks for CleanPTM: no steering
  assert not any(faults[2 * first_active:])                   # CleanPTM active: steering allowed for the rest of the run
  assert ci.CS.eps_cal_status.fault == ""


def test_switch_sequence_faults_whenever_active_is_not_mode_1():
  ci = clarity(); f = Feed(ci)
  datas = [bytes.fromhex(h) for _, h in FRAMES["seq"]["frames"]]
  states = f.run(datas)
  for i, d in enumerate(datas):
    assert states[2 * i].steerFaultTemporary == ((d[0] & 0xF) != 1), (i, d.hex())


def test_status_lost_after_timeout_then_recovers():
  ci = clarity(); f = Feed(ci)
  f.run([frame(counter=k % 4) for k in range(10)])
  assert not f.step().steerFaultTemporary
  states = [f.step() for _ in range(STATUS_TIMEOUT_FRAMES + 2)]
  assert not states[STATUS_TIMEOUT_FRAMES - 3].steerFaultTemporary
  assert states[-1].steerFaultTemporary and ci.CS.eps_cal_status.fault == "lost"
  f.run([frame(counter=k % 4) for k in range(10, 14)])
  assert not f.step().steerFaultTemporary


def test_no_status_frame_is_p1_cleanptm_behaviour():
  ci = clarity(); f = Feed(ci)
  assert not any(s.steerFaultTemporary for s in f.run([None] * 200))
  assert ci.CS.eps_cal_status.enabled and not ci.CS.eps_cal_status.announced


def test_bad_checksum_frames_are_ignored():
  ci = clarity(); f = Feed(ci)
  bad = [bytes(frame(active=0, counter=k % 4)[:7]) + bytes([frame(active=0, counter=k % 4)[7] ^ 0x01]) for k in range(40)]
  assert not any(s.steerFaultTemporary for s in f.run(bad))
  assert not ci.CS.eps_cal_status.announced


def test_unknown_build_or_missing_mode_fault():
  for build in (0x01, 0x42, 0xFF):                                   # 0x01 = an old v1-layout byte, never a build ID
    ci = clarity(); f = Feed(ci)
    states = f.run([frame(build=build, counter=k % 4) for k in range(10)])
    assert states[-1].steerFaultTemporary and ci.CS.eps_cal_status.fault == "unknown_build", (build, ci.CS.eps_cal_status.fault)
  # a known build without mode 1
  KNOWN_BUILDS[0x7E] = 0b101
  try:
    ci = clarity(); f = Feed(ci)
    f.run([frame(build=0x7E, counter=k % 4) for k in range(10)])
    assert ci.CS.eps_cal_status.fault == "mode_not_built"
  finally:
    del KNOWN_BUILDS[0x7E]


def test_stock_fw_clarity_and_other_cars_ignore_the_frame():
  ci = clarity(b'39990-TRW-A020\x00\x00'); f = Feed(ci)
  assert not ci.CS.eps_cal_status.enabled
  assert not any(s.steerFaultTemporary for s in f.run([frame(active=0, counter=k % 4) for k in range(20)]))
  assert ci.CC.eps_mode == 0
  assert clarity().CC.eps_mode == 0x02
