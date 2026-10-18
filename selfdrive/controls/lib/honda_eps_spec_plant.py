"""A Honda's steering plant predicted from its published specs and its EPS image's A table, for cars nobody has
measured. Only numpy and the A tables here, so offline tools can use it.

Measured cars keep their own fits; this is what an unmeasured car starts from, and every value carries its spread
over the cars that were measured, held out one at a time (2026-10-18; the analysis is summarised below each constant).

Geometry. Every yaw-fitted rack map (honda_eps_rack_map) is the firmware A table, then a tan, then ONE ratio per car:
  curvature * L * (1 - sf v^2) = tan(lin / R0),   lin = the A table's linear angle (radians)
which reproduces the Clarity, C020, Insight and TEG tables within 2% from 15 to 230 deg. R0 comes from the
road-wheel angle at lock that Honda publishes (lock-to-lock turns and the steering ratio Honda quotes, which is the
ratio at lock) seen through the A table. The slip factor comes from the axle loads (cornering stiffness ~ load^0.8).

Column load. The tyres' aligning torque at the steering wheel is that torque / R, and a lateral acceleration needs
R times more wheel angle, so the angle terms per steering-wheel degree go as front-axle mass / R0^2. The rate terms
(viscous, friction) are the same on every car measured.
"""
from dataclasses import dataclass

import numpy as np

from openpilot.selfdrive.controls.lib.honda_eps_rack_map import RackMapTable

LB = 0.45359237
# The slip-factor masses: curb weight plus an 80 kg driver, split at the curb front-weight fraction, plus another
# 50 kg on the front axle. That counts the driver's front share twice; SPEC_SLIP_GAIN is fitted through this same
# split, so it absorbs that. With the driver split once (50 front, 30 rear) and the gain refitted (0.00555), the
# held-out error is no better (6.1 % rms against 5.8 %) and no spec car's slip factor moves more than 1.2 % (2026-10-18).
DRIVER_KG = 80.0
DRIVER_FRONT_KG = 50.0
LOAD_CARGO_KG = 136.0  # the load masses are curb weight plus openpilot's STD_CARGO_KG, as CarParams.mass is

# R0 = SPEC_R0_GAIN * lin(lock) / road angle at lock. Mean over the four yaw-fitted cars; held out one at a time
# 1.142-1.155, which predicts R0 within -0.1 (Clarity), +0.6 (C020), -2.5 (Insight), +2.1 (TEG) %: 1.6% rms, 2.5% worst.
# The Insight and TEG share published geometry yet differ 4.4% measured, so published specs cannot do better.
SPEC_R0_GAIN = 1.149
# sf = -SPEC_SLIP_GAIN * (m_front^0.2 - m_rear^0.2) / L. Held out: Clarity -9.7, C020 +4.4, Insight +3.9, TEG +2.4 %.
SPEC_SLIP_GAIN = 0.00416
# ColumnLoadModel terms, medians over the Clarity, C020, TEG, Insight and CR-V A040 loads refitted with one recipe
# (|driver torque| < 300). Held out one car at a time: holds +-12% mean (worst 28%), turn rates +-15% (worst 30%);
# one car's own fit moves 4-25% from drive to drive, so that is the floor. Copying the Clarity's load misses by 40%.
LOAD_K0_PER_MF_R2 = -1.644      # k0 = this * m_front / R0^2
LOAD_K1_PER_MF_R2 = -0.0451     # k1 = this * m_front / R0^2
LOAD_KROLL_PER_MF_R = -0.0609   # kroll = this * m_front / R0 (weak: the cars' own roll terms scatter widely)
LOAD_C = -6.14
LOAD_FRICTION = -310.0


@dataclass(frozen=True)
class HondaSteeringSpec:
  """What Honda publishes for one car (hondanews.com / hondainfocenter.com), plus openpilot's wheelbase."""
  lock_turns: float         # steering-wheel turns lock to lock
  lock_ratio: float         # the steering ratio Honda quotes: steering-wheel angle / road-wheel angle at lock
  curb_mass_lb: float
  front_weight_fraction: float
  wheelbase: float          # m, opendbc CarSpecs

  @property
  def lock_deg(self) -> float:  # steering-wheel angle at lock, one side
    return self.lock_turns * 180.0


# Specs for every PTM image's car. The first four are the cars whose rack maps were measured (and set the constants).
CLARITY_SPEC = HondaSteeringSpec(lock_turns=2.41, lock_ratio=12.72, curb_mass_lb=4052, front_weight_fraction=0.57, wheelbase=2.75)
CIVIC_SPORT_SEDAN_SPEC = HondaSteeringSpec(lock_turns=2.11, lock_ratio=11.12, curb_mass_lb=2847, front_weight_fraction=0.608,
                                           wheelbase=2.70)  # 2019 Civic Sport sedan (TBA-C020)
INSIGHT_SPEC = HondaSteeringSpec(lock_turns=2.54, lock_ratio=12.58, curb_mass_lb=3000, front_weight_fraction=0.61, wheelbase=2.70)
CIVIC_2016_SEDAN_SPEC = HondaSteeringSpec(lock_turns=2.22, lock_ratio=10.93, curb_mass_lb=2800, front_weight_fraction=0.61,
                                          wheelbase=2.70)  # 2016-18 Civic sedan (TEG-A010, TBA-A030)
CIVIC_2019_SEDAN_SPEC = HondaSteeringSpec(lock_turns=2.22, lock_ratio=10.94, curb_mass_lb=2850, front_weight_fraction=0.609,
                                          wheelbase=2.70)  # 2019-21 Civic sedan LX/EX (TBA-C120)
CIVIC_HATCH_SPORT_SPEC = HondaSteeringSpec(lock_turns=2.11, lock_ratio=11.12, curb_mass_lb=2900, front_weight_fraction=0.60,
                                           wheelbase=2.70)  # Civic hatchback Sport (TGG-A120)
CRV_2017_SPEC = HondaSteeringSpec(lock_turns=2.30, lock_ratio=12.3, curb_mass_lb=3398, front_weight_fraction=0.59,
                                  wheelbase=2.66)  # CR-V 2017-19 (TLA-A040)
CRV_2020_SPEC = HondaSteeringSpec(lock_turns=2.30, lock_ratio=12.3, curb_mass_lb=3514, front_weight_fraction=0.58,
                                  wheelbase=2.66)  # CR-V 2020+ (TLA-A220)


def linear_angle(vgr_inverse, physical_deg: float) -> float:
  """The A table's linear angle (deg) for a physical one. Past the last knot the firmware holds its last divisor, so
  linear = physical * Y_end / Y0 exactly (= linear / physical at the last knot)."""
  linear_bp, angle_bp = (np.asarray(x, dtype=float) for x in vgr_inverse)
  if physical_deg <= angle_bp[-1]:
    return float(np.interp(physical_deg, angle_bp, linear_bp))
  return float(physical_deg * linear_bp[-1] / angle_bp[-1])


def spec_r0(spec: HondaSteeringSpec, vgr_inverse) -> float:
  """The rack ratio after the A table, at centre."""
  road_lock_deg = spec.lock_deg / spec.lock_ratio
  return SPEC_R0_GAIN * linear_angle(vgr_inverse, spec.lock_deg) / road_lock_deg


def spec_slip_factor(spec: HondaSteeringSpec) -> float:
  mass = spec.curb_mass_lb * LB + DRIVER_KG
  front = mass * spec.front_weight_fraction + DRIVER_FRONT_KG
  rear = mass - front
  return -SPEC_SLIP_GAIN * (front ** 0.2 - rear ** 0.2) / spec.wheelbase


def tan_ratio(linear_deg, r0: float):
  """The effective rack ratio (honda_eps_rack_map's) at a linear angle: lin / tan(lin / R0), -> R0 at centre."""
  lin = np.radians(np.maximum(np.asarray(linear_deg, dtype=float), 1e-6))
  return lin / np.tan(lin / r0)


def spec_rack_table(spec: HondaSteeringSpec, vgr_inverse) -> RackMapTable:
  """A RackMapTable from the specs: the tan shape on the A table, up to lock (or the table's end)."""
  r0 = spec_r0(spec, vgr_inverse)
  end = min(spec.lock_deg, float(np.asarray(vgr_inverse[1], dtype=float)[-1]))
  angles = tuple(float(a) for a in np.round(np.linspace(5.0, end, 12), 1))
  ratios = tuple(round(float(r), 3) for r in tan_ratio([linear_angle(vgr_inverse, a) for a in angles], r0))
  return RackMapTable(ratio_bp=angles, ratio_v=ratios, slip_factor=round(spec_slip_factor(spec), 6))


def load_front_mass(spec: HondaSteeringSpec) -> float:
  return (spec.curb_mass_lb * LB + LOAD_CARGO_KG) * spec.front_weight_fraction


def spec_load_terms(spec: HondaSteeringSpec, vgr_inverse) -> dict:
  """ColumnLoadModel keyword arguments. Bias 0: a sensor offset or road crown, not predictable."""
  mf, r0 = load_front_mass(spec), spec_r0(spec, vgr_inverse)
  return dict(k0=LOAD_K0_PER_MF_R2 * mf / r0 ** 2, k1=LOAD_K1_PER_MF_R2 * mf / r0 ** 2, c=LOAD_C,
              friction=LOAD_FRICTION, bias=0.0, kroll=LOAD_KROLL_PER_MF_R * mf / r0)


def r0_of_table(table: RackMapTable, vgr_inverse) -> float:
  """The tan-shape R0 that best fits a measured rack table (angles of 12 deg and up), for checks and tools."""
  angles = np.asarray(table.ratio_bp, dtype=float)
  keep = angles >= 12.0
  lin = np.array([linear_angle(vgr_inverse, a) for a in angles[keep]])
  measured = np.asarray(table.ratio_v, dtype=float)[keep]
  candidates = np.linspace(10.0, 22.0, 12001)
  errors = [np.mean((tan_ratio(lin, r) / measured - 1.0) ** 2) for r in candidates]
  return float(candidates[int(np.argmin(errors))])

