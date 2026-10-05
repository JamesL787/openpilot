import math
from types import SimpleNamespace

import pytest

from cereal import messaging
from openpilot.selfdrive.car.card import set_gps_accel_fields, set_vsa_accel_fields
from openpilot.selfdrive.car.gps_accel import G, GPS_WARMUP_FIXES, GpsAccelEstimator


def _fix(v=20.0, vd=0.0, acc=0.3, fix=True, bearing=0.6):
  return SimpleNamespace(vNED=[v * math.cos(bearing), v * math.sin(bearing), vd], speedAccuracy=acc, hasFix=fix)


def _fpcs():
  return messaging.new_message('starpilotCarState').starpilotCarState


def test_constant_decel_and_uphill_grade():
  est = GpsAccelEstimator()
  for i in range(60):
    t = i * 0.1
    est.update(t, _fix(v=25.0 - 2.0 * t, vd=-(25.0 - 2.0 * t) * math.tan(0.03)))
  assert est.valid(0.05)
  assert est.accel == pytest.approx(-2.0, abs=1e-3)
  assert est.grade == pytest.approx(0.03, abs=1e-3)  # vD < 0 is climbing: positive grade


def test_warmup_gap_and_bad_fixes_reset():
  est = GpsAccelEstimator()
  for i in range(GPS_WARMUP_FIXES - 1):
    est.update(i * 0.1, _fix())
  assert not est.valid(0.0)
  est.update(0.4, _fix())
  assert est.valid(0.0)
  est.update(1.0, _fix())  # 0.6 s gap: filters restart
  assert not est.valid(0.0)
  for bad in (_fix(acc=1.5), _fix(fix=False), _fix(v=2.0), _fix(vd=float('nan'))):
    est = GpsAccelEstimator()
    for i in range(10):
      est.update(i * 0.1, bad)
    assert not est.valid(0.0)


def test_stale_and_time_reversal():
  est = GpsAccelEstimator()
  for i in range(10):
    est.update(i * 0.1, _fix())
  assert not est.valid(0.31)
  assert not est.valid(-1.0)  # never seen
  n = est.good_fixes
  est.update(0.5, _fix())  # out of order: ignored
  assert est.good_fixes == n


def test_card_gps_fields():
  est = GpsAccelEstimator()
  for i in range(10):
    est.update(i * 0.1, _fix(v=20.0 + 0.1 * i, vd=-0.2))
  fpcs = _fpcs()
  set_gps_accel_fields(fpcs, est, 0.02)
  assert fpcs.gpsAccelValid and fpcs.aEgoGps == pytest.approx(1.0, abs=0.05) and fpcs.gpsGrade > 0
  set_gps_accel_fields(fpcs, est, 0.5)
  assert not fpcs.gpsAccelValid and fpcs.aEgoGps == 0.0 and fpcs.gpsGrade == 0.0


def test_vsa_pitch_correction():
  fpcs = _fpcs()
  set_vsa_accel_fields(fpcs, SimpleNamespace(vsa_long_accel=0.5, vsa_long_accel_valid=True), 0.05)
  assert fpcs.aEgoVsaPitchCorrected == pytest.approx(0.5 - G * math.sin(0.05), abs=1e-5)
  for cs, pitch in ((SimpleNamespace(vsa_long_accel=0.5, vsa_long_accel_valid=True), float('nan')),
                    (SimpleNamespace(vsa_long_accel=0.5, vsa_long_accel_valid=False), 0.05), (None, 0.05)):
    fpcs = _fpcs()
    set_vsa_accel_fields(fpcs, cs, pitch)
    assert math.isnan(fpcs.aEgoVsaPitchCorrected)


class _Sm:
  def __init__(self):
    self.frame = 0
    self.updated = {'gpsLocationExternal': False}
    self.seen = {'gpsLocationExternal': False}
    self.recv_frame = {'gpsLocationExternal': 0}
    self.logMonoTime = {'gpsLocationExternal': 0}
    self.valid = {'carControl': True}
    self.msgs = {'carControl': SimpleNamespace(orientationNED=[0.0, 0.02, 1.0]), 'gpsLocationExternal': None}

  def __getitem__(self, k):
    return self.msgs[k]

  def step(self, fix=None):
    self.frame += 1
    self.updated['gpsLocationExternal'] = fix is not None
    if fix is not None:
      self.seen['gpsLocationExternal'] = True
      self.recv_frame['gpsLocationExternal'] = self.frame
      self.logMonoTime['gpsLocationExternal'] = int(self.frame * 0.01 * 1e9)
      self.msgs['gpsLocationExternal'] = fix


def test_card_method_end_to_end():
  from openpilot.selfdrive.car.card import Car
  card = SimpleNamespace(sm=_Sm(), gps_accel=GpsAccelEstimator(),
                         CI=SimpleNamespace(CS=SimpleNamespace(vsa_long_accel=-1.0, vsa_long_accel_valid=True)))
  fpcs = _fpcs()
  for i in range(100):  # 1 s at 100 Hz, a fix every 10 frames, braking at -1.5
    card.sm.step(_fix(v=20.0 - 1.5 * i * 0.01) if i % 10 == 0 else None)
    Car.update_accel_log_fields(card, fpcs)
  assert fpcs.gpsAccelValid and fpcs.aEgoGps == pytest.approx(-1.5, abs=0.02)
  assert fpcs.aEgoVsaValid and fpcs.aEgoVsaPitchCorrected == pytest.approx(-1.0 - G * math.sin(0.02), abs=1e-5)
  for _ in range(31):  # GPS goes quiet: invalid after 0.3 s, VSA unaffected
    card.sm.step()
    Car.update_accel_log_fields(card, fpcs)
  assert not fpcs.gpsAccelValid and fpcs.aEgoVsaValid


def test_card_method_gps_failure_keeps_vsa():
  from openpilot.selfdrive.car.card import Car
  card = SimpleNamespace(sm=_Sm(), gps_accel=GpsAccelEstimator(),
                         CI=SimpleNamespace(CS=SimpleNamespace(vsa_long_accel=-1.0, vsa_long_accel_valid=True)))
  card.sm.step(SimpleNamespace(vNED=None, speedAccuracy=0.3, hasFix=True))  # malformed fix raises inside update
  fpcs = _fpcs()
  Car.update_accel_log_fields(card, fpcs)
  assert card.gps_accel is None and fpcs.aEgoVsa == -1.0 and math.isnan(fpcs.aEgoVsaPitchCorrected)
