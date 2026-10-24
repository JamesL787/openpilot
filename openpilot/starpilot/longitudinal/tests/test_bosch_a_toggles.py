"""BoschAStockBrakeFeel / BoschAHumanFollowing owner toggles: parsing, car gates, and both planners.

Static tests with a recording stand-in for the native acados solver; no replay or road evidence.
"""
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from openpilot.cereal import log, messaging
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import LEAD_T_IDXS_MODEL
from openpilot.selfdrive.controls.radard import RADAR_TO_CAMERA
from openpilot.starpilot.longitudinal import bosch_a_toggles, human_following
from openpilot.starpilot.longitudinal.bosch_a_toggles import OFF, BoschAToggles, read_toggles
from openpilot.starpilot.longitudinal.honda_bosch_a_long import HondaBoschALongEnhancement
from openpilot.starpilot.longitudinal.upstream import mpc, planner, plannerd


def car(fingerprint='HONDA_CIVIC_BOSCH', brand='honda', long=True, radar_unavailable=False):
  return SimpleNamespace(brand=brand, carFingerprint=fingerprint, openpilotLongitudinalControl=long,
                         radarUnavailable=radar_unavailable, pcmCruise=False, longitudinalActuatorDelay=0.15,
                         vEgoStopping=0.5, vEgoStarting=0.5, stopAccel=-2.0, stoppingDecelRate=0.8,
                         steerRatio=15.38, wheelbase=2.7)


BOSCH_A = car()
NOT_BOSCH_A = (car('TOYOTA_RAV4_TSS2_2023', brand='toyota'), car('HONDA_ACCORD'), car(long=False))


class FileParams:
  def __init__(self, root):
    self.root = root

  def get_param_path(self, key=''):
    return os.path.join(self.root, key)


class RecordingSolver:
  """Deterministic stand-in for AcadosOcpSolverCython: logs every call and derives x from the stage parameters, so any
  change in what the planner hands the MPC changes both the log and the planner output."""
  def __init__(self, *_):
    self.calls, self.p, self.x0 = [], {}, np.zeros(3)

  def _log(self, *args):
    self.calls.append(tuple(np.copy(a).tolist() if isinstance(a, np.ndarray) else a for a in args))

  def reset(self):
    self._log('reset')

  def cost_set(self, stage, key, value):
    self._log('cost_set', stage, key, value)

  def set(self, stage, key, value):
    self._log('set', stage, key, value)
    if key == 'p':
      self.p[stage] = np.copy(value)

  def constraints_set(self, stage, key, value):
    self._log('constraints_set', stage, key, value)
    self.x0 = np.copy(value)

  def solve(self):
    return 0

  def get_stats(self, _):
    return [0.001]

  def get(self, stage, key):
    if key == 'u':
      return np.array([0.0])
    p = self.p.get(stage, np.zeros(8))
    a = 0.5 * float(p[1]) - 0.02 * max(0.0, 60.0 - float(p[2]))
    return np.array([self.x0[0] + stage, self.x0[1] + 0.1 * stage * a, a])


def submaster(frame):
  services = ('carControl', 'carState', 'controlsState', 'vehicleParameters', 'radarState', 'modelV2', 'selfdriveState')
  msgs = {name: messaging.new_message(name) for name in services}
  cs = msgs['carState'].carState
  cs.vEgo, cs.aEgo, cs.vCruise, cs.canValid = 22.0 - 0.05 * frame, -0.2, 100.0, True
  # Frame 0 is the engage frame: 'off' resets the planner state to vEgo, as on the car.
  msgs['controlsState'].controlsState.longControlState = 'off' if frame == 0 else 'pid'
  ss = msgs['selfdriveState'].selfdriveState
  ss.enabled, ss.personality = True, log.LongitudinalPersonality.standard
  rs = msgs['radarState'].radarState
  d_rels = (32.0 - 0.3 * frame, 60.0)
  for track, (lead, d_rel) in enumerate(zip((rs.leadOne, rs.leadTwo), d_rels, strict=True)):
    lead.present, lead.dRel, lead.vLead, lead.vLeadK, lead.aLeadK, lead.aLeadTau, lead.modelProb, lead.radar = \
      True, d_rel, 18.0, 18.0, -0.8, 1.5, 0.9, True
    lead.radarTrackId = track + 1
  model = msgs['modelV2'].modelV2
  model.meta.disengagePredictions.gasPressProbs = [0.5, 0.5]
  model.velocity.x = [22.0] * 33
  model.init('leadsV3', 3)
  for i, model_lead in enumerate(model.leadsV3):
    # Matches leadOne/leadTwo (StarPilot's horizon check) but brakes harder than the radar aLeadK extrapolation.
    d_rel = d_rels[min(i, 1)]
    model_lead.prob = 0.9
    model_lead.t = LEAD_T_IDXS_MODEL.tolist()
    model_lead.x = [d_rel + RADAR_TO_CAMERA + 18.0 * t - 0.75 * t * t for t in model_lead.t]
    model_lead.y = [0.0] * len(model_lead.t)
    model_lead.v = [max(0.0, 18.0 - 1.5 * t) for t in model_lead.t]
    model_lead.a = [-1.5] * len(model_lead.t)
  return {name: getattr(msg, name) for name, msg in msgs.items()}


def run(planner_obj, frames=6):
  out = []
  for frame in range(frames):
    planner_obj.update(submaster(frame))
    out.append((float(planner_obj.output_a_target), bool(planner_obj.output_should_stop), bool(planner_obj.fcw),
                planner_obj.v_desired_trajectory.tolist(), planner_obj.a_desired_trajectory.tolist(),
                planner_obj.j_desired_trajectory.tolist()))
  return out, planner_obj.mpc.solver.calls


def upstream(cp, toggles):
  with patch.object(mpc, 'AcadosOcpSolverCython', RecordingSolver):
    return planner.LongitudinalPlanner(cp, bosch_a=toggles) if toggles is not None else planner.LongitudinalPlanner(cp)


class TestReadToggles(unittest.TestCase):
  def setUp(self):
    import tempfile
    self.dir = tempfile.TemporaryDirectory()
    self.params = FileParams(self.dir.name)

  def tearDown(self):
    self.dir.cleanup()

  def put(self, key, raw):
    with open(os.path.join(self.dir.name, key), 'wb') as f:
      f.write(raw)

  def test_missing_is_off(self):
    self.assertEqual(read_toggles(self.params), OFF)

  def test_only_exact_one_is_on(self):
    for raw, expected in ((b'1', True), (b'0', False), (b'', False), (b'true', False), (b'1\n', False), (b'\xff', False),
                          (b'1' * 9, False)):
      self.put(bosch_a_toggles.STOCK_BRAKE_FEEL_KEY, raw)
      self.put(bosch_a_toggles.HUMAN_FOLLOWING_KEY, raw)
      self.assertEqual(read_toggles(self.params), BoschAToggles(expected, expected), raw)

  def test_each_toggle_is_independent(self):
    self.put(bosch_a_toggles.HUMAN_FOLLOWING_KEY, b'1')
    self.assertEqual(read_toggles(self.params), BoschAToggles(stock_brake_feel=False, human_following=True))

  def test_unreadable_and_broken_params_are_off(self):
    os.mkdir(os.path.join(self.dir.name, bosch_a_toggles.STOCK_BRAKE_FEEL_KEY))  # not a regular file
    self.put(bosch_a_toggles.HUMAN_FOLLOWING_KEY, b'1')
    self.assertEqual(read_toggles(self.params), BoschAToggles(stock_brake_feel=False, human_following=True))
    self.assertEqual(read_toggles(SimpleNamespace()), OFF)  # no get_param_path
    self.assertEqual(read_toggles(None), OFF)


class TestCarGates(unittest.TestCase):
  def test_stock_brake_feel_needs_toggle_and_bosch_a(self):
    self.assertFalse(HondaBoschALongEnhancement(BOSCH_A, 0.05).stock_feel)
    self.assertFalse(HondaBoschALongEnhancement(BOSCH_A, 0.05, stock_brake_feel=False).stock_feel)
    self.assertTrue(HondaBoschALongEnhancement(BOSCH_A, 0.05, stock_brake_feel=True).stock_feel)
    self.assertFalse(HondaBoschALongEnhancement(car(radar_unavailable=True), 0.05, stock_brake_feel=True).stock_feel)
    for cp in NOT_BOSCH_A:
      enhancement = HondaBoschALongEnhancement(cp, 0.05, stock_brake_feel=True)
      self.assertFalse(enhancement.enabled or enhancement.stock_feel, cp)

  def test_human_following_needs_toggle_and_bosch_a(self):
    self.assertFalse(human_following.enabled_for(BOSCH_A))
    self.assertFalse(human_following.enabled_for(BOSCH_A, False))
    self.assertFalse(human_following.enabled_for(BOSCH_A, 1))  # only a real True arms it
    self.assertTrue(human_following.enabled_for(BOSCH_A, True))
    self.assertTrue(human_following.enabled_for(car(radar_unavailable=True), True))  # vision-only shares it
    for cp in NOT_BOSCH_A:
      self.assertFalse(human_following.enabled_for(cp, True), cp)

  def test_settings_row_gate(self):
    self.assertTrue(bosch_a_toggles.vehicle_supported(BOSCH_A))
    self.assertFalse(bosch_a_toggles.vehicle_supported(None))
    for cp in NOT_BOSCH_A:
      self.assertFalse(bosch_a_toggles.vehicle_supported(cp), cp)


class TestUpstreamPlanner(unittest.TestCase):
  def test_toggles_off_is_bit_identical_to_upstream(self):
    reference = run(upstream(BOSCH_A, None))
    self.assertEqual(run(upstream(BOSCH_A, OFF)), reference)
    self.assertEqual(run(upstream(BOSCH_A, BoschAToggles())), reference)

  def test_non_bosch_a_car_with_toggles_on_is_bit_identical(self):
    for cp in NOT_BOSCH_A:
      reference = run(upstream(cp, None))
      stock = upstream(cp, BoschAToggles(True, True))
      self.assertIsNone(stock.bosch_a_long)
      self.assertIsNone(stock.bosch_a_model_leads)
      self.assertEqual(run(stock), reference, cp)

  def test_stock_brake_feel_runs_step_on_bosch_a(self):
    stock = upstream(BOSCH_A, BoschAToggles(stock_brake_feel=True))
    self.assertIsNotNone(stock.bosch_a_long)
    self.assertTrue(stock.bosch_a_long.stock_feel)
    self.assertIsNone(stock.bosch_a_model_leads)
    seen = []
    original = stock.bosch_a_long.step
    def spy(**kwargs):
      result = original(**kwargs)
      seen.append((kwargs, result))
      return result
    stock.bosch_a_long.step = spy
    outputs, _ = run(stock)
    self.assertEqual(len(seen), len(outputs))
    for frame, ((kwargs, result), output) in enumerate(zip(seen, outputs, strict=True)):
      self.assertEqual(output[0], float(np.clip(result, mpc.ACCEL_MIN, mpc.ACCEL_MAX)))
      self.assertEqual(kwargs['lead_one'].dRel, submaster(frame)['radarState'].leadOne.dRel)  # raw radarState leads
      self.assertEqual(kwargs['reset_state'], frame == 0)

  def test_human_following_passes_cap_and_lead_paths_on_bosch_a(self):
    from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib import long_mpc
    with patch.object(long_mpc, 'qualified_model_leads', side_effect=lambda sm, now_ns, history: sm['modelV2']):
      stock = upstream(BOSCH_A, BoschAToggles(human_following=True))
    self.assertIsNotNone(stock.bosch_a_model_leads)
    self.assertIsNone(stock.bosch_a_long)
    seen = []
    original = stock.mpc.update
    def spy(radarstate, personality=None, **kwargs):
      seen.append(kwargs)
      return original(radarstate, personality=personality, **kwargs)
    stock.mpc.update = spy
    outputs, _ = run(stock)
    reference, _ = run(upstream(BOSCH_A, None))
    self.assertEqual(len(seen), len(outputs))
    for kwargs in seen:
      self.assertEqual(set(kwargs), {'acceleration_max', 'lead_paths'})
      self.assertTrue(0.0 <= kwargs['acceleration_max'] <= mpc.ACCEL_MAX)
      self.assertEqual(len(kwargs['lead_paths']), 2)
      self.assertTrue(any(path is not None for path in kwargs['lead_paths']))
    np.testing.assert_array_equal(stock.mpc.params[:, 1], seen[-1]['acceleration_max'])
    self.assertNotEqual(outputs, reference)

  def test_human_following_without_fresh_model_keeps_stock_lead_paths(self):
    stock = upstream(BOSCH_A, BoschAToggles(human_following=True))  # the real freshness check rejects the fake sm
    seen = []
    original = stock.mpc.update
    def spy(radarstate, personality=None, **kwargs):
      seen.append(kwargs['lead_paths'])
      return original(radarstate, personality=personality, **kwargs)
    stock.mpc.update = spy
    run(stock, frames=2)
    self.assertEqual(seen, [(None, None), (None, None)])

  def test_mpc_rejects_out_of_range_cap(self):
    with patch.object(mpc, 'AcadosOcpSolverCython', RecordingSolver):
      stock = mpc.LongitudinalMpc()
    radar = submaster(0)['radarState']
    for bad in (float('nan'), float('inf'), -0.1, mpc.ACCEL_MAX + 0.1):
      stock.update(radar, acceleration_max=bad)
      np.testing.assert_array_equal(stock.params[:, 1], mpc.ACCEL_MAX)
    stock.update(radar, acceleration_max=0.5)
    np.testing.assert_array_equal(stock.params[:, 1], 0.5)

  def test_plannerd_reads_toggles_once_and_passes_them(self):
    calls = []
    class SM:
      def update(self):
        raise InterruptedError('bounded end of mocked loop')
    toggles = BoschAToggles(True, False)
    with patch.object(plannerd, 'config_realtime_process'), \
         patch.object(plannerd, 'Params', return_value=SimpleNamespace(get=lambda key, **kwargs: b'CP')), \
         patch.object(plannerd.messaging, 'log_from_bytes', return_value=BOSCH_A), \
         patch.object(plannerd, 'read_bosch_a_toggles', side_effect=lambda params: calls.append('read') or toggles), \
         patch.object(plannerd, 'LongitudinalPlanner', side_effect=lambda cp, **kw: calls.append(kw)), \
         patch.object(plannerd, 'LaneDepartureWarning', return_value=object()), \
         patch.object(plannerd.messaging, 'PubMaster'), \
         patch.object(plannerd.messaging, 'SubMaster', return_value=SM()):
      with self.assertRaises(InterruptedError):
        plannerd.main()
    self.assertEqual(calls, ['read', {'bosch_a': toggles}])


class TestStarPilotPlanner(unittest.TestCase):
  def build(self, cp, toggles):
    from openpilot.selfdrive.controls.lib import longitudinal_planner
    from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib import long_mpc
    with patch.object(long_mpc, 'AcadosOcpSolverCython', RecordingSolver):
      return longitudinal_planner.LongitudinalPlanner(cp, bosch_a=toggles) if toggles is not None else \
        longitudinal_planner.LongitudinalPlanner(cp)

  def test_defaults_and_off_arm_nothing(self):
    for toggles in (None, OFF):
      stock = self.build(BOSCH_A, toggles)
      self.assertFalse(stock.human_driving)
      self.assertFalse(stock.bosch_a_long.stock_feel)

  def test_toggles_arm_features_on_bosch_a_only(self):
    stock = self.build(BOSCH_A, BoschAToggles(True, True))
    self.assertTrue(stock.human_driving)
    self.assertTrue(stock.bosch_a_long.stock_feel)
    for cp in NOT_BOSCH_A:
      other = self.build(cp, BoschAToggles(True, True))
      self.assertFalse(other.human_driving, cp)
      self.assertFalse(other.bosch_a_long.stock_feel, cp)

  def test_plannerd_passes_toggles(self):
    from openpilot.selfdrive.controls import plannerd as starpilot_plannerd
    self.assertIs(starpilot_plannerd.read_bosch_a_toggles, read_toggles)


if __name__ == '__main__':
  unittest.main()
