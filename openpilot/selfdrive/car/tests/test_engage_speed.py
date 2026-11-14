from types import SimpleNamespace

from openpilot.common.constants import CV
from openpilot.selfdrive.car.cruise import E2E_ENGAGE_SPEED_KPH, VCruiseHelper, engage_initial_speed, engage_keeps_speed
from opendbc.car.structs import car


def test_only_stock_planner_experimental_gets_66_mph():
  assert engage_initial_speed(40, True, True) == E2E_ENGAGE_SPEED_KPH
  assert engage_initial_speed(40, False, True) == 40  # Chill keeps the saved speed
  assert engage_initial_speed(40, True, False) == 40  # StarPilot planner keeps the saved speed
  assert round(E2E_ENGAGE_SPEED_KPH * CV.KPH_TO_MPH) == 66


def _engage(v_ego_mph, initial_speed, keep_speed=False):
  helper = VCruiseHelper(car.CarParams(pcmCruise=False, openpilotLongitudinalControl=True))
  cs = SimpleNamespace(vEgo=v_ego_mph * CV.MPH_TO_MS, buttonEvents=[])
  helper.initialize_v_cruise(cs, True, resume=False, initial_speed=initial_speed, keep_speed=keep_speed)
  return helper.v_cruise_kph * CV.KPH_TO_MPH


def test_engage_sets_66_or_current_speed_if_faster():
  assert round(_engage(30, E2E_ENGAGE_SPEED_KPH)) == 66
  assert round(_engage(75, E2E_ENGAGE_SPEED_KPH)) == 75
  assert round(_engage(30, 40)) == 30  # Chill: engage speed


def test_only_stock_planner_chill_keeps_speed():
  assert engage_keeps_speed(False, True)
  assert not engage_keeps_speed(True, True)  # Experimental: 66 mph rule
  assert not engage_keeps_speed(False, False)  # StarPilot planner unchanged


def test_chill_engage_below_25_mph_keeps_current_speed():
  assert round(_engage(13, 40, keep_speed=True)) == 13
  assert round(_engage(30, 40, keep_speed=True)) == 30
  assert round(_engage(13, 40)) == 25  # without it, the 40 kph floor applies
  assert round(_engage(2, 40, keep_speed=True)) == 25  # near standstill falls back to the saved speed

