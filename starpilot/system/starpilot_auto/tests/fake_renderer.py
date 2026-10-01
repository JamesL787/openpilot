"""Stand-in for car_ui in tests: publishes a pattern to the car slot and records touches."""

import argparse
import json
import sys
import time

from openpilot.starpilot.system.starpilot_auto.frame_source import FrameProducer
from openpilot.starpilot.system.starpilot_auto.touch import TouchReceiver


def main() -> int:
  parser = argparse.ArgumentParser()
  parser.add_argument("--frames", required=True)
  parser.add_argument("--touch", required=True)
  parser.add_argument("--record", required=True)
  args = parser.parse_args()
  producer = FrameProducer(args.frames)
  receiver = TouchReceiver(args.touch)
  deadline = time.monotonic() + 30
  idle_since = time.monotonic()
  try:
    while time.monotonic() < deadline:
      producer._next_open_check = 0.0
      request = producer.pending_request()
      touches = receiver.drain()
      if touches:
        with open(args.record, "a") as record:
          for touch in touches:
            record.write(json.dumps([touch.kind, round(touch.x, 3), round(touch.y, 3)]) + "\n")
      now_ns = time.monotonic_ns()
      if request is None:
        if time.monotonic() - idle_since > 3:
          return 0
      else:
        idle_since = time.monotonic()
        if producer.due(request, now_ns):
          producer.publish(request, bytes([200]) * (request.width * request.height * 4), now_ns)
      time.sleep(0.005)
    return 0
  finally:
    receiver.close()


if __name__ == "__main__":
  sys.exit(main())
