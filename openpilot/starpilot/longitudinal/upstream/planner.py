#!/usr/bin/env python3
import math
import numpy as np

import openpilot.cereal.messaging as messaging
from opendbc.car.interfaces import ACCEL_MIN, ACCEL_MAX
from openpilot.common.constants import CV
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.modeld.constants import ModelConstants
from openpilot.selfdrive.controls.lib.longcontrol import LongCtrlState
from openpilot.starpilot.longitudinal.upstream.mpc import LongitudinalMpc, LongitudinalPlanSource
from openpilot.starpilot.longitudinal.upstream.mpc import T_IDXS as T_IDXS_MPC
from openpilot.selfdrive.controls.lib.drive_helpers import CONTROL_N, get_accel_from_plan, should_stop
from openpilot.selfdrive.car.cruise import V_CRUISE_MAX, V_CRUISE_UNSET
from openpilot.common.swaglog import cloudlog

A_CRUISE_MAX_VALS = [1.6, 1.2, 0.8, 0.6]
A_CRUISE_MAX_BP = [0., 10.0, 25., 40.]
J_CRUISE_VALS = [1.6, 1.2, 0.8, 0.6]
A_CRUISE_MIN = -1.2
CONTROL_N_T_IDX = ModelConstants.T_IDXS[:CONTROL_N]
ALLOW_THROTTLE_THRESHOLD = 0.4
MIN_ALLOW_THROTTLE_SPEED = 2.5

# Lookup table for turns
_A_TOTAL_MAX_V = [1.7, 3.2]
_A_TOTAL_MAX_BP = [20., 40.]

def get_max_accel(v_ego):
  return np.interp(v_ego, A_CRUISE_MAX_BP, A_CRUISE_MAX_VALS)

def get_coast_accel(pitch):
  return np.sin(pitch) * -5.65 - 0.3  # fitted from data using xx/projects/allow_throttle/compute_coast_accel.py

def get_cruise_accel(e2e, v_cruise, v_ego, a_cruise_prev, angle_steers, CP, dt, accel_coast, allow_throttle,
                     *, jerk_limit=True):  # BOSCH-A: jerk_limit=False only for the engage init (hook 3/3)
  max_accel = ACCEL_MAX if e2e else get_max_accel(v_ego)

  if not e2e:
    a_total_max = np.interp(v_ego, _A_TOTAL_MAX_BP, _A_TOTAL_MAX_V)
    a_y = v_ego ** 2 * angle_steers * CV.DEG_TO_RAD / (CP.steerRatio * CP.wheelbase)
    a_x_allowed = math.sqrt(max(a_total_max ** 2 - a_y ** 2, 0.))
    max_accel = min(max_accel, a_x_allowed)
    if not allow_throttle:
      clipped_accel_coast = max(accel_coast, ACCEL_MIN)
      coast_limit = np.interp(v_ego, [MIN_ALLOW_THROTTLE_SPEED, MIN_ALLOW_THROTTLE_SPEED*2], [max_accel, clipped_accel_coast])
      max_accel = min(max_accel, coast_limit)

  target_accel = np.clip(v_cruise - v_ego, A_CRUISE_MIN, max_accel)
  if not jerk_limit:
    return float(target_accel)
  j_cruise = np.interp(v_ego, A_CRUISE_MAX_BP, J_CRUISE_VALS)
  target_accel = float(np.clip(target_accel, a_cruise_prev - j_cruise * dt, a_cruise_prev + j_cruise * dt))

  return target_accel


class LongitudinalPlanner:
  def __init__(self, CP, init_v=0.0, init_a=0.0, dt=DT_MDL, *, bosch_a=None):
    self.CP = CP
    self.mpc = LongitudinalMpc(dt=dt)
    # ---- BOSCH-A HOOK 1/3 (owner toggles; not in upstream 521db4c8) ----
    # Same two features, same car gates and same order relative to the MPC and the final clip as StarPilot's
    # selfdrive/controls/lib/longitudinal_planner.py. `bosch_a` is a bosch_a_toggles.BoschAToggles (None = both Off).
    # With both toggles off both stay None, nothing below runs and the planner is upstream's. The car gates and the
    # StarPilot imports only happen when a toggle is on.
    self.bosch_a_model_leads = None  # HumanFollowing + HumanAcceleration
    self.bosch_a_long = None         # Stock Brake Feel
    if bosch_a is not None and bosch_a.human_following:
      import time
      from openpilot.starpilot.longitudinal import human_acceleration, human_following
      if human_following.enabled_for(CP, True):
        from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import ModelLeadHistory, qualified_model_leads
        self.bosch_a_model_leads = ModelLeadHistory()
        self.bosch_a_human = (human_following, human_acceleration, qualified_model_leads, time.monotonic_ns)
    if bosch_a is not None and bosch_a.stock_brake_feel:
      from openpilot.starpilot.longitudinal.honda_bosch_a_long import HondaBoschALongEnhancement
      enhancement = HondaBoschALongEnhancement(CP, dt, stock_brake_feel=True)
      self.bosch_a_long = enhancement if enhancement.enabled else None
    # Bosch-A brake release smoothing + short plan read-ahead (always on for Bosch-A Hondas; bosch_a_smooth.py).
    from openpilot.starpilot.longitudinal.bosch_a_smooth import BoschASmooth
    self.bosch_a_smooth = BoschASmooth(CP, dt)
    # ---- end BOSCH-A HOOK ----
    self.fcw = False
    self.dt = dt
    self.allow_throttle = True

    self.v_desired_filter = FirstOrderFilter(init_v, 2.0, self.dt)
    self.a_cruise = init_a
    self.output_a_target = init_a
    self.output_should_stop = False

    self.v_desired_trajectory = np.zeros(CONTROL_N)
    self.a_desired_trajectory = np.zeros(CONTROL_N)
    self.j_desired_trajectory = np.zeros(CONTROL_N)

  def update(self, sm):
    if len(sm['carControl'].orientationNED) == 3:
      accel_coast = get_coast_accel(sm['carControl'].orientationNED[1])
    else:
      accel_coast = ACCEL_MAX

    v_ego = sm['carState'].vEgo
    v_cruise_kph = min(sm['carState'].vCruise, V_CRUISE_MAX)
    v_cruise = v_cruise_kph * CV.KPH_TO_MS
    if sm['controlsState'].forceDecel:
      v_cruise = 0.0

    long_control_off = sm['controlsState'].longControlState == LongCtrlState.off

    # Reset current state when not engaged, or user is controlling the speed
    reset_state = long_control_off if self.CP.openpilotLongitudinalControl else not sm['selfdriveState'].enabled
    # PCM cruise speed may be updated a few cycles later, check if initialized
    v_cruise_initialized = sm['carState'].vCruise != V_CRUISE_UNSET
    reset_state = reset_state or not v_cruise_initialized

    throttle_probs = sm['modelV2'].meta.disengagePredictions.gasPressProbs
    throttle_prob = throttle_probs[1] if len(throttle_probs) > 1 else 1.0
    self.allow_throttle = throttle_prob > ALLOW_THROTTLE_THRESHOLD or v_ego <= MIN_ALLOW_THROTTLE_SPEED

    steer_angle_without_offset = sm['carState'].steeringAngleDeg - sm['vehicleParameters'].angleOffsetDeg

    if reset_state:
      self.v_desired_filter.x = v_ego
      self.output_a_target = np.clip(sm['carState'].aEgo, ACCEL_MIN, ACCEL_MAX)
      self.a_cruise = self.output_a_target

    # Prevent divergence, smooth in current v_ego
    self.v_desired_filter.x = max(0.0, self.v_desired_filter.update(v_ego))

    # No change cost when user is controlling the speed, or when standstill
    prev_accel_constraint = not (reset_state or sm['carState'].standstill)

    self.mpc.set_weights(prev_accel_constraint, personality=sm['selfdriveState'].personality)
    self.mpc.set_cur_state(self.v_desired_filter.x, self.output_a_target)
    # ---- BOSCH-A HOOK 2/3: HumanFollowing lead paths and the HumanAcceleration MPC cap (StarPilot planner: the
    # mpc.update call). Empty (stock call) unless the BoschAHumanFollowing toggle is on and the car passes. ----
    bosch_a_mpc = {}
    if self.bosch_a_model_leads is not None:
      human_following, human_acceleration, qualified_model_leads, clock_ns = self.bosch_a_human
      human_accel_base = ACCEL_MAX if sm['selfdriveState'].experimentalMode else get_max_accel(v_ego)
      model = qualified_model_leads(sm, clock_ns(), self.bosch_a_model_leads)
      bosch_a_mpc = {'acceleration_max': human_acceleration.cap(human_accel_base, v_cruise, v_ego),
                     'lead_paths': human_following.upstream_lead_paths(model, sm['radarState'], self.mpc.x0[1])}
    # ---- end BOSCH-A HOOK ----
    self.mpc.update(sm['radarState'], personality=sm['selfdriveState'].personality, **bosch_a_mpc)

    self.v_desired_trajectory = np.interp(CONTROL_N_T_IDX, T_IDXS_MPC, self.mpc.v_solution)
    self.a_desired_trajectory = np.interp(CONTROL_N_T_IDX, T_IDXS_MPC, self.mpc.a_solution)
    self.j_desired_trajectory = np.interp(CONTROL_N_T_IDX, T_IDXS_MPC[:-1], self.mpc.j_solution)

    # TODO counter is only needed because radar is glitchy, remove once radar is gone
    self.fcw = self.mpc.crash_cnt > 2 and not sm['carState'].standstill
    if self.fcw:
      cloudlog.info("FCW triggered")

    # Save starting point for next iteration
    a_prev = self.output_a_target

    action_t = self.bosch_a_smooth.action_t(self.CP.longitudinalActuatorDelay)
    output_a_target_mpc = get_accel_from_plan(self.v_desired_trajectory, self.a_desired_trajectory, CONTROL_N_T_IDX,
                                              action_t=action_t)
    output_should_stop_mpc = should_stop(v_ego, output_a_target_mpc)
    output_a_target_e2e = sm['modelV2'].action.desiredAcceleration
    output_should_stop_e2e = sm['modelV2'].action.shouldStop

    self.a_cruise = get_cruise_accel(sm['selfdriveState'].experimentalMode, v_cruise, v_ego,
                                     self.a_cruise, steer_angle_without_offset, self.CP, self.dt,
                                     accel_coast, self.allow_throttle)
    cruise_should_stop = should_stop(v_ego, self.a_cruise)

    candidates = [(output_a_target_mpc, self.mpc.source, output_should_stop_mpc),
                  (self.a_cruise, LongitudinalPlanSource.cruise, cruise_should_stop)]
    if sm['selfdriveState'].experimentalMode:
      candidates.append((output_a_target_e2e, LongitudinalPlanSource.e2e, output_should_stop_e2e))

    output_a_target, self.mpc.source, _ = min(candidates, key=lambda c: c[0])
    self.output_should_stop = any(should_stop for _, _, should_stop in candidates)
    # ---- BOSCH-A HOOK 3/3: last shapers before the final clip, in StarPilot's order (HumanAcceleration cap, then
    # the Stock Brake Feel step). Skipped entirely when the toggles are off. ----
    if self.bosch_a_model_leads is not None:
      output_a_target = min(output_a_target, bosch_a_mpc['acceleration_max'])  # >= 0: braking passes through
    if self.bosch_a_long is not None and self.bosch_a_long.stock_feel and reset_state:
      # Engage init (Stock Brake Feel only): while long is off, a_cruise starts the first engaged frame at
      # min(aEgo, cruise target) instead of aEgo (jerk-limited around aEgo), so it does not ramp down from a positive
      # aEgo at j_cruise while already at/above the set speed. When target >= aEgo this is the stock value. Bounded:
      # lowers only, never below the cruise floor (A_CRUISE_MIN); output_a_target and the MPC state are unchanged;
      # after engage get_cruise_accel jerk-limits from here and step() still limits brake onset.
      self.a_cruise = min(self.a_cruise, get_cruise_accel(sm['selfdriveState'].experimentalMode, v_cruise, v_ego,
                                                          self.a_cruise, steer_angle_without_offset, self.CP,
                                                          self.dt, accel_coast, self.allow_throttle, jerk_limit=False))
    if self.bosch_a_long is not None:
      output_a_target = self.bosch_a_long.step(
        lead_one=sm['radarState'].leadOne, lead_two=sm['radarState'].leadTwo, prev=float(a_prev),
        target=float(output_a_target), v_ego=v_ego, stopping=bool(self.output_should_stop),
        standstill=bool(sm['carState'].standstill), reset_state=bool(reset_state))
    output_a_target = self.bosch_a_smooth.step(float(a_prev), float(output_a_target),
                                               reset=bool(reset_state or sm['carState'].standstill))
    # ---- end BOSCH-A HOOK ----
    self.output_a_target = np.clip(output_a_target, ACCEL_MIN, ACCEL_MAX)

    self.v_desired_filter.x = self.v_desired_filter.x + self.dt * (self.output_a_target + a_prev) / 2.0

  def publish(self, sm, pm):
    plan_send = messaging.new_message('longitudinalPlan')

    plan_send.valid = sm.all_checks()

    longitudinalPlan = plan_send.longitudinalPlan
    longitudinalPlan.modelMonoTime = sm.logMonoTime['modelV2']
    longitudinalPlan.processingDelay = (plan_send.logMonoTime / 1e9) - sm.logMonoTime['modelV2']
    longitudinalPlan.solverExecutionTime = self.mpc.solve_time

    longitudinalPlan.speeds = self.v_desired_trajectory.tolist()
    longitudinalPlan.accels = self.a_desired_trajectory.tolist()
    longitudinalPlan.jerks = self.j_desired_trajectory.tolist()

    longitudinalPlan.hasLead = sm['radarState'].leadOne.present
    longitudinalPlan.longitudinalPlanSource = self.mpc.source
    longitudinalPlan.fcw = self.fcw

    longitudinalPlan.aTarget = float(self.output_a_target)
    longitudinalPlan.shouldStop = bool(self.output_should_stop)
    longitudinalPlan.allowBrake = True
    longitudinalPlan.allowThrottle = bool(self.allow_throttle)

    pm.send('longitudinalPlan', plan_send)
