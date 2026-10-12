#!/usr/bin/env python3
"""Download full rlog (or qlog / qcamera) segments from a Konik/comma API into a specified directory.

Why this exists
---------------
Downloads full rlog segments (optionally qlogs) of one named route from a
Konik/comma API into a directory the caller names, so route data reaches an
analysis environment without a manual upload.

Route data is never committed to this repository (AGENTS.md §7), so --out is
REQUIRED with no default.

Layout
------
Files are stored under the output directory matching the layout expected by
tools/bosch_a_route_report.collect_inputs:
    <out>/<ROUTE_WITHOUT_DONGLE>/<segment>/<filename>

Security
--------
The authentication token is passed to curl via configuration on stdin only.
It never appears in argv, stdout, stderr, or exceptions, preventing leakage
via process tables (`ps`).

Usage
-----
    python3 tools/konik_fetch.py --route 'DONGLE|ROUTE' --out DIR [--segments SPEC] [--qlogs | --qcameras] [--host HOST] [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plain_http
from konik_preflight import KONIK_API_HOST, _token

get_json = plain_http.get_json


def _curl_escape(value: str) -> str:
  """curl config values are double-quoted; backslash and quote need escaping."""
  return value.replace("\\", "\\\\").replace('"', '\\"')


def parse_segments(spec: str | None) -> set[int] | None:
  """Parse a segment spec string like '0-4,9' into a set of segment integers, or None."""
  if not spec or not spec.strip():
    return None
  segments: set[int] = set()
  for item in spec.split(","):
    item = item.strip()
    if not item:
      continue
    if "-" in item:
      start_s, end_s = item.split("-", 1)
      start, end = int(start_s.strip()), int(end_s.strip())
      for s in range(start, end + 1):
        segments.add(s)
    else:
      segments.add(int(item))
  return segments if segments else None


def segment_of(url: str) -> int:
  """Extract the integer segment number from an rlog/qlog URL."""
  parsed = urlparse(url)
  parts = [p for p in parsed.path.split("/") if p]
  if len(parts) < 2:
    raise ValueError(f"cannot extract segment from URL: {url}")
  return int(parts[-2])


def destination(out: str, route: str, segment: int | str, filename: str) -> str:
  """Return destination path: os.path.join(out, ROUTE_WITHOUT_DONGLE, str(segment), filename)."""
  route_without_dongle = route.split("|", 1)[1] if "|" in route else route
  return os.path.join(out, route_without_dongle, str(segment), filename)


def curl_config(url: str, token: str, dst_part: str) -> str:
  """Generate curl configuration string passing the token securely."""
  lines = [
    f'url = "{_curl_escape(url)}"',
    f'header = "{_curl_escape(f"Authorization: JWT {token}")}"',
    f'output = "{_curl_escape(dst_part)}"',
    "fail",
    "silent",
    "show-error",
    "location",
  ]
  return "\n".join(lines) + "\n"


def download_one(url: str, token: str, dst: str, run=subprocess.run) -> bool:
  """Download one segment file atomically using curl, skipping if non-empty dst exists."""
  if os.path.exists(dst) and os.path.getsize(dst) > 0:
    return True

  dst_part = dst + ".part"
  os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
  cfg = curl_config(url, token, dst_part)
  cmd = ["curl", "-K", "-", "--retry", "3", "--max-time", "900"]
  try:
    res = run(cmd, input=cfg.encode())
    if getattr(res, "returncode", None) == 0:
      os.replace(dst_part, dst)
      return True
  except Exception:
    pass

  if os.path.exists(dst_part):
    try:
      os.remove(dst_part)
    except OSError:
      pass
  return False


def main(argv: list[str] | None = None) -> int:
  parser = argparse.ArgumentParser(
    description=__doc__,
    formatter_class=argparse.RawDescriptionHelpFormatter,
  )
  parser.add_argument("--route", required=True, help="route name, e.g. 'DONGLE|ROUTE'")
  parser.add_argument("--out", required=True, help="output directory for downloaded segments")
  parser.add_argument("--segments", help="segment spec, e.g. '0-4,9'")
  parser.add_argument("--qlogs", action="store_true", help="download qlogs instead of rlogs")
  parser.add_argument("--qcameras", action="store_true", help="download qcamera.ts instead of rlogs")
  parser.add_argument(
    "--host",
    default=os.environ.get("API_HOST", KONIK_API_HOST),
    help="API host (default: https://api.konik.ai)",
  )
  parser.add_argument("--dry-run", action="store_true", help="print segment numbers and destinations only")

  args = parser.parse_args(argv)

  host = args.host.rstrip("/")
  token = _token(host)
  if not token:
    print(
      f"No authentication token for {host}. Log in using tools/konik_login.py or set $KONIK_TOKEN.",
      file=sys.stderr,
    )
    return 2

  route = args.route.strip()
  headers = {"Authorization": "JWT " + token}
  url = f"{host}/v1/route/{route}/files"
  files = get_json(url, headers=headers)

  if isinstance(files, dict):
    urls = files.get("qcameras" if args.qcameras else "qlogs" if args.qlogs else "logs") or []
  else:
    urls = []

  if not urls:
    kind = "qcameras" if args.qcameras else "qlogs" if args.qlogs else "rlogs"
    print(
      f"No {kind} found for route {route}. "
      + "rlogs are not uploaded yet (comma uploads rlogs only on WiFi).",
      file=sys.stderr,
    )
    return 3

  seg_filter = parse_segments(args.segments)

  items: list[tuple[int, str, str]] = []
  for u in urls:
    seg = segment_of(u)
    if seg_filter is not None and seg not in seg_filter:
      continue
    filename = os.path.basename(urlparse(u).path)
    if not filename:
      filename = "qcamera.ts" if args.qcameras else "qlog.zst" if args.qlogs else "rlog.zst"
    dst = destination(args.out, route, seg, filename)
    items.append((seg, dst, u))

  if args.dry_run:
    for seg, dst, _ in items:
      print(f"{seg} {dst}")
    return 0

  total_bytes = 0
  failed = 0
  for seg, dst, u in items:
    ok = download_one(u, token, dst)
    if ok:
      sz = os.path.getsize(dst) if os.path.exists(dst) else 0
      total_bytes += sz
      print(f"Segment {seg}: {sz} bytes")
    else:
      failed += 1
      print(f"Segment {seg}: FAILED")

  print(f"Total: {total_bytes} bytes ({len(items) - failed}/{len(items)} downloaded)")
  return 1 if failed else 0


if __name__ == "__main__":
  sys.exit(main())
