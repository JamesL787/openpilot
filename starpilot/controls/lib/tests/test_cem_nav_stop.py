from types import SimpleNamespace

from openpilot.starpilot.controls.lib.conditional_experimental_mode import ConditionalExperimentalMode


def _cem(nav_state):
  cem = ConditionalExperimentalMode.__new__(ConditionalExperimentalMode)
  cem.starpilot_planner = SimpleNamespace(starpilot_vcruise=SimpleNamespace(_nav_instruction_state=nav_state))
  return cem


def test_d117_nav_control_hands_off_within_eight_seconds_or_80_m():
  nav = {"valid": True, "controlKind": "signal", "controlDistance": 200.0}
  assert _cem(nav).nav_control_ahead(30.0), "200 m is inside 8 s at 30 m/s"
  assert not _cem(nav).nav_control_ahead(20.0), "200 m is outside 8 s at 20 m/s"
  assert _cem({**nav, "controlDistance": 75.0}).nav_control_ahead(0.0), "80 m floor when slow"
  for kind in ("stop", "rail"):
    assert _cem({**nav, "controlKind": kind}).nav_control_ahead(30.0)


def test_d117_nav_control_ignores_missing_invalid_or_passed_controls():
  nav = {"valid": True, "controlKind": "signal", "controlDistance": 50.0}
  assert not _cem({**nav, "valid": False}).nav_control_ahead(10.0)
  assert not _cem({**nav, "controlKind": ""}).nav_control_ahead(10.0)
  assert not _cem({**nav, "controlKind": "yield"}).nav_control_ahead(10.0)
  assert not _cem({**nav, "controlDistance": 0.0}).nav_control_ahead(10.0), "already passed"
  assert not _cem({**nav, "controlDistance": "x"}).nav_control_ahead(10.0)
  assert not _cem({}).nav_control_ahead(10.0)
  assert not _cem(None).nav_control_ahead(10.0)
