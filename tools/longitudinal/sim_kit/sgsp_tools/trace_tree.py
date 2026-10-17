import sys, os, runpy, pickle
import openpilot.selfdrive.controls.lib.longitudinal_planner as LP
F = LP.__file__; LOG = []
orig = LP.LongitudinalPlanner.update
def upd(self, sm, *a, **k):
  ch = []; last = {}
  def tr(frame, ev, arg):
    if frame.f_code.co_filename != F: return None
    def lt(fr, e, ar):
      v = fr.f_locals.get("output_a_target")
      key = id(fr)
      if isinstance(v, float) and last.get(key) != v:
        ch.append((fr.f_code.co_name, fr.f_lineno, last.get(key), v)); last[key] = v
      return lt
    return lt
  sys.settrace(tr)
  try: r = orig(self, sm, *a, **k)
  finally: sys.settrace(None)
  LOG.append((sm.logMonoTime.get("modelV2") if hasattr(sm, "logMonoTime") else None, float(self.output_a_target), ch))
  return r
LP.LongitudinalPlanner.update = upd
sys.argv = ["closed_loop.py"] + sys.argv[1:3]
try: runpy.run_path("tools/longitudinal/sim_kit/closed_loop.py", run_name="__main__")
finally: pickle.dump(LOG, open(sys.argv[2] + ".trace", "wb"))
