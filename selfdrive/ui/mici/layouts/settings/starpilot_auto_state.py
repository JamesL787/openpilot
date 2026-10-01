"""What the comma four's Starpilot Auto page shows, from starpilot_autod's status; no raylib, so it tests on its own.

Values stay short (a card's value line fits about 24 characters) so nothing scrolls sideways,
and use plain ASCII: the comma four's font has no middle dot or dashes.
"""

from __future__ import annotations

TEXT_CARD_CHARS = 90  # a GreyBigButton card at 36 px holds about this much
CONNECT_STATUS_CHARS = 36  # two short lines beneath Connect / Disconnect
CONNECTION_OPTIONS = ("Wireless", "USB")
VIEW_OPTIONS = ("Starpilot Auto", "Screen Mirror")


def is_wired(status: dict) -> bool:
  return status.get("connection") == "wired"


def status_value(status: dict) -> str:
  """The one-line state for the status card and the Bluetooth screen's Starpilot Auto card."""
  if not status:
    return "starting"
  state = status.get("state", "idle")
  wired = is_wired(status)
  if state == "streaming":
    return f"projecting, {status.get('stats', {}).get('fps', 0):g} fps"
  if state == "suspended":
    return "car showing its screen"
  if state == "backoff":
    return f"retrying in {status.get('retry_in', 0):.0f} s"
  if state == "waiting_for_usb":
    return "waiting for usb"
  if state == "idle":
    if status.get("error"):
      return "stopped with an error"
    if not wired and not status.get("receiver_name"):
      return "choose a car"
    if status.get("auto_connect"):
      return "paused until next drive" if status.get("auto_paused") else "starts next drive"
    return "off"
  return str(status.get("label") or state)


def running(status: dict) -> bool:
  return bool(status.get("running"))


def connect_label(status: dict) -> str:
  return "Disconnect" if running(status) else "Connect"


def connect_status_value(status: dict) -> str:
  """Live state for the Connect card, with a compact excerpt of the real error."""
  error = " ".join(str(status.get("error") or "").split())
  value = f"Error: {error}" if error else status_value(status)
  if len(value) > CONNECT_STATUS_CHARS:
    value = value[:CONNECT_STATUS_CHARS - 3].rstrip() + "..."
  return value


def can_connect(status: dict) -> bool:
  return bool(status) and (running(status) or is_wired(status) or bool(status.get("receiver_address")))


def show_car(status: dict) -> bool:
  return not is_wired(status)


def show_pairing(status: dict, offroad: bool) -> bool:
  return not is_wired(status) and offroad


def show_error(status: dict) -> bool:
  return bool(status.get("error"))


def can_change_while(status: dict) -> bool:
  """The car and the connection type change only while stopped; starpilot_autod refuses otherwise."""
  return bool(status) and not running(status)


def view_value(status: dict) -> str:
  return VIEW_OPTIONS[1] if status.get("configured_view", "car") == "mirror" else VIEW_OPTIONS[0]


def connection_value(status: dict) -> str:
  return CONNECTION_OPTIONS[1] if is_wired(status) else CONNECTION_OPTIONS[0]


def auto_connect_title(enable: bool) -> str:
  return f"Slide for Auto\nConnect {'On' if enable else 'Off'}"


def auto_connect_value(enabled: bool) -> str:
  return "On" if enabled else "Off"


def connection_title(connection: str) -> str:
  return "slide to\nuse USB" if connection == CONNECTION_OPTIONS[1] else "slide to\nuse Wireless"


def view_title(view: str) -> str:
  return "slide to\nmirror comma" if view == VIEW_OPTIONS[1] else "slide to use\nStarpilot Auto"


def split_text(text: str, limit: int = TEXT_CARD_CHARS) -> list[str]:
  """Break text into cards of at most ``limit`` characters at word boundaries (a longer word is cut)."""
  cards: list[str] = []
  current = ""
  for word in text.split():
    while len(word) > limit:
      if current:
        cards.append(current)
        current = ""
      cards.append(word[:limit])
      word = word[limit:]
    candidate = f"{current} {word}" if current else word
    if len(candidate) > limit:
      cards.append(current)
      current = word
    else:
      current = candidate
  if current:
    cards.append(current)
  return cards
