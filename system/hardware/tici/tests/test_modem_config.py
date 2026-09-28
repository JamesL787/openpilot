import subprocess

import pytest

from openpilot.system.hardware.base import LPABase
from openpilot.system.hardware.tici.hardware import (LTE_DOWN_RESTART, LTE_PROBE_INTERVAL, LTE_RESTART_BACKOFF, PPP_LCP_ECHO, Tici)


def test_comma_profile_detection_without_lpa(mocker):
  hardware = Tici()
  modem = mocker.MagicMock()
  modem.Get.return_value = "Quectel"

  mocker.patch.object(hardware, "get_sim_info", return_value={"sim_id": "8985235000000000000"})
  mocker.patch.object(hardware, "get_modem", return_value=modem)
  mocker.patch.object(hardware, "get_device_type", return_value="mici")
  get_sim_lpa = mocker.patch.object(hardware, "get_sim_lpa")
  mocker.patch("openpilot.system.hardware.tici.hardware.os.path.exists", return_value=True)

  hardware.configure_modem()

  get_sim_lpa.assert_not_called()
  assert LPABase.is_comma_profile("8985235000000000000")
  assert not LPABase.is_comma_profile("8900000000000000000")


# on-disk profile at boot on a comma 4 (2026-09-25): blank APN, NM defaults
BOOT_PROFILE = "\nyes\nno\nunknown\n-1\n0\n0\n\n"
APPLIED_PROFILE = "fast.t-mobile.com\nno\nno\nunknown\n0\n5\n4\n94.140.14.14,94.140.15.15\n"
PPP_OFF = b"/usr/sbin/pppd\0nodetach\0ttyUSB3\0lcp-echo-failure\x000\0lcp-echo-interval\x000\0"
PPP_ON = b"/usr/sbin/pppd\0nodetach\0ttyUSB3\0lcp-echo-failure\x004\0lcp-echo-interval\x005\0"


def _eg916_hardware(mocker, tmp_path, model="EG916Q-GL", profile=BOOT_PROFILE, ppp_args=None, apn="fast.t-mobile.com", device="mici"):
  hardware = Tici()
  modem = mocker.MagicMock()
  modem.Get.side_effect = lambda iface, prop, **kw: model if prop == 'Model' else "Quectel"
  mocker.patch.object(hardware, "get_sim_info", return_value={"sim_id": ""})
  mocker.patch.object(hardware, "get_modem", return_value=modem)
  mocker.patch.object(hardware, "get_device_type", return_value=device)
  mocker.patch("openpilot.system.hardware.tici.hardware.os.system")

  params = mocker.MagicMock()
  params.get.side_effect = lambda k: apn if k == "GsmApn" else None
  params.get_bool.side_effect = lambda k: {"GsmRoaming": True, "GsmMetered": True}.get(k, False)
  mocker.patch("openpilot.common.params.Params", return_value=params)

  def check_output(cmd, **kw):
    if cmd[0] == "pgrep":
      if ppp_args is None:
        raise subprocess.CalledProcessError(1, cmd)
      return "4242\n"
    return profile
  mocker.patch("openpilot.system.hardware.tici.hardware.subprocess.check_output", side_effect=check_output)

  if ppp_args is not None:
    cmdline = tmp_path / "cmdline"
    cmdline.write_bytes(ppp_args)
    real_open = open
    mocker.patch("builtins.open", lambda p, *a, **k: real_open(cmdline, *a, **k) if p == "/proc/4242/cmdline" else real_open(p, *a, **k))
  return hardware


def _nmcli_calls(call):
  return [c.args[0] for c in call.call_args_list if "nmcli" in c.args[0]]


def _value(cmd, key):
  return cmd[cmd.index(key) + 1]


# NM passes the echo options even when they are off (seen on a comma 4, 2026-09-25)
@pytest.mark.parametrize("ppp_args", [PPP_OFF, b"/usr/sbin/pppd\0nodetach\0ttyUSB3\0"])
def test_eg916_restarts_session_without_echo(mocker, tmp_path, ppp_args):
  hardware = _eg916_hardware(mocker, tmp_path, profile=APPLIED_PROFILE, ppp_args=ppp_args)
  call = mocker.patch("openpilot.system.hardware.tici.hardware.subprocess.call")

  hardware.configure_modem()

  modify, up = _nmcli_calls(call)
  assert "--temporary" not in modify  # must survive a reboot, see configure_ppp_keepalive
  assert _value(modify, "connection.autoconnect-retries") == "0"
  assert _value(modify, "ppp.lcp-echo-interval") == "5"
  assert _value(modify, "ppp.lcp-echo-failure") == "4"
  assert up[-3:] == ["connection", "up", "lte"]


def test_eg916_applies_saved_apn_at_boot(mocker, tmp_path):
  # echo already right, but the session came up on the blank on-disk APN
  hardware = _eg916_hardware(mocker, tmp_path, profile=BOOT_PROFILE, ppp_args=PPP_ON)
  call = mocker.patch("openpilot.system.hardware.tici.hardware.subprocess.call")

  hardware.configure_modem()

  modify, up = _nmcli_calls(call)
  assert _value(modify, "gsm.apn") == "fast.t-mobile.com"
  assert _value(modify, "gsm.auto-config") == "no"
  assert _value(modify, "gsm.home-only") == "no"  # GsmRoaming on
  assert _value(modify, "connection.metered") == "unknown"  # GsmMetered on
  assert up[-3:] == ["connection", "up", "lte"]


def test_eg916_restarts_session_without_dns(mocker, tmp_path):
  # T-Mobile's PPP session gave no DNS servers: route up, no name resolution (2026-09-25)
  profile = APPLIED_PROFILE.replace("94.140.14.14,94.140.15.15", "")
  hardware = _eg916_hardware(mocker, tmp_path, profile=profile, ppp_args=PPP_ON)
  call = mocker.patch("openpilot.system.hardware.tici.hardware.subprocess.call")

  hardware.configure_modem()

  modify, up = _nmcli_calls(call)
  assert _value(modify, "ipv4.dns") == "94.140.14.14,94.140.15.15"
  assert up[-3:] == ["connection", "up", "lte"]


def test_eg916_blank_apn_uses_auto_config(mocker, tmp_path):
  hardware = _eg916_hardware(mocker, tmp_path, apn=None)
  call = mocker.patch("openpilot.system.hardware.tici.hardware.subprocess.call")

  hardware.configure_modem()

  modify, = _nmcli_calls(call)
  assert _value(modify, "gsm.apn") == ""
  assert _value(modify, "gsm.auto-config") == "yes"


def test_eg916_restarts_session_on_old_echo_values(mocker, tmp_path):
  # sessions started under the earlier 10 s x 3 setting get moved to the current one
  old = b"/usr/sbin/pppd\0nodetach\0ttyUSB3\0lcp-echo-failure\x003\0lcp-echo-interval\x0010\0"
  hardware = _eg916_hardware(mocker, tmp_path, profile=APPLIED_PROFILE, ppp_args=old)
  call = mocker.patch("openpilot.system.hardware.tici.hardware.subprocess.call")

  hardware.check_modem_config()

  assert _nmcli_calls(call)[-1][-3:] == ["connection", "up", "lte"]


def test_eg916_leaves_matching_session(mocker, tmp_path):
  hardware = _eg916_hardware(mocker, tmp_path, profile=APPLIED_PROFILE, ppp_args=PPP_ON)
  call = mocker.patch("openpilot.system.hardware.tici.hardware.subprocess.call")

  hardware.configure_modem()

  calls = _nmcli_calls(call)
  assert len(calls) == 1 and "modify" in calls[0]


def test_eg916_no_session_yet(mocker, tmp_path):
  hardware = _eg916_hardware(mocker, tmp_path, ppp_args=None)
  call = mocker.patch("openpilot.system.hardware.tici.hardware.subprocess.call")

  hardware.configure_modem()

  calls = _nmcli_calls(call)
  assert len(calls) == 1 and "modify" in calls[0]


def test_mici_configured_when_model_read_fails(mocker, tmp_path):
  # the Model D-Bus read can time out at boot; that skipped the whole setup on one boot
  hardware = _eg916_hardware(mocker, tmp_path, ppp_args=PPP_OFF)
  hardware.get_modem().Get.side_effect = lambda iface, prop, **kw: (_ for _ in ()).throw(Exception("timeout")) if prop == 'Model' else "Quectel"
  call = mocker.patch("openpilot.system.hardware.tici.hardware.subprocess.call")

  hardware.configure_modem()

  modify, up = _nmcli_calls(call)
  assert _value(modify, "ppp.lcp-echo-interval") == "5"
  assert up[-3:] == ["connection", "up", "lte"]


@pytest.mark.parametrize("device", ["tici", "tizi"])
def test_other_devices_untouched(mocker, tmp_path, device):
  hardware = _eg916_hardware(mocker, tmp_path, model="EG25-G", device=device)
  call = mocker.patch("openpilot.system.hardware.tici.hardware.subprocess.call")

  hardware.configure_modem()

  assert _nmcli_calls(call) == []


def test_watchdog_fixes_session_that_lost_echo(mocker, tmp_path):
  # seen on a comma 4 (2026-09-25): pppd with echo off hours after boot, link silently dead
  hardware = _eg916_hardware(mocker, tmp_path, profile=APPLIED_PROFILE, ppp_args=PPP_OFF)
  call = mocker.patch("openpilot.system.hardware.tici.hardware.subprocess.call")

  hardware.check_modem_config()
  modify, up = _nmcli_calls(call)
  assert _value(modify, "ppp.lcp-echo-interval") == "5"
  assert up[-3:] == ["connection", "up", "lte"]

  # rate limited: a carrier that rejects the echo must not cause a restart loop
  hardware.check_modem_config()
  assert len(_nmcli_calls(call)) == 2


@pytest.mark.parametrize("ppp_args", [PPP_ON, None])
def test_watchdog_leaves_good_or_absent_session(mocker, tmp_path, ppp_args):
  hardware = _eg916_hardware(mocker, tmp_path, profile=APPLIED_PROFILE, ppp_args=ppp_args)
  call = mocker.patch("openpilot.system.hardware.tici.hardware.subprocess.call")

  hardware.check_modem_config()

  assert _nmcli_calls(call) == []


def test_watchdog_other_devices(mocker, tmp_path):
  hardware = _eg916_hardware(mocker, tmp_path, ppp_args=PPP_OFF, device="tizi")
  call = mocker.patch("openpilot.system.hardware.tici.hardware.subprocess.call")

  hardware.check_modem_config()

  assert _nmcli_calls(call) == []


class _Clock:
  def __init__(self, mocker):
    self.t = 1000.0
    mocker.patch("openpilot.system.hardware.tici.hardware.time.monotonic", side_effect=lambda: self.t)


def _probe_hardware(mocker, reachable):
  hardware = Tici()
  mocker.patch.object(hardware, "get_device_type", return_value="mici")
  mocker.patch.object(hardware, "_running_ppp_lcp", return_value=dict(PPP_LCP_ECHO))
  mocker.patch.object(hardware, "_lte_reachable", side_effect=reachable)
  call = mocker.patch("openpilot.system.hardware.tici.hardware.subprocess.call")
  return hardware, call


def _ups(call):
  return [c for c in _nmcli_calls(call) if c[-3:] == ["connection", "up", "lte"]]


def test_probe_restarts_session_with_echo_on_but_no_internet(mocker):
  # 2026-09-26: offline and staying offline with echo on; the modem answers LCP itself
  clock = _Clock(mocker)
  hardware, call = _probe_hardware(mocker, lambda: False)
  for _ in range(2):
    hardware.check_modem_config()
    clock.t += 10
    hardware.check_modem_config()  # within the probe interval: no probe
    clock.t += LTE_PROBE_INTERVAL
  assert _ups(call) == []
  hardware.check_modem_config()  # third failed probe
  assert len(_ups(call)) == 1


def test_probe_leaves_working_session(mocker):
  clock = _Clock(mocker)
  hardware, call = _probe_hardware(mocker, lambda: True)
  for _ in range(10):
    hardware.check_modem_config()
    clock.t += LTE_PROBE_INTERVAL
  assert _ups(call) == []


def test_probe_restart_backoff(mocker):
  clock = _Clock(mocker)
  hardware, call = _probe_hardware(mocker, lambda: False)
  for _ in range(6):  # 6 failed probes in 150 s: one restart, the second is held by the backoff
    hardware.check_modem_config()
    clock.t += LTE_PROBE_INTERVAL
  assert len(_ups(call)) == 1
  clock.t += LTE_RESTART_BACKOFF
  for _ in range(3):
    hardware.check_modem_config()
    clock.t += LTE_PROBE_INTERVAL
  assert len(_ups(call)) == 2


def test_brings_lte_back_when_pppd_stays_gone(mocker):
  clock = _Clock(mocker)
  hardware, call = _probe_hardware(mocker, lambda: True)
  hardware.check_modem_config()  # pppd seen once
  hardware._running_ppp_lcp.return_value = None
  hardware.check_modem_config()
  clock.t += LTE_DOWN_RESTART - 10
  hardware.check_modem_config()
  assert _ups(call) == []
  clock.t += 10
  hardware.check_modem_config()
  assert len(_ups(call)) == 1


def test_no_restart_when_pppd_never_ran(mocker):
  # no SIM / no lte profile: nothing to bring back
  clock = _Clock(mocker)
  hardware, call = _probe_hardware(mocker, lambda: True)
  hardware._running_ppp_lcp.return_value = None
  for _ in range(10):
    hardware.check_modem_config()
    clock.t += LTE_DOWN_RESTART
  assert _ups(call) == []
