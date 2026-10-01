#!/usr/bin/env python3
"""Project from the comma to Google's Desktop Head Unit, skipping Bluetooth and Wi-Fi.

Runs on the comma. It listens on localhost only; the DHU on a computer reaches it
through an SSH tunnel, then the real supervisor streaming path runs unchanged:
the car view (or mirror), hardware H.264, touch input and the view health checks.

  comma:     python tools/starpilot_auto/dhu_device.py
  computer:  ssh -N -L 5288:127.0.0.1:5288 comma@<comma-ip>
             desktop-head-unit --adb=127.0.0.1:5288

Stop Starpilot Auto in settings first so the daemon is not projecting to a car.
While this runs, the daemon's auto-connect holds off (see supervisor.dhu_session_active),
so going onroad does not start a car attempt that starves the tunnel. The DHU's certificate is not verified (its date format trips some OpenSSL
builds), so a pass proves the comma side only, not Honda compatibility.
"""

import argparse
import atexit
import json
import os
import signal
import socket
import threading
import time
from types import SimpleNamespace

from openpilot.starpilot.system.starpilot_auto import identity as identity_store
from openpilot.starpilot.system.starpilot_auto.car_screen import DHU_ENV
from openpilot.starpilot.system.starpilot_auto.supervisor import Cancelled, Supervisor


class LocalLease:
  """Stands in for the car's Wi-Fi network: the DHU link is the SSH tunnel."""
  local_ip = None

  def still_connected(self) -> bool:
    return True


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument("--port", type=int, default=5288)
  parser.add_argument("--view", choices=("car", "mirror"), help="default: the configured view")
  parser.add_argument("--encoder", choices=("auto", "hardware", "software"), help="default: the configured encoder")
  parser.add_argument("--fps", type=int, help="cap, 5-30; default: the configured value (0 = automatic)")
  parser.add_argument("--synthetic", action="store_true", help="stream a test pattern instead of the UI")
  args = parser.parse_args()

  # The car view inherits this: on a desk there's no wheel speed, so destinations stay settable.
  os.environ[DHU_ENV] = "1"
  supervisor = Supervisor(synthetic=args.synthetic)
  config = supervisor.config
  config["verify_head_unit"] = False
  for key in ("view", "encoder", "fps"):
    if getattr(args, key) is not None:
      config[key] = getattr(args, key)
  ident = identity_store.load_identity()
  print(f"identity ok, expires {ident.expires} ({ident.days_left} days)")

  hold = identity_store.DATA_DIR / f"dhu-{args.port}.pid"
  hold.write_text(f"{os.getpid()}\n")
  atexit.register(hold.unlink, missing_ok=True)

  def stop(*_):
    supervisor._stop.set()
    supervisor._close_sockets()
  signal.signal(signal.SIGINT, stop)
  signal.signal(signal.SIGTERM, stop)

  with socket.socket() as listener:
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", args.port))
    listener.listen(1)
    listener.settimeout(1.0)
    print(f"waiting for the DHU on 127.0.0.1:{args.port}", flush=True)
    peer = None
    while peer is None and not supervisor._stop.is_set():
      try:
        peer, _ = listener.accept()
      except TimeoutError:
        continue
    if peer is None:
      return 1
  peer.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
  supervisor._connect_tcp = lambda result, lease: supervisor._track(peer)

  def report():
    while not supervisor._stop.wait(5.0):
      status = supervisor.status()
      print(json.dumps({key: status[key] for key in ("state", "view", "encoder", "target_fps", "mode", "stats")}), flush=True)
  threading.Thread(target=report, daemon=True).start()

  supervisor.log.open()
  supervisor.log("session_start", receiver="desktop-head-unit", generation=0)
  result = 0
  try:
    supervisor._project(SimpleNamespace(endpoint=None), LocalLease(), ident)
    print("session ended")
  except Cancelled:
    print("stopped")
  except Exception as error:
    if not supervisor._stop.is_set():
      print(json.dumps({"result": "fail", "error": f"{type(error).__name__}: {error}",
                        "recent": list(supervisor.log.recent)[-8:]}, default=str))
      result = 1
  finally:
    supervisor._stop.set()
    supervisor._close_sockets()
    supervisor.log("session_stop")
    supervisor.log.close()
    print(f"log: {identity_store.LOG_DIR}", flush=True)
  return result


if __name__ == "__main__":
  raise SystemExit(main())
