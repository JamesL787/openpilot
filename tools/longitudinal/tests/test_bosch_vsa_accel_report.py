import math

import numpy as np
import pytest

from openpilot.tools.longitudinal import bosch_vsa_accel_report as r


def kin_bytes(raw9: int) -> bytes:
  """0x094 payload with LONG_ACCEL (opendbc 24|9@0-) set to raw9 and every other bit zero."""
  raw9 &= 0x1FF
  b = bytearray(8)
  b[3] = (raw9 >> 8) & 0x01
  b[4] = raw9 & 0xFF
  return bytes(b)


@pytest.mark.parametrize("accel", [-4.0, -1.0, 0.0, 0.5, 2.0])
def test_long_accel_dbc_is_forward_positive(accel):
  raw = int(round(-accel / 0.049))
  assert r.long_accel_dbc(kin_bytes(raw)) == pytest.approx(accel, abs=0.05)


def test_long_accel_firmware_decode_matches_dbc_within_scale_tolerance():
  # firmware reads the same window as 10-bit offset-binary; bit 25 = !sign keeps the two equal up to the
  # 49/1024 vs 0.049 scale difference (2.4 %, docs/xcheck_openpilot_2026-10-03.md)
  for accel in (-3.0, -1.0, 1.0, 3.0):
    raw9 = int(round(-accel / 0.049)) & 0x1FF
    b = bytearray(kin_bytes(raw9))
    if not raw9 & 0x100:
      b[3] |= 0x02
    fw, dbc = r.long_accel_fw(bytes(b)), r.long_accel_dbc(bytes(b))
    assert math.copysign(1, fw) == math.copysign(1, dbc)
    assert fw == pytest.approx(dbc, rel=0.03)


def test_moving_mean_is_causal_5_tap():
  x = np.array([5.0, 0, 0, 0, 0, 0, 10.0])
  y = r.moving_mean(x, 5)
  assert y[0] == 5.0
  assert y[4] == pytest.approx(1.0)
  assert y[5] == pytest.approx(0.0)
  assert y[6] == pytest.approx(2.0)


def test_wheel_accel_recovers_constant_decel():
  t = np.arange(0, 5, 0.01)
  v = 25.0 - 2.0 * t
  a = r.wheel_accel_fw(t, v, lpf_tau=0.1)
  assert np.median(a[200:]) == pytest.approx(-2.0, abs=0.02)


def test_fw_min_selects_harder_decel():
  a_wheel = np.full(10, -1.0)
  a_vsa = np.full(10, -2.0)
  assert np.all(r.fw_min_accel(a_wheel, a_vsa) == -2.0)
  assert np.all(r.fw_min_accel(a_vsa, a_wheel) == -2.0)


def test_stock_slew_limits_onset_only():
  dt = 0.01
  cmd = np.r_[np.zeros(10), np.full(100, -3.0), np.zeros(10)]
  s = r.stock_slew(cmd, dt)
  assert np.min(np.diff(s)) >= -5.0 * dt - 1e-9
  # -3 at -5 m/s^3 takes 0.6 s
  assert s[10 + 59] > -3.0
  assert s[10 + 61] == pytest.approx(-3.0)
  # release is not limited
  assert s[-1] == 0.0


def test_bin_delivery_measures_over_brake_with_lag():
  t = np.arange(0, 20, 0.01)
  cmd = np.full_like(t, -3.3)
  delivered = np.roll(cmd * 1.27, int(0.35 / 0.01))  # 27 % over-brake, 0.35 s late
  active = np.ones_like(t, dtype=bool)
  rows = {(lo, hi): (n, med) for lo, hi, n, med, _, _ in r.bin_delivery(t, cmd, delivered, active, lag=0.35)}
  n, med = rows[(-3.6, -3.0)]
  assert n > 1000
  assert med == pytest.approx(-0.27 * 3.3, abs=0.01)
  assert rows[(-1.0, -0.5)][0] == 0


def test_bin_delivery_ignores_inactive():
  t = np.arange(0, 5, 0.01)
  rows = r.bin_delivery(t, np.full_like(t, -2.2), np.full_like(t, -2.2), np.zeros_like(t, dtype=bool))
  assert all(row[2] == 0 for row in rows)


def test_ols_recovers_ego_accel_leak():
  rng = np.random.default_rng(0)
  a = rng.uniform(-3, 1, 2000)
  y = 0.2 + 0.1 * a + rng.normal(0, 0.01, len(a))
  coef, r2, n = r.ols(y, a)
  assert coef[0] == pytest.approx(0.2, abs=0.01)
  assert coef[1] == pytest.approx(0.1, abs=0.01)
  assert r2 > 0.95 and n == 2000


def test_range_rate_breaks_on_track_change():
  t = np.arange(0, 4, 0.05)
  d = 30.0 - 2.0 * t
  trk = np.where(t < 2.0, 7, 9).astype(float)
  rr = r.range_rate(t, d, trk)
  assert np.nanmedian(rr) == pytest.approx(-2.0)
  assert np.isnan(rr[np.argmin(np.abs(t - 2.0))])


def test_report_end_to_end_on_synthetic_logs():
  t_cs = np.arange(0, 30, 0.01)
  v = np.clip(25 - 1.0 * np.clip(t_cs - 10, 0, 10), 0, None)
  a = np.where((t_cs > 10) & (t_cs < 20), -1.0, 0.0)
  cs = np.column_stack([t_cs, v, a, v])
  t_k = np.arange(0, 30, 0.02)
  ak = np.interp(t_k, t_cs, a)
  kin = np.column_stack([t_k, ak, ak])
  cmd = np.where((t_cs > 9.65) & (t_cs < 19.65), -1.2, 0.0)
  cc = np.column_stack([t_cs, np.ones_like(t_cs), cmd, np.zeros_like(t_cs)])
  t_r = np.arange(0, 30, 0.05)
  rs = np.column_stack([t_r, 40 - 0.5 * t_r, np.full_like(t_r, -0.5), np.full_like(t_r, 3)])
  text = r.report({'kin': kin, 'kin_bus': 0, 'cs': cs, 'cc': cc, 'rs': rs}, lag=0.35, fw_lpf=0.1)
  assert '0x094 KINEMATICS: bus 0' in text
  assert '[-1.5,-1.0)' in text
  assert 'U11 - d(dRel)/dt vs aVsa' in text


def test_report_without_kinematics_says_so():
  empty = np.zeros((0, 3))
  assert 'no 0x094' in r.report({'kin': empty, 'kin_bus': None, 'cs': empty, 'cc': empty, 'rs': empty}, 0.35, 0.1)
