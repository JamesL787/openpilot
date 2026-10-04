from types import SimpleNamespace

import pytest

from openpilot.selfdrive.controls.lib import longitudinal_planner as lp


def _lead(d, v_rel, a=0.0, status=True):
  return SimpleNamespace(status=status, dRel=d, vRel=v_rel, aLeadK=a)


def test_switch_is_off_by_default():
  assert lp.BRAKE_ONSET_LIMIT is False


def test_far_slow_closing_gets_the_gentlest_jerk():
  # 80 m, closing 5 m/s -> TTC 16 s
  assert lp.brake_onset_jerk((_lead(80.0, -5.0), None), 25.0) == pytest.approx(lp.BRAKE_ONSET_JERK_V[-1])


def test_jerk_allowance_grows_as_ttc_shrinks():
  far = lp.brake_onset_jerk((_lead(60.0, -10.0),), 20.0)  # 6 s
  mid = lp.brake_onset_jerk((_lead(45.0, -10.0),), 20.0)  # 4.5 s
  assert far < mid < lp.BRAKE_ONSET_JERK_V[0]


@pytest.mark.parametrize("leads,v_ego", [
  ((_lead(30.0, -10.0),), 20.0),               # TTC 3 s: urgent
  ((_lead(25.0, -1.0),), 20.0),                # inside 1.5 s of gap
  ((_lead(8.0, 0.0),), 3.0),                   # inside the 10 m floor
  ((_lead(80.0, -2.0, a=-1.2),), 25.0),        # lead braking
  ((None, _lead(5.0, 0.0, status=False)), 25.0),  # no active lead
  ((_lead(90.0, -2.0), _lead(30.0, -12.0)), 25.0),  # the worst lead decides
])
def test_limit_is_off_when_anything_is_urgent_or_unknown(leads, v_ego):
  assert lp.brake_onset_jerk(leads, v_ego) is None


def test_limited_target_slows_only_a_falling_target():
  dt = 0.05
  assert lp.brake_onset_limited_target(-0.2, -1.5, dt, 1.5) == pytest.approx(-0.2 - 1.5 * dt)
  assert lp.brake_onset_limited_target(-1.0, -0.5, dt, 1.5) == pytest.approx(-0.5)  # release untouched
  assert lp.brake_onset_limited_target(-0.2, -1.5, dt, None) == pytest.approx(-1.5)
  assert lp.brake_onset_limited_target(1.0, 0.03, dt, 1.5) == pytest.approx(0.03)   # throttle cut untouched
  assert lp.brake_onset_limited_target(0.8, -1.0, dt, 1.5) == pytest.approx(-1.5 * dt)  # ramps from 0, not from +0.8


def test_ramp_reaches_the_target_within_abs_a_over_j():
  a, dt, j = 0.0, 0.05, 1.5
  for _ in range(int(1.5 / (j * dt)) + 1):
    a = lp.brake_onset_limited_target(a, -1.5, dt, j)
  assert a == pytest.approx(-1.5)


def test_toggle_sits_under_advanced_longitudinal_tuning_in_galaxy_and_device_ui():
  import json
  from pathlib import Path
  root = Path(__file__).resolve().parents[3]
  layout = json.loads((root / "starpilot/common/assets/device_settings_layout.json").read_text())
  found = []

  def walk(node):
    if isinstance(node, dict):
      if node.get("key") == "BrakeOnsetLimit":
        found.append(node)
      for v in node.values():
        walk(v)
    elif isinstance(node, list):
      for v in node:
        walk(v)
  walk(layout)
  assert len(found) == 1
  assert found[0]["parent_key"] == "AdvancedLongitudinalTune" and found[0]["ui_type"] == "toggle"
  ui = (root / "selfdrive/ui/layouts/settings/starpilot/longitudinal.py").read_text()
  assert 'SettingRow("BrakeOnsetLimit", "toggle"' in ui
  assert '{"BrakeOnsetLimit", {PERSISTENT, BOOL, "0", "0", 3}}' in (root / "common/params_keys.h").read_text()
  assert 'toggle.brake_onset_limit = False' in (root / "starpilot/common/starpilot_variables.py").read_text()
