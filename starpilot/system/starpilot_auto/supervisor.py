"""Starpilot Auto session supervisor: owns every stage, deadline, retry and cleanup.

One session, started by the user or by auto-connect (see auto_connect.py), runs
in one worker thread:

  idle -> connecting_bluetooth -> discovering -> rfcomm -> wifi_start -> wifi_info
       -> joining_wifi -> connecting_tcp -> authenticating -> negotiating -> streaming
  streaming <-> suspended (head unit showing its own screen)
  failure -> cleanup -> backoff -> retry          stop -> cleanup -> idle

Each attempt has a generation number; Stop cancels immediately (sockets are
closed from the caller's thread to unblock I/O). Between retries the projection
network is released without restoring the previous Wi-Fi, which happens once,
on Stop. Nothing here runs as root or touches vehicle control.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openpilot.starpilot.system.starpilot_auto import identity as identity_store
from openpilot.starpilot.system.starpilot_auto.auto_connect import AutoConnectPolicy
from openpilot.starpilot.system.starpilot_auto.bootstrap import NAMES, BootstrapError, WirelessBootstrap
from openpilot.starpilot.system.starpilot_auto.frame_source import (DEFAULT_PATH as DEFAULT_FRAME_PATH, FLAG_ASYNC_READBACK, FLAG_NV12,
                                                                  FORMAT_NV12, FrameRequest)
from openpilot.starpilot.system.starpilot_auto.touch import DEFAULT_TOUCH_SOCKET
from openpilot.starpilot.system.starpilot_auto.view import CAR_FRAME_PATH, ViewSource, renderer_available
from openpilot.starpilot.system.starpilot_auto.session import AuthenticationRejected, PeerRequestedStop, ProjectionSession

BACKOFF_SECONDS = (2.0, 4.0, 8.0, 15.0, 30.0)
STABLE_SESSION_SECONDS = 30.0
PEER_STOP_RETRY_SECONDS = 10.0
FRAME_MAX_AGE = 0.5          # never send a UI frame older than this
SOFTWARE_FPS = 15            # libx264 cadence; the hardware encoder runs at 30
PREWARM_SECONDS = 0.0     # the car view needs ~11 s to its first frame; it no longer renders before focus, to spare driving processes
UNAVAILABLE_AFTER = 1.0      # focused but no fresh UI frame for this long -> "unavailable" card; the Honda gives the screen back after 3 s without video
SDP_SETTLE = (1.5, 2.2, 3.0)
TCP_ATTEMPTS = 6
MAX_LOG_FILES = 20
ENCODER_RECOVERIES = 3       # hardware encoder reopens allowed per window before the session is torn down
ENCODER_RECOVERY_WINDOW = 10.0
CAR_LINK_HOLD = 10.0         # a hands-free connection from the car counts as "car present" this long
USB_HANDSHAKE_WAIT = 10.0    # the car connected but sent no AOA START this long -> present as an accessory directly
USB_CONFIGURE_WAIT = 15.0    # slower receivers need time to enumerate after the AOA switch
HFP_WAIT = 5.0               # after paging the car, wait this long for its hands-free link before the Starpilot Auto RFCOMM
HFP_FRESH = 3.0              # a hands-free link from the car this recent still means "the car is reaching out now"
DHU_PID_GLOB = "dhu-*.pid"   # under DATA_DIR, one per running tools/starpilot_auto/dhu_device.py

STATE_LABELS = {
  "idle": "off", "connecting_bluetooth": "connecting to car", "discovering": "finding starpilot auto",
  "rfcomm": "starting wireless setup", "wifi_start": "waiting for car", "wifi_info": "getting car wi-fi",
  "joining_wifi": "joining car wi-fi", "connecting_tcp": "connecting", "authenticating": "authenticating",
  "negotiating": "negotiating video", "streaming": "projecting", "suspended": "car showing its own screen",
  "backoff": "retrying", "stopping": "stopping", "error": "error",
  "waiting_for_usb": "plug into the car's usb", "usb_accessory": "starting usb",
}


def _is_onroad() -> bool:
  try:
    from openpilot.common.params import Params
    return Params().get_bool("IsOnroad")
  except Exception:
    return False


def dhu_session_active() -> bool:
  """Whether tools/starpilot_auto/dhu_device.py is projecting to a Desktop Head Unit on this comma.

  Auto-connect holds off meanwhile: going onroad would start paging the (absent) car over
  Bluetooth, which starves the comma's Wi-Fi and times out the DHU's video acknowledgements.
  A SIGKILLed tool leaves its pid file behind, so only a live dhu_device process counts.
  Fails open: anything unreadable or unexpected means no hold, so a car always auto-connects.
  """
  try:
    paths = list(identity_store.DATA_DIR.glob(DHU_PID_GLOB))
  except Exception:
    return False
  for path in paths:
    try:
      pid = int(path.read_text())
      if Path("/proc/self").exists():
        if b"dhu_device" in Path(f"/proc/{pid}/cmdline").read_bytes():
          return True
      else:
        os.kill(pid, 0)  # no procfs (macOS tests): a live pid is enough
        return True
    except Exception:
      continue
  return False


class Cancelled(Exception):
  pass


class NoLease:
  """Wired sessions use no car Wi-Fi network."""
  local_ip = None

  def release(self, restore: bool = False) -> None:
    pass


class UsbLease:
  """The link of a wired session: the USB cable, via the accessory bridge."""
  local_ip = None
  lost = "The car's USB connection ended"

  def __init__(self, bridge):
    self.bridge = bridge

  def still_connected(self) -> bool:
    return not self.bridge.closed.is_set()


class EventLog:
  """Sanitized JSONL session log under /data/starpilot_auto/logs, plus the recent tail in memory."""

  def __init__(self, directory: Path | None = None):
    self.directory = directory or identity_store.LOG_DIR
    self.handle = None
    self.recent: deque[dict] = deque(maxlen=40)
    self.lock = threading.Lock()

  def open(self) -> None:
    try:
      self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
      logs = sorted(self.directory.glob("session-*.jsonl"), key=identity_store.session_log_order)
      for old in logs[:max(0, len(logs) - MAX_LOG_FILES + 1)]:
        old.unlink(missing_ok=True)
      number = max([0, *(identity_store.session_log_order(log)[0] for log in logs)]) + 1
      path = self.directory / f"session-{number:06d}-{identity_store.timestamp()}.jsonl"
      fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
      self.handle = os.fdopen(fd, "a")
    except OSError:
      self.handle = None

  def close(self) -> None:
    with self.lock:
      if self.handle is not None:
        self.handle.close()
        self.handle = None

  def __call__(self, name: str, **values) -> None:
    record = {"t": datetime.now(UTC).isoformat(timespec="milliseconds"), "event": name, **values}
    with self.lock:
      self.recent.append(record)
      if self.handle is not None:
        try:
          self.handle.write(json.dumps(record, default=str) + "\n")
          self.handle.flush()
        except OSError:
          pass


class Supervisor:
  def __init__(self, bluez_factory=None, lease_factory=None, bluetooth_client=None, frame_path: str | None = None,
               synthetic: bool = False, car_frame_path: str = CAR_FRAME_PATH, touch_path: str = DEFAULT_TOUCH_SOCKET,
               renderer_command: list[str] | None = None, onroad=_is_onroad):
    self._synthetic = synthetic
    self._onroad = onroad
    self._car_frame_path, self._touch_path, self._renderer_command = car_frame_path, touch_path, renderer_command
    self._bluez_factory = bluez_factory
    self._lease_factory = lease_factory
    self._bt_client = bluetooth_client
    self._frame_path = frame_path
    self._lock = threading.RLock()
    self._stop = threading.Event()
    self._thread: threading.Thread | None = None
    self._generation = 0
    self._stream_started: float | None = None
    self._retry_at = 0.0
    self._sockets: set[socket.socket] = set()
    self._bluez: Any = None
    self._pairing_until = 0.0
    self._pairing_known: set[str] | None = None  # Starpilot Auto cars already paired when the pairing window opened
    self._car_seen_at = -CAR_LINK_HOLD
    self._hfp_link = threading.Event()  # set when the chosen car opens the hands-free link
    self.auto = AutoConnectPolicy()
    self.log = EventLog()
    self.config = identity_store.load_config()
    self._status: dict = {"state": "idle", "detail": "", "error": "", "last_stage": "", "attempt": 0,
                          "retry_in": 0.0, "mode": None, "stats": {}, "head_unit": {}, "identity": "", "running": False,
                          "view": "", "encoder": "", "target_fps": 0}

  # ------------------------------------------------------------------ status

  def _set(self, **values) -> None:
    with self._lock:
      self._status.update(values)

  def _stage(self, state: str, detail: str = "") -> None:
    self._check_cancel()
    if state == "streaming":
      self._stream_started = time.monotonic()
    self._set(state=state, detail=detail, last_stage=state)
    self.log("stage", state=state, detail=detail)

  def _check_cancel(self) -> None:
    if self._stop.is_set():
      raise Cancelled()

  def status(self) -> dict:
    with self._lock:
      status = dict(self._status)
    if status["state"] == "backoff":
      status["retry_in"] = max(0.0, self._retry_at - time.monotonic())
    status["label"] = STATE_LABELS.get(status["state"], status["state"])
    status["receiver_address"] = self.config["receiver_address"]
    status["receiver_name"] = self.config["receiver_name"]
    status["configured_view"] = self.config["view"]
    status["connection"] = self.config["connection"]
    status["pairing_ready"] = self._pairing_active()
    status["auto_connect"] = bool(self.config["auto_connect"])
    status["auto_paused"] = self.auto.suppressed
    status["recent"] = list(self.log.recent)[-8:]
    return status

  # ---------------------------------------------------------------- commands

  def user_start(self) -> None:
    self.auto.manual_start()
    self.start()

  def user_stop(self) -> None:
    """Stop pressed: also holds auto-connect off until the next drive."""
    self.auto.manual_stop(self._session_alive())
    self.stop()

  def set_auto_connect(self, enabled: bool) -> None:
    with self._lock:
      self.config["auto_connect"] = bool(enabled)
      identity_store.save_config(self.config)
    self.log("auto_connect_selected", enabled=bool(enabled))

  def start(self, trigger: str = "manual") -> None:
    with self._lock:
      if self._thread is not None and self._thread.is_alive():
        if self._stop.is_set():
          raise RuntimeError("Starpilot Auto is still stopping; try again in a moment")
        return
      if self.config["connection"] != "wired" and not self.config["receiver_address"]:
        raise RuntimeError("Choose your car first")
      identity = identity_store.load_identity()  # fail fast with a clear message
      self._stop.clear()
      self._generation += 1
      self._set(state="waiting_for_usb" if self.config["connection"] == "wired" else "connecting_bluetooth",
                detail="", error="", attempt=0, retry_in=0.0, running=True,
                identity=identity_store.expiry_warning(identity))
      self._thread = threading.Thread(target=self._run, args=(self._generation, trigger), name="starpilot_auto_session", daemon=True)
      self._thread.start()

  def stop(self, timeout: float = 8.0, graceful: float = 3.0) -> None:
    """Cancel the session: let a streaming session say goodbye to the car, then force it.

    Only the session captured here is ours to tear down: once it has exited a concurrent start() may
    have launched a replacement, whose sockets and status must be left alone.
    """
    with self._lock:
      thread = self._thread
      self._stop.set()
    if thread is not None:
      thread.join(timeout=graceful)
    with self._lock:
      if self._thread is not thread:
        return  # a replacement session owns the state now
      self._close_sockets()  # unblocks any stage still waiting on Bluetooth or the network
    if thread is not None:
      thread.join(timeout=max(0.0, timeout - graceful))
    with self._lock:
      if self._thread is not thread:
        return
      if thread is not None and thread.is_alive():
        return  # still cleaning up; start() refuses until it finishes
      self._thread = None
      if self._status["state"] != "error":
        self._set(state="idle", detail="")
      self._set(running=False, retry_in=0.0)

  def select_receiver(self, address: str, name: str = "") -> None:
    from openpilot.starpilot.system.starpilot_auto.bt_sockets import normalize_address
    address = normalize_address(address)
    with self._lock:
      if self._thread is not None and self._thread.is_alive():
        raise RuntimeError("Stop Starpilot Auto before changing the car")
      self.config.update(receiver_address=address, receiver_name=name or address)
      identity_store.save_config(self.config)
    self._unselect_car_audio(address)
    try:
      self._phone().set_trusted(address)  # the car's own connections are accepted onroad, like a phone's
    except Exception as error:
      self.log("trust_failed", error=str(error))

  def forget_receiver(self, address: str) -> bool:
    """The car was unpaired from the comma: drop it as the chosen car so it leaves the car pickers and
    auto-connect stops paging it. Called by the Bluetooth service when the pairing is deleted."""
    from openpilot.starpilot.system.starpilot_auto.bt_sockets import normalize_address
    address = normalize_address(address)
    chosen = self.config["receiver_address"].upper() == address
    if chosen and self._session_alive():
      self.stop()
    with self._lock:
      cache = dict(self.config["rfcomm_cache"])
      if not chosen and cache.pop(address, None) is None:
        return False  # nothing of this device was kept
      cache.pop(address, None)
      self.config["rfcomm_cache"] = cache
      if chosen:
        self.config.update(receiver_address="", receiver_name="")
      identity_store.save_config(self.config)
    if chosen:
      self.log("car_forgotten", address=address)
    return chosen

  def set_view(self, view: str) -> None:
    """Choose what the car shows; applies from the next projection session."""
    if view not in ("car", "mirror"):
      raise RuntimeError(f"Unknown view {view!r}")
    with self._lock:
      self.config["view"] = view
      identity_store.save_config(self.config)
    self.log("view_selected", view=view)

  def set_connection(self, connection: str) -> None:
    """Choose wireless (Bluetooth + car Wi-Fi) or wired (USB) projection."""
    if connection not in ("wireless", "wired"):
      raise RuntimeError(f"Unknown connection {connection!r}")
    with self._lock:
      if self._thread is not None and self._thread.is_alive():
        raise RuntimeError("Stop Starpilot Auto before changing the connection")
      self.config["connection"] = connection
      identity_store.save_config(self.config)
    self.log("connection_selected", connection=connection)

  def prepare_pairing(self, seconds: float = 180.0) -> None:
    """Present as a phone (HFP gateway, smartphone class) while the car pairs."""
    bluez = self._phone()
    known = {device["address"] for device in bluez.devices() if device["paired"] and device.get("starpilot_auto")}
    if self.config.get("phone_class", True):
      bluez.acquire()
    with self._lock:
      self._pairing_known = known
      self._pairing_until = time.monotonic() + seconds
    self.log("pairing_window", seconds=seconds)

  def devices(self) -> list[dict]:
    try:
      devices = self._phone().devices()
    except Exception as error:
      raise RuntimeError(f"Bluetooth unavailable: {error}") from error
    return [{key: device[key] for key in ("address", "name", "paired", "connected", "starpilot_auto")}
            for device in devices if device["paired"]]

  def maintain(self, now: float | None = None) -> None:
    """Periodic housekeeping from the daemon thread: pairing window, auto-connect."""
    now = time.monotonic() if now is None else now
    if self._pairing_until:
      if self._pairing_active():
        self._select_new_car()
      else:
        with self._lock:
          self._pairing_until, self._pairing_known = 0.0, None
        if not self._session_alive():
          self._release_phone()
    self._auto_connect(now)

  def _auto_connect(self, now: float) -> None:
    config = self.config
    address = config["receiver_address"]
    wired = config["connection"] == "wired"
    enabled = config["auto_connect"] and (wired or bool(address))
    standby = bool(address) and config.get("phone_class", True)
    if (not enabled or (wired and not standby)) and self._bluez is not None and not self._session_alive() \
       and not self._pairing_active():
      self._release_phone()  # drop a standby gateway: auto-connect is off, or a USB car with no chosen Bluetooth car
    if not enabled:
      return
    running = self._session_alive()
    if wired:
      # The drive is the only sign of the car: the session then waits for its USB handshake,
      # whether the car was on before the comma booted or is switched on after.
      ready, car_link = True, False
      if standby:
        # A phone always offers its car a hands-free gateway, wired or not. The 2019 Civic, wired with none
        # (2026-10-02), refused Bluetooth audio once USB started, never gave the projection focus, and reset USB.
        try:
          self._phone().register_hfp()
        except Exception:
          pass  # Bluetooth still starting (or restarting)
    else:
      try:
        bluez = self._phone()
        adapter_ready, device = bluez.snapshot(address)
        if adapter_ready and config.get("phone_class", True):
          bluez.register_hfp()  # standby: lets the car reach the comma when it powers on
      except Exception:
        adapter_ready, device = False, None  # Bluetooth still starting (or restarting)
      car_link = bool(device and device["connected"]) or now - self._car_seen_at < CAR_LINK_HOLD
      ready = adapter_ready and bool(device and device["paired"])
    onroad = self._onroad()
    action = self.auto.decide(now, enabled=True, onroad=onroad, car_link=car_link, ready=ready, running=running)
    if action == "start" and dhu_session_active():
      return
    if action == "start":
      trigger = "onroad" if onroad else "car_connected"
      try:
        self.start(trigger=trigger)
      except Exception as error:
        self.auto.start_refused(now)
        self._set(error=f"auto-connect: {error}"[:300])
        self.log("auto_connect_refused", error=str(error))
    elif action == "stop":
      self.log("auto_connect_stop", reason="car gone")
      self.stop()

  def _select_new_car(self) -> None:
    """A car that paired during the pairing window and offers Starpilot Auto becomes the chosen car."""
    if self._session_alive():
      return
    try:
      devices = self._phone().devices()
    except Exception:
      return
    with self._lock:
      known = self._pairing_known
      if known is None:
        return
      new = [device for device in devices if device["paired"] and device.get("starpilot_auto") and device["address"] not in known]
      if not new:
        return
      known.add(new[0]["address"])
    try:
      self.select_receiver(new[0]["address"], new[0]["name"])
      self.log("car_selected_after_pairing", car=new[0]["name"])
    except (RuntimeError, ValueError) as error:
      self.log("car_select_failed", error=str(error))

  def close(self) -> None:
    self.stop()
    if self._bluez is not None:
      try:
        self._bluez.close()
      except Exception:
        pass
      self._bluez = None

  # ----------------------------------------------------------------- helpers

  def _phone(self):
    with self._lock:
      if self._bluez is None:
        if self._bluez_factory is None:
          from openpilot.starpilot.system.starpilot_auto.bluez_phone import BluezPhone
          bluez = BluezPhone(self.log)
        else:
          bluez = self._bluez_factory(self.log)
        bluez.accepts = self._hfp_accepts
        bluez.on_connection = self._hfp_connected
        self._bluez = bluez
      return self._bluez

  def _pairing_active(self) -> bool:
    return time.monotonic() < self._pairing_until

  def _session_alive(self) -> bool:
    thread = self._thread
    return thread is not None and thread.is_alive()

  def _hfp_accepts(self, address: str) -> bool:
    receiver = self.config["receiver_address"]
    return self._pairing_active() or not receiver or address.upper() == receiver.upper()

  def _hfp_connected(self, address: str) -> None:
    if address.upper() == self.config["receiver_address"].upper():
      self._car_seen_at = time.monotonic()
      self._hfp_link.set()

  def _release_phone(self) -> None:
    """Stop looking like a phone; keep only the standby gateway auto-connect needs."""
    bluez = self._bluez
    if bluez is None:
      return
    config = self.config
    standby = config["auto_connect"] and bool(config["receiver_address"]) and config.get("phone_class", True)
    if standby or self._pairing_active():
      bluez.restore_class()
    else:
      bluez.release()

  def _remember_channel(self, address: str, channel: int | None) -> None:
    with self._lock:
      cache = dict(self.config["rfcomm_cache"])
      if channel is None:
        if cache.pop(address, None) is None:
          return
      elif cache.get(address) == channel:
        return
      else:
        cache[address] = channel
      self.config["rfcomm_cache"] = cache
      identity_store.save_config(self.config)

  def _lease(self):
    if self._lease_factory is None:
      from openpilot.starpilot.system.starpilot_auto.network import NetworkLease
      return NetworkLease(self.log, self.config["wifi_interface"])
    return self._lease_factory(self.log, self.config["wifi_interface"])

  def _unselect_car_audio(self, address: str) -> None:
    try:
      client = self._bt_client
      if client is None:
        from openpilot.starpilot.system.bluetooth import BluetoothClient
        client = BluetoothClient(timeout=5.0)
      if client.status().selected_audio.upper() == address.upper():
        client.select_audio("")
        self.log("car_audio_unselected")
    except Exception:
      pass

  def _track(self, sock: socket.socket) -> socket.socket:
    with self._lock:
      self._sockets.add(sock)
    if self._stop.is_set():
      self._close_sockets()
      raise Cancelled()
    return sock

  def _close_sockets(self) -> None:
    with self._lock:
      sockets, self._sockets = self._sockets, set()
    for sock in sockets:
      try:
        sock.shutdown(socket.SHUT_RDWR)
      except OSError:
        pass
      try:
        sock.close()
      except OSError:
        pass

  def _wait(self, seconds: float) -> None:
    if self._stop.wait(seconds):
      raise Cancelled()

  def _car_link_fresh(self) -> bool:
    return time.monotonic() - self._car_seen_at < HFP_FRESH

  def _wait_backoff(self, delay: float, car_can_wake: bool) -> None:
    """Sleep out a retry delay, but retry at once when the car opens hands-free to us.

    That is the car reaching out (at startup, or when the driver taps Android Auto); it hangs
    up again within a second, so waiting out a 30 s backoff would miss it.
    """
    if not car_can_wake:
      self._wait(delay)
      return
    if not self._car_link_fresh():
      self._hfp_link.clear()
    deadline = time.monotonic() + delay
    while (remaining := deadline - time.monotonic()) > 0:
      if self._hfp_link.is_set():
        self.log("retry_early", reason="car opened hands-free", skipped_s=round(remaining, 1))
        return
      self._wait(min(0.1, remaining))

  # ---------------------------------------------------------------- session

  def _run(self, generation: int, trigger: str = "manual") -> None:
    self.log.open()
    wired = self.config["connection"] == "wired"
    self.log("session_start", receiver="usb" if wired else self.config["receiver_name"], generation=generation, trigger=trigger)
    lease = NoLease() if wired else self._lease()
    attempt = 0
    try:
      while not self._stop.is_set():
        self._stream_started = None
        self._set(stats={}, mode=None)
        peer_stopped = False
        try:
          self._attempt(lease)
          self.log("session_ended")
        except Cancelled:
          break
        except PeerRequestedStop as error:
          self._set(error="", detail=str(error))
          self.log("session_ended", reason=str(error))
          peer_stopped = True
        except Exception as error:
          if self._stop.is_set():
            break  # I/O torn down by Stop; not a failure to report
          stage = error.stage if isinstance(error, BootstrapError) else self._status["last_stage"]
          message = self._describe_error(stage, error)
          self._set(error=message)
          self.log("attempt_failed", stage=stage, error=message, kind=type(error).__name__)
        finally:
          self._close_sockets()
          try:
            lease.release(restore=False)
          except Exception as error:
            self.log("wifi_release_failed", error=str(error))
        if self._stop.is_set():
          break
        stable = self._stream_started is not None and time.monotonic() - self._stream_started >= STABLE_SESSION_SECONDS
        attempt = 0 if stable else attempt + 1
        delay = BACKOFF_SECONDS[min(max(0, attempt - 1), len(BACKOFF_SECONDS) - 1)]
        if peer_stopped:
          delay = max(delay, PEER_STOP_RETRY_SECONDS)  # the car ended projection itself; do not bounce straight back
        self._retry_at = time.monotonic() + delay
        self._set(state="backoff", attempt=attempt, retry_in=delay, mode=None)
        try:
          self._wait_backoff(delay, car_can_wake=not wired and not peer_stopped)
        except Cancelled:
          break
    finally:
      self._set(state="stopping", detail="")
      try:
        lease.release(restore=True)
      except Exception as error:
        self.log("wifi_release_failed", error=str(error))
      try:
        self._release_phone()
      except Exception as error:
        self.log("bluetooth_release_failed", error=str(error))
      self.log("session_stop")
      self.log.close()
      self._set(state="idle", detail="", running=False, retry_in=0.0, mode=None)

  @staticmethod
  def _describe_error(stage: str, error: Exception) -> str:
    if isinstance(error, AuthenticationRejected):
      return "The car rejected the Starpilot Auto identity; check or renew the certificate in Galaxy > Toggles > Starpilot Auto"
    text = str(error) or type(error).__name__
    if stage == "authenticating" and "certificate" in text.lower():
      text += " (check the comma's date/time and the certificate in Galaxy > Toggles > Starpilot Auto)"
    return f"{STATE_LABELS.get(stage, stage)}: {text}"[:300]

  def _attempt(self, lease) -> None:
    if self.config["connection"] == "wired":
      self._attempt_usb()
      return
    config = self.config
    address = config["receiver_address"]
    ident = identity_store.load_identity()

    self._stage("connecting_bluetooth", config["receiver_name"])
    bluez = self._phone()
    if config.get("phone_class", True):
      bluez.acquire()
    device = bluez.device(address)
    if device is None or not device["paired"]:
      raise RuntimeError("The car is not paired with this comma; pair it in Bluetooth settings")
    if not self._car_link_fresh():
      self._hfp_link.clear()  # keep a link the car just opened: it is why this attempt started
    bluez.connect_device(address)
    if config.get("phone_class", True) and not device["connected"]:
      # Head units treat a device as a phone once hands-free is up, and some refuse wireless
      # projection until then; wait for it rather than a fixed pause, but go on without it.
      started = time.monotonic()
      while not self._hfp_link.is_set() and time.monotonic() - started < HFP_WAIT:
        self._wait(0.1)
      self.log("hfp_wait", linked=self._hfp_link.is_set(), seconds=round(time.monotonic() - started, 1))
    self._wait(1.0)  # the service-level AT exchange, and SDP settling on the new link

    from openpilot.starpilot.system.starpilot_auto import bt_sockets
    channel = int(config.get("rfcomm_channel") or 0)
    source = "config"
    if not channel:
      channel, source = config["rfcomm_cache"].get(address, 0), "cache"
    self._stage("discovering")
    if not channel:
      channel, source = self._discover_channel(address), "sdp"
    self.log("rfcomm_channel", channel=channel, source=source)

    try:
      self._stage("rfcomm", f"channel {channel}")
      rfcomm = self._track(bt_sockets.connect_rfcomm(address, channel))
      boot = WirelessBootstrap(rfcomm, self._bootstrap_log, device_serial=config["device_name"],
                               version_status=int(config.get("version_status", 0)))
      self._stage("wifi_start")
      result = boot.run(lambda credentials: lease.acquire(credentials, cancelled=boot.join_is_cancelled), cancelled=self._stop.is_set)
    except Exception as error:
      failed_stage = getattr(error, "stage", self._status["last_stage"])
      if source == "cache" and not self._stop.is_set() and failed_stage in ("rfcomm", "wifi_start"):
        self._remember_channel(address, None)  # the car never answered there; ask it over SDP next time
        self.log("rfcomm_cache_dropped", channel=channel)
      raise
    if source == "sdp":
      self._remember_channel(address, channel)
    self._set(head_unit=result.head_unit)
    bluez.restore_class()  # the car has accepted the comma; stop looking like a phone to everything else
    keepalive_stop = threading.Event()
    threading.Thread(target=boot.keepalive, args=(keepalive_stop,), name="starpilot_auto_rfcomm_keepalive", daemon=True).start()
    try:
      self._project(result, lease, ident)
    finally:
      keepalive_stop.set()

  def _discover_channel(self, address: str) -> int:
    from openpilot.starpilot.system.starpilot_auto import bt_sockets, sdp
    last_error: Exception | None = None
    for settle in SDP_SETTLE:
      self._check_cancel()
      try:
        with self._track(bt_sockets.connect_l2cap(address, sdp.SDP_PSM)) as sdp_sock:
          self._wait(settle)
          return sdp.query_channel(sdp_sock)
      except (OSError, sdp.SdpError) as error:
        last_error = error
        self.log("sdp_retry", error=str(error), settle=settle)
        self._wait(0.35)
    raise RuntimeError(f"Could not find the car's Starpilot Auto service: {last_error}")

  def _attempt_usb(self) -> None:
    """Wired: wait for the car's accessory handshake on USB (or skip it), then project over the cable."""
    from openpilot.starpilot.system.starpilot_auto import usb_accessory as usb
    ident = identity_store.load_identity()
    mode = self.config["usb_mode"]
    gadget = usb.AccessoryGadget(self.log)
    listener = usb.UeventListener()
    bridge = None
    failed = False
    try:
      direct = mode == "direct"
      gadget.prepare(direct=direct)
      self._stage("waiting_for_usb")
      if direct:
        self._await_usb_configured(listener, None, gadget.connection_state)
      else:
        direct = self._await_accessory_start(listener, fallback=mode == "auto", state_reader=gadget.connection_state)
        gadget.switch_to_accessory()
        if not self._await_usb_configured(listener, USB_CONFIGURE_WAIT, gadget.connection_state):
          raise RuntimeError("The car did not finish USB setup. Use its Starpilot Auto data port and a data-capable cable")
      method = "direct" if direct else "handshake"
      self._stage("usb_accessory", method)
      bridge = usb.AccessoryBridge(log=self.log)
      self.log("usb_accessory_ready", method=method, strings=getattr(bridge, "strings", {}))
      self._project(None, UsbLease(bridge), ident, connect=lambda: self._track(bridge.socket))
    except BaseException:
      failed = True
      raise
    finally:
      self._release_usb(gadget, bridge, listener, failed)

  def _release_usb(self, gadget, bridge, listener, failed: bool) -> None:
    """Undo a wired attempt, running every step even when one fails.

    Closing an fd in another thread does not cancel a Linux blocking read, so the gadget
    detaches first and the bridge workers are joined before the fd can be reused. A cleanup
    error is logged, and raised only when the attempt itself ended cleanly: it must never
    replace the real reason (a car-requested stop keeps its longer retry delay).
    """
    errors = []
    steps = [("detach", gadget.detach), ("bridge", bridge.close if bridge is not None else None),
             ("listener", listener.close), ("restore", gadget.restore)]
    for name, step in steps:
      if step is None:
        continue
      try:
        step()
      except Exception as error:
        errors.append(error)
        self.log("usb_cleanup_failed", step=name, error=str(error))
    if errors and not failed:
      raise errors[0]

  def recover_usb(self) -> None:
    """At startup: undo a wired session a crash interrupted, so the car stops seeing a dead accessory
    and ADB comes back if it is on. Nothing happens unless our gadget was left holding the USB port."""
    try:
      from openpilot.starpilot.system.starpilot_auto import usb_accessory as usb
      usb.AccessoryGadget(self.log).recover()
    except Exception as error:
      self.log("usb_recover_failed", error=str(error))

  def _usb_event(self, listener) -> dict | None:
    self._check_cancel()
    event = listener.next(0.5)
    if event is not None and "USB_STATE" in event:
      self.log("usb_state", state=event["USB_STATE"])
    return event

  def _await_accessory_start(self, listener, fallback: bool, state_reader=lambda: "") -> bool:
    """Wait for the car's AOA START; True when it never came and the comma should present as an accessory itself.

    The wait starts when the car first connects, not when it configures the comma: a head unit
    that reads the descriptors of a device it does not recognise may never configure it at all.
    """
    connected_at = None
    while True:
      event = self._usb_event(listener)
      if event is not None:
        if event.get("ACCESSORY") == "START":
          return False
        state = event.get("USB_STATE")
        if state in ("CONNECTED", "CONFIGURED"):
          connected_at = connected_at or time.monotonic()
        elif state == "DISCONNECTED":
          connected_at = None
      state = state_reader()
      if state in ("CONNECTED", "CONFIGURED") and connected_at is None:
        connected_at = time.monotonic()
      elif state == "DISCONNECTED":
        connected_at = None
      if fallback and connected_at is not None and time.monotonic() - connected_at >= USB_HANDSHAKE_WAIT:
        # Some head units only send the handshake to devices they recognise as phones.
        self.log("usb_no_accessory_start", waited=USB_HANDSHAKE_WAIT)
        return True

  def _await_usb_configured(self, listener, timeout: float | None, state_reader=lambda: "") -> bool:
    """Wait until the car has configured the accessory, so reads do not fail on a link that is not up yet."""
    started = time.monotonic()
    while timeout is None or time.monotonic() - started < timeout:
      self._check_cancel()
      if state_reader() == "CONFIGURED":
        return True  # kernels may coalesce or omit the android_usb state uevent
      event = self._usb_event(listener)
      if event is not None and event.get("USB_STATE") == "CONFIGURED" and state_reader() in ("", "CONFIGURED"):
        return True
    self.log("usb_configure_timeout", waited=timeout)
    return False

  def _bootstrap_log(self, name: str, **values) -> None:
    self.log(name, **values)
    if name == "bootstrap_tx" and values.get("message") == NAMES[2]:
      self._set(state="wifi_info", last_stage="wifi_info")
    elif name == "wifi_joining":
      self._set(state="joining_wifi", last_stage="joining_wifi", detail=str(values.get("ssid", "")))

  def _connect_tcp(self, result, lease) -> socket.socket:
    self._stage("connecting_tcp", f"{result.endpoint.ip}:{result.endpoint.port}")
    last_error: Exception | None = None
    for attempt in range(TCP_ATTEMPTS):
      self._check_cancel()
      try:
        sock = socket.create_connection((result.endpoint.ip, result.endpoint.port), timeout=5.0,
                                        source_address=(lease.local_ip, 0) if lease.local_ip else None)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return self._track(sock)
      except OSError as error:
        last_error = error
        self.log("tcp_retry", attempt=attempt + 1, error=str(error))
        self._wait(1.0 + attempt * 0.5)
    raise RuntimeError(f"Car did not accept the projection connection: {last_error}")

  def _adapter_address(self) -> str:
    """The comma's Bluetooth address, which the car's Bluetooth service asks the phone for; empty if unknown."""
    try:
      return str(self._phone().adapter()[1].get("Address", "")).upper()
    except Exception as error:
      self.log("bluetooth_address_unavailable", error=str(error))
      return ""

  def _project(self, result, lease, ident, connect=None) -> None:
    config = self.config
    sock = connect() if connect is not None else self._connect_tcp(result, lease)
    ca = ident.root if config.get("verify_head_unit", True) else None
    session = ProjectionSession(sock, ident.cert, ident.key, self.log, ca)
    self._stage("authenticating")
    session.authenticate()
    self._stage("negotiating")
    mode = session.start(config["device_name"], "comma.ai", self._adapter_address())
    self._set(mode=mode.as_dict(), error="")
    self.log("projection_ready", mode=mode.as_dict(), head_unit_subject=session.head_unit_subject)

    from openpilot.starpilot.system.starpilot_auto.hw_encoder import create_encoder
    software_fps = min(SOFTWARE_FPS, config["fps"]) if config["fps"] else SOFTWARE_FPS
    encoder, fps = create_encoder(mode.width, mode.height, preference=config["encoder"], bitrate_kbps=config["bitrate_kbps"],
                                  margin_height=mode.margin_height, software_fps=software_fps, log=self.log,
                                  rate_control=config["rate_control"])
    fps = min(fps, mode.fps, config["fps"] or fps)
    interval = 1.0 / fps
    flags = (FLAG_NV12 if config["gpu_nv12"] and getattr(encoder, "supports_nv12", False) else 0) | \
            (FLAG_ASYNC_READBACK if config["async_readback"] else 0)
    request = FrameRequest(mode.width, mode.height, mode.margin_width, mode.margin_height, int(interval * 1e6), flags)
    self.log("frame_pipeline", nv12=bool(flags & FLAG_NV12), async_readback=bool(flags & FLAG_ASYNC_READBACK))
    view = config["view"]
    if view == "car" and not self._synthetic and self._renderer_command is None and not renderer_available():
      view = "mirror"
    source = None
    try:
      source = ViewSource(view, request, self.log, synthetic=self._synthetic,
                          mirror_path=self._frame_path or DEFAULT_FRAME_PATH, car_path=self._car_frame_path,
                          touch_path=self._touch_path, renderer_command=self._renderer_command,
                          renderer_log=identity_store.LOG_DIR / "car_ui.log")
      self._set(view=source.label, encoder=getattr(encoder, "backend", "libx264"), target_fps=fps)
      self._stream(session, encoder, source, lease, interval)
    finally:
      try:
        if source is not None:
          source.close()
      finally:  # the hardware encoder is a scarce device: release it even if the view failed to start or close
        try:
          encoder.close()
        finally:
          if self._stop.is_set():
            try:
              session.shutdown()
            except Exception:
              pass

  def _stream(self, session: ProjectionSession, encoder, source: ViewSource, lease, interval: float) -> None:
    started = time.monotonic()
    last_fresh = time.monotonic()
    last_unavailable = 0.0
    next_check = 0.0
    ages: deque[float] = deque(maxlen=120)
    sent_times: deque[float] = deque(maxlen=200)
    unavailable: dict[str, bytes] = {}
    recoveries: list[float] = []  # when the hardware encoder was reopened, this session
    encode_peak = 0.0
    wait_for_frame = False
    self._stage("streaming")
    while not self._stop.is_set():
      # Wait only when there was no frame or the receiver's window is full.
      # select wakes immediately for touches/ACKs; sleeping after every encode
      # used to add dead time even when the next frame was already available.
      timeout = min(interval / 4, 0.01) if wait_for_frame else 0.0
      handled = session.pump(timeout if session.can_send() else 0.05)
      # Bound the drain so a burst of input cannot starve video, but do not
      # make each queued touch or ACK wait for another encode/poll cycle.
      for _ in range(15):
        if not handled:
          break
        handled = session.pump(0.0)
      session.check_progress()
      now = time.monotonic()
      wait_for_frame = True
      if session.focused or now - started < PREWARM_SECONDS:
        source.demand(1.0)
      else:
        source.release_demand()
      if session.touch_events:
        source.send_touches(list(session.touch_events))
        session.touch_events.clear()
      state = "streaming" if session.focused else "suspended"
      if self._status["state"] != state:
        self._set(state=state)
      if session.can_send():
        frame = source.latest()
        if frame is not None:
          age = now - frame.captured_ns / 1e9
          encode = encoder.encode_nv12 if frame.pixel_format == FORMAT_NV12 else encoder.encode_rgba
          encoded = self._encode(encoder, encode, frame.data, session.needs_keyframe, recoveries) if age <= FRAME_MAX_AGE else None
          if encoded is not None:
            data, keyframe = encoded
            encode_peak = max(encode_peak, encoder.last_encode_ms)
            session.send_frame(data, frame.captured_ns // 1000, keyframe=keyframe)
            if source.view == "car":
              source.source.mark_sent(frame.captured_ns)
            sent_at = time.monotonic()
            ages.append(sent_at - frame.captured_ns / 1e9)
            sent_times.append(sent_at)
            last_fresh = sent_at
            wait_for_frame = False
        elif now - last_fresh > UNAVAILABLE_AFTER and now - last_unavailable > (interval if source.waiting_for_first_frame else 1.0):
          # The UI stopped producing frames (e.g. the offroad render budget ran
          # out). Say so on the car instead of freezing on an old image.
          text = "Starting StarPilot" if source.waiting_for_first_frame else "StarPilot display unavailable"
          if text not in unavailable:
            unavailable[text] = self._unavailable_frame(source.request, text)
          # Until the first real frame the card streams at the full frame rate, as a phone's video would
          keyframe = session.needs_keyframe or not source.waiting_for_first_frame
          encoded = self._encode(encoder, encoder.encode_rgba, unavailable[text], keyframe, recoveries)
          if encoded is not None:
            session.send_frame(encoded[0], time.monotonic_ns() // 1000, keyframe=encoded[1])
          last_unavailable = now
      now = time.monotonic()
      if now >= next_check:
        next_check = now + 1.0
        if not lease.still_connected():
          raise RuntimeError(getattr(lease, "lost", "Lost the car's Wi-Fi network"))
        label = source.label
        source.check(now, focused=session.focused)
        if source.label != label:
          self._set(view=source.label)
        window = [t for t in sent_times if now - t <= 5.0]
        ordered = sorted(ages)
        stats = {**session.stats(), "fps": round(len(window) / 5.0, 1), "encode_ms": round(encoder.last_encode_ms, 1),
                 "encode_peak_ms": round(encode_peak, 1), "encoder_recoveries": len(recoveries),
                 "frame_age_p95_ms": round(ordered[int(len(ordered) * 0.95) - 1] * 1000) if ordered else None,
                 "uptime_s": round(now - started), "frames_from_view": source.frames}
        self._set(stats=stats)
        if int(now - started) % 30 == 0:
          self.log("stats", **stats)
          encode_peak = 0.0  # the peak covers each logged 30 s window

  def _encode(self, encoder, encode, data: bytes, keyframe: bool, recoveries: list[float]) -> tuple[bytes, bool] | None:
    """Encode one frame. When the hardware encoder fails (the shared VPU stalled past the
    deadline), reopen it and drop this frame instead of tearing down the whole session:
    the next frame is an IDR, and the car waits 3 s for video before taking its screen back.
    Repeated failures still end the attempt, which reconnects from scratch."""
    started = time.monotonic()
    try:
      return encode(data, keyframe=keyframe)
    except Exception as error:
      failed = time.monotonic()
      recent = sum(1 for at in recoveries if failed - at <= ENCODER_RECOVERY_WINDOW)
      reopen = getattr(encoder, "reopen", None)  # libx264 has nothing to reopen
      if reopen is None or recent >= ENCODER_RECOVERIES:
        self.log("encoder_failed", error=str(error), encode_ms=round((failed - started) * 1000), recent_recoveries=recent)
        raise
      try:
        reopen()
      except Exception as reopen_error:
        self.log("encoder_reopen_failed", error=str(error), reopen_error=str(reopen_error))
        raise error from reopen_error
      recoveries.append(failed)
      self.log("encoder_recovered", error=str(error), encode_ms=round((failed - started) * 1000),
               reopen_ms=round((time.monotonic() - failed) * 1000), recent_recoveries=recent + 1, total=len(recoveries))
      return None

  @staticmethod
  def _unavailable_frame(request: FrameRequest | None, text: str) -> bytes:
    assert request is not None
    try:
      from PIL import Image, ImageDraw, ImageFont
      from openpilot.common.basedir import BASEDIR

      base = Path(BASEDIR)
      logo_path = base / "starpilot" / "system" / "the_galaxy" / "assets" / "images" / "main_logo.png"
      font_path = base / "selfdrive" / "assets" / "fonts" / "como-heavy.otf"

      bg_color = (10, 10, 22, 255)  # Cosmic void #0a0a16
      canvas = Image.new("RGBA", (request.width, request.height), bg_color)

      font_size = max(18, min(64, int(request.height * 0.06)))
      try:
        font = ImageFont.truetype(str(font_path), font_size) if font_path.exists() else ImageFont.load_default()
      except Exception:
        font = ImageFont.load_default()

      draw = ImageDraw.Draw(canvas)
      bbox = draw.textbbox((0, 0), text, font=font)
      text_w = bbox[2] - bbox[0]
      text_h = bbox[3] - bbox[1]

      gap = max(12, int(request.height * 0.04))
      target_logo_h = int(min(request.height * 0.42, request.width * 0.35))

      if logo_path.exists() and target_logo_h > 20:
        logo = Image.open(logo_path).convert("RGBA")
        logo_w = int(logo.width * (target_logo_h / logo.height))
        logo_resized = logo.resize((logo_w, target_logo_h), Image.Resampling.LANCZOS)
        total_h = target_logo_h + gap + text_h
        start_y = max(8, (request.height - total_h) // 2)
        logo_x = (request.width - logo_w) // 2
        canvas.paste(logo_resized, (logo_x, start_y), logo_resized)
        text_y = start_y + target_logo_h + gap
      else:
        text_y = (request.height - text_h) // 2

      text_x = (request.width - text_w) // 2
      draw.text((text_x + 1, text_y + 1), text, font=font, fill=(30, 20, 50, 180))
      draw.text((text_x, text_y), text, font=font, fill=(250, 248, 255, 255))
      return canvas.tobytes()
    except Exception:
      try:
        import cv2
        import numpy as np
        image = np.zeros((request.height, request.width, 4), np.uint8)
        image[..., 3] = 255
        scale = request.height / 480
        size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, max(1, int(2 * scale)))[0]
        cv2.putText(image, text, ((request.width - size[0]) // 2, (request.height + size[1]) // 2), cv2.FONT_HERSHEY_SIMPLEX,
                    scale, (255, 255, 255, 255), max(1, int(2 * scale)), cv2.LINE_AA)
        return image.tobytes()
      except Exception:
        return bytes(request.width * request.height * 4)
