#!/usr/bin/env python3
"""One-page health report for a drive, read on a laptop after the comma is unplugged.

Everything it reads is in the rlog, which survives pulling power: onroad alerts,
selfdrived's commIssue details, the locationd daemons' input-check events (with
their loop gaps), mapd's tile/activity events, the kernel/system journal, process
restarts and per-process CPU. No native openpilot build is needed:

  uv run --no-project --with pycapnp --with zstandard \\
    python starpilot/system/diagnostics/drive_report.py docs/Rlogs/<route>-logs.tar [--starpilot-auto session-NNNNNN-*.jsonl]

The input is an exported ``<route>-logs.tar`` or a directory of ``<route>--N/rlog.zst``
(qlogs work too, without CPU detail). On the comma, pass ``--route`` to pick one drive out
of /data/media/0/realdata; the diagnostics bundle does that.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import json
import re
import tarfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

CEREAL = Path(__file__).resolve().parents[3] / "cereal"
ROUTINE_ALERTS = {"preLaneChangeLeft", "preLaneChangeRight", "laneChange", "laneChangeBlocked", "reverseGear", "userBookmark",
                  "steerSaturated", "driverDistracted1", "promptDriverDistracted", "preDriverDistracted", "gasPressedOverride"}
WATCHED_EVENTS = re.compile(r"InputsInvalid|commIssue|^mapd_|upload_(paused|resumed)_(starpilot|android)_auto")
KERNEL_TROUBLE = re.compile("|".join((r"oom", r"out of memory", r"killed process", r"lowmemory", r"throttl", r"thermal", r"kgsl",
                                       r"gpu fault", r"hung task", r"soft lockup", r"rcu.*stall", r"page allocation failure",
                                       r"segfault", r"watchdog: bug")), re.I)
TOP_PROCESSES = 6


def _log_schema():
  import capnp
  capnp.remove_import_hook()
  return capnp.load(str(CEREAL / "log.capnp"), imports=[str(CEREAL)])


def _segment_number(name: str) -> int:
  match = re.search(r"--(\d+)/[qr]log\.zst$", name)
  return int(match.group(1)) if match else -1


def list_segments(source: Path, route: str | None = None) -> list[tuple[str, str]]:
  """(source, member) pairs in segment order; member is a tar member name or a file path."""
  if source.is_dir():
    pattern = f"{route}--*" if route else "*--*"
    files = sorted(source.glob(f"{pattern}/rlog.zst")) or sorted(source.glob(f"{pattern}/qlog.zst"))
    return [(str(path), str(path)) for path in sorted(files, key=lambda p: _segment_number(str(p)))]
  with tarfile.open(source) as tar:
    names = [m.name for m in tar.getmembers() if m.name.endswith("rlog.zst")] or \
            [m.name for m in tar.getmembers() if m.name.endswith("qlog.zst")]
  return [(str(source), name) for name in sorted(names, key=_segment_number)]


def _read(source: str, member: str) -> bytes:
  import zstandard
  if source == member:
    raw = Path(member).read_bytes()
  else:
    with tarfile.open(source) as tar:
      raw = tar.extractfile(member).read()
  return zstandard.ZstdDecompressor().decompressobj().decompress(raw)


def _json(text: str):
  try:
    return json.loads(text)
  except (TypeError, ValueError):
    return None


def scan_segment(item: tuple[str, str]) -> dict:
  source, member = item
  log = _log_schema()
  out = {"segment": _segment_number(member), "anchor": None, "alerts": [], "events": [], "kernel": [], "restarts": [],
         "cpu": None, "speed": []}
  prev_alert = None
  prev_running = None
  first_proc, last_proc, names, cores = {}, {}, {}, [None, None]
  mem = []
  for event in log.Event.read_multiple_bytes(_read(source, member)):
    which = event.which()
    mono = event.logMonoTime / 1e9
    if which == "gpsLocationExternal":
      gps = event.gpsLocationExternal
      if out["anchor"] is None and gps.hasFix and gps.unixTimestampMillis > 0:
        out["anchor"] = (mono, gps.unixTimestampMillis / 1e3)
    elif which == "carState":
      out["speed"].append(event.carState.vEgo)
    elif which == "selfdriveState":
      state = event.selfdriveState
      alert = (state.alertText1, state.alertText2, str(state.alertType)) if state.alertText1 else None
      if alert and alert != prev_alert and alert[2].split("/")[0] not in ROUTINE_ALERTS:
        out["alerts"].append((mono, f"{alert[0]} / {alert[1]} ({alert[2]})".replace(" /  (", " (")))
      prev_alert = alert
    elif which in ("logMessage", "errorLogMessage"):
      payload = _json(getattr(event, which))
      message = payload.get("msg") if isinstance(payload, dict) else None
      if isinstance(message, dict) and WATCHED_EVENTS.search(str(message.get("event", ""))):
        daemon = (payload.get("ctx") or {}).get("daemon", "")
        if which == "logMessage" and payload.get("levelnum", 0) >= 40:
          continue  # errors appear in both streams; keep the errorLogMessage copy
        out["events"].append((mono, daemon, message))
    elif which == "androidLog":
      entry = _json(event.androidLog.message) or {}
      text = str(entry.get("MESSAGE", ""))
      if KERNEL_TROUBLE.search(text) and "until shutdown" not in text:
        out["kernel"].append((int(entry.get("__REALTIME_TIMESTAMP", 0)) / 1e6, entry.get("_TRANSPORT", ""), text[:220]))
    elif which == "managerState":
      running = {p.name: p.pid for p in event.managerState.processes if p.running}
      if prev_running is not None:
        for name, pid in prev_running.items():
          if running.get(name) not in (None, pid):
            out["restarts"].append((mono, f"{name} restarted (pid {pid} -> {running[name]})"))
          elif name not in running:
            out["restarts"].append((mono, f"{name} stopped"))
      prev_running = running
    elif which == "procLog":
      proc_log = event.procLog
      for proc in proc_log.procs:
        cmd = list(proc.cmdline)
        label = (cmd[2] if len(cmd) > 2 and "python" in cmd[0] else " ".join(cmd)) or proc.name
        names[proc.pid] = label.rsplit("/", 1)[-1][:40]
        sample = (proc.cpuUser + proc.cpuSystem, mono)
        first_proc.setdefault(proc.pid, sample)
        last_proc[proc.pid] = sample
      times = [(c.user + c.nice + c.system + c.irq + c.softirq, c.idle + c.iowait) for c in proc_log.cpuTimes]
      cores[0] = cores[0] or times
      cores[1] = times
      mem.append(proc_log.mem.available / 1e6)
  if cores[1]:
    usage = collections.Counter()
    for pid, (cpu, t) in last_proc.items():
      cpu0, t0 = first_proc[pid]
      if t - t0 > 20:
        usage[names[pid]] += 100 * (cpu - cpu0) / (t - t0)
    core_pct = [round(100 * (b0 - a0) / max(1e-9, (b0 - a0) + (b1 - a1))) for (a0, a1), (b0, b1) in zip(*cores, strict=True)]
    out["cpu"] = {"cores": core_pct, "mem_avail_mb": round(sum(mem) / len(mem)), "top": usage.most_common(TOP_PROCESSES),
                  "mapd": round(sum(v for k, v in usage.items() if k in ("mapd", "starpilot.navigation.mapd_wrapper")))}
  return out


def _describe_event(daemon: str, message: dict) -> str:
  name = message.get("event", "")
  details = {k: v for k, v in message.items() if k not in ("event", "error")}
  if "details" in details:  # InputCheckLogger: keep the numbers that tell late input from late loop
    details["details"] = {s: {k: d[k] for k in ("age_ms", "recent_hz") if k in d} for s, d in details["details"].items()}
  return f"{daemon or '?'}: {name} {json.dumps(details, separators=(',', ':'))}"[:400]


def report(segments: list[dict], starpilot_auto_log: Path | None) -> str:
  anchor = next((s["anchor"] for s in segments if s["anchor"]), None)

  def clock(mono: float) -> str:
    if anchor is None:
      return f"mono {mono:9.2f}"
    return datetime.datetime.fromtimestamp(anchor[1] + mono - anchor[0]).strftime("%H:%M:%S.%f")[:-4]

  lines = []
  timeline = []
  for seg in segments:
    timeline += [(m, "ALERT", text) for m, text in seg["alerts"]]
    timeline += [(m, "EVENT", _describe_event(d, msg)) for m, d, msg in seg["events"]]
    timeline += [(m, "PROC", text) for m, text in seg["restarts"]]
  lines.append(f"== Timeline (alerts, commIssue/input checks, mapd, process restarts): {len(timeline)} entries")
  for mono, kind, text in sorted(timeline):
    lines.append(f"  {clock(mono)} {kind:5} {text}")

  kernel = [k for seg in segments for k in seg["kernel"]]
  lines.append(f"\n== Kernel/system journal trouble (OOM, throttling, GPU, hangs): {len(kernel)} lines")
  for ts, transport, text in sorted(kernel)[:60]:
    lines.append(f"  {datetime.datetime.fromtimestamp(ts).strftime('%H:%M:%S.%f')[:-4]} [{transport}] {text}")

  lines.append("\n== Per segment (≈1 min): speed, CPU per core, free memory, mapd, top processes")
  for seg in segments:
    mph = sum(seg["speed"]) / len(seg["speed"]) * 2.237 if seg["speed"] else 0
    cpu = seg["cpu"]
    if cpu is None:
      lines.append(f"  seg {seg['segment']:3} {mph:3.0f} mph  (no procLog: qlog?)")
      continue
    top = ", ".join(f"{name} {pct:.0f}%" for name, pct in cpu["top"])
    lines.append(f"  seg {seg['segment']:3} {mph:3.0f} mph  cores {cpu['cores']}  free {cpu['mem_avail_mb']} MB  mapd {cpu['mapd']}%  | {top}")

  if starpilot_auto_log is not None:
    keep = {"session_start", "attempt_failed", "session_ended", "bootstrap_start_refused", "projection_ready", "bluez_restarted",
            "wifi_joined", "peer_requested_shutdown", "tcp_retry"}
    rows = [json.loads(line) for line in starpilot_auto_log.read_text().splitlines() if line.strip()]
    events = [r for r in rows if r.get("event") in keep]
    lines.append(f"\n== Starpilot Auto session {starpilot_auto_log.name}: {len(events)} key events")
    for row in events:
      when = datetime.datetime.fromisoformat(row["t"]).astimezone().strftime("%H:%M:%S.%f")[:-4]
      detail = {k: v for k, v in row.items() if k not in ("t", "event", "head_unit", "message", "channels")}
      lines.append(f"  {when} {row['event']} {json.dumps(detail, separators=(',', ':'))[:240]}")
  return "\n".join(lines)


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument("source", type=Path, help="<route>-logs.tar or a directory of <route>--N/rlog.zst")
  parser.add_argument("--starpilot-auto", type=Path, help="Starpilot Auto session-*.jsonl for the same drive")
  parser.add_argument("--route", help="only this route (e.g. 000000cb--604289c5b5) when SOURCE holds several")
  parser.add_argument("--jobs", type=int, default=6)
  args = parser.parse_args()

  items = list_segments(args.source, args.route)
  if not items:
    raise SystemExit(f"No rlog.zst or qlog.zst segments found in {args.source}")
  with ProcessPoolExecutor(args.jobs) as pool:
    segments = list(pool.map(scan_segment, items))
  print(report(segments, args.starpilot_auto))


if __name__ == "__main__":
  main()
