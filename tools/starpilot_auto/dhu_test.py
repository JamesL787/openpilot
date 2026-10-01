#!/usr/bin/env python3
"""Validate the phone identity, session and encoder against Google's Desktop Head Unit.

Runs on a computer before any car test. It starts the DHU in ADB/TCP mode, waits
for it to connect, authenticates with the imported identity, negotiates video and
streams a moving test pattern. A pass proves the upper Starpilot Auto protocol and
the identity only: not Bluetooth, Wi-Fi, the comma's radio or Honda compatibility.

  python tools/starpilot_auto/dhu_test.py --dhu ~/Library/Android/sdk/extras/google/auto/desktop-head-unit

The DHU does not verify phones against a pinned car root, and on some desktop
OpenSSL builds verifying the DHU's own certificate fails on a date-format quirk,
so head-unit verification is off here unless ``--verify`` is given.
"""

import argparse
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

from openpilot.starpilot.system.starpilot_auto.encoder import H264Encoder
from openpilot.starpilot.system.starpilot_auto.frame_source import FrameRequest, SyntheticFrames
from openpilot.starpilot.system.starpilot_auto.identity import load_identity
from openpilot.starpilot.system.starpilot_auto.session import ProjectionSession


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument("--dhu", type=Path, required=True, help="desktop-head-unit executable")
  parser.add_argument("--identity", type=Path, default=Path(".cache/starpilot_auto/identity"))
  parser.add_argument("--seconds", type=float, default=20.0)
  parser.add_argument("--fps", type=int, default=15)
  parser.add_argument("--verify", action="store_true", help="also verify the DHU certificate against root-cert.pem")
  args = parser.parse_args()

  ident = load_identity(args.identity)
  print(f"identity ok, expires {ident.expires} ({ident.days_left} days)")
  events = []

  def log(name, **values):
    events.append({"event": name, **values})
    if name in ("version", "tls_established", "authenticated", "video_setup", "video_focus", "authentication_rejected"):
      print(json.dumps({"event": name, **values}, default=str))

  with socket.socket() as listener:
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(20)
    binary = args.dhu.expanduser().resolve(strict=True)
    child = subprocess.Popen([str(binary), f"--adb=127.0.0.1:{listener.getsockname()[1]}"], cwd=binary.parent,
                             stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
      peer, _ = listener.accept()
      with peer:
        session = ProjectionSession(peer, ident.cert, ident.key, log, ident.root if args.verify else None)
        session.authenticate()
        mode = session.start("StarPilot", "comma.ai")
        encoder = H264Encoder(mode.width, mode.height, fps=mode.fps)
        source = SyntheticFrames()
        source.configure(FrameRequest(mode.width, mode.height, mode.margin_width, mode.margin_height, int(1e6 / args.fps)))
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
          session.pump(0.01)
          session.check_progress()
          if session.can_send():
            frame = source.latest()
            if frame is not None:
              data, keyframe = encoder.encode_rgba(frame.data, keyframe=session.needs_keyframe)
              session.send_frame(data, frame.captured_ns // 1000, keyframe=keyframe)
        session.shutdown()
        encoder.close()
        print(json.dumps({"result": "pass", "mode": mode.as_dict(), **session.stats()}))
        return 0
    except Exception as error:
      print(json.dumps({"result": "fail", "error": f"{type(error).__name__}: {error}", "last_events": events[-5:]}, default=str))
      return 1
    finally:
      try:
        child.communicate(b"quit\n", timeout=3)
      except subprocess.TimeoutExpired:
        child.kill()


if __name__ == "__main__":
  sys.exit(main())
