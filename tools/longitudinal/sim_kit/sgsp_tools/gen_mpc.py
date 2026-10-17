import sys, runpy, os
sys.path.insert(0, "tools/longitudinal/sim_kit")
import sgsp_loader; sgsp_loader.install()
d = os.path.join(sgsp_loader.SGSP, "openpilot/selfdrive/controls/lib/longitudinal_mpc_lib")
os.chdir(d)
runpy.run_path("long_mpc.py", run_name="__main__")
