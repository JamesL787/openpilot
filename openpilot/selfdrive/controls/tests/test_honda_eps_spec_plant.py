import math

import numpy as np
import pytest

from opendbc.car.honda import steer_ratio as sr
import openpilot.selfdrive.controls.lib.honda_eps_firmware_ff as eps_ff
import openpilot.selfdrive.controls.lib.honda_eps_calibrations as eps_cal
import openpilot.selfdrive.controls.lib.honda_eps_rack_map as rack
import openpilot.selfdrive.controls.lib.honda_eps_spec_plant as spec

INV = sr.HONDA_VGR_INVERSE_BY_PROFILE
# The cars whose rack maps were fitted against their yaw sensor: (specs, A table, rack table, column load)
MEASURED = {
  "clarity": (spec.CLARITY_SPEC, INV[sr.HONDA_VGR_CLARITY_TRW_A020], rack.CLARITY_TRW_A020_RACK, eps_cal.CLARITY_TRW_A020_LOAD),
  "c020": (spec.CIVIC_SPORT_SEDAN_SPEC, INV[sr.HONDA_VGR_CIVIC_TBA_C020], rack.CIVIC_TBA_C020_RACK, eps_cal.CIVIC_TBA_C020_LOAD),
  "insight": (spec.INSIGHT_SPEC, INV[sr.HONDA_VGR_INSIGHT_TXM_A040], rack.INSIGHT_TXM_A040_RACK, eps_cal.INSIGHT_TXM_A040_LOAD),
  "teg": (spec.CIVIC_2016_SEDAN_SPEC, INV[sr.HONDA_VGR_CIVIC_TBA_C120], rack.CIVIC_TEG_A010_RACK, eps_cal.CIVIC_TEG_A010_LOAD),
}


def _r0_gain(name):  # measured R0 / (lin at lock / road angle at lock)
  s, inv, table, _ = MEASURED[name]
  return spec.r0_of_table(table, inv) / (spec.linear_angle(inv, s.lock_deg) / (s.lock_deg / s.lock_ratio))


def _slip_gain(name):
  s, _, table, _ = MEASURED[name]
  return table.slip_factor / spec.spec_slip_factor(s) * spec.SPEC_SLIP_GAIN


def test_the_constants_are_the_mean_over_the_measured_cars():
  assert spec.SPEC_R0_GAIN == pytest.approx(np.mean([_r0_gain(n) for n in MEASURED]), abs=0.002)
  assert spec.SPEC_SLIP_GAIN == pytest.approx(np.mean([_slip_gain(n) for n in MEASURED]), rel=0.01)


@pytest.mark.parametrize("name", MEASURED)
def test_r0_predicts_each_measured_car_held_out(name):
  # the gain from the other three cars only: within 2.6% (Insight -2.5, TEG +2.1, C020 +0.6, Clarity -0.1)
  s, inv, table, _ = MEASURED[name]
  gain = np.mean([_r0_gain(n) for n in MEASURED if n != name])
  predicted = gain * spec.linear_angle(inv, s.lock_deg) / (s.lock_deg / s.lock_ratio)
  assert predicted == pytest.approx(spec.r0_of_table(table, inv), rel=0.026)


@pytest.mark.parametrize("name", MEASURED)
def test_the_tan_shape_reproduces_each_measured_rack_map(name):
  # with the car's own R0 the shape alone is within 2% from 15 to 230 deg (worst: the Insight's flat 4-36 deg cells)
  s, inv, table, _ = MEASURED[name]
  r0 = spec.r0_of_table(table, inv)
  for angle, ratio in zip(table.ratio_bp, table.ratio_v, strict=True):
    if 15.0 <= angle <= 230.0:
      assert spec.tan_ratio(spec.linear_angle(inv, angle), r0) == pytest.approx(ratio, rel=0.02), angle


@pytest.mark.parametrize("name", MEASURED)
def test_the_spec_rack_map_steers_each_measured_car_within_its_spread(name):
  # held out: the curvature the spec map predicts for a wheel angle, against the car's own map, 12-230 deg
  s, inv, table, _ = MEASURED[name]
  gain = np.mean([_r0_gain(n) for n in MEASURED if n != name])
  r0 = gain * spec.linear_angle(inv, s.lock_deg) / (s.lock_deg / s.lock_ratio)
  for angle, ratio in zip(table.ratio_bp, table.ratio_v, strict=True):
    if 12.0 <= angle <= 230.0:
      assert spec.tan_ratio(spec.linear_angle(inv, angle), r0) == pytest.approx(ratio, rel=0.045), angle


@pytest.mark.parametrize("name", MEASURED)
def test_slip_factor_predicts_each_measured_car_held_out(name):
  s, _, table, _ = MEASURED[name]
  gain = np.mean([_slip_gain(n) for n in MEASURED if n != name])
  assert spec.spec_slip_factor(s) / spec.SPEC_SLIP_GAIN * gain == pytest.approx(table.slip_factor, rel=0.10)


def _hold(load, r0, wheelbase, v):  # counts to hold 1 m/s^2 at speed v, bias aside
  angle = math.degrees(wheelbase / v ** 2) * r0
  return load.k0 * angle + load.k1 * angle * v * v


def _rate(load, rate):
  return load.c * rate + load.friction * math.tanh(rate / eps_ff.FRICTION_WIDTH_DEG_S)


@pytest.mark.parametrize("name,s,profile,load", [
  *[(n, m[0], None, m[3]) for n, m in MEASURED.items()],
  ("crv", spec.CRV_2017_SPEC, sr.HONDA_VGR_CRV_TLA_A040, eps_cal.CRV_TLA_A040_LOAD),
])
def test_the_spec_load_is_close_to_every_measured_load(name, s, profile, load):
  # holds within 20%, turn rates within 25% of the car's own fit; copying the Clarity's load is up to 58% off
  inv = INV[profile] if profile else MEASURED[name][1]
  r0 = spec.spec_r0(s, inv)
  predicted = eps_ff.ColumnLoadModel(**spec.spec_load_terms(s, inv))
  for v in (5.0, 10.0, 20.0, 30.0):
    assert _hold(predicted, r0, s.wheelbase, v) == pytest.approx(_hold(load, r0, s.wheelbase, v), rel=0.20), v
  for rate in (30.0, 100.0):
    assert _rate(predicted, rate) == pytest.approx(_rate(load, rate), rel=0.25), rate


@pytest.mark.parametrize("cal,s,profile", [
  (eps_cal.CIVIC_TBA_C120, spec.CIVIC_2019_SEDAN_SPEC, sr.HONDA_VGR_CIVIC_TBA_C120),
  (eps_cal.CRV_TLA_A040, spec.CRV_2017_SPEC, sr.HONDA_VGR_CRV_TLA_A040),
  (eps_cal.CRV_TLA_A220, spec.CRV_2020_SPEC, sr.HONDA_VGR_CRV_TLA_A040),
])
def test_cars_without_a_yaw_fit_steer_on_their_spec_rack_map(cal, s, profile):
  assert cal.rack == spec.spec_rack_table(s, INV[profile])
  assert eps_cal.provenance(cal)["rack"].startswith("spec")
  assert all(b <= a for a, b in zip(cal.rack.ratio_v, cal.rack.ratio_v[1:], strict=False))  # quickens off centre only
  assert cal.rack.ratio_v[0] == pytest.approx(spec.spec_r0(s, INV[profile]), rel=1e-3)
  rack_map = rack.HondaEpsRackMap(s.wheelbase, INV[profile], cal.rack)
  for v in (3.0, 15.0, 30.0):
    for angle in (-300.0, -40.0, 3.0, 90.0, 380.0):
      assert rack_map.angle_from_curvature(rack_map.curvature_from_angle(angle, v, 0.01), v, 0.01) == pytest.approx(angle, abs=1e-3)


def test_measured_cars_keep_their_own_fits():
  assert eps_cal.CLARITY_TRW_A020.rack is rack.CLARITY_TRW_A020_RACK
  assert eps_cal.CIVIC_TBA_C020.rack is rack.CIVIC_TBA_C020_RACK
  assert eps_cal.INSIGHT_TXM_A040.rack is rack.INSIGHT_TXM_A040_RACK
  assert eps_cal.CIVIC_TEG_A010.rack is rack.CIVIC_TEG_A010_RACK
  assert eps_cal.CIVIC_TBA_A030.rack is rack.CIVIC_TEG_A010_RACK  # the same car on the same A table


def test_past_the_table_end_the_linear_angle_holds_the_last_divisor():
  inv = INV[sr.HONDA_VGR_INSIGHT_TXM_A040]   # the Insight locks at 457 deg, past its table's 430.5
  end_angle, end_linear = inv[1][-1], inv[0][-1]
  y = sr._INSIGHT_TXM_A040_POSITION_Y
  assert spec.linear_angle(inv, end_angle + 20.0) == pytest.approx((end_angle + 20.0) * y[-1] / y[0], rel=1e-4)
  assert spec.linear_angle(inv, end_angle) == pytest.approx(end_linear)
