#!/usr/bin/env python3
"""Keep a shared route download folder to the newest N drives plus any pinned ones.

Peter, 2026-10-01: keep up to 20 old drives. Every agent reads the same download folder, and signed analyses
cite specific older routes, so a route anyone still needs goes in <routes_dir>/KEEP, one per line:

  00000299--cfcac519b7   # James: left-overshoot prereg history
  0000029b               # an 8-hex route counter alone also matches

Anything after '#' is a note. Pins do not count toward the N. A drive is a folder named like a route
(8 hex, '--', 10 hex) that still holds raw logs (rlog/qlog); anything else in the folder (scratch dirs, files,
route folders holding only sim caches) is left alone. Deleting a drive removes its logs, cameras and fetch log
but keeps the small per-route caches the lateral sim reads (CACHE_FILES), so the sim corpus is unchanged.
Drives are ordered by the route counter, which rises with every drive on one device.

Dry run by default: it prints what it would delete. Pass --apply to delete.

  python tools/prune_routes.py ~/routes            # show the plan
  python tools/prune_routes.py ~/routes --apply    # delete
"""
import argparse
import re
import shutil
import sys
from pathlib import Path

ROUTE_RE = re.compile(r"^([0-9a-f]{8})--[0-9a-f]{10}$")
DEFAULT_KEEP = 20
CACHE_FILES = {"lat_pid_sim.npz"}  # tools/lateral/lat_pid_sim.py, a few MB per route


def read_pins(keep_file: Path) -> set[str]:
  if not keep_file.exists():
    return set()
  pins = set()
  for line in keep_file.read_text().splitlines():
    entry = line.split("#", 1)[0].strip()
    if entry:
      pins.add(entry)
  return pins


def is_pinned(name: str, counter: str, pins: set[str]) -> bool:
  return name in pins or counter in pins


def has_logs(path: Path) -> bool:
  return any(f.name.startswith(("rlog", "qlog")) for f in path.rglob("*"))


def doomed(route: Path) -> list[Path]:
  return [c for c in route.iterdir() if c.name not in CACHE_FILES]


def size(path: Path) -> int:
  if path.is_file() or path.is_symlink():
    return path.lstat().st_size
  return sum(f.stat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())


def fetch_logs(routes_dir: Path, name: str) -> list[Path]:
  # fetch logs are named by the full route or by the counter alone (fetch_2a6.log)
  names = {f"fetch_{name}.log", f"fetch_{name[:8].lstrip('0')}.log"}
  return [routes_dir / n for n in names if (routes_dir / n).is_file()]


def plan(routes_dir: Path, keep: int, pins: set[str]):
  routes = sorted((ROUTE_RE.match(p.name).group(1), p) for p in routes_dir.iterdir()
                  if p.is_dir() and not p.is_symlink() and ROUTE_RE.match(p.name) and has_logs(p))
  unpinned = [(c, p) for c, p in routes if not is_pinned(p.name, c, pins)]
  newest = {p for _, p in unpinned[-keep:]} if keep > 0 else set()
  kept, deleted = [], []
  for c, p in routes:
    (kept if p in newest or is_pinned(p.name, c, pins) else deleted).append(p)
  return kept, deleted


def main(argv=None) -> int:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("routes_dir", type=Path)
  ap.add_argument("--keep", type=int, default=DEFAULT_KEEP, help="newest unpinned drives to keep (default 20)")
  ap.add_argument("--apply", action="store_true", help="delete; without it, only print the plan")
  args = ap.parse_args(argv)

  routes_dir = args.routes_dir.expanduser()
  if not routes_dir.is_dir():
    print(f"not a directory: {routes_dir}", file=sys.stderr)
    return 2
  pins = read_pins(routes_dir / "KEEP")
  kept, deleted = plan(routes_dir, args.keep, pins)

  freed = 0
  for p in deleted:
    targets = doomed(p) + fetch_logs(routes_dir, p.name)
    route_bytes = sum(size(t) for t in targets)
    freed += route_bytes
    print(f"{'delete' if args.apply else 'would delete'}  {p.name}  {route_bytes / 1e6:8.0f} MB")
    if args.apply:
      for t in targets:
        if t.is_dir() and not t.is_symlink():
          shutil.rmtree(t)
        else:
          t.unlink()
      if not any(p.iterdir()):
        p.rmdir()
  pinned = sum(1 for p in kept if is_pinned(p.name, p.name[:8], pins))
  verb = "deleted" if args.apply else "would delete"
  print(f"keep {len(kept)} ({len(kept) - pinned} newest, {pinned} pinned); {verb} {len(deleted)}, {freed / 1e9:.1f} GB")
  if not args.apply and deleted:
    print("dry run: nothing deleted. Re-run with --apply to delete.")
  return 0


if __name__ == "__main__":
  sys.exit(main())
