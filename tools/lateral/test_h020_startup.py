"""Run the real res params/setup/card-init/CAN code with only host I/O replaced.

The card initializer is compiled from its actual AST so Mac tests need not import
socket/native Params modules. No startup/controller/packing algorithms are stubbed.
"""

import ast
import importlib
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace as NS
import numpy as np
import pytest
from cereal import car, custom
from opendbc.car import structs
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.values import CAR, DBC
from opendbc.car.honda.carcontroller import CarController
from opendbc.sunnypilot.car.honda import h020_ptm as gate
from openpilot.selfdrive.controls.lib import honda_eps_h020_activation as activation
from openpilot.selfdrive.controls.lib.latcontrol_honda_eps import LatControlHondaEps

ROOT = Path(__file__).resolve().parents[2]
CFG = {"enabled": True, "ptm_build": "20261011-trk4250", "calibration_stage": "provisional"}


def real_params(config=CFG, version=b"39990-TEA,H020\0\0"):
  fw = [car.CarParams.CarFw.new_message(ecu="eps", address=0x18DA30F1, fwVersion=version)]
  fp = {0: {}, 1: {}, 2: {}}
  with gate.startup_config(config):
    cp = CarInterface.get_params(CAR.HONDA_CIVIC_BOSCH, fp, fw, False, False, False)
    sp = CarInterface.get_params_sp(cp, CAR.HONDA_CIVIC_BOSCH, fp, fw, False, False, False)
  cp.carFw = fw
  cp.fingerprintSource = "fw"
  cp.fuzzyFingerprint = False
  return cp, sp


def controller():
  cp, sp = real_params()
  ctrl = LatControlHondaEps(cp, sp, None, activation=CFG)
  cs = NS(steeringAngleDeg=20.0, steeringRateDeg=0.0, steeringTorque=0.0, vEgo=15.0, steeringPressed=False)
  lp = NS(roll=0.0, angleOffsetDeg=0.0)
  k = ctrl.rack.curvature_from_angle(20.0, 15.0, 0.0)
  for _ in range(250):
    ctrl.update(True, cs, None, lp, False, k, None, False)
  assert ctrl.core.ff_weight == 1.0
  return ctrl, cs, lp, k


def test_short_same_direction_press_retains_ff_and_real_override_drops_it():
  ctrl, cs, lp, k = controller()
  cs.steeringPressed = True
  cs.steeringTorque = np.sign(ctrl.core.output) * 100
  for _ in range(5):
    ctrl.update(True, cs, None, lp, False, k, None, False)
    assert ctrl.core.ff_weight == 1.0
  # Opposing driver torque is immediately recognized, regardless of the same-direction filter.
  cs.steeringTorque = -np.sign(ctrl.core.output) * 100
  ctrl.update(True, cs, None, lp, False, k, None, False)
  assert ctrl.core.ff_weight == 0.0
  assert ctrl.steering_pressed_prev is True


def test_sustained_same_direction_press_is_still_recognized():
  ctrl, cs, lp, k = controller()
  cs.steeringPressed = True
  cs.steeringTorque = np.sign(ctrl.core.output) * 100
  for _ in range(29):
    ctrl.update(True, cs, None, lp, False, k, None, False)
  assert ctrl.core.ff_weight == 0.0


def test_brief_dropout_preserves_state_but_requests_zero_steering():
  ctrl, cs, lp, k = controller()
  before_i = ctrl.core.pid.i
  ctrl.reset()  # actual controlsd ordering: reset before inactive update
  out, _, state = ctrl.update(False, cs, None, lp, True, k, None, False)
  assert out == 0.0 and not state.active
  assert ctrl.core.ff_weight == 1.0 and ctrl.core.pid.i == before_i
  ctrl.update(True, cs, None, lp, False, k, None, False)
  assert ctrl.core.ff_weight == 1.0
  for _ in range(12):
    ctrl.reset()
    out, _, state = ctrl.update(False, cs, None, lp, True, k, None, False)
    assert out == 0.0 and not state.active
  assert ctrl.core.output == 0.0 and ctrl.core.pid.i == 0.0 and ctrl.core.ff_weight == 0.0


def test_source_wrapper_filter_default():
  ctrl, *_ = controller()
  assert ctrl.core.output_lpf_tau == (0.1, 0.1, 0.1)


def test_activation_snapshot_survives_config_removal_without_pid_fallback(tmp_path, monkeypatch):
  cp, sp = real_params()
  path = tmp_path / 'activation.json'
  raw = cp.to_bytes()
  activation.publish_activation(raw, CFG, path)
  operator = tmp_path / 'config.json'
  operator.write_text(json.dumps(CFG))
  monkeypatch.setattr(gate, 'CONFIG_PATH', operator)
  snapshot = activation.load_activation(cp, raw, path)
  operator.unlink()
  # Constructor gets the already latched decision; it must not reread the operator config.
  ctrl = LatControlHondaEps(cp, sp, None, activation=snapshot)
  assert ctrl.calibration.name == 'civic_tea_h020'


@pytest.mark.parametrize('kind', ['missing', 'corrupt', 'hash', 'disabled'])
def test_tuned_params_never_silently_fall_back_on_bad_record(tmp_path, kind):
  cp, _ = real_params()
  raw = cp.to_bytes()
  p = tmp_path / 'activation.json'
  if kind != 'missing':
    activation.publish_activation(raw, CFG if kind != 'disabled' else {'enabled': False}, p)
  if kind == 'corrupt':
    p.write_text('bad-json')
  if kind == 'hash':
    record = json.loads(p.read_text())
    record['cp_sha256'] = '0' * 64
    p.write_text(json.dumps(record))
  with pytest.raises(activation.H020ActivationError):
    activation.load_activation(cp, raw, p)


def test_untuned_baseline_needs_no_activation_record(tmp_path):
  cp, _ = real_params({'enabled': False})
  assert activation.load_activation(cp, cp.to_bytes(), path=tmp_path / 'missing') == {'enabled': False}


@pytest.mark.parametrize('tune', ['old-prototype', 'overwritten-torque'])
def test_stale_port_map_cannot_fall_back_without_record(tmp_path, tune):
  cp, _ = real_params()
  if tune == 'old-prototype':
    cp.lateralTuning.pid.kpBP, cp.lateralTuning.pid.kpV = [[0.0], [0.03]]
  else:
    CarInterface.configure_torque_tune(cp.carFingerprint, cp.lateralTuning)
  with pytest.raises(activation.H020ActivationError):
    activation.load_activation(cp, cp.to_bytes(), path=tmp_path / 'missing')


@pytest.mark.parametrize('record_ok', [True, False])
def test_read_only_report_explains_activation_mismatch(tmp_path, record_ok):
  from openpilot.tools.lateral.inspect_h020 import build_report

  cp, _ = real_params()
  raw = cp.to_bytes()
  p = tmp_path / 'activation.json'
  if record_ok:
    activation.publish_activation(raw, CFG, p)
  report = build_report(cp, raw, NS(get_bool=lambda _: False), CFG, p)
  assert report['controller_selected'] is record_ok
  assert bool(report['blockers']) is not record_ok


@pytest.mark.parametrize('field,value', [('fuzzyFingerprint', True), ('fingerprintSource', 'can'), ('dashcamOnly', True), ('carFingerprint', 'HONDA_CIVIC')])
def test_unverified_platform_is_blocked(field, value):
  cp, _ = real_params()
  setattr(cp, field, value)
  with pytest.raises(activation.H020ActivationError, match='fresh, exact'):
    activation.validate_final_params(cp, CFG, NS(get_bool=lambda _: False))


@pytest.fixture
def setup_runtime(monkeypatch):
  store = {'OpenpilotEnabledToggle': True}
  events = []

  class MemoryParams:
    def get(self, key, *a, **k):
      return store.get(key)

    def get_bool(self, key, *a, **k):
      return bool(store.get(key, False))

    def put(self, key, value):
      store[key] = value
      events.append(key)

    def put_bool(self, key, value):
      store[key] = value

    def put_nonblocking(self, key, value):
      store[key] = value

    def remove(self, key):
      store.pop(key, None)

  p = ModuleType('openpilot.common.params')
  p.Params = MemoryParams
  p.UnknownKeyName = KeyError
  monkeypatch.setitem(sys.modules, p.__name__, p)
  sentry = ModuleType('openpilot.system.sentry')
  sentry.capture_fingerprint = sentry.capture_fingerprint_mock = lambda *a: None
  monkeypatch.setitem(sys.modules, sentry.__name__, sentry)
  stats = ModuleType('sunnypilot.sunnylink.statsd')
  stats.STATSLOGSP = NS(raw=lambda *a: None)
  monkeypatch.setitem(sys.modules, stats.__name__, stats)
  setup = importlib.import_module('openpilot.sunnypilot.selfdrive.car.interfaces')
  monkeypatch.setattr(setup, 'Params', MemoryParams)
  monkeypatch.setattr(setup, 'get_nn_model_path', lambda cp: ('/not-loaded', 'TEST_H020_MODEL', True))
  monkeypatch.setattr(setup, 'STATSLOGSP', stats.STATSLOGSP)
  return MemoryParams, store, events, setup


@pytest.mark.parametrize('toggle', ['EnforceTorqueControl', 'NeuralNetworkLateralControl'])
def test_real_setup_cannot_silently_replace_h020_pid(setup_runtime, toggle):
  MemoryParams, store, _, setup = setup_runtime
  cp, sp = real_params()
  ci = NS(CP=cp, CP_SP=sp, configure_torque_tune=CarInterface.configure_torque_tune)
  store[toggle] = True
  setup.setup_interfaces(ci, MemoryParams())
  assert cp.lateralTuning.which() == 'torque'  # reproduce the audit's actual downstream change
  with pytest.raises(activation.H020ActivationError, match='turn off'):
    activation.validate_final_params(cp, CFG, MemoryParams())


@pytest.mark.parametrize('toggle', [None, 'EnforceTorqueControl', 'NeuralNetworkLateralControl'])
def test_actual_card_initializer_fresh_queries_and_publishes_coherent_snapshot(setup_runtime, monkeypatch, tmp_path, toggle):
  MemoryParams, store, events, setup = setup_runtime
  old, _ = real_params({'enabled': False}, b'39990-TBA,C020')
  store['CarParamsCache'] = old.to_bytes()
  store['CarPlatformBundle'] = {'platform': 'FORCED_WRONG_PLATFORM'}
  if toggle:
    store[toggle] = True
  config_file = tmp_path / 'config.json'
  config_file.write_text(json.dumps(CFG))
  monkeypatch.setattr(gate, 'CONFIG_PATH', config_file)
  monkeypatch.setattr(activation, 'ACTIVATION_PATH', tmp_path / 'activation.json')
  calls = []

  def get_car(*args):
    calls.append(args)
    assert args[6] is None and args[7] is None  # cached CP and forced fingerprint disabled
    # Consume the exact ContextVar snapshot. Editing/removing the operator file during startup cannot alter it.
    config_file.unlink()
    cp, sp = real_params(gate.requested_config())
    cc = CarController(DBC[CAR.HONDA_CIVIC_BOSCH], cp, sp)
    return NS(CP=cp, CP_SP=sp, CC=cc, CS=NS(), configure_torque_tune=CarInterface.configure_torque_tune)

  def publish(raw, cfg):
    activation.publish_activation(raw, cfg)
    events.append('activation')

  messaging = NS(
    sub_sock=lambda *a, **k: None,
    SubMaster=lambda *a, **k: NS(sock={'pandaStates': None}),
    PubMaster=lambda *a, **k: NS(sock={'sendcan': None}),
    recv_one_retry=lambda *a: NS(can=[None], pandaStates=[None]),
  )
  from openpilot.selfdrive.car.helpers import convert_to_capnp

  env = dict(
    os=NS(environ={}),
    messaging=messaging,
    car=car,
    custom=custom,
    Params=MemoryParams,
    can_comm_callbacks=lambda *a: (None, None),
    obd_callback=lambda *a: None,
    read_h020_config=gate.read_config,
    startup_config=gate.startup_config,
    get_car=get_car,
    sunnypilot_interfaces=setup,
    interfaces={str(CAR.HONDA_CIVIC_BOSCH): NS(RadarInterface=lambda *a: None)},
    set_alternative_experience=lambda *a: None,
    set_car_specific_params=lambda *a: None,
    structs=structs,
    validate_final_params=activation.validate_final_params,
    publish_activation=publish,
    convert_to_capnp=convert_to_capnp,
    MockCarState=lambda: NS(),
    VCruiseHelper=lambda *a: NS(),
    Ratekeeper=lambda *a, **k: NS(),
  )
  tree = ast.parse((ROOT / 'selfdrive/car/card.py').read_text())
  cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Car')
  init = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '__init__')
  exec(compile(ast.Module(body=[init], type_ignores=[]), str(ROOT / 'selfdrive/car/card.py'), 'exec'), env)
  instance = NS()
  if toggle:
    with pytest.raises(activation.H020ActivationError, match='turn off'):
      env['__init__'](instance)
    assert 'CarParams' not in store and 'activation' not in events
    return
  env['__init__'](instance)
  assert len(calls) == 1 and events.index('activation') < events.index('CarParams')
  with car.CarParams.from_bytes(store['CarParams']) as cp:
    snapshot = activation.load_activation(cp, store['CarParams'])
    assert snapshot['enabled'] is True
    assert activation.expected_tune(cp)
  assert store['CarParamsCache'] == store['CarParams']


@pytest.mark.parametrize('enabled', [True, False])
def test_actual_controlsd_initializer_selects_from_one_startup_snapshot(tmp_path, enabled):
  from openpilot.selfdrive.controls.lib.latcontrol_honda_eps import use_honda_eps_controller

  config = CFG if enabled else {'enabled': False}
  cp, sp = real_params(config)
  raw = cp.to_bytes()
  record = tmp_path / 'activation.json'
  activation.publish_activation(raw, config, record)
  reads = []

  def load(actual_cp, actual_raw):
    assert actual_raw == raw
    reads.append(actual_raw)
    return activation.load_activation(actual_cp, actual_raw, record)

  class ControlsExt:
    def __init__(self, *args):
      self.CP_SP = sp
      self.sm_services_ext = []
      self.pm_services_ext = []
      record.unlink()  # selection and construction must use the already loaded snapshot

  class ModelStateBase:
    def __init__(self):
      pass

  env = dict(
    Params=lambda: NS(get=lambda *a, **k: raw),
    cloudlog=NS(info=lambda *a: None, error=lambda *a: None),
    messaging=NS(log_from_bytes=lambda *a: cp, SubMaster=lambda *a, **k: None, PubMaster=lambda *a: None),
    car=car,
    load_activation=load,
    H020RuntimeGuard=lambda *args: activation.H020RuntimeGuard(*args),
    ControlsExt=ControlsExt,
    ModelStateBase=ModelStateBase,
    interfaces={cp.carFingerprint: lambda *a: None},
    PoseCalibrator=lambda: None,
    LongControl=lambda *a: None,
    VehicleModel=lambda *a: None,
    LatControlHondaEps=LatControlHondaEps,
    use_honda_eps_controller=use_honda_eps_controller,
    LatControlPID=lambda *a: 'baseline-pid',
  )
  tree = ast.parse((ROOT / 'selfdrive/controls/controlsd.py').read_text())
  cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Controls')
  init = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '__init__')
  exec(compile(ast.Module(body=[init], type_ignores=[]), str(ROOT / 'selfdrive/controls/controlsd.py'), 'exec'), env)
  instance = NS()
  env['__init__'](instance)
  assert len(reads) == 1
  assert isinstance(instance.LaC, LatControlHondaEps) if enabled else instance.LaC == 'baseline-pid'


@pytest.mark.parametrize('command', [-0.5, 0.5])
@pytest.mark.parametrize('active', [True, False])
def test_real_honda_carcontroller_e4_sign_range_and_request(command, active):
  cp, sp = real_params()
  cc = CarController(DBC[CAR.HONDA_CIVIC_BOSCH], cp, sp)
  cc.frame = 1  # skip unrelated 10 Hz dashboard messages
  cc.last_torque = command  # test the settled command, not transport slew
  request = car.CarControl.new_message()
  request.enabled = True
  request.latActive = active
  request.actuators.torque = command
  state = NS(out=car.CarState.new_message(), v_cruise_factor=1.0)
  outputs, messages = cc.update(request.as_reader(), structs.CarControlSP(), state, 0)
  e4 = next(dat for addr, dat, bus in messages if addr == 0xE4)
  value = int.from_bytes(e4[:2], 'big', signed=True)
  assert value == (int(-command * 3840) if active else 0)
  assert abs(value) <= 3840
  # res reports its pre-request-gate number here; hondacan zeros the actual inactive CAN command.
  assert outputs.torqueOutputCan == int(-command * 3840)
  # DBC STEER_TORQUE_REQUEST is bit 23 (Motorola, the high bit of byte 2).
  assert bool(e4[2] & 0x80) == active


def test_stock_h020_is_not_newly_added_to_bosch_fingerprints():
  from opendbc.sunnypilot.car.honda.fingerprints_ext import FW_VERSIONS_EXT

  versions = FW_VERSIONS_EXT[CAR.HONDA_CIVIC_BOSCH][(car.CarParams.Ecu.eps, 0x18DA30F1, None)]
  assert b'39990-TEA-H020\0\0' not in versions
  assert b'39990-TEA,H020\0\0' in versions


# A-E regression harness: execute the real initializer and state_control bodies.
# Only native host I/O, firmware-query transport, and unrelated longitudinal/services are substituted.
def execute_method(path, cls_name, method, env):
  tree = ast.parse((ROOT / path).read_text())
  cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls_name)
  fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method)
  exec(compile(ast.Module(body=[fn], type_ignores=[]), str(ROOT / path), 'exec'), env)
  return env[method]


@pytest.fixture
def live_startup(setup_runtime, monkeypatch, tmp_path):
  from opendbc.car.vehicle_model import VehicleModel
  from openpilot.selfdrive.car.helpers import convert_to_capnp
  from openpilot.selfdrive.controls.lib.drive_helpers import clip_curvature
  from openpilot.selfdrive.controls.lib.latcontrol_honda_eps import use_honda_eps_controller
  from openpilot.selfdrive.controls.lib.latcontrol_pid import LatControlPID
  import math
  from numbers import Number

  MemoryParams, store, events, setup = setup_runtime
  operator = tmp_path / 'operator.json'
  record = tmp_path / 'activation.json'
  monkeypatch.setattr(gate, 'CONFIG_PATH', operator)
  monkeypatch.setattr(activation, 'ACTIVATION_PATH', record)
  errors = []
  # Match production's carlog error path while keeping an exact assertion log.
  from opendbc.car.carlog import carlog

  monkeypatch.setattr(carlog, 'error', lambda msg, *a, **k: errors.append(str(msg)))
  now = [100.0]

  def card_start(config=CFG, version=b'39990-TEA,H020\0\0', candidate=CAR.HONDA_CIVIC_BOSCH, mutate=None):
    if config is None:
      operator.unlink(missing_ok=True)
    else:
      operator.write_text(json.dumps(config))

    def get_car(*args):
      fw = [car.CarParams.CarFw.new_message(ecu='eps', address=0x18DA30F1, fwVersion=version, brand='honda')]
      fp = {0: {}, 1: {}, 2: {}}
      cp = CarInterface.get_params(candidate, fp, fw, False, False, False)
      sp = CarInterface.get_params_sp(cp, candidate, fp, fw, False, False, False)
      cp.carFw = fw
      cp.fingerprintSource = 'fw'
      if mutate is not None:
        mutate(cp)
      return NS(CP=cp, CP_SP=sp, CC=CarController(DBC[candidate], cp, sp), CS=NS(), configure_torque_tune=CarInterface.configure_torque_tune)

    messaging = NS(
      sub_sock=lambda *a, **k: None,
      SubMaster=lambda *a, **k: NS(sock={'pandaStates': None}),
      PubMaster=lambda *a, **k: NS(sock={'sendcan': None}),
      recv_one_retry=lambda *a: NS(can=[None], pandaStates=[None]),
    )
    env = dict(
      os=NS(environ={}),
      messaging=messaging,
      car=car,
      custom=custom,
      Params=MemoryParams,
      can_comm_callbacks=lambda *a: (None, None),
      obd_callback=lambda *a: None,
      read_h020_config=gate.read_config,
      startup_config=gate.startup_config,
      get_car=get_car,
      sunnypilot_interfaces=setup,
      interfaces={candidate: NS(RadarInterface=lambda *a: None)},
      set_alternative_experience=lambda *a: None,
      set_car_specific_params=lambda *a: None,
      structs=structs,
      validate_final_params=activation.validate_final_params,
      publish_activation=activation.publish_activation,
      convert_to_capnp=convert_to_capnp,
      MockCarState=lambda: NS(),
      VCruiseHelper=lambda *a: NS(),
      Ratekeeper=lambda *a, **k: NS(),
    )
    instance = NS()
    execute_method('selfdrive/car/card.py', 'Car', '__init__', env)(instance)
    return instance

  def controls_start(card):
    class ControlsExt:
      def __init__(self, *args):
        self.CP_SP = card.CP_SP
        self.sm_services_ext = []
        self.pm_services_ext = []

    class ModelStateBase:
      def __init__(self):
        pass

    raw = store['CarParams']
    # Keep a real reader alive, just as cereal.messaging.log_from_bytes does.
    reader_context = car.CarParams.from_bytes(raw)
    cp = reader_context.__enter__()
    env = dict(
      Params=MemoryParams,
      cloudlog=NS(info=lambda *a: None, error=lambda msg: errors.append(msg)),
      messaging=NS(log_from_bytes=lambda *a: cp, SubMaster=lambda *a, **k: None, PubMaster=lambda *a: None),
      car=car,
      load_activation=activation.load_activation,
      H020RuntimeGuard=(lambda *a: activation.H020RuntimeGuard(*a, clock=lambda: now[0])),
      ControlsExt=ControlsExt,
      ModelStateBase=ModelStateBase,
      interfaces={
        cp.carFingerprint: lambda *a: NS(
          get_pid_accel_limits=CarInterface.get_pid_accel_limits, get_steer_feedforward_function=lambda: CarInterface.get_steer_feedforward_default
        )
      },
      PoseCalibrator=lambda: None,
      LongControl=lambda *a: None,
      VehicleModel=VehicleModel,
      LatControlHondaEps=LatControlHondaEps,
      use_honda_eps_controller=use_honda_eps_controller,
      LatControlPID=LatControlPID,
    )
    controls = NS()
    execute_method('selfdrive/controls/controlsd.py', 'Controls', '__init__', env)(controls)
    controls._reader_context = reader_context
    lp = NS(stiffnessFactor=1.0, steerRatio=cp.steerRatio, roll=0.0, angleOffsetDeg=0.0)
    cs = car.CarState.new_message(vEgo=15.0, steeringAngleDeg=20.0)
    curvature = controls.LaC.rack.curvature_from_angle(20.0, 15.0, 0.0) if isinstance(controls.LaC, LatControlHondaEps) else 0.0
    controls.sm = {
      'carState': cs,
      'liveParameters': lp,
      'longitudinalPlan': NS(aTarget=0.0, shouldStop=False),
      'modelV2': NS(meta=NS(laneChangeState=0), action=NS(desiredCurvature=curvature)),
      'selfdriveState': NS(enabled=True),
      'onroadEvents': [],
    }
    controls.get_lat_active = lambda *a: True
    controls.LoC = NS(long_control_state='off', reset=lambda: None, update=lambda *a: 0.0)
    env.update(
      math=math,
      CV=NS(KPH_TO_MS=1 / 3.6),
      LaneChangeState=NS(off=0),
      clip_curvature=clip_curvature,
      ACTUATOR_FIELDS=tuple(car.CarControl.Actuators.schema.fields),
      Number=Number,
    )
    state_control = execute_method('selfdrive/controls/controlsd.py', 'Controls', 'state_control', env)
    return controls, lambda: state_control(controls)

  return NS(card=card_start, controls=controls_start, store=store, errors=errors, now=now, record=record, Params=MemoryParams)


@pytest.mark.parametrize(
  'version,candidate',
  [(b'39990-TEA-H020\0\0', CAR.HONDA_CIVIC_BOSCH), (b'39990-TBA,C020\0\0', CAR.HONDA_CIVIC_BOSCH), (b'39990-TEA-H020\0\0', CAR.HONDA_CIVIC)],
)
def test_A_enabled_on_other_eps_uses_original_res_startup(live_startup, version, candidate):
  from openpilot.tools.lateral.inspect_h020 import build_report

  h = live_startup
  baseline = h.card({'enabled': False}, version, candidate)
  expected_cp = baseline.CP.to_dict()
  expected_sp = vars(baseline.CP_SP)
  h.errors.clear()
  card = h.card(CFG, version, candidate)
  assert card.CP.to_dict() == expected_cp and vars(card.CP_SP) == expected_sp
  assert any('ignoring' in message.lower() and 'H020' in message for message in h.errors)
  controls, _ = h.controls(card)
  assert not isinstance(controls.LaC, LatControlHondaEps)
  report = build_report(card.CP, h.store['CarParams'], h.Params(), CFG, h.record)
  assert report['ignored_config_reason'] and not report['blockers'] and not report['controller_selected']


@pytest.mark.parametrize('config', [None, {'enabled': False}])
def test_A_disabled_or_missing_is_ordinary_res(live_startup, config):
  h = live_startup
  card = h.card(config)
  assert not h.errors
  assert list(card.CP.lateralParams.torqueBP) == [0, 2564, 8000]
  controls, _ = h.controls(card)
  assert not isinstance(controls.LaC, LatControlHondaEps)


@pytest.mark.parametrize('restart_config', [{'enabled': False}, {**CFG, 'ptm_build': '20261011-trk3200'}])
def test_B_card_alone_restart_latches_zero_through_real_can(live_startup, restart_config):
  h = live_startup
  first_card = h.card()
  controls, step = h.controls(first_card)
  for _ in range(250):
    before, _ = step()
  assert before.latActive and abs(before.actuators.torque) > 0.1
  original_raw = h.store['CarParams']
  new_card = h.card(restart_config)
  if not restart_config['enabled']:
    assert new_card.CI.CC.params.STEER_MAX == 8000
    assert h.store['CarParams'] != original_raw
  else:
    assert h.store['CarParams'] == original_raw  # record-only mismatch must also be caught
  h.now[0] += 1.01
  for _ in range(20):
    command, state = step()
    assert not command.latActive and command.actuators.torque == 0.0 and not state.active
    cc = new_card.CI.CC
    cc.frame = 1
    _, messages = cc.update(command.as_reader(), structs.CarControlSP(), NS(out=car.CarState.new_message(), v_cruise_factor=1.0), 0)
    e4 = next(dat for addr, dat, bus in messages if addr == 0xE4)
    assert int.from_bytes(e4[:2], 'big', signed=True) == 0 and not e4[2] & 0x80
  assert any('restart controlsd' in message for message in h.errors)
  # Restoring a matching record never unlatches a running controller.
  activation.publish_activation(original_raw, CFG, h.record)
  h.store['CarParams'] = original_raw
  h.now[0] += 6.0
  assert not step()[0].latActive
  assert sum('restart controlsd' in message for message in h.errors) >= 2


def test_B_runtime_guard_checks_disk_at_most_once_per_second(live_startup, monkeypatch):
  h = live_startup
  controls, step = h.controls(h.card())
  reads = []
  original = h.Params.get

  def get(self, key, *a, **kw):
    reads.append(key)
    return original(self, key, *a, **kw)

  monkeypatch.setattr(h.Params, 'get', get)
  file_reads = []
  original_read = Path.read_text

  def read_text(path, *args, **kwargs):
    if path == h.record:
      file_reads.append(path)
    return original_read(path, *args, **kwargs)

  monkeypatch.setattr(Path, 'read_text', read_text)
  for frame in range(100):
    h.now[0] = 100.0 + frame * 0.01
    step()
  assert reads.count('CarParams') == 1
  assert len(file_reads) == 1


def test_C_exact_gate_lists_ecu_results_in_card_and_inspector(live_startup):
  from openpilot.tools.lateral.inspect_h020 import build_report

  h = live_startup
  captured = []

  def incomplete(cp):
    cp.carFw = [*[fw.to_dict() for fw in cp.carFw], {'ecu': 'vsa', 'address': 0x18DA28F1, 'brand': 'honda', 'fwVersion': b'UNKNOWN-VSA'}]
    cp.fingerprintSource = 'can'
    cp.fuzzyFingerprint = True
    captured.append(cp)

  with pytest.raises(activation.H020ActivationError) as error:
    h.card(mutate=incomplete)
  message = str(error.value)
  assert 'eps@0x18da30f1=matched' in message and 'vsa@0x18da28f1=mismatch' in message
  assert 'fwdRadar@0x18dab0f1=missing' in message
  cp = captured[0]
  raw = cp.to_bytes()
  report = build_report(cp, raw, h.Params(), CFG, h.record)
  assert any(message == blocker for blocker in report['blockers'])
  states = {(row['ecu'], row['address']): row['status'] for row in report['firmware_match']['ecus']}
  assert states[('eps', '0x18da30f1')] == 'matched'
  assert states[('vsa', '0x18da28f1')] == 'mismatch'
  assert states[('fwdRadar', '0x18dab0f1')] == 'missing'


@pytest.mark.parametrize('command', [-0.5, 0.5])
def test_D_real_honda_sign_chain_and_press_detector(command):
  from opendbc.car import Bus
  from opendbc.car.honda.carstate import CarState
  from opendbc.can import CANPacker
  from openpilot.selfdrive.controls.lib.honda_eps_h020_override import get_eps_modified_steering_pressed

  cp, sp = real_params()
  cc = CarController(DBC[CAR.HONDA_CIVIC_BOSCH], cp, sp)
  request = car.CarControl.new_message(enabled=True, latActive=True)
  request.actuators.torque = command
  cc.frame = 1
  cc.last_torque = command
  _, messages = cc.update(request.as_reader(), structs.CarControlSP(), NS(out=car.CarState.new_message(), v_cruise_factor=1.0), 0)
  e4 = next(data for addr, data, bus in messages if addr == 0xE4)
  wire_command = int.from_bytes(e4[:2], 'big', signed=True)
  assert wire_command == -command * 3840
  cs = CarState(cp, sp)
  parsers = cs.get_can_parsers(cp, sp)
  cs.update(parsers)  # res lazily registers the signals it consumes
  packer = CANPacker(DBC[cp.carFingerprint][Bus.pt])
  # "Same direction" means raw sensor and raw E4 signs agree. This is a sign convention,
  # not a claim that a physical H020's command-induced reaction torque was measured.
  # Both DBC sensor factor -1 and output -> E4 sign -1 normalize that to CS.torque * u > 0.
  for same_direction in [True, False]:
    raw_sensor = wire_command if same_direction else -wire_command
    sensor = packer.make_can_msg('STEER_STATUS', parsers[Bus.pt].bus, {'STEER_TORQUE_SENSOR': -raw_sensor})
    assert int.from_bytes(sensor[1][:2], 'big', signed=True) == raw_sensor
    parsers[Bus.pt].update([(10000000, [sensor])])
    state, _ = cs.update(parsers)
    assert state.steeringTorque == -raw_sensor and state.steeringPressed
    elapsed, pressed = get_eps_modified_steering_pressed(state.steeringPressed, state.steeringTorque, command, 0.0, False)
    assert pressed is (not same_direction)
    assert elapsed == (0.01 if same_direction else 1.0)


@pytest.mark.parametrize('kind', ['builder', 'reader'])
def test_E_load_activation_requires_original_bytes_without_serializing(tmp_path, kind):
  import warnings

  cp, _ = real_params()
  raw = cp.to_bytes()
  record = tmp_path / 'record.json'
  activation.publish_activation(raw, CFG, record)
  with car.CarParams.from_bytes(raw) as reader, warnings.catch_warnings(record=True) as emitted:
    warnings.simplefilter('always')
    obj = cp if kind == 'builder' else reader
    with pytest.raises(TypeError, match='cp_bytes'):
      activation.load_activation(obj, path=record)
    assert activation.load_activation(obj, raw, record) == CFG
    assert activation.load_activation(obj, raw, record) == CFG
    assert not emitted


def test_C_report_agrees_with_real_exact_matcher_optional_and_logging_rules():
  from opendbc.car.fw_versions import build_fw_dict, match_fw_to_car_exact
  from opendbc.car.honda.fingerprints import FW_VERSIONS
  from opendbc.car.fw_query_definitions import ECU_NAME
  from openpilot.selfdrive.controls.lib.honda_eps_h020_fingerprint import firmware_match_report

  cp, _ = real_params()
  cp.carFw = [
    {
      'ecu': ECU_NAME[ecu],
      'address': address,
      'subAddress': subaddress or 0,
      'brand': 'honda',
      'fwVersion': b'39990-TEA,H020\0\0' if ECU_NAME[ecu] == 'eps' else versions[0],
    }
    for (ecu, address, subaddress), versions in FW_VERSIONS[CAR.HONDA_CIVIC_BOSCH].items()
    if ECU_NAME[ecu] != 'vsa'
  ]
  report = firmware_match_report(cp)
  vsa = next(row for row in report['ecus'] if row['ecu'] == 'vsa')
  assert vsa['status'] == 'missing' and not vsa['required_when_missing']
  assert CAR.HONDA_CIVIC_BOSCH in match_fw_to_car_exact(build_fw_dict(cp.carFw, 'honda'), match_brand='honda', log=False)
  cp.carFw = [*[fw.to_dict() for fw in cp.carFw], {'ecu': 'vsa', 'address': 0x18DA28F1, 'brand': 'honda', 'fwVersion': b'BAD', 'logging': True}]
  assert next(row for row in firmware_match_report(cp)['ecus'] if row['ecu'] == 'vsa')['status'] == 'missing'
  cp.carFw[-1].logging = False
  assert next(row for row in firmware_match_report(cp)['ecus'] if row['ecu'] == 'vsa')['status'] == 'mismatch'
  assert CAR.HONDA_CIVIC_BOSCH not in match_fw_to_car_exact(build_fw_dict(cp.carFw, 'honda'), match_brand='honda', log=False)


def test_A_stock_reflash_with_stale_enabled_config_and_running_controls(live_startup):
  h = live_startup
  controls, step = h.controls(h.card())
  for _ in range(250):
    before, _ = step()
  assert before.latActive
  stock = h.card(CFG, b'39990-TEA-H020\0\0')
  assert list(stock.CP.lateralParams.torqueBP) == [0, 4096]
  assert any('ignoring' in message for message in h.errors)
  h.now[0] += 1.01
  assert not step()[0].latActive
  fresh, _ = h.controls(stock)
  assert not isinstance(fresh.LaC, LatControlHondaEps)


def test_A_conflicting_h020_eps_is_not_an_ordinary_fallback(live_startup):
  def conflicting(cp):
    cp.carFw = [*[fw.to_dict() for fw in cp.carFw], {'ecu': 'eps', 'address': 0x18DA30F2, 'fwVersion': b'39990-TEA-H020\0\0', 'brand': 'honda'}]

  with pytest.raises(activation.H020ActivationError, match='conflicting EPS'):
    live_startup.card(mutate=conflicting)


@pytest.mark.parametrize('failure', ['missing-record', 'corrupt-record', 'missing-carparams'])
def test_B_missing_or_corrupt_runtime_state_latches(live_startup, failure):
  h = live_startup
  controls, step = h.controls(h.card())
  assert step()[0].latActive
  if failure == 'missing-record':
    h.record.unlink()
  elif failure == 'corrupt-record':
    h.record.write_text('bad-json')
  else:
    h.store.pop('CarParams')
  h.now[0] += 1.01
  command, state = step()
  assert not command.latActive and command.actuators.torque == 0.0 and not state.active
  assert h.errors


def test_B_identical_card_restart_preserves_matching_controller(live_startup):
  h = live_startup
  controls, step = h.controls(h.card())
  before = h.store['CarParams']
  assert step()[0].latActive
  h.card()
  assert h.store['CarParams'] == before
  h.now[0] += 1.01
  assert step()[0].latActive and not h.errors


REVB_CFG = {**CFG, 'ptm_build': '20261022b-tgg-claritylimits-trk4250'}
REVB_FW = b'39990-TEA,H02B\0\0'


@pytest.mark.parametrize('tracker', [3200, 4250])
def test_revb_real_startup_selects_matching_profile_and_can(live_startup, tracker):
  from openpilot.selfdrive.controls.lib.honda_eps_calibrations import H020_REVB
  from openpilot.tools.lateral.inspect_h020 import build_report

  h = live_startup
  config = {**REVB_CFG, 'ptm_build': f'20261022b-tgg-claritylimits-trk{tracker}'}
  card = h.card(config, REVB_FW)
  assert card.CI.CC.params.STEER_MAX == 3840 and not card.CP.dashcamOnly
  controls, step = h.controls(card)
  assert controls.LaC.calibration is H020_REVB
  assert controls.LaC.core.ff.cal is H020_REVB
  for _ in range(250):
    command, state = step()
  assert command.latActive and state.active and abs(command.actuators.torque) > 0.1
  cc = card.CI.CC
  cc.frame = 1
  cc.last_torque = command.actuators.torque
  _, messages = cc.update(command.as_reader(), structs.CarControlSP(), NS(out=car.CarState.new_message(), v_cruise_factor=1.0), 0)
  e4 = next(data for addr, data, bus in messages if addr == 0xE4)
  assert int.from_bytes(e4[:2], 'big', signed=True) == int(-command.actuators.torque * 3840)
  report = build_report(card.CP, h.store['CarParams'], h.Params(), config, h.record)
  assert report['controller_selected'] and report['provenance']['profile'] == H020_REVB.name
  assert report['provenance']['build']['tracker'] == tracker


@pytest.mark.parametrize('config,version', [(CFG, REVB_FW), (REVB_CFG, b'39990-TEA,H020\0\0')])
def test_revb_wrong_firmware_family_cannot_activate(live_startup, config, version):
  with pytest.raises(activation.H020ActivationError, match='build does not match'):
    live_startup.card(config, version)
  assert 'CarParams' not in live_startup.store


@pytest.mark.parametrize('config', [None, {'enabled': False}, {**REVB_CFG, 'ptm_build': 'unknown'}])
def test_revb_unconfigured_image_is_passive(live_startup, config):
  h = live_startup
  card = h.card(config, REVB_FW)
  assert card.CP.dashcamOnly  # unique new image must never run the legacy H020 map/controller
  controls, _ = h.controls(card)
  assert not isinstance(controls.LaC, LatControlHondaEps)


@pytest.mark.parametrize('config,version,wrong_config', [(REVB_CFG, REVB_FW, CFG), (CFG, b'39990-TEA,H020\0\0', REVB_CFG)])
def test_revb_matching_cp_bytes_do_not_excuse_wrong_profile_record(tmp_path, config, version, wrong_config):
  cp, _ = real_params(config, version)
  raw = cp.to_bytes()
  record = tmp_path / 'activation.json'
  activation.publish_activation(raw, wrong_config, record)
  with pytest.raises(activation.H020ActivationError, match='build does not match'):
    activation.load_activation(cp, raw, record)


@pytest.mark.parametrize('new_config,new_version', [
  ({**REVB_CFG, 'ptm_build': '20261022b-tgg-claritylimits-trk3200'}, REVB_FW),
  (CFG, b'39990-TEA,H020\0\0'),
  ({'enabled': False}, REVB_FW),
])
def test_revb_card_restart_latches_zero_and_requires_controlsd_restart(live_startup, new_config, new_version):
  h = live_startup
  controls, step = h.controls(h.card(REVB_CFG, REVB_FW))
  for _ in range(250):
    command, _ = step()
  assert command.latActive and abs(command.actuators.torque) > 0.1
  card = h.card(new_config, new_version)
  h.now[0] += 1.01
  for _ in range(20):
    command, state = step()
    assert not command.latActive and command.actuators.torque == 0 and not state.active
    cc = card.CI.CC
    cc.frame = 1
    _, messages = cc.update(command.as_reader(), structs.CarControlSP(), NS(out=car.CarState.new_message(), v_cruise_factor=1.0), 0)
    e4 = next(data for addr, data, bus in messages if addr == 0xE4)
    assert int.from_bytes(e4[:2], 'big', signed=True) == 0 and not e4[2] & 0x80
  assert any('restart controlsd' in message for message in h.errors)


def test_revb_conflicting_new_and_old_eps_responses_are_refused(live_startup):
  def conflict(cp):
    cp.carFw = [*[fw.to_dict() for fw in cp.carFw], {'ecu': 'eps', 'address': 0x18DA30F2, 'fwVersion': b'39990-TEA,H020\0\0', 'brand': 'honda'}]

  with pytest.raises(activation.H020ActivationError, match='conflicting EPS'):
    live_startup.card(REVB_CFG, REVB_FW, mutate=conflict)


def test_revb_modified_id_only_and_full_exact_match_still_required(live_startup):
  from opendbc.sunnypilot.car.honda.fingerprints_ext import FW_VERSIONS_EXT

  versions = FW_VERSIONS_EXT[CAR.HONDA_CIVIC_BOSCH][(car.CarParams.Ecu.eps, 0x18DA30F1, None)]
  assert REVB_FW in versions and b'39990-TEA-H02B\0\0' not in versions
  with pytest.raises(activation.H020ActivationError, match='fresh, exact.*fwdRadar.*missing'):
    live_startup.card(REVB_CFG, REVB_FW, mutate=lambda cp: setattr(cp, 'fuzzyFingerprint', True))


@pytest.mark.parametrize('missing_radar', [False, True])
def test_revb_uses_real_exact_firmware_matcher_without_relaxing_ecus(missing_radar):
  from opendbc.car.fw_versions import build_fw_dict, match_fw_to_car_exact
  from opendbc.car.honda.fingerprints import FW_VERSIONS
  from opendbc.car.fw_query_definitions import ECU_NAME
  from openpilot.selfdrive.controls.lib.honda_eps_h020_fingerprint import firmware_match_report

  cp, _ = real_params(REVB_CFG, REVB_FW)
  cp.carFw = [
    {'ecu': ECU_NAME[ecu], 'address': address, 'subAddress': subaddress or 0, 'brand': 'honda',
     'fwVersion': REVB_FW if ECU_NAME[ecu] == 'eps' else versions[0]}
    for (ecu, address, subaddress), versions in FW_VERSIONS[CAR.HONDA_CIVIC_BOSCH].items()
    if not (missing_radar and ECU_NAME[ecu] == 'fwdRadar')
  ]
  matches = match_fw_to_car_exact(build_fw_dict(cp.carFw, 'honda'), match_brand='honda', log=False)
  assert (CAR.HONDA_CIVIC_BOSCH in matches) is (not missing_radar)
  report = firmware_match_report(cp)
  assert next(row for row in report['ecus'] if row['ecu'] == 'eps')['status'] == 'matched'
  if missing_radar:
    radar = next(row for row in report['ecus'] if row['ecu'] == 'fwdRadar')
    assert radar['status'] == 'missing' and radar['required_when_missing']
