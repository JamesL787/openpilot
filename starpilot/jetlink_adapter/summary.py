"""One line of words for a Jetlink status, for the settings panel. Pure functions of the status snapshot and the live
model message, so they are testable without a UI; standard library only."""
from __future__ import annotations


def setting_label(mode: str, supported: tuple[str, ...]) -> str:
  if mode == 'off':
    return "Off"
  if mode not in supported:
    return f"{mode.upper()} (unsupported)"
  return {'usb': "USB", 'ios': "iOS"}.get(mode, mode.upper())


def describe(status, live: dict | None = None) -> str:
  """What the link is doing, in a few words.

  `status` is jetlink.openpilot.Status (or None where Jetlink is not installed). `live` is the running modeld's report
  while driving: {backend, accelerator, held_frames, remote_model} from starpilotModelV2, or None."""
  if status is None:
    return "Not installed"
  if not status.enabled:
    return "Off" if status.mode == 'off' else "Off (Chestnut fitted)"
  if status.reason:
    return f"Unavailable: {status.reason}"
  if live is not None:
    backend, state = live.get('backend'), live.get('accelerator')
    if backend == 'jetlink':
      held = int(live.get('held_frames') or 0)
      return f"Driving on {live.get('remote_model') or 'the large model'}" + (f" ({held} held)" if held else "")
    if state == 'ready':
      return "Ready: disengage to switch"
    reason = f" ({live['reason']})" if live.get('reason') else ""
    if state in ('joining', 'retrying'):
      return ("Connecting" if state == 'joining' else "Reconnecting") + reason
    if state == 'unavailable':
      return "Unavailable this drive" + (f": {live['reason']}" if live.get('reason') else "")
  progress = status.progress or {}
  # parked and nothing has connected: what the port sees tells a missing cable from a host that never answered
  waiting = "" if status.present else _port_hint(status)
  if progress.get('msg'):
    return str(progress['msg']).capitalize() + waiting
  if not status.present:
    return "Waiting for the host" + waiting
  return "Ready" if status.runnable else "Host connected, model not built yet"


def port_line(status) -> str:
  """What is on the comma's USB-C port right now (Zoompilot's link_status). Jetlink names a host it is talking to and the
  transport; below that only the CC pin speaks, which says a cable with something behind it is plugged in, not what it
  is. Empty where Jetlink is not installed or the kernel does not say."""
  if status is None:
    return ""
  if status.present:
    return f"Jetlink connected: {status.transport}"
  if status.port is None:
    return ""
  return "Nothing on the USB port" if status.port == 'empty' else "A device is on the USB port, not connected"


def _port_hint(status) -> str:
  if status.port == 'empty':
    return " (nothing on the USB port)"
  if status.port is not None:
    return " (a device is on the USB port)"
  return ""
