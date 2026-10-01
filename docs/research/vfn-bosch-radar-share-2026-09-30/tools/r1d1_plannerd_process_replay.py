#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from openpilot.selfdrive.test.process_replay import replay_process_with_name
from openpilot.tools.lib.logreader import LogReader, ReadMode


ROUTE = "11c8fa231c0499ed/000001d1--43392afe10"


def main() -> None:
  parser = argparse.ArgumentParser()
  parser.add_argument("--segment", type=int, required=True)
  parser.add_argument("--output", required=True)
  args = parser.parse_args()

  lr = list(LogReader(f"{ROUTE}/{args.segment}/r", default_mode=ReadMode.RLOG, sort_by_time=True))
  car_times = [m.logMonoTime * 1e-9 for m in lr if m.which() == "carState"]
  route_base = min(car_times) - args.segment * 60.0
  output = replay_process_with_name("plannerd", lr, disable_progress=True)
  rows = []
  for msg in output:
    if msg.which() != "longitudinalPlan":
      continue
    plan = msg.longitudinalPlan
    rows.append({
      "t": msg.logMonoTime * 1e-9 - route_base,
      "aTarget": float(plan.aTarget),
      "source": str(plan.longitudinalPlanSource).rsplit(".", 1)[-1],
      "fcw": bool(plan.fcw),
      "shouldStop": bool(plan.shouldStop),
      "hasLead": bool(plan.hasLead),
      "speeds": [float(x) for x in list(plan.speeds)[:6]],
      "accels": [float(x) for x in list(plan.accels)[:6]],
    })
  with open(args.output, "w") as f:
    json.dump(rows, f, indent=2)
    f.write("\n")
  print(f"wrote {len(rows)} planner rows to {args.output}")


if __name__ == "__main__":
  main()
