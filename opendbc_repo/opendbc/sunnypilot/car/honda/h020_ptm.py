"""TEA-H020 rev-b PTM (modified EPS, comma in the firmware string) on the res architecture.

Same rule as the source branch's EPS_MODIFIED handling: the modified firmware string selects the tune. Only the exact
modified ID `39990-TEA,H020` (the rev-b image reports the same ID as every earlier PTM image) on a Civic Bosch gets the
linear 3840 map and the H020 PID base gains; every other vehicle and firmware (including the stock H020 image) keeps res's
existing behavior.
"""

import math
from pathlib import Path

EPS_ID = b"39990-TEA,H020"

# Driver-override settings for the H020, plain files in the params directory so they can be set over SSH
# (`echo -n 1800 > /data/params/d/HondaDriverOverrideThreshold`) without registering new Params keys, which would need a
# native rebuild of the prebuilt params binding. name: (default, minimum, maximum)
PARAMS_DIR = Path("/data/params/d")
SETTINGS = {
  "HondaDriverOverrideThreshold": (1800.0, 500.0, 5000.0),  # STEER_TORQUE_SENSOR units; res's stock Civic Bosch value is 1200
  "HondaOverrideFadeDownSecs": (0.0, 0.0, 10.0),            # 0: torque is cut the moment an override is detected
  "HondaOverrideFadeUpSecs": (0.5, 0.0, 10.0),              # authority returns over this long after the override ends
  "HondaOverrideHoldSecs": (0.5, 0.0, 2.0),                 # an override stays latched this long after its last above-threshold sample
  # tuning levers for the controller (read by LatControlHondaEps): 1.0 is the calibrated behavior
  "HondaEpsFeedforwardScale": (1.0, 0.0, 2.0),              # multiplies the firmware-inversion feedforward
  "HondaEpsPidScale": (1.0, 0.25, 3.0),                     # multiplies the residual angle PID's P and I
  # command delay: the curvature command is applied this much later (city below 10 m/s, highway above 15 m/s)
  "HondaEpsCmdDelayCity": (0.0, 0.0, 0.5),
  "HondaEpsCmdDelayHighway": (0.0, 0.0, 0.5),
}
CMD_DELAY_SPEED_BP = (10.0, 15.0)  # m/s
REFRESH_FRAMES = 100  # re-read the files about once a second at 100 Hz


def read_setting(name, params_dir=None):
  """The file's number clipped to the allowed range; the default when it is missing, empty or not a finite number."""
  default, lo, hi = SETTINGS[name]
  try:
    value = float((Path(params_dir or PARAMS_DIR) / name).read_text().strip())
  except (OSError, ValueError):
    return default
  return min(max(value, lo), hi) if math.isfinite(value) else default


class H020Settings:
  def __init__(self, params_dir=None):
    self.params_dir = params_dir
    self.frame = 0
    self.values = {}
    self.refresh()

  def refresh(self):
    self.values = {name: read_setting(name, self.params_dir) for name in SETTINGS}

  def tick(self):
    self.frame += 1
    if self.frame % REFRESH_FRAMES == 0:
      self.refresh()

  @property
  def override_threshold(self):
    return self.values["HondaDriverOverrideThreshold"]

  @property
  def fade_down_s(self):
    return self.values["HondaOverrideFadeDownSecs"]

  @property
  def fade_up_s(self):
    return self.values["HondaOverrideFadeUpSecs"]

  @property
  def hold_s(self):
    return self.values["HondaOverrideHoldSecs"]

  @property
  def cmd_delay_city(self):
    return self.values["HondaEpsCmdDelayCity"]

  @property
  def cmd_delay_highway(self):
    return self.values["HondaEpsCmdDelayHighway"]

  def command_delay(self, v_ego):
    """Seconds of command delay at this speed: the city value, ramping to the highway value between 10 and 15 m/s."""
    lo, hi = CMD_DELAY_SPEED_BP
    f = min(max((v_ego - lo) / (hi - lo), 0.0), 1.0)
    return self.cmd_delay_city + f * (self.cmd_delay_highway - self.cmd_delay_city)

  @property
  def feedforward_scale(self):
    return self.values["HondaEpsFeedforwardScale"]

  @property
  def pid_scale(self):
    return self.values["HondaEpsPidScale"]


def get_eps_modified_steering_pressed(raw_pressed, steering_torque, torque_cmd, filter_s, previous_pressed, dt=0.01):
  """The source branch's modified-EPS press detector: instant latch on opposing or near-zero-command driver torque,
  0.28 s on same-direction torque, instant release."""
  if not raw_pressed:
    return 0.0, False
  torque_product = float(steering_torque) * float(torque_cmd)
  torque_cmd_abs = abs(float(torque_cmd))
  if previous_pressed or torque_cmd_abs < 0.10 or torque_product < 0.0:
    return 1.0, True
  filter_s = min(1.0, filter_s + dt)
  return filter_s, filter_s >= 0.28


def override_ramp_step(ramp, pressed, fade_down_s, fade_up_s, dt=0.01):
  """One frame of the source's override ramp (torque scale 0): cut to 0 (or fade down), restore over fade_up_s."""
  if pressed:
    return 0.0 if fade_down_s <= 0.0 else max(0.0, ramp - dt / fade_down_s)
  return 1.0 if fade_up_s <= 0.0 else min(1.0, ramp + dt / fade_up_s)


def is_h020(car_fw):
  versions = {bytes(f.fwVersion).split(b"\0", 1)[0] for f in car_fw if f.ecu == "eps"}
  return versions == {EPS_ID}


def configure_h020(cp, candidate, car_fw):
  """Called after res's legacy modified-EPS tune."""
  if str(candidate) != "HONDA_CIVIC_BOSCH" or not is_h020(car_fw):
    return False
  cp.lateralTuning.init("pid")
  cp.lateralParams.torqueBP, cp.lateralParams.torqueV = [[0, 3840], [0, 3840]]
  # Civic Bosch/TGG four-point base schedule from ns-bosch-radar-testing 92428ab490.
  # Calibration p_scale/i_scale are applied by HondaEpsLateralCore as on the donor.
  mph = 0.44704
  bp = [0.0, 25.0 * mph - 1e-3, 25.0 * mph, 50.0 * mph]
  cp.lateralTuning.pid.kpBP, cp.lateralTuning.pid.kpV = [bp, [0.018, 0.024, 0.048, 0.060]]
  cp.lateralTuning.pid.kiBP, cp.lateralTuning.pid.kiV = [bp, [0.006, 0.008, 0.016, 0.020]]
  cp.lateralTuning.pid.kf = 0.0  # the firmware-inversion core supplies its own feedforward
  return True
