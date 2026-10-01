import json
import socket
import subprocess
import sys
import threading
import time

import pytest

from openpilot.starpilot.system.starpilot_auto import auto_connect
from openpilot.starpilot.system.starpilot_auto.auto_connect import AutoConnectPolicy
from openpilot.starpilot.system.starpilot_auto.bluez_phone import address_from_path
from openpilot.starpilot.system.starpilot_auto.tests.fake_head_unit import FakeHeadUnit, make_identity, rfcomm_head_unit
from openpilot.starpilot.system.starpilot_auto.tests.test_starpilot_auto import make_supervisor

CAR = "AA:BB:CC:DD:EE:01"


@pytest.fixture(scope="module")
def identity(tmp_path_factory):
  return make_identity(tmp_path_factory.mktemp("identity"))


def decide(policy, now, onroad=False, car_link=False, ready=True, running=False, enabled=True):
  return policy.decide(now, enabled=enabled, onroad=onroad, car_link=car_link, ready=ready, running=running)


# -------------------------------------------------------------------- policy

def test_policy_starts_when_car_present_and_ready():
  policy = AutoConnectPolicy()
  assert decide(policy, 0, onroad=False) is None
  assert decide(policy, 1, onroad=True, ready=False) is None      # Bluetooth still starting
  assert decide(policy, 2, onroad=True) == "start"
  assert decide(AutoConnectPolicy(), 0, car_link=True) == "start"  # the car reached the comma while offroad
  assert decide(AutoConnectPolicy(), 0, onroad=True, enabled=False) is None


def test_policy_stops_after_car_gone():
  policy = AutoConnectPolicy()
  assert decide(policy, 0, onroad=True, running=True) is None
  assert decide(policy, 10, running=True) is None                # ignition off: grace period starts
  assert decide(policy, 10 + auto_connect.STOP_AFTER - 1, running=True) is None
  assert decide(policy, 20, car_link=True, running=True) is None  # car link seen again: timer resets
  assert decide(policy, 21, running=True) is None
  assert decide(policy, 21 + auto_connect.STOP_AFTER, running=True) == "stop"
  assert decide(policy, 100) is None                             # stopped, car still gone: no restart


def test_policy_leaves_sessions_that_never_saw_the_car():
  policy = AutoConnectPolicy()
  for now in range(0, 300, 10):
    assert decide(policy, now, running=True) is None


def test_policy_manual_stop_holds_until_next_drive():
  policy = AutoConnectPolicy()
  assert decide(policy, 0, onroad=True) == "start"
  policy.manual_stop(running=True)
  assert decide(policy, 1, onroad=True) is None
  assert decide(policy, 2, onroad=True, car_link=True) is None
  assert decide(policy, 3) is None                               # ignition off
  assert decide(policy, 4, onroad=True) == "start"               # next drive


def test_policy_manual_start_clears_hold_and_idle_stop_does_not_hold():
  policy = AutoConnectPolicy()
  policy.manual_stop(running=False)
  assert decide(policy, 0, onroad=True) == "start"
  policy.manual_stop(running=True)
  policy.manual_start()
  assert decide(policy, 1, onroad=True) == "start"


def test_policy_waits_after_refused_start():
  policy = AutoConnectPolicy()
  policy.start_refused(0)
  assert decide(policy, 1, onroad=True) is None
  assert decide(policy, auto_connect.START_REFUSED_WAIT, onroad=True) == "start"


# ----------------------------------------------------------------- supervisor

def test_address_from_path():
  assert address_from_path("/org/bluez/hci0/dev_aa_bb_cc_dd_ee_01") == CAR


def auto_supervisor(identity, tmp_path, monkeypatch, onroad):
  sup, _ = make_supervisor(identity, tmp_path, monkeypatch, lambda *a, **k: socket.socketpair()[0])
  sup._onroad = lambda: onroad["value"]
  starts = []
  alive = {"value": False}
  monkeypatch.setattr(sup, "start", lambda trigger="manual": (starts.append(trigger), alive.update(value=True)))
  monkeypatch.setattr(sup, "stop", lambda *a, **k: alive.update(value=False))
  monkeypatch.setattr(sup, "_session_alive", lambda: alive["value"])
  return sup, starts, alive


def test_supervisor_auto_starts_on_ignition_and_stops_when_car_gone(identity, tmp_path, monkeypatch):
  onroad = {"value": False}
  sup, starts, alive = auto_supervisor(identity, tmp_path, monkeypatch, onroad)
  bluez = sup._phone()
  assert bluez.trusted == [CAR]
  bluez.connected = False
  sup.maintain(0)
  assert starts == [] and bluez.hfp_registrations == 1           # standby gateway, nothing started
  bluez.adapter_ready = False
  onroad["value"] = True
  sup.maintain(2)
  assert starts == []                                            # radio not up yet: no wasted attempt
  bluez.adapter_ready = True
  sup.maintain(4)
  assert starts == ["onroad"] and alive["value"]
  onroad["value"] = False
  sup.maintain(6)
  sup.maintain(6 + auto_connect.STOP_AFTER)
  assert not alive["value"]


def test_supervisor_auto_start_on_car_connection_and_user_stop_hold(identity, tmp_path, monkeypatch):
  onroad = {"value": False}
  sup, starts, alive = auto_supervisor(identity, tmp_path, monkeypatch, onroad)
  bluez = sup._phone()
  bluez.connected = False
  sup._hfp_connected(CAR.lower())                                # the car reached the hands-free gateway
  sup.maintain(time.monotonic())
  assert starts == ["car_connected"]
  sup.user_stop()
  sup.maintain(time.monotonic())
  assert starts == ["car_connected"] and sup.status()["auto_paused"]


def test_supervisor_auto_start_holds_during_dhu_session(identity, tmp_path, monkeypatch):
  from openpilot.starpilot.system.starpilot_auto import identity as identity_store
  monkeypatch.setattr(identity_store, "DATA_DIR", tmp_path / "starpilot_auto")
  onroad = {"value": False}
  sup, starts, _ = auto_supervisor(identity, tmp_path, monkeypatch, onroad)
  sup._phone().connected = False
  # A live process with dhu_device on its command line, as tools/starpilot_auto/dhu_device.py has.
  dhu = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "dhu_device"])
  try:
    (tmp_path / "starpilot_auto" / "dhu-5288.pid").write_text(f"{dhu.pid}\n")
    sup.maintain(0)
    onroad["value"] = True
    sup.maintain(2)
    assert starts == []                                          # going onroad under the DHU starts nothing
  finally:
    dhu.kill()
    dhu.wait()
  sup.maintain(4)
  assert starts == ["onroad"]                                    # a stale pid file does not hold it


@pytest.mark.parametrize("content", ["", "not a pid", "999999999"])
def test_supervisor_auto_start_ignores_unusable_dhu_pid_file(identity, tmp_path, monkeypatch, content):
  from openpilot.starpilot.system.starpilot_auto import identity as identity_store
  monkeypatch.setattr(identity_store, "DATA_DIR", tmp_path / "starpilot_auto")
  onroad = {"value": True}
  sup, starts, _ = auto_supervisor(identity, tmp_path, monkeypatch, onroad)
  (tmp_path / "starpilot_auto" / "dhu-5288.pid").write_text(content)
  sup.maintain(0)
  assert starts == ["onroad"]


def test_supervisor_auto_connect_off(identity, tmp_path, monkeypatch):
  onroad = {"value": True}
  sup, starts, _ = auto_supervisor(identity, tmp_path, monkeypatch, onroad)
  sup.set_auto_connect(False)
  bluez = sup._phone()
  sup.maintain(0)
  assert starts == [] and bluez.released == 1 and bluez.hfp_registrations == 0
  assert json.loads((tmp_path / "starpilot_auto" / "config.json").read_text())["auto_connect"] is False



def test_supervisor_auto_starts_wired_on_ignition_without_bluetooth(identity, tmp_path, monkeypatch):
  onroad = {"value": True}  # the car was already on when the comma booted
  sup, starts, alive = auto_supervisor(identity, tmp_path, monkeypatch, onroad)
  sup.set_connection("wired")
  sup.config["receiver_address"] = ""  # wired needs no chosen car
  bluez = sup._phone()                 # a gateway left from wireless use
  sup.maintain(0)
  assert starts == ["onroad"] and alive["value"]
  assert bluez.released == 1 and bluez.hfp_registrations == 0, "no Bluetooth standby for a USB car"
  onroad["value"] = False              # drive over: stop once the car has been gone a while
  sup.maintain(2)
  sup.maintain(2 + auto_connect.STOP_AFTER)
  assert not alive["value"]
  sup.maintain(3 + auto_connect.STOP_AFTER)
  assert starts == ["onroad"], "parked: nothing restarts until the next drive"
  onroad["value"] = True
  sup.maintain(4 + auto_connect.STOP_AFTER)
  assert starts == ["onroad", "onroad"]


def test_supervisor_wired_auto_connect_off_and_user_stop(identity, tmp_path, monkeypatch):
  onroad = {"value": True}
  sup, starts, alive = auto_supervisor(identity, tmp_path, monkeypatch, onroad)
  sup.set_connection("wired")
  sup.set_auto_connect(False)
  sup.maintain(0)
  assert starts == []
  sup.set_auto_connect(True)
  sup.maintain(2)
  assert starts == ["onroad"]
  sup.user_stop()
  sup.maintain(4)
  assert starts == ["onroad"] and sup.status()["auto_paused"]

def test_supervisor_auto_start_refused_reports_and_waits(identity, tmp_path, monkeypatch):
  onroad = {"value": True}
  sup, _ = make_supervisor(identity, tmp_path, monkeypatch, lambda *a, **k: socket.socketpair()[0])
  sup._onroad = lambda: onroad["value"]
  calls = []

  def refuse(trigger="manual"):
    calls.append(trigger)
    raise RuntimeError("Starpilot Auto identity missing")
  monkeypatch.setattr(sup, "start", refuse)
  sup.maintain(0)
  sup.maintain(2)
  assert calls == ["onroad"] and "identity missing" in sup.status()["error"]


def test_hfp_answers_only_the_chosen_car(identity, tmp_path, monkeypatch):
  sup, _ = make_supervisor(identity, tmp_path, monkeypatch, lambda *a, **k: socket.socketpair()[0])
  assert sup._hfp_accepts(CAR) and sup._hfp_accepts(CAR.lower())
  assert not sup._hfp_accepts("11:22:33:44:55:66")
  sup._pairing_until = time.monotonic() + 60
  assert sup._hfp_accepts("11:22:33:44:55:66")                   # a new car may pair


def test_new_car_paired_in_window_is_selected(identity, tmp_path, monkeypatch):
  sup, _ = make_supervisor(identity, tmp_path, monkeypatch, lambda *a, **k: socket.socketpair()[0])
  sup._onroad = lambda: False
  bluez = sup._phone()
  bluez.connected = False
  sup.prepare_pairing(60)
  bluez.paired_devices.append(("11:22:33:44:55:66", "Speaker", False))
  sup.maintain()
  assert sup.config["receiver_address"] == CAR                   # not an Starpilot Auto car
  bluez.paired_devices.append(("22:33:44:55:66:77", "Accord", True))
  sup.maintain()
  assert sup.config["receiver_address"] == "22:33:44:55:66:77" and sup.config["receiver_name"] == "Accord"
  assert "22:33:44:55:66:77" in bluez.trusted


# ------------------------------------------------ channel cache + phone class

def rejecting_car(identity, cars, channels):
  def rfcomm(address, channel, timeout=15.0):
    channels.append(channel)
    hu = FakeHeadUnit(identity, reject_auth=True)
    cars.append(hu)
    phone, car = socket.socketpair()

    def car_side():
      with car:
        rfcomm_head_unit(car, ("127.0.0.1", hu.port), pings=False)
        time.sleep(1.0)
    threading.Thread(target=car_side, daemon=True).start()
    return phone
  return rfcomm


def test_channel_cached_and_phone_class_restored_after_handshake(identity, tmp_path, monkeypatch):
  from openpilot.starpilot.system.starpilot_auto import bt_sockets
  cars, channels = [], []
  sup, _ = make_supervisor(identity, tmp_path, monkeypatch, rejecting_car(identity, cars, channels))
  sdp_calls = []
  original_l2cap = bt_sockets.connect_l2cap
  monkeypatch.setattr(bt_sockets, "connect_l2cap", lambda *a, **k: (sdp_calls.append(1), original_l2cap(*a, **k))[1])
  sup.start()
  deadline = time.monotonic() + 15
  while len(cars) < 2:
    assert time.monotonic() < deadline, sup.status()
    time.sleep(0.05)
  bluez = sup._phone()
  sup.stop()
  for hu in cars:
    hu.close()
  assert channels[:2] == [8, 8] and len(sdp_calls) == 1          # second attempt skipped SDP
  assert sup.config["rfcomm_cache"] == {CAR: 8}
  assert json.loads((tmp_path / "starpilot_auto" / "config.json").read_text())["rfcomm_cache"] == {CAR: 8}
  assert bluez.class_restored >= 2                               # after each handshake, before projection
  assert bluez.released == 0                                     # auto-connect keeps the car's gateway


def test_stale_cached_channel_is_dropped(identity, tmp_path, monkeypatch):
  def rfcomm(address, channel, timeout=15.0):
    raise ConnectionRefusedError(111, "Connection refused")
  sup, _ = make_supervisor(identity, tmp_path, monkeypatch, rfcomm)
  sup.config["rfcomm_cache"] = {CAR: 5}
  sup.start()
  deadline = time.monotonic() + 5
  while sup.config["rfcomm_cache"]:
    assert time.monotonic() < deadline, sup.status()
    time.sleep(0.02)
  sup.stop()


def test_config_sanitizes_channel_cache(tmp_path):
  from openpilot.starpilot.system.starpilot_auto import identity as identity_store
  path = tmp_path / "config.json"
  path.write_text(json.dumps({"config_version": 2, "rfcomm_cache": {"aa:bb:cc:dd:ee:01": 8, "X": 99, "Y": "3", "Z": True}}))
  config = identity_store.load_config(path)
  assert config["rfcomm_cache"] == {CAR: 8} and config["auto_connect"] is True
  assert identity_store.load_config(tmp_path / "missing.json")["rfcomm_cache"] is not identity_store.DEFAULT_CONFIG["rfcomm_cache"]
