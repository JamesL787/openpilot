import json
import math
import os
import threading
from collections import deque
from queue import Empty, Queue

import numpy as np

from opendbc.can import CANPacker
from opendbc.car import ACCELERATION_DUE_TO_GRAVITY, Bus, DT_CTRL, create_gas_interceptor_command, rate_limit, make_tester_present_msg, structs
from opendbc.car.common.conversions import Conversions as CV
from opendbc.car.honda import hondacan
from opendbc.car.honda.values import (
  CAR,
  CruiseButtons,
  HONDA_BOSCH,
  HONDA_BOSCH_CANFD,
  HONDA_BOSCH_RADARLESS,
  HONDA_BOSCH_TJA_CONTROL,
  HONDA_NIDEC_ALT_PCM_ACCEL,
  CarControllerParams,
  HondaFlags,
)
from opendbc.car.interfaces import CarControllerBase
from openpilot.common.params import Params

VisualAlert = structs.CarControl.HUDControl.VisualAlert
LongCtrlState = structs.CarControl.Actuators.LongControlState


def get_eps_modified_steering_pressed(
  raw_pressed: bool, steering_torque: float, torque_cmd: float, filter_s: float, previous_pressed: bool
) -> tuple[float, bool]:
  if not raw_pressed:
    return 0.0, False

  torque_product = float(steering_torque) * float(torque_cmd)
  torque_cmd_abs = abs(float(torque_cmd))
  if previous_pressed or torque_cmd_abs < 0.10 or torque_product < 0.0:
    return 1.0, True

  filter_s = min(1.0, filter_s + DT_CTRL)
  return filter_s, filter_s >= 0.28


def torque_lpf_tau(v_ego: float, low_tau: float, standard_tau: float, highway_tau: float) -> float:
  if v_ego < 25.0 * CV.MPH_TO_MS:
    return low_tau
  if v_ego < 50.0 * CV.MPH_TO_MS:
    return standard_tau
  return highway_tau


def get_honda_bosch_wind_brake_mps2(v_ego: float) -> float:
  return float(np.interp(v_ego, [0.0, 13.4, 22.4, 31.3, 40.2], [0.000, 0.049, 0.136, 0.267, 0.441]))


def update_honda_bosch_live_learning(
  gas_factor: float,
  wind_factor: float,
  wind_factor_before_brake: float,
  desired_accel: float,
  actual_accel: float,
  gas_pedal_force: float,
  wind_brake_mps2: float,
  brake_pressed: bool,
  v_ego: float,
) -> tuple[float, float, float]:
  accel_error = desired_accel - actual_accel

  if accel_error != 0.0 and gas_pedal_force > 0.0:
    gas_factor = float(np.clip(gas_factor + accel_error / 50.0 * gas_pedal_force, 0.1, 3.0))

  if accel_error != 0.0 and not brake_pressed and v_ego > 0.0:
    wind_adjust = 1.0 + wind_brake_mps2 / 1000.0
    if accel_error > 0.0:
      wind_factor = float(np.clip(wind_factor * wind_adjust, 0.1, 3.0))
    else:
      wind_factor = float(np.clip(wind_factor / wind_adjust, 0.1, 3.0))

  if gas_pedal_force <= 0.0:
    wind_factor = max(wind_factor, wind_factor_before_brake)
  else:
    wind_factor_before_brake = wind_factor

  return gas_factor, wind_factor, wind_factor_before_brake


def compute_gb_honda_bosch(accel, speed):
  # TODO returns 0s, is unused
  return 0.0, 0.0


def compute_gb_honda_nidec(accel, speed):
  creep_brake = 0.0
  creep_speed = 2.3
  creep_brake_value = 0.15
  if speed < creep_speed:
    creep_brake = (creep_speed - speed) / creep_speed * creep_brake_value
  gb = float(accel) / 4.8 - creep_brake
  return np.clip(gb, 0.0, 1.0), np.clip(-gb, 0.0, 1.0)


def compute_gas_brake(accel, speed, fingerprint):
  if fingerprint in HONDA_BOSCH:
    return compute_gb_honda_bosch(accel, speed)
  else:
    return compute_gb_honda_nidec(accel, speed)


# TODO not clear this does anything useful
def actuator_hysteresis(brake, braking, brake_steady, v_ego, car_fingerprint):
  # hyst params
  brake_hyst_on = 0.02  # to activate brakes exceed this value
  brake_hyst_off = 0.005  # to deactivate brakes below this value
  brake_hyst_gap = 0.01  # don't change brake command for small oscillations within this value

  # *** hysteresis logic to avoid brake blinking. go above 0.1 to trigger
  if (brake < brake_hyst_on and not braking) or brake < brake_hyst_off:
    brake = 0.0
  braking = brake > 0.0

  # for small brake oscillations within brake_hyst_gap, don't change the brake command
  if brake == 0.0:
    brake_steady = 0.0
  elif brake > brake_steady + brake_hyst_gap:
    brake_steady = brake - brake_hyst_gap
  elif brake < brake_steady - brake_hyst_gap:
    brake_steady = brake + brake_hyst_gap
  brake = brake_steady

  return brake, braking, brake_steady


def brake_pump_hysteresis(apply_brake, apply_brake_last, last_pump_ts, ts):
  pump_on = False

  # reset pump timer if:
  # - there is an increment in brake request
  # - we are applying steady state brakes and we haven't been running the pump
  #   for more than 20s (to prevent pressure bleeding)
  if apply_brake > apply_brake_last or (ts - last_pump_ts > 20.0 and apply_brake > 0):
    last_pump_ts = ts

  # once the pump is on, run it for at least 0.2s
  if ts - last_pump_ts < 0.2 and apply_brake > 0:
    pump_on = True

  return pump_on, last_pump_ts


def process_hud_alert(hud_alert):
  alert_fcw = False
  alert_steer_required = False

  # Make sure FCW is prioritized over steering required
  # TODO: implement separate available LDW alert
  if hud_alert == VisualAlert.fcw:
    alert_fcw = True
  elif hud_alert in (VisualAlert.steerRequired, VisualAlert.ldw):
    alert_steer_required = True

  return alert_fcw, alert_steer_required



# Sidecar path for fingerprint + version metadata (does NOT touch params_keys.h)
LEARNER_META_PATH = "/data/honda_learner_meta.json"

# Bump when learner semantics change so persisted values are discarded
LEARN_VERSION = 2

# Learner tick cadence: update() runs every 2 controller frames at 100 Hz → 0.02 s per tick
_LEARNER_DT = 2 * DT_CTRL  # 0.02 s

# Lag alignment: typical longitudinalActuatorDelay ~0.5 s → 25 learner ticks
_LAG_TICKS = 25  # 25 * 0.02 s = 0.50 s

# Quasi-steady gate: reject samples where the command is actively changing
# |Δaccel_cmd| / dt must be < 0.3 m/s³ across the deque window
_ACCEL_RATE_THRESH = 0.3  # m/s³

# G4 soft relative clamps (relative to nominal 1.0)
_HARD_LO = 0.6
_HARD_HI = 1.6
_SOFT_LO = 0.8
_SOFT_HI = 1.25
_DECAY_RATE_PER_MIN = 0.01  # fraction/min decayed toward 1.0 while outside soft band
_DECAY_PER_TICK = _DECAY_RATE_PER_MIN / 60.0 * _LEARNER_DT

# Applied-factor first-order filter (rc ~7.5 s nominal)
_FACTOR_FILTER_RC = 7.5
_FACTOR_FILTER_ALPHA = _LEARNER_DT / (_FACTOR_FILTER_RC + _LEARNER_DT)

# Hill/saturation deadband
_PITCH_DEADBAND = 0.02   # rad
_BRAKE_ADDON_DEADBAND = 1.0  # m/s²


class LongGasLearner:
  """
  Lag-aligned gas/wind factor learner with torqued-grade safety rails (G1 + G4).

  Separation of concerns:
  - raw_gasfactor / raw_windfactor: the learned integrators (persisted)
  - gasfactor / windfactor: slow-filtered applied values (initialized from persisted; no startup transient)
  - All param reads/writes handled externally; this class is pure logic.

  Tick cadence:
    Called every 2 controller frames (frame % 2 == 0) at 100 Hz → DT = 0.02 s.
    Deque depth 25 → 25 × 0.02 s = 0.50 s lag alignment (matches longitudinalActuatorDelay).
  """

  def __init__(self, init_gasfactor: float, init_windfactor: float, car_fingerprint: str):
    # Clamp + NaN-guard on load
    init_gasfactor = self._safe_clamp(init_gasfactor)
    init_windfactor = self._safe_clamp(init_windfactor, lo=_HARD_LO, hi=_HARD_HI)

    # Learned integrators (raw, before filter)
    self.raw_gasfactor = init_gasfactor
    self.raw_windfactor = init_windfactor

    # Applied factors (FirstOrderFilter outputs)
    # Initialize at loaded value → no startup transient
    self.gasfactor = init_gasfactor
    self.windfactor = init_windfactor

    self.car_fingerprint = car_fingerprint

    # MVL telemetry: latest lag-aligned gas error (carcontroller mirrors this into
    # actuators.speed via temp_errorlogging, matching mvl-boston's debug channel).
    self.last_gas_error = 0.0

    # Deque of accel commands (length = _LAG_TICKS + 1 for rate check)
    self._accel_deque: deque = deque(maxlen=_LAG_TICKS + 1)

    # Anti-windup shadow sentinels (stores raw integrator value before maxgas/brake boundary)
    self.gasfactor_before_maxgas = init_gasfactor
    self.windfactor_before_maxgas = init_windfactor
    self.windfactor_before_brake = init_windfactor

    # Track engagement state for deque reset
    self._was_engaged = False

  @staticmethod
  def _safe_clamp(v: float, lo: float = _HARD_LO, hi: float = _HARD_HI) -> float:
    """NaN/inf guard + absolute hard clamp. Returns 1.0 on non-finite."""
    if not math.isfinite(v):
      return 1.0
    return float(np.clip(v, lo, hi))

  @staticmethod
  def _decay_toward_nominal(v: float) -> float:
    """Decay v toward 1.0 by one tick's worth if outside soft band."""
    if v < _SOFT_LO or v > _SOFT_HI:
      if v < 1.0:
        v = min(1.0, v + _DECAY_PER_TICK)
      else:
        v = max(1.0, v - _DECAY_PER_TICK)
    return v

  def reset_deque(self, accel_cmd: float):
    """Reset lag deque on engagement edge or gasPressed."""
    self._accel_deque.clear()
    # Pre-fill with current command so lagged ref is valid immediately
    for _ in range(_LAG_TICKS + 1):
      self._accel_deque.append(accel_cmd)

  def update(self,
             accel_cmd: float,
             a_ego: float,
             gas_pedal_force: float,
             wind_brake_ms2: float,
             long_active: bool,
             long_pid: bool,
             gas_pressed: bool,
             brake_pressed: bool,
             v_ego: float,
             at_standstill: bool,
             pitch: float,
             brake_addon: float,
             at_accel_max: bool):
    """
    One learner tick (called at the 2-frame cadence, NOT every frame).

    Returns: (gasfactor_applied, windfactor_applied)
    Always returns finite values — NaN cannot propagate.
    """
    engaged = long_active and long_pid

    # Engagement-edge or gasPressed reset
    if (not self._was_engaged and engaged) or gas_pressed:
      self.reset_deque(accel_cmd)
    self._was_engaged = engaged

    # Push current command into deque
    self._accel_deque.append(accel_cmd)

    # Only learn when conditions are right
    should_learn = (
      engaged
      and not gas_pressed
      and not brake_pressed
      and not at_standstill
    )

    if should_learn and len(self._accel_deque) == _LAG_TICKS + 1:
      # Lag-aligned reference: the command that was current ~0.5 s ago
      lagged_accel = self._accel_deque[0]

      # Quasi-steady gate: check that command has not been changing rapidly
      oldest = self._accel_deque[0]
      newest = self._accel_deque[-1]
      accel_rate = abs(newest - oldest) / (_LAG_TICKS * _LEARNER_DT)
      quasi_steady = accel_rate < _ACCEL_RATE_THRESH

      # Hill / saturation deadband (G4 rail 7)
      pitch_ok = abs(pitch) < _PITCH_DEADBAND
      brake_addon_ok = abs(brake_addon) < _BRAKE_ADDON_DEADBAND
      condition_ok = quasi_steady and pitch_ok and brake_addon_ok

      if condition_ok:
        gas_error = lagged_accel - a_ego
        self.last_gas_error = float(gas_error)

        # --- gasfactor update (gas_pedal_force > 0 gate) ---
        if gas_error != 0.0 and gas_pedal_force > 0.0:
          if self.car_fingerprint in ("HONDA_INSIGHT", "HONDA_CIVIC_BOSCH"):  # gas pedal reacts too slowly
            learn_speed = 150.0
          elif self.car_fingerprint in ("ACURA_RDX_3G", "ACURA_RDX_3G_MMR"):  # Prevent overreacting to turbo lag
            learn_speed = 300.0
          else:
            learn_speed = 50.0
          self.raw_gasfactor = np.clip(
            self.raw_gasfactor + gas_error / learn_speed * gas_pedal_force,
            _HARD_LO, _HARD_HI
          )

        # --- windfactor update ---
        if gas_error != 0.0 and v_ego > 0.0:
          if self.car_fingerprint in ("ACURA_RDX_3G", "ACURA_RDX_3G_MMR"):  # Faster reaction
            wind_learn_speed = 100.0
          else:
            wind_learn_speed = 1000.0
          wind_adjust = 1.0 + wind_brake_ms2 / wind_learn_speed
          self.raw_windfactor = np.clip(
            self.raw_windfactor * (wind_adjust if gas_error > 0.0 else 1.0 / wind_adjust),
            _HARD_LO, _HARD_HI
          )

    # Anti-windup shadows — operate on lagged command as well (G1 requirement)
    # Use gas_pedal_force (computed from lagged-or-current path) for saturation check
    if gas_pedal_force <= 0.0:
      # Braking: don't reduce windfactor, allow increases
      self.raw_windfactor = max(self.raw_windfactor, self.windfactor_before_brake)
    else:
      self.windfactor_before_brake = self.raw_windfactor

    if at_accel_max:
      # Saturation: don't increase gasfactor or windfactor
      self.raw_gasfactor = min(self.raw_gasfactor, self.gasfactor_before_maxgas)
      self.raw_windfactor = min(self.raw_windfactor, self.windfactor_before_maxgas)
      # G4 saturation-decay: slightly decay gasfactor when clipped at BOSCH_ACCEL_MAX
      self.raw_gasfactor = max(_HARD_LO, self.raw_gasfactor - _DECAY_PER_TICK)
    else:
      self.gasfactor_before_maxgas = self.raw_gasfactor
      self.windfactor_before_maxgas = self.raw_windfactor

    # G4 NaN/inf guard on raw integrators
    if not math.isfinite(self.raw_gasfactor):
      self.raw_gasfactor = 1.0
      self.gasfactor_before_maxgas = 1.0
    if not math.isfinite(self.raw_windfactor):
      self.raw_windfactor = 1.0
      self.windfactor_before_maxgas = 1.0
      self.windfactor_before_brake = 1.0

    # G4 decay-back toward nominal while outside soft band
    self.raw_gasfactor = self._decay_toward_nominal(self.raw_gasfactor)
    self.raw_windfactor = self._decay_toward_nominal(self.raw_windfactor)

    # Hard clamp (belt-and-suspenders)
    self.raw_gasfactor = float(np.clip(self.raw_gasfactor, _HARD_LO, _HARD_HI))
    self.raw_windfactor = float(np.clip(self.raw_windfactor, _HARD_LO, _HARD_HI))

    # G4 slow FirstOrderFilter between raw integrator and applied factor
    # Alpha = DT / (RC + DT), ~7.5 s time constant
    self.gasfactor = _FACTOR_FILTER_ALPHA * self.raw_gasfactor + (1.0 - _FACTOR_FILTER_ALPHA) * self.gasfactor
    self.windfactor = _FACTOR_FILTER_ALPHA * self.raw_windfactor + (1.0 - _FACTOR_FILTER_ALPHA) * self.windfactor

    # Final NaN guard on applied factors — safety absolute last resort
    if not math.isfinite(self.gasfactor):
      self.gasfactor = 1.0
    if not math.isfinite(self.windfactor):
      self.windfactor = 1.0

    return self.gasfactor, self.windfactor


def _load_learner_meta(car_fingerprint: str) -> tuple[float, float]:
  """
  Load persisted gasfactor/windfactor from Params, verifying fingerprint + LEARN_VERSION
  from the sidecar JSON. Returns (1.0, 1.0) on any mismatch or error.

  The sidecar JSON is written atomically (temp-then-rename) and carries:
    {"car_fingerprint": "...", "learn_version": 2}

  Note: does NOT touch params_keys.h (boot-brick trap on this fork).
  """
  try:
    params = Params()
    raw_gas = params.get("HondaGasFactorParams")
    raw_wind = params.get("HondaWindFactorParams")

    if raw_gas is None or raw_wind is None:
      return 1.0, 1.0

    # Read sidecar for fingerprint + version check
    try:
      with open(LEARNER_META_PATH, "r", encoding="utf-8") as f:
        meta = json.load(f)
      if meta.get("car_fingerprint") != car_fingerprint:
        return 1.0, 1.0
      if meta.get("learn_version") != LEARN_VERSION:
        return 1.0, 1.0
    except (OSError, json.JSONDecodeError, KeyError):
      # No sidecar or corrupt → treat as fresh (reset to nominal)
      return 1.0, 1.0

    # Parse param values
    if isinstance(raw_gas, bytes):
      raw_gas = raw_gas.decode("utf-8")
    if isinstance(raw_wind, bytes):
      raw_wind = raw_wind.decode("utf-8")

    gas = float(raw_gas)
    wind = float(raw_wind)

    if not math.isfinite(gas) or not math.isfinite(wind):
      return 1.0, 1.0

    gas = float(np.clip(gas, _HARD_LO, _HARD_HI))
    wind = float(np.clip(wind, _HARD_LO, _HARD_HI))
    return gas, wind

  except Exception:
    return 1.0, 1.0


def _write_learner_meta_atomic(car_fingerprint: str):
  """
  Atomically write sidecar JSON (temp-then-rename pattern from nrdr_long_tune.py).
  Only writes the metadata — actual factor values live in Params.
  No-ops silently on /data write failures (device may have read-only fs).
  """
  try:
    meta = {
      "car_fingerprint": car_fingerprint,
      "learn_version": LEARN_VERSION,
    }
    tmp = LEARNER_META_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
      json.dump(meta, f, indent=2, sort_keys=True)
      f.write("\n")
      f.flush()
      os.fsync(f.fileno())
    os.replace(tmp, LEARNER_META_PATH)
  except OSError:
    pass




class HondaParamWriter:
  def __init__(self):
    self._params = Params()
    self._queue = Queue()
    self._thread = threading.Thread(target=self._run, name="honda-param-writer", daemon=True)
    self._thread.start()

  def put_many(self, values):
    self._queue.put({key: float(value) for key, value in values.items()})

  def _run(self):
    while True:
      pending = self._queue.get()

      # Collapse queued snapshots so delayed writes keep only the newest value per key.
      try:
        while True:
          pending.update(self._queue.get_nowait())
      except Empty:
        pass

      for key, value in pending.items():
        self._params.put(key, value)


class CarController(CarControllerBase):
  def __init__(self, dbc_names, CP):
    super().__init__(dbc_names, CP)
    self.packer = CANPacker(dbc_names[Bus.pt])
    self.params = CarControllerParams(CP)
    self.param_store = Params()
    self.CAN = hondacan.CanBus(CP)
    self.tja_control = CP.carFingerprint in HONDA_BOSCH_TJA_CONTROL

    self.braking = False
    self.brake_steady = 0.0
    self.brake_last = 0.0
    self.apply_brake_last = 0
    self.last_pump_ts = 0.0
    self.stopping_counter = 0
    self.last_button_frame = 0

    self.accel = 0.0
    self.speed = 0.0
    self.gas = 0.0
    self.brake = 0.0
    self.last_torque = 0.0
    self.torque_lpf = 0.0
    self.override_ramp = 1.0
    self.lat_active_prev = False
    self.steering_pressed_filter_s = 0.0
    self.steering_pressed_robust_prev = False
    self.bosch_last_gas = 0.0
    if self.CP.carFingerprint in HONDA_BOSCH:
      self.bosch_gas_factor = self.param_store.get_float("HondaGasFactorParams", default=1.0)
      self.bosch_wind_factor = self.param_store.get_float("HondaWindFactorParams", default=1.0)
    else:
      # NRDR keeps Nidec gas-interceptor gains static; Bosch live learning stays above.
      self.bosch_gas_factor = 1.0
      self.bosch_wind_factor = 1.0
    self.bosch_wind_factor_before_brake = self.bosch_wind_factor
    self.bosch_gas_factor_before_gasmax = self.bosch_gas_factor
    self.bosch_wind_factor_before_gasmax = self.bosch_wind_factor

    # nrdr-nightly Bosch long learner. Drives the HONDA_BOSCH gas path below; the Nidec
    # gas-interceptor path keeps the simpler bosch_*_factor fields above. Nightly's BrakeMemory is
    # deliberately NOT ported: nothing in nightly ever calls its update() and the brake PID that
    # would feed it is disabled, so it is dead code there.
    self.param_writer = HondaParamWriter()
    init_gas, init_wind = _load_learner_meta(CP.carFingerprint)
    self._learner = LongGasLearner(init_gas, init_wind, CP.carFingerprint)
    self.last_accel_cmd = 0.0
    self.last_accel_sign = 0
    self.sign_change_counter = 0
    self.pitch = 0.0

  def _filtered_steering_pressed(self, CS, torque_cmd: float) -> bool:
    # Every modified-EPS Honda -- Clarity, Civic and Civic Bosch -- shares this detector:
    # instant latch on opposing or near-zero-command driver torque, 0.28 s on same-direction
    # torque, instant release. Civic Bosch previously had a graded variant of its own with a
    # 1.60 s same-direction trip and a decaying release; it was removed rather than left
    # unrouted, so there is no second override path to fall out of sync.
    self.steering_pressed_filter_s, steering_pressed = get_eps_modified_steering_pressed(
      bool(CS.out.steeringPressed),
      float(getattr(CS.out, "steeringTorque", 0.0)),
      float(torque_cmd),
      self.steering_pressed_filter_s,
      self.steering_pressed_robust_prev,
    )
    self.steering_pressed_robust_prev = steering_pressed
    return steering_pressed

  def _get_live_tuning_params(self):
    return {
      "override_fade_down_s": float(np.clip(self.param_store.get_float("HondaOverrideFadeDownSecs", default=0.0), 0.0, 10.0)),
      "override_fade_up_s": float(np.clip(self.param_store.get_float("HondaOverrideFadeUpSecs", default=1.5), 0.0, 10.0)),
      "override_torque_scale": float(np.clip(self.param_store.get_int("HondaOverrideTorqueScale", default=0), 0, 100)) / 100.0,
      "driver_assist_during_override": self.param_store.get_bool("HondaDriverAssistDuringOverride", default=False),
      "torque_lpf_enabled": self.param_store.get_bool("HondaTorqueLowPassFilter", default=True),
      "lpf_tau_low": float(np.clip(self.param_store.get_float("HondaLpfTauLowSpeed", default=0.1), 0.0, 5.0)),
      "lpf_tau_standard": float(np.clip(self.param_store.get_float("HondaLpfTauStandard", default=0.1), 0.0, 5.0)),
      "lpf_tau_highway": float(np.clip(self.param_store.get_float("HondaLpfTauHighway", default=0.1), 0.0, 5.0)),
      "steer_delta_limiter_enabled": self.param_store.get_bool("HondaSteerDeltaLimiter", default=False),
      "steer_delta_up": float(np.clip(self.param_store.get_float("HondaSteerDeltaUp", default=3.0), 0.0, 100.0)),
      "steer_delta_down": float(np.clip(self.param_store.get_float("HondaSteerDeltaDown", default=3.0), 0.0, 100.0)),
      "live_learning_gas": self.param_store.get_bool("HondaLiveLearningGas", default=self.CP.carFingerprint in HONDA_BOSCH),
      "stopping_decel_rate": float(np.clip(self.param_store.get_int("HondaStoppingDecelRate", default=30), 0, 100)) / 100.0,
      "ecu_matched_long": self.param_store.get_bool("NrdrHondaEcuMatchedLong", default=False),
      "increase_override_tolerance": self.param_store.get_bool("NrdrIncreaseOverrideTolerance", default=False),
      "min_steer_speed": float(np.clip(self.param_store.get_int("NrdrMinSteerSpeed", default=1), 0, 45)) * CV.MPH_TO_MS,
    }

  def _update_steering_torque(self, CC, CS, live):
    torque_cmd = float(CC.actuators.torque) if CC.latActive else 0.0
    steering_pressed = False
    below_min_steer_speed = CS.out.vEgo < live["min_steer_speed"]

    if below_min_steer_speed:
      torque_cmd = 0.0
    raw_torque_cmd = torque_cmd

    if CC.latActive:
      # Clarity's behaviour, now shared by every modified-EPS Honda: the command path uses raw
      # steeringPressed and only debounces when NrdrIncreaseOverrideTolerance is explicitly on.
      # Civic Bosch used to force the filter on here regardless; that exception is gone.
      if live["increase_override_tolerance"]:
        steering_pressed = self._filtered_steering_pressed(CS, torque_cmd)
      else:
        steering_pressed = bool(CS.out.steeringPressed)

      if not self.lat_active_prev:
        self.override_ramp = 0.0

      if steering_pressed:
        fade_down_s = live["override_fade_down_s"]
        if fade_down_s <= 0.0:
          self.override_ramp = live["override_torque_scale"]
        else:
          self.override_ramp = max(live["override_torque_scale"], self.override_ramp - DT_CTRL / fade_down_s)
      else:
        fade_up_s = live["override_fade_up_s"]
        self.override_ramp = 1.0 if fade_up_s <= 0.0 else min(1.0, self.override_ramp + DT_CTRL / fade_up_s)

      torque_cmd *= self.override_ramp

      # One LPF for every modified-EPS Honda: the NRDR speed-banded tau, live-tuned through
      # HondaLpfTau{LowSpeed,Standard,Highway}. Civic Bosch used to fall back to a hardcoded
      # curve of its own when this toggle was off, which meant "disable the low-pass filter"
      # silently selected a different low-pass filter on that car. Off now means off.
      if live["torque_lpf_enabled"]:
        tau = torque_lpf_tau(CS.out.vEgo, live["lpf_tau_low"], live["lpf_tau_standard"], live["lpf_tau_highway"])
        alpha = DT_CTRL / (tau + DT_CTRL)
        self.torque_lpf = alpha * torque_cmd + (1.0 - alpha) * self.torque_lpf
        torque_cmd = self.torque_lpf
      else:
        self.torque_lpf = torque_cmd

    else:
      self.override_ramp = 0.0
      self.torque_lpf = 0.0
      self.steering_pressed_filter_s = 0.0
      self.steering_pressed_robust_prev = False

    if live["steer_delta_limiter_enabled"]:
      limited_torque = rate_limit(torque_cmd, self.last_torque, -live["steer_delta_down"] * DT_CTRL, live["steer_delta_up"] * DT_CTRL)
    else:
      limited_torque = torque_cmd

    self.last_torque = limited_torque
    self.lat_active_prev = CC.latActive

    lkas_active = CC.latActive and (live["driver_assist_during_override"] or not steering_pressed) and not below_min_steer_speed
    return limited_torque, lkas_active, steering_pressed

  def update(self, CC, CS, now_nanos, starpilot_toggles):
    live = self._get_live_tuning_params()
    actuators = CC.actuators
    hud_control = CC.hudControl
    hud_v_cruise = hud_control.setSpeed / CS.v_cruise_factor if hud_control.speedVisible else 255
    pcm_cancel_cmd = CC.cruiseControl.cancel
    gas_interceptor_command = 0.0
    if len(CC.orientationNED) == 3:
      self.pitch = CC.orientationNED[1]
    hill_brake = math.sin(self.pitch) * ACCELERATION_DUE_TO_GRAVITY

    if CC.longActive:
      accel = actuators.accel
      # Nidec only, and not with a pedal interceptor: the interceptor bypasses the stock PCM
      # accel path entirely (pcm_accel is forced to 0) and rebuilds its own command from gas
      # and brake with its own gas_mult, gas factor and wind compensation. Shaping those to
      # the factory ECU's ramp rates would be matching an ECU that is no longer in the loop.
      ecu_matched = (live["ecu_matched_long"] and self.CP.carFingerprint not in HONDA_BOSCH
                     and not self.CP.enableGasInterceptorDEPRECATED)
      accel_cmd = float(actuators.accel)
      if ecu_matched:
        accel_cmd = float(np.clip(accel_cmd, self.last_accel_cmd - 0.06, self.last_accel_cmd + 0.05))
      self.last_accel_cmd = accel_cmd
      gas, brake = compute_gas_brake(accel_cmd + hill_brake, CS.out.vEgo, self.CP.carFingerprint)

      if ecu_matched:
        coast_db = float(np.interp(CS.out.vEgo, [2.5, 10.0, 20.0, 30.0], [0.08, 0.06, 0.03, 0.005]))
        if gas < coast_db and brake < coast_db:
          gas, brake = 0.0, 0.0

        accel_sign = 1 if accel_cmd > 0.05 else (-1 if accel_cmd < -0.05 else 0)
        if accel_sign != 0 and accel_sign != self.last_accel_sign and self.last_accel_sign != 0:
          self.sign_change_counter = 20
        if self.sign_change_counter > 0:
          gas, brake = 0.0, 0.0
          self.sign_change_counter -= 1
        if accel_sign != 0:
          self.last_accel_sign = accel_sign
    else:
      accel = 0.0
      gas, brake = 0.0, 0.0
      self.last_accel_cmd = 0.0
      self.last_accel_sign = 0
      self.sign_change_counter = 0

    # *** rate limit / filter steer ***
    limited_torque, lkas_active, filtered_steering_pressed = self._update_steering_torque(CC, CS, live)

    # *** apply brake hysteresis ***
    pre_limit_brake, self.braking, self.brake_steady = actuator_hysteresis(brake, self.braking, self.brake_steady, CS.out.vEgo, self.CP.carFingerprint)

    # *** rate limit after the enable check ***
    _brake_rate_up = live["stopping_decel_rate"] if actuators.longControlState == LongCtrlState.stopping else 3.0
    self.brake_last = rate_limit(pre_limit_brake, self.brake_last, -2.0, _brake_rate_up * DT_CTRL)

    # vehicle hud display, wait for one update from 10Hz 0x304 msg
    alert_fcw, alert_steer_required = process_hud_alert(hud_control.visualAlert)

    # **** process the car messages ****

    # steer torque is converted back to CAN reference (positive when steering right)
    apply_torque = int(np.interp(-limited_torque * self.params.STEER_MAX, self.params.STEER_LOOKUP_BP, self.params.STEER_LOOKUP_V))

    # Send CAN commands
    can_sends = []

    # tester present - w/ no response (keeps radar disabled)
    if self.CP.carFingerprint in (HONDA_BOSCH - HONDA_BOSCH_RADARLESS) and self.CP.openpilotLongitudinalControl:
      if self.frame % 10 == 0:
        can_sends.append(make_tester_present_msg(0x18DAB0F1, self.CAN.pt, suppress_response=True))

    # Send steering command.
    can_sends.append(hondacan.create_steering_control(self.packer, self.CAN, apply_torque, lkas_active, self.tja_control))

    # wind brake from air resistance decel at high speed
    wind_brake = float(np.interp(CS.out.vEgo, [0.0, 2.3, 35.0], [0.001, 0.002, 0.15]))
    wind_brake_mps2 = get_honda_bosch_wind_brake_mps2(CS.out.vEgo)
    # all of this is only relevant for HONDA NIDEC
    max_accel = np.interp(CS.out.vEgo, self.params.NIDEC_MAX_ACCEL_BP, self.params.NIDEC_MAX_ACCEL_V)
    # TODO this 1.44 is just to maintain previous behavior
    pcm_speed_BP = [-wind_brake, -wind_brake * (3 / 4), 0.0, 0.5]
    # The Honda ODYSSEY seems to have different PCM_ACCEL
    # msgs, is it other cars too?
    if self.CP.enableGasInterceptorDEPRECATED or not CC.longActive:
      pcm_speed = 0.0
      pcm_accel = int(0.0)
    elif self.CP.carFingerprint in HONDA_NIDEC_ALT_PCM_ACCEL:
      pcm_speed_V = [0.0, np.clip(CS.out.vEgo - 3.0, 0.0, 100.0), np.clip(CS.out.vEgo + 0.0, 0.0, 100.0), np.clip(CS.out.vEgo + 5.0, 0.0, 100.0)]
      pcm_speed = float(np.interp(gas - brake, pcm_speed_BP, pcm_speed_V))
      pcm_accel = int(1.0 * self.params.NIDEC_GAS_MAX)
    else:
      pcm_speed_V = [0.0, np.clip(CS.out.vEgo - 2.0, 0.0, 100.0), np.clip(CS.out.vEgo + 2.0, 0.0, 100.0), np.clip(CS.out.vEgo + 5.0, 0.0, 100.0)]
      pcm_speed = float(np.interp(gas - brake, pcm_speed_BP, pcm_speed_V))
      pcm_accel = int(np.clip((accel / 1.44) / max_accel, 0.0, 1.0) * self.params.NIDEC_GAS_MAX)

    if not self.CP.openpilotLongitudinalControl:
      if self.frame % 2 == 0 and self.CP.carFingerprint not in HONDA_BOSCH_RADARLESS | HONDA_BOSCH_CANFD:
        can_sends.append(hondacan.create_bosch_supplemental_1(self.packer, self.CAN))
      # If using stock ACC, spam cancel command to kill gas when OP disengages.
      if pcm_cancel_cmd:
        can_sends.append(hondacan.spam_buttons_command(self.packer, self.CAN, CruiseButtons.CANCEL, self.CP.carFingerprint))
      elif CC.cruiseControl.resume:
        can_sends.append(hondacan.spam_buttons_command(self.packer, self.CAN, CruiseButtons.RES_ACCEL, self.CP.carFingerprint))
      else:
        # Redneck cruise: stock ACC keeps the radar and does the actual following,
        # openpilot only walks its set speed with button presses. card.py decides
        # the direction; 0 means hold. Rate limited to 20 Hz like the stock stalk.
        redneck_button = {
          1: CruiseButtons.RES_ACCEL,
          2: CruiseButtons.DECEL_SET,
        }.get(getattr(CS, "redneck_send_button", 0))
        if redneck_button is not None and (self.frame - self.last_button_frame) * DT_CTRL > 0.05:
          can_sends.append(hondacan.spam_buttons_command(self.packer, self.CAN, redneck_button, self.CP.carFingerprint))
          self.last_button_frame = self.frame

    else:
      # Send gas and brake commands.
      if self.frame % 2 == 0:
        ts = self.frame * DT_CTRL

        if self.CP.carFingerprint in HONDA_BOSCH:
          # nrdr-nightly Bosch gas path. The extra-brake PID is disabled there, so brake_addon is
          # a constant 0.0 and only feeds the learner's gating deadband.
          brake_addon = 0.0
          self.accel = float(np.clip(accel, self.params.BOSCH_ACCEL_MIN, self.params.BOSCH_ACCEL_MAX))
          gas_pedal_force = accel + wind_brake_mps2 * self._learner.windfactor + hill_brake

          if live["live_learning_gas"]:
            self._learner.update(
              accel_cmd=accel,
              a_ego=CS.out.aEgo,
              gas_pedal_force=gas_pedal_force,
              wind_brake_ms2=wind_brake_mps2,
              long_active=CC.longActive,
              long_pid=(actuators.longControlState == LongCtrlState.pid),
              gas_pressed=CS.out.gasPressed,
              brake_pressed=CS.out.brakePressed,
              v_ego=CS.out.vEgo,
              at_standstill=(CS.out.vEgo <= 0.0),
              pitch=self.pitch,
              brake_addon=float(brake_addon),
              at_accel_max=(gas_pedal_force >= self.params.BOSCH_ACCEL_MAX),
            )

          # Anchor the learned gain at min_gas so gasfactor scales the offset from the pedal-on
          # threshold rather than shifting where gas starts.
          min_gas = self.params.BOSCH_GAS_LOOKUP_BP[0]
          self.gas = float(np.interp((gas_pedal_force - min_gas) * self._learner.gasfactor + min_gas,
                                     self.params.BOSCH_GAS_LOOKUP_BP, self.params.BOSCH_GAS_LOOKUP_V))
          # limit gas ramp to 60 units per frame, matches stock. Higher sometimes causes powertrain
          # to ignore gas command.
          self.gas = min(self.gas, max(60.0, self.bosch_last_gas + 60.0))
          self.bosch_last_gas = self.gas

          stopping = actuators.longControlState == LongCtrlState.stopping
          self.stopping_counter = self.stopping_counter + 1 if stopping else 0
          can_sends.extend(
            hondacan.create_acc_commands(self.packer, self.CAN, CC.enabled, CC.longActive, self.accel, self.gas, self.stopping_counter, self.CP.carFingerprint, gas_pedal_force)
          )
        else:
          apply_brake = np.clip(self.brake_last - wind_brake, 0.0, 1.0)
          apply_brake = int(np.clip(apply_brake * self.params.NIDEC_BRAKE_MAX, 0, self.params.NIDEC_BRAKE_MAX - 1))
          pump_on, self.last_pump_ts = brake_pump_hysteresis(apply_brake, self.apply_brake_last, self.last_pump_ts, ts)

          pcm_override = True
          can_sends.append(
            hondacan.create_brake_command(
              self.packer, self.CAN, apply_brake, pump_on, pcm_override, pcm_cancel_cmd, alert_fcw, self.CP.carFingerprint, CS.stock_brake, self.CP.flags
            )
          )
          self.apply_brake_last = apply_brake
          self.brake = apply_brake / self.params.NIDEC_BRAKE_MAX

          if live["live_learning_gas"] and self.CP.enableGasInterceptorDEPRECATED:
            self.bosch_gas_factor, self.bosch_wind_factor, self.bosch_wind_factor_before_brake = update_honda_bosch_live_learning(
              self.bosch_gas_factor,
              self.bosch_wind_factor,
              self.bosch_wind_factor_before_brake,
              actuators.accel,
              CS.out.aEgo,
              gas,
              wind_brake * 4.8,
              CS.out.brakePressed,
              CS.out.vEgo,
            )

          if self.CP.enableGasInterceptorDEPRECATED:
            gas_mult = float(np.interp(CS.out.vEgo, [0.0, 10.0], [0.4, 1.0]))
            if CC.longActive:
              gas_interceptor_command = float(np.clip(
                gas_mult * ((gas * self.bosch_gas_factor) - brake + (wind_brake * self.bosch_wind_factor * 3.0 / 4.0)),
                0.0,
                1.0,
              ))
            idx = (self.frame // 2) % 0x10
            can_sends.append(create_gas_interceptor_command(self.packer, gas_interceptor_command, idx))

    # Send dashboard UI commands.
    if self.frame % 10 == 0:
      if self.CP.openpilotLongitudinalControl:
        # On Nidec, this also controls longitudinal positive acceleration
        can_sends.append(
          hondacan.create_acc_hud(self.packer, self.CAN.pt, self.CP, CC.enabled, pcm_speed, pcm_accel, hud_control, hud_v_cruise, CS.is_metric, CS.acc_hud)
        )

      steering_available = CS.out.cruiseState.available and CS.out.vEgo > max(self.params.STEER_GLOBAL_MIN_SPEED, self.CP.minSteerSpeed)
      reduced_steering = CS.out.steeringPressed
      can_sends.extend(
        hondacan.create_lkas_hud(
          self.packer, self.CAN.lkas, self.CP, hud_control, CC.latActive, steering_available, reduced_steering, alert_steer_required, CS.lkas_hud
        )
      )

      if self.CP.openpilotLongitudinalControl:
        # TODO: combining with create_acc_hud block above will change message order and will need replay logs regenerated
        if self.CP.carFingerprint in (HONDA_BOSCH - HONDA_BOSCH_RADARLESS):
          can_sends.append(hondacan.create_radar_hud(self.packer, self.CAN.pt))
        if self.CP.carFingerprint == CAR.HONDA_CIVIC_BOSCH:
          can_sends.append(hondacan.create_legacy_brake_command(self.packer, self.CAN.pt))
        if self.CP.carFingerprint not in HONDA_BOSCH:
          self.speed = pcm_speed
          if self.CP.enableGasInterceptorDEPRECATED:
            self.gas = gas_interceptor_command
          else:
            self.gas = pcm_accel / self.params.NIDEC_GAS_MAX

    if self.frame > 0 and self.frame % 6000 == 0:
      if self.CP.carFingerprint in HONDA_BOSCH:
        # Persist the raw integrators (not the filtered applied values) so the next boot
        # resumes from the actual learned position, plus the fingerprint/version sidecar.
        self.param_writer.put_many({
          "HondaGasFactorParams": self._learner.raw_gasfactor,
          "HondaWindFactorParams": self._learner.raw_windfactor,
        })
        _write_learner_meta_atomic(self.CP.carFingerprint)
      else:
        # Nidec gas-interceptor path keeps its own simple factors.
        self.param_store.put_float("HondaGasFactorParams", self.bosch_gas_factor)
        self.param_store.put_float("HondaWindFactorParams", self.bosch_wind_factor)

    new_actuators = actuators.as_builder()
    new_actuators.speed = self.speed
    new_actuators.accel = self.accel
    new_actuators.gas = self.gas
    new_actuators.brake = self.brake
    new_actuators.torque = self.last_torque
    new_actuators.torqueOutputCan = apply_torque

    self.frame += 1
    return new_actuators, can_sends
