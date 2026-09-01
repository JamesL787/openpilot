"""Controls.__init__ must resolve the lateral-controller dispatch AFTER self.LaC exists, and the
dispatch must call every controller with an argument count it accepts.

Both defects this guards against were shipped and caught in review, not by testing:
  1. controlsd passed the integrator-freeze flag positionally to every controller, but only
     LatControlPID accepts it -> TypeError on the first control frame for angle/curvature/torque/
     NNFF cars, regardless of gate state.
  2. the fix for (1) resolved the dispatch before self.LaC was assigned -> AttributeError in
     __init__ on EVERY car, including the one it was meant to help.
A syntax check catches neither. This does.
"""
import inspect
from pathlib import Path

from openpilot.selfdrive.controls.lib.latcontrol_pid import LatControlPID
from openpilot.selfdrive.controls.lib.latcontrol_angle import LatControlAngle
from openpilot.selfdrive.controls.lib.latcontrol_curvature import LatControlCurvature
from openpilot.selfdrive.controls.lib.latcontrol_torque import LatControlTorque

FLAG = "integrator_wind_blocked"
BASE_ARGS = 11  # active, CS, VM, params, steer_limited_by_safety, desired_curvature,
                # curvature_limited, lat_delay, calibrated_pose, model_data, starpilot_toggles


class TestLateralDispatch:
  def test_only_pid_takes_the_flag(self):
    assert FLAG in inspect.signature(LatControlPID.update).parameters
    for cls in (LatControlAngle, LatControlCurvature, LatControlTorque):
      assert FLAG not in inspect.signature(cls.update).parameters, \
        f"{cls.__name__} unexpectedly accepts {FLAG}; the dispatch assumes it does not"

  def test_every_controller_accepts_what_the_dispatch_sends(self):
    """Mirrors controlsd: BASE_ARGS always, plus one iff the controller declares the flag."""
    for cls in (LatControlPID, LatControlAngle, LatControlCurvature, LatControlTorque):
      params = list(inspect.signature(cls.update).parameters)[1:]  # drop self
      takes = FLAG in params
      sent = BASE_ARGS + (1 if takes else 0)
      required = [p for p, v in list(inspect.signature(cls.update).parameters.items())[1:]
                  if v.default is inspect.Parameter.empty]
      assert len(required) <= sent <= len(params), \
        f"{cls.__name__}: dispatch sends {sent} args, signature takes {len(required)}..{len(params)}"

  def test_resolution_happens_after_every_lac_assignment(self):
    """The guard must not read self.LaC before the controller-selection block has run.

    Read as text rather than importing controlsd: that module pulls compiled device-only
    extensions, and this defect is an ordering property of the source, so a textual check is both
    sufficient and runnable anywhere.
    """
    src = Path(__file__).resolve().parents[2] / "controls" / "controlsd.py"
    lines = src.read_text().splitlines()
    guard = next(i for i, l in enumerate(lines) if "_lac_takes_wind_blocked =" in l)
    last_assignment = max(i for i, l in enumerate(lines) if "self.LaC = " in l)
    assert guard > last_assignment, (
      f"dispatch resolved at line {guard + 1}, before the last self.LaC assignment at "
      f"line {last_assignment + 1} -> AttributeError in Controls.__init__")
