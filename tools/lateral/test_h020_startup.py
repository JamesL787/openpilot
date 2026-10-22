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
  assert activation.load_activation(cp, path=tmp_path / 'missing') == {'enabled': False}


@pytest.mark.parametrize('tune', ['old-prototype', 'overwritten-torque'])
def test_stale_port_map_cannot_fall_back_without_record(tmp_path, tune):
  cp, _ = real_params()
  if tune == 'old-prototype':
    cp.lateralTuning.pid.kpBP, cp.lateralTuning.pid.kpV = [[0.0], [0.03]]
  else:
    CarInterface.configure_torque_tune(cp.carFingerprint, cp.lateralTuning)
  with pytest.raises(activation.H020ActivationError):
    activation.load_activation(cp, path=tmp_path / 'missing')


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
    cloudlog=NS(info=lambda *a: None),
    messaging=NS(log_from_bytes=lambda *a: cp, SubMaster=lambda *a, **k: None, PubMaster=lambda *a: None),
    car=car,
    load_activation=load,
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
