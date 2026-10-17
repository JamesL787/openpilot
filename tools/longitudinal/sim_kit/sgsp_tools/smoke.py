import sys; sys.path.insert(0, "tools/longitudinal/sim_kit")
import sgsp_loader; sgsp_loader.install()
from openpilot.selfdrive.controls.lib.longitudinal_planner import LongitudinalPlanner
import openpilot.selfdrive.controls.lib.longitudinal_planner as lp, inspect
print(lp.__file__)
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib import long_mpc; print(long_mpc.__file__)
from cereal import car
CP = car.CarParams.new_message(); CP.longitudinalActuatorDelay = 0.3
p = LongitudinalPlanner(CP, 0.0, 0.0, 0.05, 0)
print("ok", type(p.mpc).__module__, inspect.signature(p.update))
