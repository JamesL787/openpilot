"""Receiver timing differences and repeated connection/cleanup regressions."""

from dataclasses import replace
import os
import socket
import threading
import time
import tty

import pytest

from openpilot.starpilot.system.starpilot_auto import bootstrap as bs, identity, supervisor, usb_accessory as usb
from openpilot.starpilot.system.starpilot_auto.connection_help import recovery_hint, setup_instructions
from openpilot.starpilot.system.starpilot_auto.tests.test_starpilot_auto import FakeNetworkManager, credentials, make_lease
from openpilot.starpilot.system.starpilot_auto.wire import field


@pytest.fixture
def sup(tmp_path, monkeypatch):
  monkeypatch.setattr(identity, "CONFIG_PATH", tmp_path / "config.json")
  monkeypatch.setattr(identity, "LOG_DIR", tmp_path / "logs")
  return supervisor.Supervisor(synthetic=True)


@pytest.mark.parametrize("version_first", [False, True])
def test_ping_only_receiver_still_gets_start_prompt(monkeypatch, version_first):
  now = [0.0]
  monkeypatch.setattr(bs.time, "monotonic", lambda: now[0])
  boot = bs.WirelessBootstrap(None, lambda *a, **k: None, stage_timeout=1, initial_kick_delay=0.2, start_request_delay=0.2)
  sent = []
  monkeypatch.setattr(boot, "send", lambda message, payload=b"": sent.append(message))

  def receive(timeout):
    now[0] += 0.1
    if version_first:
      return bs.WIFI_VERSION_REQUEST, field(1, 1) + field(2, 1)  # duplicate requests must not defer the prompt
    return bs.WIFI_PING_REQUEST, field(1, 42)

  monkeypatch.setattr(boot, "next_frame", receive)
  with pytest.raises(bs.BootstrapTimeout):
    boot.run(lambda _: pytest.fail("No credentials yet"))
  assert bs.WIFI_START_REQUEST in sent


@pytest.mark.parametrize("order", ["credentials_first", "setup_after_start"])
def test_bootstrap_accepts_network_details_in_either_order(monkeypatch, order):
  endpoint = field(1, "192.168.50.1") + field(2, 5288)
  network = field(1, "CarAA") + field(2, "secret-key") + field(4, 8)
  frames = [(bs.WIFI_INFO_RESPONSE, network), (bs.WIFI_START_REQUEST, endpoint)] if order == "credentials_first" else [
    (bs.WIFI_START_REQUEST, endpoint),
    (bs.WIFI_SETUP_INFO, field(5, field(1, "CarAA") + field(3, "secret-key") + field(4, 8))),
  ]
  boot = bs.WirelessBootstrap(None, lambda *a, **k: None)
  monkeypatch.setattr(boot, "next_frame", lambda _: frames.pop(0))
  monkeypatch.setattr(boot, "send", lambda *a: None)
  joined = []
  result = boot.run(joined.append)
  assert result.endpoint == bs.Endpoint("192.168.50.1", 5288)
  assert joined[0].ssid == "CarAA" and joined[0].key == "secret-key"


@pytest.mark.parametrize("failure", ["disconnect", "cancel", "rejection"])
def test_failed_bootstrap_joins_wifi_worker_before_returning(failure):
  phone, car = socket.socketpair()
  stop = threading.Event()
  finished = threading.Event()
  boot = bs.WirelessBootstrap(phone, lambda *a, **k: None)
  car.sendall(bs.encode_frame(bs.WIFI_START_REQUEST, field(1, "192.168.50.1") + field(2, 5288)) +
              bs.encode_frame(bs.WIFI_INFO_RESPONSE, field(1, "CarAA") + field(2, "secret-key") + field(4, 8)))

  def join(_):
    if failure == "disconnect":
      car.close()
    elif failure == "cancel":
      stop.set()
    else:
      car.sendall(bs.encode_frame(bs.WIFI_CONNECTION_REJECTION, field(1, 1)))
    deadline = time.monotonic() + 2
    while not boot.join_is_cancelled():
      if time.monotonic() >= deadline:
        raise AssertionError("Wi-Fi join was left running after bootstrap failed")
      time.sleep(0.005)
    finished.set()

  try:
    with pytest.raises((bs.BootstrapError, OSError)):
      boot.run(join, cancelled=stop.is_set)
    assert finished.is_set(), "cleanup must not race an old Wi-Fi activation"
  finally:
    phone.close()
    car.close()


@pytest.mark.parametrize("user_changed_network", [False, True])
def test_stop_during_backoff_restores_previous_wifi_only_if_still_owned(user_changed_network):
  nm = FakeNetworkManager()
  lease = make_lease(nm)
  lease.acquire(credentials())
  lease.release(restore=False)  # no D-Bus router remains between attempts
  nm.active_device_connection = "/active/user-picked" if user_changed_network else "/"
  lease.release(restore=True)
  assert nm.calls.count("ActivateConnection") == (0 if user_changed_network else 1)
  lease.release(restore=True)
  assert nm.calls.count("ActivateConnection") == (0 if user_changed_network else 1)


def test_projection_profile_has_stable_identity_and_no_power_saving():
  from openpilot.starpilot.system.starpilot_auto.network import connection_settings
  first, second = [connection_settings(credentials(), "wlan0") for _ in range(2)]
  assert first["connection"]["uuid"] != second["connection"]["uuid"]
  for settings in (first, second):
    assert settings["802-11-wireless"]["assigned-mac-address"] == ("s", "permanent")
    assert settings["802-11-wireless"]["powersave"] == ("u", 2)


@pytest.mark.parametrize("security", [4, 8, 12, 32, 40])
def test_missing_password_cannot_downgrade_secured_car_network(security):
  from openpilot.starpilot.system.starpilot_auto.network import NetworkError, connection_settings
  with pytest.raises(NetworkError, match="password"):
    connection_settings(replace(credentials(), security=security, key=""), "wlan0")


def test_long_failed_setup_does_not_reset_backoff_and_countdown_moves(sup, monkeypatch):
  now = [100.0]
  monkeypatch.setattr(supervisor.time, "monotonic", lambda: now[0])
  sup.config["connection"] = "wired"
  delays = []

  def fail(_):
    now[0] += 80  # a slow setup is not a stable projection session
    raise RuntimeError("car still starting")

  def wait(delay):
    delays.append(delay)
    assert sup.status()["retry_in"] == delay
    now[0] += 1
    assert sup.status()["retry_in"] == delay - 1
    if len(delays) == 5:
      sup._stop.set()

  monkeypatch.setattr(sup, "_attempt", fail)
  monkeypatch.setattr(sup, "_wait", wait)
  sup._run(1)
  assert delays == list(supervisor.BACKOFF_SECONDS)


def test_usb_state_poll_recovers_missing_events_and_rejects_stale_events(sup, monkeypatch):
  from openpilot.starpilot.system.starpilot_auto.tests.test_usb_accessory import CONFIGURED, ScriptedListener
  monkeypatch.setattr(supervisor, "USB_HANDSHAKE_WAIT", 0.03)
  assert sup._await_accessory_start(ScriptedListener([]), True, lambda: "CONNECTED")
  assert sup._await_usb_configured(ScriptedListener([]), 0.03, lambda: "CONFIGURED")
  assert not sup._await_usb_configured(ScriptedListener([(0, CONFIGURED)]), 0.03, lambda: "DISCONNECTED")


def test_usb_does_not_open_bridge_before_car_configures(sup, monkeypatch):
  from openpilot.starpilot.system.starpilot_auto.tests.test_usb_accessory import START, ScriptedListener
  calls = []

  class Gadget:
    def __init__(self, log):
      pass

    def prepare(self, **kwargs):
      calls.append("prepare")

    def switch_to_accessory(self):
      calls.append("switch")

    def connection_state(self):
      return "CONNECTED"

    def detach(self):
      calls.append("detach")

    def restore(self):
      calls.append("restore")

  listener = ScriptedListener([(0, START)])
  listener.close = lambda: calls.append("close_listener")
  monkeypatch.setattr(identity, "load_identity", lambda: None)
  monkeypatch.setattr(usb, "AccessoryGadget", Gadget)
  monkeypatch.setattr(usb, "UeventListener", lambda: listener)
  monkeypatch.setattr(usb, "AccessoryBridge", lambda **kwargs: pytest.fail("car never configured the accessory"))
  monkeypatch.setattr(supervisor, "USB_CONFIGURE_WAIT", 0.03)
  with pytest.raises(RuntimeError, match="finish USB setup"):
    sup._attempt_usb()
  assert calls == ["prepare", "switch", "detach", "close_listener", "restore"]


def test_usb_close_is_idempotent_and_workers_finish():
  master, slave = os.openpty()
  tty.setraw(slave)
  bridge = usb.AccessoryBridge(os.ttyname(slave))
  os.close(slave)
  os.close(master)  # equivalent to detaching the controller before closing
  assert bridge.closed.wait(2)
  bridge.close()
  assert bridge.fd == -1 and all(not thread.is_alive() for thread in bridge.threads)
  bridge.close()  # must not close a reused descriptor


def test_setup_help_distinguishes_transports_and_preserves_onroad_start():
  wired = setup_instructions({"connection": "wired"})
  assert "goes onroad" in wired and "No Bluetooth pairing" in wired and "data-capable cable" in wired
  wireless = setup_instructions({"connection": "wireless"})
  assert "wireless Starpilot Auto" in wireless and "confirm the code" in wireless
  assert "certificate" in recovery_hint({"error": "certificate expired"})
  assert "data-capable" in recovery_hint({"connection": "wired", "last_stage": "waiting_for_usb"})


CAR_ADDRESS = "C4:B7:57:6E:AC:E2"


def test_join_gives_the_reported_bssid_most_of_the_wait(monkeypatch):
  from openpilot.starpilot.system.starpilot_auto import network
  lease = network.NetworkLease(lambda *a, **k: None)
  budgets = []

  def once(attempt, timeout, cancelled):
    budgets.append((attempt.bssid, timeout))
    if attempt.bssid:
      raise network.NetworkError("access point not up yet")
    return "192.168.50.23"

  monkeypatch.setattr(lease, "_acquire_once", once)
  assert lease.acquire(credentials()) == "192.168.50.23"
  assert budgets == [("AA:BB:CC:DD:EE:FF", 90.0), ("", 30.0)]


def _wireless_backoff_harness(sup, monkeypatch, failure):
  now = [100.0]
  monkeypatch.setattr(supervisor.time, "monotonic", lambda: now[0])
  monkeypatch.setattr(sup, "_lease", lambda: supervisor.NoLease())
  sup.config["connection"] = "wireless"
  sup.config["receiver_address"] = CAR_ADDRESS
  starts, waits = [], []

  def attempt(_):
    starts.append(now[0])
    if len(starts) == 2:
      sup._stop.set()
    raise failure

  def wait(seconds):
    waits.append(seconds)
    now[0] += seconds
    if len(starts) == 1 and now[0] - starts[0] >= 5 and not sup._hfp_link.is_set():
      sup._hfp_connected(CAR_ADDRESS.lower())  # the car reaches out mid-backoff, e.g. the driver taps Android Auto
    if sup._stop.is_set():
      raise supervisor.Cancelled()

  monkeypatch.setattr(sup, "_attempt", attempt)
  monkeypatch.setattr(sup, "_wait", wait)
  return starts, waits


def test_car_opening_hands_free_ends_the_backoff_early(sup, monkeypatch):
  monkeypatch.setattr(supervisor, "BACKOFF_SECONDS", (30.0,))
  starts, _ = _wireless_backoff_harness(sup, monkeypatch, RuntimeError("car not answering"))
  sup._run(1)
  assert len(starts) == 2
  assert starts[1] - starts[0] < 6  # retried when the car connected, not after the 30 s backoff


def test_car_ending_projection_still_gets_its_full_pause(sup, monkeypatch):
  from openpilot.starpilot.system.starpilot_auto.session import PeerRequestedStop
  starts, waits = _wireless_backoff_harness(sup, monkeypatch, PeerRequestedStop("Head unit ended projection"))
  sup._run(1)
  assert waits[0] == supervisor.PEER_STOP_RETRY_SECONDS
