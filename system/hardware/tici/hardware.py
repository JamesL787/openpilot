import math
import os
import subprocess
import time
import tempfile
from enum import IntEnum
from functools import cached_property, lru_cache
from pathlib import Path

from cereal import log
from openpilot.common.util import sudo_read, sudo_write
from openpilot.common.gpio import gpio_set, gpio_init, get_irqs_for_action
from openpilot.system.hardware.base import HardwareBase, LPABase, ThermalConfig, ThermalZone
from openpilot.system.hardware.tici import iwlist
from openpilot.system.hardware.tici.esim import TiciLPA
from openpilot.system.hardware.tici.pins import GPIO
from openpilot.system.hardware.tici.amplifier import Amplifier

NM = 'org.freedesktop.NetworkManager'
NM_CON_ACT = NM + '.Connection.Active'
NM_DEV = NM + '.Device'
NM_DEV_WL = NM + '.Device.Wireless'
NM_DEV_STATS = NM + '.Device.Statistics'
NM_AP = NM + '.AccessPoint'
DBUS_PROPS = 'org.freedesktop.DBus.Properties'

MM = 'org.freedesktop.ModemManager1'
MM_MODEM = MM + ".Modem"
MM_MODEM_SIMPLE = MM + ".Modem.Simple"
MM_SIM = MM + ".Sim"

class MM_MODEM_STATE(IntEnum):
  FAILED        = -1
  UNKNOWN       = 0
  INITIALIZING  = 1
  LOCKED        = 2
  DISABLED      = 3
  DISABLING     = 4
  ENABLING      = 5
  ENABLED       = 6
  SEARCHING     = 7
  REGISTERED    = 8
  DISCONNECTING = 9
  CONNECTING    = 10
  CONNECTED     = 11

class NMMetered(IntEnum):
  NM_METERED_UNKNOWN = 0
  NM_METERED_YES = 1
  NM_METERED_NO = 2
  NM_METERED_GUESS_YES = 3
  NM_METERED_GUESS_NO = 4

TIMEOUT = 0.1

# comma 4 (EG916) pppd link check, see configure_ppp_keepalive
PPP_LCP_ECHO = {"lcp-echo-interval": "5", "lcp-echo-failure": "4"}
# comma 4 internet probe over ppp0, see check_modem_config. One ping per 30 s is ~10 KB/hour.
LTE_PROBE_TARGETS = ("94.140.14.14", "1.1.1.1")
LTE_PROBE_INTERVAL = 30  # s between probes while pppd is up
LTE_PROBE_FAILURES = 3  # consecutive failed probes before restarting the session (~90 s)
LTE_DOWN_RESTART = 60  # s without pppd (after it ran once) before bringing lte up again
LTE_RESTART_BACKOFF = 120  # s between restarts
REFRESH_RATE_MS = 1000

NetworkType = log.DeviceState.NetworkType
NetworkStrength = log.DeviceState.NetworkStrength

# https://developer.gnome.org/ModemManager/unstable/ModemManager-Flags-and-Enumerations.html#MMModemAccessTechnology
MM_MODEM_ACCESS_TECHNOLOGY_UMTS = 1 << 5
MM_MODEM_ACCESS_TECHNOLOGY_LTE = 1 << 14


def affine_irq(val, action):
  irqs = get_irqs_for_action(action)
  if len(irqs) == 0:
    print(f"No IRQs found for '{action}'")
    return

  for i in irqs:
    sudo_write(str(val), f"/proc/irq/{i}/smp_affinity_list")

@lru_cache
def get_device_type():
  # lru_cache and cache can cause memory leaks when used in classes
  with open("/sys/firmware/devicetree/base/model") as f:
    model = f.read().strip('\x00')
  return model.split('comma ')[-1]

class Tici(HardwareBase):
  @cached_property
  def bus(self):
    import dbus
    return dbus.SystemBus()

  @cached_property
  def nm(self):
    return self.bus.get_object(NM, '/org/freedesktop/NetworkManager')

  @property # this should not be cached, in case the modemmanager restarts
  def mm(self):
    return self.bus.get_object(MM, '/org/freedesktop/ModemManager1')

  @cached_property
  def amplifier(self):
    if self.get_device_type() == "mici":
      return None
    return Amplifier()

  def get_os_version(self):
    with open("/VERSION") as f:
      return f.read().strip()

  def get_device_type(self):
    return get_device_type()

  def reboot(self, reason=None):
    subprocess.check_output(["sudo", "reboot"])

  def uninstall(self):
    Path("/data/__system_reset__").touch()
    os.sync()
    self.reboot()

  def get_serial(self):
    return self.get_cmdline()['androidboot.serialno']

  def get_voltage(self):
    with open("/sys/class/hwmon/hwmon1/in1_input") as f:
      return int(f.read())

  def get_current(self):
    with open("/sys/class/hwmon/hwmon1/curr1_input") as f:
      return int(f.read())

  def set_ir_power(self, percent: int):
    if self.get_device_type() == "tizi":
      return

    value = int((percent / 100) * 300)
    with open("/sys/class/leds/led:switch_2/brightness", "w") as f:
      f.write("0\n")
    with open("/sys/class/leds/led:torch_2/brightness", "w") as f:
      f.write(f"{value}\n")
    with open("/sys/class/leds/led:switch_2/brightness", "w") as f:
      f.write(f"{value}\n")

  def get_network_type(self):
    try:
      primary_connection = self.nm.Get(NM, 'PrimaryConnection', dbus_interface=DBUS_PROPS, timeout=TIMEOUT)
      primary_connection = self.bus.get_object(NM, primary_connection)
      primary_type = primary_connection.Get(NM_CON_ACT, 'Type', dbus_interface=DBUS_PROPS, timeout=TIMEOUT)

      if primary_type == '802-3-ethernet':
        return NetworkType.ethernet
      elif primary_type == '802-11-wireless':
        return NetworkType.wifi
      else:
        active_connections = self.nm.Get(NM, 'ActiveConnections', dbus_interface=DBUS_PROPS, timeout=TIMEOUT)
        for conn in active_connections:
          c = self.bus.get_object(NM, conn)
          tp = c.Get(NM_CON_ACT, 'Type', dbus_interface=DBUS_PROPS, timeout=TIMEOUT)
          if tp == 'gsm':
            modem = self.get_modem()
            access_t = modem.Get(MM_MODEM, 'AccessTechnologies', dbus_interface=DBUS_PROPS, timeout=TIMEOUT)
            if access_t >= MM_MODEM_ACCESS_TECHNOLOGY_LTE:
              return NetworkType.cell4G
            elif access_t >= MM_MODEM_ACCESS_TECHNOLOGY_UMTS:
              return NetworkType.cell3G
            else:
              return NetworkType.cell2G
    except Exception:
      pass

    return NetworkType.none

  def get_modem(self):
    objects = self.mm.GetManagedObjects(dbus_interface="org.freedesktop.DBus.ObjectManager", timeout=TIMEOUT)
    modem_path = list(objects.keys())[0]
    return self.bus.get_object(MM, modem_path)

  def get_wlan(self):
    wlan_path = self.nm.GetDeviceByIpIface('wlan0', dbus_interface=NM, timeout=TIMEOUT)
    return self.bus.get_object(NM, wlan_path)

  def get_wwan(self):
    wwan_path = self.nm.GetDeviceByIpIface('wwan0', dbus_interface=NM, timeout=TIMEOUT)
    return self.bus.get_object(NM, wwan_path)

  def get_sim_info(self):
    modem = self.get_modem()
    sim_path = modem.Get(MM_MODEM, 'Sim', dbus_interface=DBUS_PROPS, timeout=TIMEOUT)

    if sim_path == "/":
      return {
        'sim_id': '',
        'mcc_mnc': None,
        'network_type': ["Unknown"],
        'sim_state': ["ABSENT"],
        'data_connected': False
      }
    else:
      sim = self.bus.get_object(MM, sim_path)
      return {
        'sim_id': str(sim.Get(MM_SIM, 'SimIdentifier', dbus_interface=DBUS_PROPS, timeout=TIMEOUT)),
        'mcc_mnc': str(sim.Get(MM_SIM, 'OperatorIdentifier', dbus_interface=DBUS_PROPS, timeout=TIMEOUT)),
        'network_type': ["Unknown"],
        'sim_state': ["READY"],
        'data_connected': modem.Get(MM_MODEM, 'State', dbus_interface=DBUS_PROPS, timeout=TIMEOUT) == MM_MODEM_STATE.CONNECTED,
      }

  def get_sim_lpa(self) -> LPABase:
    return TiciLPA()

  def get_imei(self, slot):
    if slot != 0:
      return ""

    return str(self.get_modem().Get(MM_MODEM, 'EquipmentIdentifier', dbus_interface=DBUS_PROPS, timeout=TIMEOUT))

  def get_network_info(self):
    if self.get_device_type() == "mici":
      return None
    try:
      modem = self.get_modem()
      info = modem.Command("AT+QNWINFO", math.ceil(TIMEOUT), dbus_interface=MM_MODEM, timeout=TIMEOUT)
      extra = modem.Command('AT+QENG="servingcell"', math.ceil(TIMEOUT), dbus_interface=MM_MODEM, timeout=TIMEOUT)
      state = modem.Get(MM_MODEM, 'State', dbus_interface=DBUS_PROPS, timeout=TIMEOUT)
    except Exception:
      return None

    if info and info.startswith('+QNWINFO: '):
      info = info.replace('+QNWINFO: ', '').replace('"', '').split(',')
      extra = "" if extra is None else extra.replace('+QENG: "servingcell",', '').replace('"', '')
      state = "" if state is None else MM_MODEM_STATE(state).name

      if len(info) != 4:
        return None

      technology, operator, band, channel = info

      return({
        'technology': technology,
        'operator': operator,
        'band': band,
        'channel': int(channel),
        'extra': extra,
        'state': state,
      })
    else:
      return None

  def parse_strength(self, percentage):
    if percentage < 25:
      return NetworkStrength.poor
    elif percentage < 50:
      return NetworkStrength.moderate
    elif percentage < 75:
      return NetworkStrength.good
    else:
      return NetworkStrength.great

  def get_network_strength(self, network_type):
    network_strength = NetworkStrength.unknown

    try:
      if network_type == NetworkType.none:
        pass
      elif network_type == NetworkType.wifi:
        wlan = self.get_wlan()
        active_ap_path = wlan.Get(NM_DEV_WL, 'ActiveAccessPoint', dbus_interface=DBUS_PROPS, timeout=TIMEOUT)
        if active_ap_path != "/":
          active_ap = self.bus.get_object(NM, active_ap_path)
          strength = int(active_ap.Get(NM_AP, 'Strength', dbus_interface=DBUS_PROPS, timeout=TIMEOUT))
          network_strength = self.parse_strength(strength)
      else:  # Cellular
        modem = self.get_modem()
        strength = int(modem.Get(MM_MODEM, 'SignalQuality', dbus_interface=DBUS_PROPS, timeout=TIMEOUT)[0])
        network_strength = self.parse_strength(strength)
    except Exception:
      pass

    return network_strength

  def get_network_metered(self, network_type) -> bool:
    try:
      primary_connection = self.nm.Get(NM, 'PrimaryConnection', dbus_interface=DBUS_PROPS, timeout=TIMEOUT)
      primary_connection = self.bus.get_object(NM, primary_connection)
      primary_devices = primary_connection.Get(NM_CON_ACT, 'Devices', dbus_interface=DBUS_PROPS, timeout=TIMEOUT)

      for dev in primary_devices:
        dev_obj = self.bus.get_object(NM, str(dev))
        metered_prop = dev_obj.Get(NM_DEV, 'Metered', dbus_interface=DBUS_PROPS, timeout=TIMEOUT)

        if network_type == NetworkType.wifi:
          if metered_prop in [NMMetered.NM_METERED_YES, NMMetered.NM_METERED_GUESS_YES]:
            return True
        elif network_type in [NetworkType.cell2G, NetworkType.cell3G, NetworkType.cell4G, NetworkType.cell5G]:
          if metered_prop == NMMetered.NM_METERED_NO:
            return False
    except Exception:
      pass

    return super().get_network_metered(network_type)

  def get_modem_version(self):
    try:
      modem = self.get_modem()
      return modem.Get(MM_MODEM, 'Revision', dbus_interface=DBUS_PROPS, timeout=TIMEOUT)
    except Exception:
      return None

  def get_modem_temperatures(self):
    timeout = 0.2  # Default timeout is too short
    try:
      modem = self.get_modem()
      temps = modem.Command("AT+QTEMP", math.ceil(timeout), dbus_interface=MM_MODEM, timeout=timeout)
      return list(filter(lambda t: t != 255, map(int, temps.split(' ')[1].split(','))))
    except Exception:
      return []


  def get_current_power_draw(self):
    return (self.read_param_file("/sys/class/hwmon/hwmon1/power1_input", int) / 1e6)

  def get_som_power_draw(self):
    return (self.read_param_file("/sys/class/power_supply/bms/voltage_now", int) * self.read_param_file("/sys/class/power_supply/bms/current_now", int) / 1e12)

  def shutdown(self):
    os.system("sudo poweroff")

  def get_thermal_config(self):
    intake, exhaust, gnss, bottomSoc = None, None, None, None
    if self.get_device_type() == "mici":
      gnss = ThermalZone("gnss")
      intake = ThermalZone("intake")
      exhaust = ThermalZone("exhaust")
      bottomSoc = ThermalZone("bottom_soc")
    return ThermalConfig(cpu=[ThermalZone(f"cpu{i}-silver-usr") for i in range(4)] +
                             [ThermalZone(f"cpu{i}-gold-usr") for i in range(4)],
                         gpu=[ThermalZone("gpu0-usr"), ThermalZone("gpu1-usr")],
                         dsp=ThermalZone("compute-hvx-usr"),
                         memory=ThermalZone("ddr-usr"),
                         pmic=[ThermalZone("pm8998_tz"), ThermalZone("pm8005_tz")],
                         intake=intake,
                         exhaust=exhaust,
                         gnss=gnss,
                         bottomSoc=bottomSoc)

  def set_display_power(self, on):
    try:
      with open("/sys/class/backlight/panel0-backlight/bl_power", "w") as f:
        f.write("0" if on else "4")
    except Exception:
      pass

  def set_screen_brightness(self, percentage):
    try:
      with open("/sys/class/backlight/panel0-backlight/max_brightness") as f:
        max_brightness = float(f.read().strip())

      val = int(percentage * (max_brightness / 100.))
      with open("/sys/class/backlight/panel0-backlight/brightness", "w") as f:
        f.write(str(val))
    except Exception:
      pass

  def get_screen_brightness(self):
    try:
      with open("/sys/class/backlight/panel0-backlight/max_brightness") as f:
        max_brightness = float(f.read().strip())

      with open("/sys/class/backlight/panel0-backlight/brightness") as f:
        return int(float(f.read()) / (max_brightness / 100.))
    except Exception:
      return 0

  def set_power_save(self, powersave_enabled):
    # amplifier, 100mW at idle
    if self.amplifier is not None:
      self.amplifier.set_global_shutdown(amp_disabled=powersave_enabled)
      if not powersave_enabled:
        self.amplifier.initialize_configuration(self.get_device_type())

    # *** CPU config ***

    # offline big cluster
    for i in range(4, 8):
      val = '0' if powersave_enabled else '1'
      sudo_write(val, f'/sys/devices/system/cpu/cpu{i}/online')

    for n in ('0', '4'):
      if powersave_enabled and n == '4':
        continue
      gov = 'ondemand' if powersave_enabled else 'performance'
      sudo_write(gov, f'/sys/devices/system/cpu/cpufreq/policy{n}/scaling_governor')
      if not powersave_enabled:
        # cap max core freq to 1689 Mhz
        sudo_write('1689600', f'/sys/devices/system/cpu/cpufreq/policy{n}/scaling_max_freq')

    # *** IRQ config ***

    # GPU, modeld core
    affine_irq(7, "kgsl-3d0")

    # camerad core
    camera_irqs = ("a5", "cci", "cpas_camnoc", "cpas-cdm", "csid", "ife", "csid-lite", "ife-lite")
    for n in camera_irqs:
      affine_irq(6, n)

  def get_gpu_usage_percent(self):
    try:
      with open('/sys/class/kgsl/kgsl-3d0/gpubusy') as f:
        used, total = f.read().strip().split()
      return 100.0 * int(used) / int(total)
    except Exception:
      return 0

  def initialize_hardware(self):
    if self.amplifier is not None:
      self.amplifier.initialize_configuration(self.get_device_type())

    # Allow hardwared to write engagement status to kmsg
    os.system("sudo chmod a+w /dev/kmsg")

    # Ensure fan gpio is enabled so fan runs until shutdown, also turned on at boot by the ABL
    gpio_init(GPIO.SOM_ST_IO, True)
    gpio_set(GPIO.SOM_ST_IO, 1)

    # *** IRQ config ***

    # mask off big cluster from default affinity
    sudo_write("f", "/proc/irq/default_smp_affinity")

    # move these off the default core
    affine_irq(1, "msm_vidc")  # encoders
    affine_irq(1, "i2c_geni")  # sensors

    # *** GPU config ***
    # https://github.com/commaai/agnos-kernel-sdm845/blob/master/arch/arm64/boot/dts/qcom/sdm845-gpu.dtsi#L216
    affine_irq(5, "fts_ts")    # touch
    affine_irq(5, "msm_drm")   # display
    sudo_write("1", "/sys/class/kgsl/kgsl-3d0/min_pwrlevel")
    sudo_write("1", "/sys/class/kgsl/kgsl-3d0/max_pwrlevel")
    sudo_write("1", "/sys/class/kgsl/kgsl-3d0/force_bus_on")
    sudo_write("1", "/sys/class/kgsl/kgsl-3d0/force_clk_on")
    sudo_write("1", "/sys/class/kgsl/kgsl-3d0/force_rail_on")
    sudo_write("1000", "/sys/class/kgsl/kgsl-3d0/idle_timer")
    sudo_write("performance", "/sys/class/kgsl/kgsl-3d0/devfreq/governor")
    sudo_write("710", "/sys/class/kgsl/kgsl-3d0/max_clock_mhz")

    # setup governors
    sudo_write("performance", "/sys/class/devfreq/soc:qcom,cpubw/governor")
    sudo_write("performance", "/sys/class/devfreq/soc:qcom,memlat-cpu0/governor")
    sudo_write("performance", "/sys/class/devfreq/soc:qcom,memlat-cpu4/governor")

    # *** VIDC (encoder) config ***
    sudo_write("N", "/sys/kernel/debug/msm_vidc/clock_scaling")
    sudo_write("Y", "/sys/kernel/debug/msm_vidc/disable_thermal_mitigation")

    # pandad core
    affine_irq(3, "spi_geni")         # SPI
    if "tici" in self.get_device_type():
      affine_irq(3, "xhci-hcd:usb3")  # aux panda USB (or potentially anything else on USB)
      affine_irq(3, "xhci-hcd:usb1")  # internal panda USB (also modem)
    try:
      pid = subprocess.check_output(["pgrep", "-f", "spi0"], encoding='utf8').strip()
      subprocess.call(["sudo", "chrt", "-f", "-p", "1", pid])
      subprocess.call(["sudo", "taskset", "-pc", "3", pid])
    except subprocess.CalledProcessException as e:
      print(str(e))

  def configure_modem(self):
    sim_id = self.get_sim_info().get('sim_id', '')

    modem = self.get_modem()
    try:
      manufacturer = str(modem.Get(MM_MODEM, 'Manufacturer', dbus_interface=DBUS_PROPS, timeout=TIMEOUT))
    except Exception:
      manufacturer = None

    cmds = []

    if self.get_device_type() in ("tici", "tizi"):
      # clear out old blue prime initial APN
      os.system('mmcli -m any --3gpp-set-initial-eps-bearer-settings="apn="')

      cmds += [
        # configure modem as data-centric
        'AT+QNVW=5280,0,"0102000000000000"',
        'AT+QNVFW="/nv/item_files/ims/IMS_enable",00',
        'AT+QNVFW="/nv/item_files/modem/mmode/ue_usage_setting",01',
      ]
      if self.get_device_type() == "tizi":
        # SIM hot swap, not routed on tici
        cmds += [
          'AT+QSIMDET=1,0',
          'AT+QSIMSTAT=1',
        ]
    elif manufacturer == 'Cavli Inc.':
      cmds += [
        'AT^SIMSWAP=1',     # use SIM slot, instead of internal eSIM
        'AT$QCSIMSLEEP=0',  # disable SIM sleep
        'AT$QCSIMCFG=SimPowerSave,0',  # more sleep disable

        # ethernet config
        'AT$QCPCFG=usbNet,0',
        'AT$QCNETDEVCTL=3,1',
      ]
    else:
      # this modem gets upset with too many AT commands
      if sim_id is None or len(sim_id) == 0:
        cmds += [
          # SIM sleep disable
          'AT$QCSIMSLEEP=0',
          'AT$QCSIMCFG=SimPowerSave,0',

          # ethernet config
          'AT$QCPCFG=usbNet,1',
        ]

    for cmd in cmds:
      try:
        modem.Command(cmd, math.ceil(TIMEOUT), dbus_interface=MM_MODEM, timeout=TIMEOUT)
      except Exception:
        pass

    # gated on device type, not the modem's Model: that D-Bus read uses the 0.1 s TIMEOUT and
    # came back empty on one boot of the owner's comma 4, which silently skipped this
    if self.get_device_type() == "mici":
      self.configure_ppp_keepalive()

    # eSIM prime
    dest = "/etc/NetworkManager/system-connections/esim.nmconnection"
    if LPABase.is_comma_profile(sim_id) and not os.path.exists(dest):
      with open(Path(__file__).parent/'esim.nmconnection') as f, tempfile.NamedTemporaryFile(mode='w') as tf:
        dat = f.read()
        dat = dat.replace("sim-id=", f"sim-id={sim_id}")
        tf.write(dat)
        tf.flush()

        # needs to be root
        os.system(f"sudo cp {tf.name} {dest}")
      os.system(f"sudo nmcli con load {dest}")

  def configure_ppp_keepalive(self):
    # The Quectel EG916 in the comma 4 carries data over PPP on its only AT port (ttyUSB3), so
    # ModemManager logs "connection monitoring is unsupported by the device" and cannot see a
    # data session die: the modem stays "connected", the signal bars stay cached, and there is
    # no internet until reboot. LCP echo lets pppd detect the dead link itself (4 missed echoes
    # at 5 s, ~20 s), and unlimited autoconnect retries let NetworkManager bring it back.
    # 10 s x 3 was the value checked on the device below; 5 s x 4 was chosen by the owner for
    # faster recovery (2026-09-25), not yet driven. More brief drops while driving (echoes lost in
    # handovers) would mean it is too tight: go back to 10 s x 3.
    # Checked on one device (T-Mobile, 2026-09-25): pppd ran with these values and the link held
    # with no LCP drops for >3 min. A carrier that ignores LCP echo would drop every ~30 s.
    #
    # The saved APN/roaming/metered settings are applied here too: the mici UI only pushes them
    # when its Settings screen is first opened, so after a plain boot the profile kept the
    # on-disk blank APN. Same mapping as WifiManager.update_gsm_settings.
    # The PPP session hands out no DNS servers on T-Mobile (resolvectl empty on ppp0, 2026-09-25),
    # which left the device and hotspot clients with a route but no name resolution. Static
    # servers are merged with any the carrier does send. AdGuard DNS (blocks ads and trackers)
    # at the owner's request.
    # Imported here: at module level these close a cycle through openpilot.system.hardware,
    # and common.params then silently falls back to non-persistent in-process params.
    from openpilot.common.params import Params
    from openpilot.common.swaglog import cloudlog
    params = Params()
    apn = params.get("GsmApn") or ""
    want = {
      "gsm.apn": apn,
      "gsm.auto-config": "yes" if apn == "" else "no",
      "gsm.home-only": "no" if params.get_bool("GsmRoaming") else "yes",
      "connection.metered": "unknown" if params.get_bool("GsmMetered") else "no",
      "connection.autoconnect-retries": "0",
      "ppp.lcp-echo-interval": PPP_LCP_ECHO["lcp-echo-interval"],
      "ppp.lcp-echo-failure": PPP_LCP_ECHO["lcp-echo-failure"],
      "ipv4.dns": "94.140.14.14,94.140.15.15",
    }
    try:
      out = subprocess.check_output(["nmcli", "-g", ",".join(want), "connection", "show", "lte"], encoding='utf8')
      current = dict(zip(want, out.split('\n'), strict=False))
    except (subprocess.CalledProcessError, OSError):
      current = {}
    # Saved to disk, not --temporary. The stock profile is AGNOS's read-only
    # /usr/lib/NetworkManager/system-connections/lte.nmconnection (blank APN, no LCP echo, no DNS),
    # and NM auto-activates it as soon as the modem enables, ~35 s into boot. A temporary change
    # lived in /run and was gone on every reboot, so each boot's first session ran on the stock
    # profile and had to be torn down and restarted (seen on the owner's comma 4, 2026-09-27).
    # Saved, AGNOS's NM stores it through netplan as /etc/netplan/90-NM-<uuid>.yaml (-> /data/etc,
    # persistent; checked on the device 2026-09-28), which replaces the /usr/lib copy at boot, so
    # from the next boot the first session already starts right.
    modify = [x for k, v in want.items() for x in (k, v)]
    subprocess.call(["sudo", "nmcli", "connection", "modify", "lte", *modify])

    # pppd and the bearer read these only when the session starts, so restart a running session
    # once if it came up with anything else. NM always passes the LCP options to pppd, as
    # "lcp-echo-interval 0" when off, so compare the values, not just their presence.
    running = self._running_ppp_lcp()
    if running is None:
      cloudlog.event("lte profile configured", apn=apn, running_lcp=None, restart=False)
      return  # no session yet; check_modem_config catches one that was already being set up
    session_keys = ("gsm.apn", "gsm.auto-config", "gsm.home-only", "ipv4.dns")
    restart = running != PPP_LCP_ECHO or any(current.get(k) != want[k] for k in session_keys)
    cloudlog.event("lte profile configured", apn=apn, running_lcp=running, restart=restart)
    if restart:
      subprocess.call(["sudo", "nmcli", "--wait", "0", "connection", "up", "lte"])

  def _running_ppp_lcp(self) -> dict[str, str] | None:
    try:
      pid = subprocess.check_output(["pgrep", "-x", "pppd"], encoding='utf8').split()[0]
      with open(f"/proc/{pid}/cmdline", "rb") as f:
        args = f.read().decode(errors='replace').split('\0')
    except (subprocess.CalledProcessError, IndexError, OSError):
      return None
    return {k: v for k, v in zip(args, args[1:], strict=False) if k in ("lcp-echo-interval", "lcp-echo-failure")}

  def check_modem_config(self):
    # Called every 10 s by hardwared on the comma 4.
    # 1. On one boot (2026-09-25) pppd still ran with "lcp-echo-interval 0" hours later: likely NM
    #    had already started the session with the old profile when configure_modem found no pppd
    #    yet. Re-apply whenever a running pppd lacks the echo (at most every 5 min).
    # 2. With echo on, the device still went offline and stayed offline (2026-09-26). The PPP peer
    #    is the modem, not the network, so LCP echo can keep passing after the data bearer behind
    #    it has died. So also probe the internet over ppp0 and restart the session when it fails
    #    LTE_PROBE_FAILURES times in a row, or when pppd has been gone for LTE_DOWN_RESTART s.
    if self.get_device_type() != "mici":
      return
    now = time.monotonic()
    running = self._running_ppp_lcp()
    if running is None:
      self._ppp_probe_failures = 0
      if getattr(self, "_ppp_seen", False):  # never seen: no SIM or no lte profile, leave it
        down_since = getattr(self, "_ppp_down_since", None) or now
        self._ppp_down_since = down_since
        if now - down_since >= LTE_DOWN_RESTART:
          self._restart_lte(now, "no pppd")
      return
    self._ppp_seen = True
    self._ppp_down_since = None

    if running != PPP_LCP_ECHO:
      if now - getattr(self, "_last_ppp_fix", -float("inf")) >= 300:
        self._last_ppp_fix = now
        self.configure_ppp_keepalive()
      return

    if now - getattr(self, "_last_ppp_probe", -float("inf")) < LTE_PROBE_INTERVAL:
      return
    self._last_ppp_probe = now
    if self._lte_reachable():
      self._ppp_probe_failures = 0
      return
    self._ppp_probe_failures = getattr(self, "_ppp_probe_failures", 0) + 1
    if self._ppp_probe_failures >= LTE_PROBE_FAILURES:
      self._restart_lte(now, "no internet over ppp0")

  def _lte_reachable(self) -> bool:
    for target in LTE_PROBE_TARGETS:
      try:
        cmd = ["sudo", "-n", "ping", "-I", "ppp0", "-c", "1", "-W", "3", target]
        if subprocess.call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5) == 0:
          return True
      except (subprocess.TimeoutExpired, OSError):
        pass
    return False

  def _restart_lte(self, now: float, reason: str):
    if now - getattr(self, "_last_lte_restart", -float("inf")) < LTE_RESTART_BACKOFF:
      return
    self._last_lte_restart = now
    self._ppp_probe_failures = 0
    self._ppp_down_since = None
    from openpilot.common.swaglog import cloudlog  # see configure_ppp_keepalive for why it's here
    cloudlog.event("lte restart", reason=reason)
    subprocess.call(["sudo", "nmcli", "--wait", "0", "connection", "up", "lte"])

  def reboot_modem(self):
    modem = self.get_modem()
    for state in (0, 1):
      try:
        modem.Command(f'AT+CFUN={state}', math.ceil(TIMEOUT), dbus_interface=MM_MODEM, timeout=TIMEOUT)
      except Exception:
        pass

  def get_networks(self):
    r = {}

    wlan = iwlist.scan()
    if wlan is not None:
      r['wlan'] = wlan

    lte_info = self.get_network_info()
    if lte_info is not None:
      extra = lte_info['extra']

      # <state>,"LTE",<is_tdd>,<mcc>,<mnc>,<cellid>,<pcid>,<earfcn>,<freq_band_ind>,
      # <ul_bandwidth>,<dl_bandwidth>,<tac>,<rsrp>,<rsrq>,<rssi>,<sinr>,<srxlev>
      if 'LTE' in extra:
        extra = extra.split(',')
        try:
          r['lte'] = [{
            "mcc": int(extra[3]),
            "mnc": int(extra[4]),
            "cid": int(extra[5], 16),
            "nmr": [{"pci": int(extra[6]), "earfcn": int(extra[7])}],
          }]
        except (ValueError, IndexError):
          pass

    return r

  def get_modem_data_usage(self):
    try:
      wwan = self.get_wwan()

      # Ensure refresh rate is set so values don't go stale
      refresh_rate = wwan.Get(NM_DEV_STATS, 'RefreshRateMs', dbus_interface=DBUS_PROPS, timeout=TIMEOUT)
      if refresh_rate != REFRESH_RATE_MS:
        u = type(refresh_rate)
        wwan.Set(NM_DEV_STATS, 'RefreshRateMs', u(REFRESH_RATE_MS), dbus_interface=DBUS_PROPS, timeout=TIMEOUT)

      tx = wwan.Get(NM_DEV_STATS, 'TxBytes', dbus_interface=DBUS_PROPS, timeout=TIMEOUT)
      rx = wwan.Get(NM_DEV_STATS, 'RxBytes', dbus_interface=DBUS_PROPS, timeout=TIMEOUT)
      return int(tx), int(rx)
    except Exception:
      return -1, -1

  def has_internal_panda(self):
    return True

  def reset_internal_panda(self):
    gpio_init(GPIO.STM_RST_N, True)
    gpio_init(GPIO.STM_BOOT0, True)

    gpio_set(GPIO.STM_RST_N, 1)
    gpio_set(GPIO.STM_BOOT0, 0)
    time.sleep(1)
    gpio_set(GPIO.STM_RST_N, 0)

  def recover_internal_panda(self):
    gpio_init(GPIO.STM_RST_N, True)
    gpio_init(GPIO.STM_BOOT0, True)

    gpio_set(GPIO.STM_RST_N, 1)
    gpio_set(GPIO.STM_BOOT0, 1)
    time.sleep(0.5)
    gpio_set(GPIO.STM_RST_N, 0)
    time.sleep(0.5)
    gpio_set(GPIO.STM_BOOT0, 0)

  def booted(self):
    # this normally boots within 8s, but on rare occasions takes 30+s
    encoder_state = sudo_read("/sys/kernel/debug/msm_vidc/core0/info")
    if "Core state: 0" in encoder_state and (time.monotonic() < 60*2):
      return False
    return True

if __name__ == "__main__":
  t = Tici()
  t.configure_modem()
  t.initialize_hardware()
  t.set_power_save(False)
  print(t.get_sim_info())
